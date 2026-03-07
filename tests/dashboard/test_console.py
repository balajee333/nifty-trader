"""Tests for Dashboard VENOM enhancements."""

import pytest
from unittest.mock import MagicMock
from nifty_trader.dashboard.console import Dashboard
from nifty_trader.state import TradeFSM


@pytest.fixture
def fsm():
    mock = MagicMock(spec=TradeFSM)
    mock.has_position = False
    return mock


@pytest.fixture
def dashboard():
    return Dashboard(instrument_name="NIFTY")


class TestVenomParams:
    def test_update_accepts_new_params(self, dashboard, fsm):
        """Dashboard.update() should accept all VENOM params without error."""
        dashboard.update(
            fsm,
            nifty_price=24500.0,
            daily_pnl=1200.0,
            trade_count=5,
            signals_text="Bullish",
            system_status="Running",
            vix=14.5,
            vix_mode="NORMAL",
            ohlc_signal="O=L",
            monthly_pnl=8500.0,
            weekly_pnl=3200.0,
            win_rate=65.0,
            avg_wl_ratio=1.8,
            trail_status="TRAILING",
        )
        assert dashboard._vix == 14.5
        assert dashboard._vix_mode == "NORMAL"
        assert dashboard._ohlc_signal == "O=L"
        assert dashboard._monthly_pnl == 8500.0
        assert dashboard._weekly_pnl == 3200.0
        assert dashboard._win_rate == 65.0
        assert dashboard._avg_wl_ratio == 1.8
        assert dashboard._trail_status == "TRAILING"

    def test_render_with_venom_params(self, dashboard, fsm):
        """Render should work with VENOM params set."""
        dashboard.update(
            fsm,
            vix=22.0,
            vix_mode="HIGH",
            ohlc_signal="O=H",
            monthly_pnl=-2000.0,
            weekly_pnl=-500.0,
            win_rate=45.0,
            avg_wl_ratio=0.9,
            trail_status="MOVE_SL_TO_COST",
        )
        layout = dashboard.render()
        assert layout is not None

    def test_render_default_params(self, dashboard, fsm):
        """Render should work with default (zero) VENOM params."""
        dashboard.update(fsm)
        layout = dashboard.render()
        assert layout is not None

    def test_refresh_with_venom_kwargs(self, dashboard, fsm):
        """refresh() passes VENOM kwargs through to update()."""
        dashboard.refresh(fsm, vix=18.0, trail_status="LOCK_PROFIT")
        assert dashboard._vix == 18.0
        assert dashboard._trail_status == "LOCK_PROFIT"
