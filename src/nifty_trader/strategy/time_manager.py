"""Trading-window classifier and time-stop logic for VENOM strategy."""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum


class TradingWindow(Enum):
    PRE_MARKET = "pre_market"
    SIGNAL_DETECTION = "signal_detection"
    PRIME_ENTRY = "prime_entry"
    MORNING_ENTRY = "morning_entry"
    NO_TRADE = "no_trade"
    AFTERNOON_ENTRY = "afternoon_entry"
    CLOSING = "closing"
    MARKET_CLOSE = "market_close"
    AFTER_HOURS = "after_hours"


class TimeManager:
    """Classifies the current time into a trading window and enforces
    time-based entry/exit rules."""

    def __init__(self, time_stop_minutes: int = 20):
        self.time_stop_minutes = time_stop_minutes
        self._windows = [
            (time(8, 45), time(9, 15), TradingWindow.PRE_MARKET),
            (time(9, 15), time(9, 21), TradingWindow.SIGNAL_DETECTION),
            (time(9, 21), time(10, 15), TradingWindow.PRIME_ENTRY),
            (time(10, 15), time(11, 30), TradingWindow.MORNING_ENTRY),
            (time(11, 30), time(13, 30), TradingWindow.NO_TRADE),
            (time(13, 30), time(14, 30), TradingWindow.AFTERNOON_ENTRY),
            (time(14, 30), time(15, 15), TradingWindow.CLOSING),
            (time(15, 15), time(15, 30), TradingWindow.MARKET_CLOSE),
        ]
        self._entry_windows = {
            TradingWindow.SIGNAL_DETECTION,
            TradingWindow.PRIME_ENTRY,
            TradingWindow.MORNING_ENTRY,
            TradingWindow.AFTERNOON_ENTRY,
        }

    def get_window(self, t: time) -> TradingWindow:
        """Return the trading window for the given time of day."""
        for start, end, window in self._windows:
            if start <= t < end:
                return window
        return TradingWindow.AFTER_HOURS

    def can_enter(self, t: time) -> bool:
        """True when new positions may be opened."""
        return self.get_window(t) in self._entry_windows

    def should_force_exit(self, t: time) -> bool:
        """True when all positions must be closed (market close)."""
        return t >= time(15, 15)

    def time_stop_hit(
        self,
        entry_time: datetime,
        now: datetime,
        pnl_pct: float,
    ) -> bool:
        """Return True when a flat position should be stopped out on time.

        A position is time-stopped if it has been held for longer than
        ``time_stop_minutes`` and the P&L is still near flat (< 5 %).
        Positions already showing decent profit (> 15 %) are exempt.
        """
        if pnl_pct > 15.0:
            return False
        elapsed = (now - entry_time).total_seconds() / 60
        return elapsed >= self.time_stop_minutes and abs(pnl_pct) < 5.0
