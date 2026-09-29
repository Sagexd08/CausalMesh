def test_unknown_tool_is_404(client):
    response = client.post(
        "/v1/tools/does_not_exist/execute", json={"agent_id": "test-agent", "arguments": {}}
    )
    assert response.status_code == 404
    assert "not registered" in response.json()["detail"]


def test_missing_resource_is_422(client):
    # write_file requires 'path'
    response = client.post(
        "/v1/tools/write_file/execute", json={"agent_id": "test-agent", "arguments": {}}
    )
    assert response.status_code == 422
    assert "was not provided" in response.json()["detail"]


def test_an_unhandled_error_is_a_generic_500_without_detail(client, mesh, monkeypatch):
    def explode(**_kwargs):
        raise RuntimeError("secret-token-xyz at /home/operator/private.key")

    monkeypatch.setattr(mesh, "execute", explode)
    response = client.post(
        "/v1/tools/write_file/execute",
        json={"agent_id": "test-agent", "arguments": {"path": "allowed/file.txt"}},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "secret-token-xyz" not in response.text
    assert "Traceback" not in response.text


def test_unknown_agent_is_400(client):
    response = client.post(
        "/v1/tools/write_file/execute",
        json={"agent_id": "imposter", "arguments": {"path": "allowed/file.txt"}},
    )
    assert response.status_code == 400
    assert "no signing key" in response.json()["detail"]
