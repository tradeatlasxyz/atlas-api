import asyncio
from datetime import datetime, timedelta

import pytest

from api.execution.market_data import MarketDataFetcher, PricePoint


@pytest.mark.asyncio
async def test_market_data_buffer_returns_candles():
    fetcher = MarketDataFetcher()

    class DummyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class DummySession:
        async def execute(self, *_):
            return DummyResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _noop(asset, candle):
        await asyncio.sleep(0)

    fetcher._persist_candle = _noop  # type: ignore
    now = datetime.utcnow()
    await fetcher._update_candle("BTC", PricePoint(asset="BTC", price=50000.0, timestamp=now))
    await fetcher._update_candle("BTC", PricePoint(asset="BTC", price=50100.0, timestamp=now))

    import api.execution.market_data as market_data_module

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(market_data_module, "async_session", lambda: DummySession())

    df = await fetcher.get_candles("BTC", "1m", limit=10)
    assert not df.empty

    monkeypatch.undo()


@pytest.mark.asyncio
async def test_market_data_merges_db_and_buffer(monkeypatch):
    fetcher = MarketDataFetcher()

    class DummyRow:
        def __init__(self, timestamp, open_, high, low, close, volume):
            self.timestamp = timestamp
            self.open = open_
            self.high = high
            self.low = low
            self.close = close
            self.volume = volume

    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class DummySession:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, *_):
            return DummyResult(self._rows)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    now = datetime.utcnow().replace(second=0, microsecond=0)
    db_rows = [
        DummyRow(now, 100.0, 101.0, 99.0, 100.0, 1.0),
        DummyRow(now - timedelta(minutes=1), 98.0, 99.0, 97.0, 98.0, 1.0),
    ]

    async def _noop(asset, candle):
        await asyncio.sleep(0)

    fetcher._persist_candle = _noop  # type: ignore
    await fetcher._update_candle("BTC", PricePoint(asset="BTC", price=105.0, timestamp=now))

    import api.execution.market_data as market_data_module

    monkeypatch.setattr(
        market_data_module, "async_session", lambda: DummySession(db_rows)
    )

    df = await fetcher.get_candles("BTC", "1m", limit=5)
    assert len(df) == 2
    latest = df.iloc[-1]
    assert float(latest["close"]) == 105.0
