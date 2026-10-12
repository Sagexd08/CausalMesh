"""`causalmesh verify --keyring`: a chain re-signed with the attacker's own key.

The attack: edit one event, re-chain the whole log and re-sign every record
with a fresh key the attacker chose, embedding that key in the records. Every
check that uses the keys carried by the records passes, because the attacker
chose them. Only a key ring the operator holds independently can refuse it.

Without `--keyring` the command cannot see this. That limit is documented
(docs/backlog.md) and pinned here as such, so a change that quietly "fixes"
it by guessing is noticed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from causalmesh.cli.main import app
from causalmesh.crypto import GENESIS_HASH, KeyPair, PublicKeyRing, link_event
from causalmesh.verifier import parse_record
from chain_fixtures import ACTORS

pytestmark = pytest.mark.adversarial

runner = CliRunner()
ATTACKER_SEED = b"attacker-seed-0123456789abcdef!!"


def _run_dir(directory: Path, records: list[dict[str, Any]]) -> Path:
    directory.mkdir()
    (directory / "run.json").write_text(
        json.dumps({"arm": "C3", "chain": records}), encoding="utf-8"
    )
    return directory


def _resigned_with_attacker_key(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tamper with one event, then re-chain and re-sign everything as the attacker."""
    attacker = {a: KeyPair.derive(ATTACKER_SEED, a) for a in ACTORS}
    forged: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for index, record in enumerate(records):
        event = parse_record(record).event
        if index == 3:
            event = dataclasses.replace(event, paths=("src/not_what_was_written.py",))
        linked = link_event(event, previous, attacker[event.identity.agent_id])
        previous = linked.chain_hash
        forged.append(linked.to_dict())
    return forged


def _ring_file(path: Path, ring: PublicKeyRing) -> Path:
    """The `keyring.json` format `CausalMesh.export` writes: agent id -> hex public key."""
    path.write_text(json.dumps(ring.to_dict()), encoding="ascii")
    return path


def test_a_resigned_chain_passes_without_a_keyring_and_fails_with_one(
    tmp_path: Path, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
) -> None:
    forged = _run_dir(tmp_path / "forged", _resigned_with_attacker_key(clean_records))
    ring = _ring_file(tmp_path / "keyring.json", key_ring)

    # Documented limitation: embedded keys prove consistency, not identity.
    unpinned = runner.invoke(app, ["verify", "--run", str(forged)])
    assert unpinned.exit_code == 0, unpinned.output
    assert "not pinned" in " ".join(unpinned.output.split())

    pinned = runner.invoke(app, ["verify", "--run", str(forged), "--keyring", str(ring), "--json"])
    assert pinned.exit_code == 1, pinned.output
    data = json.loads(pinned.stdout)
    assert data["valid"] is False
    (entry,) = data["experiments"]["forged"]
    assert entry["valid"] is False
    assert entry["keys"] == "operator"
    assert "the ring holds" in entry["detail"]
    assert entry["detail"].isascii()


def test_the_legitimate_chain_still_verifies_against_the_keyring(
    tmp_path: Path, clean_records: list[dict[str, Any]], key_ring: PublicKeyRing
) -> None:
    honest = _run_dir(tmp_path / "honest", clean_records)
    ring = _ring_file(tmp_path / "keyring.json", key_ring)
    result = runner.invoke(app, ["verify", "--run", str(honest), "--keyring", str(ring), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["attribution_checked"] is True
    assert data["warnings"] == []


def test_the_note_is_printed_once_per_run(
    tmp_path: Path, clean_records: list[dict[str, Any]]
) -> None:
    run = _run_dir(tmp_path / "run", clean_records)
    result = runner.invoke(app, ["verify", "--run", str(run)])
    assert result.exit_code == 0
    assert " ".join(result.output.split()).count("not pinned") == 1
