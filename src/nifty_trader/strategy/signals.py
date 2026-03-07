"""Individual signal evaluators — each returns BULLISH / BEARISH / NEUTRAL."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from nifty_trader.config import StrategyConfig
from nifty_trader.constants import Direction
from nifty_trader.data.indicators import (
    ema,
    ema_crossover,
    is_green_candle,
    is_red_candle,
    is_volume_spike,
    rsi,
    vwap,
)
from nifty_trader.strategy.levels import LevelDetector

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    name: str
    direction: Direction
    strength: float  # 0.0 to 1.0
    reason: str


def evaluate_ema(df: pd.DataFrame, cfg: StrategyConfig) -> SignalResult:
    """EMA crossover signal."""
    fast = ema(df["close"], cfg.ema_fast)
    slow = ema(df["close"], cfg.ema_slow)
    cross = ema_crossover(fast, slow)
    last_cross = cross.iloc[-1]
    price = df["close"].iloc[-1]
    last_slow = slow.iloc[-1]

    if last_cross == 1 and price > last_slow:
        return SignalResult("ema", Direction.BULLISH, 1.0, "EMA9 crossed above EMA21, price > EMA21")
    if last_cross == -1 and price < last_slow:
        return SignalResult("ema", Direction.BEARISH, 1.0, "EMA9 crossed below EMA21, price < EMA21")

    # Check persistent trend (no fresh cross but still trending)
    if fast.iloc[-1] > slow.iloc[-1] and price > last_slow:
        return SignalResult("ema", Direction.BULLISH, 0.5, "EMA9 > EMA21, price above slow EMA")
    if fast.iloc[-1] < slow.iloc[-1] and price < last_slow:
        return SignalResult("ema", Direction.BEARISH, 0.5, "EMA9 < EMA21, price below slow EMA")

    return SignalResult("ema", Direction.NEUTRAL, 0.0, "No EMA signal")


def evaluate_vwap(df: pd.DataFrame, cfg: StrategyConfig) -> SignalResult:
    """VWAP position signal — price above/below for N candles."""
    vwap_line = vwap(df["high"], df["low"], df["close"], df["volume"])
    n = cfg.vwap_confirm_candles
    recent_close = df["close"].iloc[-n:]
    recent_vwap = vwap_line.iloc[-n:]

    if recent_close.empty or recent_vwap.isna().any():
        return SignalResult("vwap", Direction.NEUTRAL, 0.0, "Insufficient VWAP data")

    above = (recent_close.values > recent_vwap.values).all()
    below = (recent_close.values < recent_vwap.values).all()

    if above:
        return SignalResult("vwap", Direction.BULLISH, 1.0, f"Price above VWAP for {n} candles")
    if below:
        return SignalResult("vwap", Direction.BEARISH, 1.0, f"Price below VWAP for {n} candles")

    return SignalResult("vwap", Direction.NEUTRAL, 0.0, "Price oscillating around VWAP")


def evaluate_rsi(df: pd.DataFrame, cfg: StrategyConfig) -> SignalResult:
    """RSI reversal signal."""
    rsi_vals = rsi(df["close"], cfg.rsi_period)
    if rsi_vals.isna().all():
        return SignalResult("rsi", Direction.NEUTRAL, 0.0, "Insufficient RSI data")

    current = rsi_vals.iloc[-1]
    prev = rsi_vals.iloc[-2] if len(rsi_vals) > 1 else current

    # Bullish: recovering from oversold
    if prev < cfg.rsi_oversold and current >= cfg.rsi_bullish_entry:
        return SignalResult("rsi", Direction.BULLISH, 1.0, f"RSI recovering from oversold ({current:.1f})")
    if current < cfg.rsi_oversold:
        return SignalResult("rsi", Direction.BULLISH, 0.6, f"RSI oversold ({current:.1f}), awaiting cross")

    # Bearish: dropping from overbought
    if prev > cfg.rsi_overbought and current <= cfg.rsi_bearish_entry:
        return SignalResult("rsi", Direction.BEARISH, 1.0, f"RSI dropping from overbought ({current:.1f})")
    if current > cfg.rsi_overbought:
        return SignalResult("rsi", Direction.BEARISH, 0.6, f"RSI overbought ({current:.1f}), awaiting cross")

    return SignalResult("rsi", Direction.NEUTRAL, 0.0, f"RSI neutral ({current:.1f})")


def evaluate_volume(df: pd.DataFrame, cfg: StrategyConfig) -> SignalResult:
    """Volume spike with directional candle."""
    spike = is_volume_spike(df["volume"], cfg.volume_sma_period, cfg.volume_spike_multiplier)
    if not spike.iloc[-1]:
        return SignalResult("volume", Direction.NEUTRAL, 0.0, "No volume spike")

    green = is_green_candle(df["open"], df["close"]).iloc[-1]
    red = is_red_candle(df["open"], df["close"]).iloc[-1]

    if green:
        return SignalResult("volume", Direction.BULLISH, 1.0, "Green candle + volume spike")
    if red:
        return SignalResult("volume", Direction.BEARISH, 1.0, "Red candle + volume spike")

    return SignalResult("volume", Direction.NEUTRAL, 0.0, "Volume spike but doji candle")


def evaluate_levels(
    df: pd.DataFrame,
    detector: LevelDetector,
    cfg: StrategyConfig,
) -> SignalResult:
    """Key level bounce/rejection signal."""
    price = float(df["close"].iloc[-1])
    threshold = cfg.level_proximity_pct

    if detector.is_near_support(price, threshold):
        # Check if bouncing (current candle green)
        if is_green_candle(df["open"], df["close"]).iloc[-1]:
            return SignalResult("levels", Direction.BULLISH, 1.0, "Bounce off support")
    if detector.is_near_resistance(price, threshold):
        if is_red_candle(df["open"], df["close"]).iloc[-1]:
            return SignalResult("levels", Direction.BEARISH, 1.0, "Rejection at resistance")

    return SignalResult("levels", Direction.NEUTRAL, 0.0, "Not near key level")
