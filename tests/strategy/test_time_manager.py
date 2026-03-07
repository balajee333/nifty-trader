"""Tests for TimeManager — window classification and time-stop logic."""

from datetime import datetime, time

import pytest

from nifty_trader.strategy.time_manager import TimeManager, TradingWindow


@pytest.fixture
def tm():
    return TimeManager(time_stop_minutes=20)


# ── Window classification ────────────────────────────────────────────

class TestGetWindow:
    def test_pre_market(self, tm):
        assert tm.get_window(time(9, 0)) == TradingWindow.PRE_MARKET

    def test_pre_market_start(self, tm):
        assert tm.get_window(time(8, 45)) == TradingWindow.PRE_MARKET

    def test_signal_detection(self, tm):
        assert tm.get_window(time(9, 15)) == TradingWindow.SIGNAL_DETECTION
        assert tm.get_window(time(9, 20)) == TradingWindow.SIGNAL_DETECTION

    def test_prime_entry(self, tm):
        assert tm.get_window(time(9, 21)) == TradingWindow.PRIME_ENTRY
        assert tm.get_window(time(10, 0)) == TradingWindow.PRIME_ENTRY

    def test_morning_entry(self, tm):
        assert tm.get_window(time(10, 15)) == TradingWindow.MORNING_ENTRY
        assert tm.get_window(time(11, 0)) == TradingWindow.MORNING_ENTRY

    def test_no_trade(self, tm):
        assert tm.get_window(time(11, 30)) == TradingWindow.NO_TRADE
        assert tm.get_window(time(12, 30)) == TradingWindow.NO_TRADE

    def test_afternoon_entry(self, tm):
        assert tm.get_window(time(13, 30)) == TradingWindow.AFTERNOON_ENTRY
        assert tm.get_window(time(14, 0)) == TradingWindow.AFTERNOON_ENTRY

    def test_closing(self, tm):
        assert tm.get_window(time(14, 30)) == TradingWindow.CLOSING
        assert tm.get_window(time(15, 0)) == TradingWindow.CLOSING

    def test_market_close(self, tm):
        assert tm.get_window(time(15, 15)) == TradingWindow.MARKET_CLOSE
        assert tm.get_window(time(15, 29)) == TradingWindow.MARKET_CLOSE

    def test_after_hours(self, tm):
        assert tm.get_window(time(15, 30)) == TradingWindow.AFTER_HOURS
        assert tm.get_window(time(8, 0)) == TradingWindow.AFTER_HOURS
        assert tm.get_window(time(16, 0)) == TradingWindow.AFTER_HOURS

    def test_boundary_signal_to_prime(self, tm):
        """09:21 is the first minute of PRIME_ENTRY, not SIGNAL_DETECTION."""
        assert tm.get_window(time(9, 20)) == TradingWindow.SIGNAL_DETECTION
        assert tm.get_window(time(9, 21)) == TradingWindow.PRIME_ENTRY


# ── Entry permission ─────────────────────────────────────────────────

class TestCanEnter:
    def test_entry_windows_allowed(self, tm):
        for t in [time(9, 16), time(9, 30), time(10, 30), time(13, 45)]:
            assert tm.can_enter(t) is True, f"should allow entry at {t}"

    def test_non_entry_windows_blocked(self, tm):
        for t in [time(9, 0), time(12, 0), time(14, 45), time(15, 20)]:
            assert tm.can_enter(t) is False, f"should block entry at {t}"


# ── Force exit ────────────────────────────────────────────────────────

class TestForceExit:
    def test_before_close(self, tm):
        assert tm.should_force_exit(time(15, 14)) is False

    def test_at_close(self, tm):
        assert tm.should_force_exit(time(15, 15)) is True

    def test_after_close(self, tm):
        assert tm.should_force_exit(time(15, 30)) is True


# ── Time stop ─────────────────────────────────────────────────────────

class TestTimeStop:
    def _dt(self, h, m):
        return datetime(2024, 1, 15, h, m)

    def test_flat_position_stopped(self, tm):
        """Position flat for 25 min with 2 % P&L → time stop."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 55), 2.0) is True

    def test_profitable_position_exempt(self, tm):
        """Position showing > 15 % P&L → never time-stopped."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 55), 16.0) is False

    def test_not_enough_time(self, tm):
        """Position held for only 10 min → too early to stop."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 40), 1.0) is False

    def test_moderate_pnl_not_stopped(self, tm):
        """Position with |P&L| >= 5 % is not flat → no time stop."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 55), 6.0) is False
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 55), -6.0) is False

    def test_exact_boundary(self, tm):
        """Exactly 20 min and exactly 4.9 % P&L → triggers."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 50), 4.9) is True

    def test_negative_flat_pnl(self, tm):
        """Small negative P&L within flat range → stops."""
        assert tm.time_stop_hit(self._dt(9, 30), self._dt(9, 55), -3.0) is True
