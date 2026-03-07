"""Tests for TrailEngine rung-based trailing stop-loss."""

import pytest
from nifty_trader.strategy.trail_engine import TrailEngine, TrailState


@pytest.fixture
def engine():
    return TrailEngine()


@pytest.fixture
def state(engine):
    return engine.create_state(entry_price=100.0)


class TestInitialState:
    def test_initial_sl(self, engine):
        state = engine.create_state(100.0)
        assert state.sl_price == pytest.approx(70.0)  # 30% below entry
        assert state.peak_price == 100.0
        assert state.risk_free is False
        assert state.rungs_hit == []


class TestSLHit:
    def test_sl_hit_returns_signal(self, engine, state):
        result = engine.update(state, 70.0)
        assert result == "SL_HIT"

    def test_sl_hit_below(self, engine, state):
        result = engine.update(state, 50.0)
        assert result == "SL_HIT"


class TestRung20:
    def test_rung_20_moves_sl_to_cost(self, engine, state):
        result = engine.update(state, 120.0)  # +20%
        assert result == "MOVE_SL_TO_COST"
        assert state.sl_price == pytest.approx(100.0)
        assert state.risk_free is True
        assert 20 in state.rungs_hit


class TestRung40:
    def test_rung_40_locks_profit(self, engine, state):
        engine.update(state, 120.0)  # hit rung 20 first
        result = engine.update(state, 140.0)  # +40%
        assert result == "LOCK_PROFIT"
        assert state.sl_price == pytest.approx(120.0)  # +20% locked
        assert 40 in state.rungs_hit


class TestRung70:
    def test_rung_70_locks_profit(self, engine, state):
        engine.update(state, 120.0)
        engine.update(state, 140.0)
        result = engine.update(state, 170.0)  # +70%
        assert result == "LOCK_PROFIT"
        assert state.sl_price == pytest.approx(145.0)  # +45% locked
        assert 70 in state.rungs_hit


class TestMaxProfit:
    def test_max_profit_exit(self, engine, state):
        engine.update(state, 120.0)
        engine.update(state, 140.0)
        engine.update(state, 170.0)
        result = engine.update(state, 200.0)  # +100%
        assert result == "EXIT_MAX_PROFIT"


class TestSLNeverLowered:
    def test_sl_never_decreases(self, engine, state):
        engine.update(state, 120.0)  # SL -> 100
        sl_after_rung = state.sl_price
        engine.update(state, 105.0)  # price drops but above SL
        assert state.sl_price == sl_after_rung  # SL unchanged


class TestContinuousTrailing:
    def test_trailing_beyond_last_rung(self, engine, state):
        engine.update(state, 120.0)
        engine.update(state, 140.0)
        engine.update(state, 170.0)  # all rungs hit
        # Price goes to 180 (+80%), beyond last rung (70)
        result = engine.update(state, 180.0)
        assert result == "TRAILING"
        # trail_sl = 180 * (1 - 0.15) = 153.0
        assert state.sl_price == pytest.approx(153.0)

    def test_trailing_updates_with_higher_peak(self, engine, state):
        engine.update(state, 120.0)
        engine.update(state, 140.0)
        engine.update(state, 170.0)
        engine.update(state, 180.0)
        result = engine.update(state, 190.0)
        assert result == "TRAILING"
        # trail_sl = 190 * 0.85 = 161.5
        assert state.sl_price == pytest.approx(161.5)


class TestNoAction:
    def test_price_unchanged_no_action(self, engine, state):
        result = engine.update(state, 100.0)
        assert result is None

    def test_small_gain_no_action(self, engine, state):
        result = engine.update(state, 110.0)  # +10%, below first rung
        assert result is None
