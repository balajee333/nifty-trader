"""Tests for the trade lifecycle FSM."""

import pytest

from nifty_trader.constants import Direction, TradeState
from nifty_trader.risk.manager import TrailingState
from nifty_trader.state import TradeFSM


class TestTradeFSM:
    def test_initial_state(self):
        fsm = TradeFSM()
        assert fsm.state == TradeState.IDLE
        assert fsm.is_idle
        assert not fsm.has_position

    def test_valid_flow(self):
        fsm = TradeFSM()
        fsm.start_signal(Direction.BULLISH, 2.5, "test")
        assert fsm.state == TradeState.SIGNAL_DETECTED

        fsm.order_placed("ORD-1", "12345", 22500, "2024-01-04", 25)
        assert fsm.state == TradeState.ORDER_PLACED

        trailing = TrailingState(
            entry_price=200, sl_price=130, target_price=340, peak_price=200,
        )
        fsm.position_opened(200, trailing)
        assert fsm.state == TradeState.POSITION_OPEN
        assert fsm.has_position

        fsm.start_trailing()
        assert fsm.state == TradeState.TRAILING
        assert fsm.has_position

        fsm.start_exit("Target hit")
        assert fsm.state == TradeState.EXITING

        fsm.position_closed(340)
        assert fsm.state == TradeState.CLOSED
        assert fsm.ctx.pnl == pytest.approx(3500)  # (340-200)*25

    def test_invalid_transition(self):
        fsm = TradeFSM()
        # Can't go from IDLE to POSITION_OPEN directly
        ok = fsm.transition(TradeState.POSITION_OPEN)
        assert not ok
        assert fsm.state == TradeState.IDLE

    def test_error_from_any(self):
        fsm = TradeFSM()
        fsm.start_signal(Direction.BEARISH, 2.0, "test")
        fsm.to_error("API failure")
        assert fsm.state == TradeState.ERROR

    def test_reset(self):
        fsm = TradeFSM()
        fsm.start_signal(Direction.BULLISH, 3.0, "test")
        fsm.reset()
        assert fsm.is_idle
        assert fsm.ctx.direction == Direction.NEUTRAL
