"""Two identical `/v1/chat/completions` sessions sign identical chains.

The chat path used to stamp `time.time_ns()` into the signed event (and into
its id), so no two sessions making the same calls shared a head hash. It now
takes its timestamp from the session's logical clock and its id from the
gateway's counter; the wall time is kept in `ToolGateway.wall_times()`, which
the export writes to the unsigned envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh import CausalMesh
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app

pytestmark = pytest.mark.reproducibility

CONTRACT = """\
version: 1
roles:
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
policy:
  arm: C3
"""

SEED = b"chat-repro-seed-0000000000000000"
WALL_FLOOR_US = 1_600_000_000_000_000


def _session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CausalMesh:
    monkeypatch.setattr("causalmesh.server.app._forward", lambda *a, **k: {"id": "x"})
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    mesh = CausalMesh(agent_id="buyer", contract=Contract.find(tmp_path), seed=SEED)
    allowed = TestClient(
        create_app(mesh=mesh, auth_disabled=True, upstream_base_url="http://api.example.com")
    )
    refused = TestClient(
        create_app(mesh=mesh, auth_disabled=True, upstream_base_url="http://evil.example")
    )
    for client, model, status in (
        (allowed, "m1", 200),
        (refused, "m2", 402),
        (allowed, "m3", 200),
    ):
        assert client.post("/v1/chat/completions", json={"model": model}).status_code == status
    return mesh


def _signed(mesh: CausalMesh) -> list[dict[str, Any]]:
    return mesh.audit_events()


def test_two_identical_chat_sessions_have_identical_signed_chains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _session(tmp_path / "a", monkeypatch)
    b = _session(tmp_path / "b", monkeypatch)
    assert len(_signed(a)) == 3
    assert _signed(a) == _signed(b)
    assert a._relay.head_hash == b._relay.head_hash


def test_no_wall_clock_value_is_signed_and_the_wall_time_is_in_the_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mesh = _session(tmp_path, monkeypatch)
    events = [r["event"] for r in _signed(mesh)]
    assert all(e["timestamp_us"] < WALL_FLOOR_US for e in events)
    assert [e["timestamp_us"] for e in events] == [0, 1_000_000, 2_000_000]
    wall = mesh._gateway.wall_times()
    assert set(wall) == {e["event_id"] for e in events}
    assert all(us > WALL_FLOOR_US for us in wall.values())
