from datetime import datetime

from fastapi.testclient import TestClient

from api.main import app
import api.routes.strategies as strategies_routes


def test_list_strategies_empty(monkeypatch) -> None:
    async def fake_get_strategy_discoveries(*_, **__):
        return [], 0

    monkeypatch.setattr(strategies_routes, "get_strategy_discoveries", fake_get_strategy_discoveries)

    client = TestClient(app)
    response = client.get("/api/strategies/discoveries")
    assert response.status_code == 200
    data = response.json()
    assert data["strategies"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["limit"] == 10


def test_list_strategies_payload(monkeypatch) -> None:
    async def fake_get_strategy_discoveries(*_, **__):
        return [object()], 1

    def fake_strategy_to_dict(_):
        return {
            "id": "strat_1",
            "name": "Test Strategy",
            "strategy_type": "Multi-Indicator",
            "asset": "BTC",
            "timeframe": "1H",
            "leverage_range": "1-2x",
            "win_rate": 0.5,
            "sharpe": 1.2,
            "sortino": 1.4,
            "max_drawdown": 0.1,
            "total_return": 1.5,
            "discovered_at": datetime(2026, 1, 1, 0, 0, 0),
            "featured": True,
            "passed_curation": True,
            "status": "deployable",
            "vault_address": None,
        }

    monkeypatch.setattr(strategies_routes, "get_strategy_discoveries", fake_get_strategy_discoveries)
    monkeypatch.setattr(strategies_routes, "strategy_to_discovery_dict", fake_strategy_to_dict)

    client = TestClient(app)
    response = client.get("/api/strategies/discoveries")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["strategies"][0]["strategyType"] == "Multi-Indicator"
    assert data["strategies"][0]["winRate"] == 0.5


def test_list_strategies_invalid_page() -> None:
    client = TestClient(app)
    response = client.get("/api/strategies/discoveries?page=0")
    assert response.status_code == 422


def test_list_strategies_invalid_sort() -> None:
    client = TestClient(app)
    response = client.get("/api/strategies/discoveries?sort=bogus")
    assert response.status_code == 422
