"""Tests for MonthlyManager risk controls."""

import pytest
from nifty_trader.risk.monthly import MonthlyManager, MonthlyMode


@pytest.fixture
def mgr():
    return MonthlyManager()


class TestDailyLimit:
    def test_can_trade_within_limit(self, mgr):
        assert mgr.can_trade_today(-2000) is True

    def test_cannot_trade_at_limit(self, mgr):
        assert mgr.can_trade_today(-3000) is False

    def test_cannot_trade_beyond_limit(self, mgr):
        assert mgr.can_trade_today(-5000) is False

    def test_can_trade_positive(self, mgr):
        assert mgr.can_trade_today(1000) is True


class TestWeeklyLimit:
    def test_can_trade_within_weekly(self, mgr):
        assert mgr.can_trade_this_week(-5000) is True

    def test_cannot_trade_at_weekly_limit(self, mgr):
        assert mgr.can_trade_this_week(-8000) is False

    def test_cannot_trade_beyond_weekly_limit(self, mgr):
        assert mgr.can_trade_this_week(-10000) is False


class TestConsecutiveLosses:
    def test_can_trade_below_limit(self, mgr):
        assert mgr.can_trade_after_streak(2) is True

    def test_cannot_trade_at_limit(self, mgr):
        assert mgr.can_trade_after_streak(3) is False

    def test_compute_consecutive_losses(self, mgr):
        assert mgr.compute_consecutive_losses([100, -50, -30, -20]) == 3

    def test_compute_no_losses(self, mgr):
        assert mgr.compute_consecutive_losses([100, 50, 30]) == 0

    def test_compute_empty(self, mgr):
        assert mgr.compute_consecutive_losses([]) == 0

    def test_compute_broken_streak(self, mgr):
        assert mgr.compute_consecutive_losses([-50, 100, -30]) == 1


class TestMTDProtection:
    def test_protection_mode_when_profitable(self, mgr):
        mode = mgr.get_monthly_mode(mtd_pnl=15000, day_of_month=10)
        assert mode.only_a_plus is True
        assert mode.size_reduction == pytest.approx(0.30)
        assert mode.stopped is False

    def test_no_protection_after_15th(self, mgr):
        mode = mgr.get_monthly_mode(mtd_pnl=15000, day_of_month=20)
        assert mode.only_a_plus is False
        assert mode.size_reduction == 0.0


class TestMTDStop:
    def test_stop_when_losing_early_month(self, mgr):
        mode = mgr.get_monthly_mode(mtd_pnl=-5000, day_of_month=10)
        assert mode.stopped is True
        assert mode.stop_days == 3
        assert mode.resume_size_reduction == pytest.approx(0.50)

    def test_no_stop_after_15th(self, mgr):
        mode = mgr.get_monthly_mode(mtd_pnl=-5000, day_of_month=20)
        assert mode.stopped is False


class TestNormalMode:
    def test_normal_mode_neutral_pnl(self, mgr):
        mode = mgr.get_monthly_mode(mtd_pnl=3000, day_of_month=10)
        assert mode.stopped is False
        assert mode.only_a_plus is False
        assert mode.size_reduction == 0.0
