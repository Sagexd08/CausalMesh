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
    "InvalidResourceError",
    "MissingResourceError",
    "PolicyError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "UnknownAgentError",
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


class InvalidResourceError(MissingResourceError):
    """A resource argument is present but cannot be turned into a resource.

    A subclass of ``MissingResourceError`` on purpose: both mean the gate has
    nothing trustworthy to decide on, both are refused before the handler
    runs, and everything that already handles the parent (the HTTP server's
    422, the OpenAI adapter's tool message) handles this too.

    Raised for a value of the wrong type (a list, ``None``, bytes: the handler
    would receive the raw object while the gate saw ``str(value)``), an empty
    name, an amount that is not a finite non-negative number, or an endpoint
    that names no host.
    """


class ToolNotFoundError(CausalMeshError):
    """A call was made to a tool that has not been registered.

    Raised by ``CausalMesh.execute`` (or ``ToolGateway.execute``) when the
    requested tool name is not in the registry.
    """


class UnknownAgentError(CausalMeshError):
    """A call was made for an agent that has no signing key in this session.

    Raised by ``CausalMesh.execute`` *before* the gate or the handler runs.
    The relay cannot attribute an event to an actor without a key, so
    running the call would produce an action with no evidence behind it.
    Declare the agent under ``roles`` (or as ``agent.id``), or pass it in
    ``agents=`` when constructing the session.
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
