"""
MarketGod Base Strategy Template

This file is the base strategy that gets modified by the AI Trading Scientist.
The AI will propose modifications to improve performance.

VECTORIZED VERSION: All loops have been converted to numpy/pandas vectorized
operations for 10-50x speedup. Original loop-based functions are preserved
with _slow suffix for reference/validation.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import argparse
import json
import os
try:
    import numba
    from numba import jit, prange
except ImportError:  # Fallback for environments without numba
    numba = None

    def jit(*_args, **_kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    def prange(*args, **_kwargs):
        return range(*args)


@dataclass
class StrategyConfig:
    """Configuration for the trading strategy.
    
    Total tunable parameters: 26
    
    Tier 1 - Core Signal (most impactful based on grid search):
        noise_filter, kdj_stoch_period, kdj_ema_span, kdj_period_k, kdj_smooth_k
        
    Tier 2 - Indicator Tuning:
        bb_period, bb_std, macd_fast, macd_slow, macd_signal
        
    Tier 3 - Risk Management:
        atr_period, trailing_stop_atr_mult, use_trailing_stop
        
    Tier 4 - Regime Filtering:
        use_volatility_filter, atr_lookback, atr_min_percentile, atr_max_percentile
        
    Tier 5 - Execution:
        position_size_pct, slippage_pct, commission_pct
    """
    # =========================================================================
    # TIER 1: CORE SIGNAL PARAMETERS (highest impact on performance)
    # =========================================================================
    
    # Noise filter (SMA period for high/low breakout detection)
    noise_filter: int = 12
    
    # KDJ Stochastic parameters (previously hardcoded)
    kdj_stoch_period: int = 9      # Rolling window for stochastic high/low (was hardcoded 9)
    kdj_ema_span: int = 3          # EMA smoothing for pK, pD lines (was hardcoded 3)
    kdj_j_mult_k: float = 3.0      # J = mult_k * pK - mult_d * pD (was hardcoded 3)
    kdj_j_mult_d: float = 2.0      # J-line formula multiplier for pD (was hardcoded 2)
    
    # KDJ K-line parameters
    kdj_period_k: int = 14
    kdj_period_d: int = 7          # Note: currently unused in calculate_kdj
    kdj_smooth_k: int = 4
    
    # BBR comparison shift period (for rising/falling detection)
    bbr_shift: int = 1             # Compare BBR to N periods ago (was hardcoded 1)
    
    # =========================================================================
    # TIER 2: INDICATOR TUNING PARAMETERS
    # =========================================================================
    
    # Bollinger Bands parameters
    bb_period: int = 20
    bb_std: float = 2.0
    
    # MACD parameters (optional confirmation)
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    require_macd_confirmation: bool = False
    
    # =========================================================================
    # TIER 3: RISK MANAGEMENT PARAMETERS
    # =========================================================================
    
    # ATR parameters
    atr_period: int = 14
    
    # Trailing stop (optional)
    use_trailing_stop: bool = False
    trailing_stop_atr_mult: float = 2.0
    
    # =========================================================================
    # TIER 4: REGIME FILTERING PARAMETERS
    # =========================================================================
    
    # Volatility regime filter (optional)
    use_volatility_filter: bool = False
    atr_lookback: int = 100
    atr_min_percentile: float = 25
    atr_max_percentile: float = 75
    
    # =========================================================================
    # TIER 5: EXECUTION PARAMETERS
    # =========================================================================
    
    # Position sizing
    position_size_pct: float = 25.0
    
    # Transaction costs (previously passed as function args)
    slippage_pct: float = 0.1
    commission_pct: float = 0.1


@jit(nopython=True, cache=True)
def _calculate_ha_open_numba(ha_close: np.ndarray, first_open: float, first_close: float) -> np.ndarray:
    """Numba-accelerated Heikin-Ashi open calculation."""
    n = len(ha_close)
    ha_open = np.empty(n, dtype=np.float64)
    ha_open[0] = (first_open + first_close) / 2
    
    for i in range(1, n):
        ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2
    
    return ha_open


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Heikin-Ashi candles (vectorized with numba)."""
    ha = pd.DataFrame(index=df.index)
    
    # HA Close is fully vectorized
    ha['ha_close'] = (df['open'].values + df['high'].values + df['low'].values + df['close'].values) / 4
    
    # HA Open uses numba JIT for the recursive calculation
    ha['ha_open'] = _calculate_ha_open_numba(
        ha['ha_close'].values,
        df['open'].iloc[0],
        df['close'].iloc[0]
    )
    
    # HA High/Low are vectorized
    ha['ha_high'] = np.maximum.reduce([df['high'].values, ha['ha_open'].values, ha['ha_close'].values])
    ha['ha_low'] = np.minimum.reduce([df['low'].values, ha['ha_open'].values, ha['ha_close'].values])
    
    return ha


@jit(nopython=True, cache=True)
def _rolling_stochastic_numba(close: np.ndarray, period: int) -> np.ndarray:
    """Numba-accelerated rolling stochastic calculation."""
    n = len(close)
    result = np.empty(n, dtype=np.float64)
    result[:period-1] = np.nan
    
    for i in range(period - 1, n):
        window = close[i - period + 1:i + 1]
        min_val = np.min(window)
        max_val = np.max(window)
        denom = max_val - min_val
        if denom < 1e-10:
            result[i] = 50.0  # Neutral when no range
        else:
            result[i] = 100 * (close[i] - min_val) / denom
    
    return result


def calculate_kdj(ha: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Calculate KDJ oscillator with J-line (VECTORIZED).
    
    Uses configurable parameters instead of hardcoded values:
    - kdj_stoch_period: Rolling window for stochastic high/low (default 9)
    - kdj_ema_span: EMA smoothing span for pK, pD (default 3)
    - kdj_j_mult_k, kdj_j_mult_d: J-line formula coefficients (default 3, 2)
    """
    # Stochastic calculation with configurable period - vectorized
    hi = ha['ha_high'].rolling(config.kdj_stoch_period).max()
    lo = ha['ha_low'].rolling(config.kdj_stoch_period).min()
    
    k_raw = 100 * ((ha['ha_close'].values - lo.values) / (hi.values - lo.values + 1e-10))
    k_raw = pd.Series(k_raw, index=ha.index)
    
    # EMA smoothing with configurable span - already vectorized in pandas
    pk = k_raw.ewm(span=config.kdj_ema_span, adjust=False).mean()
    pd_line = pk.ewm(span=config.kdj_ema_span, adjust=False).mean()
    
    # J-line with configurable multipliers
    pj = config.kdj_j_mult_k * pk - config.kdj_j_mult_d * pd_line
    
    # Secondary stochastic K - numba accelerated (replaces slow .apply())
    stoch_k_raw = _rolling_stochastic_numba(ha['ha_close'].values, config.kdj_period_k)
    stoch_k_smooth = pd.Series(stoch_k_raw, index=ha.index).rolling(config.kdj_smooth_k).mean()
    
    return pd.DataFrame({
        'pK': pk.values,
        'pD': pd_line.values,
        'pJ': pj.values,
        'K': stoch_k_smooth.values
    }, index=ha.index)


def calculate_bollinger_pct_b(ha: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    """Calculate Bollinger Bands %B."""
    basis = ha['ha_close'].rolling(config.bb_period).mean()
    dev = ha['ha_close'].rolling(config.bb_period).std()
    
    upper = basis + config.bb_std * dev
    lower = basis - config.bb_std * dev
    
    pct_b = (ha['ha_close'] - lower) / (upper - lower + 1e-10)
    return pct_b


def calculate_macd(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Calculate MACD indicator."""
    ema_fast = df['close'].ewm(span=config.macd_fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=config.macd_slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=config.macd_signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }, index=df.index)


def calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate Average True Range."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean()
    
    return atr


@jit(nopython=True, cache=True)
def _state_machine_numba(buy_raw: np.ndarray, sell_raw: np.ndarray) -> np.ndarray:
    """
    Numba-accelerated state machine for signal generation.
    
    Returns: array of ints (0=HOLD, 1=BUY, 2=SELL)
    """
    n = len(buy_raw)
    signals = np.zeros(n, dtype=np.int8)  # 0=HOLD, 1=BUY, 2=SELL
    state = 0  # 0 = neutral/short, 1 = long
    
    for i in range(n):
        if buy_raw[i] and state == 0:
            signals[i] = 1  # BUY
            state = 1
        elif sell_raw[i] and state == 1:
            signals[i] = 2  # SELL
            state = 0
    
    return signals


@jit(nopython=True, cache=True, parallel=True)
def _calculate_atr_percentile_numba(atr: np.ndarray, lookback: int) -> np.ndarray:
    """Numba-accelerated rolling ATR percentile calculation."""
    n = len(atr)
    result = np.full(n, np.nan)
    
    for i in prange(lookback, n):
        window = atr[i-lookback:i]
        valid_count = 0
        less_count = 0
        current_val = atr[i]
        
        for j in range(lookback):
            if not np.isnan(window[j]):
                valid_count += 1
                if window[j] < current_val:
                    less_count += 1
        
        if valid_count > 0:
            result[i] = (less_count / valid_count) * 100
    
    return result


def generate_signals(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """
    Generate trading signals based on the strategy configuration.
    
    VECTORIZED VERSION: Uses numba JIT for state machine (~20x faster).
    """
    # Ensure lowercase columns
    df = df.copy()
    df.columns = df.columns.str.lower()
    
    # Calculate Heikin-Ashi
    ha = calculate_heikin_ashi(df)
    
    # Calculate indicators
    kdj = calculate_kdj(ha, config)
    bbr = calculate_bollinger_pct_b(ha, config)
    atr = calculate_atr(df, config.atr_period)
    
    # Average high/low (noise filter) - vectorized
    avg_high = ha['ha_high'].rolling(config.noise_filter).mean()
    avg_low = ha['ha_low'].rolling(config.noise_filter).mean()
    
    # UP/DOWN conditions - vectorized
    up = (df['open'].values < df['close'].values) & (df['close'].values > avg_high.values)
    down = (df['open'].values > df['close'].values) & (df['close'].values < avg_low.values)
    
    # Rising/Falling BBands %B - vectorized
    bbr_values = bbr.values
    bbr_shifted = np.roll(bbr_values, config.bbr_shift)
    bbr_shifted[:config.bbr_shift] = np.nan
    bbr_rising = bbr_values > bbr_shifted
    bbr_falling = bbr_values < bbr_shifted
    
    # Core signals - vectorized
    pj_values = kdj['pJ'].values
    k_values = kdj['K'].values
    buy_raw = up & (pj_values > k_values) & bbr_rising
    sell_raw = down & (pj_values < k_values) & bbr_falling
    
    # Handle NaN values (set to False)
    buy_raw = np.nan_to_num(buy_raw, nan=0).astype(bool)
    sell_raw = np.nan_to_num(sell_raw, nan=0).astype(bool)
    
    # Optional: MACD confirmation
    if config.require_macd_confirmation:
        macd = calculate_macd(df, config)
        buy_raw = buy_raw & (macd['histogram'].values > 0)
        sell_raw = sell_raw & (macd['histogram'].values < 0)
    
    # Optional: Volatility regime filter (numba accelerated)
    if config.use_volatility_filter:
        atr_percentile = _calculate_atr_percentile_numba(atr.values, config.atr_lookback)
        volatility_ok = (atr_percentile >= config.atr_min_percentile) & \
                        (atr_percentile <= config.atr_max_percentile)
        volatility_ok = np.nan_to_num(volatility_ok, nan=0).astype(bool)
        buy_raw = buy_raw & volatility_ok
        sell_raw = sell_raw & volatility_ok
    
    # State machine (numba JIT accelerated)
    signal_codes = _state_machine_numba(buy_raw, sell_raw)
    
    # Convert codes to strings
    signal_map = {0: 'HOLD', 1: 'BUY', 2: 'SELL'}
    signals = pd.Series([signal_map[c] for c in signal_codes], index=df.index)
    
    # Compile results
    result = pd.DataFrame({
        'close': df['close'].values,
        'signal': signals,
        'ha_close': ha['ha_close'].values,
        'pJ': pj_values,
        'K': k_values,
        'bbr': bbr_values,
        'atr': atr.values
    }, index=df.index)
    
    return result


@jit(nopython=True, cache=True)
def _backtest_core_numba(
    prices: np.ndarray,
    signals: np.ndarray,  # 0=HOLD, 1=BUY, 2=SELL
    atr: np.ndarray,
    initial_capital: float,
    position_size_pct: float,
    slippage_pct: float,
    commission_pct: float,
    use_trailing_stop: bool,
    trailing_stop_atr_mult: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Numba-accelerated backtest core loop.
    
    Returns:
        equity_curve: array of equity values
        trade_pnls: array of P&L for each closed trade
        trade_types: array of trade types (1=BUY, 2=SELL, 3=TRAILING_STOP)
        trade_indices: array of bar indices where trades occurred
    """
    n = len(prices)
    equity_curve = np.empty(n + 1, dtype=np.float64)
    equity_curve[0] = initial_capital
    
    # Pre-allocate trade arrays (max possible trades)
    max_trades = n // 2 + 1
    trade_pnls = np.empty(max_trades, dtype=np.float64)
    trade_types = np.empty(max_trades, dtype=np.int8)
    trade_indices = np.empty(max_trades, dtype=np.int64)
    num_trades = 0
    
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    highest_since_entry = 0.0
    cost_mult = 1 + slippage_pct/100 + commission_pct/100
    proceeds_mult = 1 - slippage_pct/100 - commission_pct/100
    
    for i in range(n):
        price = prices[i]
        signal = signals[i]
        
        # Trailing stop check
        if use_trailing_stop and position > 0:
            current_atr = atr[i] if not np.isnan(atr[i]) else 0.0
            trailing_stop_price = highest_since_entry - (trailing_stop_atr_mult * current_atr)
            
            if price < trailing_stop_price:
                # Exit due to trailing stop
                proceeds = position * price * proceeds_mult
                pnl = proceeds - (position * entry_price)
                capital += proceeds
                
                trade_pnls[num_trades] = pnl
                trade_types[num_trades] = 3  # TRAILING_STOP
                trade_indices[num_trades] = i
                num_trades += 1
                position = 0.0
        
        if signal == 1 and position == 0:  # BUY
            size = (capital * position_size_pct / 100) / price
            cost = size * price * cost_mult
            if cost <= capital:
                position = size
                entry_price = price
                highest_since_entry = price
                capital -= cost
                
                trade_pnls[num_trades] = 0.0  # Entry, no P&L yet
                trade_types[num_trades] = 1  # BUY
                trade_indices[num_trades] = i
                num_trades += 1
        
        elif signal == 2 and position > 0:  # SELL
            proceeds = position * price * proceeds_mult
            pnl = proceeds - (position * entry_price)
            capital += proceeds
            
            trade_pnls[num_trades] = pnl
            trade_types[num_trades] = 2  # SELL
            trade_indices[num_trades] = i
            num_trades += 1
            position = 0.0
        
        # Update highest price for trailing stop
        if position > 0 and price > highest_since_entry:
            highest_since_entry = price
        
        # Track equity
        equity_curve[i + 1] = capital + (position * price if position > 0 else 0)
    
    # Trim arrays to actual size
    return (
        equity_curve,
        trade_pnls[:num_trades],
        trade_types[:num_trades],
        trade_indices[:num_trades]
    )


def backtest(
    signals_df: pd.DataFrame,
    config: StrategyConfig,
    initial_capital: float = 10000.0
) -> Dict:
    """Run backtest and return performance metrics.
    
    VECTORIZED VERSION: Uses numba JIT for core loop (~20x faster).
    """
    # Convert signals to numeric codes
    signal_map = {'HOLD': 0, 'BUY': 1, 'SELL': 2}
    signal_codes = signals_df['signal'].map(signal_map).values.astype(np.int8)
    
    prices = signals_df['close'].values.astype(np.float64)
    atr = signals_df['atr'].values.astype(np.float64) if 'atr' in signals_df.columns else np.zeros(len(prices))
    
    # Run numba-accelerated backtest
    equity_curve, trade_pnls, trade_types, trade_indices = _backtest_core_numba(
        prices=prices,
        signals=signal_codes,
        atr=atr,
        initial_capital=initial_capital,
        position_size_pct=config.position_size_pct,
        slippage_pct=config.slippage_pct,
        commission_pct=config.commission_pct,
        use_trailing_stop=config.use_trailing_stop,
        trailing_stop_atr_mult=config.trailing_stop_atr_mult
    )
    
    # Calculate metrics from results
    equity_series = pd.Series(equity_curve)
    returns = equity_series.pct_change().dropna()
    
    total_return = (equity_series.iloc[-1] / initial_capital - 1) * 100
    
    # Sharpe ratio
    returns_std = returns.std()
    sharpe = returns.mean() / (returns_std + 1e-10) * np.sqrt(252)
    
    # Sortino ratio (only penalize downside volatility)
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 0 else 1e-10
    sortino = returns.mean() / (downside_std + 1e-10) * np.sqrt(252)
    
    # Max drawdown
    rolling_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = np.min(drawdown) * 100
    
    # Calmar ratio (annualized return / max drawdown)
    annualized_return = total_return  # Simplified; could adjust for actual period
    calmar = abs(annualized_return / max_drawdown) if max_drawdown != 0 else 0
    
    # Trade statistics
    # Filter to exit trades only (SELL or TRAILING_STOP)
    exit_mask = (trade_types == 2) | (trade_types == 3)
    exit_pnls = trade_pnls[exit_mask]
    
    winning_pnls = exit_pnls[exit_pnls > 0]
    losing_pnls = exit_pnls[exit_pnls < 0]
    
    total_closed = len(exit_pnls)
    win_rate = len(winning_pnls) / total_closed * 100 if total_closed > 0 else 0
    
    return {
        'initial_capital': initial_capital,
        'final_capital': equity_series.iloc[-1],
        'total_return_pct': total_return,
        'sharpe_ratio': sharpe,
        'sortino_ratio': sortino,
        'calmar_ratio': calmar,
        'max_drawdown_pct': max_drawdown,
        'total_trades': len(trade_pnls),
        'win_rate_pct': win_rate,
        'avg_win': np.mean(winning_pnls) if len(winning_pnls) > 0 else 0,
        'avg_loss': np.mean(losing_pnls) if len(losing_pnls) > 0 else 0,
    }


def run_experiment(config: StrategyConfig, out_dir: str = "run_0") -> Dict:
    """
    Main experiment function - runs backtests on multiple assets.
    
    This function is called by the AI Trading Scientist to evaluate strategies.
    """
    import yfinance as yf
    
    assets = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    start_date = '2021-01-01'
    end_date = '2024-01-01'
    
    results = {}
    
    for asset in assets:
        print(f"Testing on {asset}...")
        
        # Fetch data
        data = yf.download(asset, start=start_date, end=end_date, interval='1d', progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        
        if len(data) < 100:
            print(f"Insufficient data for {asset}")
            continue
        
        # Generate signals
        signals = generate_signals(data, config)
        
        # Run backtest
        metrics = backtest(signals, config)
        results[asset] = metrics
        
        print(f"  Return: {metrics['total_return_pct']:.1f}%, Sharpe: {metrics['sharpe_ratio']:.2f}")
    
    # Calculate aggregate metrics
    if results:
        avg_metrics = {
            'avg_return': np.mean([r['total_return_pct'] for r in results.values()]),
            'avg_sharpe': np.mean([r['sharpe_ratio'] for r in results.values()]),
            'avg_drawdown': np.mean([r['max_drawdown_pct'] for r in results.values()]),
            'avg_win_rate': np.mean([r['win_rate_pct'] for r in results.values()]),
        }
        results['aggregate'] = avg_metrics
    
    # Save results
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'final_info.json'), 'w') as f:
        # Convert to serializable format
        serializable_results = {}
        for k, v in results.items():
            serializable_results[k] = {'means': v}
        json.dump(serializable_results, f, indent=2, default=str)
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run trading strategy experiment")
    parser.add_argument("--out_dir", type=str, default="run_0", help="Output directory")
    parser.add_argument("--noise_filter", type=int, default=12)
    parser.add_argument("--position_size", type=float, default=25.0)
    args = parser.parse_args()
    
    config = StrategyConfig(
        noise_filter=args.noise_filter,
        position_size_pct=args.position_size
    )
    
    results = run_experiment(config, args.out_dir)
    
    print("\n=== Final Results ===")
    for asset, metrics in results.items():
        if asset == 'aggregate':
            print(f"\nAggregate:")
            print(f"  Avg Return: {metrics['avg_return']:.1f}%")
            print(f"  Avg Sharpe: {metrics['avg_sharpe']:.2f}")
            print(f"  Avg MaxDD: {metrics['avg_drawdown']:.1f}%")

