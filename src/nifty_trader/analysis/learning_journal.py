"""Learning journal — auto-generated trading insights that accumulate over time."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Insight:
    id: int
    date: str
    category: str
    insight: str
    confidence: str  # 'confirmed', 'observed', 'hypothesis'
    occurrences: int
    last_seen: str
    pnl_impact: float


class LearningJournal:
    """Auto-generate and persist trading insights that accumulate over time."""

    CATEGORIES = ("signal", "entry", "exit", "risk", "market", "system")

    def __init__(self, db_path: str | Path = "venom_journal.db"):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                category TEXT,
                insight TEXT,
                confidence TEXT DEFAULT 'observed',
                occurrences INTEGER DEFAULT 1,
                last_seen TEXT,
                pnl_impact REAL DEFAULT 0.0
            )
        """)
        self._conn.commit()

    def add_insight(
        self,
        category: str,
        insight: str,
        pnl_impact: float = 0.0,
        date: str | None = None,
    ):
        """Add or update an insight. If similar insight exists, increment occurrences."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # Check for similar existing insight
        existing = self._conn.execute(
            "SELECT id, occurrences, pnl_impact FROM learnings WHERE insight = ?",
            (insight,),
        ).fetchone()

        if existing:
            new_occ = existing["occurrences"] + 1
            confidence = "confirmed" if new_occ >= 3 else "observed"
            total_impact = existing["pnl_impact"] + pnl_impact
            self._conn.execute(
                """UPDATE learnings SET occurrences = ?, confidence = ?,
                   last_seen = ?, pnl_impact = ? WHERE id = ?""",
                (new_occ, confidence, date, total_impact, existing["id"]),
            )
        else:
            self._conn.execute(
                """INSERT INTO learnings (date, category, insight, confidence,
                   occurrences, last_seen, pnl_impact)
                VALUES (?, ?, ?, 'observed', 1, ?, ?)""",
                (date, category, insight, date, pnl_impact),
            )

        self._conn.commit()

    def analyze_trades(self, trades: list[dict], date: str | None = None):
        """Auto-generate insights from a batch of trades."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        if not trades:
            return

        self._analyze_day_of_week(trades, date)
        self._analyze_time_windows(trades, date)
        self._analyze_signal_types(trades, date)
        self._analyze_exit_patterns(trades, date)
        self._analyze_streaks(trades, date)

    def _analyze_day_of_week(self, trades: list[dict], date: str):
        """Check if specific days of week perform better/worse."""
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            day_name = dt.strftime("%A")
        except ValueError:
            return

        pnls = [t.get("pnl", 0) or 0 for t in trades]
        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)

        if total > 0:
            wr = wins / total * 100
            if wr >= 70:
                self.add_insight(
                    "market",
                    f"{day_name}s show strong win rate ({wr:.0f}%)",
                    total_pnl,
                    date,
                )
            elif wr <= 30 and total >= 2:
                self.add_insight(
                    "market",
                    f"{day_name}s show poor win rate ({wr:.0f}%) — consider reducing size",
                    total_pnl,
                    date,
                )

    def _analyze_time_windows(self, trades: list[dict], date: str):
        """Analyze performance by entry time window."""
        morning_pnl = 0.0
        afternoon_pnl = 0.0
        morning_count = 0
        afternoon_count = 0

        for t in trades:
            entry_time = t.get("entry_time", "")
            pnl = t.get("pnl", 0) or 0
            if not entry_time:
                continue

            if isinstance(entry_time, str):
                try:
                    dt = datetime.fromisoformat(entry_time)
                except ValueError:
                    continue
            else:
                dt = entry_time

            if dt.hour < 11:
                morning_pnl += pnl
                morning_count += 1
            else:
                afternoon_pnl += pnl
                afternoon_count += 1

        if morning_count > 0 and afternoon_count > 0:
            if morning_pnl > 0 and afternoon_pnl < 0:
                self.add_insight(
                    "entry",
                    "Morning entries profitable, afternoon entries losing — "
                    "consider restricting to morning-only",
                    afternoon_pnl,
                    date,
                )
            elif afternoon_pnl > 0 and morning_pnl < 0:
                self.add_insight(
                    "entry",
                    "Afternoon entries outperforming morning — "
                    "morning signals may be unreliable",
                    morning_pnl,
                    date,
                )

    def _analyze_signal_types(self, trades: list[dict], date: str):
        """Analyze O=H vs O=L performance."""
        oh_pnl = 0.0
        ol_pnl = 0.0
        oh_count = 0
        ol_count = 0

        for t in trades:
            signals = t.get("signals_summary", "") or ""
            pnl = t.get("pnl", 0) or 0

            if "O=H" in signals:
                oh_pnl += pnl
                oh_count += 1
            if "O=L" in signals:
                ol_pnl += pnl
                ol_count += 1

        if oh_count >= 1:
            avg = oh_pnl / oh_count
            if avg > 0:
                self.add_insight(
                    "signal",
                    f"O=H signals averaging +{avg:,.0f}/trade",
                    oh_pnl,
                    date,
                )
            elif avg < -500:
                self.add_insight(
                    "signal",
                    f"O=H signals underperforming ({avg:,.0f}/trade) — review criteria",
                    oh_pnl,
                    date,
                )

        if ol_count >= 1:
            avg = ol_pnl / ol_count
            if avg > 0:
                self.add_insight(
                    "signal",
                    f"O=L signals averaging +{avg:,.0f}/trade",
                    ol_pnl,
                    date,
                )
            elif avg < -500:
                self.add_insight(
                    "signal",
                    f"O=L signals underperforming ({avg:,.0f}/trade) — review criteria",
                    ol_pnl,
                    date,
                )

    def _analyze_exit_patterns(self, trades: list[dict], date: str):
        """Analyze exit reason performance."""
        time_stops = 0
        sl_hits = 0
        trail_exits = 0
        total = len(trades)

        for t in trades:
            reason = t.get("exit_reason", "") or ""
            if "TIME_STOP" in reason:
                time_stops += 1
            elif "SL_HIT" in reason:
                sl_hits += 1
            elif "TRAIL" in reason or "LOCK" in reason or "MAX_PROFIT" in reason:
                trail_exits += 1

        if total > 0:
            if time_stops / total > 0.3:
                self.add_insight(
                    "exit",
                    f"Time stops account for {time_stops / total * 100:.0f}% of exits — "
                    "consider reducing time_stop_minutes",
                    0,
                    date,
                )

            if sl_hits > 0 and sl_hits == total:
                self.add_insight(
                    "risk",
                    "All trades hit SL today — possible adverse market conditions",
                    sum(t.get("pnl", 0) or 0 for t in trades),
                    date,
                )

            if trail_exits > 0:
                trail_pnl = sum(
                    t.get("pnl", 0) or 0
                    for t in trades
                    if any(
                        x in (t.get("exit_reason", "") or "")
                        for x in ("TRAIL", "LOCK", "MAX_PROFIT")
                    )
                )
                self.add_insight(
                    "exit",
                    f"Trail engine captured {trail_pnl:+,.0f} from {trail_exits} trade(s)",
                    trail_pnl,
                    date,
                )

    def _analyze_streaks(self, trades: list[dict], date: str):
        """Flag consecutive losses."""
        consecutive = 0
        for t in trades:
            pnl = t.get("pnl", 0) or 0
            if pnl < 0:
                consecutive += 1
            else:
                consecutive = 0

        if consecutive >= 3:
            self.add_insight(
                "risk",
                f"{consecutive} consecutive losses — system may be in adverse regime",
                sum(t.get("pnl", 0) or 0 for t in trades if (t.get("pnl", 0) or 0) < 0),
                date,
            )

    def get_insights(
        self,
        category: str | None = None,
        confidence: str | None = None,
        min_occurrences: int = 1,
    ) -> list[Insight]:
        """Retrieve accumulated insights with optional filters."""
        query = "SELECT * FROM learnings WHERE occurrences >= ?"
        params: list = [min_occurrences]

        if category:
            query += " AND category = ?"
            params.append(category)
        if confidence:
            query += " AND confidence = ?"
            params.append(confidence)

        query += " ORDER BY occurrences DESC, pnl_impact DESC"

        rows = self._conn.execute(query, params).fetchall()
        return [
            Insight(
                id=r["id"],
                date=r["date"],
                category=r["category"],
                insight=r["insight"],
                confidence=r["confidence"],
                occurrences=r["occurrences"],
                last_seen=r["last_seen"],
                pnl_impact=r["pnl_impact"],
            )
            for r in rows
        ]

    def get_confirmed_insights(self) -> list[Insight]:
        """Get only confirmed insights (seen 3+ times)."""
        return self.get_insights(confidence="confirmed")

    def close(self):
        self._conn.close()
