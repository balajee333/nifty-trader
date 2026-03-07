"""Super Order API — atomic entry + target + SL in a single call."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nifty_trader.constants import ExchangeSegment, ProductType, TransactionType
from nifty_trader.journal.database import TradeJournal
from nifty_trader.orders.tracker import OrderRecord, OrderTracker

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


class SuperOrderManager:
    """Manages DhanHQ Super Orders for atomic entry+SL+target."""

    def __init__(
        self,
        dhan: DhanHQ,
        tracker: OrderTracker,
        journal: TradeJournal,
        paper_mode: bool = True,
    ):
        self._dhan = dhan
        self._tracker = tracker
        self._journal = journal
        self._paper_mode = paper_mode
        self._next_paper_id = 5000

    def place_super_order(
        self,
        security_id: str,
        quantity: int,
        sl_price: float,
        target_price: float,
        trailing_jump: float = 0.0,
    ) -> str | None:
        """Place a Super Order with entry, SL, and target legs.

        Returns the order_id or None on failure.
        """
        if self._tracker.is_duplicate(security_id):
            logger.warning("Duplicate super order blocked for %s", security_id)
            return None

        if self._paper_mode:
            return self._paper_super_order(security_id, quantity, sl_price, target_price)

        try:
            resp = self._dhan.place_super_order(
                security_id=security_id,
                exchange_segment=ExchangeSegment.NSE_FNO,
                transaction_type=TransactionType.BUY,
                quantity=quantity,
                order_type="MARKET",
                product_type=ProductType.INTRADAY,
                validity="DAY",
                price=0,
                trigger_price=0,
                sl_value=sl_price,
                target_value=target_price,
                trailing_jump=trailing_jump if trailing_jump > 0 else None,
            )
        except Exception:
            logger.exception("Super Order placement failed")
            return None

        if not resp:
            return None

        status = resp.get("status", "")
        order_id = str(resp.get("data", {}).get("orderId", ""))

        if status == "success" and order_id:
            record = OrderRecord(
                order_id=order_id,
                security_id=security_id,
                transaction_type="BUY",
                status="PENDING",
                quantity=quantity,
            )
            self._tracker.register(record)
            self._journal.log_order(
                order_id=order_id,
                security_id=security_id,
                transaction_type="BUY",
                order_type="SUPER",
                price=0,
                quantity=quantity,
                status="PENDING",
                raw_response=json.dumps(resp),
            )
            logger.info(
                "Super Order placed: %s qty=%d SL=%.2f TGT=%.2f",
                security_id, quantity, sl_price, target_price,
            )
            return order_id

        logger.warning("Super Order failed: %s", resp)
        return None

    def _paper_super_order(
        self,
        security_id: str,
        quantity: int,
        sl_price: float,
        target_price: float,
    ) -> str:
        order_id = f"PAPER-SUPER-{self._next_paper_id}"
        self._next_paper_id += 1
        record = OrderRecord(
            order_id=order_id,
            security_id=security_id,
            transaction_type="BUY",
            status="PAPER_FILLED",
            quantity=quantity,
        )
        self._tracker.register(record)
        self._journal.log_order(
            order_id=order_id,
            security_id=security_id,
            transaction_type="BUY",
            order_type="SUPER",
            price=0,
            quantity=quantity,
            status="PAPER_FILLED",
        )
        logger.info(
            "[PAPER] Super Order: %s qty=%d SL=%.2f TGT=%.2f",
            security_id, quantity, sl_price, target_price,
        )
        return order_id
