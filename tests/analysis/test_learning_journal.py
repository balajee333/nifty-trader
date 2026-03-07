"""Tests for LearningJournal."""

import pytest

from nifty_trader.analysis.learning_journal import Insight, LearningJournal


@pytest.fixture
def learner(tmp_path):
    db = tmp_path / "test.db"
    lj = LearningJournal(db)
    yield lj
    lj.close()


@pytest.fixture
def sample_trades():
    return [
        {
            "id": 1, "pnl": 2000, "direction": "BEARISH",
            "entry_time": "2026-03-07T09:20:00", "exit_time": "2026-03-07T10:30:00",
            "exit_reason": "TRAILING", "confluence_score": 3.5,
            "signals_summary": "O=H strong bearish",
        },
        {
            "id": 2, "pnl": -800, "direction": "BULLISH",
            "entry_time": "2026-03-07T13:00:00", "exit_time": "2026-03-07T13:25:00",
            "exit_reason": "SL_HIT", "confluence_score": 1.8,
            "signals_summary": "pullback reversal",
        },
    ]


class TestLearningJournal:
    def test_add_insight_new(self, learner):
        learner.add_insight("signal", "O=H works well on Mondays", 1500)
        insights = learner.get_insights()
        assert len(insights) == 1
        assert insights[0].confidence == "observed"
        assert insights[0].occurrences == 1

    def test_add_insight_duplicate_increments(self, learner):
        learner.add_insight("signal", "O=H works well", 1000)
        learner.add_insight("signal", "O=H works well", 500)
        insights = learner.get_insights()
        assert len(insights) == 1
        assert insights[0].occurrences == 2
        assert insights[0].pnl_impact == 1500

    def test_confidence_confirmed_at_3(self, learner):
        for _ in range(3):
            learner.add_insight("signal", "Pattern X is reliable", 100)
        insights = learner.get_insights()
        assert insights[0].confidence == "confirmed"
        assert insights[0].occurrences == 3

    def test_filter_by_category(self, learner):
        learner.add_insight("signal", "Signal insight", 100)
        learner.add_insight("exit", "Exit insight", 200)

        signal_only = learner.get_insights(category="signal")
        assert len(signal_only) == 1
        assert signal_only[0].category == "signal"

    def test_filter_by_confidence(self, learner):
        learner.add_insight("signal", "New insight", 100)
        for _ in range(3):
            learner.add_insight("signal", "Confirmed insight", 100)

        confirmed = learner.get_insights(confidence="confirmed")
        assert len(confirmed) == 1

    def test_filter_by_min_occurrences(self, learner):
        learner.add_insight("signal", "Once", 100)
        learner.add_insight("signal", "Twice", 100)
        learner.add_insight("signal", "Twice", 100)

        multi = learner.get_insights(min_occurrences=2)
        assert len(multi) == 1
        assert multi[0].insight == "Twice"

    def test_get_confirmed_insights(self, learner):
        for _ in range(4):
            learner.add_insight("signal", "Very reliable", 200)
        learner.add_insight("signal", "Just once", 50)

        confirmed = learner.get_confirmed_insights()
        assert len(confirmed) == 1
        assert confirmed[0].insight == "Very reliable"

    def test_analyze_trades_generates_insights(self, learner, sample_trades):
        learner.analyze_trades(sample_trades, date="2026-03-07")
        insights = learner.get_insights()
        # Should generate at least some insights about signals, exits, etc.
        assert len(insights) > 0

    def test_analyze_signal_types(self, learner, sample_trades):
        learner._analyze_signal_types(sample_trades, "2026-03-07")
        insights = learner.get_insights(category="signal")
        assert len(insights) >= 1
        assert any("O=H" in i.insight for i in insights)

    def test_analyze_exit_patterns(self, learner, sample_trades):
        learner._analyze_exit_patterns(sample_trades, "2026-03-07")
        insights = learner.get_insights(category="exit")
        assert len(insights) >= 1

    def test_analyze_time_windows(self, learner, sample_trades):
        learner._analyze_time_windows(sample_trades, "2026-03-07")
        insights = learner.get_insights(category="entry")
        # Morning profitable, afternoon losing → should generate insight
        assert len(insights) >= 1

    def test_analyze_streaks_consecutive_losses(self, learner):
        trades = [
            {"id": i, "pnl": -500, "entry_time": "2026-03-07T10:00:00",
             "exit_reason": "SL_HIT", "signals_summary": ""}
            for i in range(4)
        ]
        learner._analyze_streaks(trades, "2026-03-07")
        insights = learner.get_insights(category="risk")
        assert any("consecutive losses" in i.insight for i in insights)

    def test_analyze_empty_trades(self, learner):
        learner.analyze_trades([])
        assert learner.get_insights() == []

    def test_day_of_week_high_win_rate(self, learner):
        trades = [
            {"id": 1, "pnl": 1000, "entry_time": "2026-03-07T10:00:00",
             "exit_reason": "", "signals_summary": ""},
            {"id": 2, "pnl": 800, "entry_time": "2026-03-07T10:30:00",
             "exit_reason": "", "signals_summary": ""},
            {"id": 3, "pnl": 500, "entry_time": "2026-03-07T11:00:00",
             "exit_reason": "", "signals_summary": ""},
        ]
        learner._analyze_day_of_week(trades, "2026-03-07")  # Saturday in test, but logic still runs
        insights = learner.get_insights(category="market")
        assert len(insights) >= 1
