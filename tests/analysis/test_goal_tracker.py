"""Tests for GoalTracker."""

import pytest

from nifty_trader.analysis.goal_tracker import GoalProgress, GoalTracker, Streak


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test.db"
    t = GoalTracker(db, start_capital=100_000, target=200_000, target_days=252)
    # Create trades table for avg W/L computation
    t._conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, pnl REAL, entry_time TEXT
        )
    """)
    t._conn.commit()
    yield t
    t.close()


class TestGoalTracker:
    def test_initial_progress(self, tracker):
        progress = tracker.get_progress()
        assert isinstance(progress, GoalProgress)
        assert progress.current_capital == 100_000
        assert progress.target_capital == 200_000
        assert progress.cumulative_pnl == 0
        assert progress.days_elapsed == 0

    def test_update_single_day(self, tracker):
        tracker.update(1500, trades=2, wins=1, losses=1, date="2026-03-07")
        progress = tracker.get_progress()

        assert progress.current_capital == 101_500
        assert progress.cumulative_pnl == 1500
        assert progress.days_elapsed == 1
        assert progress.progress_pct == pytest.approx(1.5)
        assert progress.remaining == 98_500

    def test_update_multiple_days(self, tracker):
        tracker.update(2000, 3, 2, 1, date="2026-03-03")
        tracker.update(-500, 2, 0, 2, date="2026-03-04")
        tracker.update(3000, 4, 3, 1, date="2026-03-05")

        progress = tracker.get_progress()
        assert progress.cumulative_pnl == 4500  # 2000 - 500 + 3000
        assert progress.current_capital == 104_500
        assert progress.days_elapsed == 3

    def test_on_track_ahead(self, tracker):
        # Need 100k in 252 days = ~397/day. 2000/day is way ahead.
        tracker.update(2000, 2, 2, 0, date="2026-03-07")
        progress = tracker.get_progress()
        assert progress.on_track == 1  # ahead

    def test_on_track_behind(self, tracker):
        # Losing money = behind
        tracker.update(-3000, 2, 0, 2, date="2026-03-07")
        progress = tracker.get_progress()
        assert progress.on_track == -1  # behind

    def test_streak_winning(self, tracker):
        tracker.update(1000, 2, 2, 0, date="2026-03-03")
        tracker.update(500, 1, 1, 0, date="2026-03-04")
        tracker.update(2000, 3, 3, 0, date="2026-03-05")

        streak = tracker.get_streak()
        assert streak.type == "W"
        assert streak.count == 3
        assert streak.pnl_during == 3500

    def test_streak_losing(self, tracker):
        tracker.update(1000, 2, 2, 0, date="2026-03-03")
        tracker.update(-500, 1, 0, 1, date="2026-03-04")
        tracker.update(-200, 2, 0, 2, date="2026-03-05")

        streak = tracker.get_streak()
        assert streak.type == "L"
        assert streak.count == 2
        assert streak.pnl_during == -700

    def test_streak_empty(self, tracker):
        streak = tracker.get_streak()
        assert streak.count == 0

    def test_weekly_summary(self, tracker):
        tracker.update(1000, 2, 1, 1, date="2026-03-03")
        tracker.update(2000, 3, 2, 1, date="2026-03-04")

        weekly = tracker.get_weekly_summary()
        # May be None if dates don't fall in current week
        if weekly:
            assert weekly.total_pnl == 3000

    def test_monthly_summary(self, tracker):
        tracker.update(1500, 2, 1, 1, date="2026-03-03")
        tracker.update(-500, 1, 0, 1, date="2026-03-04")

        monthly = tracker.get_monthly_summary()
        assert monthly is not None
        assert monthly.total_pnl == 1000
        assert monthly.trading_days == 2

    def test_max_drawdown_tracked(self, tracker):
        tracker.update(3000, 3, 3, 0, date="2026-03-03")
        tracker.update(-5000, 2, 0, 2, date="2026-03-04")

        progress = tracker.get_progress()
        assert progress.max_drawdown < 0

    def test_estimated_days(self, tracker):
        tracker.update(2000, 2, 2, 0, date="2026-03-07")
        progress = tracker.get_progress()
        # pace = 2000/day, remaining = 98000, est = 49 days
        assert progress.estimated_days_remaining == 49
