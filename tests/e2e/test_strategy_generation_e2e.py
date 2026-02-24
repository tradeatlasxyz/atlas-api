"""End-to-end tests for strategy signal generation.

These tests hit real external APIs (Pyth Benchmarks) and load real strategy files.
Run with: pytest tests/e2e/test_strategy_generation_e2e.py -m e2e -v
"""
import os
from pathlib import Path

import pytest

from api.execution.market_data import MarketDataFetcher, PythBenchmarksClient
from api.execution.signal_generator import SignalGenerator
from api.execution.strategy_loader import load_strategy_from_file, STRATEGIES_DIR


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pyth_benchmarks_fetch_btc_price():
    """Verify we can fetch BTC price from Pyth Benchmarks API."""
    client = PythBenchmarksClient()
    price_point = await client.fetch_latest_price("BTC")

    assert price_point.asset == "BTC"
    assert price_point.price > 0
    assert price_point.timestamp is not None


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pyth_benchmarks_fetch_history():
    """Verify we can fetch historical candle data from Pyth."""
    import time

    client = PythBenchmarksClient()
    now = int(time.time())
    # Fetch last 2 hours of 1-minute candles
    data = await client.fetch_history("Crypto.BTC/USD", "1", now - 7200, now)

    assert data.get("s") == "ok"
    assert "t" in data  # timestamps
    assert "o" in data  # open
    assert "h" in data  # high
    assert "l" in data  # low
    assert "c" in data  # close
    assert len(data["t"]) > 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_load_deployed_strategy():
    """Verify deployed strategies load correctly."""
    strategy_files = list(STRATEGIES_DIR.glob("*.py"))
    if not strategy_files:
        pytest.skip("No deployed strategies found")

    # Load the first available strategy
    strategy_path = strategy_files[0]
    strategy = load_strategy_from_file(strategy_path)

    assert strategy.slug == strategy_path.stem
    assert strategy.generate_signals is not None
    assert callable(strategy.generate_signals)
    assert strategy.asset in ["BTC", "ETH", "SOL"]


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_generate_signal_btc_momentum():
    """End-to-end test: load BTC momentum strategy and generate a signal."""
    strategy_path = STRATEGIES_DIR / "btc-momentum-1h.py"
    if not strategy_path.exists():
        pytest.skip("btc-momentum-1h.py strategy not found")

    # Load the real strategy
    strategy = load_strategy_from_file(strategy_path)
    assert strategy.slug == "btc-momentum-1h"
    assert strategy.asset == "BTC"

    # Create market data fetcher (uses real Pyth API)
    market_data = MarketDataFetcher()

    # Generate signal
    generator = SignalGenerator(market_data)
    signal = await generator.generate_signal(strategy)

    # Validate signal structure
    assert signal.direction in [-1, 0, 1]
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.current_price > 0
    assert signal.strategy_slug == "btc-momentum-1h"
    assert signal.asset == "BTC"
    assert signal.timeframe == "1H"
    assert signal.reason is not None

    # If actionable, validate risk levels
    if signal.is_actionable:
        assert signal.stop_loss is not None
        assert signal.take_profit is not None
        if signal.direction == 1:  # Long
            assert signal.stop_loss < signal.current_price < signal.take_profit
        else:  # Short
            assert signal.take_profit < signal.current_price < signal.stop_loss


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_all_deployed_strategies_loadable():
    """Verify all deployed strategies can be loaded and have valid structure."""
    strategy_files = list(STRATEGIES_DIR.glob("*.py"))
    if not strategy_files:
        pytest.skip("No deployed strategies found")

    import pandas as pd
    import numpy as np

    # Create mock data for testing generate_signals
    mock_df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="1h"),
        "open": np.random.uniform(40000, 50000, 100),
        "high": np.random.uniform(45000, 55000, 100),
        "low": np.random.uniform(35000, 45000, 100),
        "close": np.random.uniform(40000, 50000, 100),
        "volume": np.random.uniform(100, 1000, 100),
    })

    results = []
    for strategy_path in strategy_files:
        strategy = load_strategy_from_file(strategy_path)

        # Verify structure
        assert strategy.slug == strategy_path.stem
        assert strategy.generate_signals is not None
        assert callable(strategy.generate_signals)
        assert strategy.asset in ["BTC", "ETH", "SOL"]
        assert strategy.timeframe in ["1H", "4H", "1D"]

        # Verify generate_signals works with mock data
        signals = strategy.generate_signals(mock_df)
        assert isinstance(signals, np.ndarray)
        assert len(signals) == len(mock_df)
        assert all(s in [-1, 0, 1] for s in signals)

        results.append({
            "strategy": strategy.slug,
            "asset": strategy.asset,
            "timeframe": strategy.timeframe,
        })

    # Print summary for visibility
    print(f"\n=== Loaded {len(results)} deployed strategies ===")
    for r in results:
        print(f"  {r['strategy']}: {r['asset']} @ {r['timeframe']}")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_market_data_fetcher_candles():
    """Verify MarketDataFetcher can get candles for different timeframes."""
    market_data = MarketDataFetcher()

    # Test getting current price
    btc_price = await market_data.get_current_price("BTC")
    assert btc_price > 0

    eth_price = await market_data.get_current_price("ETH")
    assert eth_price > 0

    # Prices should be reasonable (sanity check)
    assert 10_000 < btc_price < 500_000  # BTC between $10k and $500k
    assert 500 < eth_price < 50_000  # ETH between $500 and $50k
