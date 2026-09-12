"""Clean-room verification from exported artifacts (spec §26, §82).

The requirement is that a third party can take an export elsewhere and check
it with no access to the relay, the database or the originating source tree.
That claim is only credible if it is exercised the way a third party would
exercise it, so this test runs the verifier in a **separate subprocess** with
a **different working directory**, reading only the exported files.

Testing it in-process would prove much less: the relay's absence would be
incidental rather than enforced, and an accidental dependency on a live
service would go unnoticed until someone actually tried to reproduce a
result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from causalmesh.crypto.chain import GENESIS_HASH, link_event
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.events.schema import Event, EventIdentity, EventType

pytestmark = pytest.mark.integration

SEED = b"causalmesh-cleanroom-integration"
SRC_ROOT = Path(__file__).resolve().parents[2] / "src"

SCRIPT: tuple[tuple[str, EventType, tuple[str, ...]], ...] = (
    ("agent_a", EventType.READ, ("src/schema.py",)),
    ("agent_a", EventType.WRITE, ("src/schema.py",)),
    ("agent_b", EventType.READ, ("src/schema.py",)),
    ("agent_b", EventType.WRITE, ("src/api.py",)),
)


def cleanroom_env() -> dict[str, str]:
    """Environment for the clean room.

    The package is reached through PYTHONPATH rather than an installed
    distribution, so the export is checked against the source under test. The
    rest of the environment is inherited: a third party doing this would have
    Python and its installed libraries, and stripping those would test the
    absence of `cryptography` rather than the absence of the relay.
    """
    return {**os.environ, "PYTHONPATH": str(SRC_ROOT)}


def export_chain(destination: Path) -> dict[str, str]:
    """Write a genuine chain plus its key ring and an anchor, as a run export."""
    destination.mkdir(parents=True, exist_ok=True)
    keypairs = {actor: KeyPair.derive(SEED, actor) for actor in ("agent_a", "agent_b")}
    ring = PublicKeyRing.from_keypairs(keypairs)

    previous = GENESIS_HASH
    lines: list[str] = []
    for sequence, (actor, event_type, paths) in enumerate(SCRIPT):
        event = Event(
            event_id=f"evt_{sequence:04d}",
            identity=EventIdentity(
                experiment_id="exp_cleanroom",
                task_id="task_cleanroom",
                run_id="run_001",
                agent_id=actor,
                arm="C3",
            ),
            event_type=event_type,
            sequence=sequence,
            timestamp_us=1_700_000_000_000_000 + sequence * 1_000,
            paths=paths,
        )
        linked = link_event(event, previous, keypairs[actor])
        lines.append(json.dumps(linked.to_dict(), sort_keys=True))
        previous = linked.chain_hash

    (destination / "chain.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (destination / "keyring.json").write_text(json.dumps(ring.to_dict()), encoding="utf-8")
    (destination / "anchors.json").write_text(json.dumps({"3": previous}), encoding="utf-8")
    return {"head": previous}


# Runs inside the clean room: imports only the verification stack.
VERIFY_PROGRAM = """
import json, sys
from pathlib import Path
from causalmesh.crypto import PublicKeyRing
from causalmesh.verifier import load_chain, verify_chain

export = Path(sys.argv[1])
chain_file = sys.argv[2]
use_anchors = sys.argv[3] == "anchors"

records = load_chain(export / chain_file)
ring = PublicKeyRing.from_dict(json.loads((export / "keyring.json").read_text()))
anchors = (
    {int(k): v for k, v in json.loads((export / "anchors.json").read_text()).items()}
    if use_anchors
    else None
)
print(json.dumps(verify_chain(records, ring, anchors=anchors).to_dict()))
"""


def verify_in_cleanroom(
    export: Path, cwd: Path, chain_file: str = "chain.jsonl", *, anchors: bool = False
) -> dict:
    """Run the verifier in a fresh process from an unrelated directory."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            VERIFY_PROGRAM,
            str(export),
            chain_file,
            "anchors" if anchors else "none",
        ],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=cleanroom_env(),
        timeout=120,
    )
    assert result.returncode == 0, f"clean-room verification crashed:\n{result.stderr}"
    return json.loads(result.stdout)


class TestCleanRoom:
    def test_an_exported_chain_verifies_elsewhere(self, tmp_path: Path) -> None:
        export = tmp_path / "export"
        export_chain(export)
        elsewhere = tmp_path / "unrelated_directory"
        elsewhere.mkdir()

        result = verify_in_cleanroom(export, cwd=elsewhere)
        assert result["valid"] is True
        assert result["events"] == len(SCRIPT)

    def test_the_export_needs_only_three_files(self, tmp_path: Path) -> None:
        # Anything more would mean the export is not self-contained.
        export = tmp_path / "export"
        export_chain(export)
        assert {p.name for p in export.iterdir()} == {
            "chain.jsonl",
            "keyring.json",
            "anchors.json",
        }

    def test_anchors_verify_and_close_the_suffix_gap(self, tmp_path: Path) -> None:
        export = tmp_path / "export"
        export_chain(export)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = verify_in_cleanroom(export, cwd=elsewhere, anchors=True)
        assert result["valid"] is True
        assert result["anchor_status"] == "verified"
        assert result["unanchored_suffix"] == 0

    def test_on_disk_tampering_is_caught_in_the_clean_room(self, tmp_path: Path) -> None:
        export = tmp_path / "export"
        export_chain(export)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        # Edit the exported file the way an attacker with disk access would.
        lines = (export / "chain.jsonl").read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["event"]["paths"] = ["src/attacker_owned.py"]
        lines[1] = json.dumps(record, sort_keys=True)
        (export / "tampered.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_in_cleanroom(export, cwd=elsewhere, chain_file="tampered.jsonl")
        assert result["valid"] is False
        assert result["chain_failures"] >= 1
        assert result["failures"][0]["index"] == 1

    def test_truncation_needs_the_anchor_to_be_caught(self, tmp_path: Path) -> None:
        """Both halves of the §27 truncation row, end to end on real files."""
        export = tmp_path / "export"
        export_chain(export)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        lines = (export / "chain.jsonl").read_text(encoding="utf-8").splitlines()
        (export / "truncated.jsonl").write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

        without = verify_in_cleanroom(export, cwd=elsewhere, chain_file="truncated.jsonl")
        assert without["valid"] is True, "truncation is genuinely undetectable without an anchor"
        assert without["unanchored_suffix"] == 2

        with_anchor = verify_in_cleanroom(
            export, cwd=elsewhere, chain_file="truncated.jsonl", anchors=True
        )
        assert with_anchor["valid"] is False
        assert with_anchor["anchor_status"] == "mismatch"

    def test_the_verifier_does_not_import_the_relay(self, tmp_path: Path) -> None:
        """§26 stated as an executable constraint, not a convention."""
        program = (
            "import sys, json;"
            "import causalmesh.verifier;"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('causalmesh'))))"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=cleanroom_env(),
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        loaded = json.loads(result.stdout)
        assert not [
            m
            for m in loaded
            if any(part in m for part in (".relay", ".scheduler", ".storage", ".agents"))
        ], f"verifier pulled in runtime modules: {loaded}"
