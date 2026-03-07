"""Trade lifecycle finite state machine."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from nifty_trader.constants import Direction, OptionType, TradeState
from nifty_trader.risk.manager import TrailingState

logger = logging.getLogger(__name__)

# Valid state transitions
_TRANSITIONS: dict[TradeState, set[TradeState]] = {
    TradeState.IDLE: {TradeState.SIGNAL_DETECTED, TradeState.DAILY_STOPPED},
    TradeState.SIGNAL_DETECTED: {TradeState.ORDER_PLACED, TradeState.IDLE},
    TradeState.ORDER_PLACED: {TradeState.POSITION_OPEN, TradeState.IDLE},
    TradeState.POSITION_OPEN: {TradeState.TRAILING, TradeState.EXITING},
    TradeState.TRAILING: {TradeState.EXITING},
    TradeState.EXITING: {TradeState.CLOSED},
    TradeState.CLOSED: {TradeState.IDLE},
    TradeState.ERROR: {TradeState.IDLE},
    TradeState.DAILY_STOPPED: set(),
}
# Any state can transition to ERROR
for st in TradeState:
    if st not in (TradeState.ERROR, TradeState.DAILY_STOPPED):
        _TRANSITIONS[st].add(TradeState.ERROR)
        _TRANSITIONS[st].add(TradeState.DAILY_STOPPED)


@dataclass
class TradeContext:
    """Mutable context carried through the trade lifecycle."""
    direction: Direction = Direction.NEUTRAL
    option_type: OptionType = OptionType.CALL
    security_id: str = ""
    strike_price: float = 0.0
    expiry: str = ""
    entry_price: float = 0.0
    quantity: int = 0
    order_id: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    trailing: TrailingState | None = None
    confluence_score: float = 0.0
    signals_summary: str = ""
    # Spread fields
    is_spread: bool = False
    short_security_id: str = ""
    short_strike_price: float = 0.0
    short_order_id: str = ""
    short_entry_price: float = 0.0
    long_security_id: str = ""
    long_strike_price: float = 0.0
    long_order_id: str = ""
    long_entry_price: float = 0.0
    net_credit: float = 0.0
    spread_width: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0


class TradeFSM:
    """Manages the trade lifecycle state machine."""

    def __init__(self):
        self._state = TradeState.IDLE
        self._context = TradeContext()
        self._history: list[tuple[TradeState, TradeState, datetime]] = []

    @property
    def state(self) -> TradeState:
        return self._state

    @property
    def ctx(self) -> TradeContext:
        return self._context

    @property
    def is_idle(self) -> bool:
        return self._state == TradeState.IDLE

    @property
    def has_position(self) -> bool:
        return self._state in (TradeState.POSITION_OPEN, TradeState.TRAILING)

    def transition(self, new_state: TradeState) -> bool:
        """Attempt a state transition. Returns True if successful."""
        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            logger.error(
                "Invalid transition: %s -> %s (allowed: %s)",
                self._state.value, new_state.value, [s.value for s in allowed],
            )
            return False

        old = self._state
        self._state = new_state
        self._history.append((old, new_state, datetime.now()))
        logger.info("State: %s -> %s", old.value, new_state.value)
        return True

    def reset(self):
        """Reset to IDLE with fresh context."""
        self._state = TradeState.IDLE
        self._context = TradeContext()

    def start_signal(self, direction: Direction, score: float, summary: str):
        if self.transition(TradeState.SIGNAL_DETECTED):
            self._context.direction = direction
            self._context.option_type = (
                OptionType.CALL if direction == Direction.BULLISH else OptionType.PUT
            )
            self._context.confluence_score = score
            self._context.signals_summary = summary

    def order_placed(
        self,
        order_id: str,
        security_id: str,
        strike_price: float,
        expiry: str,
        quantity: int,
    ):
        if self.transition(TradeState.ORDER_PLACED):
            self._context.order_id = order_id
            self._context.security_id = security_id
            self._context.strike_price = strike_price
            self._context.expiry = expiry
            self._context.quantity = quantity

    def position_opened(self, fill_price: float, trailing: TrailingState):
        if self.transition(TradeState.POSITION_OPEN):
            self._context.entry_price = fill_price
            self._context.entry_time = datetime.now()
            self._context.trailing = trailing

    def start_trailing(self):
        self.transition(TradeState.TRAILING)

    def start_exit(self, reason: str):
        if self.transition(TradeState.EXITING):
            self._context.exit_reason = reason

    def position_closed(self, exit_price: float):
        if self.transition(TradeState.CLOSED):
            self._context.exit_price = exit_price
            self._context.exit_time = datetime.now()
            self._context.pnl = (
                (exit_price - self._context.entry_price) * self._context.quantity
            )

    def spread_order_placed(
        self,
        short_order_id: str,
        long_order_id: str,
        short_security_id: str,
        long_security_id: str,
        short_strike: float,
        long_strike: float,
        expiry: str,
        quantity: int,
        net_credit: float,
        spread_width: float,
    ):
        if self.transition(TradeState.ORDER_PLACED):
            ctx = self._context
            ctx.is_spread = True
            ctx.short_order_id = short_order_id
            ctx.long_order_id = long_order_id
            ctx.short_security_id = short_security_id
            ctx.long_security_id = long_security_id
            ctx.short_strike_price = short_strike
            ctx.long_strike_price = long_strike
            ctx.expiry = expiry
            ctx.quantity = quantity
            ctx.net_credit = net_credit
            ctx.spread_width = spread_width
            ctx.max_profit = net_credit
            ctx.max_loss = spread_width - net_credit

    def spread_position_opened(
        self,
        short_fill: float,
        long_fill: float,
    ):
        if self.transition(TradeState.POSITION_OPEN):
            ctx = self._context
            ctx.short_entry_price = short_fill
            ctx.long_entry_price = long_fill
            ctx.net_credit = short_fill - long_fill
            ctx.max_profit = ctx.net_credit
            ctx.max_loss = ctx.spread_width - ctx.net_credit
            ctx.entry_price = ctx.net_credit  # net credit as entry reference
            ctx.entry_time = datetime.now()

    def spread_position_closed(self, short_exit: float, long_exit: float):
        if self.transition(TradeState.CLOSED):
            ctx = self._context
            ctx.exit_time = datetime.now()
            # PnL = (credit received - cost to close) × quantity
            cost_to_close = short_exit - long_exit  # cost to buy back short - proceeds from selling long
            ctx.pnl = (ctx.net_credit - cost_to_close) * ctx.quantity
            ctx.exit_price = cost_to_close

    def to_error(self, reason: str):
        self.transition(TradeState.ERROR)
        self._context.exit_reason = reason

    def daily_stop(self):
        self.transition(TradeState.DAILY_STOPPED)
