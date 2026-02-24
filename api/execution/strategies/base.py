from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class BaseStrategy(ABC):
    """Base class for structured strategies."""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> np.ndarray:
        """Generate signals from OHLCV data."""
        raise NotImplementedError


def generate_signals(df: pd.DataFrame) -> np.ndarray:
    """Standard function interface for strategy files."""
    raise NotImplementedError("Strategy must implement generate_signals")
