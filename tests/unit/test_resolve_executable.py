"""`resolve_executable`: a `bash` that cannot run is not an answer on Windows.

A PowerShell session carries `Git\\cmd` on PATH but not `Git\\bin`, so a bare
`bash` is the WSL relay at System32, which exits 1 with no distro installed.
That is the same exit code as a failed test, so the harness would report every
arm as failed for a reason that has nothing to do with the task.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from causalmesh.tasks.runner import resolve_executable

pytestmark = [pytest.mark.unit]


def test_other_executables_resolve_exactly_as_shutil_which_does() -> None:
    assert resolve_executable("python", None) == shutil.which("python")
    assert resolve_executable("no-such-executable-xyz", None) is None


@pytest.mark.skipif(sys.platform != "win32", reason="the WSL relay exists only on Windows")
def test_a_path_with_only_git_cmd_still_finds_a_bash_that_runs() -> None:
    git = shutil.which("git")
    roots = [p for p in Path(git).parents[1:3] if (p / "cmd" / "git.exe").exists()] if git else []
    if not roots:
        pytest.skip("needs Git for Windows (a root with cmd/git.exe)")
    system32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
    path = os.pathsep.join([str(system32), str(roots[0] / "cmd")])

    bash = resolve_executable("bash", path)

    assert bash is not None
    assert Path(bash).parent != system32, "resolved to the WSL relay"
    assert subprocess.run([bash, "-c", "exit 0"], capture_output=True, check=False).returncode == 0
