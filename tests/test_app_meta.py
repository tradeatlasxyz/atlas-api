from fastapi.testclient import TestClient

from api.main import app


def test_openapi_metadata() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == "Atlas API"
    assert payload["info"]["version"] == "0.1.0"


def test_cors_middleware_configured() -> None:
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes
