"""Publish daily VENOM analysis to GitHub Pages."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # VenomEngine imported only for type checking

logger = logging.getLogger(__name__)


class JournalPublisher:
    """Collects daily engine state and publishes to GitHub Pages."""

    REPO_URL = "https://github.com/balajee333/venom-journal.git"
    BRANCH = "gh-pages"

    def __init__(self, work_dir: str | None = None):
        self._work_dir = Path(work_dir or "/tmp/venom-journal")
        self._day_data: dict | None = None

    def collect_day_data(self, engine) -> dict:
        """Extract daily summary from the running engine."""
        today = datetime.now().strftime("%Y-%m-%d")

        # Parse signal type and detail from engine._ohlc_signal_text
        # Format: "signal_type: detail text" or empty
        signal = "none"
        signal_detail = ""
        if getattr(engine, "_ohlc_signal_text", None):
            parts = engine._ohlc_signal_text.split(": ", 1)
            signal = parts[0].strip().lower().replace(" ", "_")
            signal_detail = parts[1] if len(parts) > 1 else ""

        # Get VIX mode
        vix = getattr(engine, "_vix", 0.0) or 0.0
        vix_mode = ""
        try:
            vix_mode = engine.vix_gate.get_mode(vix).value
        except Exception:
            pass

        # Get index prices from feed or historical
        nifty_open = nifty_close = nifty_change_pct = 0.0
        index_ohlc = None
        try:
            df = engine.hist_fetcher.get_intraday_5min(
                security_id=engine.inst.security_id,
                exchange=engine.inst.spot_exchange_segment,
                lookback_days=1,
                instrument_type=engine.inst.instrument_type,
            )
            if df is not None and not df.empty:
                # Get first candle for OHLC
                first = df.iloc[0]
                o = float(first.get("open", first.get("Open", 0)))
                h = float(first.get("high", first.get("High", 0)))
                l = float(first.get("low", first.get("Low", 0)))
                c = float(first.get("close", first.get("Close", 0)))
                index_ohlc = {
                    "o": round(o, 1),
                    "h": round(h, 1),
                    "l": round(l, 1),
                    "c": round(c, 1),
                }

                # Get day open and close from first and last candles
                nifty_open = o
                last = df.iloc[-1]
                nifty_close = float(last.get("close", last.get("Close", 0)))
                if nifty_open > 0:
                    nifty_change_pct = round(
                        (nifty_close - nifty_open) / nifty_open * 100, 2
                    )
        except Exception:
            logger.debug("Could not fetch intraday data for journal")

        # Fallback: use live feed LTP for close
        if nifty_close == 0:
            try:
                ltp = engine.feed.get_ltp(engine.inst.security_id)
                if ltp:
                    nifty_close = ltp
            except Exception:
                pass

        # Get trades from journal
        trades_data = []
        try:
            raw_trades = engine.journal.get_today_trades()
            for t in raw_trades:
                trades_data.append(
                    {
                        "entry_time": t.get("entry_time", ""),
                        "exit_time": t.get("exit_time", ""),
                        "direction": t.get("option_type", t.get("direction", "")),
                        "strike": t.get("strike_price", 0),
                        "entry_premium": t.get("entry_price", 0),
                        "exit_premium": t.get("exit_price", 0),
                        "exit_reason": t.get("exit_reason", ""),
                        "pnl": t.get("pnl", 0),
                        "grade": t.get("grade", ""),
                        "rungs_hit": t.get("rungs_hit", []),
                        "peak_premium": t.get("peak_premium", 0),
                        "risk_free": t.get("risk_free", False),
                        "quantity": t.get("quantity", 0),
                    }
                )
        except Exception:
            logger.debug("Could not fetch trades from journal")

        # Determine system health
        daily_pnl = getattr(engine, "_daily_pnl", 0.0) or 0.0
        trade_count = getattr(engine, "_trade_count", 0) or 0
        system_health = "green"
        if trade_count > 0:
            if daily_pnl < -5000:
                system_health = "red"
            elif daily_pnl < 0:
                system_health = "yellow"

        # Determine skip reason
        skip_reason = None
        if trade_count == 0:
            if "blocked" in signal.lower() or vix_mode == "blocked":
                skip_reason = "VIX blocked"
            elif signal in ("wait", "no_trade", "none"):
                skip_reason = "No signal"

        # Collect decision events from engine
        events = list(getattr(engine, "_day_events", []))

        # Extract confluence score from events (if available)
        confluence_score = 0
        for ev in events:
            if ev.get("type") == "confluence":
                confluence_score = ev.get("total_score", 0)

        self._day_data = {
            "date": today,
            "nifty_open": round(nifty_open, 1),
            "nifty_close": round(nifty_close, 1),
            "nifty_change_pct": nifty_change_pct,
            "vix": round(vix, 1),
            "vix_mode": vix_mode,
            "signal": signal,
            "signal_detail": signal_detail,
            "index_ohlc": index_ohlc,
            "confluence_score": confluence_score,
            "day_type": self._classify_day(nifty_open, nifty_close, index_ohlc),
            "trades": trades_data,
            "daily_pnl": round(daily_pnl, 0),
            "trade_count": trade_count,
            "system_health": system_health,
            "skip_reason": skip_reason,
            "events": events,
        }

        logger.info(
            "Journal data collected for %s: signal=%s pnl=%.0f trades=%d",
            today,
            signal,
            daily_pnl,
            trade_count,
        )
        return self._day_data

    @staticmethod
    def _classify_day(
        nifty_open: float, nifty_close: float, ohlc: dict | None,
    ) -> str:
        """Classify trading day from OHLC data."""
        if not ohlc or nifty_open <= 0:
            return "unknown"
        high = ohlc.get("h", 0)
        low = ohlc.get("l", 0)
        day_range = high - low
        if day_range <= 0:
            return "unknown"
        body = abs(nifty_close - nifty_open)
        body_ratio = body / day_range
        if body_ratio > 0.5:
            return "trending_bullish" if nifty_close > nifty_open else "trending_bearish"
        return "choppy"

    def publish(self):
        """Clone gh-pages, merge today's data, regenerate index.html, push."""
        if not self._day_data:
            logger.warning("No day data to publish")
            return

        try:
            self._ensure_repo()
            self._merge_data()
            self._regenerate_html()
            self._push()
            logger.info("Journal published to GitHub Pages")
        except Exception:
            logger.exception("Failed to publish journal")

    def _ensure_repo(self):
        """Clone or pull the gh-pages branch."""
        if (self._work_dir / ".git").exists():
            # Pull latest
            self._run_git("fetch", "origin", self.BRANCH)
            self._run_git("reset", "--hard", f"origin/{self.BRANCH}")
        else:
            # Clone gh-pages branch only
            self._work_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--branch",
                    self.BRANCH,
                    "--single-branch",
                    "--depth",
                    "1",
                    self.REPO_URL,
                    str(self._work_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

    def _merge_data(self):
        """Load existing data, upsert today's entry."""
        data_file = self._work_dir / "data.js"

        existing: list[dict] = []
        if data_file.exists():
            content = data_file.read_text()
            # Parse: const VENOM_DATA = [...];
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    existing = json.loads(content[start:end])
                except json.JSONDecodeError:
                    existing = []

        # Upsert by date
        today = self._day_data["date"]
        existing = [d for d in existing if d.get("date") != today]
        existing.append(self._day_data)
        existing.sort(key=lambda d: d.get("date", ""))

        data_file.write_text(
            "const VENOM_DATA = " + json.dumps(existing, indent=2) + ";\n"
        )

    def _regenerate_html(self):
        """Regenerate index.html from template with current data."""
        from nifty_trader.pages.template import render_html

        data_file = self._work_dir / "data.js"
        content = data_file.read_text()
        start = content.find("[")
        end = content.rfind("]") + 1
        days_json = content[start:end]

        html_file = self._work_dir / "index.html"
        html_file.write_text(render_html(days_json))

    def _push(self):
        """Git add, commit, push."""
        self._run_git("add", "data.js", "index.html")

        today = self._day_data["date"]
        pnl = self._day_data.get("daily_pnl", 0)
        signal = self._day_data.get("signal", "none")
        msg = f"{today}: {signal} | P&L: {pnl:+.0f}"

        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=self._work_dir,
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("No changes to publish")
            return

        self._run_git("commit", "-m", msg)
        self._run_git("push", "origin", self.BRANCH)

    def _run_git(self, *args):
        """Run a git command in the work directory."""
        subprocess.run(
            ["git"] + list(args),
            cwd=self._work_dir,
            check=True,
            capture_output=True,
            text=True,
        )
