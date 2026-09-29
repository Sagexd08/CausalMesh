"""The policy plane, wired into the run loop.

`ClaimGate` in `gates.py` enforces one thing: an exclusive lease on a path.
That is what the experiment measures, and it stays exactly as it is, because
changing it would change what the measured C3 results mean.

This gate does something wider. It consults a declared contract, so a call
can be refused for owning, for an allowlist, for a per-call ceiling, for an
exhausted budget, *or* for a live lease. It satisfies the same `Gate`
protocol, so installing it is a substitution rather than a new code path
through the boundary.

**Why both exist.** The experiment's contrast is C2 against C3, and that
contrast is only clean if the two arms differ by one factor. `ClaimGate` is
that factor. A contract that also refuses on ownership would be a second
difference, and the measurement would stop isolating enforcement. So the
narrow gate remains the one the arms install, and this one is what an
operator installs when they are running work rather than running an
experiment.

**Leases are the registry's, not this gate's.** The policy gate's own
`claim` rule consults the registry through `may_write`, so exclusivity keeps
coming from the `BEGIN IMMEDIATE` transaction that makes it hold across
processes. What this gate adds is the *recording*: `may_write` answers a
question and writes nothing, so a refusal here has to write the denial or
the enforcement count stays at zero however much was blocked.

**Every refusal is recorded once.** The distinction the claim registry draws
between asking (`may_write`) and being stopped (`record_denial`) holds here
too: this gate is only called when a tool call actually reaches the
boundary, so a refusal here is a blocked write rather than a question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from causalmesh.hooks.lifecycle import GateDecision, ToolCall
from causalmesh.policy import Contract, Gate as PolicyGate, Resource, Verdict
from causalmesh.policy.resource import ResourceError

if TYPE_CHECKING:
    from causalmesh.claims.registry import ClaimRegistry
    from causalmesh.policy.checkpoints import CheckpointHandler

__all__ = ["ContractGate"]


@dataclass
class ContractGate:
    """Refuse a mutating call that the contract does not permit.

    Satisfies the `Gate` protocol in `lifecycle.py`, so the lifecycle
    boundary installs it the same way it installs `AllowAllGate` or
    `ClaimGate` and knows nothing about which it got.
    """

    policy: PolicyGate
    registry: ClaimRegistry | None = None
    verdicts: list[Verdict] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        contract: Contract,
        *,
        run_id: str,
        registry: ClaimRegistry | None = None,
        enforcing: bool = True,
        ledger: object | None = None,
        checkpoint_handler: CheckpointHandler | None = None,
        require_ledger: bool = False,
    ) -> ContractGate:
        """Assemble a gate from a contract, and a registry when there is one.

        `enforcing=False` produces a gate that evaluates every rule and
        allows anyway, recording what it would have refused. That is how an
        unenforced arm reports the counterfactual: what enforcement would
        have cost it, without paying the cost.
        """
        policy = PolicyGate(
            contract,
            run_id=run_id,
            registry=registry,
            enforcing=enforcing,
            checkpoint_handler=checkpoint_handler,
            require_ledger=require_ledger,
        )
        if ledger is not None:
            policy.attach_ledger(ledger)

        return cls(policy=policy, registry=registry if enforcing else None)

    def check(self, call: ToolCall, now_us: int) -> GateDecision:
        """Decide whether this call may proceed.

        Paths are checked in the order the call lists them, and the first
        refusal stops the call. A partially applied multi-path operation
        would leave the workspace in a state no event describes, which is
        the same reasoning `ClaimGate` records.
        """
        # Paths first, in the order the call lists them, then any other
        # resource the call declared (`Tool(resource_kind=...)`). The harness's
        # own `ToolCall` carries no `resources`, so it sees paths only.
        named: list[tuple[str, Resource | None]] = [(path, None) for path in call.paths]
        named.extend((resource.identity, resource) for resource in getattr(call, "resources", ()))

        for label, declared in named:
            try:
                resource = declared if declared is not None else Resource.path(label)
            except ResourceError as exc:
                # A path that cannot be formed cannot be decided on. Refuse it as
                # data, like every other refusal, instead of raising past the gate.
                return GateDecision(
                    allowed=False,
                    reason=f"{label!r} is not a usable resource: {exc}",
                    blocked_path=label,
                    rule="malformed",
                )
            verdict = self.policy.check(agent_id=call.agent_id, resource=resource, now_us=now_us)
            self.verdicts.append(verdict)
            if not verdict.refused:
                continue

            if verdict.rule == "claim" and self.registry is not None:
                holder = self.registry.check(
                    path=resource.identity, run_id=self.policy.run_id, now_us=now_us
                )
                self.registry.record_denial(
                    path=resource.identity,
                    requesting_agent=call.agent_id,
                    run_id=self.policy.run_id,
                    now_us=now_us,
                    holder=holder,
                    reason=verdict.reason,
                )

            return GateDecision(
                allowed=False,
                reason=verdict.reason,
                holder_agent=verdict.holder,
                blocked_path=label,
                rule=verdict.rule,
            )

        return GateDecision(allowed=True, reason="the contract permits this call")

    def refusals(self) -> list[Verdict]:
        """Every verdict that refused, in order."""
        return [verdict for verdict in self.verdicts if verdict.refused]

    def shadow_refusals(self) -> list[Verdict]:
        """What an unenforced gate would have refused.

        Empty when enforcing. On C0, C1 and C2 this is the measurement that
        makes the counterfactual visible: the rules ran, reached a verdict,
        and were not acted on.
        """
        return [verdict for verdict in self.verdicts if verdict.detail.get("would_refuse") is True]

    def to_dict(self) -> dict[str, Any]:
        """The gate's own record, for the run artifact."""
        return {
            "enforcing": self.policy.enforcing,
            "refusals": [verdict.to_dict() for verdict in self.refusals()],
            "shadow_refusals": [verdict.to_dict() for verdict in self.shadow_refusals()],
            "checks": len(self.verdicts),
        }
