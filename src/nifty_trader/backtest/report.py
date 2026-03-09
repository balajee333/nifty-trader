"""Rich terminal report for VENOM backtest results."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nifty_trader.backtest.engine import BacktestResult, BacktestDaySummary


class BacktestReportGenerator:
    """Generates a rich terminal report from backtest results."""

    def __init__(self):
        self._console = Console()

    def print_report(self, result: BacktestResult) -> None:
        self._console.print()
        self._print_header(result)
        self._print_summary(result)
        self._print_equity_curve(result)
        self._print_monthly_breakdown(result)
        self._print_signal_stats(result)
        self._print_day_of_week(result)
        self._print_vix_regime(result)
        self._print_trail_stats(result)
        self._print_trade_log(result)
        self._print_skipped_days(result)
        self._print_footer(result)

    def _print_header(self, result: BacktestResult) -> None:
        cfg = result.config
        header = Text()
        header.append("VENOM BACKTEST REPORT\n", style="bold cyan")
        header.append(f"Period: {cfg.start_date} → {cfg.end_date}\n")
        data_mode = "REAL OPTIONS" if cfg.use_real_options else "SIMULATED"
        header.append(f"Capital: {cfg.start_capital:,.0f} | Lot Size: {cfg.lot_size} | Data: {data_mode}\n")
        header.append(f"Trading Days: {len(result.days)} | Trades: {result.total_trades}")
        self._console.print(Panel(header, border_style="cyan"))

    def _print_summary(self, result: BacktestResult) -> None:
        table = Table(title="Performance Summary", show_header=False, border_style="green")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        pnl_style = "green" if result.total_pnl >= 0 else "red"
        pnl_pct = (result.total_pnl / result.config.start_capital * 100)
        final_capital = result.config.start_capital + result.total_pnl

        table.add_row("Total P&L", Text(f"{result.total_pnl:+,.2f} ({pnl_pct:+.1f}%)", style=pnl_style))
        table.add_row("Final Capital", f"{final_capital:,.2f}")
        table.add_row("", "")
        table.add_row("Total Trades", str(result.total_trades))
        table.add_row("Winners", f"{result.winners} ({result.win_rate:.1f}%)")
        table.add_row("Losers", str(result.losers))
        table.add_row("", "")
        table.add_row("Avg Winner", Text(f"{result.avg_winner:+,.2f}", style="green"))
        table.add_row("Avg Loser", Text(f"{result.avg_loser:+,.2f}", style="red"))
        table.add_row("Expectancy", f"{result.expectancy:+,.2f}")
        table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
        table.add_row("", "")
        table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
        table.add_row("Max Drawdown", Text(f"{result.max_drawdown:,.2f} ({result.max_drawdown_pct:.1f}%)", style="red"))
        table.add_row("Best Day", Text(f"{result.best_day:+,.2f}", style="green"))
        table.add_row("Worst Day", Text(f"{result.worst_day:+,.2f}", style="red"))

        self._console.print(table)

    def _print_equity_curve(self, result: BacktestResult) -> None:
        curve = result.equity_curve
        if len(curve) < 2:
            return

        # ASCII sparkline
        mn = min(curve)
        mx = max(curve)
        rng = mx - mn if mx > mn else 1.0
        width = min(60, len(curve))
        step = max(1, len(curve) // width)

        sampled = [curve[i] for i in range(0, len(curve), step)]
        if sampled[-1] != curve[-1]:
            sampled.append(curve[-1])

        height = 8
        lines = []
        for row in range(height, -1, -1):
            threshold = mn + (rng * row / height)
            line = ""
            for val in sampled:
                if val >= threshold:
                    line += "█"
                else:
                    line += " "
            lines.append(line)

        chart = "\n".join(lines)
        label_top = f" {mx:,.0f}"
        label_bot = f" {mn:,.0f}"

        text = Text()
        text.append("Equity Curve\n\n", style="bold")
        for i, line in enumerate(lines):
            if i == 0:
                text.append(f"  {line}{label_top}\n", style="green" if curve[-1] >= curve[0] else "red")
            elif i == len(lines) - 1:
                text.append(f"  {line}{label_bot}\n")
            else:
                text.append(f"  {line}\n")

        self._console.print(Panel(text, border_style="blue"))

    def _print_monthly_breakdown(self, result: BacktestResult) -> None:
        if not result.monthly_breakdown:
            return

        table = Table(title="Monthly Breakdown", border_style="yellow")
        table.add_column("Month", style="bold")
        table.add_column("P&L", justify="right")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")

        for month, pnl in sorted(result.monthly_breakdown.items()):
            month_trades = [t for d in result.days for t in d.trades if d.date.startswith(month)]
            wins = sum(1 for t in month_trades if t.pnl > 0)
            wr = (wins / len(month_trades) * 100) if month_trades else 0
            style = "green" if pnl >= 0 else "red"
            table.add_row(
                month,
                Text(f"{pnl:+,.2f}", style=style),
                str(len(month_trades)),
                f"{wr:.0f}%",
            )

        self._console.print(table)

    def _print_signal_stats(self, result: BacktestResult) -> None:
        if not result.signal_stats:
            return

        table = Table(title="Signal Type Breakdown", border_style="magenta")
        table.add_column("Signal", style="bold")
        table.add_column("Trades", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg P&L", justify="right")

        for sig, stats in sorted(result.signal_stats.items()):
            n = stats["trades"]
            pnl = stats["pnl"]
            wins = stats["wins"]
            wr = (wins / n * 100) if n else 0
            avg = pnl / n if n else 0
            style = "green" if pnl >= 0 else "red"
            table.add_row(
                sig, str(n),
                Text(f"{pnl:+,.2f}", style=style),
                f"{wr:.0f}%",
                Text(f"{avg:+,.2f}", style=style),
            )

        self._console.print(table)

    def _print_day_of_week(self, result: BacktestResult) -> None:
        if not result.day_of_week_stats:
            return

        table = Table(title="Day-of-Week Breakdown", border_style="cyan")
        table.add_column("Day", style="bold")
        table.add_column("Trading Days", justify="right")
        table.add_column("Trades", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Win Rate", justify="right")

        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        for dow in day_order:
            stats = result.day_of_week_stats.get(dow)
            if not stats:
                continue
            n = stats["trades"]
            pnl = stats["pnl"]
            wins = stats["wins"]
            wr = (wins / n * 100) if n else 0
            style = "green" if pnl >= 0 else "red"
            table.add_row(
                dow, str(stats["days"]), str(n),
                Text(f"{pnl:+,.2f}", style=style),
                f"{wr:.0f}%",
            )

        self._console.print(table)

    def _print_vix_regime(self, result: BacktestResult) -> None:
        if not result.vix_regime_stats:
            return

        table = Table(title="VIX Regime Breakdown", border_style="red")
        table.add_column("Regime", style="bold")
        table.add_column("Trades", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Win Rate", justify="right")

        for mode, stats in sorted(result.vix_regime_stats.items()):
            n = stats["trades"]
            pnl = stats["pnl"]
            wins = stats["wins"]
            wr = (wins / n * 100) if n else 0
            style = "green" if pnl >= 0 else "red"
            table.add_row(
                mode.upper(), str(n),
                Text(f"{pnl:+,.2f}", style=style),
                f"{wr:.0f}%",
            )

        self._console.print(table)

    def _print_trail_stats(self, result: BacktestResult) -> None:
        ts = result.trail_stats
        if not ts:
            return

        table = Table(title="Trail Engine Stats", show_header=False, border_style="green")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Total Rung Hits", str(ts.get("total_rung_hits", 0)))
        table.add_row("Risk-Free Trades", str(ts.get("risk_free_trades", 0)))
        table.add_row("Avg Rungs/Trade", f"{ts.get('avg_rungs_per_trade', 0):.1f}")

        exit_reasons = ts.get("exit_reasons", {})
        if exit_reasons:
            table.add_row("", "")
            table.add_row("Exit Reasons", "")
            for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
                pct = (count / result.total_trades * 100) if result.total_trades else 0
                table.add_row(f"  {reason}", f"{count} ({pct:.0f}%)")

        self._console.print(table)

    def _print_trade_log(self, result: BacktestResult) -> None:
        trades = [t for d in result.days for t in d.trades]
        if not trades:
            return

        table = Table(title="Trade Log", border_style="white")
        table.add_column("Date", style="bold")
        table.add_column("Dir")
        table.add_column("Signal")
        table.add_column("Entry", justify="right")
        table.add_column("Exit", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Exit Reason")
        table.add_column("VIX", justify="right")
        table.add_column("Rungs")
        table.add_column("Grade")

        for t in trades:
            pnl_style = "green" if t.pnl >= 0 else "red"
            grade_style = {
                "A+": "bold green", "A": "green", "B": "yellow",
                "C": "dim", "F": "red",
            }.get(t.grade, "")

            table.add_row(
                t.date,
                t.direction[:4],
                t.signal_type[:20],
                f"{t.entry_premium:.2f}",
                f"{t.exit_premium:.2f}",
                Text(f"{t.pnl:+,.2f}", style=pnl_style),
                t.exit_reason,
                f"{t.vix:.1f}",
                str(t.rungs_hit) if t.rungs_hit else "-",
                Text(t.grade, style=grade_style),
            )

        self._console.print(table)

    def _print_skipped_days(self, result: BacktestResult) -> None:
        skipped = [d for d in result.days if d.skipped]
        if not skipped:
            return

        table = Table(title=f"Skipped Days ({len(skipped)})", border_style="dim")
        table.add_column("Date", style="bold")
        table.add_column("Signal")
        table.add_column("VIX", justify="right")
        table.add_column("Reason")

        for d in skipped[:20]:  # show first 20
            table.add_row(d.date, d.signal_detected, f"{d.vix:.1f}", d.skip_reason)

        if len(skipped) > 20:
            table.add_row("...", f"+{len(skipped) - 20} more", "", "")

        self._console.print(table)

    def _print_footer(self, result: BacktestResult) -> None:
        traded_days = [d for d in result.days if not d.skipped]
        skipped_days = [d for d in result.days if d.skipped]

        text = Text()
        text.append("\n")
        text.append(f"  {len(result.days)} calendar trading days | ", style="dim")
        text.append(f"{len(traded_days)} traded | ", style="dim")
        text.append(f"{len(skipped_days)} skipped\n", style="dim")

        if result.total_trades > 0:
            avg_per_day = result.total_trades / len(traded_days) if traded_days else 0
            text.append(f"  Avg trades/day: {avg_per_day:.1f} | ", style="dim")
            daily_avg = result.total_pnl / len(traded_days) if traded_days else 0
            style = "green" if daily_avg >= 0 else "red"
            text.append(f"Avg daily P&L: ", style="dim")
            text.append(f"{daily_avg:+,.2f}", style=style)
            text.append("\n", style="dim")

            # Goal projection
            monthly_avg = daily_avg * 22  # ~22 trading days/month
            text.append(f"  Projected monthly: ", style="dim")
            text.append(f"{monthly_avg:+,.0f}", style="green" if monthly_avg >= 0 else "red")
            text.append("\n", style="dim")

        self._console.print(text)
