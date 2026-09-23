"""Unit tests for the x402 client (`docs/backlog.md`, "Spend is enforced,
but nothing speaks x402").

Payloads here are shaped exactly as the reference implementation
(github.com/coinbase/x402, `python/x402/schemas/`) produces them — V1 in a
JSON body, V2 base64-encoded in a `PAYMENT-REQUIRED` header — not simplified
or guessed, because a parser tested against an invented shape proves nothing
about a real 402 response.

What is not tested here, on purpose: signing or submitting a payment. This
module does not do that (see its own docstring for why), so there is nothing
of that kind to verify.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest

from causalmesh.adapters.x402 import (
    X402Error,
    decide_payment,
    parse_payment_required,
    resource_for,
)
from causalmesh.policy import Contract, Gate, Resource, ResourceKind

pytestmark = pytest.mark.unit

NOW = 1_000_000


@pytest.fixture
def contract() -> Contract:
    return Contract.from_dict(
        {
            "version": 1,
            "roles": [
                {
                    "agent_id": "buyer",
                    "archetype": "spender",
                    "allow": ["api.vendor.io"],
                    "budget": {"usd_total": "5.00", "usd_per_call": "1.00"},
                },
            ],
            "policy": {"arm": "C3"},
        }
    )


def gate_for(contract: Contract, **kwargs) -> Gate:
    return Gate(contract, run_id="run_x402", **kwargs)


def v1_body(*, amount: str = "50000", pay_to: str = "api.vendor.io", **overrides) -> bytes:
    entry = {
        "scheme": "exact",
        "network": "base-sepolia",
        "maxAmountRequired": amount,
        "resource": "https://api.vendor.io/data",
        "payTo": pay_to,
        "asset": "USDC",
        "maxTimeoutSeconds": 60,
    }
    entry.update(overrides)
    return json.dumps({"x402Version": 1, "accepts": [entry]}).encode("utf-8")


def v2_header(*, amount: str = "50000", pay_to: str = "api.vendor.io", **overrides) -> str:
    entry = {
        "scheme": "exact",
        "network": "eip155:8453",
        "asset": "USDC",
        "amount": amount,
        "payTo": pay_to,
        "maxTimeoutSeconds": 60,
    }
    entry.update(overrides)
    payload = {"x402Version": 2, "accepts": [entry]}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


class TestParsingV1:
    def test_a_real_shaped_v1_body_parses(self) -> None:
        parsed = parse_payment_required(headers={}, body=v1_body())
        assert parsed.x402_version == 1
        assert len(parsed.accepts) == 1
        requirement = parsed.accepts[0]
        assert requirement.scheme == "exact"
        assert requirement.network == "base-sepolia"
        assert requirement.pay_to == "api.vendor.io"
        assert requirement.amount == Decimal("50000")

    def test_amount_is_decimal_not_float(self) -> None:
        # A float on the wire ("maxAmountRequired": 0.5) would be rejected,
        # the same rule Resource.spend already enforces at its own call site.
        body = json.dumps(
            {
                "x402Version": 1,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "base-sepolia",
                        "maxAmountRequired": 0.5,
                        "resource": "https://api.vendor.io/data",
                        "payTo": "api.vendor.io",
                        "asset": "USDC",
                        "maxTimeoutSeconds": 60,
                    }
                ],
            }
        ).encode("utf-8")
        with pytest.raises(X402Error):
            parse_payment_required(headers={}, body=body)

    def test_a_missing_field_is_a_located_error(self) -> None:
        body = json.dumps(
            {"x402Version": 1, "accepts": [{"scheme": "exact", "network": "base-sepolia"}]}
        ).encode("utf-8")
        with pytest.raises(X402Error):
            parse_payment_required(headers={}, body=body)

    def test_an_unsupported_version_is_rejected(self) -> None:
        body = json.dumps({"x402Version": 3, "accepts": [{}]}).encode("utf-8")
        with pytest.raises(X402Error):
            parse_payment_required(headers={}, body=body)

    def test_no_header_and_no_body_is_rejected(self) -> None:
        with pytest.raises(X402Error):
            parse_payment_required(headers={}, body=None)

    def test_an_empty_accepts_list_is_rejected(self) -> None:
        body = json.dumps({"x402Version": 1, "accepts": []}).encode("utf-8")
        with pytest.raises(X402Error):
            parse_payment_required(headers={}, body=body)


class TestParsingV2:
    def test_a_real_shaped_v2_header_parses(self) -> None:
        header = v2_header()
        parsed = parse_payment_required(headers={"PAYMENT-REQUIRED": header}, body=None)
        assert parsed.x402_version == 2
        requirement = parsed.accepts[0]
        assert requirement.amount == Decimal("50000")
        assert requirement.pay_to == "api.vendor.io"

    def test_header_matching_is_case_insensitive(self) -> None:
        header = v2_header()
        parsed = parse_payment_required(headers={"payment-required": header}, body=None)
        assert parsed.x402_version == 2

    def test_the_v2_header_is_preferred_over_a_body(self) -> None:
        # A server capable of the header form is assumed to be answering in
        # it, matching the reference implementation's own precedence.
        header = v2_header(amount="1")
        parsed = parse_payment_required(
            headers={"PAYMENT-REQUIRED": header}, body=v1_body(amount="999999")
        )
        assert parsed.x402_version == 2
        assert parsed.accepts[0].amount == Decimal("1")

    def test_malformed_base64_is_a_located_error(self) -> None:
        with pytest.raises(X402Error):
            parse_payment_required(headers={"PAYMENT-REQUIRED": "not-base64!!"}, body=None)


class TestResourceFor:
    def test_produces_a_spend_resource_the_gate_understands(self) -> None:
        parsed = parse_payment_required(headers={}, body=v1_body())
        resource = resource_for(parsed.accepts[0])
        assert resource.kind is ResourceKind.SPEND
        assert resource.amount == Decimal("50000")


class TestDecidePayment:
    def test_an_allowed_requirement_is_allowed(self, contract: Contract) -> None:
        parsed = parse_payment_required(headers={}, body=v1_body(amount="0.50"))
        decision = decide_payment(parsed, gate=gate_for(contract), agent_id="buyer", now_us=NOW)
        assert decision.allowed
        assert decision.requirement.pay_to == "api.vendor.io"

    def test_a_ceiling_refusal_is_reported_with_its_rule(self, contract: Contract) -> None:
        parsed = parse_payment_required(headers={}, body=v1_body(amount="5000000"))
        decision = decide_payment(parsed, gate=gate_for(contract), agent_id="buyer", now_us=NOW)
        assert decision.refused
        assert decision.verdict.rule == "ceiling"

    def test_an_unallowlisted_destination_is_refused(self, contract: Contract) -> None:
        parsed = parse_payment_required(headers={}, body=v1_body(pay_to="evil.io", amount="0.10"))
        decision = decide_payment(parsed, gate=gate_for(contract), agent_id="buyer", now_us=NOW)
        assert decision.refused
        assert decision.verdict.rule == "allowlist"

    def test_nothing_is_recorded_by_deciding(self, contract: Contract) -> None:
        """Like Gate.check itself, this is a read. Only an operator who goes
        on to actually pay records the spend, and only afterward."""
        parsed = parse_payment_required(headers={}, body=v1_body(amount="0.50"))
        gate = gate_for(contract)
        decide_payment(parsed, gate=gate, agent_id="buyer", now_us=NOW)
        assert gate.spent(
            agent_id="buyer", resource=Resource.spend(to="api.vendor.io", amount="0.50")
        ) == Decimal(0)

    def test_the_first_allowed_option_wins_when_several_are_offered(
        self, contract: Contract
    ) -> None:
        body = json.dumps(
            {
                "x402Version": 1,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "base-sepolia",
                        "maxAmountRequired": "5000000",  # over ceiling
                        "resource": "https://api.vendor.io/data",
                        "payTo": "api.vendor.io",
                        "asset": "USDC",
                        "maxTimeoutSeconds": 60,
                    },
                    {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "maxAmountRequired": "0.10",  # within ceiling
                        "resource": "https://api.vendor.io/data",
                        "payTo": "api.vendor.io",
                        "asset": "USDC",
                        "maxTimeoutSeconds": 60,
                    },
                ],
            }
        ).encode("utf-8")
        parsed = parse_payment_required(headers={}, body=body)
        decision = decide_payment(parsed, gate=gate_for(contract), agent_id="buyer", now_us=NOW)
        assert decision.allowed
        assert decision.requirement.network == "eip155:8453"

    def test_the_last_refusal_is_reported_when_nothing_is_payable(self, contract: Contract) -> None:
        body = json.dumps(
            {
                "x402Version": 1,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "base-sepolia",
                        "maxAmountRequired": "5000000",
                        "resource": "https://api.vendor.io/data",
                        "payTo": "api.vendor.io",
                        "asset": "USDC",
                        "maxTimeoutSeconds": 60,
                    },
                    {
                        "scheme": "exact",
                        "network": "eip155:8453",
                        "maxAmountRequired": "0.10",
                        "resource": "https://evil.io/data",
                        "payTo": "evil.io",
                        "asset": "USDC",
                        "maxTimeoutSeconds": 60,
                    },
                ],
            }
        ).encode("utf-8")
        parsed = parse_payment_required(headers={}, body=body)
        decision = decide_payment(parsed, gate=gate_for(contract), agent_id="buyer", now_us=NOW)
        assert decision.refused
        # Both refuse; the second (last) is what is reported.
        assert decision.requirement.network == "eip155:8453"
        assert decision.verdict.rule == "allowlist"
