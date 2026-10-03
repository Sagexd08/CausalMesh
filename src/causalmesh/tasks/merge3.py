"""A deterministic three-way line merge, for contested paths.

Two agents that both edit one file cannot both survive if the integrated
workspace takes one agent's whole file (`last_writer`, the default and the
only behaviour before this module). That is a statement about the harness, not
about the agents: 512 of CooperBench's 652 feature pairs share exactly one
file, and 153 of the 652 are changes git itself merges cleanly. `three_way`
merges the two agents' files against the fixture they both started from.

**Why not shell out to `git merge-file`.** The same reason `ActionKind.PATCH`
was rejected (`docs/backlog.md`, "CooperBench import"): what lands in a
workspace would depend on the machine's `git` version instead of solely on
the task. This is pure Python over `difflib`, which is deterministic for a
given Python, adds no dependency, and is checked against `git merge-file` as
an oracle rather than trusted (`tests/unit/test_merge3.py`,
`scripts/cooperbench_real.py merge-check`).

**What "conflict" means here.** The rule is git's: two changes conflict when
they touch the same base lines or touch *adjacent* base lines, unless both made
the identical change. Two sides that both deleted the same lines are not a
conflict. A conflicted file is written with git-style markers, so a Python
file with a conflict fails to import and an integration test notices, but the
conflict is also returned as data (`MergeResult.conflicts`) and the runner
records it: a refusal is data (AGENTS.md), and a run with a conflict has not
succeeded however its tests happen to score.

**What it does not do.** Line-based only: it cannot see that two edits to
different lines are semantically incompatible, which is for the integration
test to find. It does not detect renames. `difflib` and git's `xdiff` can
align repeated lines differently, so on a file with long runs of identical
lines the two can disagree about where a change sits; the real-data
agreement figure in `docs/backlog.md` says how often that happens on
CooperBench.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

__all__ = ["MergeResult", "merge_three_way"]

_NUL = b"\x00"


@dataclass(frozen=True, slots=True)
class MergeResult:
    """The merged bytes and how many regions could not be merged.

    `content` is always usable as a file: with conflicts it carries git-style
    markers around each unmerged region. `conflicts` is a count of regions,
    never a guess: zero means every region merged.
    """

    content: bytes
    conflicts: int

    @property
    def clean(self) -> bool:
        return self.conflicts == 0


def merge_three_way(
    base: bytes,
    ours: bytes,
    theirs: bytes,
    *,
    ours_label: str = "ours",
    theirs_label: str = "theirs",
) -> MergeResult:
    """Merge `ours` and `theirs`, two edits of `base`, line by line.

    Byte-exact when nothing conflicts: line endings and a missing final newline
    are preserved as the winning side wrote them. Binary content (a NUL byte)
    is never line-merged: unless one side did not change it, it is one conflict
    and `content` is `ours` unchanged.
    """
    if ours == theirs:
        return MergeResult(ours, 0)
    if ours == base:
        return MergeResult(theirs, 0)
    if theirs == base:
        return MergeResult(ours, 0)
    if _NUL in base or _NUL in ours or _NUL in theirs:
        return MergeResult(ours, 1)

    base_lines = base.splitlines(keepends=True)
    ours_lines = ours.splitlines(keepends=True)
    theirs_lines = theirs.splitlines(keepends=True)

    out: list[bytes] = []
    conflicts = 0
    for region in _regions(base_lines, ours_lines, theirs_lines):
        kind = region[0]
        if kind == "unchanged":
            out.extend(base_lines[region[1] : region[2]])
        elif kind == "ours" or kind == "same":
            out.extend(ours_lines[region[1] : region[2]])
        elif kind == "theirs":
            out.extend(theirs_lines[region[1] : region[2]])
        else:
            conflicts += 1
            _, _, _, ours_start, ours_end, theirs_start, theirs_end = region
            out.append(b"<<<<<<< " + ours_label.encode("utf-8") + b"\n")
            out.extend(_ending_in_newline(ours_lines[ours_start:ours_end]))
            out.append(b"=======\n")
            out.extend(_ending_in_newline(theirs_lines[theirs_start:theirs_end]))
            out.append(b">>>>>>> " + theirs_label.encode("utf-8") + b"\n")
    return MergeResult(b"".join(out), conflicts)


def _ending_in_newline(lines: list[bytes]) -> list[bytes]:
    """A marker must start on its own line, so a final unterminated line gets one."""
    if lines and not lines[-1].endswith((b"\n", b"\r")):
        return [*lines[:-1], lines[-1] + b"\n"]
    return lines


def _regions(
    base: list[bytes], ours: list[bytes], theirs: list[bytes]
) -> list[tuple[int | str, ...]]:
    """Walk the sync regions and classify each gap between them.

    A sync region is a run of lines all three versions agree on. Between two of
    them, each side either left the base lines alone or changed them: one side
    changed (take it), both made the same change (take it), or both changed it
    differently (conflict). Two edits with no agreed line between them fall in
    the same gap, which is what makes adjacent edits conflict, as in git.
    """
    regions: list[tuple[int | str, ...]] = []
    base_pos = ours_pos = theirs_pos = 0
    for base_start, base_end, ours_start, ours_end, theirs_start, theirs_end in _sync_regions(
        base, ours, theirs
    ):
        ours_gap = ours[ours_pos:ours_start]
        theirs_gap = theirs[theirs_pos:theirs_start]
        base_gap = base[base_pos:base_start]
        if ours_start - ours_pos or theirs_start - theirs_pos:
            ours_same = ours_gap == base_gap
            theirs_same = theirs_gap == base_gap
            if ours_gap == theirs_gap:
                regions.append(("same", ours_pos, ours_start))
            elif ours_same and not theirs_same:
                regions.append(("theirs", theirs_pos, theirs_start))
            elif theirs_same and not ours_same:
                regions.append(("ours", ours_pos, ours_start))
            else:
                regions.append(
                    (
                        "conflict",
                        base_pos,
                        base_start,
                        ours_pos,
                        ours_start,
                        theirs_pos,
                        theirs_start,
                    )
                )
        # Both sides dropped the same base lines: nothing to emit for them.
        if base_end > base_start:
            regions.append(("unchanged", base_start, base_end))
            base_pos = base_end
            ours_pos = ours_end
            theirs_pos = theirs_end
    return regions


def _sync_regions(
    base: list[bytes], ours: list[bytes], theirs: list[bytes]
) -> list[tuple[int, int, int, int, int, int]]:
    """Runs of base lines that survive unchanged in both `ours` and `theirs`.

    Each entry is `(base_start, base_end, ours_start, ours_end, theirs_start,
    theirs_end)`, ending with an empty sentinel at the end of all three.
    """
    ours_blocks = SequenceMatcher(None, base, ours, autojunk=False).get_matching_blocks()
    theirs_blocks = SequenceMatcher(None, base, theirs, autojunk=False).get_matching_blocks()

    found: list[tuple[int, int, int, int, int, int]] = []
    i = j = 0
    while i < len(ours_blocks) and j < len(theirs_blocks):
        ours_base, ours_match, ours_len = ours_blocks[i]
        theirs_base, theirs_match, theirs_len = theirs_blocks[j]
        start = max(ours_base, theirs_base)
        end = min(ours_base + ours_len, theirs_base + theirs_len)
        if start < end:
            length = end - start
            ours_at = ours_match + (start - ours_base)
            theirs_at = theirs_match + (start - theirs_base)
            found.append((start, end, ours_at, ours_at + length, theirs_at, theirs_at + length))
        if ours_base + ours_len < theirs_base + theirs_len:
            i += 1
        else:
            j += 1
    found.append((len(base), len(base), len(ours), len(ours), len(theirs), len(theirs)))
    return found
