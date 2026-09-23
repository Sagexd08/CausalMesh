"""The policy plane: what agents may do, and who says so.

Three pieces, in the order a decision moves through them:

- `Contract` — the declared rules, read from `causalmesh.yaml`. Written by a
  person; never inferred from what agents did.
- `Gate` — consults the contract and returns a `Verdict`: allowed or refused,
  with the reason a person will read months later.
- `Ledger` — what has already been consumed, recorded across processes so a
  budget holds when several agents share it.

The type that makes this one plane rather than three is `Resource`. A refused
write and a refused payment are the same event — a gate consulting declared
authority, denying, and recording the denial — so they are the same type, and
the enforcement plane does not know or care which kind it just refused.
"""

from __future__ import annotations

from causalmesh.policy.checkpoints import (
    AutoDenyHandler,
    CheckpointDecision,
    CheckpointHandler,
    ScriptedHandler,
    evaluate_checkpoints,
)
from causalmesh.policy.contract import Checkpoint, Contract, ContractError, Role
from causalmesh.policy.gate import Gate, Verdict
from causalmesh.policy.ledger import Entry, Ledger
from causalmesh.policy.resource import Resource, ResourceError, ResourceKind

__all__ = [
    "AutoDenyHandler",
    "Checkpoint",
    "CheckpointDecision",
    "CheckpointHandler",
    "Contract",
    "ContractError",
    "Entry",
    "Gate",
    "Ledger",
    "Resource",
    "ResourceError",
    "ResourceKind",
    "Role",
    "ScriptedHandler",
    "Verdict",
    "evaluate_checkpoints",
]
