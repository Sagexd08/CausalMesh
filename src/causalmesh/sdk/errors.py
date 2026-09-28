"""SDK-layer errors.

Developer-facing exceptions that wrap internal failures with a message
a person can act on.  Internal exceptions (ContractError, ResourceError,
…) are caught here and re-raised as one of these so callers never have
to import from internal modules.
"""

from __future__ import annotations

__all__ = [
    "CausalMeshError",
    "ConfigurationError",
    "MissingResourceError",
    "PolicyError",
    "ToolExecutionError",
    "ToolNotFoundError",
]


class CausalMeshError(RuntimeError):
    """Base class for all SDK errors."""


class ConfigurationError(CausalMeshError):
    """The causalmesh.yaml is missing, malformed, or contains invalid rules.

    Raised by ``CausalMesh.from_config`` when it cannot produce a usable
    policy from the supplied file.  The message describes what to fix.
    """


class MissingResourceError(CausalMeshError):
    """A required resource argument is missing from the tool arguments.

    Raised when the gateway cannot resolve resources declared in
    ``resource_args`` because the agent failed to supply them.
    """


class ToolNotFoundError(CausalMeshError):
    """A call was made to a tool that has not been registered.

    Raised by ``CausalMesh.execute`` (or ``ToolGateway.execute``) when the
    requested tool name is not in the registry.
    """


class ToolExecutionError(CausalMeshError):
    """The tool raised an unexpected exception during execution.

    Denials are *not* wrapped here; they surface as ``ToolResult.denied``.
    This only fires when the handler itself crashes after the gate allowed
    the call.
    """


class PolicyError(CausalMeshError):
    """The policy configuration prevents the SDK from starting.

    Raised when the contract is structurally valid YAML but semantically
    unusable — for example, an unknown arm value.
    """
