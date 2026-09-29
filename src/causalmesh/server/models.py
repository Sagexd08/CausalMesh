from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ExecuteRequest(BaseModel):
    agent_id: str
    arguments: dict[str, Any] = {}


class ToolMeta(BaseModel):
    name: str
    kind: str
    mutating: bool
    description: str


class ToolListResponse(BaseModel):
    tools: list[ToolMeta]


class ExecuteResponse(BaseModel):
    allowed: bool
    executed: bool
    denied: bool
    failed: bool
    tool: str
    agent_id: str
    event_id: str | None
    recorded: bool
    reason: str
    rule: str
    audit_error: str | None
    would_refuse: bool
    # What the handler returned, when it ran and the value is JSON-encodable.
    # `value_omitted` says why it is absent otherwise. Additive: a client that
    # ignores both behaves as it did before.
    value: Any = None
    value_omitted: str | None = None
