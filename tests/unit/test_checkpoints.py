"""`policy.checkpoints`: human-in-the-loop rules, evaluated synchronously.

`CheckpointHandler` is a plain callback so the gate stays synchronous end to
end -- no new concurrency model, and a scripted handler keeps a checkpointed
run reproducible the same way a scripted mock agent does.
"""

from __future__ import annotations

import pytest

from causalmesh.policy.checkpoints import (
    AutoDenyHandler,
    CheckpointDecision,
    ScriptedHandler,
    evaluate_checkpoints,
)
from causalmesh.policy.contract import Checkpoint
from causalmesh.policy.resource import Resource

pytestmark = pytest.mark.unit

NOW = 1_000_000


class TestNoMatchingCheckpoint:
    def test_none_when_the_contract_has_no_checkpoints(self) -> None:
        decision = evaluate_checkpoints(
            (),
            agent_id="buyer",
            resource=Resource.path("src/a.py"),
            handler=AutoDenyHandler(),
            now_us=NOW,
        )
        assert decision is None

    def test_none_when_on_does_not_match_the_resource_kind(self) -> None:
        checkpoints = (Checkpoint(on="spend", require="human"),)
        decision = evaluate_checkpoints(
            checkpoints,
            agent_id="buyer",
            resource=Resource.path("src/a.py"),
            handler=AutoDenyHandler(),
            now_us=NOW,
        )
        assert decision is None

    def test_none_when_when_does_not_match(self) -> None:
        checkpoints = (Checkpoint(on="spend", when={"usd": ">0.50"}, require="human"),)
        resource = Resource.spend(to="api.example.com", amount="0.10")
        decision = evaluate_checkpoints(
            checkpoints, agent_id="buyer", resource=resource, handler=AutoDenyHandler(), now_us=NOW
        )
        assert decision is None


class TestAutoDenyHandler:
    def test_denies_every_matching_checkpoint(self) -> None:
        checkpoints = (Checkpoint(on="spend", require="human"),)
        resource = Resource.spend(to="api.example.com", amount="1.00")
        decision = evaluate_checkpoints(
            checkpoints, agent_id="buyer", resource=resource, handler=AutoDenyHandler(), now_us=NOW
        )
        assert decision is not None
        assert decision.approved is False
        assert decision.checkpoint is checkpoints[0]

    def test_the_reason_names_the_absent_handler(self) -> None:
        checkpoints = (Checkpoint(on="spend", require="human"),)
        resource = Resource.spend(to="api.example.com", amount="1.00")
        decision = evaluate_checkpoints(
            checkpoints, agent_id="buyer", resource=resource, handler=AutoDenyHandler(), now_us=NOW
        )
        assert decision is not None
        assert "no checkpoint handler" in decision.reason.lower()


class TestScriptedHandler:
    def test_returns_the_scripted_answer_in_order(self) -> None:
        checkpoints = (Checkpoint(on="spend", require="human"),)
        resource = Resource.spend(to="api.example.com", amount="1.00")
        handler = ScriptedHandler([True])
        decision = evaluate_checkpoints(
            checkpoints, agent_id="buyer", resource=resource, handler=handler, now_us=NOW
        )
        assert decision is not None
        assert decision.approved is True

    def test_exhausting_the_script_is_an_error_not_a_silent_deny(self) -> None:
        checkpoints = (Checkpoint(on="spend", require="human"),)
        resource = Resource.spend(to="api.example.com", amount="1.00")
        handler = ScriptedHandler([])
        with pytest.raises(RuntimeError, match="exhausted"):
            evaluate_checkpoints(
                checkpoints, agent_id="buyer", resource=resource, handler=handler, now_us=NOW
            )


class TestWhenMatching:
    @pytest.mark.parametrize(
        ("operator", "threshold", "amount", "expected_match"),
        [
            (">", "0.50", "1.00", True),
            (">", "0.50", "0.50", False),
            (">=", "0.50", "0.50", True),
            ("<", "5.00", "1.00", True),
            ("<", "5.00", "5.00", False),
            ("<=", "5.00", "5.00", True),
            ("==", "1.00", "1.00", True),
            ("==", "1.00", "1.01", False),
        ],
    )
    def test_usd_comparisons(
        self, operator: str, threshold: str, amount: str, expected_match: bool
    ) -> None:
        checkpoints = (
            Checkpoint(on="spend", when={"usd": f"{operator}{threshold}"}, require="human"),
        )
        resource = Resource.spend(to="api.example.com", amount=amount)
        decision = evaluate_checkpoints(
            checkpoints, agent_id="buyer", resource=resource, handler=AutoDenyHandler(), now_us=NOW
        )
        assert (decision is not None) is expected_match

    def test_a_malformed_when_clause_raises_rather_than_silently_never_matching(self) -> None:
        checkpoints = (Checkpoint(on="spend", when={"usd": "not-an-expression"}, require="human"),)
        resource = Resource.spend(to="api.example.com", amount="1.00")
        with pytest.raises(ValueError, match="usd"):
            evaluate_checkpoints(
                checkpoints,
                agent_id="buyer",
                resource=resource,
                handler=AutoDenyHandler(),
                now_us=NOW,
            )


class TestCheckpointDecisionShape:
    def test_serializes_for_the_chain(self) -> None:
        checkpoint = Checkpoint(on="spend", when={"usd": ">0.50"}, require="human")
        resource = Resource.spend(to="api.example.com", amount="1.00")
        decision = CheckpointDecision(
            approved=True, checkpoint=checkpoint, resource=resource, reason="approved by human"
        )
        payload = decision.to_dict()
        assert payload["approved"] is True
        assert payload["checkpoint"]["on"] == "spend"
        assert payload["resource"]["identity"] == resource.identity
        assert payload["reason"] == "approved by human"
