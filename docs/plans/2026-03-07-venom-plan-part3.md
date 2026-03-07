# VENOM Implementation Plan — Part 3 (Tasks 9-10)

---

## Task 9: VENOM Orchestrator

**Files:**
- Create: `src/nifty_trader/venom.py`
- Modify: `src/nifty_trader/main.py` (add `--mode venom` flag)
- Test: `tests/test_venom.py`

**Step 1: Write failing test**

```python
# tests/test_venom.py
import pytest
from unittest.mock import MagicMock, patch
from nifty_trader.venom import VenomEngine

def test_venom_initializes_all_components():
    with patch("nifty_trader.venom.load_config") as mock_cfg:
        mock_cfg.return_value = _mock_config()
        engine = VenomEngine(config_path="config/settings.yaml", paper=True)
        assert engine.time_mgr is not None
        assert engine.vix_gate is not None
        assert engine.ohlc_detector is not None
        assert engine.trail_engine is not None
        assert engine.monthly_mgr is not None
        assert engine.persister is not None

def test_venom_blocks_on_high_vix():
    engine = _make_engine()
    engine._current_vix = 31.0
    assert not engine._pre_entry_checks()

def test_venom_blocks_outside_entry_window():
    engine = _make_engine()
    engine._current_vix = 12.0
    from datetime import time
    engine._current_time = time(12, 0)  # lunch hour
    assert not engine._pre_entry_checks()

def test_venom_blocks_after_daily_loss():
    engine = _make_engine()
    engine._current_vix = 12.0
    from datetime import time
    engine._current_time = time(9, 20)
    engine._daily_pnl = -3500.0
    assert not engine._pre_entry_checks()

def test_venom_blocks_after_3_consecutive_losses():
    engine = _make_engine()
    engine._current_vix = 12.0
    from datetime import time
    engine._current_time = time(9, 20)
    engine._consecutive_losses = 3
    assert not engine._pre_entry_checks()

def _mock_config():
    """Build a mock config with all required VENOM fields."""
    from nifty_trader.config import VenomConfig
    cfg = MagicMock()
    cfg.venom = VenomConfig()
    cfg.instrument.name = "NIFTY"
    cfg.instrument.security_id = 13
    cfg.instrument.lot_size = 75
    cfg.paper_mode = True
    return cfg

def _make_engine():
    with patch("nifty_trader.venom.load_config") as mock_cfg:
        mock_cfg.return_value = _mock_config()
        return VenomEngine(config_path="config/settings.yaml", paper=True)
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/venom.py
"""VENOM — Fully automated options scalping engine."""

import logging
import time as _time
from datetime import datetime, time, timedelta

from nifty_trader.config import load_config, AppConfig
from nifty_trader.constants import Direction, ExchangeSegment, TradeState
from nifty_trader.state import TradeFSM
from nifty_trader.data.feed import MarketFeedManager
from nifty_trader.data.option_chain import OptionChainFetcher
from nifty_trader.data.historical import HistoricalDataFetcher
from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
from nifty_trader.strategy.vix_gate import VixGate
from nifty_trader.strategy.time_manager import TimeManager
from nifty_trader.strategy.trail_engine import TrailEngine
from nifty_trader.strategy.confluence import evaluate_confluence
from nifty_trader.strategy.strike_selector import select_strike
from nifty_trader.orders.manager import OrderManager
from nifty_trader.orders.tracker import OrderTracker
from nifty_trader.risk.manager import RiskManager
from nifty_trader.risk.kill_switch import KillSwitch
from nifty_trader.risk.validator import OrderValidator
from nifty_trader.risk.monthly import MonthlyManager
from nifty_trader.core.persister import StatePersister, VenomSnapshot
from nifty_trader.journal.database import TradeJournal
from nifty_trader.dashboard.console import Dashboard
from nifty_trader.alerts.notifier import Notifier

log = logging.getLogger(__name__)

INDIA_VIX_SECURITY_ID = 26  # India VIX on NSE

class VenomEngine:
    def __init__(self, config_path: str = "config/settings.yaml", paper: bool = False):
        self.cfg = load_config(config_path)
        if paper:
            self.cfg = self.cfg  # paper_mode set via .env
        v = self.cfg.venom

        # Core state
        self.fsm = TradeFSM()
        self.tracker = OrderTracker()
        self._daily_pnl = 0.0
        self._trade_count = 0
        self._consecutive_losses = 0
        self._current_vix = 0.0
        self._current_time = None
        self._ohlc_signal = None
        self._trail_state = None

        # VENOM components
        self.time_mgr = TimeManager(time_stop_minutes=v.time_stop_minutes)
        self.vix_gate = VixGate(
            full=v.vix_full, selective=v.vix_selective,
            caution=v.vix_caution, blocked=v.vix_blocked,
            delta_low=v.target_delta_low_vix, delta_high=v.target_delta_high_vix,
        )
        self.ohlc_detector = OhlcSignalDetector(
            index_tolerance_pct=v.ohlc_tolerance_index_pct,
            option_tolerance_abs=v.ohlc_tolerance_option_abs,
        )
        self.trail_engine = TrailEngine(
            sl_pct=v.sl_percent, activation_pct=v.trail_activation_pct,
            trail_distance_pct=v.trail_distance_pct, max_profit_pct=v.max_profit_pct,
        )
        self.monthly_mgr = MonthlyManager(
            max_daily_loss=v.max_daily_loss, max_weekly_loss=v.max_weekly_loss,
            consecutive_loss_limit=v.consecutive_loss_limit,
            mtd_protection_threshold=v.mtd_protection_threshold,
            mtd_stop_threshold=v.mtd_stop_threshold,
        )
        self.persister = StatePersister()

        # Existing infrastructure
        self.feed = MarketFeedManager(self.cfg)
        self.chain = OptionChainFetcher(self.cfg)
        self.historical = HistoricalDataFetcher(self.cfg)
        self.order_mgr = OrderManager(self.cfg, self.tracker)
        self.risk_mgr = RiskManager(self.cfg)
        self.kill_switch = KillSwitch(self.cfg, self.order_mgr, self.tracker)
        self.validator = OrderValidator(self.cfg, self.risk_mgr, self.tracker)
        self.journal = TradeJournal(self.cfg)
        self.dashboard = Dashboard(instrument_name=self.cfg.instrument.name)
        self.notifier = Notifier(self.cfg)

    def _pre_entry_checks(self) -> bool:
        """All gates must pass before any entry."""
        # VIX gate
        if not self.vix_gate.can_trade(self._current_vix):
            return False
        # Time window
        t = self._current_time or datetime.now().time()
        if not self.time_mgr.can_enter(t):
            return False
        # Daily loss
        if not self.monthly_mgr.can_trade_today(self._daily_pnl):
            return False
        # Consecutive losses
        if not self.monthly_mgr.can_trade_after_streak(self._consecutive_losses):
            return False
        # Trade count
        if self._trade_count >= self.cfg.venom.max_trades_per_day:
            return False
        return True

    def run(self):
        """Main event loop — called from CLI."""
        log.info("VENOM engine starting...")
        self._try_recover()
        self.feed.start()
        self.notifier.info("VENOM started")

        try:
            while True:
                now = datetime.now()
                self._current_time = now.time()

                # Force exit at 15:15
                if self.time_mgr.should_force_exit(self._current_time):
                    if self.fsm.has_position:
                        self._force_exit("Market close")
                    if self._current_time >= time(15, 30):
                        break

                # Update VIX
                vix_data = self.feed.get_ltp(INDIA_VIX_SECURITY_ID)
                if vix_data:
                    self._current_vix = vix_data.get("ltp", self._current_vix)

                # Kill switch
                self.kill_switch.check(self._daily_pnl, self.fsm)

                # State machine
                if self.fsm.is_idle and not self.fsm.has_position:
                    self._scan_for_entry(now)
                elif self.fsm.has_position:
                    self._monitor_position(now)

                # Update dashboard
                self._update_dashboard()

                # Persist state
                self._persist()

                _time.sleep(1)  # 1-second tick loop

        except KeyboardInterrupt:
            log.info("VENOM stopped by user")
        finally:
            self._shutdown()

    def _scan_for_entry(self, now: datetime):
        """Check O=H/O=L signal, confirmations, and enter if valid."""
        if not self._pre_entry_checks():
            return

        # O=H/O=L detection at 9:16
        if self._ohlc_signal is None and self._current_time >= time(9, 16):
            self._detect_ohlc()

        if self._ohlc_signal is None:
            return
        if self._ohlc_signal.signal_type in (SignalType.WAIT, SignalType.NO_TRADE):
            return

        # Determine direction
        direction = (Direction.BULLISH if self._ohlc_signal.signal_type == SignalType.BUY_CE
                     else Direction.BEARISH)

        # Run confluence confirmations
        df = self.historical.get_intraday_5min(
            self.cfg.instrument.security_id,
            self.cfg.instrument.exchange_segment,
        )
        if df is None or df.empty:
            return

        from nifty_trader.strategy.levels import LevelDetector
        daily_df = self.historical.get_daily(
            self.cfg.instrument.security_id,
            self.cfg.instrument.exchange_segment,
        )
        level_det = LevelDetector(daily_df)
        result = evaluate_confluence(df, level_det, self.cfg.strategy)

        if not result.triggered:
            return
        if result.direction != direction:
            return

        # VIX-adjusted confirmation threshold
        min_conf = self.vix_gate.min_confirmations(self._current_vix)
        confirmed_count = sum(1 for s in result.signals if s.direction == direction)
        if confirmed_count < min_conf:
            return

        # Select strike
        expiry = self.chain.nearest_weekly_expiry(self.cfg.instrument.security_id)
        contracts = self.chain.get_chain(expiry, self.cfg.instrument.security_id)
        target_delta = self.vix_gate.target_delta(self._current_vix)
        strike = select_strike(contracts, direction, self.cfg.strike)

        if strike is None:
            return

        # Position sizing with VIX multiplier
        size = self.risk_mgr.compute_position_size(strike.contract.ltp)
        size_mult = self.vix_gate.size_multiplier(self._current_vix)
        qty = max(self.cfg.instrument.lot_size,
                  int(size.quantity * size_mult))

        # Validate
        if not self.validator.validate(strike.contract.security_id, strike.contract.ltp):
            return

        # Place order
        order_id = self.order_mgr.place_market_buy(
            strike.contract.security_id, qty)
        if order_id is None:
            return

        # FSM transitions
        self.fsm.start_signal(direction, result.score,
                              str([s.name for s in result.signals]))
        self.fsm.order_placed(order_id, strike.contract.security_id,
                              strike.contract.strike_price, expiry, qty)

        # Assume fill at LTP for now (tracker will reconcile)
        fill_price = strike.contract.ltp
        trail = self.trail_engine.create_state(fill_price)
        self._trail_state = trail
        self.fsm.position_opened(fill_price, self.risk_mgr.create_trailing_state(fill_price))

        # Place SL order
        sl_oid = self.order_mgr.place_sl_order(
            strike.contract.security_id, qty, trail.sl_price)

        self._trade_count += 1
        self.notifier.trade_entry(
            f"{direction.value} {strike.contract.strike_price} "
            f"{'CE' if direction == Direction.BULLISH else 'PE'} "
            f"@ {fill_price} | SL: {trail.sl_price:.1f}")

        self.journal.log_event("ENTRY", f"VENOM entry: {strike.contract.strike_price}")

    def _detect_ohlc(self):
        """Fetch first candle OHLC and run O=H/O=L detection."""
        # Get index first candle
        idx_data = self.historical.get_intraday_5min(
            self.cfg.instrument.security_id,
            self.cfg.instrument.exchange_segment,
        )
        if idx_data is None or len(idx_data) < 1:
            return

        first = idx_data.iloc[0]
        idx_open, idx_high = first["open"], first["high"]
        idx_low, idx_close = first["low"], first["close"]

        # Get ATM option first candles (approximate from option chain)
        spot = idx_close
        chain = self.chain.get_chain(
            self.chain.nearest_weekly_expiry(self.cfg.instrument.security_id),
            self.cfg.instrument.security_id,
        )
        # Find nearest CE and PE
        atm_ce = min([c for c in chain if c.option_type == "CALL"],
                     key=lambda c: abs(c.strike_price - spot), default=None)
        atm_pe = min([c for c in chain if c.option_type == "PUT"],
                     key=lambda c: abs(c.strike_price - spot), default=None)

        if not atm_ce or not atm_pe:
            return

        # Use LTP as proxy for close, bid/ask for range estimate
        # For precise O=H/O=L we need option intraday candles
        # Fetch 1-min candle for ATM CE and PE
        ce_data = self.historical.get_intraday_5min(
            atm_ce.security_id, ExchangeSegment.NSE_FNO.value)
        pe_data = self.historical.get_intraday_5min(
            atm_pe.security_id, ExchangeSegment.NSE_FNO.value)

        if ce_data is None or pe_data is None or ce_data.empty or pe_data.empty:
            # Fallback: use option chain snapshot
            self._ohlc_signal = self.ohlc_detector.detect(
                idx_open, idx_high, idx_low, idx_close,
                atm_ce.ltp, atm_ce.ltp, atm_ce.ltp * 0.95, atm_ce.ltp,
                atm_pe.ltp, atm_pe.ltp, atm_pe.ltp * 0.95, atm_pe.ltp,
            )
            return

        ce_first = ce_data.iloc[0]
        pe_first = pe_data.iloc[0]
        self._ohlc_signal = self.ohlc_detector.detect(
            idx_open, idx_high, idx_low, idx_close,
            ce_first["open"], ce_first["high"], ce_first["low"], ce_first["close"],
            pe_first["open"], pe_first["high"], pe_first["low"], pe_first["close"],
        )
        log.info(f"O=H/O=L signal: {self._ohlc_signal}")
        self.notifier.info(f"Signal: {self._ohlc_signal.signal_type.value} — {self._ohlc_signal.reason}")

    def _monitor_position(self, now: datetime):
        """Trail SL, check time stop, check targets."""
        if self._trail_state is None:
            return

        ctx = self.fsm.ctx
        sec_id = ctx.security_id
        ltp_data = self.feed.get_ltp(sec_id)
        if not ltp_data:
            ltp_data = {"ltp": self.feed.fetch_ltp_rest(sec_id, ExchangeSegment.NSE_FNO.value)}
        current_price = ltp_data.get("ltp", 0)
        if current_price <= 0:
            return

        # Time-based stop
        pnl_pct = (current_price - ctx.entry_price) / ctx.entry_price * 100
        if self.time_mgr.time_stop_hit(ctx.entry_time, now, pnl_pct):
            self._exit_position(current_price, "Time stop — flat after 20 min")
            return

        # Force exit
        if self.time_mgr.should_force_exit(self._current_time):
            self._exit_position(current_price, "Market close force exit")
            return

        # Trail engine update
        action = self.trail_engine.update(self._trail_state, current_price)

        if action == "SL_HIT":
            self._exit_position(current_price, "SL hit")
        elif action == "EXIT_MAX_PROFIT":
            self._exit_position(current_price, f"Max profit (+{self.cfg.venom.max_profit_pct}%)")
        elif action in ("MOVE_SL_TO_COST", "LOCK_PROFIT", "TRAILING"):
            # Modify SL order
            # Find the SL order ID from tracker
            for oid, rec in self.tracker._orders.items():
                if rec.security_id == sec_id and rec.status == "PENDING":
                    self.order_mgr.modify_sl_trigger(oid, self._trail_state.sl_price)
                    break
            if action == "MOVE_SL_TO_COST":
                self.notifier.info(f"SL moved to cost: {self._trail_state.sl_price:.1f}")

    def _exit_position(self, exit_price: float, reason: str):
        """Exit current position."""
        ctx = self.fsm.ctx
        order_id = self.order_mgr.place_market_sell(ctx.security_id, ctx.quantity)
        self.fsm.position_closed(exit_price)

        pnl = (exit_price - ctx.entry_price) * ctx.quantity
        self._daily_pnl += pnl
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        self.journal.log_trade(ctx)
        self.notifier.trade_exit(
            f"Exit @ {exit_price:.1f} | Reason: {reason} | "
            f"PnL: {'+'if pnl>0 else ''}{pnl:.0f}")

        self._trail_state = None
        self.fsm.reset()

    def _force_exit(self, reason: str):
        """Force exit any open position."""
        ctx = self.fsm.ctx
        ltp = self.feed.get_ltp(ctx.security_id)
        price = ltp.get("ltp", ctx.entry_price) if ltp else ctx.entry_price
        self._exit_position(price, reason)

    def _update_dashboard(self):
        ohlc_text = None
        if self._ohlc_signal:
            ohlc_text = f"{self._ohlc_signal.signal_type.value}: {self._ohlc_signal.reason}"
        trail_text = None
        if self._trail_state:
            status = "RISK-FREE" if self._trail_state.risk_free else "ACTIVE"
            trail_text = f"SL: {self._trail_state.sl_price:.1f} ({status})"

        self.dashboard.update(
            fsm=self.fsm,
            nifty_price=0,  # filled from feed
            daily_pnl=self._daily_pnl,
            trade_count=self._trade_count,
            signals_text=ohlc_text or "Waiting...",
            system_status="LIVE",
            vix=self._current_vix,
            vix_mode=self.vix_gate.get_mode(self._current_vix).value,
            ohlc_signal=ohlc_text,
            trail_status=trail_text,
        )

    def _persist(self):
        ctx = self.fsm.ctx
        pos = None
        trail = None
        if self.fsm.has_position:
            pos = {"security_id": ctx.security_id, "entry_price": ctx.entry_price,
                   "quantity": ctx.quantity}
            if self._trail_state:
                trail = {"sl_price": self._trail_state.sl_price,
                         "peak_price": self._trail_state.peak_price,
                         "risk_free": self._trail_state.risk_free}
        snap = VenomSnapshot(
            fsm_state=self.fsm.state.value,
            position=pos, daily_pnl=self._daily_pnl,
            trade_count=self._trade_count,
            consecutive_losses=self._consecutive_losses,
            trail_state=trail,
        )
        self.persister.save(snap)

    def _try_recover(self):
        snap = self.persister.load()
        if snap and snap.fsm_state != "IDLE" and snap.position:
            log.warning(f"Recovering from state: {snap.fsm_state}")
            self._daily_pnl = snap.daily_pnl
            self._trade_count = snap.trade_count
            self._consecutive_losses = snap.consecutive_losses
            self.notifier.warning(f"Crash recovery: state={snap.fsm_state}")
            # TODO: reconcile with API positions

    def _shutdown(self):
        self.feed.stop()
        self.persister.clear()
        self.journal.close()
        self.notifier.info("VENOM shutdown complete")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="VENOM Scalping Engine")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--paper", action="store_true", default=False)
    args = parser.parse_args()
    engine = VenomEngine(config_path=args.config, paper=args.paper)
    engine.run()

if __name__ == "__main__":
    main()
```

**Step 4: Run tests, verify pass**

**Step 5: Add CLI entry point to `pyproject.toml`**

Add under `[project.scripts]`:
```
venom = "nifty_trader.venom:main"
```

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: add VenomEngine orchestrator — full auto scalping loop"
```

---

## Task 10: Integration Test & Paper Mode Validation

**Files:**
- Create: `tests/test_venom_integration.py`
- Modify: `config/settings.yaml` (add venom section)

**Step 1: Write integration test**

```python
# tests/test_venom_integration.py
"""Integration test: verify all VENOM components wire together."""
import pytest
from unittest.mock import MagicMock, patch
from nifty_trader.venom import VenomEngine
from nifty_trader.strategy.ohlc_signal import SignalType
from nifty_trader.strategy.vix_gate import VixMode
from nifty_trader.strategy.time_manager import TradingWindow
from datetime import time

class TestVenomIntegration:

    def _engine(self):
        with patch("nifty_trader.venom.load_config") as mock:
            from nifty_trader.config import VenomConfig
            cfg = MagicMock()
            cfg.venom = VenomConfig()
            cfg.instrument.name = "NIFTY"
            cfg.instrument.security_id = 13
            cfg.instrument.lot_size = 75
            cfg.paper_mode = True
            mock.return_value = cfg
            return VenomEngine(paper=True)

    def test_all_gates_pass(self):
        e = self._engine()
        e._current_vix = 12.0
        e._current_time = time(9, 20)
        e._daily_pnl = 0
        e._consecutive_losses = 0
        e._trade_count = 0
        assert e._pre_entry_checks()

    def test_vix_blocks(self):
        e = self._engine()
        e._current_vix = 35.0
        e._current_time = time(9, 20)
        assert not e._pre_entry_checks()

    def test_lunch_blocks(self):
        e = self._engine()
        e._current_vix = 12.0
        e._current_time = time(12, 0)
        assert not e._pre_entry_checks()

    def test_trade_count_blocks(self):
        e = self._engine()
        e._current_vix = 12.0
        e._current_time = time(9, 20)
        e._trade_count = 3
        assert not e._pre_entry_checks()

    def test_trail_engine_integrates(self):
        e = self._engine()
        state = e.trail_engine.create_state(100.0)
        assert state.sl_price == 70.0
        action = e.trail_engine.update(state, 125.0)
        assert state.risk_free
        assert state.sl_price == 100.0
```

**Step 2: Run all tests**

```bash
cd /Users/balajrajendran/projects/nifty-trader
python -m pytest tests/ -v --tb=short
```

**Step 3: Add venom section to settings.yaml**

Append to `config/settings.yaml`:

```yaml
venom:
  ohlc_tolerance_index_pct: 0.05
  ohlc_tolerance_option_abs: 0.50
  min_confirmations: 3
  vix_full: 13.0
  vix_selective: 18.0
  vix_caution: 23.0
  vix_restricted: 30.0
  vix_blocked: 30.0
  entry_window_start: "09:16"
  entry_window_end: "14:30"
  no_trade_start: "11:30"
  no_trade_end: "13:30"
  signal_detection_end: "09:20"
  target_delta_low_vix: 0.50
  target_delta_high_vix: 0.65
  max_premium_nifty: 265.0
  max_premium_banknifty: 660.0
  sl_percent: 30.0
  trail_activation_pct: 20.0
  trail_distance_pct: 15.0
  max_profit_pct: 100.0
  time_stop_minutes: 20
  max_trades_per_day: 3
  max_daily_loss: 3000.0
  max_weekly_loss: 8000.0
  consecutive_loss_limit: 3
  mtd_protection_threshold: 12000.0
  mtd_protection_size_reduction: 0.30
  mtd_stop_threshold: -5000.0
  mtd_stop_days: 3
  mtd_resume_size_reduction: 0.50
```

**Step 4: Final commit**

```bash
git add -A && git commit -m "feat: add integration tests and VENOM config to settings.yaml"
```

---

## Execution Order Summary

| Task | Module | Depends On | Est. Complexity |
|------|--------|------------|-----------------|
| 1 | VenomConfig | — | Small |
| 2 | TimeManager | — | Small |
| 3 | VixGate | — | Small |
| 4 | OhlcSignalDetector | — | Medium |
| 5 | TrailEngine | — | Medium |
| 6 | MonthlyManager | — | Small |
| 7 | StatePersister | — | Small |
| 8 | Dashboard enhancements | — | Small |
| 9 | VenomEngine orchestrator | Tasks 1-8 | Large |
| 10 | Integration tests | Task 9 | Medium |

Tasks 1-8 are independent and can be parallelized. Task 9 depends on all of them. Task 10 validates the full system.

## Post-Implementation: Paper Trading Checklist

After all tasks are complete:

1. `pip install -e .` in the venv
2. Set `PAPER_MODE=true` in `.env`
3. Run: `venom --config config/settings.yaml --paper`
4. Verify dashboard renders at 9:00
5. Verify VIX gate blocks/allows correctly
6. Verify O=H/O=L detection fires at 9:16
7. Verify paper orders are placed
8. Verify trail engine moves SL
9. Verify force exit at 15:15
10. Run for 5 full trading days before going live
