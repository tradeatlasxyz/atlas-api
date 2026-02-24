from contextlib import asynccontextmanager
from datetime import datetime

import pytest
import sqlalchemy as sa

from api.models.database import HistoricalCandle
from api.services import backfill
from api.services.backfill import BackfillService


@asynccontextmanager
async def _session_ctx(session):
    yield session


@pytest.mark.asyncio
async def test_backfill_asset_invalid_symbol():
    service = BackfillService()
    with pytest.raises(ValueError, match="Unsupported asset"):
        await service.backfill_asset("DOGE")


@pytest.mark.asyncio
async def test_backfill_asset_calls_all_timeframes(monkeypatch):
    service = BackfillService()
    calls = []

    async def _fake_backfill_timeframe(asset, symbol, resolution, timeframe, days):
        calls.append((asset, symbol, resolution, timeframe, days))

    monkeypatch.setattr(service, "_backfill_timeframe", _fake_backfill_timeframe)
    await service.backfill_asset("BTC")

    expected = [
        ("BTC", backfill.PYTH_SYMBOLS["BTC"], cfg["resolution"], cfg["timeframe"], cfg["days"])
        for cfg in backfill.BACKFILL_CONFIG
    ]
    assert calls == expected


@pytest.mark.asyncio
async def test_backfill_timeframe_skips_empty_data(monkeypatch):
    service = BackfillService()

    async def _fake_fetch(*_args, **_kwargs):
        return {"timestamps": [], "opens": [], "highs": [], "lows": [], "closes": []}

    async def _fail_store(*_args, **_kwargs):
        raise AssertionError("Should not store when no timestamps returned")

    monkeypatch.setattr(service, "_fetch_from_pyth", _fake_fetch)
    monkeypatch.setattr(service, "_store_candles", _fail_store)

    await service._backfill_timeframe("BTC", "Crypto.BTC/USD", "1", "1m", 1)


@pytest.mark.asyncio
async def test_store_candles_inserts_rows(db_session, monkeypatch):
    service = BackfillService()
    monkeypatch.setattr(backfill, "async_session", lambda: _session_ctx(db_session))

    data = {
        "timestamps": [int(datetime(2024, 1, 1).timestamp()), int(datetime(2024, 1, 1, 0, 1).timestamp())],
        "opens": [1.0, 2.0],
        "highs": [1.5, 2.5],
        "lows": [0.5, 1.5],
        "closes": [1.2, 2.2],
    }

    await service._store_candles("BTC", "1m", data)
    result = await db_session.execute(sa.select(sa.func.count(HistoricalCandle.id)))
    assert int(result.scalar() or 0) == 2


@pytest.mark.asyncio
async def test_check_backfill_status_returns_counts(db_session, monkeypatch):
    monkeypatch.setattr(backfill, "async_session", lambda: _session_ctx(db_session))

    db_session.add(
        HistoricalCandle(
            asset="BTC",
            timeframe="1m",
            timestamp=datetime(2024, 1, 1),
            open=1,
            high=2,
            low=0.5,
            close=1.5,
            volume=None,
        )
    )
    await db_session.commit()

    service = BackfillService()
    status = await service.check_backfill_status()
    assert status["BTC"]["1m"] == 1
    assert status["BTC"]["5m"] == 0
    assert status["BTC"]["1d"] == 0
