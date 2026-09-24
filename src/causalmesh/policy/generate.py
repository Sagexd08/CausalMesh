"""Repo-aware contract generation: `causalmesh policy init`, made to look.

`docs/FRAMEWORK-PLAN.md` describes an `init` that writes a contract "by
reading the repo and any existing AGENTS.md" rather than one empty
`agent_a` role. This is that reading: AGENTS.md's own Layout table --
`| path | description |` rows -- names the directories a person already
decided are worth describing, and each becomes a role. Nothing here infers
an archetype, a budget or a contested path: those are judgment calls this
project's own AGENTS.md leaves to the person writing the contract, and a
generator that guessed them would be inferring behaviour rather than
reading a declaration, which is exactly what `Contract`'s own docstring
says never to do.

A repository with no AGENTS.md, or one with no parseable Layout table,
gets the same static, empty-role template `causalmesh policy init` always
wrote -- this module extends that behaviour, it does not replace it for
repositories the reading does not apply to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["LayoutEntry", "discover_layout", "generate_contract_yaml", "role_id_for"]

_TABLE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$")

# Directory names that make a poor role id on their own -- too generic, or
# already the project's own package name -- get a clearer synonym instead.
_ID_OVERRIDES = {
    "frontend": "web",
    "src": "substrate",
}


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    """One row from AGENTS.md's Layout table: a path and what it holds."""

    path: str
    description: str


def discover_layout(agents_md_path: Path) -> list[LayoutEntry]:
    """Every `| \\`path\\` | description |` row in AGENTS.md's Layout table.

    Table rows outside a fenced code block are indistinguishable from any
    other markdown table by shape alone, so this reads by shape rather than
    by locating a "## Layout" heading first: a project may not head the
    section exactly that way, and a row that names a real repository path
    is the actual signal this cares about, wherever it lives in the file.
    The header-separator row (`|---|---|`) is excluded because its first
    cell is dashes, never a backtick-quoted path.

    Returns an empty list, never raising, when the file is absent or has no
    such table -- the same "absent means nothing to add" default `Contract`
    itself uses for undeclared paths.
    """
    if not agents_md_path.is_file():
        return []
    entries = []
    for line in agents_md_path.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW.match(line)
        if match is None:
            continue
        path, description = match.groups()
        entries.append(LayoutEntry(path=path, description=description))
    return entries


_MARKDOWN_EMPHASIS = re.compile(r"\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`")


def _plain_text(description: str) -> str:
    """Strip markdown emphasis so a table-cell description reads cleanly as

    a YAML comment. `**Do not lint or reformat.**` becomes `Do not lint or
    reformat.` -- the words are what a comment needs, not the markup that
    made them bold in a table cell.
    """

    def unwrap(match: re.Match[str]) -> str:
        return next(group for group in match.groups() if group is not None)

    return _MARKDOWN_EMPHASIS.sub(unwrap, description)


def role_id_for(path: str) -> str:
    """A plausible role id from a declared path.

    The final real path segment, lower-cased and stripped of extension --
    `src/causalmesh/policy/` names `policy`, `README.md` names `readme`.
    Generic or ambiguous segments are overridden with a clearer synonym
    (`frontend/` becomes `web`, matching what a person actually wrote for
    this exact repository) rather than left as a name nobody would choose.
    """
    trimmed = path.rstrip("/")
    segment = trimmed.rsplit("/", 1)[-1]
    stem = segment.rsplit(".", 1)[0] if "." in segment else segment
    stem = stem.lower()
    return _ID_OVERRIDES.get(stem, stem)


def _top_level_entries(entries: list[LayoutEntry]) -> list[LayoutEntry]:
    """Entries whose path is not itself owned by an earlier, shorter entry.

    AGENTS.md's own Layout table declares both `src/causalmesh/` and
    `src/causalmesh/policy/` -- the second is a carve-out of the first, the
    same "longest declaration wins" relationship `Contract.owner_of`
    already encodes for ownership. Generating a separate top-level role for
    every nested row would produce a contract with as many roles as
    directories, most of them redundant; keeping only the top-level
    entries and letting a person carve out exceptions by hand matches how
    this project's own contract was actually written.
    """
    normalized = [entry.path.rstrip("/") + "/" for entry in entries]
    top_level = []
    for index, entry in enumerate(entries):
        candidate = normalized[index]
        covered_by_another = any(
            i != index and candidate != other and candidate.startswith(other)
            for i, other in enumerate(normalized)
        )
        if not covered_by_another:
            top_level.append(entry)
    return top_level


def generate_contract_yaml(root: Path) -> str:
    """A starter `causalmesh.yaml`, informed by `root`'s own AGENTS.md.

    Deliberately permissive, the same guarantee the static template makes:
    every generated role owns real paths and nothing is contested, so a
    freshly generated contract does not refuse real work on the first run.
    """
    entries = _top_level_entries(discover_layout(root / "AGENTS.md"))
    if not entries:
        return _STATIC_TEMPLATE

    seen_ids: set[str] = set()
    roles = []
    for entry in entries:
        role_id = role_id_for(entry.path)
        if role_id in seen_ids:
            continue
        seen_ids.add(role_id)
        roles.append((role_id, entry.path, entry.description))

    role_blocks = "\n".join(
        f"  - agent_id: {role_id}\n"
        f"    archetype: writer\n"
        f"    # {_plain_text(description)}\n"
        f"    owns: [{path}]"
        for role_id, path, description in roles
    )

    return f"""\
# causalmesh.yaml - what agents in this repository may do.
#
# Sibling to AGENTS.md, not a replacement. AGENTS.md says what agents should
# do; this says what they are allowed to do, and the gate holds them to it.
#
# Generated from AGENTS.md's own Layout table: one role per top-level path
# it names, owning exactly that path and nothing else. Nobody's archetype,
# budget or allowlist was guessed -- add those by hand where they apply.
# Absent means unrestricted. Check any rule with:
#     causalmesh policy check --agent {roles[0][0]} --kind path --name {roles[0][1].rstrip("/")}
version: 1

roles:
{role_blocks}

  # An agent that spends money. Uncomment to enforce it.
  # - agent_id: buyer
  #   archetype: spender
  #   allow: [api.example.com]      # hosts it may reach; covers subdomains
  #   budget:
  #     usd_total: "5.00"           # quote money, or use an integer
  #     usd_per_call: "0.10"        # the one catastrophic call, refused

policy:
  # C0 none - C1 transcripts - C2 metadata - C3 metadata + enforced claims.
  # Only C3 refuses; the others record what C3 would have done.
  arm: C3

  # Paths that need an exclusive lease before a write.
  contested: {{}}

  # Allowances for the whole run, unless a role declares its own.
  budgets: {{}}
    # tokens: 200000

evidence:
  sign: true
"""


_STATIC_TEMPLATE = """\
# causalmesh.yaml - what agents in this repository may do.
#
# Sibling to AGENTS.md, not a replacement. AGENTS.md says what agents should
# do; this says what they are allowed to do, and the gate holds them to it.
#
# Absent means unrestricted. Declare the parts you care about; the rest keeps
# working. Check any rule with:
#     causalmesh policy check --agent agent_a --kind path --name src/config.py
version: 1

roles:
  - agent_id: agent_a
    archetype: writer
    # Paths this agent owns. A directory covers everything under it, and a
    # longer declaration wins, so you can carve one file out of a directory.
    owns: []

  # An agent that spends money. Uncomment to enforce it.
  # - agent_id: buyer
  #   archetype: spender
  #   allow: [api.example.com]      # hosts it may reach; covers subdomains
  #   budget:
  #     usd_total: "5.00"           # quote money, or use an integer
  #     usd_per_call: "0.10"        # the one catastrophic call, refused

policy:
  # C0 none - C1 transcripts - C2 metadata - C3 metadata + enforced claims.
  # Only C3 refuses; the others record what C3 would have done.
  arm: C3

  # Paths that need an exclusive lease before a write.
  contested: {}

  # Allowances for the whole run, unless a role declares its own.
  budgets: {}
    # tokens: 200000

evidence:
  sign: true
"""
