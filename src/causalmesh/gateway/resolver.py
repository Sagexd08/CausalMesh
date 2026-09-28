"""Resource extraction from tool arguments.

Security-critical resources (paths, URIs, identifiers) that the policy gate
uses to make ALLOW/DENY decisions **must** be declared explicitly via
``Tool(resource_args=[...])``.  Explicit declaration is the only way to
guarantee that the gate sees exactly the resources the handler will act on.

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

import warnings
from typing import Any

from causalmesh.gateway.tool import Tool

__all__ = ["ResourceResolver"]


class ResourceResolver:
    """Extracts security-critical resource declarations from tool arguments.

    Preferred usage::

        Tool(name="write_file", handler=..., resource_args=["path"])

    The resolver then maps each declared argument name to its string value.
    If a declared argument is absent the call is refused with
    :class:`~causalmesh.sdk.errors.MissingResourceError` — it **fails
    closed**, never silently passes a resource check with a missing value.
    """

    def resolve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[str, ...]:
        """Extract declared resource arguments as a tuple of strings.

        Args:
            tool:       The ``Tool`` definition.
            arguments:  The arguments provided for this invocation.

        Returns:
            A tuple of resource strings in the same order as
            ``tool.resource_args``.  Empty tuple when no resources are
            declared *and* no ``"path"`` fallback applies.

        Raises:
            MissingResourceError: When a declared ``resource_args`` name is
                absent from ``arguments``.  The call is not executed.
        """
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
            #   • None values and empty strings pass through as-is; the caller
            #     may expect a resource to be checked but the gate sees nothing.
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
                return (str(path_arg),)
            return ()

        paths: list[str] = []
        for arg_name in tool.resource_args:
            if arg_name not in arguments:
                from causalmesh.sdk.errors import MissingResourceError

                raise MissingResourceError(
                    f"Tool {tool.name!r} declares resource_args={tool.resource_args!r} "
                    f"but argument {arg_name!r} was not provided. "
                    f"Got: {sorted(arguments.keys()) or ['(none)']}"
                )
            paths.append(str(arguments[arg_name]))

        return tuple(paths)
