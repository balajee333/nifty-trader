"""Goal tracker — 1L → 2L progress with projections and pace analysis."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GoalProgress:
    starting_capital: float
    current_capital: float
    target_capital: float
    cumulative_pnl: float
    progress_pct: float  # % of goal completed
    remaining: float
    days_elapsed: int
    actual_daily_pace: float
    required_daily_pace: float
    estimated_days_remaining: int
    on_track: int  # 1=ahead, 0=on track, -1=behind
    max_drawdown: float
    peak_capital: float


@dataclass
class Streak:
    type: str  # "W" or "L"
    count: int
    pnl_during: float


@dataclass
class WeekSummary:
    week_start: str
    week_end: str
    total_pnl: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    best_day_pnl: float
    worst_day_pnl: float


@dataclass
class MonthlySummary:
    month: str
    total_pnl: float
    trading_days: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_daily_pnl: float
    max_drawdown: float


class GoalTracker:
    """Track the 1L → 2L journey with projections and pace analysis."""

    def __init__(
        self,
        db_path: str | Path = "venom_journal.db",
        start_capital: float = 100_000,
        target: float = 200_000,
        target_days: int = 252,
    ):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._start_capital = start_capital
        self._target = target
        self._target_days = target_days
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS goal_tracking (
                date TEXT PRIMARY KEY,
                starting_capital REAL,
                current_capital REAL,
                daily_pnl REAL,
                cumulative_pnl REAL,
                trades_today INTEGER,
                wins_today INTEGER,
                losses_today INTEGER,
                win_rate_cumulative REAL,
                avg_winner REAL,
                avg_loser REAL,
                expectancy REAL,
                max_drawdown REAL,
                days_elapsed INTEGER,
                days_remaining INTEGER,
                required_daily_pace REAL,
                actual_daily_pace REAL,
                on_track INTEGER
            )
        """)
        self._conn.commit()

    def update(
        self,
        daily_pnl: float,
        trades: int,
        wins: int,
        losses: int,
        date: str | None = None,
    ):
        """Record a day's results and update goal tracking."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # Get previous cumulative data
        prev = self._conn.execute(
            "SELECT * FROM goal_tracking ORDER BY date DESC LIMIT 1"
        ).fetchone()

        if prev:
            cumulative_pnl = prev["cumulative_pnl"] + daily_pnl
            days_elapsed = prev["days_elapsed"] + 1
            prev_max_dd = prev["max_drawdown"]
        else:
            cumulative_pnl = daily_pnl
            days_elapsed = 1
            prev_max_dd = 0.0

        current_capital = self._start_capital + cumulative_pnl
        remaining = self._target - current_capital
        days_remaining = max(self._target_days - days_elapsed, 1)
        required_pace = remaining / days_remaining if days_remaining > 0 else 0
        actual_pace = cumulative_pnl / days_elapsed if days_elapsed > 0 else 0

        # Cumulative win rate
        all_rows = self._conn.execute(
            "SELECT wins_today, losses_today FROM goal_tracking"
        ).fetchall()
        total_wins = wins + sum(r["wins_today"] for r in all_rows)
        total_losses = losses + sum(r["losses_today"] for r in all_rows)
        total_trades = total_wins + total_losses
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

        # Avg winner / loser from trades table
        avg_winner, avg_loser = self._compute_avg_wl()

        # Expectancy
        if total_trades > 0:
            wr = total_wins / total_trades
            lr = 1 - wr
            expectancy = (wr * avg_winner) - (lr * abs(avg_loser))
        else:
            expectancy = 0

        # Max drawdown tracking
        peak = self._start_capital + max(cumulative_pnl, 0)
        dd = current_capital - peak
        max_drawdown = min(dd, prev_max_dd)

        # On track
        if actual_pace > required_pace * 1.1:
            on_track = 1
        elif actual_pace < required_pace * 0.8:
            on_track = -1
        else:
            on_track = 0

        self._conn.execute(
            """INSERT OR REPLACE INTO goal_tracking
            (date, starting_capital, current_capital, daily_pnl, cumulative_pnl,
             trades_today, wins_today, losses_today, win_rate_cumulative,
             avg_winner, avg_loser, expectancy, max_drawdown,
             days_elapsed, days_remaining, required_daily_pace,
             actual_daily_pace, on_track)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                date, self._start_capital, current_capital, daily_pnl,
                cumulative_pnl, trades, wins, losses, win_rate,
                avg_winner, avg_loser, expectancy, max_drawdown,
                days_elapsed, days_remaining, required_pace, actual_pace,
                on_track,
            ),
        )
        self._conn.commit()

    def _compute_avg_wl(self) -> tuple[float, float]:
        """Compute average winner and loser from trades table."""
        try:
            winners = self._conn.execute(
                "SELECT AVG(pnl) as avg_w FROM trades WHERE pnl > 0"
            ).fetchone()
            losers = self._conn.execute(
                "SELECT AVG(pnl) as avg_l FROM trades WHERE pnl < 0"
            ).fetchone()
            avg_w = winners["avg_w"] if winners and winners["avg_w"] else 0
            avg_l = losers["avg_l"] if losers and losers["avg_l"] else 0
            return avg_w, avg_l
        except sqlite3.OperationalError:
            return 0.0, 0.0

    def get_progress(self) -> GoalProgress:
        """Get current goal progress."""
        row = self._conn.execute(
            "SELECT * FROM goal_tracking ORDER BY date DESC LIMIT 1"
        ).fetchone()

        if not row:
            needed = self._target - self._start_capital
            return GoalProgress(
                starting_capital=self._start_capital,
                current_capital=self._start_capital,
                target_capital=self._target,
                cumulative_pnl=0,
                progress_pct=0,
                remaining=needed,
                days_elapsed=0,
                actual_daily_pace=0,
                required_daily_pace=needed / self._target_days,
                estimated_days_remaining=self._target_days,
                on_track=0,
                max_drawdown=0,
                peak_capital=self._start_capital,
            )

        needed = self._target - self._start_capital
        progress_pct = (row["cumulative_pnl"] / needed * 100) if needed > 0 else 0
        remaining = self._target - row["current_capital"]
        pace = row["actual_daily_pace"]
        est_days = int(remaining / pace) if pace > 0 else self._target_days

        # Peak capital
        peak_row = self._conn.execute(
            "SELECT MAX(current_capital) as peak FROM goal_tracking"
        ).fetchone()
        peak_capital = peak_row["peak"] if peak_row and peak_row["peak"] else self._start_capital

        return GoalProgress(
            starting_capital=self._start_capital,
            current_capital=row["current_capital"],
            target_capital=self._target,
            cumulative_pnl=row["cumulative_pnl"],
            progress_pct=progress_pct,
            remaining=remaining,
            days_elapsed=row["days_elapsed"],
            actual_daily_pace=pace,
            required_daily_pace=row["required_daily_pace"],
            estimated_days_remaining=est_days,
            on_track=row["on_track"],
            max_drawdown=row["max_drawdown"],
            peak_capital=peak_capital,
        )

    def get_streak(self) -> Streak:
        """Get current win/loss streak."""
        rows = self._conn.execute(
            "SELECT daily_pnl FROM goal_tracking ORDER BY date DESC"
        ).fetchall()

        if not rows:
            return Streak(type="W", count=0, pnl_during=0)

        streak_type = "W" if rows[0]["daily_pnl"] >= 0 else "L"
        count = 0
        pnl = 0.0

        for row in rows:
            is_win = row["daily_pnl"] >= 0
            if (is_win and streak_type == "W") or (not is_win and streak_type == "L"):
                count += 1
                pnl += row["daily_pnl"]
            else:
                break

        return Streak(type=streak_type, count=count, pnl_during=pnl)

    def get_weekly_summary(self) -> WeekSummary | None:
        """Get current week's summary."""
        rows = self._conn.execute("""
            SELECT * FROM goal_tracking
            WHERE date >= date('now', 'weekday 0', '-7 days')
            ORDER BY date
        """).fetchall()

        if not rows:
            return None

        pnls = [r["daily_pnl"] for r in rows]
        total_wins = sum(r["wins_today"] for r in rows)
        total_losses = sum(r["losses_today"] for r in rows)
        total_trades = total_wins + total_losses

        return WeekSummary(
            week_start=rows[0]["date"],
            week_end=rows[-1]["date"],
            total_pnl=sum(pnls),
            trades=total_trades,
            wins=total_wins,
            losses=total_losses,
            win_rate=(total_wins / total_trades * 100) if total_trades > 0 else 0,
            best_day_pnl=max(pnls),
            worst_day_pnl=min(pnls),
        )

    def get_monthly_summary(self) -> MonthlySummary | None:
        """Get current month's summary."""
        month_str = datetime.now().strftime("%Y-%m")
        rows = self._conn.execute(
            "SELECT * FROM goal_tracking WHERE date LIKE ? ORDER BY date",
            (f"{month_str}%",),
        ).fetchall()

        if not rows:
            return None

        pnls = [r["daily_pnl"] for r in rows]
        total_wins = sum(r["wins_today"] for r in rows)
        total_losses = sum(r["losses_today"] for r in rows)
        total_trades = total_wins + total_losses

        # Max drawdown within the month
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cum += p
            peak = max(peak, cum)
            max_dd = min(max_dd, cum - peak)

        return MonthlySummary(
            month=month_str,
            total_pnl=sum(pnls),
            trading_days=len(rows),
            trades=total_trades,
            wins=total_wins,
            losses=total_losses,
            win_rate=(total_wins / total_trades * 100) if total_trades > 0 else 0,
            avg_daily_pnl=sum(pnls) / len(pnls) if pnls else 0,
            max_drawdown=max_dd,
        )

    def close(self):
        self._conn.close()
