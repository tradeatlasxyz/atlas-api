from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from api.execution.strategy_loader import load_strategy_from_file


def test_load_strategy_from_file(tmp_path: Path) -> None:
    strategy_path = tmp_path / "test_strategy.py"
    strategy_path.write_text(
        """
import numpy as np
import pandas as pd

STRATEGY_META = {"asset": "BTC", "timeframe": "1H"}

def generate_signals(df: pd.DataFrame) -> np.ndarray:
    return np.zeros(len(df))
"""
    )

    loaded = load_strategy_from_file(strategy_path)
    assert loaded.slug == "test_strategy"
    assert loaded.asset == "BTC"
    assert loaded.timeframe == "1H"

    df = pd.DataFrame({"close": [100, 101, 102]})
    signals = loaded.generate_signals(df)
    assert isinstance(signals, np.ndarray)


def test_load_strategy_defaults(tmp_path: Path) -> None:
    strategy_path = tmp_path / "defaults.py"
    strategy_path.write_text(
        """
def generate_signals(df):
    return [0 for _ in range(len(df))]

STRATEGY_META = {}
"""
    )

    loaded = load_strategy_from_file(strategy_path)
    assert loaded.asset == "BTC"
    assert loaded.timeframe == "1H"
    assert loaded.stop_loss_pct == 0.02
    assert loaded.take_profit_pct == 0.05


def test_missing_generate_signals_raises(tmp_path: Path) -> None:
    strategy_path = tmp_path / "missing_fn.py"
    strategy_path.write_text("STRATEGY_META = {}")

    with pytest.raises(AttributeError):
        load_strategy_from_file(strategy_path)
