"""Coding agents: the provider-neutral interface and the mock implementation.

Spec §8 and §9. MockAgent is mandatory and implemented; model-backed
adapters are deferred and tracked in `docs/backlog.md` rather than stubbed,
because an unused stub with no consumer is worse than an honest absence
(§92, §93).
"""

from __future__ import annotations

from .base import AgentContext, AgentIdentity, CodingAgent, TurnResult
from .mock import MockAgent, MockAgentCrashError
from .script import (
    Action,
    ActionKind,
    AgentScript,
    Scenario,
    ScriptError,
    parse_duration_us,
)

__all__ = [
    "Action",
    "ActionKind",
    "AgentContext",
    "AgentIdentity",
    "AgentScript",
    "CodingAgent",
    "MockAgent",
    "MockAgentCrashError",
    "Scenario",
    "ScriptError",
    "TurnResult",
    "parse_duration_us",
]
