def test_no_auth_required_in_dev_mode(client):
    # App was created with auth_disabled=True in this fixture
    response = client.get("/v1/tools")
    assert response.status_code == 200


def test_auth_enforced_when_tokens_configured(authed_client):
    response = authed_client.get("/v1/tools")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_auth_succeeds_with_valid_token(authed_client):
    response = authed_client.get("/v1/tools", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200


def test_auth_fails_with_invalid_token(authed_client):
    response = authed_client.get("/v1/tools", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}


def test_health_never_requires_auth(authed_client):
    response = authed_client.get("/health")
    assert response.status_code == 200
