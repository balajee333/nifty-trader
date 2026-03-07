"""Order ID tracking and duplicate prevention."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class OrderRecord:
    order_id: str
    security_id: str
    transaction_type: str
    status: str
    placed_at: datetime = field(default_factory=datetime.now)
    filled_price: float = 0.0
    quantity: int = 0


class OrderTracker:
    """Tracks order IDs and prevents duplicates."""

    def __init__(self):
        self._orders: dict[str, OrderRecord] = {}
        self._pending: set[str] = set()
        self._consecutive_rejections: int = 0

    def register(self, record: OrderRecord):
        self._orders[record.order_id] = record
        if record.status in ("PENDING", "TRANSIT"):
            self._pending.add(record.order_id)
        logger.info("Registered order %s (%s)", record.order_id, record.status)

    def update_status(self, order_id: str, status: str, filled_price: float = 0.0):
        if order_id in self._orders:
            self._orders[order_id].status = status
            if filled_price > 0:
                self._orders[order_id].filled_price = filled_price
            self._pending.discard(order_id)

            if status == "REJECTED":
                self._consecutive_rejections += 1
            else:
                self._consecutive_rejections = 0

    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def is_duplicate(self, security_id: str, window_sec: float = 60) -> bool:
        """Check if there's a recent pending or recently filled order for the same security."""
        now = datetime.now()
        # Check pending orders
        for oid in self._pending:
            rec = self._orders.get(oid)
            if rec and rec.security_id == security_id:
                return True
        # Check recently filled/paper orders within time window
        for rec in self._orders.values():
            if (
                rec.security_id == security_id
                and rec.transaction_type == "BUY"
                and (now - rec.placed_at).total_seconds() < window_sec
            ):
                return True
        return False

    @property
    def consecutive_rejections(self) -> int:
        return self._consecutive_rejections

    def get_order(self, order_id: str) -> OrderRecord | None:
        return self._orders.get(order_id)

    def reset(self):
        self._orders.clear()
        self._pending.clear()
        self._consecutive_rejections = 0
