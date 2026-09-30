"""`/v1/tools/{name}/execute` records how the agent was established.

Chat events already carry `identity_source`. A tool call is a stronger claim
(it may write a file), so its event must say the same thing: `token-bound`
when a credential named the agent, `asserted` when the caller merely said so.
The value is a function of the token type alone, so it is reproducible and
safe to sign into the chain.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh.crypto.keys import PublicKeyRing
from causalmesh.server import create_app
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration]

BOUND = "bound-token-0000000000000000"
SHARED = "operator-token-000000000000"


def _last_payload(mesh) -> dict:
    return mesh.audit_events()[-1]["event"]["payload"]


def _execute(client, path, *, token, agent="test-agent"):
    return client.post(
        "/v1/tools/write_file/execute",
        json={"agent_id": agent, "arguments": {"path": path}},
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )


def test_a_token_bound_call_is_recorded_as_token_bound(mesh):
    app = create_app(mesh=mesh, agent_tokens={"test-agent": BOUND})
    client = TestClient(app, raise_server_exceptions=False)
    assert _execute(client, "allowed/a.txt", token=BOUND).status_code == 200
    payload = _last_payload(mesh)
    assert payload["identity_source"] == "token-bound"
    assert payload["outcome"] == "executed"


def test_an_unbound_token_call_is_recorded_as_asserted(mesh):
    app = create_app(mesh=mesh, api_tokens={SHARED})
    client = TestClient(app, raise_server_exceptions=False)
    assert _execute(client, "allowed/a.txt", token=SHARED).status_code == 200
    assert _last_payload(mesh)["identity_source"] == "asserted"


def test_a_call_with_auth_disabled_is_recorded_as_asserted(mesh):
    client = TestClient(create_app(mesh=mesh, auth_disabled=True), raise_server_exceptions=False)
    assert _execute(client, "allowed/a.txt", token=None).status_code == 200
    assert _last_payload(mesh)["identity_source"] == "asserted"


def test_a_denied_call_carries_it_too(mesh):
    app = create_app(mesh=mesh, agent_tokens={"test-agent": BOUND}, api_tokens={SHARED})
    client = TestClient(app, raise_server_exceptions=False)
    assert _execute(client, "forbidden/x", token=BOUND).status_code == 403
    denied = _last_payload(mesh)
    assert denied["outcome"] != "executed"
    assert denied["identity_source"] == "token-bound"
    assert _execute(client, "forbidden/y", token=SHARED).status_code == 403
    assert _last_payload(mesh)["identity_source"] == "asserted"


def test_an_async_handler_is_annotated_as_well(mesh):
    client = TestClient(create_app(mesh=mesh, api_tokens={SHARED}), raise_server_exceptions=False)
    response = client.post(
        "/v1/tools/async_write/execute",
        json={"agent_id": "test-agent", "arguments": {"path": "allowed/x"}},
        headers={"Authorization": f"Bearer {SHARED}"},
    )
    assert response.status_code == 200
    assert _last_payload(mesh)["identity_source"] == "asserted"


def test_the_chain_still_verifies_with_the_annotation_in_it(mesh):
    app = create_app(mesh=mesh, agent_tokens={"test-agent": BOUND})
    client = TestClient(app, raise_server_exceptions=False)
    for name in ("allowed/1", "allowed/2", "forbidden/3"):
        _execute(client, name, token=BOUND)
    events = mesh.audit_events()
    assert len(events) == 3
    assert verify_chain(events, PublicKeyRing.from_keypairs(mesh._relay._keypairs)).valid


def test_a_direct_sdk_call_has_no_identity_source(mesh):
    """Absent is absent: the SDK does not invent a source it never established."""
    mesh.execute(agent_id="test-agent", tool="write_file", arguments={"path": "allowed/sdk"})
    assert "identity_source" not in _last_payload(mesh)


def test_annotations_never_override_what_the_gateway_records(mesh):
    mesh.execute(
        agent_id="test-agent",
        tool="write_file",
        arguments={"path": "allowed/sdk"},
        annotations={"outcome": "forged", "identity_source": "asserted"},
    )
    payload = _last_payload(mesh)
    assert payload["outcome"] == "executed"
    assert payload["identity_source"] == "asserted"
