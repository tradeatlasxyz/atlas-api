from fastapi.testclient import TestClient

from api.main import app
import api.routes.health as health_routes


def test_root() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Atlas API", "docs": "/docs"}


def test_health_live() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "timestamp" in data


def test_health_ready(monkeypatch) -> None:
    async def fake_check_database():
        return True, 1.23, None

    monkeypatch.setattr(health_routes, "check_database", fake_check_database)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["database_latency_ms"] == 1.23


def test_health_ready_unavailable(monkeypatch) -> None:
    async def fake_check_database():
        return False, 2.5, "db down"

    monkeypatch.setattr(health_routes, "check_database", fake_check_database)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["database"] == "error"


def test_health_detailed(monkeypatch) -> None:
    async def fake_check_database():
        return True, 3.33, None

    monkeypatch.setattr(health_routes, "check_database", fake_check_database)
    client = TestClient(app)
    response = client.get("/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["database"]["status"] == "ok"
