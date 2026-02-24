from fastapi.testclient import TestClient

from api.main import app
import api.routes.pools as pools_routes


VALID_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


def test_investor_report_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/investor-report")
    assert response.status_code == 422


def test_investor_report_not_found(monkeypatch) -> None:
    async def fake_report(*_, **__):
        return None

    monkeypatch.setattr(pools_routes, "get_investor_report_by_vault", fake_report)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/investor-report")
    assert response.status_code == 404


def test_investor_report_success(monkeypatch) -> None:
    async def fake_report(*_, **__):
        return {
            "win_rate": 0.6,
            "total_return": 1.2,
            "sharpe": 1.1,
            "sortino": 1.3,
            "max_drawdown": 0.2,
            "trade_count": 10,
            "profit_factor": 1.8,
            "avg_trade_duration": "4.2 days",
            "leverage": 2.0,
            "strategy_type": "Momentum",
            "timeframe": "1H",
            "asset": "BTC",
            "description": "Investor friendly",
            "report_url": "/reports/strat_1.html",
            "equity_curve": [{"date": "2024-01-01", "value": 100000}],
        }

    monkeypatch.setattr(pools_routes, "get_investor_report_by_vault", fake_report)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/investor-report")
    assert response.status_code == 200
    data = response.json()
    assert data["strategyType"] == "Momentum"
    assert data["winRate"] == 0.6


def test_pool_history_invalid_interval() -> None:
    client = TestClient(app)
    response = client.get(
        f"/api/pool/{VALID_ADDRESS}/history?interval=invalid"
    )
    assert response.status_code == 422


def test_pool_history_invalid_date_range() -> None:
    client = TestClient(app)
    response = client.get(
        f"/api/pool/{VALID_ADDRESS}/history?startDate=2024-12-31&endDate=2024-01-01"
    )
    assert response.status_code == 422


def test_pool_history_not_found(monkeypatch) -> None:
    async def fake_history(*_, **__):
        return None, None

    monkeypatch.setattr(pools_routes, "get_vault_history", fake_history)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/history")
    assert response.status_code == 404


def test_pool_history_success(monkeypatch) -> None:
    async def fake_history(*_, **__):
        return (
            [
                {
                    "timestamp": 1704067200000,
                    "share_price": 1.0,
                    "tvl": 100000.0,
                    "depositor_count": 5,
                    "daily_return": 0.0,
                }
            ],
            {
                "vault_address": VALID_ADDRESS.lower(),
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
                "data_points": 1,
                "interval": "daily",
            },
        )

    monkeypatch.setattr(pools_routes, "get_vault_history", fake_history)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/history")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["data"][0]["sharePrice"] == 1.0


def test_pool_trades_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/trades")
    assert response.status_code == 422


def test_pool_trades_not_found(monkeypatch) -> None:
    async def fake_trades(*_, **__):
        return None, None

    monkeypatch.setattr(pools_routes, "get_vault_trades", fake_trades)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/trades")
    assert response.status_code == 404


def test_pool_trades_success(monkeypatch) -> None:
    async def fake_trades(*_, **__):
        return (
            [
                {
                    "id": 1,
                    "trade_num": 42,
                    "timestamp": "2026-01-10T12:00:00+00:00",
                    "side": "long",
                    "asset": "BTC",
                    "size": 1000.0,
                    "entry_price": 95000.0,
                    "exit_price": 97000.0,
                    "exit_timestamp": "2026-01-10T14:00:00+00:00",
                    "pnl": 200.0,
                    "pnl_pct": 0.0211,
                    "result": "win",
                    "tx_hash": "0xabc",
                }
            ],
            {
                "vault_address": VALID_ADDRESS.lower(),
                "page": 1,
                "limit": 50,
                "total": 1,
                "has_more": False,
            },
        )

    monkeypatch.setattr(pools_routes, "get_vault_trades", fake_trades)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["meta"]["hasMore"] is False
    assert data["trades"][0]["tradeNum"] == 42
    assert data["trades"][0]["entryPrice"] == 95000.0


def test_pool_trades_passes_query_params(monkeypatch) -> None:
    captured = {}

    async def fake_trades(*_, **kwargs):
        captured.update(kwargs)
        return (
            [],
            {
                "vault_address": VALID_ADDRESS.lower(),
                "page": kwargs["page"],
                "limit": kwargs["limit"],
                "total": 0,
                "has_more": False,
            },
        )

    monkeypatch.setattr(pools_routes, "get_vault_trades", fake_trades)

    client = TestClient(app)
    response = client.get(
        f"/api/pool/{VALID_ADDRESS}/trades?page=2&limit=10&includeErrors=true"
    )
    assert response.status_code == 200
    assert captured["page"] == 2
    assert captured["limit"] == 10
    assert captured["include_errors"] is True


def test_pool_signals_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/signals")
    assert response.status_code == 422


def test_pool_signals_not_found(monkeypatch) -> None:
    async def fake_signals(*_, **__):
        return None, None

    monkeypatch.setattr(pools_routes, "get_vault_signals", fake_signals)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/signals")
    assert response.status_code == 404


def test_pool_signals_success(monkeypatch) -> None:
    async def fake_signals(*_, **__):
        return (
            [
                {
                    "id": 7,
                    "timestamp": "2026-01-10T12:30:00+00:00",
                    "asset": "ETH",
                    "timeframe": "1h",
                    "direction": 1,
                    "confidence": 0.87,
                    "size_pct": 0.25,
                    "reason": "Momentum breakout",
                    "current_price": 3500.0,
                    "stop_loss": 3400.0,
                    "take_profit": 3650.0,
                },
                {
                    "id": 8,
                    "timestamp": "2026-01-10T13:30:00+00:00",
                    "asset": "BTC",
                    "timeframe": "1h",
                    "direction": -1,
                    "confidence": 0.61,
                    "size_pct": 0.1,
                    "reason": "Mean reversion",
                    "current_price": 97000.0,
                    "stop_loss": 98000.0,
                    "take_profit": 95500.0,
                },
            ],
            {
                "vault_address": VALID_ADDRESS.lower(),
                "page": 1,
                "limit": 50,
                "total": 2,
                "has_more": False,
            },
        )

    monkeypatch.setattr(pools_routes, "get_vault_signals", fake_signals)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/signals")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["data"][0]["directionLabel"] == "LONG"
    assert data["data"][1]["directionLabel"] == "SHORT"


def test_pool_signals_passes_query_params(monkeypatch) -> None:
    captured = {}

    async def fake_signals(*_, **kwargs):
        captured.update(kwargs)
        return (
            [],
            {
                "vault_address": VALID_ADDRESS.lower(),
                "page": kwargs["page"],
                "limit": kwargs["limit"],
                "total": 0,
                "has_more": False,
            },
        )

    monkeypatch.setattr(pools_routes, "get_vault_signals", fake_signals)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/signals?page=3&limit=25")
    assert response.status_code == 200
    assert captured["page"] == 3
    assert captured["limit"] == 25


def test_pool_live_performance_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/live-performance")
    assert response.status_code == 422


def test_pool_live_performance_not_found(monkeypatch) -> None:
    async def fake_live_performance(*_, **__):
        return None

    monkeypatch.setattr(
        pools_routes, "get_vault_live_performance", fake_live_performance
    )

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/live-performance")
    assert response.status_code == 404


def test_pool_live_performance_success(monkeypatch) -> None:
    async def fake_live_performance(*_, **__):
        return {
            "vault_address": VALID_ADDRESS.lower(),
            "total_trades": 3,
            "closed_trades": 2,
            "open_trades": 1,
            "win_rate": 0.5,
            "profit_factor": 1.25,
            "avg_trade_duration_hours": 4.5,
            "realized_pnl_usd": 120.0,
            "unrealized_pnl_usd": 35.5,
            "total_pnl_usd": 155.5,
            "sharpe": 1.234,
            "snapshot_count": 8,
            "first_trade_at": "2026-01-01T00:00:00+00:00",
            "last_trade_at": "2026-01-10T00:00:00+00:00",
            "data_quality": {
                "hasClosedTrades": True,
                "hasSnapshots": True,
                "sharpeDataPoints": 8,
                "sharpeAvailable": True,
            },
        }

    monkeypatch.setattr(
        pools_routes, "get_vault_live_performance", fake_live_performance
    )

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/live-performance")
    assert response.status_code == 200
    data = response.json()
    assert data["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["totalTrades"] == 3
    assert data["openTrades"] == 1
    assert data["realizedPnlUsd"] == 120.0
    assert data["dataQuality"]["sharpeAvailable"] is True


def test_pool_positions_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/positions")
    assert response.status_code == 422


def test_pool_positions_not_found(monkeypatch) -> None:
    async def fake_positions(*_, **__):
        return None

    monkeypatch.setattr(pools_routes, "get_vault_positions", fake_positions)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/positions")
    assert response.status_code == 404


def test_pool_positions_flat_success(monkeypatch) -> None:
    async def fake_positions(*_, **__):
        return {
            "vault_address": VALID_ADDRESS.lower(),
            "positions": [],
            "total_unrealized_pnl": 0.0,
            "snapshot_at": None,
            "is_flat": True,
        }

    monkeypatch.setattr(pools_routes, "get_vault_positions", fake_positions)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/positions")
    assert response.status_code == 200
    data = response.json()
    assert data["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["positions"] == []
    assert data["isFlat"] is True


def test_pool_positions_with_short_position(monkeypatch) -> None:
    async def fake_positions(*_, **__):
        return {
            "vault_address": VALID_ADDRESS.lower(),
            "positions": [
                {
                    "market_id": "0xmarket",
                    "asset": "BTC",
                    "direction": "short",
                    "size": 0.25,
                    "size_usd": None,
                    "entry_price": 98000.0,
                    "current_price": 97000.0,
                    "unrealized_pnl": 250.0,
                    "unrealized_pnl_pct": 0.0204,
                    "leverage": 2.0,
                    "liquidation_price": None,
                }
            ],
            "total_unrealized_pnl": 250.0,
            "snapshot_at": "2026-01-11T00:00:00+00:00",
            "is_flat": False,
        }

    monkeypatch.setattr(pools_routes, "get_vault_positions", fake_positions)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/positions")
    assert response.status_code == 200
    data = response.json()
    assert data["isFlat"] is False
    assert data["positions"][0]["direction"] == "short"
    assert data["positions"][0]["unrealizedPnlPct"] == 0.0204


def test_pool_health_invalid_address() -> None:
    client = TestClient(app)
    response = client.get("/api/pool/not-an-address/health")
    assert response.status_code == 422


def test_pool_health_not_found(monkeypatch) -> None:
    async def fake_health(*_, **__):
        return None

    monkeypatch.setattr(pools_routes, "get_vault_health", fake_health)
    monkeypatch.setattr(pools_routes, "_assert_manager_signature", lambda *_args, **_kwargs: None)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/health?signer={VALID_ADDRESS}&signature=0xabc")
    assert response.status_code == 404


def test_pool_health_success(monkeypatch) -> None:
    async def fake_health(*_, **__):
        return {
            "vault_address": VALID_ADDRESS.lower(),
            "circuit_breaker_tripped": True,
            "consecutive_failures": 5,
            "tripped_at": "2026-01-11T00:00:00+00:00",
            "cooldown_remaining_seconds": 1200,
            "circuit_breaker_threshold": 5,
            "circuit_breaker_cooldown": 3600,
            "last_successful_trade_at": "2026-01-10T23:00:00+00:00",
            "last_failed_trade_at": "2026-01-10T23:30:00+00:00",
            "last_error_message": "insufficient balance",
            "last_checked_at": "2026-01-11T00:05:00+00:00",
            "status": "paused",
        }

    monkeypatch.setattr(pools_routes, "get_vault_health", fake_health)
    monkeypatch.setattr(pools_routes, "_assert_manager_signature", lambda *_args, **_kwargs: None)

    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/health?signer={VALID_ADDRESS}&signature=0xabc")
    assert response.status_code == 200
    data = response.json()
    assert data["vaultAddress"] == VALID_ADDRESS.lower()
    assert data["circuitBreakerTripped"] is True
    assert data["consecutiveFailures"] == 5
    assert data["cooldownRemainingSeconds"] == 1200
    assert data["status"] == "paused"


def test_pool_health_requires_signature_params() -> None:
    client = TestClient(app)
    response = client.get(f"/api/pool/{VALID_ADDRESS}/health")
    assert response.status_code == 422
