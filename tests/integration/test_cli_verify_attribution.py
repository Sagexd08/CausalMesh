"""`causalmesh verify` and attribution.

The defect these pin: `verify` built its key ring from the public keys inside
the records it was checking, so a log an attacker rewrote and re-signed with
their own key verified perfectly.  `--keys` takes the operator's ring instead,
and without it the output says, plainly, that attribution was not checked.

Every "forged" chain here is built the way an attacker would: real events,
edited, re-chained and re-signed with a key the attacker chose.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from causalmesh import CausalMesh, Tool
from causalmesh.cli.main import app
from causalmesh.crypto import GENESIS_HASH, KeyPair, link_event
from causalmesh.verifier import parse_record

pytestmark = pytest.mark.integration

runner = CliRunner()

OPERATOR_SEED = b"operator-seed-0123456789abcdef!!"
ATTACKER_SEED = b"attacker-seed-0123456789abcdef!!"
AGENTS = ["coding-agent", "dba-agent"]


def invoke(*args: str):
    return runner.invoke(app, list(args))


def flat(result) -> str:
    """Output with Rich's line wrapping folded away."""
    return " ".join(result.output.split())


def payload(result) -> dict[str, Any]:
    return json.loads(result.stdout)


@pytest.fixture
def contract(tmp_path: Path) -> Path:
    path = tmp_path / "causalmesh.yaml"
    path.write_text(
        "version: 1\nagent:\n  id: coding-agent\nroles:\n"
        "  - agent_id: coding-agent\n    archetype: writer\n    owns:\n      - src/\n"
        "  - agent_id: dba-agent\n    archetype: writer\n    owns:\n      - production/\n"
        "policy:\n  arm: C3\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def honest(tmp_path: Path, contract: Path) -> Path:
    """A real SDK evidence file: two allowed writes and one denial."""
    evidence = tmp_path / "honest.jsonl"
    with CausalMesh.from_config(contract, seed=OPERATOR_SEED, evidence_path=evidence) as mesh:
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content="": "ok", resource_args=["path"])
        )
        for i, path in enumerate(["src/a.py", "src/b.py", "production/db.sql"]):
            mesh.execute(tool="write_file", arguments={"path": path}, now_us=1000 + i)
    return evidence


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _forge(source: Path, destination: Path) -> Path:
    """Edit the log, re-chain it and re-sign every record with the attacker's keys."""
    records = _lines(source)
    keys = {a: KeyPair.derive(ATTACKER_SEED, a) for a in AGENTS}
    previous = GENESIS_HASH
    forged = []
    for record in records:
        event = parse_record(record).event
        if event.payload.get("outcome") == "denied":
            # The point of forging: make the refused write look like it was allowed.
            event = dataclasses.replace(
                event, payload={"tool": "write_file", "outcome": "executed"}
            )
        chained = link_event(event, previous, keys[event.identity.agent_id])
        previous = chained.chain_hash
        forged.append(chained.to_dict())
    destination.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in forged), encoding="utf-8"
    )
    return destination


def _operator_keys(directory: Path) -> Path:
    """The operator's ring, built from their seed and not from any log."""
    directory.mkdir(exist_ok=True)
    for agent in AGENTS:
        pair = KeyPair.derive(OPERATOR_SEED, agent)
        (directory / f"{agent}.pub").write_text(pair.public_key_hex + "\n", encoding="ascii")
    return directory


class TestWithoutAnOperatorRing:
    def test_a_resigned_forgery_passes_and_the_output_says_attribution_was_not_checked(
        self, tmp_path: Path, honest: Path
    ) -> None:
        forged = _forge(honest, tmp_path / "forged.jsonl")
        result = invoke("verify", "--evidence", str(forged))

        assert result.exit_code == 0, "documented limitation: an embedded ring cannot see this"
        text = flat(result)
        assert "attribution NOT checked" in text
        assert "INTACT" in text
        assert "VERIFIED" not in text, "the word must not claim more than was proven"

    def test_the_json_says_so_too(self, honest: Path) -> None:
        result = invoke("verify", "--evidence", str(honest), "--json")
        data = payload(result)
        assert result.exit_code == 0
        assert data["attribution_checked"] is False
        assert data["key_ring"] == {"source": "embedded"}
        assert "attribution NOT checked" in data["warnings"][0]

    def test_what_this_command_adds_is_ascii(self, honest: Path) -> None:
        """The table's box drawing is the shared helper's, which asks the console
        what it can encode; every line this command writes itself must be ASCII."""
        from causalmesh.cli.commands_verify import UNATTRIBUTED

        assert UNATTRIBUTED.isascii()
        result = invoke("verify", "--evidence", str(honest))
        prose = [ln for ln in result.output.splitlines() if not set(ln) & set("─│┌┐└┘┬┴├┤┼")]
        assert all(ln.isascii() for ln in prose), prose

    def test_require_keys_refuses_to_run_without_them(self, honest: Path) -> None:
        result = invoke("verify", "--evidence", str(honest), "--require-keys")
        assert result.exit_code == 2
        assert "--keys" in flat(result)


class TestWithTheOperatorsRing:
    def test_the_same_forgery_fails(self, tmp_path: Path, honest: Path) -> None:
        forged = _forge(honest, tmp_path / "forged.jsonl")
        result = invoke(
            "verify", "--evidence", str(forged), "--keys", str(_operator_keys(tmp_path / "keys"))
        )
        assert result.exit_code == 1
        text = flat(result)
        assert "FAILED" in text
        assert "the ring holds" in text, "the failure should name the key mismatch"

    def test_the_honest_log_is_verified_and_the_ring_is_named(
        self, tmp_path: Path, honest: Path
    ) -> None:
        result = invoke(
            "verify",
            "--evidence",
            str(honest),
            "--keys",
            str(_operator_keys(tmp_path / "keys")),
            "--require-keys",
            "--json",
        )
        data = payload(result)
        assert result.exit_code == 0, result.output
        assert data["attribution_checked"] is True
        assert data["key_ring"]["source"] == "operator"
        assert data["key_ring"]["actors"] == AGENTS
        assert len(data["key_ring"]["fingerprint"]) == 64
        assert data["warnings"] == []

    def test_the_table_says_verified_only_now(self, tmp_path: Path, honest: Path) -> None:
        result = invoke(
            "verify", "--evidence", str(honest), "--keys", str(_operator_keys(tmp_path / "keys"))
        )
        assert "VERIFIED" in flat(result)
        assert "NOT checked" not in flat(result)

    def test_an_actor_missing_from_the_ring_fails(self, tmp_path: Path, honest: Path) -> None:
        keys = _operator_keys(tmp_path / "keys")
        (keys / "dba-agent.pub").unlink()
        result = invoke("verify", "--evidence", str(honest), "--keys", str(keys))
        # dba-agent signs nothing in this log, so the ring still covers every signer...
        assert result.exit_code == 0
        (keys / "coding-agent.pub").unlink()
        (keys / "other.pub").write_text("00" * 32, encoding="ascii")
        result = invoke("verify", "--evidence", str(honest), "--keys", str(keys))
        # ...and a ring that lacks a signer does not.
        assert result.exit_code == 1
        assert "not in the key ring" in flat(result)

    def test_a_run_artifact_is_checked_against_the_ring_too(
        self, tmp_path: Path, honest: Path
    ) -> None:
        forged = _forge(honest, tmp_path / "forged.jsonl")
        export = tmp_path / "run"
        export.mkdir()
        (export / "run.json").write_text(
            json.dumps({"arm": "C3", "chain": _lines(forged)}), encoding="utf-8"
        )
        keys = _operator_keys(tmp_path / "keys")
        assert invoke("verify", "--run", str(export)).exit_code == 0
        assert invoke("verify", "--run", str(export), "--keys", str(keys)).exit_code == 1


class TestKeyRingFormats:
    def test_seed_files_in_identity_keys_format_work(self, tmp_path: Path, honest: Path) -> None:
        # identity.keys holds raw 32-byte seeds; here the operator seed is not one,
        # so derive the per-agent seed material the same way the loader reads it.
        directory = tmp_path / "seeds"
        directory.mkdir()
        raw = {a: bytes([i + 1]) * 32 for i, a in enumerate(AGENTS)}
        for agent, seed in raw.items():
            (directory / f"{agent}.key").write_bytes(seed)
        result = invoke("verify", "--evidence", str(honest), "--keys", str(directory), "--json")
        # The log was signed with derived keys, not these seeds: attribution must fail.
        assert result.exit_code == 1
        assert payload(result)["key_ring"]["actors"] == AGENTS

    def test_a_relay_style_keyring_json_works(self, tmp_path: Path, honest: Path) -> None:
        ring = {a: KeyPair.derive(OPERATOR_SEED, a).public_key_hex for a in AGENTS}
        path = tmp_path / "keyring.json"
        path.write_text(json.dumps(ring), encoding="utf-8")
        assert invoke("verify", "--evidence", str(honest), "--keys", str(path)).exit_code == 0

    def test_two_files_that_disagree_are_refused(self, tmp_path: Path, honest: Path) -> None:
        keys = _operator_keys(tmp_path / "keys")
        other = KeyPair.derive(ATTACKER_SEED, "coding-agent").public_key_hex
        (keys / "keyring.json").write_text(json.dumps({"coding-agent": other}), encoding="utf-8")
        result = invoke("verify", "--evidence", str(honest), "--keys", str(keys))
        assert result.exit_code == 2
        assert "different keys" in flat(result)

    def test_an_empty_or_missing_ring_is_a_usage_error(self, tmp_path: Path, honest: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert invoke("verify", "--evidence", str(honest), "--keys", str(empty)).exit_code == 2
        missing = tmp_path / "missing"
        assert invoke("verify", "--evidence", str(honest), "--keys", str(missing)).exit_code == 2

    def test_a_malformed_public_key_is_refused(self, tmp_path: Path, honest: Path) -> None:
        keys = tmp_path / "keys"
        keys.mkdir()
        (keys / "coding-agent.pub").write_text("not-hex", encoding="ascii")
        assert invoke("verify", "--evidence", str(honest), "--keys", str(keys)).exit_code == 2


class TestEvidenceFileDamage:
    def test_a_torn_final_line_fails_and_says_so(self, tmp_path: Path, honest: Path) -> None:
        data = honest.read_bytes()
        honest.write_bytes(data[: len(data) - 40])
        result = invoke(
            "verify", "--evidence", str(honest), "--keys", str(_operator_keys(tmp_path / "k"))
        )
        assert result.exit_code == 1
        assert "incomplete" in flat(result)

    def test_damage_in_the_middle_fails(self, tmp_path: Path, honest: Path) -> None:
        lines = honest.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1][:30]
        honest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = invoke("verify", "--evidence", str(honest))
        assert result.exit_code == 1
        assert "line 2" in flat(result)

    def test_a_tampered_record_fails_even_without_keys(self, honest: Path) -> None:
        lines = honest.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["event"]["payload"]["outcome"] = "denied"
        lines[0] = json.dumps(record, sort_keys=True)
        honest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert invoke("verify", "--evidence", str(honest)).exit_code == 1

    def test_suffix_truncation_is_caught_only_by_an_anchor(
        self, tmp_path: Path, honest: Path
    ) -> None:
        records = _lines(honest)
        head = records[-1]["chain_hash"]
        honest.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records[:-1]), encoding="utf-8"
        )
        assert invoke("verify", "--evidence", str(honest)).exit_code == 0  # the known gap
        result = invoke("verify", "--evidence", str(honest), "--anchor-head", head)
        assert result.exit_code == 1
        assert "truncated" in flat(result)

    def test_a_matching_anchor_passes(self, honest: Path) -> None:
        head = _lines(honest)[-1]["chain_hash"]
        assert invoke("verify", "--evidence", str(honest), "--anchor-head", head).exit_code == 0


class TestUsage:
    def test_evidence_cannot_be_combined_with_run(self, tmp_path: Path, honest: Path) -> None:
        result = invoke("verify", "--evidence", str(honest), "--run", str(tmp_path))
        assert result.exit_code == 2

    def test_a_missing_evidence_file_is_a_usage_error(self, tmp_path: Path) -> None:
        assert invoke("verify", "--evidence", str(tmp_path / "nope.jsonl")).exit_code == 2

    def test_anchor_head_needs_evidence(self, tmp_path: Path) -> None:
        assert invoke("verify", "--anchor-head", "ab", "--root", str(tmp_path)).exit_code == 2
