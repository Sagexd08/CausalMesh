"""The three-way line merge, against hand-derived cases and against git.

The hand cases state the rule in plain terms. The oracle test is the check
that matters: `git merge-file` is an independent implementation of the same
rule, so agreement on generated inputs is evidence the merge is right and not
merely self-consistent. Skipped, not failed, where git is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from causalmesh.tasks.merge3 import merge_three_way

pytestmark = pytest.mark.unit

BASE = b"one\ntwo\nthree\nfour\nfive\n"


class TestTheRule:
    def test_edits_to_different_regions_both_survive(self) -> None:
        ours = b"ONE\ntwo\nthree\nfour\nfive\n"
        theirs = b"one\ntwo\nthree\nfour\nFIVE\n"
        result = merge_three_way(BASE, ours, theirs)
        assert result.clean
        assert result.content == b"ONE\ntwo\nthree\nfour\nFIVE\n"

    def test_the_same_change_on_both_sides_is_not_a_conflict(self) -> None:
        both = b"one\nTWO\nthree\nfour\nfive\n"
        result = merge_three_way(BASE, both, both)
        assert result.clean and result.content == both

    def test_different_changes_to_the_same_line_conflict(self) -> None:
        result = merge_three_way(
            BASE,
            b"one\nTWO\nthree\nfour\nfive\n",
            b"one\n2\nthree\nfour\nfive\n",
            ours_label="agent_a",
            theirs_label="agent_b",
        )
        assert result.conflicts == 1
        assert result.content == (
            b"one\n<<<<<<< agent_a\nTWO\n=======\n2\n>>>>>>> agent_b\nthree\nfour\nfive\n"
        )

    def test_edits_to_adjacent_lines_conflict_as_in_git(self) -> None:
        """No agreed line between the two edits, so they are one region."""
        result = merge_three_way(
            BASE,
            b"one\nTWO\nthree\nfour\nfive\n",
            b"one\ntwo\nTHREE\nfour\nfive\n",
        )
        assert result.conflicts == 1

    def test_both_sides_deleting_the_same_lines_is_not_a_conflict(self) -> None:
        both = b"one\nthree\nfour\nfive\n"
        assert merge_three_way(BASE, both, both).clean

    def test_a_deletion_and_an_edit_elsewhere_both_apply(self) -> None:
        result = merge_three_way(
            BASE, b"two\nthree\nfour\nfive\n", b"one\ntwo\nthree\nfour\nFIVE\n"
        )
        assert result.clean and result.content == b"two\nthree\nfour\nFIVE\n"

    def test_two_insertions_at_the_same_place_conflict(self) -> None:
        result = merge_three_way(
            BASE, b"one\nA\ntwo\nthree\nfour\nfive\n", b"one\nB\ntwo\nthree\nfour\nfive\n"
        )
        assert result.conflicts == 1

    def test_two_insertions_in_different_places_both_apply(self) -> None:
        result = merge_three_way(
            BASE, b"A\none\ntwo\nthree\nfour\nfive\n", b"one\ntwo\nthree\nfour\nfive\nB\n"
        )
        assert result.clean and result.content == b"A\none\ntwo\nthree\nfour\nfive\nB\n"

    def test_a_file_both_added_differently_conflicts_and_identically_does_not(self) -> None:
        assert merge_three_way(b"", b"x\n", b"y\n").conflicts == 1
        assert merge_three_way(b"", b"x\n", b"x\n").clean


class TestBytesAreHonoured:
    def test_a_missing_final_newline_is_preserved(self) -> None:
        result = merge_three_way(b"a\nb\nc", b"A\nb\nc", b"a\nb\nC")
        assert result.clean and result.content == b"A\nb\nC"

    def test_crlf_line_endings_are_preserved(self) -> None:
        base = b"a\r\nb\r\nc\r\nd\r\ne\r\n"
        result = merge_three_way(base, b"A\r\nb\r\nc\r\nd\r\ne\r\n", b"a\r\nb\r\nc\r\nd\r\nE\r\n")
        assert result.clean and result.content == b"A\r\nb\r\nc\r\nd\r\nE\r\n"

    def test_binary_content_is_never_line_merged(self) -> None:
        result = merge_three_way(b"\x00a", b"\x00b", b"\x00c")
        assert result.conflicts == 1 and result.content == b"\x00b"

    def test_an_unchanged_side_returns_the_other_whole(self) -> None:
        assert merge_three_way(b"\x00a", b"\x00a", b"\x00z").content == b"\x00z"

    def test_a_conflict_with_no_final_newline_still_puts_markers_on_their_own_lines(self) -> None:
        result = merge_three_way(b"a", b"b", b"c", ours_label="o", theirs_label="t")
        assert result.content == b"<<<<<<< o\nb\n=======\nc\n>>>>>>> t\n"

    def test_it_is_deterministic(self) -> None:
        args = (BASE, b"one\nTWO\nthree\nfour\nfive\n", b"one\n2\nthree\nfour\nfive\n")
        assert merge_three_way(*args) == merge_three_way(*args)


# ---------------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------------

git = shutil.which("git")


def _git_merge_file(base: bytes, ours: bytes, theirs: bytes, scratch: Path) -> tuple[int, bytes]:
    for name, content in (("ours", ours), ("base", base), ("theirs", theirs)):
        (scratch / name).write_bytes(content)
    completed = subprocess.run(
        [git or "git", "merge-file", "-p", "ours", "base", "theirs"],
        cwd=scratch,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout


@st.composite
def three_versions(draw: st.DrawFn) -> tuple[bytes, bytes, bytes]:
    """Base plus two edited copies, over lines that are all distinct.

    Distinct lines keep the alignment unambiguous. With repeated lines two
    correct diff algorithms may place a change differently, which is a real
    difference between difflib and xdiff, not a bug in either (the module
    docstring says so, and the CooperBench agreement figure measures it).
    """
    size = draw(st.integers(min_value=0, max_value=18))
    base = [f"line-{i}\n" for i in range(size)]
    counter = iter(range(10_000))

    def edit(tag: str) -> list[str]:
        lines = list(base)
        for _ in range(draw(st.integers(min_value=0, max_value=3))):
            op = draw(st.sampled_from("ird"))
            at = draw(st.integers(min_value=0, max_value=max(len(lines), 1)))
            if op == "i":
                lines.insert(min(at, len(lines)), f"{tag}-new-{next(counter)}\n")
            elif lines:
                index = min(at, len(lines) - 1)
                if op == "r":
                    lines[index] = f"{tag}-chg-{next(counter)}\n"
                else:
                    del lines[index]
        return lines

    return "".join(base).encode(), "".join(edit("o")).encode(), "".join(edit("t")).encode()


@pytest.mark.skipif(git is None, reason="git is not installed; the oracle is unavailable")
class TestAgainstGit:
    @settings(
        max_examples=400,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(versions=three_versions())
    def test_it_agrees_with_git_merge_file(
        self, versions: tuple[bytes, bytes, bytes], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        base, ours, theirs = versions
        scratch = tmp_path_factory.mktemp("oracle")
        git_conflicts, git_content = _git_merge_file(base, ours, theirs, scratch)
        assert git_conflicts >= 0, "git merge-file itself failed"
        mine = merge_three_way(base, ours, theirs)
        assert mine.clean == (git_conflicts == 0), (base, ours, theirs)
        if mine.clean:
            assert mine.content == git_content, (base, ours, theirs)
