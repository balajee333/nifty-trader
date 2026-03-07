"""Tests for technical indicators."""

import numpy as np
import pandas as pd
import pytest

from nifty_trader.data.indicators import (
    ema,
    ema_crossover,
    is_green_candle,
    is_red_candle,
    is_volume_spike,
    pivot_levels,
    round_number_levels,
    rsi,
    sma,
    vwap,
)


@pytest.fixture
def sample_df():
    np.random.seed(42)
    n = 100
    close = pd.Series(np.cumsum(np.random.randn(n)) + 100)
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([close, open_], axis=1).max(axis=1) + abs(np.random.randn(n))
    low = pd.concat([close, open_], axis=1).min(axis=1) - abs(np.random.randn(n))
    volume = pd.Series(np.random.randint(1000, 10000, n))
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


class TestEMA:
    def test_length(self, sample_df):
        result = ema(sample_df["close"], 9)
        assert len(result) == len(sample_df)

    def test_smoothing(self, sample_df):
        fast = ema(sample_df["close"], 5)
        slow = ema(sample_df["close"], 20)
        # Fast EMA should be more volatile (higher std)
        assert fast.std() >= slow.std()


class TestSMA:
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = sma(s, 3)
        assert result.iloc[-1] == pytest.approx(4.0)
        assert pd.isna(result.iloc[0])


class TestRSI:
    def test_range(self, sample_df):
        result = rsi(sample_df["close"], 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_overbought_oversold(self):
        # Monotonically rising should give RSI near 100
        rising = pd.Series(range(50))
        result = rsi(rising, 14)
        assert result.iloc[-1] > 80


class TestVWAP:
    def test_basic(self, sample_df):
        result = vwap(sample_df["high"], sample_df["low"], sample_df["close"], sample_df["volume"])
        assert len(result) == len(sample_df)
        assert not pd.isna(result.iloc[-1])


class TestVolumeSpike:
    def test_spike_detection(self):
        vol = pd.Series([100] * 25 + [500])
        spike = is_volume_spike(vol, period=20, multiplier=1.5)
        assert spike.iloc[-1] == True
        assert spike.iloc[20] == False


class TestEMACrossover:
    def test_crossover(self):
        fast = pd.Series([1, 2, 3, 4, 5])
        slow = pd.Series([3, 3, 3, 3, 3])
        result = ema_crossover(fast, slow)
        # Should have a bullish crossover where fast crosses above slow
        assert 1 in result.values


class TestCandleType:
    def test_green(self):
        o = pd.Series([100, 105])
        c = pd.Series([105, 110])
        assert is_green_candle(o, c).all()

    def test_red(self):
        o = pd.Series([110, 105])
        c = pd.Series([105, 100])
        assert is_red_candle(o, c).all()


class TestPivotLevels:
    def test_structure(self):
        levels = pivot_levels(high=100, low=90, close=95)
        assert "pivot" in levels
        assert "r1" in levels
        assert "s1" in levels
        assert levels["r1"] > levels["pivot"] > levels["s1"]

    def test_symmetry(self):
        levels = pivot_levels(high=100, low=90, close=95)
        assert levels["r1"] > levels["pivot"]
        assert levels["s1"] < levels["pivot"]


class TestRoundNumberLevels:
    def test_basic(self):
        levels = round_number_levels(22350, step=100)
        assert 22300 in levels
        assert 22400 in levels
        assert len(levels) == 7
