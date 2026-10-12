"""The generated hidden-test harness is correct on its own terms (backlog §54).

`ImportOptions(hidden_tests="pytest")` makes the loader write a `run_tests.sh`
that applies each feature's `tests.patch` to a scratch copy of the workspace
and runs the Python tests that patch touches. Before that script's verdict is
used to say anything about a task (the §37 gate), it has to be shown to
discriminate, using the two properties CooperBench states for its own data
(`dataset/README.md`, "Patches: what each one is for"):

- each feature's `tests.patch` **fails** on the untouched base commit;
- the combined patch (every feature landed, conflicts resolved) **passes**
  every feature's tests.

The dataset here is synthetic and built on the fly from real `git diff`
output; it is not CooperBench data. The same two checks were run by hand
against the real click, jinja and dirty-equals tasks, see
`docs/backlog.md`, "CooperBench import".
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from causalmesh.tasks.cooperbench import ImportOptions, import_task

pytestmark = [pytest.mark.integration, pytest.mark.slow]

BASE_CALC = '''"""calc"""

OPS = {
    "add": lambda a, b: a + b,
}


def apply(name, a, b):
    return OPS[name](a, b)
'''

#: (feature number, operator name, expression, test's expected value)
FEATURES = ((1, "sub", "a - b", 2), (2, "mul", "a * b", 15))


def _git(args: list[str], cwd: Path) -> str:
    # autocrlf=false: with Windows' default of `true` git rewrites the tree and the
    # patches made from it, and `git apply` then rejects its own diff.
    done = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True, check=True
    )
    return done.stdout.decode("utf-8")


def _put(path: Path, text: str) -> None:
    """Write exactly these characters; `Path.write_text` would turn LF into CRLF on Windows."""
    path.write_bytes(text.encode("utf-8"))


def _edit_diff(repo: Path, edits: dict[str, str]) -> str:
    for relative, content in edits.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _put(target, content)
    _git(["add", "-N", "-A"], repo)
    text = _git(["diff"], repo)
    # Drop the intent-to-add entries first: otherwise `checkout` restores the
    # new files as empty tracked files and they leak into the next diff.
    _git(["reset", "-q"], repo)
    _git(["checkout", "-q", "--", "."], repo)
    _git(["clean", "-fdq"], repo)
    return text


def _with_ops(*names: tuple[str, str]) -> str:
    lines = "".join(f'    "{name}": lambda a, b: {expr},\n' for name, expr in names)
    return BASE_CALC.replace(
        '    "add": lambda a, b: a + b,\n', '    "add": lambda a, b: a + b,\n' + lines
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("hidden_tests")
    repo = root / "origin"
    repo.mkdir()
    _git(["init", "-q"], repo)
    (repo / "src").mkdir()
    _put(repo / "src" / "calc.py", BASE_CALC)
    _git(["add", "-A"], repo)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"], repo)

    task = root / "dataset" / "calc_task" / "task1"
    task.mkdir(parents=True)
    _put(task / "setup.sh", "#!/bin/bash\n")
    for number, name, expr, expected in FEATURES:
        feature = task / f"feature{number}"
        feature.mkdir()
        _put(feature / "feature.md", f"# {name}\n\nAdd {name}.\n")
        _put(feature / "feature.patch", _edit_diff(repo, {"src/calc.py": _with_ops((name, expr))}))
        test = (
            "from calc import apply\n\n\n"
            f'def test_{name}():\n    assert apply("{name}", 5, 3) == {expected}\n'
        )
        _put(feature / "tests.patch", _edit_diff(repo, {f"tests/test_{name}.py": test}))
    combined = _edit_diff(repo, {"src/calc.py": _with_ops(*((n, e) for _, n, e, _ in FEATURES))})
    _put(task / "combined.patch", combined)

    imported = import_task(
        task,
        base_files={"src/calc.py": BASE_CALC},
        options=ImportOptions(hidden_tests="pytest"),
    )
    fixture = imported.write_fixture(root / "fixture")
    return {"fixture": fixture, "combined": task / "combined.patch", "root": root}


def _run_harness(workspace: Path) -> tuple[int, list[str]]:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    done = subprocess.run(
        # Absolute path: a bare "bash" can resolve to the WSL launcher at System32 on
        # Windows (see test_adoption_hook.py).
        [shutil.which("bash") or "bash", "run_tests.sh"],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    return done.returncode, re.findall(r"feature\d+: (?:PASS|FAIL)", done.stdout)


def _copy(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def test_on_the_untouched_base_every_feature_fails(built: dict[str, Path]) -> None:
    workspace = _copy(built["fixture"], built["root"] / "on_base")
    code, verdicts = _run_harness(workspace)
    assert verdicts == ["feature1: FAIL", "feature2: FAIL"]
    assert code != 0


def test_with_the_combined_patch_every_feature_passes(built: dict[str, Path]) -> None:
    workspace = _copy(built["fixture"], built["root"] / "on_combined")
    subprocess.run(
        ["git", "apply", str(built["combined"])], cwd=workspace, check=True, capture_output=True
    )
    code, verdicts = _run_harness(workspace)
    assert verdicts == ["feature1: PASS", "feature2: PASS"]
    assert code == 0


def test_with_only_one_feature_landed_only_that_feature_passes(built: dict[str, Path]) -> None:
    workspace = _copy(built["fixture"], built["root"] / "on_first_only")
    feature_patch = built["root"] / "dataset" / "calc_task" / "task1" / "feature1" / "feature.patch"
    subprocess.run(
        ["git", "apply", str(feature_patch)], cwd=workspace, check=True, capture_output=True
    )
    code, verdicts = _run_harness(workspace)
    assert verdicts == ["feature1: PASS", "feature2: FAIL"]
    assert code != 0
