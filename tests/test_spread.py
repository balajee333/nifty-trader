"""Tests for credit spread support."""

import pytest

from nifty_trader.config import RiskConfig, SpreadConfig
from nifty_trader.constants import Direction, OptionType, TradeState
from nifty_trader.data.option_chain import OptionContract
from nifty_trader.risk.manager import RiskManager, SpreadMonitorState
from nifty_trader.state import TradeFSM
from nifty_trader.strategy.strike_selector import select_spread


def _make_contract(
    security_id: str,
    strike: float,
    option_type: OptionType,
    delta: float,
    bid: float,
    ask: float,
    volume: int = 1000,
    oi: int = 10000,
    iv: float = 40.0,
) -> OptionContract:
    return OptionContract(
        security_id=security_id,
        strike_price=strike,
        option_type=option_type,
        expiry="2024-01-04",
        ltp=(bid + ask) / 2,
        bid=bid,
        ask=ask,
        volume=volume,
        oi=oi,
        delta=delta,
        theta=-0.5,
        gamma=0.01,
        vega=0.1,
        iv=iv,
    )


class TestSpreadStrikeSelection:
    @pytest.fixture
    def spread_cfg(self):
        return SpreadConfig(
            short_delta_min=0.15,
            short_delta_max=0.30,
            short_delta_target=0.20,
            spread_width_points=100,
            min_credit=5.0,
            min_volume=500,
            min_oi=5000,
            max_spread_pct=3.0,
            iv_rank_min=30.0,
        )

    def test_bull_put_spread(self, spread_cfg):
        # bid-ask spread must be < 3%: (ask-bid)/bid*100
        contracts = [
            _make_contract("P22500", 22500, OptionType.PUT, -0.20, 100, 102, iv=40),
            _make_contract("P22400", 22400, OptionType.PUT, -0.12, 80, 82, iv=40),
            _make_contract("C22700", 22700, OptionType.CALL, 0.40, 50, 52),
        ]
        result = select_spread(contracts, Direction.BULLISH, spread_cfg)
        assert result is not None
        assert result.short_leg.strike_price == 22500
        assert result.long_leg.strike_price == 22400
        assert result.net_credit == pytest.approx(20.0)  # 101 - 81
        assert result.spread_width == 100
        assert result.max_loss == pytest.approx(80.0)  # 100 - 20

    def test_bear_call_spread(self, spread_cfg):
        contracts = [
            _make_contract("C22700", 22700, OptionType.CALL, 0.20, 100, 102, iv=40),
            _make_contract("C22800", 22800, OptionType.CALL, 0.10, 80, 82, iv=40),
        ]
        result = select_spread(contracts, Direction.BEARISH, spread_cfg)
        assert result is not None
        assert result.short_leg.strike_price == 22700
        assert result.long_leg.strike_price == 22800
        assert result.net_credit == pytest.approx(20.0)  # 101 - 81
        assert result.spread_width == 100

    def test_no_spread_insufficient_credit(self, spread_cfg):
        contracts = [
            _make_contract("P22500", 22500, OptionType.PUT, -0.20, 10, 12, iv=40),
            _make_contract("P22400", 22400, OptionType.PUT, -0.12, 8, 10, iv=40),
        ]
        result = select_spread(contracts, Direction.BULLISH, spread_cfg)
        # Net credit = 11 - 9 = 2 < min_credit 5
        assert result is None

    def test_no_spread_low_iv(self, spread_cfg):
        contracts = [
            _make_contract("P22500", 22500, OptionType.PUT, -0.20, 30, 32, iv=20),
            _make_contract("P22400", 22400, OptionType.PUT, -0.12, 18, 20, iv=20),
        ]
        result = select_spread(contracts, Direction.BULLISH, spread_cfg)
        assert result is None  # IV 20 < iv_rank_min 30

    def test_no_long_leg_match(self, spread_cfg):
        contracts = [
            _make_contract("P22500", 22500, OptionType.PUT, -0.20, 30, 32, iv=40),
            # No 22400 PUT available
        ]
        result = select_spread(contracts, Direction.BULLISH, spread_cfg)
        assert result is None


class TestSpreadPositionSizing:
    @pytest.fixture
    def risk_mgr(self):
        return RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0))

    def test_basic_sizing(self, risk_mgr):
        size = risk_mgr.compute_spread_position_size(net_credit=12.0, spread_width=100.0)
        assert size is not None
        assert size.lots >= 1
        assert size.quantity == size.lots * 25
        # max_loss_per_lot = (100 - 12) * 25 = 2200
        # max_risk = 100k * 2% = 2000
        # lots = int(2000 / 2200) = 0 → clamped to 1
        assert size.lots == 1
        assert size.max_risk == pytest.approx(2200.0)

    def test_wider_risk_budget(self):
        mgr = RiskManager(RiskConfig(capital=500_000, risk_per_trade_pct=2.0))
        size = mgr.compute_spread_position_size(net_credit=20.0, spread_width=100.0)
        assert size is not None
        # max_loss_per_lot = (100 - 20) * 25 = 2000
        # max_risk = 500k * 2% = 10000
        # lots = int(10000 / 2000) = 5
        assert size.lots == 5

    def test_zero_credit(self, risk_mgr):
        assert risk_mgr.compute_spread_position_size(0, 100) is None

    def test_zero_width(self, risk_mgr):
        assert risk_mgr.compute_spread_position_size(12, 0) is None


class TestSpreadFSMLifecycle:
    def test_full_spread_lifecycle(self):
        fsm = TradeFSM()
        assert fsm.state == TradeState.IDLE

        # Signal
        fsm.start_signal(Direction.BULLISH, 2.5, "test spread")
        assert fsm.state == TradeState.SIGNAL_DETECTED

        # Order placed
        fsm.spread_order_placed(
            short_order_id="PAPER-1",
            long_order_id="PAPER-2",
            short_security_id="P22500",
            long_security_id="P22400",
            short_strike=22500,
            long_strike=22400,
            expiry="2024-01-04",
            quantity=25,
            net_credit=12.0,
            spread_width=100.0,
        )
        assert fsm.state == TradeState.ORDER_PLACED
        assert fsm.ctx.is_spread
        assert fsm.ctx.max_profit == pytest.approx(12.0)
        assert fsm.ctx.max_loss == pytest.approx(88.0)

        # Position opened
        fsm.spread_position_opened(short_fill=31.0, long_fill=19.0)
        assert fsm.state == TradeState.POSITION_OPEN
        assert fsm.has_position
        assert fsm.ctx.net_credit == pytest.approx(12.0)

        # Skip TRAILING — spreads go directly to exit
        fsm.start_exit("Profit target reached")
        assert fsm.state == TradeState.EXITING

        # Position closed — 50% of credit captured
        # short bought back at 25, long sold at 19 → cost_to_close = 25 - 19 = 6
        fsm.spread_position_closed(short_exit=25.0, long_exit=19.0)
        assert fsm.state == TradeState.CLOSED
        # PnL = (12 - 6) * 25 = 150
        assert fsm.ctx.pnl == pytest.approx(150.0)

    def test_spread_losing_trade(self):
        fsm = TradeFSM()
        fsm.start_signal(Direction.BULLISH, 2.5, "test")
        fsm.spread_order_placed(
            short_order_id="PAPER-1",
            long_order_id="PAPER-2",
            short_security_id="P22500",
            long_security_id="P22400",
            short_strike=22500,
            long_strike=22400,
            expiry="2024-01-04",
            quantity=25,
            net_credit=12.0,
            spread_width=100.0,
        )
        fsm.spread_position_opened(31.0, 19.0)
        fsm.start_exit("Loss threshold")
        # Cost to close = 36 - 19 = 17 > credit of 12
        fsm.spread_position_closed(short_exit=36.0, long_exit=19.0)
        # PnL = (12 - 17) * 25 = -125
        assert fsm.ctx.pnl == pytest.approx(-125.0)


class TestMCXSpreadPositionSizing:
    """Credit spread sizing with MCX lot sizes."""

    def test_gold_mini_spread(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0), lot_size=100)
        # Gold Mini 500-point spread, ₹15 credit
        size = mgr.compute_spread_position_size(net_credit=15.0, spread_width=500.0)
        # max_loss_per_lot = (500 - 15) * 100 = 48500 > 2× risk (4000)
        assert size is None

    def test_gold_mini_narrow_spread(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0), lot_size=100)
        # Narrower spread more suitable for ₹1L capital
        size = mgr.compute_spread_position_size(net_credit=10.0, spread_width=20.0)
        assert size is not None
        # max_loss_per_lot = (20 - 10) * 100 = 1000
        # max_risk = 2000
        # lots = int(2000/1000) = 2
        assert size.lots == 2
        assert size.quantity == 200

    def test_crude_mini_spread(self):
        mgr = RiskManager(RiskConfig(capital=100_000, risk_per_trade_pct=2.0), lot_size=10)
        size = mgr.compute_spread_position_size(net_credit=50.0, spread_width=100.0)
        assert size is not None
        # max_loss_per_lot = (100 - 50) * 10 = 500
        # max_risk = 2000
        # lots = int(2000/500) = 4
        assert size.lots == 4
        assert size.quantity == 40


class TestSpreadExitLogic:
    def test_profit_target_exit(self):
        mgr = RiskManager(RiskConfig(capital=100_000))
        state = SpreadMonitorState(
            short_entry_price=31.0,
            long_entry_price=19.0,
            net_credit=12.0,
            profit_target_pct=50.0,
            loss_threshold_multiplier=2.0,
        )
        # 50% profit captured: close cost = 6, profit = 12-6 = 6 = 50%
        should, reason = mgr.should_exit_spread(state, short_ltp=25.0, long_ltp=19.0)
        assert should
        assert "Profit target" in reason

    def test_no_exit_yet(self):
        mgr = RiskManager(RiskConfig(capital=100_000))
        state = SpreadMonitorState(
            short_entry_price=31.0,
            long_entry_price=19.0,
            net_credit=12.0,
            profit_target_pct=50.0,
            loss_threshold_multiplier=2.0,
        )
        # close cost = 10, profit = 12-10 = 2 = 16.7% < 50%
        should, _ = mgr.should_exit_spread(state, short_ltp=29.0, long_ltp=19.0)
        assert not should

    def test_loss_threshold_exit(self):
        mgr = RiskManager(RiskConfig(capital=100_000))
        state = SpreadMonitorState(
            short_entry_price=31.0,
            long_entry_price=19.0,
            net_credit=12.0,
            profit_target_pct=50.0,
            loss_threshold_multiplier=2.0,
        )
        # Loss threshold: close cost >= 2× credit = 24
        should, reason = mgr.should_exit_spread(state, short_ltp=43.0, long_ltp=19.0)
        assert should
        assert "Loss threshold" in reason
