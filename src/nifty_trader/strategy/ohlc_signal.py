"""O=H / O=L signal detector for VENOM strategy.

Compares the first-candle OHLC of the index and its ATM CE/PE options to
determine whether a strong directional bias exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    BUY_CE = "buy_ce"
    BUY_PE = "buy_pe"
    WAIT = "wait"
    NO_TRADE = "no_trade"


@dataclass
class OhlcSignal:
    signal_type: SignalType
    index_pattern: str
    ce_pattern: str
    pe_pattern: str
    reason: str


class OhlcSignalDetector:
    """Detect O=H / O=L patterns across index + option candles.

    Tolerance is measured as a fraction of the candle's range (H-L),
    not of the open price.  For a 100-point range with 5 % tolerance,
    the open must be within 5 points of the high or low.
    """

    def __init__(
        self,
        index_tolerance_pct: float = 5.0,
        option_tolerance_abs: float = 2.0,
    ):
        # index_tolerance_pct: max (O-H)/(H-L) or (O-L)/(H-L) as a %
        self._idx_tol = index_tolerance_pct / 100.0
        # option_tolerance_abs: kept as absolute Rs for option premiums
        self._opt_tol = option_tolerance_abs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_open_eq_high(self, open_p: float, high: float, low: float, is_index: bool) -> bool:
        if is_index:
            rng = high - low
            if rng <= 0:
                return False
            return (high - open_p) / rng <= self._idx_tol
        return (high - open_p) <= self._opt_tol

    def _is_open_eq_low(self, open_p: float, high: float, low: float, is_index: bool) -> bool:
        if is_index:
            rng = high - low
            if rng <= 0:
                return False
            return (open_p - low) / rng <= self._idx_tol
        return (open_p - low) <= self._opt_tol

    def _pattern(self, open_p: float, high: float, low: float, is_index: bool) -> str:
        if self._is_open_eq_high(open_p, high, low, is_index):
            return "O=H"
        if self._is_open_eq_low(open_p, high, low, is_index):
            return "O=L"
        return "MID"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        index_open: float,
        index_high: float,
        index_low: float,
        index_close: float,
        ce_open: float,
        ce_high: float,
        ce_low: float,
        ce_close: float,
        pe_open: float,
        pe_high: float,
        pe_low: float,
        pe_close: float,
    ) -> OhlcSignal:
        """Analyse the first candle of index + ATM CE/PE and return a signal."""
        idx = self._pattern(index_open, index_high, index_low, is_index=True)
        ce = self._pattern(ce_open, ce_high, ce_low, is_index=False)
        pe = self._pattern(pe_open, pe_high, pe_low, is_index=False)

        # Strong bullish: index O=L, CE O=L, PE O=H
        if idx == "O=L" and ce == "O=L" and pe == "O=H":
            return OhlcSignal(
                SignalType.BUY_CE, idx, ce, pe,
                "Strong bullish: index + CE opening at low, PE capped",
            )

        # Strong bearish: index O=H, CE O=H, PE O=L
        if idx == "O=H" and ce == "O=H" and pe == "O=L":
            return OhlcSignal(
                SignalType.BUY_PE, idx, ce, pe,
                "Strong bearish: index + CE capped at open, PE climbing",
            )

        # Partial bullish
        if idx == "O=L" and (ce == "O=L" or pe == "O=H"):
            return OhlcSignal(
                SignalType.BUY_CE, idx, ce, pe,
                "Partial bullish: index O=L with supporting option signal",
            )

        # Partial bearish
        if idx == "O=H" and (ce == "O=H" or pe == "O=L"):
            return OhlcSignal(
                SignalType.BUY_PE, idx, ce, pe,
                "Partial bearish: index O=H with supporting option signal",
            )

        # Choppy: both options sold from open
        if ce == "O=H" and pe == "O=H":
            return OhlcSignal(
                SignalType.NO_TRADE, idx, ce, pe,
                "Choppy: both CE and PE sold from open",
            )

        # Default: no clear pattern
        return OhlcSignal(
            SignalType.WAIT, idx, ce, pe,
            "No clear O=H/O=L pattern detected",
        )
