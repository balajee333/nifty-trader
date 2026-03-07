"""Historical candle data fetcher with rate limiting."""

from __future__ import annotations

import time
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from nifty_trader.constants import NIFTY_SECURITY_ID, ExchangeSegment

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, max_per_sec: int = 5):
        self._min_interval = 1.0 / max_per_sec
        self._last_call = 0.0

    def wait(self):
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


class HistoricalDataFetcher:
    """Fetches intraday and daily candles from DhanHQ."""

    def __init__(self, dhan: DhanHQ, rate_limit_per_sec: int = 5):
        self._dhan = dhan
        self._limiter = RateLimiter(rate_limit_per_sec)

    def get_intraday_5min(
        self,
        security_id: str = NIFTY_SECURITY_ID,
        exchange: str = ExchangeSegment.IDX_I,
        lookback_days: int = 5,
    ) -> pd.DataFrame:
        """Fetch 5-minute intraday candles."""
        from_date = datetime.now() - timedelta(days=lookback_days)
        to_date = datetime.now()

        self._limiter.wait()
        try:
            resp = self._dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange,
                instrument_type="INDEX",
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
            )
        except Exception:
            logger.exception("Failed to fetch intraday data")
            return pd.DataFrame()

        return self._parse_candles(resp)

    def get_daily(
        self,
        security_id: str = NIFTY_SECURITY_ID,
        exchange: str = ExchangeSegment.IDX_I,
        lookback_days: int = 60,
    ) -> pd.DataFrame:
        """Fetch daily candles."""
        from_date = datetime.now() - timedelta(days=lookback_days)
        to_date = datetime.now()

        self._limiter.wait()
        try:
            resp = self._dhan.historical_daily_data(
                security_id=security_id,
                exchange_segment=exchange,
                instrument_type="INDEX",
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
            )
        except Exception:
            logger.exception("Failed to fetch daily data")
            return pd.DataFrame()

        return self._parse_candles(resp)

    @staticmethod
    def _parse_candles(resp: dict) -> pd.DataFrame:
        """Parse DhanHQ candle response into a DataFrame."""
        if not resp or resp.get("status") != "success":
            logger.warning("Candle API returned non-success: %s", resp)
            return pd.DataFrame()

        data = resp.get("data", {})
        if not data:
            return pd.DataFrame()

        # Handle timestamp format — may be ISO strings or Unix epoch
        raw_ts = data.get("start_Time", data.get("timestamp", []))
        if raw_ts and isinstance(raw_ts[0], (int, float)):
            timestamps = pd.to_datetime(raw_ts, unit="s")
        else:
            timestamps = pd.to_datetime(raw_ts)

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": pd.to_numeric(data.get("open", []), errors="coerce"),
            "high": pd.to_numeric(data.get("high", []), errors="coerce"),
            "low": pd.to_numeric(data.get("low", []), errors="coerce"),
            "close": pd.to_numeric(data.get("close", []), errors="coerce"),
            "volume": pd.to_numeric(data.get("volume", []), errors="coerce"),
        })
        df.dropna(subset=["close"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df
