"""VIX-based regime filter for VENOM strategy."""

from __future__ import annotations

from enum import Enum


class VixMode(Enum):
    FULL = "full"
    SELECTIVE = "selective"
    CAUTION = "caution"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"


class VixGate:
    """Maps the current India VIX reading to a risk regime and adjusts
    position sizing, confirmation requirements, and delta targets."""

    def __init__(
        self,
        full: float = 13.0,
        selective: float = 18.0,
        caution: float = 23.0,
        blocked: float = 30.0,
        delta_low: float = 0.50,
        delta_high: float = 0.65,
    ):
        self._full = full
        self._selective = selective
        self._caution = caution
        self._blocked = blocked
        self._delta_low = delta_low
        self._delta_high = delta_high

    def get_mode(self, vix: float) -> VixMode:
        """Classify VIX into a trading mode."""
        if vix >= self._blocked:
            return VixMode.BLOCKED
        if vix >= self._caution:
            return VixMode.RESTRICTED
        if vix >= self._selective:
            return VixMode.CAUTION
        if vix >= self._full:
            return VixMode.SELECTIVE
        return VixMode.FULL

    def can_trade(self, vix: float) -> bool:
        """Return False when VIX is too high to trade."""
        return self.get_mode(vix) != VixMode.BLOCKED

    def size_multiplier(self, vix: float) -> float:
        """Return position-size multiplier (0.0–1.0) based on VIX regime."""
        mode = self.get_mode(vix)
        if mode == VixMode.BLOCKED:
            return 0.0
        if mode in (VixMode.CAUTION, VixMode.RESTRICTED):
            return 0.5
        return 1.0

    def min_confirmations(self, vix: float) -> int:
        """Higher VIX → more confirmations required before entry."""
        mode = self.get_mode(vix)
        if mode in (VixMode.SELECTIVE, VixMode.RESTRICTED):
            return 4
        return 3

    def target_delta(self, vix: float) -> float:
        """Higher VIX → deeper ITM strikes (higher delta)."""
        return self._delta_high if vix >= self._selective else self._delta_low
