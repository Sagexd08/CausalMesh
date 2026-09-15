"""The gate: one decision point for every kind of resource.

**What this is.** Given a declared contract and a resource an agent wants to
act on, the gate answers allow or refuse, and says why. It is the enforcement
plane of the framework, and it is deliberately the narrowest possible thing:
a pure function of contract plus current state, returning a verdict.

**Why the verdict is data, not an exception.** The claim registry already
established this and the reason is the same here: a refusal is the primary
measurement, so it must be recorded with its reason rather than thrown for
each call site to decide what to log. `ClaimOutcome` made that choice for
paths; `Verdict` makes it for every kind.

**What the gate does not do.** It does not write to the chain, does not touch
the registry's tables directly, and does not decide whether an action was
*attempted*. Those are the caller's, because the distinction between "asked
speculatively" and "really tried" is exactly what `may_write` and
`record_denial` keep apart in the registry — and merging them would make
denial counts depend on how often the gate was consulted.

**Budgets are checked against spend already recorded, never against a
running total held in memory.** An in-process counter would be wrong the
moment two agent processes shared a budget, which is the case the whole
project exists to handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from causalmesh.policy.resource import Resource, ResourceKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from causalmesh.claims.registry import ClaimRegistry
    from causalmesh.policy.contract import Contract

__all__ = ["Gate", "Verdict"]


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the gate decided, and why.

    `reason` is written to be read by a person in a terminal: it names the
    resource, the rule that fired, and the holder or limit involved. It ends
    up verbatim in the signed chain, so it is the sentence someone reads when
    they ask months later why an action did not happen.
    """

    allowed: bool
    resource: Resource
    reason: str
    rule: str = ""
    holder: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "detail": self.detail,
            "holder": self.holder,
            "reason": self.reason,
            "resource": self.resource.to_dict(),
            "rule": self.rule,
        }


class Gate:
    """Consults a contract, and allows or refuses.

    One gate serves one run. It holds the contract and, when enforcement is
    active, the claim registry that makes exclusivity real across processes.

    `enforcing=False` is the C0/C1/C2 case: the gate still evaluates and still
    reports what it *would* have done, but always allows. That is what lets
    the C2 -> C3 contrast isolate enforcement — the same code path runs in
    both arms, and only the verdict differs.
    """

    def __init__(
        self,
        contract: Contract,
        *,
        run_id: str,
        registry: ClaimRegistry | None = None,
        enforcing: bool = True,
    ) -> None:
        self.contract = contract
        self.run_id = run_id
        self.registry = registry
        self.enforcing = enforcing

    # -- the decision ------------------------------------------------------

    def check(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict:
        """Decide whether this agent may act on this resource. Read-only.

        Records nothing. A caller that actually performed the action, or was
        actually stopped, reports that separately — see the module docstring.
        """
        verdict = self._evaluate(agent_id=agent_id, resource=resource, now_us=now_us)

        if verdict.refused and not self.enforcing:
            # The arm has information but no enforcement. The gate still
            # reached a verdict — that is what makes the counterfactual
            # measurable — but it does not act on it. `would_refuse` carries
            # the shadow verdict so an unenforced arm can still report what
            # enforcement would have cost it.
            return Verdict(
                allowed=True,
                resource=resource,
                reason=f"not enforcing; would have refused: {verdict.reason}",
                rule=verdict.rule,
                holder=verdict.holder,
                detail={**verdict.detail, "would_refuse": True},
            )
        return verdict

    def _evaluate(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict:
        """The rules, in the order they are allowed to refuse.

        Ordered cheapest and most specific first: a declaration the operator
        wrote by hand outranks a lease acquired at run time, because an agent
        should be told "you do not own this" rather than "someone else is
        currently editing it" when both are true.
        """
        for rule in (
            self._rule_ownership,
            self._rule_allowlist,
            self._rule_ceiling,
            self._rule_budget,
            self._rule_claim,
        ):
            verdict = rule(agent_id=agent_id, resource=resource, now_us=now_us)
            if verdict is not None and verdict.refused:
                return verdict

        return Verdict(
            allowed=True,
            resource=resource,
            reason="no rule refuses this",
            rule="default-allow",
        )

    # -- rules -------------------------------------------------------------
    #
    # Each returns a refusing Verdict, or None meaning "nothing to say".
    # None rather than an allowing verdict so the caller above can tell
    # "this rule permitted it" from "this rule did not apply".

    def _rule_ownership(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict | None:
        """Declared ownership. Paths only, and only where someone owns it.

        A path nobody declared is not refused: the contract states exceptions,
        not an exhaustive map of the repository. Refusing everything
        undeclared would make adoption a rewrite, and the framework's claim is
        that you keep your agent and change the substrate.
        """
        if resource.kind is not ResourceKind.PATH:
            return None
        owner = self.contract.owner_of(resource.name)
        if owner is None or owner == agent_id:
            return None
        return Verdict(
            allowed=False,
            resource=resource,
            reason=f"{resource.name!r} is owned by {owner!r}, not {agent_id!r}",
            rule="ownership",
            holder=owner,
        )

    def _rule_allowlist(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict | None:
        """Where an agent may send money or traffic.

        Applies only when the role declares an allowlist. An absent allowlist
        means unrestricted, which is the right default for a substrate people
        adopt incrementally — and `causalmesh init` writes one, so the
        permissive case is the un-configured one rather than the chosen one.
        """
        if resource.kind not in (ResourceKind.SPEND, ResourceKind.ENDPOINT):
            return None
        allowed = self.contract.allowlist_for(agent_id)
        if allowed is None:
            return None
        host = resource.to_dict()["name"]
        if _host_allowed(host, allowed):
            return None
        return Verdict(
            allowed=False,
            resource=resource,
            reason=f"{host!r} is not in the allowlist for {agent_id!r}",
            rule="allowlist",
            detail={"allowed": sorted(allowed)},
        )

    def _rule_ceiling(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict | None:
        """The most one call may cost.

        Separate from the total budget because they fail differently: a total
        catches a slow drain, a ceiling catches one catastrophic call. A
        system with only a total discovers the mistake after it has been made.
        """
        if resource.kind is not ResourceKind.SPEND or resource.amount is None:
            return None
        ceiling = self.contract.per_call_ceiling(agent_id)
        if ceiling is None or resource.amount <= ceiling:
            return None
        return Verdict(
            allowed=False,
            resource=resource,
            reason=(
                f"{resource.describe()} exceeds the per-call ceiling "
                f"of {ceiling:f} for {agent_id!r}"
            ),
            rule="ceiling",
            detail={"ceiling": f"{ceiling:f}", "requested": f"{resource.amount:f}"},
        )

    def _rule_budget(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict | None:
        """The total an agent may consume over the run.

        Checked against what the ledger has already recorded rather than an
        in-memory tally, because agents run as separate processes and a
        per-process counter would let each one spend the whole budget.
        """
        if resource.kind not in (ResourceKind.SPEND, ResourceKind.BUDGET):
            return None
        if resource.amount is None:
            return None
        limit = self.contract.budget_for(agent_id, resource)
        if limit is None:
            return None
        spent = self.spent(agent_id=agent_id, resource=resource)
        if spent + resource.amount <= limit:
            return None
        return Verdict(
            allowed=False,
            resource=resource,
            reason=(
                f"{resource.describe()} would take {agent_id!r} to "
                f"{spent + resource.amount:f} against a limit of {limit:f}"
            ),
            rule="budget",
            detail={
                "limit": f"{limit:f}",
                "requested": f"{resource.amount:f}",
                "spent": f"{spent:f}",
            },
        )

    def _rule_claim(self, *, agent_id: str, resource: Resource, now_us: int) -> Verdict | None:
        """An exclusive lease another agent currently holds.

        The measured case, unchanged. Delegates to the registry rather than
        reimplementing exclusivity: the registry's `BEGIN IMMEDIATE`
        transaction is what makes the invariant hold across processes, and a
        second implementation here would be a second chance to get it wrong.
        """
        if self.registry is None:
            return None
        if resource.kind not in (ResourceKind.PATH, ResourceKind.SPEND):
            return None
        outcome = self.registry.may_write(
            path=resource.identity, agent_id=agent_id, run_id=self.run_id, now_us=now_us
        )
        if outcome.granted:
            return None
        holder = outcome.holder
        return Verdict(
            allowed=False,
            resource=resource,
            reason=outcome.reason,
            rule="claim",
            holder=holder.agent_id if holder else None,
        )

    # -- ledger ------------------------------------------------------------

    def spent(self, *, agent_id: str, resource: Resource) -> Decimal:
        """What this agent has already consumed of this resource's allowance.

        Zero without a ledger. That is the honest answer rather than a
        failure: a gate with no ledger cannot enforce a total, and saying so
        by allowing is better than refusing everything on missing data. The
        caller wires a ledger when totals matter.
        """
        ledger = getattr(self, "_ledger", None)
        if ledger is None:
            return Decimal(0)
        total: Decimal = ledger.total(agent_id=agent_id, resource=resource)
        return total

    def attach_ledger(self, ledger: Any) -> None:
        """Give the gate a record of what has already been consumed."""
        self._ledger = ledger


def _host_allowed(host: str, allowed: set[str]) -> bool:
    """Whether a host matches an allowlist entry.

    An entry matches the host itself or any subdomain of it, so
    `example.com` covers `api.example.com` without the operator listing every
    subdomain. Matching is on label boundaries: `notexample.com` must not be
    covered by `example.com`, and a naive `endswith` would let it through —
    which is a real way an allowlist silently fails open.
    """
    # A destination may carry a path or port; the allowlist is about hosts.
    bare = host.split("/", 1)[0].split(":", 1)[0]
    return any(bare == entry or bare.endswith(f".{entry}") for entry in allowed)
