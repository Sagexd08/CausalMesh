"""Tool abstraction for the CausalMesh gateway.

A ``Tool`` wraps an arbitrary Python callable with metadata the gateway
needs to route calls through the policy layer:

- ``name``     — the identifier callers use in ``mesh.execute(tool=...)``
- ``handler``  — the callable that performs the work
- ``kind``     — a human-readable category (e.g. ``"filesystem"``)
- ``mutating`` — whether the call may change external state

``mutating=True`` means the ``LifecycleBoundary`` will consult the gate
*before* invoking the handler.  A denied mutating call never reaches the
handler — that invariant is enforced by the boundary, not by this class.

``mutating=False`` calls still pass through the boundary (for recording)
but are allowed unconditionally by the gate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Tool"]


@dataclass
class Tool:
    """One developer-registered tool.

    Example::

        Tool(
            name="write_file",
            handler=write_file,
            kind="filesystem",
            mutating=True,
        )
    """

    name: str
    handler: Callable[..., Any]
    kind: str = "generic"
    mutating: bool = False
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool.name must be a non-empty string")
        if not callable(self.handler):
            raise TypeError(f"Tool.handler must be callable, got {type(self.handler).__name__}")
        self.name = self.name.strip()

    def __call__(self, **arguments: Any) -> Any:
        """Invoke the underlying handler with keyword arguments."""
        return self.handler(**arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "kind": self.kind,
            "mutating": self.mutating,
            "name": self.name,
        }
