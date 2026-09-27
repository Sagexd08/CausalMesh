"""Developer-friendly result wrapper for a gateway tool call.

``GatewayResult`` is the object callers receive from ``mesh.execute()``.
It wraps the internal ``ToolResult`` (from ``causalmesh.hooks.lifecycle``)
and exposes a clean surface:

    result.allowed   → True / False
    result.denied    → True / False
    result.executed  → True / False (allowed *and* succeeded)
    result.failed    → True / False (allowed but handler raised)
    result.reason    → human-readable string
    result.rule      → which policy rule fired (ownership / budget / …)
    result.tool      → tool name
    result.agent_id  → agent that made the call
    result.value     → return value of the handler (None when denied/failed)
    result.event_id  → audit identifier when available

A denial prints a message a developer can act on::

    Action denied.

    Agent: coding-agent
    Tool:  write_file
    Path:  production/database.sql
    Rule:  ownership
    Reason: 'production/database.sql' is owned by 'dba', not 'coding-agent'
"""

from __future__ import annotations

from typing import Any

from causalmesh.hooks.lifecycle import ToolOutcome

__all__ = ["GatewayResult"]


class GatewayResult:
    """The outcome of one ``mesh.execute()`` call.

    Wraps the internal ``ToolResult`` so callers never have to import from
    ``causalmesh.hooks``.  The original ``ToolResult`` is available as
    ``.raw`` for callers that need lower-level access.
    """

    def __init__(
        self,
        raw: ToolResult,
        *,
        event_id: str | None = None,
    ) -> None:
        self._raw = raw
        self._event_id = event_id

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    @property
    def raw(self) -> ToolResult:
        """The underlying internal ``ToolResult`` (advanced use)."""
        return self._raw

    @property
    def tool(self) -> str:
        return self._raw.call.tool

    @property
    def agent_id(self) -> str:
        return self._raw.call.agent_id

    @property
    def allowed(self) -> bool:
        """True when the gate permitted the call (executed or failed)."""
        return self._raw.outcome != ToolOutcome.DENIED

    @property
    def denied(self) -> bool:
        """True when the gate refused the call before the handler ran."""
        return self._raw.outcome == ToolOutcome.DENIED

    @property
    def executed(self) -> bool:
        """True when the handler completed without raising."""
        return self._raw.outcome == ToolOutcome.EXECUTED

    @property
    def failed(self) -> bool:
        """True when the gate allowed but the handler raised an exception."""
        return self._raw.outcome == ToolOutcome.FAILED

    @property
    def value(self) -> Any:
        """Return value from the handler, or ``None`` when denied/failed."""
        return self._raw.value

    @property
    def reason(self) -> str:
        """Human-readable explanation of the outcome."""
        if self.denied and self._raw.decision:
            return self._raw.decision.reason
        if self.failed and self._raw.error:
            return self._raw.error
        if self.executed:
            return "allowed"
        return ""

    @property
    def rule(self) -> str:
        """Which policy rule fired, or empty string when allowed."""
        if self._raw.decision:
            return self._raw.decision.rule
        return ""

    @property
    def blocked_path(self) -> str | None:
        """The path that triggered a denial, when applicable."""
        if self._raw.decision:
            return self._raw.decision.blocked_path
        return None

    @property
    def holder(self) -> str | None:
        """Agent that holds the conflicting claim, when applicable."""
        if self._raw.decision:
            return self._raw.decision.holder_agent
        return None

    @property
    def event_id(self) -> str | None:
        """Audit / event identifier for this call, when available."""
        return self._event_id

    @property
    def duration_us(self) -> int:
        """How long the handler ran, in microseconds (0 when denied)."""
        return self._raw.duration_us

    # ------------------------------------------------------------------ #
    # Human-readable output                                               #
    # ------------------------------------------------------------------ #

    def describe(self) -> str:
        """A denial notice that a developer can read and act on.

        For allowed calls returns a one-liner.
        """
        if self.executed:
            return f"Allowed. Agent: {self.agent_id}  Tool: {self.tool}"
        if self.failed:
            return (
                f"Tool execution failed.\n\n"
                f"Agent: {self.agent_id}\n"
                f"Tool:  {self.tool}\n"
                f"Error: {self.reason}"
            )
        # Denied
        lines = [
            "Action denied.\n",
            f"Agent: {self.agent_id}",
            f"Tool:  {self.tool}",
        ]
        if self.blocked_path:
            lines.append(f"Path:  {self.blocked_path}")
        if self.rule:
            lines.append(f"Rule:  {self.rule}")
        lines.append(f"Reason: {self.reason}")
        if self.holder:
            lines.append(f"Holder: {self.holder}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        status = "executed" if self.executed else ("denied" if self.denied else "failed")
        return f"<GatewayResult tool={self.tool!r} agent={self.agent_id!r} status={status!r}>"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "allowed": self.allowed,
            "blocked_path": self.blocked_path,
            "denied": self.denied,
            "duration_us": self.duration_us,
            "event_id": self.event_id,
            "executed": self.executed,
            "failed": self.failed,
            "holder": self.holder,
            "reason": self.reason,
            "rule": self.rule,
            "tool": self.tool,
        }


# Convenience alias — GatewayResult IS the public ToolResult for SDK users
ToolResult = GatewayResult
