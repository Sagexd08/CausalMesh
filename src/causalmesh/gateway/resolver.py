"""Resource extraction from tool arguments.

Security-critical resources (paths, hosts, destinations, amounts) that the
policy gate uses to make ALLOW/DENY decisions **must** be declared explicitly
via ``Tool(resource_args=[...])``, with ``resource_kind`` and ``amount_arg``
where the resource is not a path.  Explicit declaration is the only way to
guarantee that the gate sees exactly the resources the handler will act on.

**The gate must see what the handler sees.**  The handler receives the raw
argument object.  The gate receives a string built from it.  If those can
differ, the gate is deciding about a different resource: a list of paths is
checked as one odd string, ``None`` as a file named ``"None"``, bytes as their
repr.  So a resource argument must be a ``str`` or an ``os.PathLike``, and
anything else is refused with :class:`~causalmesh.sdk.errors.InvalidResourceError`
before the handler runs.  Endpoint values that a URL parser and an HTTP client
could read differently (a backslash, whitespace, control characters) are
refused for the same reason.

Fallback behaviour
------------------
For tools registered without ``resource_args`` the resolver checks for a
``"path"`` key in the arguments and, if present, uses it as the sole
resource.  This fallback exists only for backward compatibility with callers
that pre-date Phase 1B and have not yet been updated.

.. deprecated::
    The ``"path"`` fallback is deprecated and will be removed in a future
    major release.  Set ``resource_args`` explicitly on every ``Tool`` that
    acts on a protected resource.  Tools that intentionally have *no*
    resource constraint should pass ``resource_args=[]`` (the default) and
    the resolver will return an empty tuple, which grants the gate no
    resource to check against.
"""

from __future__ import annotations

import os
import urllib.parse
import warnings
from decimal import Decimal, InvalidOperation
from typing import Any

from causalmesh.gateway.tool import Tool
from causalmesh.policy.resource import Resource, ResourceError, ResourceKind

__all__ = ["ResourceResolver"]


def _errors() -> Any:
    """`causalmesh.sdk.errors`, imported on use.

    `causalmesh.sdk` imports the gateway, which imports this module, so a
    module-level import here would be circular.
    """
    from causalmesh.sdk import errors

    return errors


# Characters an endpoint value may not contain: a URL parser and an HTTP client
# can disagree about where the host ends when they are present, and the
# allowlist has to see the host the request will connect to.
_ENDPOINT_FORBIDDEN = frozenset("\\ \t\r\n\x00")


class ResourceResolver:
    """Extracts security-critical resource declarations from tool arguments.

    Preferred usage::

        Tool(name="write_file", handler=..., resource_args=["path"])
        Tool(name="fetch", handler=..., resource_args=["url"], resource_kind="endpoint")
        Tool(
            name="pay", handler=..., resource_args=["to"],
            resource_kind="spend", amount_arg="usd",
        )

    If a declared argument is absent the call is refused with
    :class:`~causalmesh.sdk.errors.MissingResourceError`, and if it is present
    but unusable with :class:`~causalmesh.sdk.errors.InvalidResourceError`:
    it **fails closed**, never silently passes a resource check with a
    missing or malformed value.
    """

    def resolve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[str, ...]:
        """Extract declared *path* resources as a tuple of strings.

        Only ``resource_kind="path"`` tools yield anything here; the other
        kinds are :meth:`resolve_resources`.

        Args:
            tool:       The ``Tool`` definition.
            arguments:  The arguments provided for this invocation.

        Returns:
            A tuple of path strings in the same order as
            ``tool.resource_args``, exactly as the caller spelled them.
            Empty tuple when no resources are declared *and* no ``"path"``
            fallback applies.

        Raises:
            MissingResourceError: When a declared ``resource_args`` name is
                absent from ``arguments``.  The call is not executed.
            InvalidResourceError: When a declared value is not a usable path.
        """
        if tool.resource_kind != ResourceKind.PATH.value:
            return ()

        if not tool.resource_args:
            # ------------------------------------------------------------------
            # DEPRECATED FALLBACK — do not rely on this in new code.
            #
            # For tools without explicit resource_args, we attempt to infer the
            # resource from a bare "path" argument.  This existed before Phase
            # 1B introduced explicit declaration and is kept only to avoid
            # breaking callers that have not yet been updated.
            #
            # Limitations of the fallback:
            #   • It is positional-name-dependent: any tool whose path argument
            #     is named "filepath", "dest", "source", etc. will silently get
            #     no resource, meaning the gate has nothing to check.
            #   • It cannot handle multiple resources.
            #   • None values pass through as "no resource"; the caller may
            #     expect a resource to be checked but the gate sees nothing.
            # ------------------------------------------------------------------
            path_arg = arguments.get("path")
            if path_arg is not None:
                warnings.warn(
                    f"Tool {tool.name!r} does not declare resource_args. "
                    "The automatic 'path' fallback is deprecated and will be "
                    "removed in a future major release. "
                    'Set resource_args=["path"] (or the correct argument names) '
                    "on the Tool definition.",
                    DeprecationWarning,
                    stacklevel=3,
                )
                return (self._text(tool, "path", path_arg),)
            return ()

        return tuple(
            self._text(tool, name, self._required(tool, arguments, name))
            for name in tool.resource_args
        )

    def resolve_resources(self, tool: Tool, arguments: dict[str, Any]) -> tuple[Resource, ...]:
        """Extract declared *non-path* resources as ``Resource`` objects.

        Empty for path tools.  For an endpoint, spend or budget tool every
        ``resource_args`` entry becomes one resource, and a spend or budget
        resource carries the amount from ``amount_arg``.

        Raises:
            MissingResourceError: A declared argument, or the amount, is absent.
            InvalidResourceError: A value is the wrong type, is not a finite
                non-negative number, or names no host.
        """
        kind = ResourceKind(tool.resource_kind)
        if kind is ResourceKind.PATH:
            return ()

        amount = self._amount(tool, arguments) if tool.amount_arg else None
        resources: list[Resource] = []
        for name in tool.resource_args:
            text = self._text(tool, name, self._required(tool, arguments, name))
            try:
                if kind is ResourceKind.ENDPOINT:
                    resources.append(Resource.endpoint(self._host(tool, name, text)))
                elif kind is ResourceKind.SPEND:
                    destination = self._host(tool, name, text) if "://" in text else text
                    resources.append(
                        Resource.spend(
                            to=destination, amount=self._need(amount, tool), unit=tool.unit or "USD"
                        )
                    )
                else:
                    resources.append(
                        Resource.budget(name=text, amount=self._need(amount, tool), unit=tool.unit)
                    )
            except ResourceError as exc:
                raise _errors().InvalidResourceError(
                    f"Tool {tool.name!r}: argument {name!r}: {exc}"
                ) from exc
        return tuple(resources)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _need(amount: Decimal | None, tool: Tool) -> Decimal:
        """The amount a spend or budget resource needs, which `Tool` guarantees."""
        if amount is None:
            raise _errors().InvalidResourceError(f"Tool {tool.name!r} resolved no amount")
        return amount

    @staticmethod
    def _required(tool: Tool, arguments: dict[str, Any], name: str) -> Any:
        if name not in arguments:
            raise _errors().MissingResourceError(
                f"Tool {tool.name!r} declares resource_args={tool.resource_args!r} "
                f"but argument {name!r} was not provided. "
                f"Got: {sorted(arguments.keys()) or ['(none)']}"
            )
        return arguments[name]

    @staticmethod
    def _text(tool: Tool, name: str, value: Any) -> str:
        """A resource argument as text, or a refusal.

        Only ``str`` and ``os.PathLike`` are accepted: anything else is
        something the handler would receive as itself while the gate checked
        ``str(value)``.
        """
        if isinstance(value, os.PathLike):
            value = os.fspath(value)
        if not isinstance(value, str):
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: argument {name!r} must be a str or a path, "
                f"got {type(value).__name__}; the gate would check a different "
                "resource from the one the handler receives"
            )
        if not value.strip():
            raise _errors().InvalidResourceError(f"Tool {tool.name!r}: argument {name!r} is empty")
        if "\x00" in value:
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: argument {name!r} contains a NUL character"
            )
        return value

    @staticmethod
    def _host(tool: Tool, name: str, text: str) -> str:
        """The ``host[:port]`` a URL or bare host connects to."""
        if any(char in _ENDPOINT_FORBIDDEN or ord(char) < 32 for char in text):
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: argument {name!r} contains a backslash, whitespace or "
                "a control character, which parsers and HTTP clients read differently"
            )
        try:
            has_authority = "://" in text or text.startswith("//")
            parts = urllib.parse.urlsplit(text if has_authority else f"//{text}")
            host = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: argument {name!r} is not a valid host or URL: {exc}"
            ) from exc
        if not host:
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: argument {name!r} names no host"
            )
        if ":" in host:
            host = f"[{host}]"
        return host if port is None else f"{host}:{port}"

    @staticmethod
    def _amount(tool: Tool, arguments: dict[str, Any]) -> Decimal:
        """The amount as a ``Decimal``.

        ``bool`` is an ``int`` to Python and would read as 0 or 1, and a float
        is already imprecise, so both are refused rather than converted.
        """
        name = tool.amount_arg or ""
        if name not in arguments:
            raise _errors().MissingResourceError(
                f"Tool {tool.name!r} declares amount_arg={name!r} but it was not provided. "
                f"Got: {sorted(arguments.keys()) or ['(none)']}"
            )
        value = arguments[name]
        if isinstance(value, bool) or not isinstance(value, int | str | Decimal):
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: amount {name!r} must be an int, a Decimal or a numeric "
                f"string, got {type(value).__name__}"
            )
        try:
            amount = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: amount {name!r} is not a number: {value!r}"
            ) from exc
        if not amount.is_finite():
            raise _errors().InvalidResourceError(
                f"Tool {tool.name!r}: amount {name!r} is not finite"
            )
        return amount
