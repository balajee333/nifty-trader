"""Emergency halt on anomaly detection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nifty_trader.alerts.notifier import Notifier
from nifty_trader.orders.tracker import OrderTracker

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


class KillSwitch:
    """Monitors for anomalies and triggers emergency halt."""

    def __init__(
        self,
        dhan: DhanHQ,
        tracker: OrderTracker,
        notifier: Notifier,
        max_single_loss_pct: float = 5.0,
        capital: float = 100_000.0,
        max_consecutive_rejections: int = 3,
    ):
        self._dhan = dhan
        self._tracker = tracker
        self._notifier = notifier
        self._max_loss = capital * max_single_loss_pct / 100
        self._max_rejections = max_consecutive_rejections
        self._triggered = False

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def check(
        self,
        internal_position_count: int,
        current_loss: float = 0.0,
        is_spread: bool = False,
    ) -> bool:
        """Run anomaly checks. Returns True if kill switch was triggered.

        For spreads, 1 internal position = 2 API positions (short + long legs).
        """
        if self._triggered:
            return True

        reasons: list[str] = []

        # Check position mismatch (spread = 2 API positions per 1 internal)
        expected_api_count = internal_position_count * 2 if is_spread else internal_position_count
        api_count = self._get_api_position_count()
        if api_count is not None and api_count != expected_api_count:
            reasons.append(
                f"Position mismatch: API={api_count} vs Expected={expected_api_count}"
            )

        # Check single position loss
        if current_loss < -self._max_loss:
            reasons.append(f"Single position loss {current_loss:.0f} exceeds limit {-self._max_loss:.0f}")

        # Check consecutive rejections
        if self._tracker.consecutive_rejections >= self._max_rejections:
            reasons.append(
                f"{self._tracker.consecutive_rejections} consecutive order rejections"
            )

        if reasons:
            self._trigger(reasons)
            return True

        return False

    def _trigger(self, reasons: list[str]):
        self._triggered = True
        reason_str = "; ".join(reasons)
        logger.critical("KILL SWITCH TRIGGERED: %s", reason_str)

        # Cancel all orders
        try:
            self._dhan.cancel_order(order_id="all")
        except Exception:
            logger.exception("Failed to cancel all orders during kill switch")

        # Activate DhanHQ kill switch
        try:
            self._dhan.kill_switch(action="activate")
            logger.info("DhanHQ kill switch activated")
        except Exception:
            logger.exception("Failed to activate DhanHQ kill switch")

        self._notifier.kill_switch(reason_str)

    def _get_api_position_count(self) -> int | None:
        """Get open position count from DhanHQ API."""
        try:
            resp = self._dhan.get_positions()
            if resp and resp.get("status") == "success":
                positions = resp.get("data", [])
                open_count = sum(
                    1 for p in positions
                    if int(p.get("netQty", p.get("quantity", 0))) != 0
                )
                return open_count
        except Exception:
            logger.exception("Failed to fetch API positions")
        return None

    def reset(self):
        """Reset kill switch (manual intervention required)."""
        self._triggered = False
        try:
            self._dhan.kill_switch(action="deactivate")
        except Exception:
            logger.exception("Failed to deactivate DhanHQ kill switch")
