"""Support/Resistance level detection from daily pivots + round numbers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from nifty_trader.data.indicators import pivot_levels, round_number_levels

logger = logging.getLogger(__name__)


@dataclass
class Level:
    price: float
    kind: str  # "pivot_s1", "pivot_r1", "round", etc.

    def distance_pct(self, current_price: float) -> float:
        if current_price <= 0:
            return float("inf")
        return abs(current_price - self.price) / current_price * 100


class LevelDetector:
    """Computes key S/R levels from daily candles."""

    def __init__(self, daily_df: pd.DataFrame):
        self._levels: list[Level] = []
        self._compute(daily_df)

    def _compute(self, df: pd.DataFrame):
        if df.empty:
            return

        last = df.iloc[-1]
        pivots = pivot_levels(
            high=float(last["high"]),
            low=float(last["low"]),
            close=float(last["close"]),
        )
        for name, price in pivots.items():
            self._levels.append(Level(price=price, kind=f"pivot_{name}"))

        rounds = round_number_levels(float(last["close"]))
        for price in rounds:
            self._levels.append(Level(price=price, kind="round"))

        self._levels.sort(key=lambda l: l.price)

    @property
    def all_levels(self) -> list[Level]:
        return self._levels

    def supports_below(self, price: float) -> list[Level]:
        return [l for l in self._levels if l.price < price]

    def resistances_above(self, price: float) -> list[Level]:
        return [l for l in self._levels if l.price > price]

    def nearest_support(self, price: float) -> Level | None:
        below = self.supports_below(price)
        return below[-1] if below else None

    def nearest_resistance(self, price: float) -> Level | None:
        above = self.resistances_above(price)
        return above[0] if above else None

    def is_near_support(self, price: float, threshold_pct: float = 0.3) -> bool:
        sup = self.nearest_support(price)
        return sup is not None and sup.distance_pct(price) <= threshold_pct

    def is_near_resistance(self, price: float, threshold_pct: float = 0.3) -> bool:
        res = self.nearest_resistance(price)
        return res is not None and res.distance_pct(price) <= threshold_pct
