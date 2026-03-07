"""Live terminal dashboard using Rich."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nifty_trader.constants import OptionType, TradeState
from nifty_trader.state import TradeFSM


class Dashboard:
    """Rich-based live terminal dashboard."""

    def __init__(self, instrument_name: str = "NIFTY"):
        self._console = Console()
        self._live: Live | None = None
        self._instrument_name = instrument_name
        self._spot_price: float = 0.0
        self._daily_pnl: float = 0.0
        self._trade_count: int = 0
        self._signals_text: str = "Waiting..."
        self._system_status: str = "Starting"
        self._position_info: str = "No position"
        self._last_update: str = ""
        # VENOM enhancements
        self._vix: float = 0.0
        self._vix_mode: str = ""
        self._ohlc_signal: str = ""
        self._monthly_pnl: float = 0.0
        self._weekly_pnl: float = 0.0
        self._win_rate: float = 0.0
        self._avg_wl_ratio: float = 0.0
        self._trail_status: str = ""

    def update(
        self,
        fsm: TradeFSM,
        nifty_price: float = 0.0,
        daily_pnl: float = 0.0,
        trade_count: int = 0,
        signals_text: str = "",
        system_status: str = "",
        vix: float = 0.0,
        vix_mode: str = "",
        ohlc_signal: str = "",
        monthly_pnl: float = 0.0,
        weekly_pnl: float = 0.0,
        win_rate: float = 0.0,
        avg_wl_ratio: float = 0.0,
        trail_status: str = "",
    ):
        self._spot_price = nifty_price
        self._daily_pnl = daily_pnl
        self._trade_count = trade_count
        if signals_text:
            self._signals_text = signals_text
        if system_status:
            self._system_status = system_status
        self._last_update = datetime.now().strftime("%H:%M:%S")
        # VENOM params
        self._vix = vix
        self._vix_mode = vix_mode
        self._ohlc_signal = ohlc_signal
        self._monthly_pnl = monthly_pnl
        self._weekly_pnl = weekly_pnl
        self._win_rate = win_rate
        self._avg_wl_ratio = avg_wl_ratio
        self._trail_status = trail_status

        if fsm.has_position:
            ctx = fsm.ctx
            if ctx.is_spread:
                type_char = "P" if ctx.option_type == OptionType.PUT else "C"
                self._position_info = (
                    f"SPREAD: SELL {ctx.short_strike_price:.0f}{type_char} "
                    f"/ BUY {ctx.long_strike_price:.0f}{type_char} | "
                    f"Credit: {ctx.net_credit:.2f} | MaxL: {ctx.max_loss:.2f} | "
                    f"Qty: {ctx.quantity}"
                )
            else:
                self._position_info = (
                    f"{ctx.option_type.value} @ {ctx.strike_price:.0f} | "
                    f"Entry: {ctx.entry_price:.2f} | Qty: {ctx.quantity}"
                )
        else:
            self._position_info = "No position"

    def render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._header_panel(), size=3),
            Layout(name="body", ratio=1),
            Layout(name="bottom", size=8),
            Layout(self._footer_panel(), size=3),
        )
        layout["body"].split_row(
            Layout(self._market_panel(), ratio=1),
            Layout(self._position_panel(), ratio=1),
            Layout(self._signals_panel(), ratio=1),
        )
        layout["bottom"].split_row(
            Layout(self._signal_detail_panel(), ratio=1),
            Layout(self._monthly_stats_panel(), ratio=1),
        )
        return layout

    def _header_panel(self) -> Panel:
        pnl_color = "green" if self._daily_pnl >= 0 else "red"
        text = Text()
        text.append(f"{self._instrument_name} TRADER", style="bold white")
        text.append(f"  |  P&L: ", style="white")
        text.append(f"{self._daily_pnl:+.2f}", style=pnl_color)
        text.append(f"  |  Trades: {self._trade_count}", style="white")
        text.append(f"  |  {self._last_update}", style="dim")
        return Panel(text, style="blue")

    def _market_panel(self) -> Panel:
        table = Table(show_header=False, expand=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row(self._instrument_name, f"{self._spot_price:.2f}")
        table.add_row("Status", self._system_status)
        return Panel(table, title="Market", border_style="green")

    def _position_panel(self) -> Panel:
        return Panel(self._position_info, title="Position", border_style="yellow")

    def _signals_panel(self) -> Panel:
        return Panel(self._signals_text, title="Signals", border_style="magenta")

    def _signal_detail_panel(self) -> Panel:
        table = Table(show_header=False, expand=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        vix_color = "red" if self._vix > 20 else "green"
        table.add_row("VIX", f"[{vix_color}]{self._vix:.2f}[/{vix_color}]")
        table.add_row("VIX Mode", self._vix_mode or "-")
        table.add_row("O=H/O=L", self._ohlc_signal or "-")
        table.add_row("Trail", self._trail_status or "-")
        return Panel(table, title="Signal Detail", border_style="cyan")

    def _monthly_stats_panel(self) -> Panel:
        table = Table(show_header=False, expand=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        mtd_color = "green" if self._monthly_pnl >= 0 else "red"
        wtd_color = "green" if self._weekly_pnl >= 0 else "red"
        table.add_row("MTD P&L", f"[{mtd_color}]{self._monthly_pnl:+.2f}[/{mtd_color}]")
        table.add_row("Weekly P&L", f"[{wtd_color}]{self._weekly_pnl:+.2f}[/{wtd_color}]")
        table.add_row("Win Rate", f"{self._win_rate:.1f}%")
        table.add_row("Avg W/L", f"{self._avg_wl_ratio:.2f}")
        return Panel(table, title="Monthly Stats", border_style="blue")

    def _footer_panel(self) -> Panel:
        return Panel(
            "[dim]Press Ctrl+C to stop[/dim]",
            style="dim",
        )

    def start_live(self):
        self._live = Live(self.render(), console=self._console, refresh_per_second=1)
        self._live.start()

    def refresh(self, fsm: TradeFSM, **kwargs):
        self.update(fsm, **kwargs)
        if self._live:
            self._live.update(self.render())

    def stop(self):
        if self._live:
            self._live.stop()
