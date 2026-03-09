"""Rung-based trailing stop-loss engine for VENOM strategy."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrailState:
    entry_price: float
    sl_price: float
    peak_price: float
    risk_free: bool = False
    rungs_hit: list = field(default_factory=list)


class TrailEngine:
    def __init__(self, sl_pct: float = 30, activation_pct: float = 20,
                 trail_distance_pct: float = 15, max_profit_pct: float = 100):
        self.sl_pct = sl_pct
        self.activation_pct = activation_pct
        self.trail_distance_pct = trail_distance_pct
        self.max_profit_pct = max_profit_pct
        self._rungs = [
            (12, 0),     # +12% gain -> SL at cost (risk-free)
            (25, 12),    # +25% gain -> SL at +12%
            (50, 30),    # +50% gain -> SL at +30%
        ]

    def create_state(self, entry_price: float) -> TrailState:
        sl = entry_price * (1 - self.sl_pct / 100)
        return TrailState(entry_price=entry_price, sl_price=sl, peak_price=entry_price)

    def update(self, state: TrailState, current_price: float) -> Optional[str]:
        if current_price <= state.sl_price:
            return "SL_HIT"
        if current_price > state.peak_price:
            state.peak_price = current_price
        gain_pct = (current_price - state.entry_price) / state.entry_price * 100
        if gain_pct >= self.max_profit_pct:
            return "EXIT_MAX_PROFIT"
        action = None
        for rung_gain, sl_at in self._rungs:
            if gain_pct >= rung_gain and rung_gain not in state.rungs_hit:
                new_sl = state.entry_price * (1 + sl_at / 100)
                if new_sl > state.sl_price:
                    state.sl_price = new_sl
                    state.rungs_hit.append(rung_gain)
                    if sl_at == 0:
                        state.risk_free = True
                        action = "MOVE_SL_TO_COST"
                    else:
                        action = "LOCK_PROFIT"
        if state.rungs_hit and gain_pct > self._rungs[-1][0]:
            trail_sl = state.peak_price * (1 - self.trail_distance_pct / 100)
            if trail_sl > state.sl_price:
                state.sl_price = trail_sl
                action = "TRAILING"
        return action
