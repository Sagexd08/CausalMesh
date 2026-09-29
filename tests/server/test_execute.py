import pytest

pytestmark = pytest.mark.integration


def test_execute_allowed(client, mesh):
    response = client.post(
        "/v1/tools/write_file/execute",
        json={
            "agent_id": "test-agent",
            "arguments": {"path": "allowed/hello.txt", "content": "hello"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is True
    assert data["executed"] is True
    assert data["denied"] is False
    assert data["failed"] is False
    assert data["tool"] == "write_file"
    assert data["agent_id"] == "test-agent"
    assert data["recorded"] is True
    assert data["reason"] == "allowed"

    assert "allowed/hello.txt" in mesh._called


def test_execute_async_allowed(client, mesh):
    response = client.post(
        "/v1/tools/async_write/execute",
        json={"agent_id": "test-agent", "arguments": {"path": "allowed/async.txt"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is True
    assert data["executed"] is True

    assert "allowed/async.txt" in mesh._called


def test_execute_denied(client, mesh):
    response = client.post(
        "/v1/tools/write_file/execute",
        json={"agent_id": "test-agent", "arguments": {"path": "forbidden/secret.txt"}},
    )
    # The HTTP adapter maps denied calls to 403
    assert response.status_code == 403

    data = response.json()
    assert "detail" in data

    detail = data["detail"]
    assert "message" in detail
    assert "rule" in detail
    assert detail["rule"] == "ownership"

    # Handler must not have been called
    assert "forbidden/secret.txt" not in mesh._called
