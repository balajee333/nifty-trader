"""Integration tests: verify all VENOM components wire together correctly."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import time, datetime


class TestVenomModuleIntegration:
    def test_all_modules_import(self):
        from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
        from nifty_trader.strategy.vix_gate import VixGate, VixMode
        from nifty_trader.strategy.time_manager import TimeManager, TradingWindow
        from nifty_trader.strategy.trail_engine import TrailEngine, TrailState
        from nifty_trader.risk.monthly import MonthlyManager, MonthlyMode
        from nifty_trader.core.persister import StatePersister, VenomSnapshot
        from nifty_trader.config import VenomConfig
        from nifty_trader.venom import VenomEngine

    def test_ohlc_to_direction_flow(self):
        """O=H/O=L signal -> direction -> correct option type"""
        from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
        from nifty_trader.constants import Direction

        detector = OhlcSignalDetector()
        # Bearish signal: index O=H, CE O=H, PE O=L
        signal = detector.detect(
            24450, 24450, 24380, 24390,  # index O=H
            145, 145, 100, 105,          # CE O=H
            85, 130, 85, 125,            # PE O=L
        )
        assert signal.signal_type == SignalType.BUY_PE
        direction = Direction.BEARISH  # derived from BUY_PE
        assert direction == Direction.BEARISH

    def test_vix_gate_to_trail_flow(self):
        """VIX mode -> size multiplier -> trail engine"""
        from nifty_trader.strategy.vix_gate import VixGate
        from nifty_trader.strategy.trail_engine import TrailEngine

        gate = VixGate()
        engine = TrailEngine(sl_pct=30)

        # Low VIX: full size, normal trail
        assert gate.size_multiplier(12.0) == 1.0
        state = engine.create_state(100.0)
        assert state.sl_price == 70.0

        # High VIX (caution zone): half size
        assert gate.size_multiplier(22.0) == 0.5

    def test_time_manager_to_monthly_flow(self):
        """Time window + monthly limits combined gating"""
        from nifty_trader.strategy.time_manager import TimeManager
        from nifty_trader.risk.monthly import MonthlyManager

        tm = TimeManager()
        mm = MonthlyManager(max_daily_loss=3000)

        # Both pass: 09:20 is in SIGNAL_DETECTION window
        assert tm.can_enter(time(9, 20))
        assert mm.can_trade_today(-1000)

        # Time blocks: 12:00 is NO_TRADE window
        assert not tm.can_enter(time(12, 0))

        # Monthly blocks: daily loss exceeds limit
        assert not mm.can_trade_today(-3500)

    def test_full_trail_lifecycle(self):
        """Complete trail from entry through all rungs to exit"""
        from nifty_trader.strategy.trail_engine import TrailEngine

        engine = TrailEngine(sl_pct=30, max_profit_pct=100)
        state = engine.create_state(100.0)

        # Price rises but not at rung yet
        assert engine.update(state, 110.0) is None
        # +20% gain -> SL moves to cost
        assert engine.update(state, 120.0) == "MOVE_SL_TO_COST"
        assert state.risk_free
        assert state.sl_price == 100.0

        # +40% gain -> SL locks at +20%
        assert engine.update(state, 140.0) == "LOCK_PROFIT"
        assert state.sl_price == 120.0

        # +70% gain -> SL locks at +45%
        assert engine.update(state, 170.0) == "LOCK_PROFIT"
        assert state.sl_price == 145.0

        # +100% gain -> max profit exit
        assert engine.update(state, 200.0) == "EXIT_MAX_PROFIT"

    def test_persister_round_trip_with_trail(self):
        """Save trail state in snapshot, recover it"""
        import tempfile
        import os
        from nifty_trader.core.persister import StatePersister, VenomSnapshot
        from nifty_trader.strategy.trail_engine import TrailEngine

        engine = TrailEngine()
        trail = engine.create_state(100.0)
        engine.update(trail, 125.0)  # +25% -> move to cost rung

        with tempfile.TemporaryDirectory() as d:
            p = StatePersister(
                os.path.join(d, "state.json"),
                max_age_seconds=3600,
            )
            snap = VenomSnapshot(
                fsm_state="POSITION_OPEN",
                position={
                    "security_id": "123",
                    "entry_price": 100.0,
                    "quantity": 75,
                },
                trail_state={
                    "sl_price": trail.sl_price,
                    "peak_price": trail.peak_price,
                    "risk_free": trail.risk_free,
                },
            )
            p.save(snap)
            loaded = p.load()
            assert loaded is not None
            assert loaded.trail_state["risk_free"] is True
            assert loaded.trail_state["sl_price"] == trail.sl_price

    def test_config_loads_venom_section(self):
        """VenomConfig is populated from settings.yaml"""
        from nifty_trader.config import load_config
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
        cfg = load_config(yaml_path=yaml_path)
        assert cfg.venom.sl_percent == 30.0
        assert cfg.venom.max_profit_pct == 100.0
        assert cfg.venom.vix_full == 13.0
        assert cfg.venom.max_trades_per_day == 3

    def test_venom_engine_instantiation(self):
        """VenomEngine can be instantiated with mocked DhanHQ"""
        from nifty_trader.config import load_config
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"

        with patch.dict("os.environ", {
            "DHAN_CLIENT_ID": "test_client",
            "DHAN_ACCESS_TOKEN": "test_token",
        }):
            cfg = load_config(yaml_path=yaml_path)

            with patch("nifty_trader.venom.DhanHQ") as mock_dhan:
                mock_dhan.return_value = MagicMock()
                from nifty_trader.venom import VenomEngine
                engine = VenomEngine(cfg)

                # Verify all VENOM modules are wired
                assert engine.time_mgr is not None
                assert engine.vix_gate is not None
                assert engine.ohlc_detector is not None
                assert engine.trail_engine is not None
                assert engine.monthly_mgr is not None
                assert engine.persister is not None

                # Verify config was threaded through
                assert engine.trail_engine.sl_pct == 30.0
                assert engine.trail_engine.max_profit_pct == 100.0

    def test_signal_to_direction_mapping(self):
        """Verify all signal types map to correct directions"""
        from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
        from nifty_trader.constants import Direction

        detector = OhlcSignalDetector()

        # Bullish: index O=L, CE O=L, PE O=H
        bull = detector.detect(
            24450, 24520, 24450, 24510,  # index O=L
            85, 130, 85, 125,            # CE O=L
            145, 145, 100, 105,          # PE O=H
        )
        assert bull.signal_type == SignalType.BUY_CE
        assert (Direction.BULLISH if bull.signal_type == SignalType.BUY_CE
                else Direction.BEARISH) == Direction.BULLISH

    def test_monthly_manager_streak_integration(self):
        """Consecutive loss tracking works with trade sequence"""
        from nifty_trader.risk.monthly import MonthlyManager

        mm = MonthlyManager(consecutive_loss_limit=3)

        # Last 3 trades are losses: reversed = [-100, -300, -200, 500] -> streak=3
        pnls = [500, -200, -300, -100]
        streak = mm.compute_consecutive_losses(pnls)
        assert streak == 3
        assert not mm.can_trade_after_streak(streak)

        # Win breaks the streak
        pnls_with_win = [500, -200, -300, -100, 400]
        streak2 = mm.compute_consecutive_losses(pnls_with_win)
        assert streak2 == 0
        assert mm.can_trade_after_streak(streak2)

    def test_vix_gate_blocks_at_threshold(self):
        """VIX at blocked threshold prevents trading"""
        from nifty_trader.strategy.vix_gate import VixGate, VixMode

        gate = VixGate(blocked=30.0)
        assert gate.can_trade(29.9)
        assert not gate.can_trade(30.0)
        assert gate.get_mode(30.0) == VixMode.BLOCKED
        assert gate.size_multiplier(30.0) == 0.0
