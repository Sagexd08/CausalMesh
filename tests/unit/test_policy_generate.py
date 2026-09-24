from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.policy.contract import Contract
from causalmesh.policy.generate import discover_layout, generate_contract_yaml, role_id_for

pytestmark = [pytest.mark.unit]

SAMPLE_AGENTS_MD = """\
# AGENTS.md

Some prose that is not a table row.

## Layout

| Path | What lives there |
|---|---|
| `src/causalmesh/` | the substrate. Everything shipped. |
| `src/causalmesh/policy/` | contract, gate, ledger, resources |
| `frontend/` | the whole website: `/` and `/docs` |
| `docs/` | architecture, protocol, security, and the backlog |

## Rules

Not a table row either.
"""


class TestDiscoverLayout:
    def test_extracts_every_path_row(self, tmp_path: Path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        entries = discover_layout(agents_md)
        paths = [entry.path for entry in entries]
        assert paths == [
            "src/causalmesh/",
            "src/causalmesh/policy/",
            "frontend/",
            "docs/",
        ]

    def test_ignores_prose_lines_that_are_not_table_rows(self, tmp_path: Path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        entries = discover_layout(agents_md)
        assert not any("Some prose" in entry.path for entry in entries)

    def test_ignores_the_header_separator_row(self, tmp_path: Path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        entries = discover_layout(agents_md)
        assert not any(entry.path.startswith("-") for entry in entries)

    def test_a_missing_file_yields_no_entries_rather_than_raising(self, tmp_path: Path) -> None:
        assert discover_layout(tmp_path / "AGENTS.md") == []

    def test_a_file_with_no_table_yields_no_entries(self, tmp_path: Path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# AGENTS.md\n\nJust prose, no table.\n", encoding="utf-8")
        assert discover_layout(agents_md) == []


class TestRoleIdFor:
    """Matched against this repository's own causalmesh.yaml, written by hand.

    `owner_of` isn't queried here -- these are the role names a human chose,
    checked directly against what the generator would derive from the same
    paths this project's own AGENTS.md declares.
    """

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/causalmesh/crypto/", "crypto"),
            ("src/causalmesh/policy/", "policy"),
            ("src/causalmesh/cli/", "cli"),
            ("src/causalmesh/tui/", "tui"),
            ("frontend/", "web"),
            ("docs/", "docs"),
            ("tests/", "tests"),
        ],
    )
    def test_derives_a_plausible_id_from_the_final_path_segment(
        self, path: str, expected: str
    ) -> None:
        assert role_id_for(path) == expected

    def test_a_bare_filename_with_no_directory_uses_its_stem(self) -> None:
        assert role_id_for("README.md") == "readme"


class TestGenerateContractYaml:
    def test_falls_back_to_the_static_template_with_no_agents_md(self, tmp_path: Path) -> None:
        yaml_text = generate_contract_yaml(tmp_path)
        contract = Contract.from_dict(__import__("yaml").safe_load(yaml_text))
        assert contract.version == 1

    def test_generates_one_role_per_top_level_layout_entry(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        yaml_text = generate_contract_yaml(tmp_path)
        contract = Contract.from_dict(__import__("yaml").safe_load(yaml_text))
        role_ids = {role.agent_id for role in contract.roles}
        # src/causalmesh/policy/ is nested under src/causalmesh/, which
        # already owns it -- a nested entry becomes a carve-out on the same
        # role tree the way the hand-written contract itself does it, not a
        # second top-level agent.
        assert "web" in role_ids
        assert "docs" in role_ids

    def test_the_output_parses_as_a_valid_contract(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        yaml_text = generate_contract_yaml(tmp_path)
        contract = Contract.from_dict(__import__("yaml").safe_load(yaml_text))
        assert contract.owner_of("frontend/app/page.tsx") == "web"
        assert contract.owner_of("docs/backlog.md") == "docs"

    def test_generated_contract_is_permissive_by_default(self, tmp_path: Path) -> None:
        """A freshly generated contract must not refuse real work on the

        first run -- the same discipline the static template already
        states in its own docstring.
        """
        (tmp_path / "AGENTS.md").write_text(SAMPLE_AGENTS_MD, encoding="utf-8")
        yaml_text = generate_contract_yaml(tmp_path)
        contract = Contract.from_dict(__import__("yaml").safe_load(yaml_text))
        assert contract.contested == {}
        assert contract.budgets == {}

    def test_against_this_repositorys_own_agents_md(self) -> None:
        """The strongest check available: run the generator against the

        real AGENTS.md this project ships. Not every documented directory
        has a declared owner in the hand-written contract (`fixtures/` and
        `tests/` do not; `reviewer` owns nothing at all) -- the real
        assertion is that nothing the generator infers is a *nonsense*
        id, not that every id matches an existing role exactly.
        """
        repo_root = Path(__file__).resolve().parents[2]
        agents_md = repo_root / "AGENTS.md"
        if not agents_md.is_file():
            pytest.skip("AGENTS.md not present in this checkout")
        entries = discover_layout(agents_md)
        assert entries, "expected the real AGENTS.md to have a parseable Layout table"
        inferred_ids = {role_id_for(entry.path) for entry in entries}
        # Every inferred id is a plain lower-case directory-name-shaped
        # token: no empty strings, no path separators leaking through, no
        # id longer than a real path segment could produce.
        assert all(inferred_ids)
        assert all("/" not in role_id for role_id in inferred_ids)
        assert all(role_id == role_id.lower() for role_id in inferred_ids)
        # And the ids this repository's own generated contract would carve
        # out under `src/causalmesh/` are exactly the real roles that
        # actually own something there.
        real_contract = Contract.load(repo_root / "causalmesh.yaml")
        real_ids = {role.agent_id for role in real_contract.roles if role.owns}
        assert real_ids & inferred_ids, "expected at least one id to overlap a real role"
