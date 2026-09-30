"""`serve` signs `/execute` events on the gateway's logical clock.

`/v1/tools/{name}/execute` goes through `CausalMesh.execute`, so it inherits
the logical timestamp. `/v1/chat/completions` does not go through the gateway
and still stamps the wall clock; `docs/backlog.md` ("The chat path still signs the wall clock")
records that, and the last test here pins it so the gap is executable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh import CausalMesh, Tool
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app

pytestmark = pytest.mark.unit

CONTRACT = """\
version: 1
roles:
  - agent_id: test-agent
    archetype: writer
    owns: [allowed/]
  - agent_id: admin-agent
    archetype: admin
    owns: [forbidden/]
policy:
  arm: C3
"""

SEED = b"serve-clock-seed-000000000000000"
WALL_FLOOR_US = 1_600_000_000_000_000


def _client(tmp_path: Path) -> tuple[TestClient, CausalMesh]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    mesh = CausalMesh(agent_id="test-agent", contract=Contract.find(tmp_path), seed=SEED)
    mesh.register_tool(
        Tool(name="write_file", handler=lambda path: f"w:{path}", resource_args=["path"])
    )
    return TestClient(create_app(mesh=mesh, auth_disabled=True)), mesh


def _drive(client: TestClient) -> None:
    for path in ("allowed/a.txt", "forbidden/b.txt", "allowed/c.txt"):
        client.post(
            "/v1/tools/write_file/execute",
            json={"agent_id": "test-agent", "arguments": {"path": path}},
        )


def test_execute_events_are_signed_on_the_logical_clock(tmp_path: Path) -> None:
    client, mesh = _client(tmp_path)
    _drive(client)
    stamps = [r["event"]["timestamp_us"] for r in mesh.audit_events()]
    assert len(stamps) == 3
    assert all(stamp < WALL_FLOOR_US for stamp in stamps), stamps
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


def test_two_servers_with_one_seed_and_one_sequence_share_a_head_hash(tmp_path: Path) -> None:
    (ca, a), (cb, b) = _client(tmp_path / "a"), _client(tmp_path / "b")
    _drive(ca)
    _drive(cb)
    assert a._relay.head_hash == b._relay.head_hash
    assert a._relay.sequence == 3


def test_chat_events_still_carry_the_wall_clock(tmp_path: Path) -> None:
    """A known gap, stated as a test: chat completions bypass the gateway."""
    client, mesh = _client(tmp_path)
    response = client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert response.status_code == 200
    (record,) = mesh.audit_events()
    assert record["event"]["timestamp_us"] > WALL_FLOOR_US
