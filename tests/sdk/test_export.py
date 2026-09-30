"""Export of an SDK session's evidence, checked by the real verifier.

``CausalMesh.export`` writes ``run.json`` and ``keyring.json``. Nothing here
calls a verification helper of the test's own: every check goes through
``causalmesh verify --run``, the command an auditor would run, because an
export that only the code that wrote it can read is not evidence.

The mutation checks are the point. The clean export passing proves little; a
tampered event, and a whole chain re-signed under a key the operator never
issued, each have to fail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from causalmesh import CausalMesh, Tool
from causalmesh.cli.main import app as cli_app
from causalmesh.sdk.errors import ConfigurationError

pytestmark = pytest.mark.unit

SEED = b"export-seed-0000000000000000000a"
FOREIGN_SEED = b"export-seed-0000000000000000000b"

CONTRACT = """\
version: 1
agent:
  id: coding-agent
roles:
  - agent_id: coding-agent
    archetype: writer
    owns:
      - "src/"
  - agent_id: dba-agent
    archetype: writer
    owns:
      - "production/"
policy:
  arm: C3
"""

runner = CliRunner()


def _config(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "causalmesh.yaml"
    path.write_text(CONTRACT, encoding="utf-8")
    return path


def _session(tmp_path: Path, *, seed: bytes = SEED, **kwargs: Any) -> CausalMesh:
    mesh = CausalMesh.from_config(_config(tmp_path), seed=seed, **kwargs)
    mesh.register_tool(
        Tool(name="write_file", handler=lambda path, content="": "ok", resource_args=["path"])
    )
    return mesh


def _calls(mesh: CausalMesh) -> None:
    """Two allowed calls and one refusal, so the chain holds both outcomes."""
    mesh.execute(tool="write_file", arguments={"path": "src/a.py"})
    mesh.execute(agent_id="dba-agent", tool="write_file", arguments={"path": "production/x.sql"})
    mesh.execute(tool="write_file", arguments={"path": "production/y.sql"})  # refused: not owned


def _verify(directory: Path) -> tuple[int, dict[str, Any]]:
    result = runner.invoke(cli_app, ["verify", "--run", str(directory), "--json"])
    return result.exit_code, json.loads(result.stdout)


def _run(directory: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    return loaded


def _write_run(directory: Path, artifact: dict[str, Any]) -> None:
    (directory / "run.json").write_text(json.dumps(artifact), encoding="utf-8")


class TestCleanExport:
    def test_a_clean_export_verifies_through_the_real_verifier(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "export"
        paths = mesh.export(out)
        assert paths["run"] == out / "run.json"
        assert paths["keyring"] == out / "keyring.json"

        code, report = _verify(out)
        assert code == 0, report
        assert report["valid"] is True
        (entry,) = report["experiments"][out.name]
        assert entry["events"] == 3
        assert entry["arm"] == "C3"
        assert entry["keys"] == "keyring.json"
        assert entry["head_hash"] == _run(out)["head_hash"]

    def test_the_export_holds_the_refusal_as_well_as_the_successes(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        mesh.export(tmp_path / "e")
        types = [r["event"]["event_type"] for r in _run(tmp_path / "e")["chain"]]
        assert types == ["WRITE", "WRITE", "FAILURE"]

    def test_an_empty_session_is_not_reported_as_verified(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        mesh.export(tmp_path / "e")
        code, report = _verify(tmp_path / "e")
        assert code == 1
        assert report["valid"] is False

    def test_no_private_key_is_written(self, tmp_path: Path) -> None:
        """The seed derives every agent key, and the keyring is meant to be shared."""
        mesh = _session(tmp_path)
        _calls(mesh)
        mesh.export(tmp_path / "e")
        ring = json.loads((tmp_path / "e" / "keyring.json").read_text(encoding="utf-8"))
        assert sorted(ring) == ["coding-agent", "dba-agent"]

        from causalmesh.crypto.keys import KeyPair

        for agent, public_hex in ring.items():
            assert public_hex == KeyPair.derive(SEED, agent).public_key_hex
        private_hex = [
            KeyPair.derive(SEED, agent)._private_key.private_bytes_raw().hex() for agent in ring
        ]
        for name in ("run.json", "keyring.json"):
            text = (tmp_path / "e" / name).read_text(encoding="utf-8")
            assert SEED.decode() not in text
            assert all(secret not in text for secret in private_hex), name

    def test_an_export_is_written_once(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        mesh.export(tmp_path / "e")
        before = (tmp_path / "e" / "run.json").read_bytes()
        with pytest.raises(FileExistsError):
            mesh.export(tmp_path / "e")
        assert (tmp_path / "e" / "run.json").read_bytes() == before

    def test_a_foreign_keyring_in_the_target_is_not_overwritten(self, tmp_path: Path) -> None:
        out = tmp_path / "e"
        out.mkdir()
        (out / "keyring.json").write_text("{}", encoding="utf-8")
        mesh = _session(tmp_path)
        _calls(mesh)
        with pytest.raises(FileExistsError):
            mesh.export(out)
        assert not (out / "run.json").exists()


class TestTamperingIsCaught:
    def test_a_changed_event_fails(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        artifact = _run(out)
        artifact["chain"][1]["event"]["payload"]["tool"] = "delete_everything"
        _write_run(out, artifact)

        code, report = _verify(out)
        assert code == 1
        assert report["valid"] is False
        assert report["verified"] == 0

    def test_a_dropped_event_fails(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        artifact = _run(out)
        del artifact["chain"][1]
        _write_run(out, artifact)
        assert _verify(out)[0] == 1

    def test_the_envelope_is_outside_the_signature(self, tmp_path: Path) -> None:
        """Wall-clock values are editable by design, and verification says so by not caring."""
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        artifact = _run(out)
        artifact["envelope"]["exported_at_us"] = 1
        artifact["envelope"]["wall_time_us_by_event"] = {}
        _write_run(out, artifact)
        assert _verify(out)[0] == 0

    def test_a_chain_resigned_with_a_foreign_key_fails_against_the_keyring(
        self, tmp_path: Path
    ) -> None:
        """The attack the embedded-key check cannot see.

        A second session with a different seed makes the same calls, so it
        produces the same events, correctly chained and signed, under keys
        the operator never issued. It verifies on its own terms.
        """
        genuine = _session(tmp_path / "a")
        _calls(genuine)
        out = tmp_path / "e"
        genuine.export(out)

        forger = _session(tmp_path / "b", seed=FOREIGN_SEED)
        _calls(forger)
        forged = tmp_path / "forged"
        forger.export(forged)
        assert _verify(forged)[0] == 0  # self-consistent: this is what the forger ships

        _write_run(out, _run(forged))  # the forged chain, beside the genuine keyring
        code, report = _verify(out)
        assert code == 1
        assert report["valid"] is False

    def test_without_a_keyring_the_same_forgery_passes(self, tmp_path: Path) -> None:
        """Pinned as a limitation, not a feature.

        With no ``keyring.json`` the verifier has only the keys the records
        carry, which a forger chooses. The keyring is what closes this, so
        an auditor who is given only ``run.json`` has a weaker check.
        """
        forger = _session(tmp_path / "b", seed=FOREIGN_SEED)
        _calls(forger)
        forged = tmp_path / "forged"
        forger.export(forged)
        (forged / "keyring.json").unlink()
        code, report = _verify(forged)
        assert code == 0
        (entry,) = report["experiments"][forged.name]
        assert entry["keys"] == "embedded"

    def test_a_keyring_missing_an_agent_fails(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        ring = json.loads((out / "keyring.json").read_text(encoding="utf-8"))
        del ring["dba-agent"]
        (out / "keyring.json").write_text(json.dumps(ring), encoding="utf-8")
        assert _verify(out)[0] == 1

    @pytest.mark.parametrize("content", ["not json", "[]", '{"coding-agent": 5}'])
    def test_an_unusable_keyring_fails_instead_of_falling_back(
        self, tmp_path: Path, content: str
    ) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        (out / "keyring.json").write_text(content, encoding="utf-8")
        code, report = _verify(out)
        assert code == 1
        (entry,) = report["experiments"][out.name]
        assert "keyring.json" in entry["detail"]


class TestEnvelope:
    def test_the_wall_clock_is_in_the_envelope_and_not_in_the_chain(self, tmp_path: Path) -> None:
        mesh = _session(tmp_path)
        _calls(mesh)
        out = tmp_path / "e"
        mesh.export(out)
        artifact = _run(out)
        envelope = artifact["envelope"]
        assert envelope["clock"]["kind"] == "logical"

        wall = envelope["wall_time_us_by_event"]
        assert sorted(wall) == sorted(r["event"]["event_id"] for r in artifact["chain"])
        assert all(value > 1_600_000_000_000_000 for value in wall.values())
        assert envelope["exported_at_us"] > 1_600_000_000_000_000

        signed = [r["event"]["timestamp_us"] for r in artifact["chain"]]
        assert all(value < 1_000_000_000_000 for value in signed), signed

    def test_two_identical_sessions_export_the_same_chain(self, tmp_path: Path) -> None:
        a, b = _session(tmp_path / "a"), _session(tmp_path / "b")
        _calls(a)
        _calls(b)
        a.export(tmp_path / "ea")
        b.export(tmp_path / "eb")
        assert _run(tmp_path / "ea")["chain"] == _run(tmp_path / "eb")["chain"]
        assert _run(tmp_path / "ea")["head_hash"] == _run(tmp_path / "eb")["head_hash"]


class TestPersistTo:
    def test_the_chain_is_on_disk_before_any_export(self, tmp_path: Path) -> None:
        live = tmp_path / "live"
        mesh = _session(tmp_path, persist_to=live)
        _calls(mesh)
        lines = (live / "chain.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == mesh.audit_events()
        assert (live / "keyring.json").is_file()
        mesh.close()

    def test_export_into_the_persist_directory_verifies(self, tmp_path: Path) -> None:
        live = tmp_path / "live"
        mesh = _session(tmp_path, persist_to=live)
        _calls(mesh)
        mesh.export(live)
        mesh.close()
        code, report = _verify(live)
        assert code == 0, report

    def test_an_existing_chain_is_not_reopened(self, tmp_path: Path) -> None:
        live = tmp_path / "live"
        first = _session(tmp_path / "a", persist_to=live)
        _calls(first)
        first.close()
        with pytest.raises(ConfigurationError):
            _session(tmp_path / "b", persist_to=live)
