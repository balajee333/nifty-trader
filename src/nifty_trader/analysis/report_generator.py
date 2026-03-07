"""Rich terminal post-market report generator."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from nifty_trader.analysis.eod_analyzer import DayAnalysis, TradeGrade
from nifty_trader.analysis.goal_tracker import GoalProgress, GoalTracker, Streak


class ReportGenerator:
    """Generate rich terminal post-market reports."""

    def __init__(self, console: Console | None = None):
        self._console = console or Console()

    def print_eod_report(
        self,
        analysis: DayAnalysis,
        progress: GoalProgress,
        streak: Streak,
        cumulative_stats: dict | None = None,
    ):
        """Print the full end-of-day report."""
        self._console.print()
        self._print_header(analysis)
        self._print_market_snapshot(analysis)
        self._print_trades(analysis)
        self._print_missed_opportunities(analysis)
        self._print_daily_stats(analysis, cumulative_stats)
        self._print_cumulative(progress, streak, cumulative_stats)
        self._print_goal_tracker(progress)
        self._print_learnings(analysis)
        self._console.print()

    def print_dashboard(self, progress: GoalProgress, streak: Streak,
                        weekly: dict | None = None, monthly: dict | None = None):
        """Print standalone goal tracker dashboard."""
        self._console.print()
        self._print_dashboard_header()
        self._print_goal_tracker(progress)
        self._print_streak_panel(streak)
        if weekly:
            self._print_weekly_panel(weekly)
        if monthly:
            self._print_monthly_panel(monthly)
        self._console.print()

    def print_learnings(self, insights: list):
        """Print accumulated trading insights."""
        self._console.print()
        self._console.print(
            Panel(
                Text("VENOM TRADING INSIGHTS", style="bold white", justify="center"),
                style="blue",
            )
        )

        if not insights:
            self._console.print(
                Panel("No insights accumulated yet. Run --eod after trading sessions.",
                      title="Learnings", border_style="yellow")
            )
            return

        # Group by category
        by_category: dict[str, list] = {}
        for i in insights:
            cat = i.category
            by_category.setdefault(cat, []).append(i)

        for category, items in by_category.items():
            table = Table(show_header=True, expand=True)
            table.add_column("Insight", ratio=4)
            table.add_column("Seen", justify="center", width=6)
            table.add_column("Status", justify="center", width=10)
            table.add_column("P&L Impact", justify="right", width=12)

            for item in items:
                conf_style = {
                    "confirmed": "bold green",
                    "observed": "yellow",
                    "hypothesis": "dim",
                }.get(item.confidence, "white")

                pnl_color = "green" if item.pnl_impact >= 0 else "red"
                pnl_str = f"[{pnl_color}]{item.pnl_impact:+,.0f}[/{pnl_color}]"

                table.add_row(
                    item.insight,
                    str(item.occurrences),
                    f"[{conf_style}]{item.confidence}[/{conf_style}]",
                    pnl_str,
                )

            self._console.print(
                Panel(table, title=f"[bold]{category.upper()}[/bold]",
                      border_style="cyan")
            )

        self._console.print()

    # ------------------------------------------------------------------
    # Private panel builders
    # ------------------------------------------------------------------

    def _print_header(self, analysis: DayAnalysis):
        try:
            dt = datetime.strptime(analysis.date, "%Y-%m-%d")
            date_str = dt.strftime("%A %m/%d/%Y")
        except ValueError:
            date_str = analysis.date

        health_color = {
            "green": "green",
            "yellow": "yellow",
            "red": "red",
        }.get(analysis.system_health, "white")

        text = Text(justify="center")
        text.append("VENOM POST-MARKET REPORT", style="bold white")
        text.append(f"  |  {date_str}", style="white")
        text.append(f"  |  Health: ", style="white")
        text.append(analysis.system_health.upper(), style=f"bold {health_color}")

        self._console.print(Panel(text, style="blue"))

    def _print_dashboard_header(self):
        text = Text(justify="center")
        text.append("VENOM GOAL TRACKER", style="bold white")
        text.append(f"  |  {datetime.now().strftime('%A %m/%d/%Y')}", style="white")
        self._console.print(Panel(text, style="blue"))

    def _print_market_snapshot(self, analysis: DayAnalysis):
        table = Table(show_header=False, expand=True, padding=(0, 1))
        table.add_column("Field", style="cyan", width=20)
        table.add_column("Value")

        nifty_lo, nifty_hi = analysis.nifty_range
        vix_lo, vix_hi = analysis.vix_range

        change_color = "green" if analysis.nifty_change_pct >= 0 else "red"
        table.add_row(
            "Nifty Range",
            f"{nifty_lo:,.0f} — {nifty_hi:,.0f}  "
            f"([{change_color}]{analysis.nifty_change_pct:+.2f}%[/{change_color}])",
        )
        if vix_hi > 0:
            table.add_row("VIX Range", f"{vix_lo:.1f} — {vix_hi:.1f}")
        table.add_row("Day Type", f"[bold]{analysis.day_type.upper()}[/bold]")

        self._console.print(
            Panel(table, title="[bold]MARKET SNAPSHOT[/bold]", border_style="green")
        )

    def _print_trades(self, analysis: DayAnalysis):
        if not analysis.trades_taken:
            self._console.print(
                Panel("No trades taken today", title="TRADES", border_style="yellow")
            )
            return

        table = Table(show_header=True, expand=True)
        table.add_column("#", width=3, justify="center")
        table.add_column("Details", ratio=3)
        table.add_column("P&L", width=10, justify="right")
        table.add_column("Grade", width=6, justify="center")
        table.add_column("Notes", ratio=2)

        for tg in analysis.trades_taken:
            grade_color = {
                "A+": "bold green",
                "A": "green",
                "B": "yellow",
                "C": "red",
                "F": "bold red",
            }.get(tg.grade, "white")

            notes_str = " | ".join(tg.notes[:2]) if tg.notes else ""

            table.add_row(
                str(tg.trade_id),
                f"Entry:{tg.entry_score:.0f} Exit:{tg.exit_score:.0f} "
                f"Time:{tg.timing_score:.0f} | Captured {tg.captured_pct:.0f}%",
                f"{tg.mfe:+,.0f}" if tg.mfe != 0 else f"{tg.mae:+,.0f}",
                f"[{grade_color}]{tg.grade}[/{grade_color}]",
                notes_str,
            )

        self._console.print(
            Panel(table, title="[bold]TRADES[/bold]", border_style="yellow")
        )

    def _print_missed_opportunities(self, analysis: DayAnalysis):
        if not analysis.missed_signals:
            return

        table = Table(show_header=True, expand=True)
        table.add_column("Time", width=10)
        table.add_column("Signal", ratio=2)
        table.add_column("Reason", ratio=3)
        table.add_column("Theo. P&L", width=12, justify="right")

        for ms in analysis.missed_signals:
            table.add_row(
                ms.time,
                ms.signal_type,
                ms.reason_missed,
                f"[yellow]+{ms.theoretical_pnl:,.0f}[/yellow]",
            )

        self._console.print(
            Panel(
                table,
                title="[bold]MISSED OPPORTUNITIES[/bold]",
                border_style="magenta",
            )
        )

    def _print_daily_stats(self, analysis: DayAnalysis, cumulative: dict | None):
        table = Table(show_header=False, expand=True, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value")

        trades = analysis.trades_taken
        total = len(trades)
        winners = sum(1 for t in trades if t.mfe > 0)
        losers = total - winners

        pnl_color = "green" if analysis.actual_pnl >= 0 else "red"

        table.add_row("Trades", f"{total}")
        table.add_row("Won / Lost", f"{winners}W / {losers}L")
        table.add_row(
            "Net P&L",
            f"[{pnl_color}]{analysis.actual_pnl:+,.0f}[/{pnl_color}]",
        )
        table.add_row("Win Rate", f"{winners / total * 100:.0f}%" if total else "N/A")
        table.add_row("Efficiency", f"{analysis.efficiency:.0f}%")

        self._console.print(
            Panel(table, title="[bold]TODAY'S STATS[/bold]", border_style="cyan")
        )

    def _print_cumulative(self, progress: GoalProgress, streak: Streak,
                          cumulative: dict | None):
        table = Table(show_header=False, expand=True, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value")

        cap_color = "green" if progress.cumulative_pnl >= 0 else "red"
        table.add_row(
            "Capital",
            f"{progress.starting_capital:,.0f} → "
            f"[{cap_color}]{progress.current_capital:,.0f}[/{cap_color}] "
            f"([{cap_color}]{progress.cumulative_pnl:+,.0f}[/{cap_color}])",
        )

        streak_color = "green" if streak.type == "W" else "red"
        table.add_row(
            "Streak",
            f"[{streak_color}]{streak.count}{streak.type}[/{streak_color}] "
            f"({streak.pnl_during:+,.0f})",
        )

        if cumulative:
            table.add_row(
                "Win Rate (all)",
                f"{cumulative.get('win_rate', 0):.0f}%",
            )
            table.add_row(
                "Expectancy",
                f"{cumulative.get('expectancy', 0):+,.0f}/trade",
            )

        self._console.print(
            Panel(table, title="[bold]CUMULATIVE[/bold]", border_style="blue")
        )

    def _print_goal_tracker(self, progress: GoalProgress):
        # Progress bar
        pct = max(0, min(progress.progress_pct, 100))
        filled = int(pct / 100 * 30)
        bar = "[green]" + "\u2588" * filled + "[/green]" + "\u2591" * (30 - filled)

        table = Table(show_header=False, expand=True, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value")

        table.add_row("Progress", f"{bar}  {pct:.1f}%")
        table.add_row(
            "Current / Target",
            f"{progress.current_capital:,.0f} / {progress.target_capital:,.0f}",
        )
        table.add_row("Remaining", f"{progress.remaining:,.0f}")
        table.add_row(
            "Pace",
            f"{progress.actual_daily_pace:,.0f}/day "
            f"(need {progress.required_daily_pace:,.0f}/day)",
        )
        table.add_row(
            "Est. Completion",
            f"{progress.estimated_days_remaining} trading days",
        )

        status_map = {1: ("AHEAD OF TARGET", "green"),
                      0: ("ON TRACK", "yellow"),
                      -1: ("BEHIND TARGET", "red")}
        label, color = status_map.get(progress.on_track, ("UNKNOWN", "white"))
        table.add_row("Status", f"[bold {color}]{label}[/bold {color}]")

        if progress.max_drawdown < 0:
            table.add_row(
                "Max Drawdown",
                f"[red]{progress.max_drawdown:,.0f}[/red]",
            )

        self._console.print(
            Panel(
                table,
                title="[bold]GOAL TRACKER: 1L → 2L[/bold]",
                border_style="green",
            )
        )

    def _print_learnings(self, analysis: DayAnalysis):
        if not analysis.insights:
            return

        text = Text()
        for insight in analysis.insights:
            if insight.startswith("+") or "captured" in insight.lower():
                text.append(f"  + {insight}\n", style="green")
            elif insight.startswith("-") or "poor" in insight.lower() or "losing" in insight.lower():
                text.append(f"  - {insight}\n", style="red")
            elif insight.startswith("!") or "consider" in insight.lower():
                text.append(f"  ! {insight}\n", style="yellow")
            else:
                text.append(f"  * {insight}\n", style="white")

        self._console.print(
            Panel(text, title="[bold]LEARNINGS[/bold]", border_style="cyan")
        )

    def _print_streak_panel(self, streak: Streak):
        color = "green" if streak.type == "W" else "red"
        self._console.print(
            Panel(
                f"[{color}]{streak.count}{streak.type}[/{color}] streak "
                f"({streak.pnl_during:+,.0f})",
                title="[bold]CURRENT STREAK[/bold]",
                border_style=color,
            )
        )

    def _print_weekly_panel(self, weekly):
        table = Table(show_header=False, expand=True)
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value")

        pnl_color = "green" if weekly.total_pnl >= 0 else "red"
        table.add_row("Week", f"{weekly.week_start} — {weekly.week_end}")
        table.add_row("P&L", f"[{pnl_color}]{weekly.total_pnl:+,.0f}[/{pnl_color}]")
        table.add_row("Trades", f"{weekly.trades} ({weekly.wins}W / {weekly.losses}L)")
        table.add_row("Win Rate", f"{weekly.win_rate:.0f}%")
        table.add_row("Best Day", f"[green]{weekly.best_day_pnl:+,.0f}[/green]")
        table.add_row("Worst Day", f"[red]{weekly.worst_day_pnl:+,.0f}[/red]")

        self._console.print(
            Panel(table, title="[bold]THIS WEEK[/bold]", border_style="blue")
        )

    def _print_monthly_panel(self, monthly):
        table = Table(show_header=False, expand=True)
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value")

        pnl_color = "green" if monthly.total_pnl >= 0 else "red"
        table.add_row("Month", monthly.month)
        table.add_row("P&L", f"[{pnl_color}]{monthly.total_pnl:+,.0f}[/{pnl_color}]")
        table.add_row("Trading Days", str(monthly.trading_days))
        table.add_row("Trades", f"{monthly.trades} ({monthly.wins}W / {monthly.losses}L)")
        table.add_row("Win Rate", f"{monthly.win_rate:.0f}%")
        table.add_row("Avg Daily", f"{monthly.avg_daily_pnl:+,.0f}")
        if monthly.max_drawdown < 0:
            table.add_row("Max Drawdown", f"[red]{monthly.max_drawdown:,.0f}[/red]")

        self._console.print(
            Panel(table, title="[bold]THIS MONTH[/bold]", border_style="magenta")
        )
