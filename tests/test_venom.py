"""Tests for the VenomEngine orchestrator."""

from __future__ import annotations

from datetime import datetime, time as dtime
from unittest.mock import MagicMock, patch

import pytest


def _make_config():
    """Build an AppConfig with all defaults (no network, no .env)."""
    from nifty_trader.config import (
        AppConfig,
        DataConfig,
        InstrumentConfig,
        NotificationConfig,
        RiskConfig,
        SpreadConfig,
        StrikeConfig,
        StrategyConfig,
        TimingConfig,
        VenomConfig,
    )

    return AppConfig(
        dhan_client_id="test_client",
        dhan_access_token="test_token",
        dhan_base_url="",
        telegram_bot_token="",
        telegram_chat_id="",
        paper_mode=True,
        strategy_mode="directional",
        instrument=InstrumentConfig(),
        strategy=StrategyConfig(),
        risk=RiskConfig(capital=100_000),
        strike=StrikeConfig(),
        spread=SpreadConfig(),
        timing=TimingConfig(),
        data=DataConfig(),
        notifications=NotificationConfig(),
        venom=VenomConfig(
            max_trades_per_day=3,
            max_daily_loss=3000,
            max_weekly_loss=8000,
            consecutive_loss_limit=3,
            vix_blocked=30.0,
        ),
    )


@pytest.fixture
def engine():
    """Create a VenomEngine with mocked DhanHQ client."""
    with patch("nifty_trader.venom.DhanHQ") as MockDhan:
        mock_dhan = MagicMock()
        MockDhan.return_value = mock_dhan
        mock_dhan.client_id = "test_client"
        mock_dhan.access_token = "test_token"

        config = _make_config()

        from nifty_trader.venom import VenomEngine
        eng = VenomEngine(config)
        yield eng


class TestVenomEngineInit:
    """VenomEngine initializes all components."""

    def test_all_components_created(self, engine):
        assert engine.fsm is not None
        assert engine.risk_mgr is not None
        assert engine.tracker is not None
        assert engine.journal is not None
        assert engine.notifier is not None
        assert engine.validator is not None
        assert engine.order_mgr is not None
        assert engine.kill_switch is not None
        assert engine.dashboard is not None
        assert engine.feed is not None
        assert engine.hist_fetcher is not None
        assert engine.chain_fetcher is not None

    def test_venom_modules_created(self, engine):
        assert engine.time_mgr is not None
        assert engine.vix_gate is not None
        assert engine.ohlc_detector is not None
        assert engine.trail_engine is not None
        assert engine.monthly_mgr is not None
        assert engine.persister is not None

    def test_initial_state_is_idle(self, engine):
        assert engine.fsm.is_idle

    def test_paper_mode(self, engine):
        assert engine.cfg.paper_mode is True


class TestPreEntryChecks:
    """_pre_entry_checks() gating logic."""

    def test_blocks_on_high_vix(self, engine):
        """VIX >= 30 (blocked mode) should block entry."""
        engine._vix = 35.0
        # Set time to a valid entry window
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_blocks_outside_entry_window(self, engine):
        """Outside entry window (e.g., 15:00) should block entry."""
        engine._vix = 12.0
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(15, 0)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_blocks_after_daily_loss_limit(self, engine):
        """Daily P&L below -max_daily_loss should block entry."""
        engine._vix = 12.0
        engine._daily_pnl = -4000.0  # Exceeds max_daily_loss of 3000
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_blocks_after_consecutive_losses(self, engine):
        """3 consecutive losses should block entry."""
        engine._vix = 12.0
        engine._consecutive_losses = 3
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_blocks_after_max_trade_count(self, engine):
        """Reaching max_trades_per_day (3) should block entry."""
        engine._vix = 12.0
        engine._trade_count = 3
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_passes_when_all_clear(self, engine):
        """All gates clear -> should allow entry."""
        engine._vix = 12.0
        engine._daily_pnl = 0.0
        engine._weekly_pnl = 0.0
        engine._consecutive_losses = 0
        engine._trade_count = 0
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is True

    def test_blocks_after_weekly_loss_limit(self, engine):
        """Weekly P&L below -max_weekly_loss should block entry."""
        engine._vix = 12.0
        engine._weekly_pnl = -9000.0  # Exceeds max_weekly_loss of 8000
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False

    def test_blocks_when_kill_switch_triggered(self, engine):
        """Kill switch triggered should block entry."""
        engine._vix = 12.0
        engine.kill_switch._triggered = True
        with patch("nifty_trader.venom.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.time.return_value = dtime(9, 30)
            mock_dt.now.return_value = mock_now
            result = engine._pre_entry_checks()
        assert result is False


class TestTrailIntegration:
    """Trail engine integration with position monitoring."""

    def test_trail_state_created_on_entry(self, engine):
        state = engine.trail_engine.create_state(100.0)
        assert state.entry_price == 100.0
        assert state.sl_price == 70.0  # 30% SL default
        assert state.peak_price == 100.0

    def test_trail_sl_hit(self, engine):
        state = engine.trail_engine.create_state(100.0)
        action = engine.trail_engine.update(state, 60.0)
        assert action == "SL_HIT"

    def test_trail_max_profit(self, engine):
        state = engine.trail_engine.create_state(100.0)
        action = engine.trail_engine.update(state, 200.0)
        assert action == "EXIT_MAX_PROFIT"


class TestStatePersistence:
    """State save/load round-trip."""

    def test_save_and_recover(self, engine, tmp_path):
        engine.persister._path = str(tmp_path / "state.json")
        engine._daily_pnl = 500.0
        engine._trade_count = 2
        engine._consecutive_losses = 1
        engine._ohlc_signal_text = "buy_ce: test"

        engine._save_state()

        snap = engine.persister.load()
        assert snap is not None
        assert snap.daily_pnl == 500.0
        assert snap.trade_count == 2
        assert snap.consecutive_losses == 1
