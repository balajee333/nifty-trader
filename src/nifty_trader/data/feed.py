"""WebSocket MarketFeed wrapper with heartbeat monitoring."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

from nifty_trader.constants import NIFTY_SECURITY_ID, ExchangeSegment

if TYPE_CHECKING:
    from dhanhq import dhanhq as DhanHQ

logger = logging.getLogger(__name__)


class MarketFeedManager:
    """Manages DhanHQ WebSocket market feed with heartbeat and reconnect.

    Uses DhanFeed (v2.0.x) which provides:
      - DhanFeed(client_id, access_token, instruments) to connect
      - get_data() to poll latest tick
      - subscribe_symbols() / unsubscribe_symbols() for dynamic subscriptions
    Instruments format: list of (exchange_segment_code, security_id, feed_type)
    where feed_type: Ticker=15, Quote=17, Full=21
    """

    TICKER = 15
    QUOTE = 17

    def __init__(
        self,
        dhan: DhanHQ,
        on_tick: Callable[[dict], None] | None = None,
        heartbeat_timeout: int = 15,
    ):
        self._dhan = dhan
        self._on_tick = on_tick
        self._heartbeat_timeout = heartbeat_timeout
        self._last_tick_time: float = 0.0
        self._running = False
        self._feed = None
        self._poll_thread: threading.Thread | None = None
        self._subscriptions: list[tuple[int, str, int]] = []  # (exchange_code, security_id, feed_type)
        self._latest_ltp: dict[str, float] = {}

    @property
    def latest_ltp(self) -> dict[str, float]:
        return self._latest_ltp

    def get_ltp(self, security_id: str) -> float | None:
        return self._latest_ltp.get(security_id)

    def subscribe_nifty_spot(self):
        """Subscribe to NIFTY 50 index quote (backward-compat wrapper)."""
        self.subscribe_spot()

    def subscribe_spot(self, feed_code: int | None = None, security_id: str = NIFTY_SECURITY_ID):
        """Subscribe to spot/index quote. feed_code: 0=IDX, 5=MCX."""
        if feed_code is None:
            from dhanhq.marketfeed import IDX
            feed_code = IDX
        self._subscriptions.append((feed_code, security_id, self.QUOTE))

    def subscribe_option(self, security_id: str, feed_code: int | None = None):
        """Subscribe to an option contract for LTP."""
        if feed_code is None:
            from dhanhq.marketfeed import NSE_FNO
            feed_code = NSE_FNO
        self._subscriptions.append((feed_code, security_id, self.QUOTE))

    def start(self):
        """Start the WebSocket feed and polling thread."""
        if self._running:
            return

        self._running = True
        self._last_tick_time = time.monotonic()

        try:
            from dhanhq.marketfeed import DhanFeed

            # DhanFeed expects instruments as list of (exchange_code, security_id, feed_type) tuples
            self._feed = DhanFeed(
                client_id=self._dhan.client_id,
                access_token=self._dhan.access_token,
                instruments=self._subscriptions,
            )

            # Start WebSocket connection in background
            ws_thread = threading.Thread(target=self._run_feed, daemon=True)
            ws_thread.start()

            # Start polling thread to fetch data
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()

        except Exception:
            logger.exception("Failed to start MarketFeed")
            self._running = False

    def _run_feed(self):
        """Run the WebSocket event loop."""
        try:
            self._feed.run_forever()
        except Exception:
            logger.exception("MarketFeed WebSocket error")
            self._running = False

    def _poll_loop(self):
        """Poll for new tick data periodically."""
        import asyncio

        loop = asyncio.new_event_loop()
        while self._running:
            try:
                # get_data() internally calls run_until_complete on an async method
                # but it may fail if the feed's loop is already running in another thread.
                # Use the feed's data attribute directly if available.
                if hasattr(self._feed, 'data') and self._feed.data:
                    data = self._feed.data
                    self._feed.data = ""
                    if data:
                        self._last_tick_time = time.monotonic()
                        self._process_tick(data)
            except Exception:
                pass  # Feed not ready yet or disconnected

            # Check heartbeat
            elapsed = time.monotonic() - self._last_tick_time
            if elapsed > self._heartbeat_timeout:
                logger.warning("No tick for %.0fs — feed may be disconnected", elapsed)

            time.sleep(1)
        loop.close()

    def stop(self):
        self._running = False
        if self._feed:
            try:
                self._feed.close_connection()
            except Exception:
                try:
                    self._feed.disconnect()
                except Exception:
                    pass

    def _process_tick(self, message):
        """Extract LTP from tick data and call user callback."""
        if isinstance(message, dict):
            sec_id = str(message.get("security_id", message.get("sid", "")))
            ltp = message.get("LTP", message.get("ltp", 0))
            if sec_id and ltp:
                self._latest_ltp[sec_id] = float(ltp)
                if self._on_tick:
                    self._on_tick(message)
        elif isinstance(message, list):
            for item in message:
                if isinstance(item, dict):
                    self._process_tick(item)

    def fetch_ltp_rest(self, security_id: str, exchange_segment: str = ExchangeSegment.NSE_FNO) -> float | None:
        """Fallback REST-based LTP fetch when WebSocket is down."""
        try:
            resp = self._dhan.get_market_quote(
                security_id=security_id,
                exchange_segment=exchange_segment,
            )
            if resp and resp.get("status") == "success":
                data = resp.get("data", {})
                ltp = data.get("ltp", data.get("LTP"))
                return float(ltp) if ltp else None
        except Exception:
            logger.exception("REST LTP fetch failed for %s", security_id)
        return None
