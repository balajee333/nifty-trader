"""Risk manager — position sizing, daily loss cap, trailing stop logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from nifty_trader.config import RiskConfig, SpreadConfig
from nifty_trader.constants import NIFTY_LOT_SIZE

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    lots: int
    quantity: int
    risk_amount: float
    sl_per_unit: float


@dataclass
class SpreadPositionSize:
    lots: int
    quantity: int
    max_risk: float
    net_credit: float
    spread_width: float


@dataclass
class SpreadMonitorState:
    short_entry_price: float
    long_entry_price: float
    net_credit: float
    profit_target_pct: float
    loss_threshold_multiplier: float

    @property
    def profit_target_credit(self) -> float:
        """Exit when spread can be bought back for this amount (credit - target%)."""
        return self.net_credit * (1 - self.profit_target_pct / 100)

    @property
    def loss_threshold_cost(self) -> float:
        """Exit when spread cost reaches this (multiplier × credit)."""
        return self.net_credit * self.loss_threshold_multiplier


@dataclass
class TrailingState:
    entry_price: float
    sl_price: float
    target_price: float
    peak_price: float
    at_breakeven: bool = False
    at_advanced: bool = False


class RiskManager:
    """Handles position sizing, daily loss tracking, trailing stops."""

    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self._daily_pnl: float = 0.0
        self._trade_count: int = 0
        self._open_positions: int = 0

    @property
    def daily_loss_limit(self) -> float:
        return self.cfg.capital * self.cfg.daily_loss_limit_pct / 100

    @property
    def is_daily_stopped(self) -> bool:
        return self._daily_pnl <= -self.daily_loss_limit

    @property
    def can_open_position(self) -> bool:
        return self._open_positions < self.cfg.max_positions and not self.is_daily_stopped

    def compute_position_size(self, entry_price: float) -> PositionSize | None:
        """Calculate lots based on risk per trade and SL amount."""
        if entry_price <= 0:
            return None

        max_risk = self.cfg.capital * self.cfg.risk_per_trade_pct / 100
        sl_per_unit = entry_price * self.cfg.sl_pct / 100

        if sl_per_unit <= 0:
            return None

        risk_per_lot = sl_per_unit * NIFTY_LOT_SIZE
        lots = int(max_risk / risk_per_lot)

        if lots < 1:
            lots = 1  # Minimum 1 lot

        total_cost = entry_price * lots * NIFTY_LOT_SIZE
        if total_cost > self.cfg.capital:
            lots = int(self.cfg.capital / (entry_price * NIFTY_LOT_SIZE))
            if lots < 1:
                logger.warning("Insufficient capital for even 1 lot at %.2f", entry_price)
                return None

        return PositionSize(
            lots=lots,
            quantity=lots * NIFTY_LOT_SIZE,
            risk_amount=sl_per_unit * lots * NIFTY_LOT_SIZE,
            sl_per_unit=sl_per_unit,
        )

    def compute_sl_target(self, entry_price: float) -> tuple[float, float]:
        """Returns (stop_loss_price, target_price)."""
        sl_amount = entry_price * self.cfg.sl_pct / 100
        sl_price = entry_price - sl_amount
        target_price = entry_price + sl_amount * self.cfg.reward_risk_ratio
        return max(sl_price, 0.05), target_price

    def create_trailing_state(self, entry_price: float) -> TrailingState:
        sl, target = self.compute_sl_target(entry_price)
        return TrailingState(
            entry_price=entry_price,
            sl_price=sl,
            target_price=target,
            peak_price=entry_price,
        )

    def update_trailing(self, state: TrailingState, current_price: float) -> TrailingState:
        """Update trailing stop based on current price movement."""
        if current_price <= 0:
            return state

        state.peak_price = max(state.peak_price, current_price)
        move_from_entry = current_price - state.entry_price
        target_move = state.target_price - state.entry_price

        if target_move <= 0:
            return state

        progress_pct = (move_from_entry / target_move) * 100

        # Move to breakeven at 50% of target
        if not state.at_breakeven and progress_pct >= self.cfg.trailing_breakeven_pct:
            state.sl_price = state.entry_price
            state.at_breakeven = True
            logger.info("Trailing: moved SL to breakeven at %.2f", state.entry_price)

        # Trail further at 75% of target
        if not state.at_advanced and progress_pct >= self.cfg.trailing_advance_pct:
            # Move SL to 50% of profit
            state.sl_price = state.entry_price + move_from_entry * 0.5
            state.at_advanced = True
            logger.info("Trailing: advanced SL to %.2f", state.sl_price)
        elif state.at_advanced:
            # Keep trailing at 50% of peak profit
            peak_profit = state.peak_price - state.entry_price
            new_sl = state.entry_price + peak_profit * 0.5
            if new_sl > state.sl_price:
                state.sl_price = new_sl

        return state

    def should_exit(self, state: TrailingState, current_price: float) -> tuple[bool, str]:
        """Check if position should be exited based on trailing SL or target."""
        if current_price <= state.sl_price:
            return True, f"SL hit at {current_price:.2f} (SL={state.sl_price:.2f})"
        if current_price >= state.target_price:
            return True, f"Target hit at {current_price:.2f} (Target={state.target_price:.2f})"
        return False, ""

    def record_trade_pnl(self, pnl: float):
        self._daily_pnl += pnl
        self._trade_count += 1
        logger.info("Daily P&L: %.2f after %d trades", self._daily_pnl, self._trade_count)

    def on_position_opened(self):
        self._open_positions += 1

    def on_position_closed(self):
        self._open_positions = max(0, self._open_positions - 1)

    def compute_spread_position_size(
        self,
        net_credit: float,
        spread_width: float,
    ) -> SpreadPositionSize | None:
        """Calculate lots for a credit spread based on max risk per trade."""
        if net_credit <= 0 or spread_width <= 0:
            return None

        max_risk = self.cfg.capital * self.cfg.risk_per_trade_pct / 100
        max_loss_per_lot = (spread_width - net_credit) * NIFTY_LOT_SIZE

        if max_loss_per_lot <= 0:
            # Spread credit exceeds width — free money, unlikely but cap at 1 lot
            lots = 1
        else:
            lots = int(max_risk / max_loss_per_lot)

        if lots < 1:
            # Even 1 lot exceeds risk budget — reject if > 2× limit
            if max_loss_per_lot > max_risk * 2:
                logger.warning(
                    "Spread too risky: max_loss/lot %.0f > 2× risk limit %.0f",
                    max_loss_per_lot, max_risk,
                )
                return None
            lots = 1

        return SpreadPositionSize(
            lots=lots,
            quantity=lots * NIFTY_LOT_SIZE,
            max_risk=max_loss_per_lot * lots,
            net_credit=net_credit,
            spread_width=spread_width,
        )

    def create_spread_monitor_state(
        self,
        short_entry: float,
        long_entry: float,
        spread_cfg: SpreadConfig,
    ) -> SpreadMonitorState:
        net_credit = short_entry - long_entry
        return SpreadMonitorState(
            short_entry_price=short_entry,
            long_entry_price=long_entry,
            net_credit=net_credit,
            profit_target_pct=spread_cfg.profit_target_pct,
            loss_threshold_multiplier=spread_cfg.loss_threshold_multiplier,
        )

    def should_exit_spread(
        self,
        state: SpreadMonitorState,
        short_ltp: float,
        long_ltp: float,
    ) -> tuple[bool, str]:
        """Check if spread should be exited based on profit target or loss threshold."""
        current_spread_cost = short_ltp - long_ltp  # cost to close the spread

        # Profit: credit captured >= target %
        profit_captured = state.net_credit - current_spread_cost
        profit_pct = (profit_captured / state.net_credit * 100) if state.net_credit > 0 else 0

        if profit_pct >= state.profit_target_pct:
            return True, (
                f"Profit target: {profit_pct:.0f}% of credit captured "
                f"(credit={state.net_credit:.2f}, close_cost={current_spread_cost:.2f})"
            )

        # Loss: spread cost exceeds threshold
        if current_spread_cost >= state.loss_threshold_cost:
            return True, (
                f"Loss threshold: spread cost {current_spread_cost:.2f} >= "
                f"{state.loss_threshold_multiplier:.0f}× credit ({state.loss_threshold_cost:.2f})"
            )

        return False, ""

    def reset_daily(self):
        self._daily_pnl = 0.0
        self._trade_count = 0
        self._open_positions = 0
