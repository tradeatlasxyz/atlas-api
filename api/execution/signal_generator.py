"""Generate signals by running loaded strategy code."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np

from api.execution.market_data import MarketDataFetcher
from api.execution.models import Signal
from api.execution.strategy_loader import LoadedStrategy

logger = logging.getLogger(__name__)


class SignalGenerator:
    def __init__(self, market_data: MarketDataFetcher):
        self.market_data = market_data

    async def generate_signal(self, strategy: LoadedStrategy) -> Signal:
        asset = strategy.asset
        timeframe = strategy.timeframe

        try:
            current_price = await self.market_data.get_current_price(asset)
            df = await self.market_data.get_candles(asset, timeframe, limit=300)
            if current_price <= 0:
                logger.warning("Missing current price for %s", asset)
                return self._neutral_signal(strategy, current_price, "Missing market price")
            if df.empty or len(df) < 10:
                logger.warning("Insufficient data for %s: %s candles", asset, len(df))
                return self._neutral_signal(strategy, current_price, "Insufficient data")
        except Exception as exc:
            logger.error("Market data error: %s", exc)
            return self._neutral_signal(strategy, 0.0, f"Market data error: {exc}")

        try:
            signals = strategy.generate_signals(df)
            if isinstance(signals, np.ndarray):
                latest_signal = int(signals[-1])
            else:
                latest_signal = int(signals)
            if latest_signal not in [-1, 0, 1]:
                logger.warning("Invalid signal value: %s", latest_signal)
                latest_signal = 0
        except Exception as exc:
            logger.exception("Strategy execution error: %s", exc)
            return self._neutral_signal(strategy, current_price, f"Strategy error: {exc}")

        direction = latest_signal
        confidence = self._calculate_confidence(signals)
        size_pct = self._calculate_size(direction, confidence)
        reason = self._generate_reason(strategy, direction, df)

        stop_loss, take_profit = self._calculate_risk_levels(
            strategy, direction, current_price
        )

        signal = Signal(
            direction=direction,
            confidence=confidence,
            size_pct=size_pct,
            reason=reason,
            timestamp=datetime.utcnow(),
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_slug=strategy.slug,
            asset=asset,
            timeframe=timeframe,
        )

        logger.info(
            "Signal: %s %s @ $%.2f (confidence %.2f)",
            signal.direction_str,
            asset,
            current_price,
            confidence,
        )
        return signal

    def _neutral_signal(
        self, strategy: LoadedStrategy, price: float, reason: str
    ) -> Signal:
        return Signal(
            direction=0,
            confidence=0.0,
            size_pct=0.0,
            reason=reason,
            current_price=price,
            strategy_slug=strategy.slug,
            asset=strategy.asset,
            timeframe=strategy.timeframe,
        )

    def _calculate_confidence(self, signals: np.ndarray) -> float:
        if len(signals) < 5:
            return 0.5
        recent = signals[-5:]
        latest = recent[-1]
        if latest == 0:
            return 0.0
        agreeing = sum(1 for s in recent if s == latest)
        confidence = agreeing / len(recent)
        return min(max(confidence, 0.0), 1.0)

    def _calculate_size(self, direction: int, confidence: float) -> float:
        if direction == 0:
            return 0.0
        base_size = 1.0
        size = base_size * confidence
        return max(0.1, min(size, 1.0))

    def _calculate_risk_levels(
        self, strategy: LoadedStrategy, direction: int, price: float
    ) -> tuple[Optional[float], Optional[float]]:
        if direction == 0 or price == 0:
            return None, None
        stop_pct = strategy.stop_loss_pct
        tp_pct = strategy.take_profit_pct
        if direction == 1:
            stop = price * (1 - stop_pct)
            take = price * (1 + tp_pct)
        else:
            stop = price * (1 + stop_pct)
            take = price * (1 - tp_pct)
        return round(stop, 2), round(take, 2)

    def _generate_reason(self, strategy: LoadedStrategy, direction: int, df) -> str:
        if direction == 0:
            return "No signal generated"
        direction_str = "LONG" if direction == 1 else "SHORT"
        return f"{direction_str} signal from {strategy.slug} on {strategy.asset} ({strategy.timeframe})"
