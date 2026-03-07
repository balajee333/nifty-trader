"""Post-market P&L verification and position reconciliation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nifty_trader.alerts.notifier import Notifier
from nifty_trader.journal.database import TradeJournal

if TYPE_CHECKING:
    from dhanhq import DhanHQ

logger = logging.getLogger(__name__)


class Reconciler:
    """Cross-checks API positions vs internal state after market close."""

    def __init__(
        self,
        dhan: DhanHQ,
        journal: TradeJournal,
        notifier: Notifier,
        capital: float = 100_000.0,
    ):
        self._dhan = dhan
        self._journal = journal
        self._notifier = notifier
        self._capital = capital

    def run(self) -> dict:
        """Perform post-market reconciliation. Returns summary dict."""
        summary: dict = {
            "api_positions": [],
            "ghost_positions": [],
            "journal_trades": [],
            "daily_pnl": 0.0,
            "mismatches": [],
        }

        # Fetch API positions
        api_positions = self._fetch_api_positions()
        summary["api_positions"] = api_positions

        # Check for ghost positions (non-zero qty after market close)
        ghosts = [p for p in api_positions if p.get("net_qty", 0) != 0]
        summary["ghost_positions"] = ghosts
        if ghosts:
            msg = f"GHOST POSITIONS DETECTED: {len(ghosts)} open positions after market close"
            logger.critical(msg)
            self._notifier.error(msg)
            for g in ghosts:
                logger.critical("  Ghost: %s qty=%s", g.get("security_id"), g.get("net_qty"))

        # Get today's journal trades
        journal_trades = self._journal.get_today_trades()
        summary["journal_trades"] = journal_trades

        # Compute P&L from journal
        journal_pnl = sum(t.get("pnl", 0) or 0 for t in journal_trades)
        summary["daily_pnl"] = journal_pnl

        # Fetch API trade history for cross-check
        api_pnl = self._fetch_api_pnl()
        if api_pnl is not None and abs(api_pnl - journal_pnl) > 1.0:
            mismatch = f"P&L mismatch: API={api_pnl:.2f} vs Journal={journal_pnl:.2f}"
            summary["mismatches"].append(mismatch)
            self._notifier.warning(mismatch)

        # Update daily summary
        self._journal.update_daily_summary(self._capital)

        # Build summary message
        msg_lines = [
            f"Trades: {len(journal_trades)}",
            f"P&L: {journal_pnl:+.2f}",
            f"Ghost positions: {len(ghosts)}",
        ]
        if summary["mismatches"]:
            msg_lines.append(f"Mismatches: {len(summary['mismatches'])}")

        self._notifier.daily_summary("\n".join(msg_lines))

        return summary

    def _fetch_api_positions(self) -> list[dict]:
        try:
            resp = self._dhan.get_positions()
            if resp and resp.get("status") == "success":
                return [
                    {
                        "security_id": str(p.get("securityId", "")),
                        "net_qty": int(p.get("netQty", p.get("quantity", 0))),
                        "avg_price": float(p.get("averagePrice", 0)),
                        "pnl": float(p.get("realizedProfit", 0)),
                    }
                    for p in resp.get("data", [])
                ]
        except Exception:
            logger.exception("Failed to fetch API positions for reconciliation")
        return []

    def _fetch_api_pnl(self) -> float | None:
        try:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            resp = self._dhan.get_trade_history(from_date=today, to_date=today)
            if resp and resp.get("status") == "success":
                trades = resp.get("data", [])
                total = sum(float(t.get("tradedPrice", 0)) for t in trades)
                return total
        except Exception:
            logger.exception("Failed to fetch API trade history")
        return None
