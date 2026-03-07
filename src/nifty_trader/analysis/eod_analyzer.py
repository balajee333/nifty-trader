"""End-of-day analyzer — replay day, grade trades, find missed signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TradeGrade:
    trade_id: int
    grade: str  # A+, A, B, C, F
    entry_score: float  # 0-100
    exit_score: float  # 0-100
    timing_score: float  # 0-100
    mfe: float  # max favorable excursion (best unrealized P&L)
    mae: float  # max adverse excursion (worst unrealized P&L)
    captured_pct: float  # % of available move captured
    notes: list[str] = field(default_factory=list)


@dataclass
class MissedSignal:
    time: str
    signal_type: str
    reason_missed: str
    theoretical_pnl: float


@dataclass
class DayAnalysis:
    date: str
    trades_taken: list[TradeGrade]
    missed_signals: list[MissedSignal]
    day_type: str  # trending/choppy/volatile
    vix_range: tuple[float, float]
    nifty_range: tuple[float, float]
    nifty_change_pct: float
    actual_pnl: float
    optimal_pnl: float
    efficiency: float  # actual/optimal
    insights: list[str] = field(default_factory=list)
    system_health: str = "green"  # green/yellow/red


class EODAnalyzer:
    """Analyzes a day's trading and produces grades + insights."""

    def __init__(self, journal, lot_size: int = 25):
        self._journal = journal
        self._lot_size = lot_size

    def analyze(
        self,
        date: str | None = None,
        candles: list[dict] | None = None,
        vix_data: list[dict] | None = None,
    ) -> DayAnalysis:
        """Run full end-of-day analysis.

        Args:
            date: Date string YYYY-MM-DD. Defaults to today.
            candles: 5-min candles for the day (list of dicts with
                     open/high/low/close/volume/timestamp).
            vix_data: VIX readings for the day.
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        trades = self._journal.get_today_trades()
        if not trades and date != datetime.now().strftime("%Y-%m-%d"):
            trades = self._get_trades_for_date(date)

        # Market data summary
        nifty_range, nifty_change_pct = self._compute_market_range(candles)
        vix_range = self._compute_vix_range(vix_data)
        day_type = self._classify_day(candles, vix_range)

        # Grade each trade
        graded_trades = [self._grade_trade(t, candles) for t in trades]

        # Detect missed signals
        missed = self._detect_missed_signals(trades, candles, date)

        # Compute P&L metrics
        actual_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
        optimal_pnl = self._compute_optimal_pnl(candles)
        efficiency = (actual_pnl / optimal_pnl * 100) if optimal_pnl > 0 else 0.0

        # Generate insights
        insights = self._generate_insights(graded_trades, missed, day_type, vix_range)

        # System health
        system_health = self._assess_health(graded_trades, actual_pnl)

        return DayAnalysis(
            date=date,
            trades_taken=graded_trades,
            missed_signals=missed,
            day_type=day_type,
            vix_range=vix_range,
            nifty_range=nifty_range,
            nifty_change_pct=nifty_change_pct,
            actual_pnl=actual_pnl,
            optimal_pnl=optimal_pnl,
            efficiency=efficiency,
            insights=insights,
            system_health=system_health,
        )

    def _get_trades_for_date(self, date: str) -> list[dict]:
        """Fetch trades for a specific date from the journal."""
        rows = self._journal._conn.execute(
            "SELECT * FROM trades WHERE date(entry_time) = ? ORDER BY id",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _compute_market_range(
        self, candles: list[dict] | None
    ) -> tuple[tuple[float, float], float]:
        if not candles:
            return (0.0, 0.0), 0.0
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        opens = candles[0]["open"]
        closes = candles[-1]["close"]
        change_pct = ((closes - opens) / opens) * 100 if opens else 0.0
        return (min(lows), max(highs)), change_pct

    def _compute_vix_range(
        self, vix_data: list[dict] | None
    ) -> tuple[float, float]:
        if not vix_data:
            return (0.0, 0.0)
        values = [v.get("close", v.get("value", 0)) for v in vix_data]
        return (min(values), max(values)) if values else (0.0, 0.0)

    def _classify_day(
        self, candles: list[dict] | None, vix_range: tuple[float, float]
    ) -> str:
        if not candles:
            return "unknown"

        opens = candles[0]["open"]
        closes = candles[-1]["close"]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        day_range = max(highs) - min(lows)
        body = abs(closes - opens)

        # VIX driven classification
        avg_vix = sum(vix_range) / 2 if vix_range[1] > 0 else 0
        if avg_vix > 20:
            return "volatile"

        # Body-to-range ratio determines trending vs choppy
        if day_range > 0 and body / day_range > 0.5:
            direction = "bullish" if closes > opens else "bearish"
            return f"{direction} trending"

        return "choppy"

    def _grade_trade(self, trade: dict, candles: list[dict] | None) -> TradeGrade:
        """Grade a single trade on entry, exit, and timing."""
        entry_price = trade.get("entry_price", 0) or 0
        exit_price = trade.get("exit_price", 0) or 0
        pnl = trade.get("pnl", 0) or 0
        quantity = trade.get("quantity", 0) or self._lot_size

        # MFE/MAE from candle data (simplified — uses trade P&L direction)
        mfe = max(pnl, 0)
        mae = min(pnl, 0)

        # Captured percentage
        if entry_price > 0 and exit_price > 0:
            move = abs(exit_price - entry_price)
            # Estimate available move as 2x the actual move for grading
            available = move * 2 if pnl > 0 else move
            captured_pct = (move / available * 100) if available > 0 else 0
        else:
            captured_pct = 0

        # Scoring
        entry_score = self._score_entry(trade)
        exit_score = self._score_exit(trade, candles)
        timing_score = self._score_timing(trade)

        avg_score = (entry_score + exit_score + timing_score) / 3
        grade = self._score_to_grade(avg_score, pnl)

        notes = self._generate_trade_notes(trade, grade, entry_score, exit_score)

        return TradeGrade(
            trade_id=trade.get("id", 0),
            grade=grade,
            entry_score=entry_score,
            exit_score=exit_score,
            timing_score=timing_score,
            mfe=mfe,
            mae=mae,
            captured_pct=captured_pct,
            notes=notes,
        )

    def _score_entry(self, trade: dict) -> float:
        """Score entry quality 0-100."""
        score = 50.0  # base

        # Confluence score bonus
        conf = trade.get("confluence_score", 0) or 0
        if conf >= 3.0:
            score += 30
        elif conf >= 2.0:
            score += 15

        # Signal summary check
        signals = trade.get("signals_summary", "") or ""
        if "O=H" in signals or "O=L" in signals:
            score += 20  # strong pattern entry

        return min(score, 100)

    def _score_exit(self, trade: dict, candles: list[dict] | None) -> float:
        """Score exit quality 0-100."""
        score = 50.0
        exit_reason = trade.get("exit_reason", "") or ""
        pnl = trade.get("pnl", 0) or 0

        if "MAX_PROFIT" in exit_reason:
            score = 95  # captured full move
        elif "TRAIL" in exit_reason or "LOCK" in exit_reason:
            score = 80  # trailed well
        elif "SL_TO_COST" in exit_reason or "BREAKEVEN" in exit_reason:
            score = 60  # at least didn't lose
        elif "TIME_STOP" in exit_reason:
            score = 35  # trade went nowhere
        elif "SL_HIT" in exit_reason and pnl < 0:
            score = 20  # stopped out

        return score

    def _score_timing(self, trade: dict) -> float:
        """Score entry timing 0-100."""
        score = 60.0
        entry_time = trade.get("entry_time")
        if not entry_time:
            return score

        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time)
            except ValueError:
                return score

        hour, minute = entry_time.hour, entry_time.minute
        minutes_from_open = (hour - 9) * 60 + (minute - 15)

        # Best entries: first 15 minutes (O=H/O=L window)
        if minutes_from_open <= 15:
            score = 90
        elif minutes_from_open <= 30:
            score = 75
        elif minutes_from_open <= 60:
            score = 60
        elif minutes_from_open > 180:  # after 12:15 — lunch zone
            score = 35

        return score

    def _score_to_grade(self, avg_score: float, pnl: float) -> str:
        if avg_score >= 85 and pnl > 0:
            return "A+"
        if avg_score >= 70 and pnl > 0:
            return "A"
        if avg_score >= 55:
            return "B"
        if avg_score >= 40:
            return "C"
        return "F"

    def _generate_trade_notes(
        self, trade: dict, grade: str, entry_score: float, exit_score: float
    ) -> list[str]:
        notes = []
        pnl = trade.get("pnl", 0) or 0
        exit_reason = trade.get("exit_reason", "") or ""

        if pnl > 0:
            notes.append(f"Winner: +{pnl:,.0f}")
        else:
            notes.append(f"Loser: {pnl:,.0f}")

        if entry_score >= 80:
            notes.append("Strong entry signal")
        elif entry_score < 40:
            notes.append("Weak entry — consider skipping similar setups")

        if "TIME_STOP" in exit_reason:
            notes.append("Time stop — trade went flat, wasted capital time")

        if "SL_HIT" in exit_reason and pnl < 0:
            notes.append("SL hit immediately — possible false signal")

        return notes

    def _detect_missed_signals(
        self,
        trades: list[dict],
        candles: list[dict] | None,
        date: str,
    ) -> list[MissedSignal]:
        """Detect potential missed O=H/O=L signals in the day's data."""
        if not candles or len(candles) < 2:
            return []

        missed = []

        # Check first candle for O=H/O=L that wasn't traded
        first = candles[0]
        open_p, high, low = first["open"], first["high"], first["low"]

        idx_tol = open_p * 0.0005  # 0.05% tolerance
        has_oh = (high - open_p) <= idx_tol
        has_ol = (open_p - low) <= idx_tol

        traded_directions = set()
        for t in trades:
            d = t.get("direction", "")
            traded_directions.add(d)

        if has_oh and "BEARISH" not in traded_directions and not trades:
            # O=H appeared but no bearish trade taken
            # Estimate theoretical P&L from afternoon candles
            afternoon_low = min(c["low"] for c in candles[len(candles) // 2 :])
            theoretical = (open_p - afternoon_low) * self._lot_size * 0.3
            missed.append(
                MissedSignal(
                    time=first.get("timestamp", "09:15"),
                    signal_type="O=H (bearish)",
                    reason_missed="System did not enter — check confirmations",
                    theoretical_pnl=theoretical,
                )
            )

        if has_ol and "BULLISH" not in traded_directions and not trades:
            afternoon_high = max(c["high"] for c in candles[len(candles) // 2 :])
            theoretical = (afternoon_high - open_p) * self._lot_size * 0.3
            missed.append(
                MissedSignal(
                    time=first.get("timestamp", "09:15"),
                    signal_type="O=L (bullish)",
                    reason_missed="System did not enter — check confirmations",
                    theoretical_pnl=theoretical,
                )
            )

        # Check for breakout moves after NO_TRADE classification
        if not trades and len(candles) >= 10:
            # Look for strong directional moves > 0.5% in afternoon
            for i in range(len(candles) // 2, len(candles) - 1):
                c = candles[i]
                body_pct = abs(c["close"] - c["open"]) / c["open"] * 100
                if body_pct > 0.3:
                    direction = "breakout up" if c["close"] > c["open"] else "breakout down"
                    theoretical = abs(c["close"] - c["open"]) * self._lot_size * 0.5
                    missed.append(
                        MissedSignal(
                            time=c.get("timestamp", ""),
                            signal_type=f"Afternoon {direction}",
                            reason_missed="System in NO_TRADE zone",
                            theoretical_pnl=theoretical,
                        )
                    )
                    break  # only report first big breakout

        return missed

    def _compute_optimal_pnl(self, candles: list[dict] | None) -> float:
        """Theoretical max P&L from perfect entries/exits."""
        if not candles or len(candles) < 2:
            return 0.0

        # Optimal: capture the full day's range on the right side
        opens = candles[0]["open"]
        highs = max(c["high"] for c in candles)
        lows = min(c["low"] for c in candles)
        closes = candles[-1]["close"]

        # If market went up, optimal is buy at low sell at high
        # If market went down, optimal is short at high cover at low
        up_move = highs - lows
        return up_move * self._lot_size * 0.5  # 50% capture is "optimal realistic"

    def _generate_insights(
        self,
        trades: list[TradeGrade],
        missed: list[MissedSignal],
        day_type: str,
        vix_range: tuple[float, float],
    ) -> list[str]:
        insights = []

        if not trades:
            insights.append("No trades taken today")
            if missed:
                insights.append(
                    f"{len(missed)} missed signal(s) — review entry criteria"
                )
            return insights

        winners = [t for t in trades if t.grade in ("A+", "A", "B")]
        losers = [t for t in trades if t.grade in ("C", "F")]

        if winners:
            avg_captured = sum(t.captured_pct for t in winners) / len(winners)
            insights.append(
                f"Winners captured avg {avg_captured:.0f}% of available move"
            )

        if losers:
            for t in losers:
                for note in t.notes:
                    if "false signal" in note.lower() or "weak entry" in note.lower():
                        insights.append(f"Trade #{t.trade_id}: {note}")

        if "trending" in day_type:
            insights.append(f"Day was {day_type} — trail engine should perform well")
        elif day_type == "choppy":
            insights.append("Choppy day — consider reducing entries on similar days")

        if vix_range[1] > 20:
            insights.append(
                f"High VIX ({vix_range[0]:.1f}-{vix_range[1]:.1f}) — "
                "premiums elevated, wider SLs may help"
            )

        if missed:
            total_missed_pnl = sum(m.theoretical_pnl for m in missed)
            insights.append(
                f"Missed opportunities worth ~{total_missed_pnl:,.0f} theoretical P&L"
            )

        return insights

    def _assess_health(self, trades: list[TradeGrade], actual_pnl: float) -> str:
        if not trades:
            return "green"

        f_count = sum(1 for t in trades if t.grade == "F")
        avg_score = sum(t.entry_score + t.exit_score + t.timing_score for t in trades) / (
            len(trades) * 3
        )

        if f_count >= 2 or actual_pnl < -5000 or avg_score < 30:
            return "red"
        if f_count >= 1 or actual_pnl < -2000 or avg_score < 50:
            return "yellow"
        return "green"
