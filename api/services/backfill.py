"""Backfill historical market data from Pyth Benchmarks API."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import logging
import aiohttp

import sqlalchemy as sa

from api.config import settings
from api.models.database import HistoricalCandle
from api.services.database import async_session

logger = logging.getLogger(__name__)

PYTH_SYMBOLS = {
    "BTC": "Crypto.BTC/USD",
    "ETH": "Crypto.ETH/USD",
    "SOL": "Crypto.SOL/USD",
}

BACKFILL_CONFIG = [
    {"resolution": "1", "timeframe": "1m", "days": 3},
    {"resolution": "5", "timeframe": "5m", "days": 7},
    {"resolution": "60", "timeframe": "1h", "days": 30},
    {"resolution": "240", "timeframe": "4h", "days": 90},
    {"resolution": "D", "timeframe": "1d", "days": 365},
]


class BackfillService:
    """Backfill historical data from Pyth Benchmarks API."""

    async def backfill_all(self) -> None:
        for asset, symbol in PYTH_SYMBOLS.items():
            logger.info("Backfilling %s...", asset)
            await self.backfill_asset(asset)
            logger.info("✓ %s backfill complete", asset)

    async def backfill_asset(self, asset: str) -> None:
        symbol = PYTH_SYMBOLS.get(asset.upper())
        if not symbol:
            raise ValueError(f"Unsupported asset: {asset}")
        for config in BACKFILL_CONFIG:
            await self._backfill_timeframe(
                asset=asset.upper(),
                symbol=symbol,
                resolution=config["resolution"],
                timeframe=config["timeframe"],
                days=config["days"],
            )

    async def _backfill_timeframe(
        self,
        asset: str,
        symbol: str,
        resolution: str,
        timeframe: str,
        days: int,
    ) -> None:
        now = datetime.utcnow()
        from_ts = int((now - timedelta(days=days)).timestamp())
        to_ts = int(now.timestamp())

        logger.info("  Fetching %s candles for %s days...", timeframe, days)
        data = await self._fetch_from_pyth(symbol, resolution, from_ts, to_ts)
        if not data["timestamps"]:
            logger.warning("  No data returned for %s %s", asset, timeframe)
            return

        await self._store_candles(asset, timeframe, data)
        logger.info("  ✓ Stored %s %s candles", len(data["timestamps"]), timeframe)

    async def _fetch_from_pyth(
        self,
        symbol: str,
        resolution: str,
        from_ts: int,
        to_ts: int,
    ) -> dict:
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(settings.pyth_benchmarks_url, params=params) as resp:
                data = await resp.json()
                if data.get("s") != "ok":
                    raise ValueError(f"Pyth API error: {data}")
                return {
                    "timestamps": data.get("t", []),
                    "opens": data.get("o", []),
                    "highs": data.get("h", []),
                    "lows": data.get("l", []),
                    "closes": data.get("c", []),
                }

    async def _store_candles(self, asset: str, timeframe: str, data: dict) -> None:
        async with async_session() as db:
            for idx, ts in enumerate(data["timestamps"]):
                candle = HistoricalCandle(
                    asset=asset,
                    timeframe=timeframe,
                    timestamp=datetime.utcfromtimestamp(ts),
                    open=Decimal(str(data["opens"][idx])),
                    high=Decimal(str(data["highs"][idx])),
                    low=Decimal(str(data["lows"][idx])),
                    close=Decimal(str(data["closes"][idx])),
                    volume=None,
                )
                db.add(candle)
            await db.commit()

    async def check_backfill_status(self) -> dict:
        status: dict[str, dict[str, int]] = {}
        async with async_session() as db:
            for asset in PYTH_SYMBOLS:
                status[asset] = {}
                for config in BACKFILL_CONFIG:
                    result = await db.execute(
                        sa.select(sa.func.count(HistoricalCandle.id))
                        .where(HistoricalCandle.asset == asset)
                        .where(HistoricalCandle.timeframe == config["timeframe"])
                    )
                    status[asset][config["timeframe"]] = int(result.scalar() or 0)
        return status
