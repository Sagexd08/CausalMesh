"""The Claude Code hook adapter documented in docs/adoption.md, run for

real against a synthesized PreToolUse payload -- not merely present in the
doc, but proven to produce the JSON shape Claude Code actually expects.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "docs" / "examples" / "claude-pretooluse.sh"

# Resolved once, by absolute path, rather than passing the bare name "bash"
# to subprocess. On Windows, CreateProcess's own search order can land on
# the WSL launcher stub at System32\bash.exe ahead of Git Bash even when
# PATH (and `where bash`) puts Git Bash first -- that stub exits non-zero
# with no WSL distro installed. Resolving up front, with shutil.which
# (which does respect PATH order), sidesteps that and gives a clear skip
# reason when neither bash nor jq is on the machine at all.
BASH = shutil.which("bash")
JQ = shutil.which("jq")


@pytest.fixture
def contract_dir(tmp_path: Path) -> Path:
    # `claude-code` owns exactly one file; everything else under `src/` is
    # declared to another role, so a write to `src/someone_elses.py` is a
    # real ownership refusal rather than an undeclared (and therefore
    # unrefused) path -- see Contract.owner_of and its longest-match rule.
    (tmp_path / "causalmesh.yaml").write_text(
        "version: 1\n"
        "roles:\n"
        "  - agent_id: claude-code\n"
        "    owns: [src/allowed.py]\n"
        "  - agent_id: someone-else\n"
        "    owns: [src/]\n",
        encoding="utf-8",
    )
    return tmp_path


def run_hook(payload: dict, *, cwd: Path) -> dict:
    if BASH is None or JQ is None:
        pytest.skip("bash and jq are required to run docs/examples/claude-pretooluse.sh")
    result = subprocess.run(
        [BASH, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestClaudeCodeHookAdapter:
    def test_allows_a_write_to_an_owned_path(self, contract_dir: Path) -> None:
        output = run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "src/allowed.py"}},
            cwd=contract_dir,
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_denies_a_write_to_an_unowned_path(self, contract_dir: Path) -> None:
        output = run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/someone_elses.py"}},
            cwd=contract_dir,
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "reason" not in output["hookSpecificOutput"] or output["hookSpecificOutput"].get(
            "permissionDecisionReason"
        )

    def test_a_non_write_tool_is_allowed_without_consulting_the_gate(
        self, contract_dir: Path
    ) -> None:
        output = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "anything.py"}}, cwd=contract_dir
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
