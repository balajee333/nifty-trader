"""Pre-order validation — fund check, time check, duplicate prevention."""

from __future__ import annotations

import logging
from datetime import datetime, time

from nifty_trader.config import AppConfig
from nifty_trader.risk.manager import RiskManager

logger = logging.getLogger(__name__)


class OrderValidator:
    """Validates whether a new order should be placed."""

    def __init__(self, config: AppConfig, risk_mgr: RiskManager):
        self._cfg = config
        self._risk = risk_mgr
        self._last_order_security_id: str | None = None
        self._last_order_time: datetime | None = None

    def validate(self, security_id: str, premium: float) -> tuple[bool, str]:
        """Run all pre-order checks. Returns (ok, reason)."""
        checks = [
            self._check_time_window(),
            self._check_daily_loss(),
            self._check_position_limit(),
            self._check_duplicate(security_id),
            self._check_funds(premium),
        ]
        for ok, reason in checks:
            if not ok:
                logger.warning("Order validation failed: %s", reason)
                return False, reason

        self._last_order_security_id = security_id
        self._last_order_time = datetime.now()
        return True, "All checks passed"

    def _check_time_window(self) -> tuple[bool, str]:
        now = datetime.now().time()
        parts = self._cfg.timing.no_entry_after.split(":")
        cutoff = time(int(parts[0]), int(parts[1]))
        open_time = time(9, 15)

        if now < open_time:
            return False, f"Market not open yet ({now})"
        if now >= cutoff:
            return False, f"Past entry cutoff ({self._cfg.timing.no_entry_after})"
        return True, ""

    def _check_daily_loss(self) -> tuple[bool, str]:
        if self._risk.is_daily_stopped:
            return False, "Daily loss limit reached"
        return True, ""

    def _check_position_limit(self) -> tuple[bool, str]:
        if not self._risk.can_open_position:
            return False, "Max open positions reached"
        return True, ""

    def _check_duplicate(self, security_id: str) -> tuple[bool, str]:
        if (
            self._last_order_security_id == security_id
            and self._last_order_time
            and (datetime.now() - self._last_order_time).total_seconds() < 60
        ):
            return False, f"Duplicate order for {security_id} within 60s"
        return True, ""

    def _check_funds(self, premium: float) -> tuple[bool, str]:
        from nifty_trader.constants import NIFTY_LOT_SIZE
        cost = premium * NIFTY_LOT_SIZE
        if cost > self._cfg.risk.capital:
            return False, f"Premium cost {cost:.0f} exceeds capital {self._cfg.risk.capital:.0f}"
        return True, ""

    def validate_spread(
        self,
        short_security_id: str,
        long_security_id: str,
        net_credit: float,
        spread_width: float,
    ) -> tuple[bool, str]:
        """Run pre-order checks for a credit spread."""
        checks = [
            self._check_time_window(),
            self._check_daily_loss(),
            self._check_position_limit(),
            self._check_duplicate(short_security_id),
            self._check_spread_margin(net_credit, spread_width),
        ]
        for ok, reason in checks:
            if not ok:
                logger.warning("Spread validation failed: %s", reason)
                return False, reason

        self._last_order_security_id = short_security_id
        self._last_order_time = datetime.now()
        return True, "All spread checks passed"

    def _check_spread_margin(self, net_credit: float, spread_width: float) -> tuple[bool, str]:
        from nifty_trader.constants import NIFTY_LOT_SIZE
        max_loss_per_lot = (spread_width - net_credit) * NIFTY_LOT_SIZE
        risk_limit = self._cfg.risk.capital * self._cfg.risk.risk_per_trade_pct / 100
        if max_loss_per_lot > risk_limit:
            return False, (
                f"Spread max loss/lot {max_loss_per_lot:.0f} exceeds "
                f"risk limit {risk_limit:.0f}"
            )
        return True, ""
