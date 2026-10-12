"""The Claude Code hook adapter documented in docs/adoption.md, run for

real against a synthesized PreToolUse payload -- not merely present in the
doc, but proven to produce the JSON shape Claude Code actually expects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from causalmesh.tasks.runner import resolve_executable

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "docs" / "examples" / "claude-pretooluse.sh"

# Resolved once, by absolute path, rather than passing the bare name "bash"
# to subprocess. On Windows the WSL launcher stub at System32\bash.exe can
# come first, through CreateProcess's own search order or because the
# invoking shell's PATH carries only `Git\cmd` (a PowerShell session does);
# the stub exits non-zero with no WSL distro installed. `resolve_executable`
# skips a bash that does not run, finds Git for Windows beside `git`, and
# gives a clear skip reason when neither bash nor jq is on the machine at all.
BASH = resolve_executable("bash")
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


def run_hook_raw(stdin: str, *, cwd: Path, path: str | None = None) -> dict:
    """Run the hook on a raw stdin string; `path` replaces PATH when given."""
    if BASH is None or JQ is None:
        pytest.skip("bash and jq are required to run docs/examples/claude-pretooluse.sh")
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    result = subprocess.run(
        [BASH, str(HOOK_SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_hook(payload: dict, *, cwd: Path) -> dict:
    return run_hook_raw(json.dumps(payload), cwd=cwd)


def assert_denied_with_reason(output: dict, *, mentions: str) -> None:
    hook_output = output["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny"
    reason = hook_output.get("permissionDecisionReason")
    assert isinstance(reason, str) and reason
    assert mentions in reason


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
        hook_output = output["hookSpecificOutput"]
        assert hook_output["permissionDecision"] == "deny"
        # A refusal must say why: the path and whose it is, not an empty string.
        reason = hook_output.get("permissionDecisionReason")
        assert isinstance(reason, str) and reason
        assert "src/someone_elses.py" in reason
        assert "someone-else" in reason

    def test_a_non_write_tool_is_allowed_without_consulting_the_gate(
        self, contract_dir: Path
    ) -> None:
        output = run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "anything.py"}}, cwd=contract_dir
        )
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


WRITE_PAYLOAD = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "src/allowed.py"}})


class TestHookFailsClosed:
    """Bad inputs end in an explicit deny with a reason, never a bare exit code."""

    @pytest.mark.parametrize(
        "stdin",
        ["{not json", "", "[]", "null", '"Write"', "{}", '{"tool_name": 7}'],
        ids=["garbage", "empty", "array", "null", "string", "no-tool-name", "tool-name-not-text"],
    )
    def test_unreadable_payload_is_denied(self, stdin: str, contract_dir: Path) -> None:
        output = run_hook_raw(stdin, cwd=contract_dir)
        assert_denied_with_reason(output, mentions="tool_name")

    def test_a_write_without_a_path_is_denied(self, contract_dir: Path) -> None:
        output = run_hook({"tool_name": "Write", "tool_input": {}}, cwd=contract_dir)
        assert_denied_with_reason(output, mentions="file_path")

    def test_missing_jq_is_denied(self, contract_dir: Path, tmp_path: Path) -> None:
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        output = run_hook_raw(WRITE_PAYLOAD, cwd=contract_dir, path=str(empty))
        assert_denied_with_reason(output, mentions="jq")

    def test_missing_causalmesh_is_denied(self, contract_dir: Path, tmp_path: Path) -> None:
        only_jq = tmp_path / "jq-bin"
        only_jq.mkdir()
        assert JQ is not None
        shutil.copy2(JQ, only_jq / Path(JQ).name)
        output = run_hook_raw(WRITE_PAYLOAD, cwd=contract_dir, path=str(only_jq))
        assert_denied_with_reason(output, mentions="causalmesh CLI")

    def test_no_contract_is_denied_with_a_reason(self, tmp_path: Path) -> None:
        bare = tmp_path / "no-contract"
        bare.mkdir()
        output = run_hook_raw(WRITE_PAYLOAD, cwd=bare)
        assert_denied_with_reason(output, mentions="causalmesh.yaml")
