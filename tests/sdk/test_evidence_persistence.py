"""Durable SDK evidence: the JSONL file, resume, torn writes, export.

Each class pins one promise ``causalmesh.sdk.evidence`` makes.  The failure
cases are the point: a persistence layer that only works when nothing goes
wrong is not evidence storage.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.crypto.chain import GENESIS_HASH
from causalmesh.sdk import (
    EvidenceCorruptError,
    EvidenceError,
    EvidenceLockedError,
    EvidenceUnavailableError,
    load_evidence,
)
from causalmesh.sdk.evidence import scan_evidence
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.unit

SEED = b"evidence-test-seed-0123456789abc"
NOW = 1_000_000


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "causalmesh.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "agent:",
                "  id: coding-agent",
                "roles:",
                "  - agent_id: coding-agent",
                "    archetype: writer",
                "    owns:",
                '      - "src/"',
                "  - agent_id: dba-agent",
                "    archetype: writer",
                "    owns:",
                '      - "production/"',
                "policy:",
                "  arm: C3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _mesh(tmp_path: Path, evidence: Path | None = None, **kwargs: Any) -> CausalMesh:
    kwargs.setdefault("seed", SEED)
    mesh = CausalMesh.from_config(_contract(tmp_path), evidence_path=evidence, **kwargs)
    mesh.register_tool(
        Tool(name="write_file", handler=lambda path, content="": "ok", resource_args=["path"])
    )
    return mesh


def _write(mesh: CausalMesh, index: int, *, agent: str | None = None) -> Any:
    return mesh.execute(
        agent_id=agent,
        tool="write_file",
        arguments={"path": f"src/f{index}.py", "content": "x"},
        now_us=NOW + index,
    )


def _ring(tmp_path: Path):
    """The operator's ring: built from the seed, never from the file."""
    from causalmesh.crypto import KeyPair, PublicKeyRing

    agents = ["coding-agent", "dba-agent"]
    return PublicKeyRing.from_keypairs({a: KeyPair.derive(SEED, a) for a in agents})


class TestPerEventWrite:
    def test_every_event_is_on_disk_before_the_call_returns(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            for i in range(3):
                assert _write(mesh, i).recorded
                # Read through a separate handle while the session is still open.
                assert len(scan_evidence(evidence).records) == i + 1

    def test_the_file_verifies_against_the_operators_ring(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            _write(mesh, 0)
            mesh.execute(
                tool="write_file",
                arguments={"path": "production/db.sql", "content": "x"},
                now_us=NOW + 9,
            )
        records = load_evidence(evidence)
        assert [r["event"]["event_type"] for r in records] == ["WRITE", "FAILURE"]
        assert records[0]["previous_hash"] == GENESIS_HASH
        assert verify_chain(records, _ring(tmp_path)).valid

    def test_a_denied_call_is_persisted_too(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            result = mesh.execute(
                tool="write_file", arguments={"path": "production/x", "content": ""}, now_us=NOW
            )
            assert result.denied
        assert load_evidence(evidence)[0]["event"]["payload"]["outcome"] == "denied"

    def test_non_ascii_content_round_trips(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            mesh.execute(
                tool="write_file", arguments={"path": "src/café.py", "content": ""}, now_us=NOW
            )
        records = load_evidence(evidence)
        assert records[0]["event"]["paths"] == ["src/café.py"]
        assert verify_chain(records, _ring(tmp_path)).valid

    def test_memory_only_sessions_are_unchanged(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        assert mesh.evidence_path is None
        assert _write(mesh, 0).recorded
        assert len(mesh.audit_events()) == 1


class TestResume:
    def test_a_restart_continues_the_same_chain(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as first:
            for i in range(3):
                _write(first, i)
            head = first.evidence_head
        with _mesh(tmp_path, evidence) as second:
            assert second.evidence_head == head
            for i in range(3, 5):
                assert _write(second, i).recorded

        records = load_evidence(evidence)
        assert [r["event"]["sequence"] for r in records] == [0, 1, 2, 3, 4]
        assert records[3]["previous_hash"] == records[2]["chain_hash"]
        ids = [r["event"]["event_id"] for r in records]
        assert len(set(ids)) == 5, f"event ids collided across the restart: {ids}"
        result = verify_chain(records, _ring(tmp_path))
        assert result.valid, result.failures

    def test_a_resumed_chain_is_bit_identical_to_an_uninterrupted_one(self, tmp_path: Path) -> None:
        split = tmp_path / "split.jsonl"
        whole = tmp_path / "whole.jsonl"
        with _mesh(tmp_path, split) as a:
            for i in range(2):
                _write(a, i)
        with _mesh(tmp_path, split) as b:
            for i in range(2, 4):
                _write(b, i)
        with _mesh(tmp_path, whole) as c:
            for i in range(4):
                _write(c, i)
        assert split.read_bytes() == whole.read_bytes()

    def test_resume_refuses_a_file_signed_by_other_keys(self, tmp_path: Path) -> None:
        """Random keys change every session, so an old file cannot be extended."""
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence, seed=None) as first:
            _write(first, 0)
        before = evidence.read_bytes()
        with pytest.raises(EvidenceCorruptError, match="does not verify against this session"):
            _mesh(tmp_path, evidence, seed=None)
        assert evidence.read_bytes() == before, "a refused resume must not touch the file"

    def test_resume_refuses_another_runs_file(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence, run_id="run-a") as first:
            _write(first, 0)
        with pytest.raises(EvidenceCorruptError, match="belongs to run 'run-a'"):
            _mesh(tmp_path, evidence, run_id="run-b")

    def test_a_refused_open_releases_the_lock(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence, run_id="run-a") as first:
            _write(first, 0)
        with pytest.raises(EvidenceCorruptError):
            _mesh(tmp_path, evidence, run_id="run-b")
        with _mesh(tmp_path, evidence, run_id="run-a") as again:
            assert _write(again, 1).recorded


class TestTampering:
    def _record(self, tmp_path: Path) -> Path:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            for i in range(3):
                _write(mesh, i)
        return evidence

    def test_an_edited_record_stops_the_resume(self, tmp_path: Path) -> None:
        evidence = self._record(tmp_path)
        lines = evidence.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["event"]["payload"]["outcome"] = "denied"
        lines[1] = json.dumps(record, sort_keys=True)
        evidence.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(EvidenceCorruptError, match="chain_break"):
            _mesh(tmp_path, evidence)

    def test_a_deleted_middle_record_stops_the_resume(self, tmp_path: Path) -> None:
        evidence = self._record(tmp_path)
        lines = evidence.read_text(encoding="utf-8").splitlines()
        del lines[1]
        evidence.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceCorruptError):
            _mesh(tmp_path, evidence)

    def test_a_resigned_forgery_stops_the_resume(self, tmp_path: Path) -> None:
        """Every record re-signed with an attacker's seed: the ring says no."""
        forged = tmp_path / "forged.jsonl"
        with _mesh(tmp_path, forged, seed=b"attacker-seed-0123456789abcdef!") as mesh:
            for i in range(3):
                _write(mesh, i)
        with pytest.raises(EvidenceCorruptError, match="key_mismatch"):
            _mesh(tmp_path, forged)

    def test_damage_in_the_middle_is_not_recoverable(self, tmp_path: Path) -> None:
        evidence = self._record(tmp_path)
        lines = evidence.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1][:40]
        evidence.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(EvidenceCorruptError, match="line 2") as info:
            _mesh(tmp_path, evidence, recover_evidence=True)
        assert not info.value.torn


class TestTornWrite:
    """A crash mid-write leaves a final line that is not a whole record."""

    def _torn(self, tmp_path: Path) -> tuple[Path, int]:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            for i in range(3):
                _write(mesh, i)
        complete = evidence.read_bytes()
        last = complete.rstrip(b"\n").split(b"\n")[-1]
        evidence.write_bytes(complete[: len(complete) - len(last) // 2 - 1])
        return evidence, len(last) // 2

    def test_opening_a_torn_file_is_refused_by_default(self, tmp_path: Path) -> None:
        evidence, _ = self._torn(tmp_path)
        before = evidence.read_bytes()
        with pytest.raises(EvidenceCorruptError, match="last line is incomplete") as info:
            _mesh(tmp_path, evidence)
        assert info.value.torn
        assert evidence.read_bytes() == before, "the refusal must not repair anything"

    def test_load_evidence_refuses_a_torn_tail(self, tmp_path: Path) -> None:
        evidence, _ = self._torn(tmp_path)
        with pytest.raises(EvidenceCorruptError) as info:
            load_evidence(evidence)
        assert info.value.torn
        assert len(load_evidence(evidence, allow_torn_tail=True)) == 2

    def test_recovery_keeps_the_fragment_and_continues_the_chain(self, tmp_path: Path) -> None:
        evidence, torn_bytes = self._torn(tmp_path)
        fragment = evidence.read_bytes().rsplit(b"\n", 1)[1]
        with _mesh(tmp_path, evidence, recover_evidence=True) as mesh:
            recovery = mesh.evidence_recovery
            assert recovery is not None
            assert recovery["records_kept"] == 2
            assert recovery["torn_bytes"] == len(fragment)
            assert _write(mesh, 9).recorded

        sidecar = evidence.with_name(evidence.name + ".torn")
        assert sidecar.read_bytes() == fragment + b"\n", "the torn write is evidence; keep it"
        records = load_evidence(evidence)
        assert [r["event"]["sequence"] for r in records] == [0, 1, 2]
        assert verify_chain(records, _ring(tmp_path)).valid

    def test_a_complete_record_missing_only_its_newline_is_not_torn(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            for i in range(2):
                _write(mesh, i)
        evidence.write_bytes(evidence.read_bytes().rstrip(b"\n"))
        with _mesh(tmp_path, evidence) as mesh:
            assert _write(mesh, 2).recorded
        records = load_evidence(evidence)
        assert len(records) == 3
        assert verify_chain(records, _ring(tmp_path)).valid

    def test_recovery_on_an_intact_file_reports_nothing(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with _mesh(tmp_path, evidence) as mesh:
            _write(mesh, 0)
        with _mesh(tmp_path, evidence, recover_evidence=True) as mesh:
            assert mesh.evidence_recovery is None


class TestFailClosed:
    def test_a_failed_write_stops_later_calls_and_leaves_a_valid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        evidence = tmp_path / "ev.jsonl"
        ran: list[str] = []
        mesh = CausalMesh.from_config(_contract(tmp_path), seed=SEED, evidence_path=evidence)
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content="": ran.append(path),
                resource_args=["path"],
            )
        )
        assert _write(mesh, 0).recorded

        def boom(fd: int) -> None:
            raise OSError("disk on fire")

        monkeypatch.setattr(os, "fsync", boom)
        failed = _write(mesh, 1)
        assert failed.recorded is False
        assert "disk on fire" in (failed.audit_error or "")
        monkeypatch.undo()

        with pytest.raises(EvidenceUnavailableError, match="no further calls"):
            _write(mesh, 2)
        assert ran == ["src/f0.py", "src/f1.py"], "the handler must not run after the failure"

        mesh.close()
        records = load_evidence(evidence)
        assert len(records) == 1, "the failed write was cut back off the file"
        assert verify_chain(records, _ring(tmp_path)).valid
        with _mesh(tmp_path, evidence) as again:
            assert _write(again, 5).recorded

    def test_a_closed_session_refuses_to_run_tools(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, tmp_path / "ev.jsonl")
        mesh.close()
        mesh.close()  # idempotent
        with pytest.raises(EvidenceUnavailableError, match="closed"):
            _write(mesh, 0)


class TestSingleWriter:
    def test_a_second_live_session_on_the_same_file_is_refused(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        with (
            _mesh(tmp_path, evidence),
            pytest.raises(EvidenceLockedError, match="another session"),
        ):
            _mesh(tmp_path, evidence)
        with _mesh(tmp_path, evidence) as reopened:
            assert reopened.evidence_path == evidence


class TestConcurrency:
    def test_parallel_calls_produce_one_valid_chain(self, tmp_path: Path) -> None:
        evidence = tmp_path / "ev.jsonl"
        threads_n, calls_n = 8, 20
        errors: list[BaseException] = []
        with _mesh(tmp_path, evidence) as mesh:

            def work(worker: int) -> None:
                try:
                    for i in range(calls_n):
                        result = mesh.execute(
                            tool="write_file",
                            arguments={"path": f"src/w{worker}_{i}.py", "content": ""},
                            now_us=NOW,
                        )
                        assert result.recorded, result.audit_error
                except BaseException as exc:  # noqa: BLE001 - reported below
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(n,)) for n in range(threads_n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert not errors, errors

        records = load_evidence(evidence)
        assert len(records) == threads_n * calls_n
        assert [r["event"]["sequence"] for r in records] == list(range(len(records)))
        assert len({r["event"]["event_id"] for r in records}) == len(records)
        result = verify_chain(records, _ring(tmp_path))
        assert result.valid, result.failures[:3]


class TestExport:
    def test_export_and_load_round_trip(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        for i in range(3):
            _write(mesh, i)
        out = mesh.export_evidence(tmp_path / "out" / "export.jsonl")
        assert not out.with_name(out.name + ".tmp").exists()
        assert CausalMesh.load_evidence(out) == mesh.audit_events()
        assert verify_chain(load_evidence(out), _ring(tmp_path)).valid

    def test_a_persisted_session_can_export_a_copy(self, tmp_path: Path) -> None:
        with _mesh(tmp_path, tmp_path / "ev.jsonl") as mesh:
            _write(mesh, 0)
            copy = mesh.export_evidence(tmp_path / "copy.jsonl")
        assert copy.read_bytes() == (tmp_path / "ev.jsonl").read_bytes()

    def test_export_over_the_live_file_is_refused(self, tmp_path: Path) -> None:
        with _mesh(tmp_path, tmp_path / "ev.jsonl") as mesh:
            _write(mesh, 0)
            with pytest.raises(EvidenceError, match="live evidence file"):
                mesh.export_evidence(tmp_path / "ev.jsonl")

    def test_export_public_keys_writes_public_material_only(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        files = mesh.export_public_keys(tmp_path / "keys")
        assert sorted(f.name for f in files) == ["coding-agent.pub", "dba-agent.pub"]
        ring = _ring(tmp_path)
        for f in files:
            assert f.read_text(encoding="ascii").strip() == ring.keys[f.stem]

    def test_loading_a_missing_file_is_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(EvidenceError, match="no evidence file"):
            load_evidence(tmp_path / "nope.jsonl")
