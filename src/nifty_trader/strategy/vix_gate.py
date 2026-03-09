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
    position sizing, confirmation requirements, and delta targets.

    VIX smoothing: uses a simple moving average over recent readings to
    avoid regime flipping on tick-to-tick noise.
    """

    _VIX_SMOOTH_WINDOW = 10  # number of readings to average

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
        self._vix_history: list[float] = []

    def smooth(self, raw_vix: float) -> float:
        """Feed a raw VIX reading and return the smoothed (SMA) value."""
        self._vix_history.append(raw_vix)
        if len(self._vix_history) > self._VIX_SMOOTH_WINDOW:
            self._vix_history = self._vix_history[-self._VIX_SMOOTH_WINDOW:]
        return sum(self._vix_history) / len(self._vix_history)

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
        """Return position-size multiplier (0.0–1.0), linearly interpolated.

        Full size at VIX <= full threshold, zero at VIX >= blocked threshold,
        smooth linear ramp in between.
        """
        if vix >= self._blocked:
            return 0.0
        if vix <= self._full:
            return 1.0
        # Linear interpolation: 1.0 at _full → 0.0 at _blocked
        return round(max(0.0, 1.0 - (vix - self._full) / (self._blocked - self._full)), 2)

    def min_confirmations(self, vix: float) -> int:
        """Higher VIX → more confirmations required before entry."""
        mode = self.get_mode(vix)
        if mode in (VixMode.CAUTION, VixMode.SELECTIVE, VixMode.RESTRICTED):
            return 4
        return 3

    def target_delta(self, vix: float) -> float:
        """Higher VIX → safer OTM strikes (lower delta) to reduce vega risk."""
        return self._delta_low if vix >= self._selective else self._delta_high
