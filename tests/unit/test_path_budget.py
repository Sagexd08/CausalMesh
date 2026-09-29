"""The Windows path budget: refuse only what is certain to fail, and say why.

A checkout at an ordinary location used to fail every run with a bare
`FileNotFoundError` or a `shutil.Error` listing dozens of paths, because the
run id sat in the workspace path twice. The scheduler no longer nests it, and
`check_path_budget` refuses, before anything is copied, a run whose deepest
known path Windows cannot open.

The check is exercised with `enforce=True` so it runs on every platform.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from causalmesh.isolation import workspace
from causalmesh.isolation.workspace import WorkspaceError, build_run_workspaces, check_path_budget

pytestmark = pytest.mark.unit

RUN_ID = "exp__task__C0__r0000"


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    deep = tmp_path / "fixture" / "src" / "pkg"
    deep.mkdir(parents=True)
    (deep / "module.py").write_text("x = 1\n")
    return tmp_path / "fixture"


def _deepest_file(fixture: Path) -> int:
    return max(len(p.relative_to(fixture).as_posix()) + 1 for p in fixture.rglob("*"))


def _needed(base: Path, fixture: Path) -> int:
    # `<run_id>_integrated` is the longest root when the agent ids are short.
    return len(os.path.abspath(base / f"{RUN_ID}_integrated")) + _deepest_file(fixture)


def _padded_to(limit: int, tmp_path: Path, fixture: Path) -> Path:
    """A base directory whose deepest known path is exactly `limit` characters."""
    base = tmp_path / "work"
    gap = limit - _needed(base / "p", fixture)
    assert gap >= 0, "the temp directory is already deeper than the limit"
    return base / ("p" * (1 + gap))


class TestTheBudget:
    def test_a_shallow_checkout_passes(self, tmp_path: Path, fixture_dir: Path) -> None:
        assert (
            check_path_budget(
                base=tmp_path,
                run_id=RUN_ID,
                agent_ids=["a", "b"],
                fixture=fixture_dir,
                enforce=True,
            )
            is None
        )

    def test_the_limit_itself_is_allowed_and_one_over_is_refused(
        self, tmp_path: Path, fixture_dir: Path
    ) -> None:
        # MAX_PATH is 260 with the terminating NUL: 259 characters are usable.
        at_limit = _padded_to(259, tmp_path, fixture_dir)
        assert _needed(at_limit, fixture_dir) == 259
        check_path_budget(
            base=at_limit, run_id=RUN_ID, agent_ids=["a"], fixture=fixture_dir, enforce=True
        )
        over = at_limit.parent / (at_limit.name + "p")
        assert _needed(over, fixture_dir) == 260
        with pytest.raises(WorkspaceError, match="Windows opens at most 259"):
            check_path_budget(
                base=over, run_id=RUN_ID, agent_ids=["a"], fixture=fixture_dir, enforce=True
            )

    def test_the_refusal_names_the_length_the_workspace_and_both_ways_out(
        self, tmp_path: Path, fixture_dir: Path
    ) -> None:
        with pytest.raises(WorkspaceError) as caught:
            check_path_budget(
                base=tmp_path / ("p" * 300),
                run_id=RUN_ID,
                agent_ids=["agent_a"],
                fixture=fixture_dir,
                enforce=True,
            )
        message = str(caught.value)
        assert RUN_ID in message
        assert "259" in message and "characters" in message
        assert "shorter" in message and "LongPathsEnabled" in message
        assert "ppp" in message, "the workspace path that would not fit is shown"

    def test_the_integrated_sibling_counts_when_it_is_the_longest_root(
        self, tmp_path: Path, fixture_dir: Path
    ) -> None:
        # `<run_id>_integrated` is longer than `<run_id>/<agent>` for a short agent
        # id, so it is the one that overflows first, and it must be the one counted.
        at_limit = _padded_to(259, tmp_path, fixture_dir)
        agent_root = os.path.abspath(at_limit / RUN_ID / "a")
        assert len(agent_root) + _deepest_file(fixture_dir) < 259
        check_path_budget(
            base=at_limit, run_id=RUN_ID, agent_ids=["a"], fixture=fixture_dir, enforce=True
        )
        with pytest.raises(WorkspaceError):
            check_path_budget(
                base=at_limit.parent / (at_limit.name + "p"),
                run_id=RUN_ID,
                agent_ids=["a"],
                fixture=fixture_dir,
                enforce=True,
            )

    def test_it_does_not_apply_where_the_limit_does_not(
        self, tmp_path: Path, fixture_dir: Path
    ) -> None:
        assert (
            check_path_budget(
                base=tmp_path / ("p" * 400),
                run_id=RUN_ID,
                agent_ids=["a"],
                fixture=fixture_dir,
                enforce=False,
            )
            is None
        )

    def test_it_does_not_apply_off_windows(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Replace the module's reference, not the global `sys.platform`.
        monkeypatch.setattr(workspace, "sys", SimpleNamespace(platform="linux"))
        assert workspace._long_paths_enabled() is True
        check_path_budget(
            base=tmp_path / ("p" * 400), run_id=RUN_ID, agent_ids=["a"], fixture=fixture_dir
        )

    def test_no_fixture_is_fine(self, tmp_path: Path) -> None:
        assert (
            check_path_budget(
                base=tmp_path, run_id=RUN_ID, agent_ids=["a"], fixture=None, enforce=True
            )
            is None
        )


class TestBuildingWorkspaces:
    def test_a_run_that_cannot_fit_is_refused_before_anything_is_created(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(workspace, "_long_paths_enabled", lambda: False)
        base = tmp_path / ("p" * 300)
        with pytest.raises(WorkspaceError, match="Windows opens at most"):
            build_run_workspaces(
                base=base, run_id=RUN_ID, agent_ids=["agent_a", "agent_b"], fixture=fixture_dir
            )
        assert not base.exists(), "a half-built workspace was left behind"

    def test_a_run_that_fits_is_built_as_before(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(workspace, "_long_paths_enabled", lambda: False)
        made = build_run_workspaces(
            base=tmp_path / "work",
            run_id=RUN_ID,
            agent_ids=["agent_a", "agent_b"],
            fixture=fixture_dir,
        )
        assert sorted(made) == ["agent_a", "agent_b"]
        assert (tmp_path / "work" / RUN_ID / "agent_a" / "src" / "pkg" / "module.py").is_file()
