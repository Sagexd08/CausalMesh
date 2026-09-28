"""Resource extraction from tool arguments."""

from __future__ import annotations

from typing import Any

from causalmesh.gateway.tool import Tool

__all__ = ["ResourceResolver"]


class ResourceResolver:
    """Extracts security-critical resource declarations from tool arguments."""

    def resolve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[str, ...]:
        """Extract declared resource arguments as a tuple of strings.

        If the tool declares ``resource_args``, those exact arguments are
        extracted.  If an argument is missing, raises MissingResourceError.
        If the tool declares no resource_args, returns an empty tuple.

        Args:
            tool: The Tool definition.
            arguments: The arguments provided to the tool call.

        Raises:
            MissingResourceError: When a declared resource argument is absent.
        """
        if not tool.resource_args:
            # Backwards compatibility: fallback to guessing "path"
            # if resource_args is not explicitly declared.
            path_arg = arguments.get("path")
            return (str(path_arg),) if path_arg else ()

        paths: list[str] = []
        for arg_name in tool.resource_args:
            if arg_name not in arguments:
                from causalmesh.sdk.errors import MissingResourceError

                raise MissingResourceError(
                    f"Tool {tool.name!r} requires resource argument {arg_name!r}, "
                    f"but it was missing from the arguments: {list(arguments.keys())}"
                )
            paths.append(str(arguments[arg_name]))

        return tuple(paths)
