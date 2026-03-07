"""VENOM backtester engine — day-by-day replay of the full strategy."""

from __future__ import annotations

import logging
import math
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from nifty_trader.backtest.simulator import PremiumSimulator
from nifty_trader.config import AppConfig, StrategyConfig, load_config
from nifty_trader.constants import (
    Direction,
    ExchangeSegment,
    NIFTY_SECURITY_ID,
)
from nifty_trader.strategy.confluence import ConfluenceResult, evaluate_confluence
from nifty_trader.strategy.levels import LevelDetector
from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, OhlcSignal, SignalType
from nifty_trader.strategy.time_manager import TimeManager, TradingWindow
from nifty_trader.strategy.trail_engine import TrailEngine, TrailState
from nifty_trader.strategy.vix_gate import VixGate, VixMode

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)

# India VIX security ID on DhanHQ
VIX_SECURITY_ID = "26"

# DhanHQ historical API max range is 90 calendar days
_CHUNK_DAYS = 89


# ── Dataclasses ───────────────────────────────────────────────────────


@dataclass
class BacktestConfig:
    start_date: str
    end_date: str
    start_capital: float = 100_000
    lot_size: int = 25
    max_trades_per_day: int = 3


@dataclass
class BacktestTrade:
    date: str
    direction: str
    signal_type: str
    entry_time: str
    entry_premium: float
    exit_time: str
    exit_premium: float
    exit_reason: str
    quantity: int
    pnl: float
    vix: float
    vix_mode: str
    grade: str
    rungs_hit: list = field(default_factory=list)
    peak_premium: float = 0.0
    confluence_score: float = 0.0


@dataclass
class BacktestDaySummary:
    date: str
    trades: list[BacktestTrade]
    daily_pnl: float
    signal_detected: str
    vix: float
    vix_mode: str
    nifty_open: float
    nifty_close: float
    nifty_change_pct: float
    day_type: str
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class BacktestResult:
    config: BacktestConfig
    days: list[BacktestDaySummary]
    total_pnl: float
    total_trades: int
    winners: int
    losers: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_winner: float
    avg_loser: float
    expectancy: float
    best_day: float
    worst_day: float
    equity_curve: list[float]
    monthly_breakdown: dict[str, float] = field(default_factory=dict)
    signal_stats: dict = field(default_factory=dict)
    day_of_week_stats: dict = field(default_factory=dict)
    vix_regime_stats: dict = field(default_factory=dict)
    trail_stats: dict = field(default_factory=dict)


# ── Engine ────────────────────────────────────────────────────────────


class VenomBacktester:
    """Replays the VENOM strategy day-by-day on historical data."""

    def __init__(
        self,
        dhan: DhanHQ,
        config: AppConfig,
        bt_config: BacktestConfig,
    ):
        self._dhan = dhan
        self._cfg = config
        self._bt = bt_config

        vcfg = config.venom

        # Strategy modules (reused from live engine)
        self._ohlc = OhlcSignalDetector(
            index_tolerance_pct=vcfg.ohlc_tolerance_index_pct,
            option_tolerance_abs=vcfg.ohlc_tolerance_option_abs,
        )
        self._vix_gate = VixGate(
            full=vcfg.vix_full,
            selective=vcfg.vix_selective,
            caution=vcfg.vix_caution,
            blocked=vcfg.vix_blocked,
        )
        self._time_mgr = TimeManager(time_stop_minutes=vcfg.time_stop_minutes)
        self._trail = TrailEngine(
            sl_pct=vcfg.sl_percent,
            activation_pct=vcfg.trail_activation_pct,
            trail_distance_pct=vcfg.trail_distance_pct,
            max_profit_pct=vcfg.max_profit_pct,
        )
        self._simulator = PremiumSimulator()

        self._lot_size = bt_config.lot_size
        self._max_trades = bt_config.max_trades_per_day

        # Rate limiter for API calls
        self._last_api_call = 0.0
        self._api_interval = 1.0 / config.data.rate_limit_data_per_sec

    # ── Data fetching ─────────────────────────────────────────────

    def _rate_wait(self):
        now = _time.monotonic()
        elapsed = now - self._last_api_call
        if elapsed < self._api_interval:
            _time.sleep(self._api_interval - elapsed)
        self._last_api_call = _time.monotonic()

    def _fetch_intraday_chunked(
        self,
        start: date,
        end: date,
        security_id: str = NIFTY_SECURITY_ID,
        exchange: str = ExchangeSegment.IDX_I,
        instrument_type: str = "INDEX",
    ) -> pd.DataFrame:
        """Fetch 5-min intraday candles in 90-day chunks."""
        frames = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
            self._rate_wait()
            try:
                resp = self._dhan.intraday_minute_data(
                    security_id=security_id,
                    exchange_segment=exchange,
                    instrument_type=instrument_type,
                    from_date=chunk_start.strftime("%Y-%m-%d"),
                    to_date=chunk_end.strftime("%Y-%m-%d"),
                )
                df = self._parse_candles(resp)
                if not df.empty:
                    frames.append(df)
            except Exception:
                logger.exception(
                    "Failed to fetch intraday chunk %s → %s",
                    chunk_start, chunk_end,
                )
            chunk_start = chunk_end + timedelta(days=1)

        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined.sort_values("timestamp", inplace=True)
        combined.reset_index(drop=True, inplace=True)
        return combined

    def _fetch_daily_chunked(
        self,
        start: date,
        end: date,
        security_id: str = NIFTY_SECURITY_ID,
        exchange: str = ExchangeSegment.IDX_I,
        instrument_type: str = "INDEX",
    ) -> pd.DataFrame:
        """Fetch daily candles in 90-day chunks."""
        frames = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=_CHUNK_DAYS), end)
            self._rate_wait()
            try:
                resp = self._dhan.historical_daily_data(
                    security_id=security_id,
                    exchange_segment=exchange,
                    instrument_type=instrument_type,
                    from_date=chunk_start.strftime("%Y-%m-%d"),
                    to_date=chunk_end.strftime("%Y-%m-%d"),
                )
                df = self._parse_candles(resp)
                if not df.empty:
                    frames.append(df)
            except Exception:
                logger.exception(
                    "Failed to fetch daily chunk %s → %s",
                    chunk_start, chunk_end,
                )
            chunk_start = chunk_end + timedelta(days=1)

        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined.sort_values("timestamp", inplace=True)
        combined.reset_index(drop=True, inplace=True)
        return combined

    @staticmethod
    def _parse_candles(resp: dict) -> pd.DataFrame:
        """Parse DhanHQ candle response into a DataFrame."""
        if not resp or resp.get("status") != "success":
            return pd.DataFrame()
        data = resp.get("data", {})
        if not data:
            return pd.DataFrame()

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

    # ── Day classification ────────────────────────────────────────

    @staticmethod
    def _classify_day(candles: list[dict]) -> str:
        if not candles or len(candles) < 2:
            return "unknown"
        o = candles[0]["open"]
        c = candles[-1]["close"]
        h = max(cd["high"] for cd in candles)
        l = min(cd["low"] for cd in candles)
        body = abs(c - o)
        rng = h - l
        if rng > 0 and body / rng > 0.5:
            return "bullish trending" if c > o else "bearish trending"
        return "choppy"

    # ── Single-day replay ─────────────────────────────────────────

    def _replay_day(
        self,
        day_date: date,
        day_candles: pd.DataFrame,
        daily_df: pd.DataFrame,
        vix_value: float,
    ) -> BacktestDaySummary:
        """Replay VENOM strategy for a single trading day."""
        date_str = day_date.strftime("%Y-%m-%d")

        candle_dicts = day_candles.to_dict("records")
        nifty_open = candle_dicts[0]["open"] if candle_dicts else 0.0
        nifty_close = candle_dicts[-1]["close"] if candle_dicts else 0.0
        nifty_change = ((nifty_close - nifty_open) / nifty_open * 100) if nifty_open else 0.0

        vix_mode = self._vix_gate.get_mode(vix_value)
        day_type = self._classify_day(candle_dicts)

        # VIX gating
        if not self._vix_gate.can_trade(vix_value):
            return BacktestDaySummary(
                date=date_str, trades=[], daily_pnl=0.0,
                signal_detected="BLOCKED", vix=vix_value,
                vix_mode=vix_mode.value, nifty_open=nifty_open,
                nifty_close=nifty_close, nifty_change_pct=nifty_change,
                day_type=day_type, skipped=True,
                skip_reason=f"VIX {vix_value:.1f} ≥ blocked threshold",
            )

        if len(candle_dicts) < 3:
            return BacktestDaySummary(
                date=date_str, trades=[], daily_pnl=0.0,
                signal_detected="NO_DATA", vix=vix_value,
                vix_mode=vix_mode.value, nifty_open=nifty_open,
                nifty_close=nifty_close, nifty_change_pct=nifty_change,
                day_type=day_type, skipped=True,
                skip_reason="Insufficient candles",
            )

        # ── Step 1: O=H/O=L detection from first candle ──
        first = candle_dicts[0]
        sim_opts = self._simulator.simulate_option_ohlc_from_index(
            first["open"], first["high"], first["low"], first["close"],
        )

        signal = self._ohlc.detect(
            first["open"], first["high"], first["low"], first["close"],
            sim_opts["ce_open"], sim_opts["ce_high"],
            sim_opts["ce_low"], sim_opts["ce_close"],
            sim_opts["pe_open"], sim_opts["pe_high"],
            sim_opts["pe_low"], sim_opts["pe_close"],
        )

        if signal.signal_type in (SignalType.WAIT, SignalType.NO_TRADE):
            return BacktestDaySummary(
                date=date_str, trades=[], daily_pnl=0.0,
                signal_detected=signal.signal_type.value,
                vix=vix_value, vix_mode=vix_mode.value,
                nifty_open=nifty_open, nifty_close=nifty_close,
                nifty_change_pct=nifty_change, day_type=day_type,
                skipped=True,
                skip_reason=f"No signal: {signal.reason}",
            )

        direction_str = (
            "BULLISH" if signal.signal_type == SignalType.BUY_CE else "BEARISH"
        )
        signal_label = (
            f"O={'L' if direction_str == 'BULLISH' else 'H'} {direction_str.lower()}"
        )
        if "Partial" in signal.reason:
            signal_label = f"Partial {signal_label}"

        # ── Step 2: Confluence check ──
        # Need enough candles for indicators — use available window
        window_end = min(6, len(day_candles))  # ~30 min of candles
        if window_end < 3:
            window_end = len(day_candles)

        # Build a small DataFrame including some daily lookback for indicators
        # We need prior daily data for level detection
        level_detector = LevelDetector(daily_df) if not daily_df.empty else None

        confluence = None
        if level_detector and window_end >= 3:
            window_df = day_candles.iloc[:window_end].copy()
            try:
                confluence = evaluate_confluence(
                    window_df, level_detector, self._cfg.strategy,
                )
            except Exception:
                logger.debug("Confluence evaluation failed for %s", date_str)

        min_confirms = self._vix_gate.min_confirmations(vix_value)
        if confluence and not confluence.triggered and confluence.score < min_confirms:
            return BacktestDaySummary(
                date=date_str, trades=[], daily_pnl=0.0,
                signal_detected=signal_label,
                vix=vix_value, vix_mode=vix_mode.value,
                nifty_open=nifty_open, nifty_close=nifty_close,
                nifty_change_pct=nifty_change, day_type=day_type,
                skipped=True,
                skip_reason=f"Confluence {confluence.score:.1f} < min {min_confirms}",
            )

        # ── Step 3: Simulate entry + trail ──
        trades = self._simulate_trades(
            candle_dicts, direction_str, signal_label,
            vix_value, vix_mode, date_str, nifty_open,
            confluence,
        )

        daily_pnl = sum(t.pnl for t in trades)

        return BacktestDaySummary(
            date=date_str, trades=trades, daily_pnl=daily_pnl,
            signal_detected=signal_label, vix=vix_value,
            vix_mode=vix_mode.value, nifty_open=nifty_open,
            nifty_close=nifty_close, nifty_change_pct=nifty_change,
            day_type=day_type,
        )

    def _simulate_trades(
        self,
        candles: list[dict],
        direction: str,
        signal_label: str,
        vix: float,
        vix_mode: VixMode,
        date_str: str,
        base_spot: float,
        confluence: ConfluenceResult | None,
    ) -> list[BacktestTrade]:
        """Simulate entry, trail, and exit for a trading day."""
        trades: list[BacktestTrade] = []
        if len(candles) < 2:
            return trades

        # Find entry candle — first candle in an entry-allowed window after signal
        entry_idx = None
        for i, c in enumerate(candles):
            ts = c.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            t = ts.time() if hasattr(ts, "time") else None
            if t is None:
                continue
            window = self._time_mgr.get_window(t)
            if window in (
                TradingWindow.PRIME_ENTRY,
                TradingWindow.MORNING_ENTRY,
                TradingWindow.AFTERNOON_ENTRY,
            ):
                entry_idx = i
                break
            if window == TradingWindow.NO_TRADE:
                continue

        if entry_idx is None:
            # Try second candle if timestamps missing or all pre-market
            entry_idx = 1

        entry_candle = candles[entry_idx]
        entry_spot = entry_candle["open"]
        entry_premium = self._simulator.get_entry_premium(entry_spot, vix)
        entry_ts = entry_candle.get("timestamp", "09:21")

        # Size multiplier from VIX
        size_mult = self._vix_gate.size_multiplier(vix)
        quantity = max(int(self._lot_size * size_mult), self._lot_size)

        # Initialize trail state
        trail_state = self._trail.create_state(entry_premium)

        # Walk through remaining candles
        exit_premium = entry_premium
        exit_reason = "FORCE_EXIT"
        exit_ts = candles[-1].get("timestamp", "15:15")

        for candle in candles[entry_idx + 1:]:
            ts = candle.get("timestamp")
            if ts is None:
                continue

            if isinstance(ts, str):
                try:
                    ts_dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            else:
                ts_dt = ts

            t = ts_dt.time() if hasattr(ts_dt, "time") else None

            # Force exit check
            if t and self._time_mgr.should_force_exit(t):
                exit_premium = self._simulator.premium_at_index_price(
                    candle["close"], base_spot, entry_premium, direction,
                )
                exit_ts = candle.get("timestamp", "15:15")
                exit_reason = "FORCE_EXIT"
                break

            # Skip NO_TRADE zone for monitoring? No — we still monitor open positions
            # Calculate current premium
            current_premium = self._simulator.premium_at_index_price(
                candle["close"], base_spot, entry_premium, direction,
            )

            # Also check intra-candle extremes
            if direction == "BULLISH":
                worst_premium = self._simulator.premium_at_index_price(
                    candle["low"], base_spot, entry_premium, direction,
                )
                best_premium = self._simulator.premium_at_index_price(
                    candle["high"], base_spot, entry_premium, direction,
                )
            else:
                worst_premium = self._simulator.premium_at_index_price(
                    candle["high"], base_spot, entry_premium, direction,
                )
                best_premium = self._simulator.premium_at_index_price(
                    candle["low"], base_spot, entry_premium, direction,
                )

            # Check SL on worst price first
            action = self._trail.update(trail_state, worst_premium)
            if action == "SL_HIT":
                exit_premium = trail_state.sl_price
                exit_ts = candle.get("timestamp", "")
                exit_reason = "SL_HIT"
                break

            # Now check best price for rung hits
            action = self._trail.update(trail_state, best_premium)
            if action == "EXIT_MAX_PROFIT":
                exit_premium = best_premium
                exit_ts = candle.get("timestamp", "")
                exit_reason = "MAX_PROFIT"
                break

            # Update with close price
            action = self._trail.update(trail_state, current_premium)
            if action == "SL_HIT":
                exit_premium = trail_state.sl_price
                exit_ts = candle.get("timestamp", "")
                exit_reason = "SL_HIT"
                break
            if action == "EXIT_MAX_PROFIT":
                exit_premium = current_premium
                exit_ts = candle.get("timestamp", "")
                exit_reason = "MAX_PROFIT"
                break

            # Time stop check
            if t and isinstance(entry_ts, (datetime,)):
                pnl_pct = (current_premium - entry_premium) / entry_premium * 100
                if self._time_mgr.time_stop_hit(entry_ts, ts_dt, pnl_pct):
                    exit_premium = current_premium
                    exit_ts = candle.get("timestamp", "")
                    exit_reason = "TIME_STOP"
                    break

            exit_premium = current_premium
            exit_ts = candle.get("timestamp", "")

        # Compute P&L
        pnl_per_unit = exit_premium - entry_premium
        pnl = pnl_per_unit * quantity

        # Simple grade based on P&L %
        pnl_pct = (pnl_per_unit / entry_premium * 100) if entry_premium > 0 else 0
        if pnl_pct >= 40:
            grade = "A+"
        elif pnl_pct >= 20:
            grade = "A"
        elif pnl_pct >= 5:
            grade = "B"
        elif pnl_pct >= -5:
            grade = "C"
        else:
            grade = "F"

        trades.append(BacktestTrade(
            date=date_str,
            direction=direction,
            signal_type=signal_label,
            entry_time=str(entry_ts),
            entry_premium=round(entry_premium, 2),
            exit_time=str(exit_ts),
            exit_premium=round(exit_premium, 2),
            exit_reason=exit_reason,
            quantity=quantity,
            pnl=round(pnl, 2),
            vix=vix,
            vix_mode=vix_mode.value,
            grade=grade,
            rungs_hit=list(trail_state.rungs_hit),
            peak_premium=round(trail_state.peak_price, 2),
            confluence_score=confluence.score if confluence else 0.0,
        ))

        return trades

    # ── Main run ──────────────────────────────────────────────────

    def run(self, progress_callback=None) -> BacktestResult:
        """Execute the full backtest.

        Args:
            progress_callback: Optional callable(current_day, total_days, date_str)
                               for progress reporting.
        """
        start = datetime.strptime(self._bt.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(self._bt.end_date, "%Y-%m-%d").date()

        logger.info("Fetching Nifty 5-min candles %s → %s", start, end)
        nifty_5min = self._fetch_intraday_chunked(start, end)

        # Fetch daily candles with some lookback for S/R levels
        daily_start = start - timedelta(days=30)
        logger.info("Fetching Nifty daily candles %s → %s", daily_start, end)
        nifty_daily = self._fetch_daily_chunked(daily_start, end)

        # Fetch VIX daily
        logger.info("Fetching VIX daily candles %s → %s", start, end)
        vix_daily = self._fetch_daily_chunked(
            start, end,
            security_id=VIX_SECURITY_ID,
            exchange=ExchangeSegment.IDX_I,
            instrument_type="INDEX",
        )

        # Build VIX lookup by date
        vix_by_date: dict[str, float] = {}
        if not vix_daily.empty:
            for _, row in vix_daily.iterrows():
                d = row["timestamp"]
                if hasattr(d, "strftime"):
                    key = d.strftime("%Y-%m-%d")
                else:
                    key = str(d)[:10]
                vix_by_date[key] = float(row["close"])

        # Identify unique trading days from intraday data
        if nifty_5min.empty:
            logger.warning("No intraday data fetched — empty backtest result")
            return self._empty_result()

        nifty_5min["date"] = nifty_5min["timestamp"].dt.date
        trading_days = sorted(nifty_5min["date"].unique())

        logger.info("Replaying %d trading days", len(trading_days))

        day_summaries: list[BacktestDaySummary] = []
        for i, day_dt in enumerate(trading_days):
            day_str = day_dt.strftime("%Y-%m-%d")
            if progress_callback:
                progress_callback(i + 1, len(trading_days), day_str)

            day_candles = nifty_5min[nifty_5min["date"] == day_dt].copy()
            day_candles.reset_index(drop=True, inplace=True)

            # Get daily data up to this day for level detection
            if not nifty_daily.empty:
                prior_daily = nifty_daily[
                    nifty_daily["timestamp"].dt.date < day_dt
                ].copy()
            else:
                prior_daily = pd.DataFrame()

            # Get VIX for this day
            vix_value = vix_by_date.get(day_str, 15.0)  # default moderate VIX

            summary = self._replay_day(day_dt, day_candles, prior_daily, vix_value)
            day_summaries.append(summary)

        return self._aggregate(day_summaries)

    # ── Aggregation ───────────────────────────────────────────────

    def _aggregate(self, days: list[BacktestDaySummary]) -> BacktestResult:
        """Compute aggregate statistics from day summaries."""
        all_trades: list[BacktestTrade] = []
        for d in days:
            all_trades.extend(d.trades)

        total_pnl = sum(t.pnl for t in all_trades)
        winners = [t for t in all_trades if t.pnl > 0]
        losers = [t for t in all_trades if t.pnl <= 0]
        total_trades = len(all_trades)

        win_rate = (len(winners) / total_trades * 100) if total_trades else 0.0
        avg_winner = (sum(t.pnl for t in winners) / len(winners)) if winners else 0.0
        avg_loser = (sum(t.pnl for t in losers) / len(losers)) if losers else 0.0

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        expectancy = (avg_winner * win_rate / 100 + avg_loser * (1 - win_rate / 100))

        # Equity curve + drawdown
        equity_curve = [self._bt.start_capital]
        for t in all_trades:
            equity_curve.append(equity_curve[-1] + t.pnl)

        peak = self._bt.start_capital
        max_dd = 0.0
        max_dd_pct = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = (dd / peak * 100) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        # Sharpe (annualized, daily returns)
        daily_pnls = [d.daily_pnl for d in days if d.trades]
        if len(daily_pnls) > 1:
            mean_daily = sum(daily_pnls) / len(daily_pnls)
            var = sum((p - mean_daily) ** 2 for p in daily_pnls) / (len(daily_pnls) - 1)
            std_daily = math.sqrt(var) if var > 0 else 1.0
            sharpe = (mean_daily / std_daily) * math.sqrt(252) if std_daily > 0 else 0.0
        else:
            sharpe = 0.0

        # Best / worst day
        all_daily_pnls = [d.daily_pnl for d in days]
        best_day = max(all_daily_pnls) if all_daily_pnls else 0.0
        worst_day = min(all_daily_pnls) if all_daily_pnls else 0.0

        # Monthly breakdown
        monthly: dict[str, float] = {}
        for d in days:
            month_key = d.date[:7]  # YYYY-MM
            monthly[month_key] = monthly.get(month_key, 0.0) + d.daily_pnl

        # Signal stats
        signal_stats: dict[str, dict] = {}
        for t in all_trades:
            key = t.signal_type
            if key not in signal_stats:
                signal_stats[key] = {"trades": 0, "pnl": 0.0, "wins": 0}
            signal_stats[key]["trades"] += 1
            signal_stats[key]["pnl"] += t.pnl
            if t.pnl > 0:
                signal_stats[key]["wins"] += 1

        # Day-of-week stats
        dow_stats: dict[str, dict] = {}
        for d in days:
            try:
                dt = datetime.strptime(d.date, "%Y-%m-%d")
                dow = dt.strftime("%A")
            except ValueError:
                dow = "Unknown"
            if dow not in dow_stats:
                dow_stats[dow] = {"trades": 0, "pnl": 0.0, "wins": 0, "days": 0}
            dow_stats[dow]["days"] += 1
            dow_stats[dow]["trades"] += len(d.trades)
            dow_stats[dow]["pnl"] += d.daily_pnl
            dow_stats[dow]["wins"] += sum(1 for t in d.trades if t.pnl > 0)

        # VIX regime stats
        vix_stats: dict[str, dict] = {}
        for t in all_trades:
            mode = t.vix_mode
            if mode not in vix_stats:
                vix_stats[mode] = {"trades": 0, "pnl": 0.0, "wins": 0}
            vix_stats[mode]["trades"] += 1
            vix_stats[mode]["pnl"] += t.pnl
            if t.pnl > 0:
                vix_stats[mode]["wins"] += 1

        # Trail stats
        total_rungs = sum(len(t.rungs_hit) for t in all_trades)
        risk_free_trades = sum(1 for t in all_trades if 20 in t.rungs_hit)
        trail_stats = {
            "total_rung_hits": total_rungs,
            "risk_free_trades": risk_free_trades,
            "avg_rungs_per_trade": (total_rungs / total_trades) if total_trades else 0,
            "exit_reasons": {},
        }
        for t in all_trades:
            reason = t.exit_reason
            trail_stats["exit_reasons"][reason] = (
                trail_stats["exit_reasons"].get(reason, 0) + 1
            )

        return BacktestResult(
            config=self._bt,
            days=days,
            total_pnl=round(total_pnl, 2),
            total_trades=total_trades,
            winners=len(winners),
            losers=len(losers),
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown=round(max_dd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            avg_winner=round(avg_winner, 2),
            avg_loser=round(avg_loser, 2),
            expectancy=round(expectancy, 2),
            best_day=round(best_day, 2),
            worst_day=round(worst_day, 2),
            equity_curve=equity_curve,
            monthly_breakdown=monthly,
            signal_stats=signal_stats,
            day_of_week_stats=dow_stats,
            vix_regime_stats=vix_stats,
            trail_stats=trail_stats,
        )

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            config=self._bt,
            days=[],
            total_pnl=0.0,
            total_trades=0,
            winners=0,
            losers=0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            avg_winner=0.0,
            avg_loser=0.0,
            expectancy=0.0,
            best_day=0.0,
            worst_day=0.0,
            equity_curve=[self._bt.start_capital],
        )
