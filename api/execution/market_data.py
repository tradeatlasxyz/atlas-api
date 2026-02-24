"""Market data fetcher backed by Pyth Benchmarks + optional on-chain oracle."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
import logging
from typing import Optional

import aiohttp
import pandas as pd
from sqlalchemy import select
from web3 import Web3

from api.config import settings
from api.models.database import HistoricalCandle
from api.services.database import async_session

logger = logging.getLogger(__name__)

DEFAULT_PYTH_SYMBOLS = {
    "BTC": "Crypto.BTC/USD",
    "ETH": "Crypto.ETH/USD",
    "SOL": "Crypto.SOL/USD",
}


def _normalize_asset(asset: str) -> str:
    return (asset or "").strip().upper()


def _get_pyth_symbol(asset: str) -> Optional[str]:
    asset_key = _normalize_asset(asset)
    if not asset_key:
        return None
    if asset_key in settings.pyth_symbols:
        return settings.pyth_symbols[asset_key]
    return DEFAULT_PYTH_SYMBOLS.get(asset_key)


def _supported_assets() -> set[str]:
    assets = set(DEFAULT_PYTH_SYMBOLS.keys())
    assets.update({k.upper() for k in settings.pyth_symbols.keys()})
    assets.update({k.upper() for k in settings.pyth_price_ids.keys()})
    return {a for a in assets if a}


@dataclass
class PricePoint:
    asset: str
    price: float
    timestamp: datetime


class PythBenchmarksClient:
    async def fetch_history(
        self,
        symbol: str,
        resolution: str,
        from_ts: int,
        to_ts: int,
    ) -> dict:
        params = {"symbol": symbol, "resolution": resolution, "from": from_ts, "to": to_ts}
        async with aiohttp.ClientSession() as session:
            async with session.get(settings.pyth_benchmarks_url, params=params) as resp:
                data = await resp.json()
                if data.get("s") != "ok":
                    raise ValueError(f"Pyth API error: {data}")
                return data

    async def fetch_latest_price(self, asset: str) -> PricePoint:
        symbol = _get_pyth_symbol(asset)
        if not symbol:
            raise ValueError(f"No Pyth benchmark symbol configured for {asset}")
        now = int(datetime.utcnow().timestamp())
        data = await self.fetch_history(symbol, "1", now - 120, now)
        if not data.get("t"):
            raise ValueError("No price data returned")
        idx = -1
        price = float(data["c"][idx])
        timestamp = datetime.fromtimestamp(data["t"][idx], tz=timezone.utc)
        return PricePoint(asset=asset, price=price, timestamp=timestamp)


class PythOracleClient:
    def __init__(self) -> None:
        self.web3 = Web3(Web3.HTTPProvider(settings.arbitrum_rpc_url))
        self.contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(settings.pyth_oracle_address),
            abi=self._abi(),
        )

    def _abi(self) -> list[dict]:
        return [
            {
                "inputs": [{"name": "id", "type": "bytes32"}],
                "name": "getPriceUnsafe",
                "outputs": [
                    {"name": "price", "type": "int64"},
                    {"name": "conf", "type": "uint64"},
                    {"name": "expo", "type": "int32"},
                    {"name": "publishTime", "type": "uint64"},
                ],
                "stateMutability": "view",
                "type": "function",
            }
        ]

    def get_price(self, asset: str) -> PricePoint:
        asset_key = _normalize_asset(asset)
        price_id = settings.pyth_price_ids.get(asset_key)
        if not price_id or price_id.lower() in {"0x", ""}:
            raise ValueError(f"Missing Pyth price id for {asset_key}")
        price_id_bytes = Web3.to_bytes(hexstr=price_id)
        raw = self.contract.functions.getPriceUnsafe(price_id_bytes).call()
        price, _conf, expo, publish_time = raw
        scaled = float(price) * (10 ** int(expo))
        timestamp = datetime.fromtimestamp(int(publish_time), tz=timezone.utc)
        return PricePoint(asset=asset, price=scaled, timestamp=timestamp)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MarketDataFetcher:
    def __init__(self) -> None:
        self._buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=5000))
        self._lock = asyncio.Lock()
        self._benchmarks = PythBenchmarksClient()
        self._oracle: Optional[PythOracleClient] = None
        self._polling_task: Optional[asyncio.Task] = None
        if settings.arbitrum_rpc_url and settings.pyth_price_ids:
            self._oracle = PythOracleClient()

    async def get_current_price(self, asset: str) -> float:
        asset_key = _normalize_asset(asset)
        async with self._lock:
            if self._buffers[asset_key]:
                return float(self._buffers[asset_key][-1]["close"])
        try:
            price_id = settings.pyth_price_ids.get(asset_key)
            if self._oracle and price_id and price_id.lower() not in {"0x", ""}:
                return self._oracle.get_price(asset_key).price
        except Exception as exc:
            logger.warning("Oracle price failed for %s: %s", asset_key, exc)

        symbol = _get_pyth_symbol(asset_key)
        if not symbol:
            logger.warning("No Pyth benchmark symbol configured for %s", asset_key)
            return 0.0

        try:
            return (await self._benchmarks.fetch_latest_price(asset_key)).price
        except Exception as exc:
            logger.warning("Benchmark price failed for %s: %s", asset_key, exc)
            return 0.0

    async def get_candles(self, asset: str, timeframe: str, limit: int = 300) -> pd.DataFrame:
        asset_key = _normalize_asset(asset)
        asset_candidates = [asset] if asset == asset_key else [asset, asset_key]
        timeframe = timeframe.lower()
        if timeframe == "1m":
            async with self._lock:
                buffer = list(self._buffers[asset_key])[-limit:]
            rows: list = []
            try:
                async with async_session() as db:
                    result = await db.execute(
                        select(HistoricalCandle)
                        .where(HistoricalCandle.asset.in_(asset_candidates))
                        .where(HistoricalCandle.timeframe == timeframe)
                        .order_by(HistoricalCandle.timestamp.desc())
                        .limit(limit)
                    )
                    rows = list(reversed(result.scalars().all()))
            except Exception as exc:
                logger.warning("DB candle fetch failed for %s/1m: %s", asset, exc)
            combined: dict[datetime, dict] = {}
            for row in rows:
                ts = _ensure_utc(row.timestamp)
                combined[ts] = {
                    "timestamp": ts,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume) if row.volume is not None else 0.0,
                }
            for candle in buffer:
                ts = _ensure_utc(candle["timestamp"])
                combined[ts] = candle
            if not combined:
                return pd.DataFrame()
            ordered = [combined[ts] for ts in sorted(combined.keys())]
            return pd.DataFrame(ordered[-limit:])
        if timeframe in {"5m", "1h", "4h", "1d"}:
            try:
                async with async_session() as db:
                    result = await db.execute(
                        select(HistoricalCandle)
                        .where(HistoricalCandle.asset.in_(asset_candidates))
                        .where(HistoricalCandle.timeframe == timeframe)
                        .order_by(HistoricalCandle.timestamp.desc())
                        .limit(limit)
                    )
                    rows = list(reversed(result.scalars().all()))
                if rows:
                    return pd.DataFrame(
                        [
                            {
                                "timestamp": _ensure_utc(row.timestamp),
                                "open": float(row.open),
                                "high": float(row.high),
                                "low": float(row.low),
                                "close": float(row.close),
                                "volume": float(row.volume) if row.volume is not None else 0.0,
                            }
                            for row in rows
                        ]
                    )
            except Exception as exc:
                logger.warning("DB candle fetch failed for %s/%s: %s", asset, timeframe, exc)
            # Fall through to resample if no DB rows or DB error

        minutes = _timeframe_to_minutes(timeframe)
        # Cap the base request to avoid fetching too many 1m candles
        base_limit = min(limit * max(1, minutes), 5000)
        base = await self.get_candles(asset, "1m", limit=base_limit)
        if base.empty:
            return base
        base = base.copy()
        base["timestamp"] = pd.to_datetime(base["timestamp"])
        base = base.set_index("timestamp")
        rule = f"{minutes}min"
        agg = base.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        agg = agg.dropna().reset_index()
        return agg.tail(limit)

    async def start_price_polling(self, interval_seconds: int = 10) -> None:
        if self._polling_task:
            return

        async def _loop() -> None:
            while True:
                try:
                    await self._poll_once()
                except Exception as exc:
                    logger.warning("Price polling error: %s", exc)
                await asyncio.sleep(interval_seconds)

        self._polling_task = asyncio.create_task(_loop())

    async def stop_price_polling(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()
            self._polling_task = None

    async def _poll_once(self) -> None:
        for asset in _supported_assets():
            asset_key = _normalize_asset(asset)
            try:
                price_id = settings.pyth_price_ids.get(asset_key)
                if self._oracle and price_id and price_id.lower() not in {"0x", ""}:
                    price_point = self._oracle.get_price(asset_key)
                else:
                    symbol = _get_pyth_symbol(asset_key)
                    if not symbol:
                        logger.debug("Skipping price poll for %s (no Pyth symbol)", asset_key)
                        continue
                    price_point = await self._benchmarks.fetch_latest_price(asset_key)
                await self._update_candle(asset_key, price_point)
            except Exception as exc:
                logger.warning("Failed to update price for %s: %s", asset_key, exc)

    async def _update_candle(self, asset: str, price_point: PricePoint) -> None:
        asset_key = _normalize_asset(asset)
        timestamp = price_point.timestamp.replace(second=0, microsecond=0)
        should_persist = False
        async with self._lock:
            buffer = self._buffers[asset_key]
            if buffer and buffer[-1]["timestamp"] == timestamp:
                candle = buffer[-1]
                candle["high"] = max(candle["high"], price_point.price)
                candle["low"] = min(candle["low"], price_point.price)
                candle["close"] = price_point.price
            else:
                candle = {
                    "timestamp": timestamp,
                    "open": price_point.price,
                    "high": price_point.price,
                    "low": price_point.price,
                    "close": price_point.price,
                    "volume": 0.0,
                }
                buffer.append(candle)
                should_persist = True
        if should_persist:
            await self._persist_candle(asset_key, candle)

    async def _persist_candle(self, asset: str, candle: dict) -> None:
        async with async_session() as db:
            db.add(
                HistoricalCandle(
                    asset=_normalize_asset(asset),
                    timeframe="1m",
                    timestamp=candle["timestamp"],
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                )
            )
            await db.commit()

    def get_buffer_status(self) -> dict[str, int]:
        return {asset: len(buffer) for asset, buffer in self._buffers.items()}


_market_data: Optional[MarketDataFetcher] = None


def get_market_data() -> MarketDataFetcher:
    global _market_data
    if _market_data is None:
        _market_data = MarketDataFetcher()
    return _market_data


def _timeframe_to_minutes(timeframe: str) -> int:
    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    if timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    if timeframe.endswith("d"):
        return int(timeframe[:-1]) * 24 * 60
    return 1
