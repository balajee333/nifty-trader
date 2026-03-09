"""WebSocket MarketFeed wrapper with heartbeat monitoring."""

from __future__ import annotations

import asyncio
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

    Uses DhanFeed (v2) which provides:
      - DhanFeed(client_id, access_token, instruments, version='v2') to connect
      - get_data() to receive next tick (calls ws.recv())
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
        self._ws_thread: threading.Thread | None = None
        self._subscriptions: list[tuple[int, str, int]] = []  # (exchange_code, security_id, feed_type)
        self._latest_ltp: dict[str, float] = {}
        self._ltp_timestamp: dict[str, float] = {}  # security_id → monotonic time
        self._LTP_STALE_SEC = 30  # reject LTP older than this

    @property
    def latest_ltp(self) -> dict[str, float]:
        return self._latest_ltp

    def get_ltp(self, security_id: str) -> float | None:
        ltp = self._latest_ltp.get(security_id)
        if ltp is None:
            return None
        ts = self._ltp_timestamp.get(security_id, 0)
        if time.monotonic() - ts > self._LTP_STALE_SEC:
            return None  # stale — force REST fallback
        return ltp

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
        """Start the WebSocket feed with a receive loop in a background thread."""
        if self._running:
            return

        self._running = True
        self._last_tick_time = time.monotonic()

        try:
            from dhanhq.marketfeed import DhanFeed

            self._feed = DhanFeed(
                client_id=self._dhan.client_id,
                access_token=self._dhan.access_token,
                instruments=self._subscriptions,
                version="v2",
            )

            # Run connect + recv loop in a dedicated thread with its own event loop
            self._ws_thread = threading.Thread(target=self._run_ws_loop, daemon=True)
            self._ws_thread.start()

        except Exception:
            logger.exception("Failed to start MarketFeed")
            self._running = False

    def _run_ws_loop(self):
        """Connect, then continuously receive and process ticks."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Replace the feed's event loop with ours so get_data() works
        self._feed.loop = loop

        try:
            # Connect + subscribe
            loop.run_until_complete(self._feed.connect())
            logger.info("MarketFeed WebSocket connected (v2)")

            # Continuous receive loop
            loop.run_until_complete(self._recv_loop())
        except Exception:
            logger.exception("MarketFeed WebSocket error")
        finally:
            self._running = False
            loop.close()

    async def _recv_loop(self):
        """Continuously receive data from the WebSocket."""
        while self._running:
            try:
                data = await asyncio.wait_for(
                    self._feed.ws.recv(),
                    timeout=self._heartbeat_timeout,
                )
                parsed = self._feed.process_data(data)
                if parsed:
                    self._last_tick_time = time.monotonic()
                    self._process_tick(parsed)
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - self._last_tick_time
                logger.warning("No tick for %.0fs — feed may be disconnected", elapsed)
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("WebSocket recv error: %s", exc)
                await asyncio.sleep(1)

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
                self._ltp_timestamp[sec_id] = time.monotonic()
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
