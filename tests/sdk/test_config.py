"""Tests for the Phase-1 config loader.

Validates both backwards compatibility (existing causalmesh.yaml still
loads) and forward compatibility (new agent/tools fields parse correctly).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from causalmesh.sdk.config import SDKConfig, load_sdk_config
from causalmesh.sdk.errors import ConfigurationError

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def write_yaml(path: Path, content: str) -> Path:
    target = path / "causalmesh.yaml"
    target.write_text(dedent(content), encoding="utf-8")
    return target


# ------------------------------------------------------------------ #
# Backwards-compatibility                                             #
# ------------------------------------------------------------------ #

class TestBackwardsCompatibility:
    """Existing causalmesh.yaml (no SDK fields) still loads."""

    def test_minimal_contract_loads(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            roles:
              - agent_id: agent-a
                archetype: writer
                owns:
                  - src/
            policy:
              arm: C3
        """)
        contract, sdk_config = load_sdk_config(yaml_path)
        assert contract.arm == "C3"
        assert len(contract.roles) == 1
        assert sdk_config.agent_id is None
        assert sdk_config.tool_names == ()

    def test_full_existing_contract_loads(self, tmp_path: Path) -> None:
        """The project's own causalmesh.yaml must still load."""
        root = Path(__file__).parent.parent.parent
        yaml_path = root / "causalmesh.yaml"
        if not yaml_path.is_file():
            pytest.skip("causalmesh.yaml not found at project root")
        contract, sdk_config = load_sdk_config(yaml_path)
        assert contract.arm in {"C0", "C1", "C2", "C3"}
        assert sdk_config.agent_id is None  # no agent section in repo contract


# ------------------------------------------------------------------ #
# Phase-1 extension fields                                            #
# ------------------------------------------------------------------ #

class TestSDKExtensionFields:
    def test_agent_section_parsed(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            agent:
              id: coding-agent
            roles:
              - agent_id: coding-agent
                archetype: writer
                owns:
                  - src/
            policy:
              arm: C3
        """)
        contract, sdk_config = load_sdk_config(yaml_path)
        assert sdk_config.agent_id == "coding-agent"

    def test_tools_section_parsed(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            roles:
              - agent_id: a
            policy:
              arm: C3
            tools:
              read_file:
                mode: auto
              write_file:
                mode: auto
        """)
        contract, sdk_config = load_sdk_config(yaml_path)
        assert set(sdk_config.tool_names) == {"read_file", "write_file"}

    def test_tools_section_null_entry(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            roles:
              - agent_id: a
            policy:
              arm: C3
            tools:
              read_file:
        """)
        _, sdk_config = load_sdk_config(yaml_path)
        assert "read_file" in sdk_config.tool_names

    def test_agent_and_tools_together(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            agent:
              id: my-agent
            roles:
              - agent_id: my-agent
            policy:
              arm: C3
            tools:
              do_thing:
                mode: auto
        """)
        contract, sdk_config = load_sdk_config(yaml_path)
        assert sdk_config.agent_id == "my-agent"
        assert "do_thing" in sdk_config.tool_names


# ------------------------------------------------------------------ #
# Error cases                                                         #
# ------------------------------------------------------------------ #

class TestConfigErrors:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="no config file"):
            load_sdk_config(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "causalmesh.yaml"
        bad.write_text("{ bad yaml: [}}", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="not valid YAML"):
            load_sdk_config(bad)

    def test_unknown_top_level_key_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            totally_unknown: value
            policy:
              arm: C3
        """)
        with pytest.raises(ConfigurationError, match="unknown key"):
            load_sdk_config(yaml_path)

    def test_invalid_arm_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            policy:
              arm: BADARM
        """)
        with pytest.raises(ConfigurationError, match="unknown arm"):
            load_sdk_config(yaml_path)

    def test_agent_id_empty_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            agent:
              id: "  "
            policy:
              arm: C3
        """)
        with pytest.raises(ConfigurationError, match="non-empty string"):
            load_sdk_config(yaml_path)

    def test_unknown_agent_key_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            agent:
              id: coding-agent
              totally_unknown: value
            policy:
              arm: C3
        """)
        with pytest.raises(ConfigurationError, match="unknown key"):
            load_sdk_config(yaml_path)

    def test_unknown_tool_mode_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            policy:
              arm: C3
            tools:
              read_file:
                mode: manual
        """)
        with pytest.raises(ConfigurationError, match="mode"):
            load_sdk_config(yaml_path)

    def test_unknown_tool_key_raises(self, tmp_path: Path) -> None:
        yaml_path = write_yaml(tmp_path, """\
            version: 1
            policy:
              arm: C3
            tools:
              read_file:
                mode: auto
                unknown_key: value
        """)
        with pytest.raises(ConfigurationError, match="unknown key"):
            load_sdk_config(yaml_path)
