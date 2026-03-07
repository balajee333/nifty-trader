"""SQLite trade journal — trades, orders, daily summary, system events."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from nifty_trader.state import TradeContext

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL,
    option_type TEXT NOT NULL,
    security_id TEXT,
    strike_price REAL,
    expiry TEXT,
    entry_price REAL,
    exit_price REAL,
    quantity INTEGER,
    pnl REAL,
    entry_time TEXT,
    exit_time TEXT,
    exit_reason TEXT,
    confluence_score REAL,
    signals_summary TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    order_id TEXT UNIQUE,
    security_id TEXT,
    transaction_type TEXT,
    order_type TEXT,
    price REAL,
    quantity INTEGER,
    status TEXT,
    raw_response TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    gross_pnl REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    capital_end REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    details TEXT
);

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
);

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    category TEXT,
    insight TEXT,
    confidence TEXT DEFAULT 'observed',
    occurrences INTEGER DEFAULT 1,
    last_seen TEXT,
    pnl_impact REAL DEFAULT 0.0
);
"""


class TradeJournal:
    """SQLite-backed trade journal."""

    def __init__(self, db_path: str | Path = "trade_journal.db"):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate_spread_columns()

    def _migrate_spread_columns(self):
        """Add spread columns to trades table if they don't exist (backward-compatible)."""
        cursor = self._conn.execute("PRAGMA table_info(trades)")
        existing = {row[1] for row in cursor.fetchall()}
        spread_cols = {
            "is_spread": "INTEGER DEFAULT 0",
            "short_security_id": "TEXT",
            "short_strike_price": "REAL",
            "long_security_id": "TEXT",
            "long_strike_price": "REAL",
            "net_credit": "REAL",
            "spread_width": "REAL",
            "max_profit": "REAL",
            "max_loss": "REAL",
        }
        for col, col_type in spread_cols.items():
            if col not in existing:
                self._conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
        self._conn.commit()

    def log_trade(self, ctx: TradeContext):
        self._conn.execute(
            """INSERT INTO trades (
                timestamp, direction, option_type, security_id, strike_price,
                expiry, entry_price, exit_price, quantity, pnl,
                entry_time, exit_time, exit_reason, confluence_score, signals_summary,
                is_spread, short_security_id, short_strike_price,
                long_security_id, long_strike_price,
                net_credit, spread_width, max_profit, max_loss
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(),
                ctx.direction.value,
                ctx.option_type.value,
                ctx.security_id,
                ctx.strike_price,
                ctx.expiry,
                ctx.entry_price,
                ctx.exit_price,
                ctx.quantity,
                ctx.pnl,
                ctx.entry_time.isoformat() if ctx.entry_time else None,
                ctx.exit_time.isoformat() if ctx.exit_time else None,
                ctx.exit_reason,
                ctx.confluence_score,
                ctx.signals_summary,
                1 if ctx.is_spread else 0,
                ctx.short_security_id or None,
                ctx.short_strike_price or None,
                ctx.long_security_id or None,
                ctx.long_strike_price or None,
                ctx.net_credit or None,
                ctx.spread_width or None,
                ctx.max_profit or None,
                ctx.max_loss or None,
            ),
        )
        self._conn.commit()

    def log_order(
        self,
        order_id: str,
        security_id: str,
        transaction_type: str,
        order_type: str,
        price: float,
        quantity: int,
        status: str,
        raw_response: str = "",
    ):
        self._conn.execute(
            """INSERT OR REPLACE INTO orders (
                timestamp, order_id, security_id, transaction_type,
                order_type, price, quantity, status, raw_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(),
                order_id,
                security_id,
                transaction_type,
                order_type,
                price,
                quantity,
                status,
                raw_response,
            ),
        )
        self._conn.commit()

    def log_event(self, event_type: str, message: str, details: str = ""):
        self._conn.execute(
            "INSERT INTO system_events (timestamp, event_type, message, details) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), event_type, message, details),
        )
        self._conn.commit()

    def update_daily_summary(self, capital: float):
        today = datetime.now().strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT pnl FROM trades WHERE date(entry_time) = ?", (today,)
        ).fetchall()

        if not rows:
            return

        pnls = [r["pnl"] for r in rows if r["pnl"] is not None]
        total = len(pnls)
        winners = sum(1 for p in pnls if p > 0)
        losers = sum(1 for p in pnls if p < 0)
        gross = sum(pnls)

        # Max drawdown from cumulative P&L
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            cum += p
            peak = max(peak, cum)
            max_dd = min(max_dd, cum - peak)

        self._conn.execute(
            """INSERT OR REPLACE INTO daily_summary
            (date, total_trades, winning_trades, losing_trades, gross_pnl, max_drawdown, capital_end)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (today, total, winners, losers, gross, max_dd, capital + gross),
        )
        self._conn.commit()

    def get_today_trades(self) -> list[dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE date(entry_time) = ? ORDER BY id DESC", (today,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
