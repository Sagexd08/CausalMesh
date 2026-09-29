import pytest

pytestmark = pytest.mark.integration


def test_health_unauthenticated(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_unauthenticated(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "run_id" in data
