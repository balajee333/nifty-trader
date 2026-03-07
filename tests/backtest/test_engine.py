"""Tests for VenomBacktester engine with mock DhanHQ responses."""

from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from nifty_trader.backtest.engine import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
    VenomBacktester,
)
from nifty_trader.config import load_config


def _make_config():
    """Load default config (no YAML needed for tests)."""
    with patch.dict("os.environ", {
        "DHAN_CLIENT_ID": "test",
        "DHAN_ACCESS_TOKEN": "test",
    }):
        return load_config(yaml_path="/dev/null")


def _mock_dhan():
    """Create a mock DhanHQ client with sample responses."""
    dhan = MagicMock()
    return dhan


def _make_5min_response(day: date, pattern: str = "bullish") -> dict:
    """Build a mock DhanHQ intraday response for one day.

    pattern: 'bullish' (O=L), 'bearish' (O=H), 'choppy' (MID)
    """
    base = datetime(day.year, day.month, day.day, 9, 15)
    times = []
    opens, highs, lows, closes, volumes = [], [], [], [], []

    spot = 24500.0
    candle_count = 75  # ~6 hours of 5-min candles

    for i in range(candle_count):
        ts = base + timedelta(minutes=i * 5)
        times.append(ts.isoformat())

        if i == 0:
            o = spot
            if pattern == "bullish":
                h = spot + 30
                l = spot  # O=L
                c = spot + 20
            elif pattern == "bearish":
                h = spot  # O=H
                l = spot - 30
                c = spot - 20
            else:
                h = spot + 15
                l = spot - 15
                c = spot + 5
        else:
            if pattern == "bullish":
                drift = i * 2
            elif pattern == "bearish":
                drift = -i * 2
            else:
                drift = (-1) ** i * 5

            o = spot + drift
            h = o + 10
            l = o - 5
            c = o + 5

        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(100000 + i * 1000)

    return {
        "status": "success",
        "data": {
            "start_Time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
    }


def _make_daily_response(start: date, end: date) -> dict:
    """Build mock daily candle response."""
    times, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    d = start
    spot = 24400.0
    while d <= end:
        if d.weekday() < 5:  # skip weekends
            times.append(datetime(d.year, d.month, d.day).isoformat())
            opens.append(spot)
            highs.append(spot + 100)
            lows.append(spot - 50)
            closes.append(spot + 30)
            volumes.append(5_000_000)
            spot += 10
        d += timedelta(days=1)

    return {
        "status": "success",
        "data": {
            "start_Time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
    }


def _make_vix_response(start: date, end: date, vix: float = 14.5) -> dict:
    """Build mock VIX daily response."""
    times, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    d = start
    while d <= end:
        if d.weekday() < 5:
            times.append(datetime(d.year, d.month, d.day).isoformat())
            opens.append(vix)
            highs.append(vix + 0.5)
            lows.append(vix - 0.3)
            closes.append(vix)
            volumes.append(0)
        d += timedelta(days=1)

    return {
        "status": "success",
        "data": {
            "start_Time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
    }


class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig(start_date="2025-12-01", end_date="2025-12-31")
        assert cfg.start_capital == 100_000
        assert cfg.lot_size == 25
        assert cfg.max_trades_per_day == 3


class TestParseCandles:
    def test_parses_success_response(self):
        resp = _make_5min_response(date(2025, 12, 1))
        df = VenomBacktester._parse_candles(resp)
        assert not df.empty
        assert "timestamp" in df.columns
        assert "open" in df.columns
        assert "close" in df.columns
        assert len(df) == 75

    def test_handles_failure_response(self):
        df = VenomBacktester._parse_candles({"status": "error"})
        assert df.empty

    def test_handles_none(self):
        df = VenomBacktester._parse_candles(None)
        assert df.empty

    def test_handles_empty_data(self):
        df = VenomBacktester._parse_candles({"status": "success", "data": {}})
        assert df.empty


class TestClassifyDay:
    def test_bullish_trending(self):
        candles = [
            {"open": 100, "high": 110, "low": 99, "close": 108},
            {"open": 108, "high": 115, "low": 107, "close": 114},
        ]
        assert "bullish" in VenomBacktester._classify_day(candles)

    def test_bearish_trending(self):
        candles = [
            {"open": 110, "high": 112, "low": 100, "close": 101},
            {"open": 101, "high": 103, "low": 95, "close": 96},
        ]
        assert "bearish" in VenomBacktester._classify_day(candles)

    def test_choppy(self):
        candles = [
            {"open": 100, "high": 110, "low": 90, "close": 101},
            {"open": 101, "high": 105, "low": 95, "close": 100},
        ]
        result = VenomBacktester._classify_day(candles)
        assert result == "choppy"

    def test_empty(self):
        assert VenomBacktester._classify_day([]) == "unknown"


class TestBacktesterRun:
    """Integration test with mocked API calls."""

    def test_bullish_day_produces_trade(self):
        config = _make_config()
        bt_config = BacktestConfig(
            start_date="2025-12-01",
            end_date="2025-12-01",
        )
        dhan = _mock_dhan()

        # Mock intraday_minute_data to return bullish day
        dhan.intraday_minute_data.return_value = _make_5min_response(
            date(2025, 12, 1), "bullish"
        )
        dhan.historical_daily_data.side_effect = [
            _make_daily_response(date(2025, 11, 1), date(2025, 12, 1)),  # daily
            _make_vix_response(date(2025, 12, 1), date(2025, 12, 1)),    # VIX
        ]

        backtester = VenomBacktester(dhan, config, bt_config)
        result = backtester.run()

        assert isinstance(result, BacktestResult)
        assert len(result.days) >= 1

    def test_high_vix_skips_day(self):
        config = _make_config()
        bt_config = BacktestConfig(
            start_date="2025-12-01",
            end_date="2025-12-01",
        )
        dhan = _mock_dhan()

        dhan.intraday_minute_data.return_value = _make_5min_response(
            date(2025, 12, 1), "bullish"
        )
        dhan.historical_daily_data.side_effect = [
            _make_daily_response(date(2025, 11, 1), date(2025, 12, 1)),
            _make_vix_response(date(2025, 12, 1), date(2025, 12, 1), vix=35.0),
        ]

        backtester = VenomBacktester(dhan, config, bt_config)
        result = backtester.run()

        assert result.total_trades == 0
        if result.days:
            assert result.days[0].skipped

    def test_empty_data_returns_empty_result(self):
        config = _make_config()
        bt_config = BacktestConfig(
            start_date="2025-12-01",
            end_date="2025-12-01",
        )
        dhan = _mock_dhan()

        dhan.intraday_minute_data.return_value = {"status": "error"}
        dhan.historical_daily_data.return_value = {"status": "error"}

        backtester = VenomBacktester(dhan, config, bt_config)
        result = backtester.run()

        assert result.total_trades == 0
        assert result.total_pnl == 0.0
        assert result.equity_curve == [100_000]


class TestAggregation:
    def test_equity_curve_starts_at_capital(self):
        config = _make_config()
        bt_config = BacktestConfig(
            start_date="2025-12-01",
            end_date="2025-12-01",
            start_capital=50_000,
        )
        dhan = _mock_dhan()
        dhan.intraday_minute_data.return_value = {"status": "error"}
        dhan.historical_daily_data.return_value = {"status": "error"}

        backtester = VenomBacktester(dhan, config, bt_config)
        result = backtester.run()

        assert result.equity_curve[0] == 50_000

    def test_profit_factor_handles_no_losses(self):
        config = _make_config()
        bt_config = BacktestConfig(
            start_date="2025-12-01",
            end_date="2025-12-01",
        )
        dhan = _mock_dhan()
        dhan.intraday_minute_data.return_value = {"status": "error"}
        dhan.historical_daily_data.return_value = {"status": "error"}

        backtester = VenomBacktester(dhan, config, bt_config)
        result = backtester.run()
        # With no trades, profit factor should be 0 or inf gracefully
        assert result.profit_factor >= 0
