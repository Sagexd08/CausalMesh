"""Resources: the one thing a gate can refuse.

**The idea this package exists for.** A refused write and a refused payment
are the same event. In both cases a gate consults declared authority, denies,
and records the denial with its reason. They differ in payload and in nothing
the substrate cares about. Writing that down as a type is what lets one
enforcement plane cover agents that edit files, agents that spend money, and
agents that run unattended.

So a `Resource` is a *kind* plus an *identifier*, and everything downstream —
claims, denials, the signed chain — handles it as one opaque normalized
string. That is not a new idea here so much as a recognition: the claim
registry already treats `path` as an opaque normalized string, which is
precisely why it can hold a lease on `pay:usdc/premium.unknown.io` without a
single change to its transactional core.

**Why kinds are a closed set.** An open one would let a typo
(`paymnt:...`) silently create a resource nobody holds and nobody refuses —
the same defect class as the enforcement bug in `docs/backlog.md`, where a
measurement reported a confident zero. A wrong kind must raise.

**Why identity is normalized here rather than at each call site.** `src/a.py`
and `src\\a.py` are one file; `API.Example.COM` and `api.example.com` are one
host. If two spellings of the same resource produce two claims, exclusivity
silently does not hold between them. The registry already normalizes paths;
this does the same job for the kinds it does not know about.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from causalmesh.events.canonical import normalize_text

__all__ = [
    "Resource",
    "ResourceError",
    "ResourceKind",
]


class ResourceKind(StrEnum):
    """What sort of thing is being claimed or refused.

    Closed deliberately. Each member names an action an agent takes that
    someone might have to answer for later.
    """

    PATH = "path"
    SPEND = "spend"
    ENDPOINT = "endpoint"
    BUDGET = "budget"


class ResourceError(ValueError):
    """A resource could not be formed from what was given."""


@dataclass(frozen=True, slots=True)
class Resource:
    """One thing an agent may act on, and a gate may refuse.

    `identity` is the canonical string the registry leases on. It is built
    once, here, so that every layer below agrees about what "the same
    resource" means.
    """

    kind: ResourceKind
    name: str
    amount: Decimal | None = None
    unit: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ResourceError(f"resource name must be a non-empty string, got {self.name!r}")
        if self.kind in (ResourceKind.SPEND, ResourceKind.BUDGET) and self.amount is None:
            raise ResourceError(f"{self.kind} resources require an amount")
        if self.amount is not None and self.amount < 0:
            raise ResourceError(f"amount must not be negative, got {self.amount}")

    @property
    def identity(self) -> str:
        """The canonical string this resource is leased and refused under.

        Prefixed by kind so two kinds can never collide: a file literally
        named `premium.unknown.io` is not the endpoint of the same name, and
        a registry that could not tell them apart would refuse the wrong one.
        """
        return f"{self.kind.value}:{_normalize_name(self.kind, self.name)}"

    def describe(self) -> str:
        """One line naming this resource the way an operator would say it."""
        if self.amount is None:
            return self.identity
        unit = f" {self.unit}" if self.unit else ""
        return f"{_format_amount(self.amount)}{unit} -> {_normalize_name(self.kind, self.name)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": _format_amount(self.amount) if self.amount is not None else None,
            "identity": self.identity,
            "kind": self.kind.value,
            "name": _normalize_name(self.kind, self.name),
            "unit": self.unit,
        }

    @classmethod
    def path(cls, name: str) -> Resource:
        """A file. The case the experiment measures."""
        return cls(kind=ResourceKind.PATH, name=name)

    @classmethod
    def spend(cls, *, to: str, amount: Decimal | str | int, unit: str = "USD") -> Resource:
        """Money leaving the operator's account, to one destination."""
        return cls(kind=ResourceKind.SPEND, name=to, amount=_to_decimal(amount), unit=unit)

    @classmethod
    def endpoint(cls, host: str) -> Resource:
        """A network destination."""
        return cls(kind=ResourceKind.ENDPOINT, name=host)

    @classmethod
    def budget(cls, *, name: str, amount: Decimal | str | int, unit: str = "") -> Resource:
        """A consumable allowance — tokens, seconds, bytes."""
        return cls(kind=ResourceKind.BUDGET, name=name, amount=_to_decimal(amount), unit=unit)

    @classmethod
    def parse(cls, identity: str) -> Resource:
        """Rebuild a resource from an identity string.

        Needed because the registry and the chain store the identity, not the
        object, and the TUI has to render a stored denial without the
        original call in hand. Round-trips with `identity` for every kind;
        amount is not carried, because the identity deliberately does not
        encode it — a lease is on the destination, not on one sum.
        """
        head, separator, tail = identity.partition(":")
        if not separator:
            raise ResourceError(f"not a resource identity: {identity!r}")
        try:
            kind = ResourceKind(head)
        except ValueError as exc:
            known = ", ".join(sorted(member.value for member in ResourceKind))
            raise ResourceError(f"unknown resource kind {head!r}; known kinds: {known}") from exc
        amount = Decimal(0) if kind in (ResourceKind.SPEND, ResourceKind.BUDGET) else None
        return cls(kind=kind, name=tail, amount=amount)


def _normalize_name(kind: ResourceKind, name: str) -> str:
    """Canonicalize a name for its kind.

    Paths unify separators; hosts and destinations fold case. Both are NFC
    normalized, because the same character can be typed two ways and two
    spellings of one resource would break exclusivity between them.
    """
    text = normalize_text(name.strip())
    if kind is ResourceKind.PATH:
        return text.replace("\\", "/")
    if kind in (ResourceKind.ENDPOINT, ResourceKind.SPEND):
        return text.lower()
    return text


def _to_decimal(amount: Decimal | str | int) -> Decimal:
    """Money and allowances as Decimal, never float.

    `Decimal(str(...))` for floats would launder a value that is already
    imprecise; a float is rejected outright so the imprecision is caught at
    the call site that introduced it rather than at the ledger that inherits
    it.
    """
    if isinstance(amount, float):
        raise ResourceError(
            "amount must not be a float; pass a Decimal or a string "
            f"(got {amount!r}, which is already imprecise)"
        )
    try:
        return Decimal(amount)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ResourceError(f"amount is not a number: {amount!r}") from exc


def _format_amount(amount: Decimal) -> str:
    """A stable decimal string.

    `normalize()` would render 2.40 as 2.4 and 100 as 1E+2, both of which
    are the same number and neither of which is what an operator expects to
    read in a ledger or match in a test.
    """
    return f"{amount:f}"
