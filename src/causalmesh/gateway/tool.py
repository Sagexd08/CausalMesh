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

``mutating`` defaults to ``True``: a tool is gated unless it is declared
read-only.  Skipping the gate has to be a statement someone made, not the
result of a forgotten argument.

What the gate is asked about is declared, never inferred:

- ``resource_args`` names the arguments that carry the resource.
- ``resource_kind`` says what they are: ``"path"`` (the default), ``"endpoint"``
  (a host or URL), ``"spend"`` (a destination that money goes to) or
  ``"budget"`` (the name of a consumable allowance).
- ``amount_arg`` names the argument carrying the amount, required for
  ``spend`` and ``budget`` and refused for the others.

A tool that declares no resources is checked against nothing and runs: the
contract states exceptions, so a call it names nothing about is not refused.
``mutating=False`` skips the gate altogether, for every kind, so a read-only
tool that reaches a network is not held to an endpoint allowlist.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from causalmesh.policy.resource import ResourceKind

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
    mutating: bool = True
    resource_args: list[str] = field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    resource_kind: str = "path"
    amount_arg: str | None = None
    unit: str = ""
    spend_on_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool.name must be a non-empty string")
        if not callable(self.handler):
            raise TypeError(f"Tool.handler must be callable, got {type(self.handler).__name__}")
        self.name = self.name.strip()
        self._validate_resource_declaration()

    def _validate_resource_declaration(self) -> None:
        """Refuse a declaration that could not be enforced, at registration.

        Each of these would otherwise surface on the first call, or worse,
        never: a spend tool with no amount would simply not be checked.
        """
        try:
            kind = ResourceKind(self.resource_kind)
        except ValueError:
            known = ", ".join(sorted(member.value for member in ResourceKind))
            raise ValueError(
                f"Tool {self.name!r}: unknown resource_kind {self.resource_kind!r}; "
                f"known kinds: {known}"
            ) from None
        self.resource_kind = kind.value
        consumable = kind in (ResourceKind.SPEND, ResourceKind.BUDGET)
        if consumable and not self.amount_arg:
            raise ValueError(
                f"Tool {self.name!r}: resource_kind={kind.value!r} needs amount_arg, "
                "the name of the argument carrying the amount"
            )
        if not consumable and self.amount_arg is not None:
            raise ValueError(
                f"Tool {self.name!r}: amount_arg only applies to spend and budget tools"
            )
        if kind is not ResourceKind.PATH and not self.resource_args:
            raise ValueError(
                f"Tool {self.name!r}: resource_kind={kind.value!r} needs resource_args, "
                "or nothing would be checked"
            )
        if self.spend_on_error and not consumable:
            raise ValueError(
                f"Tool {self.name!r}: spend_on_error only applies to spend and budget tools"
            )
        if consumable and not self.mutating:
            raise ValueError(
                f"Tool {self.name!r}: a {kind.value} tool cannot be mutating=False, "
                "because that skips the gate and the amount would go unchecked"
            )

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
