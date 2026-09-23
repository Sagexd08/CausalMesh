"""The contract gate: the policy plane installed in the run loop.

The property under test is that `ContractGate` satisfies the same `Gate`
protocol as `ClaimGate`, so the lifecycle boundary installs one or the other
without knowing which it got. If that stops being true, enforcement becomes
a conditional inside the boundary and the arms stop differing by exactly one
installed object.

Two behaviours matter most and are tested directly:

- **Leases are delegated, not reimplemented.** The registry's transaction is
  what makes exclusivity hold across processes; a second implementation here
  would be a second chance to get it wrong.
- **An unenforced gate still reaches a verdict.** That is what makes the
  counterfactual measurable on C0, C1 and C2: the rules ran, decided, and
  were not acted on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.claims.registry import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.hooks.lifecycle import ToolCall
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy import Contract

pytestmark = [pytest.mark.unit]

NOW = 1_000_000


@pytest.fixture
def contract() -> Contract:
    return Contract.from_dict(
        {
            "version": 1,
            "roles": [
                {"agent_id": "agent_a", "owns": ["src/schema.py", "src/models/"]},
                {"agent_id": "agent_b", "owns": ["src/handlers/"]},
            ],
            "policy": {"arm": "C3"},
        }
    )


@pytest.fixture
def registry(tmp_path: Path) -> ClaimRegistry:
    with ClaimRegistry(tmp_path / "claims.db") as opened:
        yield opened


def write(agent: str, *paths: str) -> ToolCall:
    return ToolCall(tool="write_file", agent_id=agent, paths=paths)


class TestOwnership:
    def test_a_non_owner_is_refused(self, contract: Contract) -> None:
        gate = ContractGate.build(contract, run_id="r1")
        decision = gate.check(write("agent_b", "src/schema.py"), NOW)
        assert not decision.allowed
        assert decision.blocked_path == "src/schema.py"
        assert "agent_a" in decision.reason

    def test_the_owner_proceeds(self, contract: Contract) -> None:
        gate = ContractGate.build(contract, run_id="r1")
        assert gate.check(write("agent_a", "src/schema.py"), NOW).allowed

    def test_an_undeclared_path_is_not_refused(self, contract: Contract) -> None:
        """The contract states exceptions, not a map of the repository.

        Refusing everything undeclared would make adoption a rewrite.
        """
        gate = ContractGate.build(contract, run_id="r1")
        assert gate.check(write("agent_b", "README.md"), NOW).allowed

    def test_a_multi_path_call_stops_at_the_first_refusal(self, contract: Contract) -> None:
        """A partially applied operation leaves a state no event describes."""
        gate = ContractGate.build(contract, run_id="r1")
        decision = gate.check(write("agent_b", "README.md", "src/schema.py"), NOW)
        assert not decision.allowed
        assert decision.blocked_path == "src/schema.py"


class TestLeasesAreDelegated:
    def test_a_held_path_is_refused_through_the_registry(
        self, contract: Contract, registry: ClaimRegistry
    ) -> None:
        """Exclusivity comes from the registry, not from a copy of it here."""
        granted = registry.acquire(
            claim_id="k1",
            path="path:src/config.py",
            agent_id="agent_a",
            run_id="r1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        assert granted.granted

        gate = ContractGate.build(contract, run_id="r1", registry=registry)
        decision = gate.check(write("agent_b", "src/config.py"), NOW)
        assert not decision.allowed
        assert decision.holder_agent == "agent_a"

    def test_the_holder_proceeds(self, contract: Contract, registry: ClaimRegistry) -> None:
        registry.acquire(
            claim_id="k1",
            path="path:src/config.py",
            agent_id="agent_a",
            run_id="r1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        gate = ContractGate.build(contract, run_id="r1", registry=registry)
        assert gate.check(write("agent_a", "src/config.py"), NOW).allowed

    def test_a_blocked_write_is_recorded_as_a_denial(
        self, contract: Contract, registry: ClaimRegistry
    ) -> None:
        """A refusal the registry does not see is a measurement that reports zero.

        This is the defect class recorded in `docs/backlog.md`: enforcement
        working correctly while the counter said nothing had happened.
        """
        registry.acquire(
            claim_id="k1",
            path="path:src/config.py",
            agent_id="agent_a",
            run_id="r1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        gate = ContractGate.build(contract, run_id="r1", registry=registry)
        gate.check(write("agent_b", "src/config.py"), NOW)

        assert len(registry.denials(run_id="r1")) == 1

    def test_ownership_outranks_a_lease(self, contract: Contract, registry: ClaimRegistry) -> None:
        """ "You do not own this" is the more useful answer when both are true."""
        registry.acquire(
            claim_id="k1",
            path="path:src/schema.py",
            agent_id="agent_b",
            run_id="r1",
            now_us=NOW,
            duration_us=60_000_000,
        )
        gate = ContractGate.build(contract, run_id="r1", registry=registry)
        decision = gate.check(write("agent_c", "src/schema.py"), NOW)
        assert not decision.allowed
        # The ownership rule fired, not the claim rule.
        assert decision.holder_agent == "agent_a"


class TestTheCounterfactual:
    def test_an_unenforced_gate_allows_and_records_what_it_would_refuse(
        self, contract: Contract
    ) -> None:
        """C0, C1 and C2 run the same rules and do not act on them."""
        gate = ContractGate.build(contract, run_id="r1", enforcing=False)
        decision = gate.check(write("agent_b", "src/schema.py"), NOW)

        assert decision.allowed
        assert len(gate.shadow_refusals()) == 1
        assert gate.refusals() == []

    def test_an_enforcing_gate_has_no_shadow(self, contract: Contract) -> None:
        gate = ContractGate.build(contract, run_id="r1", enforcing=True)
        gate.check(write("agent_b", "src/schema.py"), NOW)

        assert len(gate.refusals()) == 1
        assert gate.shadow_refusals() == []


class TestTheRecord:
    def test_the_gate_reports_what_it_decided(self, contract: Contract) -> None:
        gate = ContractGate.build(contract, run_id="r1")
        gate.check(write("agent_a", "src/schema.py"), NOW)
        gate.check(write("agent_b", "src/schema.py"), NOW)

        record = gate.to_dict()
        assert record["checks"] == 2
        assert record["enforcing"] is True
        assert len(record["refusals"]) == 1
        # The reason survives into the record, because it is the sentence
        # someone reads months later when they ask why this did not happen.
        assert "owned by" in record["refusals"][0]["reason"]

    def test_it_satisfies_the_gate_protocol(self, contract: Contract) -> None:
        """The boundary installs one gate or another and knows nothing else.

        `Gate` is a Protocol rather than a base class, so the assertion is
        that the call signature and the return type match what the boundary
        already calls. If this drifts, enforcement becomes a conditional
        inside the boundary instead of an installed object, and the arms
        stop differing by exactly one thing.
        """
        import inspect

        from causalmesh.hooks.gates import ClaimGate
        from causalmesh.hooks.lifecycle import GateDecision

        gate = ContractGate.build(contract, run_id="r1")
        decision = gate.check(write("agent_a", "src/schema.py"), NOW)

        assert isinstance(decision, GateDecision)
        assert inspect.signature(ContractGate.check) == inspect.signature(ClaimGate.check)


class TestPolicyGateIdentity:
    """The signing identity a verdict event is attributed to.

    A verdict is reached by the policy plane, not by any agent in the run,
    so it needs its own signing identity rather than borrowing an agent's
    key — attributing it to an agent would misattribute provenance.
    """

    def test_policy_gate_key_is_deterministic(self) -> None:
        seed = b"causalmesh-test-seed-0000000001"
        a = KeyPair.derive(seed, "policy_gate")
        b = KeyPair.derive(seed, "policy_gate")
        assert a.public_key_hex == b.public_key_hex

    def test_policy_gate_key_differs_from_an_agent_key(self) -> None:
        seed = b"causalmesh-test-seed-0000000001"
        policy_key = KeyPair.derive(seed, "policy_gate")
        agent_key = KeyPair.derive(seed, "agent_a")
        assert policy_key.public_key_hex != agent_key.public_key_hex
