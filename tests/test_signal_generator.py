import pandas as pd
import numpy as np
import pytest

from api.execution.signal_generator import SignalGenerator
from api.execution.strategy_loader import LoadedStrategy


@pytest.mark.asyncio
async def test_generate_signal_actionable():
    def mock_generate_signals(df):
        return np.array([0, 0, 1])

    strategy = LoadedStrategy(
        slug="test-strategy",
        generate_signals=mock_generate_signals,
        meta={"asset": "BTC", "timeframe": "1H", "stop_loss_pct": 0.02, "take_profit_pct": 0.04},
        code_path=None,
    )

    class MockMarketData:
        async def get_current_price(self, asset: str) -> float:
            return 50000.0

        async def get_candles(self, asset: str, timeframe: str, limit: int = 300):
            freq = timeframe.lower()
            if freq.endswith("m"):
                freq = f"{freq[:-1]}min"
            return pd.DataFrame(
                {
                    "timestamp": pd.date_range("2024-01-01", periods=20, freq=freq),
                    "open": [50000] * 20,
                    "high": [50500] * 20,
                    "low": [49500] * 20,
                    "close": [50000] * 20,
                    "volume": [100] * 20,
                }
            )

    generator = SignalGenerator(MockMarketData())
    signal = await generator.generate_signal(strategy)
    assert signal.direction == 1
    assert signal.is_actionable
    assert signal.asset == "BTC"
