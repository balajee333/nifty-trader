"""Technical indicators — pure numpy/pandas, no external TA libs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    # When avg_loss is 0 (all gains), RSI = 100
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # Fill NaN from zero-loss periods with 100 (pure uptrend)
    result = result.fillna(100.0)
    return result


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Volume Weighted Average Price (intraday, resets assumed by caller)."""
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    return sma(volume, period)


def is_volume_spike(volume: pd.Series, period: int = 20, multiplier: float = 1.5) -> pd.Series:
    """True where current volume exceeds multiplier × SMA(volume, period)."""
    avg = volume_sma(volume, period)
    return volume > (avg * multiplier)


def ema_crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    Returns:
        +1 where fast crosses above slow (bullish)
        -1 where fast crosses below slow (bearish)
         0 otherwise
    """
    prev_fast = fast.shift(1)
    prev_slow = slow.shift(1)

    bullish = (prev_fast <= prev_slow) & (fast > slow)
    bearish = (prev_fast >= prev_slow) & (fast < slow)

    result = pd.Series(0, index=fast.index)
    result[bullish] = 1
    result[bearish] = -1
    return result


def is_green_candle(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True for bullish (green) candles."""
    return close > open_


def is_red_candle(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True for bearish (red) candles."""
    return close < open_


def pivot_levels(high: float, low: float, close: float) -> dict[str, float]:
    """Standard pivot point levels from daily H/L/C."""
    pivot = (high + low + close) / 3
    return {
        "r3": high + 2 * (pivot - low),
        "r2": pivot + (high - low),
        "r1": 2 * pivot - low,
        "pivot": pivot,
        "s1": 2 * pivot - high,
        "s2": pivot - (high - low),
        "s3": low - 2 * (high - pivot),
    }


def round_number_levels(price: float, step: int = 100) -> list[float]:
    """Generate round number support/resistance levels around price."""
    base = int(price / step) * step
    return [float(base + i * step) for i in range(-3, 4)]
