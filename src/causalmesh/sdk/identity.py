"""Lightweight agent identity for the SDK.

The SDK needs an ``EventIdentity`` to stamp events that flow into the
relay.  This module provides a minimal helper that builds one without
exposing the internal ``EventIdentity`` dataclass to public callers.

For Phase 1 the experiment id, task id, and arm come from the contract
(or sensible defaults).  A future phase can extend this to carry real
experimental identity.
"""

from __future__ import annotations

from causalmesh.events.schema import EventIdentity
from causalmesh.policy.contract import Contract

__all__ = ["make_identity"]

_SDK_EXPERIMENT_ID = "sdk-run"
_SDK_TASK_ID = "sdk-task"


def make_identity(agent_id: str, *, contract: Contract, run_id: str) -> EventIdentity:
    """Build an ``EventIdentity`` for one SDK-managed agent.

    ``experiment_id`` and ``task_id`` use stable SDK defaults so the
    event schema validation passes.  The ``arm`` comes from the contract
    so evidence correctly reflects the active policy arm.
    """
    return EventIdentity(
        experiment_id=_SDK_EXPERIMENT_ID,
        task_id=_SDK_TASK_ID,
        run_id=run_id,
        agent_id=agent_id,
        arm=contract.arm,
    )
