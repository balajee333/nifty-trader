"""Tests for risk manager."""

import pytest

from nifty_trader.config import RiskConfig
from nifty_trader.risk.manager import RiskManager, TrailingState


@pytest.fixture
def risk_mgr():
    return RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0, sl_pct=35.0))


class TestPositionSizing:
    def test_basic(self, risk_mgr):
        size = risk_mgr.compute_position_size(entry_price=200)
        assert size is not None
        assert size.lots >= 1
        assert size.quantity == size.lots * 25
        assert size.sl_per_unit == pytest.approx(70.0)  # 35% of 200

    def test_zero_price(self, risk_mgr):
        assert risk_mgr.compute_position_size(0) is None

    def test_expensive_option(self):
        mgr = RiskManager(RiskConfig(capital=10_000))
        size = mgr.compute_position_size(entry_price=500)
        # 500 * 25 = 12500 > 10000, should not return None since we allow 1 lot minimum check
        # But capital check: 500 * 1 * 25 = 12500 > 10000 → None
        assert size is None


class TestSLTarget:
    def test_basic(self, risk_mgr):
        sl, target = risk_mgr.compute_sl_target(200)
        assert sl == pytest.approx(130.0)  # 200 - 35% = 130
        assert target == pytest.approx(340.0)  # 200 + 70*2 = 340


class TestTrailing:
    def test_breakeven(self, risk_mgr):
        state = risk_mgr.create_trailing_state(200)
        # At 50% of target move → breakeven
        # target = 340, so 50% move = 200 + 0.5*(340-200) = 270
        state = risk_mgr.update_trailing(state, 270)
        assert state.at_breakeven
        assert state.sl_price == pytest.approx(200.0)

    def test_advanced_trail(self, risk_mgr):
        state = risk_mgr.create_trailing_state(200)
        # At 75% of target move → advanced
        # 200 + 0.75*140 = 305
        state = risk_mgr.update_trailing(state, 305)
        assert state.at_advanced
        assert state.sl_price > 200  # Should be above breakeven

    def test_exit_sl(self, risk_mgr):
        state = risk_mgr.create_trailing_state(200)
        should, reason = risk_mgr.should_exit(state, 120)
        assert should
        assert "SL" in reason

    def test_exit_target(self, risk_mgr):
        state = risk_mgr.create_trailing_state(200)
        should, reason = risk_mgr.should_exit(state, 350)
        assert should
        assert "Target" in reason


class TestLotSizeParameterization:
    def test_default_lot_size(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0, sl_pct=35.0))
        size = mgr.compute_position_size(200)
        assert size is not None
        assert size.quantity == size.lots * 25

    def test_mcx_gold_mini_lot_size(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0, sl_pct=35.0), lot_size=100)
        size = mgr.compute_position_size(50)
        assert size is not None
        assert size.quantity == size.lots * 100

    def test_mcx_spread_sizing_too_risky(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0), lot_size=100)
        size = mgr.compute_spread_position_size(net_credit=15.0, spread_width=500.0)
        # max_loss_per_lot = (500 - 15) * 100 = 48500 > 2× risk limit 4000 → rejected
        assert size is None

    def test_mcx_spread_sizing_feasible(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0), lot_size=100)
        size = mgr.compute_spread_position_size(net_credit=10.0, spread_width=20.0)
        assert size is not None
        assert size.quantity == size.lots * 100

    def test_natural_gas_lot_size(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0, sl_pct=35.0), lot_size=1250)
        size = mgr.compute_position_size(5)
        assert size is not None
        assert size.quantity == size.lots * 1250


class TestDailyLoss:
    def test_cap(self, risk_mgr):
        assert not risk_mgr.is_daily_stopped
        risk_mgr.record_trade_pnl(-3100)  # > 3% of 100k
        assert risk_mgr.is_daily_stopped

    def test_reset(self, risk_mgr):
        risk_mgr.record_trade_pnl(-5000)
        assert risk_mgr.is_daily_stopped
        risk_mgr.reset_daily()
        assert not risk_mgr.is_daily_stopped
