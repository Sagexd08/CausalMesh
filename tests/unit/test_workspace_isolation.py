"""Workspace containment — the L2 isolation layer (spec §11, §87).

§11 requires an explicit test for filesystem leakage. This is it. Every
attempt below tries to reach a peer's workspace through the path API, and
every one must be refused.

Containment is checked after `realpath` resolution, so these tests attack the
resolution itself: `..` traversal, absolute paths, symlinks, Windows
junctions, and a sibling directory whose name shares a prefix with the
workspace root.

What is being tested is L2 — reachability *through the sanctioned path API*.
It is not a filesystem jail, and `docs/security.md` says so; a test suite
that implied otherwise would be the overclaim §87 forbids.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from causalmesh.isolation import (
    PathEscapeError,
    Workspace,
    WorkspaceError,
    build_run_workspaces,
)

pytestmark = pytest.mark.unit

RUN = "run_001"


@pytest.fixture
def workspaces(tmp_path: Path) -> dict[str, Workspace]:
    return build_run_workspaces(
        base=tmp_path / "workspace", run_id=RUN, agent_ids=["agent_a", "agent_b"]
    )


@pytest.fixture
def agent_a(workspaces: dict[str, Workspace]) -> Workspace:
    return workspaces["agent_a"]


@pytest.fixture
def peer_secret(workspaces: dict[str, Workspace]) -> Path:
    """A file in agent_b's workspace that agent_a must never reach."""
    target = workspaces["agent_b"].root / "secret.py"
    target.write_text("# agent_b's private work\n", encoding="utf-8")
    return target


class TestLayout:
    def test_each_agent_gets_its_own_directory(self, workspaces: dict[str, Workspace]) -> None:
        assert workspaces["agent_a"].root != workspaces["agent_b"].root
        assert workspaces["agent_a"].root.is_dir()
        assert workspaces["agent_b"].root.is_dir()

    def test_workspaces_are_siblings_never_nested(self, workspaces: dict[str, Workspace]) -> None:
        # Nesting would make one agent's containment check automatically
        # admit the other's files.
        a, b = workspaces["agent_a"].root, workspaces["agent_b"].root
        assert not a.is_relative_to(b)
        assert not b.is_relative_to(a)

    def test_the_layout_matches_the_specification(self, tmp_path: Path) -> None:
        # §11: base/run_id/agent_id
        workspace = Workspace.create(base=tmp_path / "ws", run_id=RUN, agent_id="agent_a")
        assert workspace.root.parts[-2:] == (RUN, "agent_a")

    def test_duplicate_agent_ids_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError, match="unique"):
            build_run_workspaces(base=tmp_path, run_id=RUN, agent_ids=["agent_a", "agent_a"])

    def test_the_root_is_fully_resolved(self, tmp_path: Path) -> None:
        # Every later containment check compares two real paths, never a real
        # path against a symlinked spelling of the root.
        workspace = Workspace.create(base=tmp_path / "ws", run_id=RUN, agent_id="agent_a")
        assert workspace.root == workspace.root.resolve()


class TestNormalPaths:
    def test_a_simple_relative_path_resolves_inside(self, agent_a: Workspace) -> None:
        assert agent_a.resolve("src/schema.py").is_relative_to(agent_a.root)

    def test_a_nested_path_resolves_inside(self, agent_a: Workspace) -> None:
        assert agent_a.resolve("a/b/c/deep.py").is_relative_to(agent_a.root)

    def test_a_path_need_not_exist_yet(self, agent_a: Workspace) -> None:
        # create_file and write_file target paths that do not exist.
        assert not agent_a.resolve("brand/new/file.py").exists()

    def test_interior_dot_dot_that_stays_inside_is_allowed(self, agent_a: Workspace) -> None:
        # `src/../src/x.py` never leaves the workspace, so refusing it would
        # be a false positive rather than protection.
        resolved = agent_a.resolve("src/../src/x.py")
        assert resolved == agent_a.root / "src" / "x.py"

    def test_relative_renders_back_as_posix(self, agent_a: Workspace) -> None:
        # Events record workspace-relative POSIX paths so two agents editing
        # "the same file" are comparable and no machine paths leak.
        assert agent_a.relative(agent_a.resolve("src/schema.py")) == "src/schema.py"


class TestLeakageAttempts:
    """§11: explicit tests for filesystem leakage. Every one must be refused."""

    @pytest.mark.parametrize(
        "attack",
        [
            "../agent_b/secret.py",
            "../../run_001/agent_b/secret.py",
            "src/../../agent_b/secret.py",
            "./../agent_b/secret.py",
            "a/b/../../../agent_b/secret.py",
        ],
        ids=["parent", "grandparent", "mid-path", "dot-parent", "deep-unwind"],
    )
    def test_dot_dot_traversal_is_refused(
        self, agent_a: Workspace, peer_secret: Path, attack: str
    ) -> None:
        with pytest.raises(PathEscapeError):
            agent_a.resolve(attack)

    def test_an_absolute_path_to_a_peer_is_refused(
        self, agent_a: Workspace, peer_secret: Path
    ) -> None:
        with pytest.raises(PathEscapeError):
            agent_a.resolve(str(peer_secret))

    def test_an_absolute_path_is_refused_not_rebased(self, agent_a: Workspace) -> None:
        # Silently reinterpreting an absolute path as relative would hide the
        # agent's actual intent from the record.
        with pytest.raises(PathEscapeError):
            agent_a.resolve("/etc/passwd" if os.name != "nt" else "C:/Windows/System32")

    def test_a_symlink_out_of_the_workspace_is_refused(
        self, agent_a: Workspace, peer_secret: Path
    ) -> None:
        """A symlink planted inside the workspace must not become an exit.

        This is why containment is checked after `realpath` rather than on
        the path string: the string looks perfectly innocent.
        """
        link = agent_a.root / "innocent.py"
        try:
            link.symlink_to(peer_secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires privileges not available here")

        with pytest.raises(PathEscapeError):
            agent_a.resolve("innocent.py")

    def test_a_symlinked_directory_out_of_the_workspace_is_refused(
        self, agent_a: Workspace, workspaces: dict[str, Workspace]
    ) -> None:
        link = agent_a.root / "peer"
        try:
            link.symlink_to(workspaces["agent_b"].root, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires privileges not available here")

        with pytest.raises(PathEscapeError):
            agent_a.resolve("peer/secret.py")

    @pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-specific")
    def test_a_windows_junction_out_of_the_workspace_is_refused(
        self, agent_a: Workspace, workspaces: dict[str, Workspace]
    ) -> None:
        """Junctions need no privileges on Windows, so they are the realistic attack.

        Unlike symlinks, an unprivileged user can always create one, which
        makes this the escape a real agent would most plausibly find.
        """
        junction = agent_a.root / "peer"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(workspaces["agent_b"].root)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"could not create junction: {result.stderr.strip()}")

        with pytest.raises(PathEscapeError):
            agent_a.resolve("peer/secret.py")

    def test_a_sibling_with_a_shared_name_prefix_is_refused(
        self, agent_a: Workspace, tmp_path: Path
    ) -> None:
        """A string `startswith` check would wrongly admit this.

        `.../agent_a_backup` starts with `.../agent_a` as text but is a
        different directory, which is why containment compares path
        components rather than string prefixes.
        """
        decoy = agent_a.root.parent / "agent_a_backup"
        decoy.mkdir()
        (decoy / "leak.py").write_text("# not agent_a's\n", encoding="utf-8")

        with pytest.raises(PathEscapeError):
            agent_a.resolve("../agent_a_backup/leak.py")

    @pytest.mark.parametrize("bad", ["", "   "], ids=["empty", "whitespace"])
    def test_an_empty_path_is_refused(self, agent_a: Workspace, bad: str) -> None:
        with pytest.raises(WorkspaceError, match="non-empty"):
            agent_a.resolve(bad)

    def test_a_refusal_records_what_was_attempted(
        self, agent_a: Workspace, peer_secret: Path
    ) -> None:
        # A denial must be traceable to evidence (§52), not an opaque refusal.
        with pytest.raises(PathEscapeError) as caught:
            agent_a.resolve("../agent_b/secret.py")
        assert caught.value.requested == "../agent_b/secret.py"
        assert caught.value.root == agent_a.root
        assert "agent_b" in str(caught.value.resolved)


class TestNonRaisingCheck:
    def test_contains_reports_rather_than_raises(
        self, agent_a: Workspace, peer_secret: Path
    ) -> None:
        assert agent_a.contains("src/schema.py")
        assert not agent_a.contains("../agent_b/secret.py")


class TestFixtureSeeding:
    def test_each_agent_gets_its_own_copy_of_the_fixture(self, tmp_path: Path) -> None:
        """§11: no shared filesystem between agents.

        Any interference must travel through the coordination channel, where
        it can be measured — a shared directory would let agents affect one
        another invisibly.
        """
        fixture = tmp_path / "fixture"
        (fixture / "src").mkdir(parents=True)
        (fixture / "src" / "schema.py").write_text("# original\n", encoding="utf-8")

        workspaces = build_run_workspaces(
            base=tmp_path / "ws",
            run_id=RUN,
            agent_ids=["agent_a", "agent_b"],
            fixture=fixture,
        )

        a_file = workspaces["agent_a"].resolve("src/schema.py")
        b_file = workspaces["agent_b"].resolve("src/schema.py")
        assert a_file.read_text() == b_file.read_text() == "# original\n"

        # Writing in one workspace must not affect the other.
        a_file.write_text("# changed by agent_a\n", encoding="utf-8")
        assert b_file.read_text() == "# original\n"

    def test_seeding_from_a_missing_fixture_is_refused(
        self, agent_a: Workspace, tmp_path: Path
    ) -> None:
        with pytest.raises(WorkspaceError, match="not a directory"):
            agent_a.seed_from(tmp_path / "does_not_exist")

    def test_list_files_returns_relative_posix_paths(self, agent_a: Workspace) -> None:
        (agent_a.root / "src").mkdir()
        (agent_a.root / "src" / "a.py").write_text("x", encoding="utf-8")
        (agent_a.root / "b.py").write_text("y", encoding="utf-8")
        assert agent_a.list_files() == ["b.py", "src/a.py"]
