"""Option chain fetcher with strict rate limiting."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from nifty_trader.constants import NIFTY_SECURITY_ID, ExchangeSegment, OptionType

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


@dataclass
class OptionContract:
    security_id: str
    strike_price: float
    option_type: OptionType
    expiry: str
    ltp: float
    bid: float
    ask: float
    volume: int
    oi: int
    delta: float
    theta: float
    gamma: float
    vega: float
    iv: float

    @property
    def spread(self) -> float:
        if self.bid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.bid * 100

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2


class OptionChainFetcher:
    """Fetches option chain data with 3-second rate limiting per unique request."""

    def __init__(self, dhan: DhanHQ, min_interval_sec: float = 3.0, exchange_segment: str = "NSE_FNO"):
        self._dhan = dhan
        self._min_interval = min_interval_sec
        self._exchange_segment = exchange_segment
        self._last_fetch: float = 0.0
        self._cached_expiries: list[str] = []
        self._expiry_fetched_at: float = 0.0

    def _rate_limit(self):
        elapsed = time.monotonic() - self._last_fetch
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_fetch = time.monotonic()

    def get_expiries(self, security_id: str = NIFTY_SECURITY_ID) -> list[str]:
        """Fetch available expiry dates for NIFTY options."""
        # Cache expiries for 5 minutes
        if self._cached_expiries and (time.monotonic() - self._expiry_fetched_at) < 300:
            return self._cached_expiries

        self._rate_limit()
        try:
            resp = self._dhan.expiry_list(
                under_security_id=int(security_id),
                under_exchange_segment=self._exchange_segment,
            )
            if resp and resp.get("status") == "success":
                data = resp.get("data", {})
                # DhanHQ v2 nests the list inside data.data
                if isinstance(data, dict):
                    expiry_list = data.get("data", [])
                elif isinstance(data, list):
                    expiry_list = data
                else:
                    expiry_list = []
                if isinstance(expiry_list, list):
                    self._cached_expiries = sorted(expiry_list)
                    self._expiry_fetched_at = time.monotonic()
        except Exception:
            logger.exception("Failed to fetch expiry list")

        return self._cached_expiries

    def nearest_weekly_expiry(self, security_id: str = NIFTY_SECURITY_ID) -> str | None:
        """Get the nearest weekly expiry date string."""
        expiries = self.get_expiries(security_id)
        if not expiries:
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        future = [e for e in expiries if e >= today]
        return future[0] if future else None

    def get_chain(
        self,
        expiry: str,
        security_id: str = NIFTY_SECURITY_ID,
    ) -> list[OptionContract]:
        """Fetch full option chain for given expiry."""
        self._rate_limit()
        try:
            resp = self._dhan.option_chain(
                under_security_id=int(security_id),
                under_exchange_segment=self._exchange_segment,
                expiry=expiry,
            )
        except Exception:
            logger.exception("Failed to fetch option chain")
            return []

        if not resp or resp.get("status") != "success":
            logger.warning("Option chain API non-success: %s", resp)
            return []

        raw_data = resp.get("data", {})
        # DhanHQ v2: data is nested — {"data": {"last_price": ..., "oc": {strike: {ce: ..., pe: ...}}}}
        if isinstance(raw_data, dict):
            inner = raw_data.get("data", raw_data)
            if isinstance(inner, dict):
                oc = inner.get("oc", {})
            else:
                oc = {}
        elif isinstance(raw_data, list):
            # Legacy flat list format
            oc = None
        else:
            return []

        contracts: list[OptionContract] = []

        if oc is not None:
            # v2 dict format: {strike_str: {"ce": {...}, "pe": {...}}}
            for strike_str, sides in oc.items():
                try:
                    strike_price = float(strike_str)
                except (ValueError, TypeError):
                    continue
                for side in ("ce", "pe"):
                    entry = sides.get(side)
                    if not entry:
                        continue
                    greeks = entry.get("greeks", {})
                    try:
                        contracts.append(OptionContract(
                            security_id=str(entry.get("security_id", "")),
                            strike_price=strike_price,
                            option_type=OptionType.CALL if side == "ce" else OptionType.PUT,
                            expiry=expiry,
                            ltp=float(entry.get("last_price", 0)),
                            bid=float(entry.get("top_bid_price", 0)),
                            ask=float(entry.get("top_ask_price", 0)),
                            volume=int(entry.get("volume", 0)),
                            oi=int(entry.get("oi", 0)),
                            delta=float(greeks.get("delta", 0)),
                            theta=float(greeks.get("theta", 0)),
                            gamma=float(greeks.get("gamma", 0)),
                            vega=float(greeks.get("vega", 0)),
                            iv=float(entry.get("implied_volatility", 0)),
                        ))
                    except (ValueError, TypeError):
                        continue
        else:
            # Legacy flat list format
            for row in raw_data:
                for side in ("ce", "pe"):
                    entry = row.get(side)
                    if not entry:
                        continue
                    try:
                        contracts.append(OptionContract(
                            security_id=str(entry.get("security_id", "")),
                            strike_price=float(row.get("strike_price", 0)),
                            option_type=OptionType.CALL if side == "ce" else OptionType.PUT,
                            expiry=expiry,
                            ltp=float(entry.get("ltp", 0)),
                            bid=float(entry.get("bid", 0)),
                            ask=float(entry.get("ask", 0)),
                            volume=int(entry.get("volume", 0)),
                            oi=int(entry.get("oi", 0)),
                            delta=float(entry.get("delta", 0)),
                            theta=float(entry.get("theta", 0)),
                            gamma=float(entry.get("gamma", 0)),
                            vega=float(entry.get("vega", 0)),
                            iv=float(entry.get("iv", 0)),
                        ))
                    except (ValueError, TypeError):
                        continue

        return contracts
