"""Tests for EODAnalyzer."""

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nifty_trader.analysis.eod_analyzer import (
    DayAnalysis,
    EODAnalyzer,
    MissedSignal,
    TradeGrade,
)


@pytest.fixture
def mock_journal(tmp_path):
    """Create a mock journal with SQLite backing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, direction TEXT, option_type TEXT,
            security_id TEXT, strike_price REAL, expiry TEXT,
            entry_price REAL, exit_price REAL, quantity INTEGER,
            pnl REAL, entry_time TEXT, exit_time TEXT,
            exit_reason TEXT, confluence_score REAL, signals_summary TEXT
        );
    """)
    conn.commit()

    journal = MagicMock()
    journal._conn = conn
    journal.get_today_trades = MagicMock(return_value=[])
    return journal


@pytest.fixture
def sample_candles():
    """Sample 5-min candles for a bearish trending day."""
    base = 24500
    candles = []
    for i in range(75):  # ~6 hours of 5-min candles
        offset = -i * 2  # gradual decline
        candles.append({
            "timestamp": f"09:{15 + i * 5 // 60:02d}",
            "open": base + offset,
            "high": base + offset + 10,
            "low": base + offset - 15,
            "close": base + offset - 5,
            "volume": 100000 + i * 1000,
        })
    return candles


@pytest.fixture
def sample_trades():
    """Sample trades for grading."""
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        {
            "id": 1,
            "direction": "BEARISH",
            "option_type": "PUT",
            "entry_price": 85.0,
            "exit_price": 128.0,
            "quantity": 25,
            "pnl": 1075.0,
            "entry_time": f"{today}T09:20:00",
            "exit_time": f"{today}T10:30:00",
            "exit_reason": "TRAILING",
            "confluence_score": 3.5,
            "signals_summary": "O=H strong bearish",
        },
        {
            "id": 2,
            "direction": "BULLISH",
            "option_type": "CALL",
            "entry_price": 95.0,
            "exit_price": 72.0,
            "quantity": 25,
            "pnl": -575.0,
            "entry_time": f"{today}T13:00:00",
            "exit_time": f"{today}T13:25:00",
            "exit_reason": "SL_HIT",
            "confluence_score": 1.8,
            "signals_summary": "pullback reversal attempt",
        },
    ]


class TestEODAnalyzer:
    def test_analyze_no_trades(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        result = analyzer.analyze()

        assert isinstance(result, DayAnalysis)
        assert result.actual_pnl == 0
        assert result.trades_taken == []

    def test_analyze_with_trades(self, mock_journal, sample_trades):
        mock_journal.get_today_trades.return_value = sample_trades
        analyzer = EODAnalyzer(mock_journal)
        result = analyzer.analyze()

        assert len(result.trades_taken) == 2
        assert result.actual_pnl == 500.0  # 1075 - 575

    def test_grade_winning_trade(self, mock_journal, sample_trades):
        analyzer = EODAnalyzer(mock_journal)
        grade = analyzer._grade_trade(sample_trades[0], None)

        assert isinstance(grade, TradeGrade)
        assert grade.grade in ("A+", "A", "B")
        assert grade.entry_score >= 70  # high confluence + O=H signal
        assert grade.timing_score >= 70  # morning entry

    def test_grade_losing_trade(self, mock_journal, sample_trades):
        analyzer = EODAnalyzer(mock_journal)
        grade = analyzer._grade_trade(sample_trades[1], None)

        assert isinstance(grade, TradeGrade)
        assert grade.grade in ("C", "F")
        assert grade.exit_score <= 30  # SL hit
        assert grade.timing_score <= 40  # afternoon entry

    def test_classify_day_trending(self, mock_journal, sample_candles):
        analyzer = EODAnalyzer(mock_journal)
        day_type = analyzer._classify_day(sample_candles, (14.0, 16.0))
        assert "trending" in day_type

    def test_classify_day_volatile(self, mock_journal, sample_candles):
        analyzer = EODAnalyzer(mock_journal)
        day_type = analyzer._classify_day(sample_candles, (22.0, 28.0))
        assert day_type == "volatile"

    def test_classify_day_no_data(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        assert analyzer._classify_day(None, (0, 0)) == "unknown"
        assert analyzer._classify_day([], (0, 0)) == "unknown"

    def test_missed_signals_oh_not_traded(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        candles = [
            {"timestamp": "09:15", "open": 24500, "high": 24502, "low": 24450,
             "close": 24470, "volume": 200000},
        ] + [
            {"timestamp": f"{10 + i}:00", "open": 24470 - i * 10,
             "high": 24475 - i * 10, "low": 24460 - i * 10,
             "close": 24465 - i * 10, "volume": 100000}
            for i in range(10)
        ]

        missed = analyzer._detect_missed_signals([], candles, "2026-03-07")
        # O=H detected (high ≈ open), should flag missed bearish signal
        assert any("O=H" in m.signal_type for m in missed)

    def test_missed_signals_no_candles(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        assert analyzer._detect_missed_signals([], None, "2026-03-07") == []
        assert analyzer._detect_missed_signals([], [], "2026-03-07") == []

    def test_compute_market_range(self, mock_journal, sample_candles):
        analyzer = EODAnalyzer(mock_journal)
        (lo, hi), change = analyzer._compute_market_range(sample_candles)
        assert hi > lo
        assert change != 0

    def test_compute_market_range_empty(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        (lo, hi), change = analyzer._compute_market_range(None)
        assert lo == 0 and hi == 0 and change == 0

    def test_system_health_green(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trades = [TradeGrade(1, "A", 80, 80, 80, 1000, 0, 70, [])]
        assert analyzer._assess_health(trades, 1000) == "green"

    def test_system_health_red(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trades = [
            TradeGrade(1, "F", 20, 20, 20, 0, -2000, 0, []),
            TradeGrade(2, "F", 15, 15, 15, 0, -3000, 0, []),
        ]
        assert analyzer._assess_health(trades, -5000) == "red"

    def test_score_entry_high_confluence(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trade = {"confluence_score": 3.5, "signals_summary": "O=H bearish"}
        assert analyzer._score_entry(trade) >= 80

    def test_score_entry_low_confluence(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trade = {"confluence_score": 1.0, "signals_summary": ""}
        assert analyzer._score_entry(trade) <= 60

    def test_score_exit_max_profit(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trade = {"exit_reason": "EXIT_MAX_PROFIT", "pnl": 5000}
        assert analyzer._score_exit(trade, None) == 95

    def test_score_exit_sl_hit(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trade = {"exit_reason": "SL_HIT", "pnl": -2000}
        assert analyzer._score_exit(trade, None) == 20

    def test_generate_insights(self, mock_journal):
        analyzer = EODAnalyzer(mock_journal)
        trades = [TradeGrade(1, "A", 80, 80, 80, 1000, 0, 72, ["good entry"])]
        missed = [MissedSignal("13:45", "breakout", "NO_TRADE", 4200)]
        insights = analyzer._generate_insights(trades, missed, "bearish trending", (14, 16))
        assert len(insights) > 0
        assert any("captured" in i.lower() for i in insights)
