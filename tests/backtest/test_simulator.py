"""Tests for PremiumSimulator."""

import math

import pytest

from nifty_trader.backtest.simulator import PremiumSimulator


class TestEstimateBasePremium:
    def test_typical_values(self):
        sim = PremiumSimulator()
        premium = sim.estimate_base_premium(spot=24000, vix=15, dte=5)
        # spot * (15/100) * sqrt(5/365) * 0.4
        expected = 24000 * 0.15 * math.sqrt(5 / 365) * 0.4
        assert abs(premium - expected) < 0.01

    def test_higher_vix_gives_higher_premium(self):
        sim = PremiumSimulator()
        low_vix = sim.estimate_base_premium(spot=24000, vix=12, dte=5)
        high_vix = sim.estimate_base_premium(spot=24000, vix=25, dte=5)
        assert high_vix > low_vix

    def test_zero_spot_returns_min(self):
        sim = PremiumSimulator(min_premium=5.0)
        assert sim.estimate_base_premium(spot=0, vix=15, dte=5) == 5.0

    def test_zero_vix_returns_min(self):
        sim = PremiumSimulator(min_premium=5.0)
        assert sim.estimate_base_premium(spot=24000, vix=0, dte=5) == 5.0

    def test_zero_dte_returns_min(self):
        sim = PremiumSimulator(min_premium=5.0)
        assert sim.estimate_base_premium(spot=24000, vix=15, dte=0) == 5.0


class TestSimulateOptionOhlc:
    def test_index_oh_produces_bearish_pattern(self):
        """Index O=H → CE should drop (O=H), PE should rise (O=L)."""
        sim = PremiumSimulator()
        result = sim.simulate_option_ohlc_from_index(
            index_open=24500,
            index_high=24500,  # O=H
            index_low=24350,
            index_close=24380,
        )
        # CE high should be near open (capped)
        assert result["ce_high"] <= result["ce_open"] + 1.0
        # PE high should be above open (rising)
        assert result["pe_high"] > result["pe_open"]

    def test_index_ol_produces_bullish_pattern(self):
        """Index O=L → CE should rise (O=L), PE should drop (O=H)."""
        sim = PremiumSimulator()
        result = sim.simulate_option_ohlc_from_index(
            index_open=24500,
            index_high=24650,
            index_low=24500,  # O=L
            index_close=24620,
        )
        # CE should go up
        assert result["ce_high"] > result["ce_open"]
        # PE high should be near open (capped)
        assert result["pe_high"] <= result["pe_open"] + 1.0


class TestPremiumAtIndexPrice:
    def test_bullish_direction(self):
        sim = PremiumSimulator(atm_delta=0.5)
        premium = sim.premium_at_index_price(
            index_price=24600,
            base_spot=24500,
            base_premium=150,
            direction="BULLISH",
        )
        # 100 point rise * 0.5 delta = 50 premium increase
        assert abs(premium - 200) < 0.01

    def test_bearish_direction(self):
        sim = PremiumSimulator(atm_delta=0.5)
        premium = sim.premium_at_index_price(
            index_price=24400,
            base_spot=24500,
            base_premium=150,
            direction="BEARISH",
        )
        # 100 point drop * 0.5 delta = 50 premium increase for PE
        assert abs(premium - 200) < 0.01

    def test_premium_floor(self):
        sim = PremiumSimulator(atm_delta=0.5, min_premium=5.0)
        premium = sim.premium_at_index_price(
            index_price=25000,
            base_spot=24500,
            base_premium=50,
            direction="BEARISH",
        )
        # 500 point rise hurts PE by 250 → 50 - 250 = -200, floored to 5
        assert premium == 5.0


class TestSimulatePremiumPath:
    def test_returns_one_per_candle(self):
        sim = PremiumSimulator()
        candles = [
            {"open": 24500, "high": 24520, "low": 24490, "close": 24510, "timestamp": "09:15"},
            {"open": 24510, "high": 24540, "low": 24500, "close": 24530, "timestamp": "09:20"},
            {"open": 24530, "high": 24560, "low": 24520, "close": 24550, "timestamp": "09:25"},
        ]
        path = sim.simulate_premium_path(candles, "BULLISH", vix=15)
        assert len(path) == 3

    def test_bullish_path_tracks_upward(self):
        sim = PremiumSimulator()
        candles = [
            {"open": 24500, "high": 24520, "low": 24490, "close": 24510, "timestamp": "1"},
            {"open": 24510, "high": 24550, "low": 24505, "close": 24540, "timestamp": "2"},
            {"open": 24540, "high": 24580, "low": 24530, "close": 24570, "timestamp": "3"},
        ]
        path = sim.simulate_premium_path(candles, "BULLISH", vix=15)
        # CE premium should increase as index goes up
        assert path[2].ce_premium > path[0].ce_premium

    def test_empty_candles(self):
        sim = PremiumSimulator()
        assert sim.simulate_premium_path([], "BULLISH", vix=15) == []
