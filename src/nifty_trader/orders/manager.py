"""Order placement, modification, cancellation via DhanHQ."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nifty_trader.constants import (
    ExchangeSegment,
    OrderType,
    ProductType,
    TransactionType,
    Validity,
)
from nifty_trader.journal.database import TradeJournal
from nifty_trader.orders.tracker import OrderRecord, OrderTracker

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


class OrderManager:
    """Handles order lifecycle with DhanHQ API."""

    def __init__(
        self,
        dhan: DhanHQ,
        tracker: OrderTracker,
        journal: TradeJournal,
        paper_mode: bool = True,
        exchange_segment: str = "NSE_FNO",
    ):
        self._dhan = dhan
        self._tracker = tracker
        self._journal = journal
        self._paper_mode = paper_mode
        self._exchange_segment = exchange_segment
        self._next_paper_id = 1000

    def place_market_buy(
        self,
        security_id: str,
        quantity: int,
    ) -> str | None:
        """Place a MARKET BUY order. Returns order_id or None."""
        if self._tracker.is_duplicate(security_id):
            logger.warning("Duplicate order blocked for %s", security_id)
            return None

        if self._paper_mode:
            return self._paper_order(security_id, quantity, "BUY", "MARKET")

        try:
            resp = self._dhan.place_order(
                security_id=security_id,
                exchange_segment=self._exchange_segment,
                transaction_type=TransactionType.BUY,
                quantity=quantity,
                order_type=OrderType.MARKET,
                product_type=ProductType.INTRADAY,
                validity=Validity.DAY,
                price=0,
            )
        except Exception:
            logger.exception("Order placement failed for %s", security_id)
            return None

        order_id = self._process_response(resp, security_id, quantity, "BUY", "MARKET")
        return order_id

    def place_sl_order(
        self,
        security_id: str,
        quantity: int,
        trigger_price: float,
    ) -> str | None:
        """Place a SL-MARKET SELL order for stop loss."""
        if self._paper_mode:
            return self._paper_order(security_id, quantity, "SELL", "SL-M", trigger_price)

        try:
            resp = self._dhan.place_order(
                security_id=security_id,
                exchange_segment=self._exchange_segment,
                transaction_type=TransactionType.SELL,
                quantity=quantity,
                order_type=OrderType.SL_MARKET,
                product_type=ProductType.INTRADAY,
                validity=Validity.DAY,
                price=0,
                trigger_price=trigger_price,
            )
        except Exception:
            logger.exception("SL order placement failed")
            return None

        return self._process_response(resp, security_id, quantity, "SELL", "SL-M")

    def place_market_sell(
        self,
        security_id: str,
        quantity: int,
    ) -> str | None:
        """Place a MARKET SELL order for exit."""
        if self._paper_mode:
            return self._paper_order(security_id, quantity, "SELL", "MARKET")

        try:
            resp = self._dhan.place_order(
                security_id=security_id,
                exchange_segment=self._exchange_segment,
                transaction_type=TransactionType.SELL,
                quantity=quantity,
                order_type=OrderType.MARKET,
                product_type=ProductType.INTRADAY,
                validity=Validity.DAY,
                price=0,
            )
        except Exception:
            logger.exception("Exit order failed")
            return None

        return self._process_response(resp, security_id, quantity, "SELL", "MARKET")

    def modify_sl_trigger(self, order_id: str, new_trigger: float) -> bool:
        """Modify the trigger price of an existing SL order."""
        if self._paper_mode:
            logger.info("[PAPER] Modified SL order %s trigger to %.2f", order_id, new_trigger)
            self._tracker.update_status(order_id, "MODIFIED")
            return True

        try:
            resp = self._dhan.modify_order(
                order_id=order_id,
                order_type=OrderType.SL_MARKET,
                trigger_price=new_trigger,
            )
            if resp and resp.get("status") == "success":
                logger.info("SL modified: order=%s trigger=%.2f", order_id, new_trigger)
                return True
            logger.warning("SL modify failed: %s", resp)
            return False
        except Exception:
            logger.exception("SL modify exception")
            return False

    def cancel_order(self, order_id: str) -> bool:
        if self._paper_mode:
            logger.info("[PAPER] Cancelled order %s", order_id)
            self._tracker.update_status(order_id, "CANCELLED")
            return True

        try:
            resp = self._dhan.cancel_order(order_id=order_id)
            if resp and resp.get("status") == "success":
                self._tracker.update_status(order_id, "CANCELLED")
                return True
            return False
        except Exception:
            logger.exception("Cancel order failed")
            return False

    def cancel_all(self) -> int:
        """Cancel all pending orders. Returns count cancelled."""
        if self._paper_mode:
            logger.info("[PAPER] Cancel all pending orders")
            return 0
        try:
            resp = self._dhan.cancel_order(order_id="all")
            return 1 if resp else 0
        except Exception:
            logger.exception("Cancel all failed")
            return 0

    def _process_response(
        self,
        resp: dict,
        security_id: str,
        quantity: int,
        txn_type: str,
        order_type: str,
    ) -> str | None:
        if not resp:
            return None

        status = resp.get("status", "")
        order_id = str(resp.get("data", {}).get("orderId", resp.get("orderId", "")))

        if status == "success" and order_id:
            record = OrderRecord(
                order_id=order_id,
                security_id=security_id,
                transaction_type=txn_type,
                status="PENDING",
                quantity=quantity,
            )
            self._tracker.register(record)
            self._journal.log_order(
                order_id=order_id,
                security_id=security_id,
                transaction_type=txn_type,
                order_type=order_type,
                price=0,
                quantity=quantity,
                status="PENDING",
                raw_response=json.dumps(resp),
            )
            logger.info("Order placed: %s %s %s qty=%d", txn_type, order_type, security_id, quantity)
            return order_id

        logger.warning("Order failed: %s", resp)
        self._tracker._consecutive_rejections += 1
        return None

    def place_spread_entry(
        self,
        short_security_id: str,
        long_security_id: str,
        quantity: int,
    ) -> tuple[str | None, str | None]:
        """Place a credit spread entry: SELL short leg, BUY long leg.

        Returns (short_order_id, long_order_id). If long leg fails, rolls back
        the short leg to avoid a naked position.
        """
        # SELL short leg first (collect credit)
        short_oid = self._place_order(
            short_security_id, quantity, TransactionType.SELL, OrderType.MARKET,
        )
        if not short_oid:
            logger.warning("Short leg order failed — aborting spread entry")
            return None, None

        # BUY long leg (protection)
        long_oid = self._place_order(
            long_security_id, quantity, TransactionType.BUY, OrderType.MARKET,
        )
        if not long_oid:
            # ROLLBACK: buy back the short leg to avoid naked position
            logger.warning("Long leg failed — rolling back short leg %s", short_oid)
            rollback_oid = self._place_order(
                short_security_id, quantity, TransactionType.BUY, OrderType.MARKET,
            )
            if rollback_oid:
                logger.info("Rollback successful: bought back short leg %s", rollback_oid)
            else:
                logger.critical("ROLLBACK FAILED — naked short position on %s!", short_security_id)
            return None, None

        return short_oid, long_oid

    def place_spread_exit(
        self,
        short_security_id: str,
        long_security_id: str,
        quantity: int,
    ) -> tuple[str | None, str | None]:
        """Exit a credit spread: BUY back short leg, SELL long leg."""
        # BUY back short leg
        buy_back_oid = self._place_order(
            short_security_id, quantity, TransactionType.BUY, OrderType.MARKET,
        )
        # SELL long leg
        sell_long_oid = self._place_order(
            long_security_id, quantity, TransactionType.SELL, OrderType.MARKET,
        )
        return buy_back_oid, sell_long_oid

    def _place_order(
        self,
        security_id: str,
        quantity: int,
        txn_type: TransactionType,
        order_type: OrderType,
        trigger_price: float = 0,
    ) -> str | None:
        """Shared helper for placing a single order."""
        if self._paper_mode:
            return self._paper_order(security_id, quantity, txn_type.value, order_type.value, trigger_price)

        try:
            resp = self._dhan.place_order(
                security_id=security_id,
                exchange_segment=self._exchange_segment,
                transaction_type=txn_type,
                quantity=quantity,
                order_type=order_type,
                product_type=ProductType.INTRADAY,
                validity=Validity.DAY,
                price=0,
                trigger_price=trigger_price if trigger_price else 0,
            )
        except Exception:
            logger.exception("Order placement failed for %s %s", txn_type.value, security_id)
            return None

        return self._process_response(resp, security_id, quantity, txn_type.value, order_type.value)

    def _paper_order(
        self,
        security_id: str,
        quantity: int,
        txn_type: str,
        order_type: str,
        trigger_price: float = 0,
    ) -> str:
        order_id = f"PAPER-{self._next_paper_id}"
        self._next_paper_id += 1
        record = OrderRecord(
            order_id=order_id,
            security_id=security_id,
            transaction_type=txn_type,
            status="PAPER_FILLED",
            quantity=quantity,
        )
        self._tracker.register(record)
        self._journal.log_order(
            order_id=order_id,
            security_id=security_id,
            transaction_type=txn_type,
            order_type=order_type,
            price=trigger_price,
            quantity=quantity,
            status="PAPER_FILLED",
        )
        logger.info(
            "[PAPER] %s %s %s qty=%d trigger=%.2f",
            txn_type, order_type, security_id, quantity, trigger_price,
        )
        return order_id
