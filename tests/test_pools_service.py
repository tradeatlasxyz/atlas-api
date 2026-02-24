from datetime import datetime, timedelta, timezone

import pytest

from api.models.database import PerformanceSnapshot, Trade, Vault
from api.services.pools import (
    get_vault_health,
    get_vault_live_performance,
    get_vault_positions,
)


VALID_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


@pytest.mark.asyncio
async def test_get_vault_live_performance_calculates_metrics(db_session):
    db_session.add(Vault(address=VALID_ADDRESS, name="Test Vault"))
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Trade(
                vault_address=VALID_ADDRESS,
                strategy_id=None,
                trade_num=1,
                timestamp=now - timedelta(hours=10),
                side="long",
                asset="BTC",
                size=1000,
                entry_price=100,
                exit_price=110,
                exit_timestamp=now - timedelta(hours=8),
                pnl=100,
                pnl_pct=0.10,
                result="win",
                tx_hash="0x1",
                error_message=None,
            ),
            Trade(
                vault_address=VALID_ADDRESS,
                strategy_id=None,
                trade_num=2,
                timestamp=now - timedelta(hours=7),
                side="short",
                asset="BTC",
                size=1000,
                entry_price=110,
                exit_price=115,
                exit_timestamp=now - timedelta(hours=6),
                pnl=-50,
                pnl_pct=-0.05,
                result="loss",
                tx_hash="0x2",
                error_message=None,
            ),
            Trade(
                vault_address=VALID_ADDRESS,
                strategy_id=None,
                trade_num=3,
                timestamp=now - timedelta(hours=5),
                side="long",
                asset="BTC",
                size=500,
                entry_price=120,
                exit_price=None,
                exit_timestamp=None,
                pnl=None,
                pnl_pct=None,
                result="open",
                tx_hash="0x3",
                error_message=None,
            ),
        ]
    )

    daily_returns = [0.01, 0.02, -0.01, 0.015, 0.005]
    for idx, ret in enumerate(daily_returns):
        db_session.add(
            PerformanceSnapshot(
                vault_address=VALID_ADDRESS,
                timestamp=now - timedelta(days=len(daily_returns) - idx),
                tvl=10000,
                share_price=1.0,
                depositor_count=1,
                daily_return=ret,
                positions_json=[],
                unrealized_pnl=25 if idx == len(daily_returns) - 1 else None,
            )
        )

    await db_session.commit()
    result = await get_vault_live_performance(db_session, vault_address=VALID_ADDRESS)

    assert result is not None
    assert result["total_trades"] == 3
    assert result["closed_trades"] == 2
    assert result["open_trades"] == 1
    assert result["win_rate"] == 0.5
    assert result["realized_pnl_usd"] == 50.0
    assert result["unrealized_pnl_usd"] == 25.0
    assert result["total_pnl_usd"] == 75.0
    assert result["profit_factor"] == 2.0
    assert result["avg_trade_duration_hours"] == 1.5
    assert result["sharpe"] is not None
    assert result["data_quality"]["sharpeAvailable"] is True


@pytest.mark.asyncio
async def test_get_vault_positions_derives_short_direction_and_pct(db_session):
    db_session.add(Vault(address=VALID_ADDRESS, name="Test Vault"))
    now = datetime.now(timezone.utc)
    db_session.add(
        PerformanceSnapshot(
            vault_address=VALID_ADDRESS,
            timestamp=now,
            tvl=10000,
            share_price=1.0,
            depositor_count=1,
            daily_return=None,
            positions_json=[
                {
                    "market_id": "0xmarket",
                    "asset": "BTC",
                    "size": -2.0,
                    "entry_price": 100.0,
                    "current_price": 90.0,
                    "unrealized_pnl": 20.0,
                    "leverage": 2.0,
                    "liquidation_price": None,
                }
            ],
            unrealized_pnl=20.0,
        )
    )
    await db_session.commit()

    result = await get_vault_positions(db_session, vault_address=VALID_ADDRESS)
    assert result is not None
    assert result["is_flat"] is False
    assert result["positions"][0]["direction"] == "short"
    assert result["positions"][0]["size"] == 2.0
    assert result["positions"][0]["unrealized_pnl_pct"] == 0.2
    assert result["total_unrealized_pnl"] == 20.0


@pytest.mark.asyncio
async def test_get_vault_health_reflects_circuit_breaker_state(db_session, monkeypatch):
    db_session.add(Vault(address=VALID_ADDRESS, name="Test Vault"))
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Trade(
                vault_address=VALID_ADDRESS,
                strategy_id=None,
                trade_num=1,
                timestamp=now - timedelta(hours=2),
                side="long",
                asset="BTC",
                size=1000,
                entry_price=100,
                exit_price=102,
                exit_timestamp=now - timedelta(hours=1),
                pnl=20,
                pnl_pct=0.02,
                result="win",
                tx_hash="0xok",
                error_message=None,
            ),
            Trade(
                vault_address=VALID_ADDRESS,
                strategy_id=None,
                trade_num=2,
                timestamp=now - timedelta(minutes=30),
                side="long",
                asset="BTC",
                size=1000,
                entry_price=102,
                exit_price=None,
                exit_timestamp=None,
                pnl=None,
                pnl_pct=None,
                result=None,
                tx_hash="0xbad",
                error_message="execution failed",
            ),
        ]
    )
    await db_session.commit()

    class DummyScheduler:
        _circuit_breaker = {
            VALID_ADDRESS: {
                "failures": 5,
                "tripped_at": now - timedelta(minutes=10),
            }
        }

    monkeypatch.setattr("api.services.pools.get_scheduler", lambda: DummyScheduler())

    result = await get_vault_health(db_session, vault_address=VALID_ADDRESS)
    assert result is not None
    assert result["circuit_breaker_tripped"] is True
    assert result["status"] == "paused"
    assert result["consecutive_failures"] == 5
    assert result["last_error_message"] == "execution failed"
    assert result["last_successful_trade_at"] is not None
    assert result["last_failed_trade_at"] is not None
