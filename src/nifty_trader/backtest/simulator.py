"""Option premium simulator — approximate ATM premium path from index candles + VIX.

Since DhanHQ doesn't provide historical option candles, we simulate
CE/PE premiums from the underlying index candle data and VIX level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SimulatedPremium:
    """Simulated ATM option premium at a point in time."""
    timestamp: str
    ce_premium: float
    pe_premium: float
    delta: float  # approximate ATM delta used


class PremiumSimulator:
    """Estimates ATM option premium from index price movement + VIX.

    Model:
        base_premium ≈ spot × (vix/100) × sqrt(dte/365) × scaling_factor
        premium_delta ≈ index_move × delta (ATM ~0.5)

    The first candle premium is the base. Subsequent candles track the
    index proportionally through delta.
    """

    def __init__(
        self,
        scaling_factor: float = 0.4,
        atm_delta: float = 0.50,
        min_premium: float = 5.0,
        slippage_pct: float = 0.5,
    ):
        self._scaling = scaling_factor
        self._delta = atm_delta
        self._min_premium = min_premium
        self._slippage_pct = slippage_pct  # bid-ask spread cost per side

    def estimate_base_premium(
        self, spot: float, vix: float, dte: float = 5.0,
    ) -> float:
        """Estimate ATM option premium from spot, VIX, and days to expiry."""
        if spot <= 0 or vix <= 0 or dte <= 0:
            return self._min_premium
        premium = spot * (vix / 100) * math.sqrt(dte / 365) * self._scaling
        return max(premium, self._min_premium)

    def simulate_option_ohlc_from_index(
        self,
        index_open: float,
        index_high: float,
        index_low: float,
        index_close: float,
    ) -> dict:
        """Simulate CE and PE first-candle OHLC from index candle.

        Index O=H (bearish) implies:
          - CE: O=H (call sellers dominate, premium drops)
          - PE: O=L (put buyers push premium up)

        Index O=L (bullish) implies:
          - CE: O=L (call buyers push premium up)
          - PE: O=H (put sellers dominate, premium drops)
        """
        idx_range = index_high - index_low
        if idx_range <= 0:
            idx_range = 1.0

        # CE moves WITH index (bullish → CE up)
        ce_open = 150.0  # representative ATM premium
        ce_move_high = (index_high - index_open) * self._delta
        ce_move_low = (index_low - index_open) * self._delta
        ce_move_close = (index_close - index_open) * self._delta

        ce_high = ce_open + max(ce_move_high, 0)
        ce_low = ce_open + min(ce_move_low, 0)
        ce_close = ce_open + ce_move_close

        # PE moves AGAINST index (bearish → PE up)
        pe_open = 150.0
        pe_move_high = (index_open - index_low) * self._delta
        pe_move_low = (index_open - index_high) * self._delta
        pe_move_close = (index_open - index_close) * self._delta

        pe_high = pe_open + max(pe_move_high, 0)
        pe_low = pe_open + min(pe_move_low, 0)
        pe_close = pe_open + pe_move_close

        return {
            "ce_open": ce_open,
            "ce_high": max(ce_high, self._min_premium),
            "ce_low": max(ce_low, self._min_premium),
            "ce_close": max(ce_close, self._min_premium),
            "pe_open": pe_open,
            "pe_high": max(pe_high, self._min_premium),
            "pe_low": max(pe_low, self._min_premium),
            "pe_close": max(pe_close, self._min_premium),
        }

    def simulate_premium_path(
        self,
        candles: list[dict],
        direction: str,
        vix: float,
        dte: float = 5.0,
    ) -> list[SimulatedPremium]:
        """Simulate option premium for each candle in the day.

        Args:
            candles: List of index candle dicts (open, high, low, close, timestamp).
            direction: "BULLISH" (CE) or "BEARISH" (PE).
            vix: Daily VIX level.
            dte: Days to expiry (default 5 for weekly options).

        Returns:
            List of SimulatedPremium for each candle.
        """
        if not candles:
            return []

        first = candles[0]
        base_spot = first["open"]
        base_premium = self.estimate_base_premium(base_spot, vix, dte)

        # Approximate theta decay: ~3% of premium per trading day for weeklies
        # Spread across trading minutes (375 min/day = 9:15-15:30)
        theta_per_min = base_premium * 0.03 / 375.0

        result = []
        for i, candle in enumerate(candles):
            # Time decay based on candle index (5-min intervals)
            decay = theta_per_min * 5.0 * i

            if direction == "BULLISH":
                move = (candle["close"] - base_spot) * self._delta
                premium = base_premium + move - decay
            else:
                move = (base_spot - candle["close"]) * self._delta
                premium = base_premium + move - decay

            premium = max(premium, self._min_premium)

            result.append(SimulatedPremium(
                timestamp=str(candle.get("timestamp", "")),
                ce_premium=max(base_premium + (candle["close"] - base_spot) * self._delta - decay, self._min_premium),
                pe_premium=max(base_premium + (base_spot - candle["close"]) * self._delta - decay, self._min_premium),
                delta=self._delta,
            ))

        return result

    def get_entry_premium(
        self, spot: float, vix: float, dte: float = 5.0,
    ) -> float:
        """Get the entry premium for position sizing (includes slippage)."""
        base = self.estimate_base_premium(spot, vix, dte)
        # Entry pays the ask — add slippage
        return base * (1 + self._slippage_pct / 100)

    def premium_at_index_price(
        self,
        index_price: float,
        base_spot: float,
        base_premium: float,
        direction: str,
    ) -> float:
        """Calculate option premium at a given index price.

        Args:
            index_price: Current index price.
            base_spot: Index price when position was entered.
            base_premium: Option premium at entry.
            direction: "BULLISH" (CE) or "BEARISH" (PE).
        """
        if direction == "BULLISH":
            move = (index_price - base_spot) * self._delta
        else:
            move = (base_spot - index_price) * self._delta
        return max(base_premium + move, self._min_premium)
