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

from causalmesh.policy.contract import Contract, ContractError

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

_AGENT_KEYS = {"id"}
_TOOL_ENTRY_KEYS = {"mode"}
_ALLOWED_TOOL_MODES = {"auto"}


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

    # Contract.from_dict is strict and rejects unknown keys.
    # Strip the Phase-1 SDK extension keys before passing to it.
    _sdk_only_keys = {"agent", "tools"}
    contract_raw = {k: v for k, v in raw.items() if k not in _sdk_only_keys}

    try:
        contract = Contract.from_dict(contract_raw, source=path)
    except ContractError as exc:
        raise ConfigurationError(str(exc)) from exc

    sdk = _parse_sdk_fields(raw)
    return contract, sdk


def _parse_sdk_fields(raw: dict[str, Any]) -> SDKConfig:
    """Extract the Phase-1 extension fields from an already-loaded mapping."""
    agent_section = raw.get("agent")
    agent_id: str | None = None
    if agent_section is not None:
        if not isinstance(agent_section, dict):
            raise ConfigurationError("`agent` must be a mapping")
        unknown = set(agent_section) - _AGENT_KEYS
        if unknown:
            raise ConfigurationError(
                f"unknown key(s) in `agent`: {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(_AGENT_KEYS))}"
            )
        raw_id = agent_section.get("id")
        if raw_id is not None:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ConfigurationError("`agent.id` must be a non-empty string")
            agent_id = raw_id.strip()

    tools_section = raw.get("tools")
    tool_names: tuple[str, ...] = ()
    if tools_section is not None:
        if not isinstance(tools_section, dict):
            raise ConfigurationError("`tools` must be a mapping")
        names = []
        for tool_name, tool_conf in tools_section.items():
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ConfigurationError("`tools` keys must be non-empty strings")
            if tool_conf is not None:
                if not isinstance(tool_conf, dict):
                    raise ConfigurationError(f"`tools.{tool_name}` must be a mapping or null")
                unknown = set(tool_conf) - _TOOL_ENTRY_KEYS
                if unknown:
                    raise ConfigurationError(
                        f"unknown key(s) in `tools.{tool_name}`: "
                        f"{', '.join(sorted(unknown))}. "
                        f"Valid keys: {', '.join(sorted(_TOOL_ENTRY_KEYS))}"
                    )
                mode = tool_conf.get("mode", "auto")
                if mode not in _ALLOWED_TOOL_MODES:
                    raise ConfigurationError(
                        f"`tools.{tool_name}.mode` must be one of "
                        f"{sorted(_ALLOWED_TOOL_MODES)}, got {mode!r}"
                    )
            names.append(tool_name.strip())
        tool_names = tuple(names)

    return SDKConfig(agent_id=agent_id, tool_names=tool_names)
