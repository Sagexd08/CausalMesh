"""x402: the client half of "the gate sits at 'agent pays'" (docs/FRAMEWORK-PLAN.md).

The x402 flow is: agent requests -> server answers `HTTP 402` with payment
instructions -> agent forms a payment -> server verifies -> access granted.
`docs/backlog.md`'s "Spend is enforced, but nothing speaks x402" names the
gap this module closes: `policy.gate.Gate` already decides allow or refuse
on a `Resource.spend`; nothing yet reads a real 402 challenge into one.

**What this module does not do.** It does not sign a payment, does not hold
a wallet or a private key, and does not make the HTTP request itself. Actually
paying needs a signer for one of x402's payment schemes and networks — a
real dependency this project has never carried and AGENTS.md gates adding
without a reason that survives "what does this cost a person installing the
package." This module is the part that is genuinely this project's job: turn
a 402 into the `Resource` the gate already understands, ask it, and hand back
a typed decision. An operator's own payment code makes the actual transfer
when the decision allows it, and records it to the `Ledger` afterward — the
same "the caller records what it actually did" discipline `policy/ledger.py`
already documents.

**Versions.** Verified against the reference implementation
(github.com/coinbase/x402, `python/x402/schemas/`), not written from memory:

- **V1 (legacy, still widely deployed):** the 402 response's JSON *body* is
  `{"x402Version": 1, "accepts": [...], "error": ...}`, each entry shaped
  `{"scheme", "network", "maxAmountRequired", "resource", "payTo",
  "asset", "maxTimeoutSeconds", ...}`. The client retries with an
  `X-PAYMENT` header.
- **V2 (current):** the requirements travel in a `PAYMENT-REQUIRED` response
  *header*, base64-encoded JSON shaped `{"x402Version": 2, "accepts": [...]}`
  with each entry `{"scheme", "network", "asset", "amount", "payTo",
  "maxTimeoutSeconds", ...}` — `amount` replacing V1's `maxAmountRequired`.
  The client retries with a `PAYMENT-SIGNATURE` header.

Both are parsed into the same `PaymentRequirement`, because the gate does not
care which wire version asked — only what and how much.

**Paying.** The operator-facing orchestration (a `PaymentSigner` protocol the
operator implements, reserve-then-commit ledger recording, idempotency) lives
in `adapters/x402_pay.py`; this module stays the parse-and-decide half.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ..policy.gate import Gate, Verdict
from ..policy.resource import Resource

__all__ = [
    "PaymentDecision",
    "PaymentRequired",
    "PaymentRequirement",
    "X402Error",
    "decide_payment",
    "parse_payment_required",
    "resource_for",
]

PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"
PAYMENT_RESPONSE_HEADER = "PAYMENT-RESPONSE"
X_PAYMENT_HEADER = "X-PAYMENT"
X_PAYMENT_RESPONSE_HEADER = "X-PAYMENT-RESPONSE"


class X402Error(ValueError):
    """A 402 response could not be read as a payment challenge."""


@dataclass(frozen=True, slots=True)
class PaymentRequirement:
    """One accepted way to pay, independent of which x402 version asked.

    Amounts are `Decimal`, not `str` or `float`: this is the same money
    this project's `Resource.spend` and `Ledger` already carry as `Decimal`
    end to end, and a payment amount converted through `float` on the way in
    would defeat that the moment it arrived.
    """

    scheme: str
    network: str
    asset: str
    amount: Decimal
    pay_to: str
    max_timeout_seconds: int | None = None
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": f"{self.amount:f}",
            "asset": self.asset,
            "extra": self.extra,
            "max_timeout_seconds": self.max_timeout_seconds,
            "network": self.network,
            "pay_to": self.pay_to,
            "scheme": self.scheme,
        }


@dataclass(frozen=True, slots=True)
class PaymentRequired:
    """A parsed 402 challenge: every way the server said it would accept payment."""

    x402_version: int
    accepts: tuple[PaymentRequirement, ...]
    error: str | None = None


def _to_decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise X402Error(f"{field_name} must not be a float; the wire value should be a string")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise X402Error(f"{field_name} is not a valid amount: {value!r}") from exc


def _requirement_from_v1(entry: dict[str, Any]) -> PaymentRequirement:
    try:
        return PaymentRequirement(
            scheme=entry["scheme"],
            network=entry["network"],
            asset=entry["asset"],
            amount=_to_decimal(entry["maxAmountRequired"], field_name="maxAmountRequired"),
            pay_to=entry["payTo"],
            max_timeout_seconds=entry.get("maxTimeoutSeconds"),
            extra=entry.get("extra"),
        )
    except KeyError as exc:
        raise X402Error(f"V1 payment requirement is missing field {exc}") from exc


def _requirement_from_v2(entry: dict[str, Any]) -> PaymentRequirement:
    try:
        return PaymentRequirement(
            scheme=entry["scheme"],
            network=entry["network"],
            asset=entry["asset"],
            amount=_to_decimal(entry["amount"], field_name="amount"),
            pay_to=entry["payTo"],
            max_timeout_seconds=entry.get("maxTimeoutSeconds"),
            extra=entry.get("extra"),
        )
    except KeyError as exc:
        raise X402Error(f"V2 payment requirement is missing field {exc}") from exc


def _decode_v2_header(header_value: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(header_value.encode("ascii"), validate=True)
        return json.loads(decoded.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - every failure here is one malformed-header report
        raise X402Error(
            f"{PAYMENT_REQUIRED_HEADER} header is not valid base64 JSON: {exc}"
        ) from exc


def parse_payment_required(
    *, headers: dict[str, str], body: bytes | dict[str, Any] | None = None
) -> PaymentRequired:
    """Parse a 402 response into a version-independent `PaymentRequired`.

    Headers are matched case-insensitively, the way HTTP headers actually
    compare — a server sending `payment-required` rather than
    `PAYMENT-REQUIRED` is still a V2 response.

    Prefers the V2 header when present, matching the reference
    implementation's own precedence (`x402HTTPClientBase.get_payment_required_response`):
    a server capable of the header form is assumed to be answering in it.
    """
    normalized_headers = {key.upper(): value for key, value in headers.items()}

    header_value = normalized_headers.get(PAYMENT_REQUIRED_HEADER)
    if header_value:
        data = _decode_v2_header(header_value)
        return _parse_body(data)

    if body is not None:
        if isinstance(body, bytes):
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise X402Error(f"402 response body is not valid JSON: {exc}") from exc
        else:
            data = body
        return _parse_body(data)

    raise X402Error(
        f"no {PAYMENT_REQUIRED_HEADER} header and no body; nothing to parse as a 402 challenge"
    )


def _parse_body(data: dict[str, Any]) -> PaymentRequired:
    if not isinstance(data, dict):
        raise X402Error(f"a payment-required payload must be a mapping, got {type(data).__name__}")
    version = data.get("x402Version")
    if version not in (1, 2):
        raise X402Error(f"unsupported x402Version {version!r}; this client speaks 1 and 2")

    raw_accepts = data.get("accepts")
    if not isinstance(raw_accepts, list) or not raw_accepts:
        raise X402Error("payment-required payload has no non-empty 'accepts' list")

    parser = _requirement_from_v1 if version == 1 else _requirement_from_v2
    accepts = tuple(parser(entry) for entry in raw_accepts)
    return PaymentRequired(x402_version=version, accepts=accepts, error=data.get("error"))


def resource_for(requirement: PaymentRequirement) -> Resource:
    """The `Resource.spend` this project's gate already knows how to judge.

    `to` is `pay_to`, the destination the money actually moves to — the same
    identity an allowlist rule and a budget are declared against, and the
    one that must match for either to mean anything.
    """
    return Resource.spend(to=requirement.pay_to, amount=requirement.amount, unit=requirement.asset)


@dataclass(frozen=True, slots=True)
class PaymentDecision:
    """What the gate decided about one accepted way to pay, and why.

    Carries the `PaymentRequirement` the verdict was reached against — not
    just the resource identity — so an operator's own payment code has
    everything it needs to actually pay (`network`, `scheme`,
    `max_timeout_seconds`) without re-parsing the original challenge.
    """

    allowed: bool
    requirement: PaymentRequirement
    verdict: Verdict

    @property
    def refused(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requirement": self.requirement.to_dict(),
            "verdict": self.verdict.to_dict(),
        }


def decide_payment(
    payment_required: PaymentRequired, *, gate: Gate, agent_id: str, now_us: int
) -> PaymentDecision:
    """Ask the gate about the first accepted requirement it allows.

    x402 lets a server accept several ways to pay; this asks the gate about
    each in the order the server listed them and returns the first it
    allows, or the *last* refusal if the gate refuses all of them — the most
    informative single verdict to report when nothing was payable, since it
    reflects the option the server itself listed last (commonly the
    fallback or default in server implementations that order accepts by
    preference).

    This is a read: like `Gate.check` itself, nothing is recorded here. A
    caller that goes on to actually pay records the spend on the ledger
    afterward, once the transfer is real — never before, and never for a
    requirement the gate refused.
    """
    if not payment_required.accepts:
        raise X402Error("payment_required has no accepted requirements to decide between")

    decisions = []
    for requirement in payment_required.accepts:
        resource = resource_for(requirement)
        verdict = gate.check(agent_id=agent_id, resource=resource, now_us=now_us)
        decision = PaymentDecision(
            allowed=verdict.allowed, requirement=requirement, verdict=verdict
        )
        if verdict.allowed:
            return decision
        decisions.append(decision)

    return decisions[-1]
