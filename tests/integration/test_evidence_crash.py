"""A real process killed mid-write, then the evidence file reopened.

The unit tests build a torn file by hand.  This one produces it the way a
crash does: a child process that dies half way through a record, with no
chance to clean up, so the file is whatever the OS was left holding.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.crypto import KeyPair, PublicKeyRing
from causalmesh.sdk import EvidenceCorruptError, load_evidence
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

SEED = b"evidence-test-seed-0123456789abc"
SRC = Path(__file__).resolve().parents[2] / "src"

CHILD = textwrap.dedent(
    """
    import os, sys
    from causalmesh import CausalMesh, Tool

    contract, evidence, seed = sys.argv[1], sys.argv[2], sys.argv[3].encode()
    mesh = CausalMesh.from_config(contract, seed=seed, evidence_path=evidence)
    mesh.register_tool(
        Tool(name="write_file", handler=lambda path, content="": "ok", resource_args=["path"])
    )
    for i in range(2):
        mesh.execute(tool="write_file", arguments={"path": f"src/f{i}.py"}, now_us=1000 + i)

    class HalfWrite:
        def __init__(self, inner):
            self._inner = inner
        def write(self, data):
            self._inner.write(bytes(data)[: len(data) // 2])
            self._inner.flush()
            os._exit(9)
        def __getattr__(self, name):
            return getattr(self._inner, name)

    mesh._evidence._fh = HalfWrite(mesh._evidence._fh)
    mesh.execute(tool="write_file", arguments={"path": "src/f2.py"}, now_us=1002)
    """
)


def test_a_killed_writer_leaves_a_file_that_is_refused_then_recovered(tmp_path: Path) -> None:
    contract = tmp_path / "causalmesh.yaml"
    contract.write_text("version: 1\nagent:\n  id: coding-agent\npolicy:\n  arm: C3\n")
    evidence = tmp_path / "ev.jsonl"
    child = tmp_path / "child.py"
    child.write_text(CHILD, encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [sys.executable, str(child), str(contract), str(evidence), SEED.decode()],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 9, proc.stderr

    # The lock died with the process, so nothing stale blocks the reopen.
    with pytest.raises(EvidenceCorruptError, match="last line is incomplete") as info:
        CausalMesh.from_config(contract, seed=SEED, evidence_path=evidence)
    assert info.value.torn

    with CausalMesh.from_config(
        contract, seed=SEED, evidence_path=evidence, recover_evidence=True
    ) as mesh:
        recovery = mesh.evidence_recovery
        assert recovery is not None and recovery["records_kept"] == 2
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content="": "ok", resource_args=["path"])
        )
        assert mesh.execute(
            tool="write_file", arguments={"path": "src/f9.py"}, now_us=2000
        ).recorded

    records = load_evidence(evidence)
    assert [r["event"]["sequence"] for r in records] == [0, 1, 2]
    ring = PublicKeyRing.from_keypairs({"coding-agent": KeyPair.derive(SEED, "coding-agent")})
    result = verify_chain(records, ring)
    assert result.valid, result.failures
