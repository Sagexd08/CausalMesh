"""Load and validate the developer-facing causalmesh.yaml extension fields.

Phase 1 adds two optional top-level keys to the existing contract format:

    agent:
      id: coding-agent          # default agent_id for mesh.execute()

    tools:
      write_file:
        mode: auto              # reserved — only "auto" in phase 1
      read_file:
        mode: auto

These keys are *backwards-compatible*: an existing causalmesh.yaml without
them still loads correctly.  Neither key is required.

The ``SDKConfig`` dataclass holds the Phase-1 extension fields; the
underlying ``Contract`` is obtained separately via ``Contract.load()``.
The two are composed in ``mesh.py`` — one parser, one contract, no
second schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from causalmesh.policy.contract import Contract, ContractError, parse_sdk_sections

from .errors import ConfigurationError

__all__ = ["SDKConfig", "load_sdk_config"]

_ALLOWED_TOP_LEVEL = {
    "version",
    "identity",
    "roles",
    "policy",
    "evidence",
    # Phase-1 extensions
    "agent",
    "tools",
}


@dataclass(frozen=True, slots=True)
class SDKConfig:
    """Phase-1 extension fields extracted from causalmesh.yaml.

    These are *in addition* to the core ``Contract``.  The contract is
    loaded separately and not duplicated here.
    """

    agent_id: str | None
    """Default agent id.  ``None`` when the ``agent`` section is absent."""

    tool_names: tuple[str, ...] = ()
    """Names of tools declared under the ``tools`` section.

    Empty tuple when no ``tools`` section is present — not an error.
    """


def load_sdk_config(path: Path | str) -> tuple[Contract, SDKConfig]:
    """Load a causalmesh.yaml and return both the Contract and the SDKConfig.

    Raises ``ConfigurationError`` on any parse or validation problem.
    """
    path = Path(path)
    try:
        import yaml
    except ImportError as exc:
        raise ConfigurationError("pyyaml is required to load a config file") from exc

    if not path.is_file():
        raise ConfigurationError(f"no config file at {path}")

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(f"{path} must be a YAML mapping at the top level")

    unknown = set(raw) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise ConfigurationError(
            f"unknown key(s) in {path}: {', '.join(sorted(unknown))}. "
            f"Valid keys: {', '.join(sorted(_ALLOWED_TOP_LEVEL))}"
        )

    # The core schema accepts (and validates) the SDK sections itself, so the
    # whole mapping goes through it unchanged.
    try:
        contract = Contract.from_dict(raw, source=path)
    except ContractError as exc:
        raise ConfigurationError(str(exc)) from exc

    sdk = _parse_sdk_fields(raw)
    return contract, sdk


def _parse_sdk_fields(raw: dict[str, Any]) -> SDKConfig:
    """Extract the Phase-1 extension fields from an already-loaded mapping.

    The validation lives in ``causalmesh.policy.contract.parse_sdk_sections``
    so that the core contract loader and this one accept the same file.
    """
    try:
        agent_id, tool_names = parse_sdk_sections(raw)
    except ContractError as exc:
        raise ConfigurationError(str(exc)) from exc
    return SDKConfig(agent_id=agent_id, tool_names=tool_names)
