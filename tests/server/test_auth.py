import pytest
from fastapi.testclient import TestClient

from causalmesh.server import create_app

pytestmark = pytest.mark.integration


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


def test_a_401_tells_the_client_which_scheme_to_use(authed_client):
    response = authed_client.get("/v1/tools")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("presented", ["good-toke", "good-token-", "GOOD-TOKEN", "", "x" * 4096])
def test_only_the_exact_token_is_accepted(authed_client, presented):
    response = authed_client.get("/v1/tools", headers={"Authorization": f"Bearer {presented}"})
    assert response.status_code == 401


def test_a_non_bearer_scheme_is_refused(authed_client):
    response = authed_client.get("/v1/tools", headers={"Authorization": "Basic good-token"})
    assert response.status_code == 401


def test_the_factory_refuses_to_serve_without_an_explicit_auth_choice(mesh):
    # Forgetting `api_tokens` used to produce an open server.
    with pytest.raises(ValueError, match="authentication is required"):
        create_app(mesh=mesh)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_token_is_refused_rather_than_matching_an_empty_header(mesh, blank):
    with pytest.raises(ValueError, match="non-blank"):
        create_app(mesh=mesh, api_tokens={blank})


def test_an_empty_token_set_refuses_every_request(mesh):
    client = TestClient(create_app(mesh=mesh, api_tokens=set()), raise_server_exceptions=False)
    assert client.get("/v1/tools").status_code == 401
    assert client.get("/v1/tools", headers={"Authorization": "Bearer x"}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/tools"),
        ("post", "/v1/tools/write_file/execute"),
        ("post", "/v1/chat/completions"),
    ],
)
def test_every_v1_route_refuses_a_missing_token(authed_client, method, path):
    response = authed_client.request(method.upper(), path, json={})
    assert response.status_code == 401
