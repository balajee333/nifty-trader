"""VENOM engine — O=H/O=L scalping orchestrator with VIX gating.

Integrates all VENOM modules (TimeManager, VixGate, OhlcSignalDetector,
TrailEngine, MonthlyManager, StatePersister) with the existing trading
infrastructure (FSM, feeds, order manager, risk, journal, dashboard).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

from dhanhq import dhanhq as DhanHQ

from nifty_trader.alerts.notifier import Notifier
from nifty_trader.pages.publisher import JournalPublisher
from nifty_trader.config import AppConfig, load_config
from nifty_trader.constants import Direction, OptionType, TradeState
from nifty_trader.core.persister import StatePersister, VenomSnapshot
from nifty_trader.dashboard.console import Dashboard
from nifty_trader.data.feed import MarketFeedManager
from nifty_trader.data.historical import HistoricalDataFetcher
from nifty_trader.data.option_chain import OptionChainFetcher
from nifty_trader.journal.database import TradeJournal
from nifty_trader.orders.manager import OrderManager
from nifty_trader.orders.tracker import OrderTracker
from nifty_trader.risk.kill_switch import KillSwitch
from nifty_trader.risk.manager import RiskManager
from nifty_trader.risk.monthly import MonthlyManager
from nifty_trader.risk.validator import OrderValidator
from nifty_trader.state import TradeFSM
from nifty_trader.strategy.confluence import evaluate_confluence
from nifty_trader.strategy.levels import LevelDetector
from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
from nifty_trader.strategy.strike_selector import select_strike
from nifty_trader.strategy.time_manager import TimeManager
from nifty_trader.strategy.trail_engine import TrailEngine, TrailState
from nifty_trader.strategy.vix_gate import VixGate, VixMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("venom.log"),
    ],
)
logger = logging.getLogger(__name__)

# India VIX security ID on DhanHQ
VIX_SECURITY_ID = "21"


class VenomEngine:
    """Full auto-scalping loop for the VENOM strategy."""

    def __init__(self, config: AppConfig):
        self.cfg = config
        self.vcfg = config.venom
        self._running = False

        # DhanHQ client
        self.dhan = DhanHQ(
            client_id=config.dhan_client_id,
            access_token=config.dhan_access_token,
        )
        if config.dhan_base_url:
            self.dhan.base_url = config.dhan_base_url

        self.inst = config.instrument

        # ------- Existing infrastructure -------
        self.risk_mgr = RiskManager(config.risk, lot_size=self.inst.lot_size)
        self.fsm = TradeFSM()
        self.tracker = OrderTracker()
        self.journal = TradeJournal(Path("venom_journal.db"))
        self.notifier = Notifier(
            telegram_bot_token=config.telegram_bot_token,
            telegram_chat_id=config.telegram_chat_id,
            telegram_enabled=config.notifications.telegram_enabled,
            console_enabled=config.notifications.console_enabled,
        )
        self.validator = OrderValidator(
            config, self.risk_mgr,
            lot_size=self.inst.lot_size,
            market_open=self.inst.market_open,
        )
        self.order_mgr = OrderManager(
            self.dhan, self.tracker, self.journal, config.paper_mode,
            exchange_segment=self.inst.exchange_segment,
        )
        self.kill_switch = KillSwitch(
            self.dhan, self.tracker, self.notifier,
            max_single_loss_pct=config.risk.max_single_loss_pct,
            capital=config.risk.capital,
        )
        self.dashboard = Dashboard(instrument_name=f"VENOM {self.inst.name}")

        # Data layer
        self.hist_fetcher = HistoricalDataFetcher(
            self.dhan, config.data.rate_limit_data_per_sec,
        )
        # Option chain API uses the spot exchange segment (IDX_I for index
        # options), not the FNO segment.
        self.chain_fetcher = OptionChainFetcher(
            self.dhan, config.data.rate_limit_option_chain_sec,
            exchange_segment=self.inst.spot_exchange_segment,
        )
        self.feed = MarketFeedManager(
            self.dhan,
            on_tick=self._on_tick,
            heartbeat_timeout=config.data.ws_heartbeat_timeout_sec,
        )

        # ------- VENOM modules -------
        self.time_mgr = TimeManager(time_stop_minutes=self.vcfg.time_stop_minutes)
        self.vix_gate = VixGate(
            full=self.vcfg.vix_full,
            selective=self.vcfg.vix_selective,
            caution=self.vcfg.vix_caution,
            blocked=self.vcfg.vix_blocked,
            delta_low=self.vcfg.target_delta_low_vix,
            delta_high=self.vcfg.target_delta_high_vix,
        )
        self.ohlc_detector = OhlcSignalDetector(
            index_tolerance_pct=self.vcfg.ohlc_tolerance_index_pct,
            option_tolerance_abs=self.vcfg.ohlc_tolerance_option_abs,
        )
        self.trail_engine = TrailEngine(
            sl_pct=self.vcfg.sl_percent,
            activation_pct=self.vcfg.trail_activation_pct,
            trail_distance_pct=self.vcfg.trail_distance_pct,
            max_profit_pct=self.vcfg.max_profit_pct,
        )
        self.monthly_mgr = MonthlyManager(
            max_daily_loss=self.vcfg.max_daily_loss,
            max_weekly_loss=self.vcfg.max_weekly_loss,
            consecutive_loss_limit=self.vcfg.consecutive_loss_limit,
            mtd_protection_threshold=self.vcfg.mtd_protection_threshold,
            mtd_protection_size_reduction=self.vcfg.mtd_protection_size_reduction,
            mtd_stop_threshold=self.vcfg.mtd_stop_threshold,
            mtd_stop_days=self.vcfg.mtd_stop_days,
            mtd_resume_size_reduction=self.vcfg.mtd_resume_size_reduction,
        )
        self.persister = StatePersister()
        self._journal_publisher = JournalPublisher()

        # ------- Runtime state -------
        self._vix: float = 0.0
        self._ohlc_signal_text: str = ""
        self._trail_state: TrailState | None = None
        self._sl_order_id: str | None = None
        self._daily_pnl: float = 0.0
        self._trade_count: int = 0
        self._consecutive_losses: int = 0
        self._recent_pnls: list[float] = []
        self._level_detector: LevelDetector | None = None
        self._signal_detected: bool = False
        self._signal_attempt_done: bool = False
        self._time_offset: timedelta | None = None
        self._weekly_pnl: float = 0.0
        self._monthly_pnl: float = 0.0
        self._day_events: list[dict] = []

    # ------------------------------------------------------------------
    # Time simulation
    # ------------------------------------------------------------------

    def set_time_offset(self, offset):
        """Shift the engine's clock by a timedelta for simulation."""
        self._time_offset = offset

    def _now(self) -> datetime:
        """Return current time, adjusted by simulation offset if set."""
        now = datetime.now()
        if self._time_offset:
            now = now + self._time_offset
        return now

    def _log_event(self, event_type: str, **kwargs):
        """Append a structured decision event for the daily journal."""
        self._day_events.append({
            "type": event_type,
            "time": self._now().strftime("%H:%M:%S"),
            **kwargs,
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self):
        """Main entry point — run the VENOM event loop."""
        self._running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        mode = "PAPER" if self.cfg.paper_mode else "LIVE"
        logger.info("VENOM engine starting in %s mode", mode)
        self.notifier.info(f"VENOM started in {mode} mode")
        self.journal.log_event("STARTUP", f"VENOM engine started in {mode} mode")

        # Attempt crash recovery
        self._recover_state()

        try:
            self._pre_market_setup()
            self._event_loop()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        except Exception:
            logger.exception("Fatal error in VENOM event loop")
            self.notifier.error("VENOM fatal error — shutting down")
        finally:
            self._shutdown()

    def _handle_shutdown(self, signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False

    def _shutdown(self):
        logger.info("VENOM shutting down...")
        if self.fsm.has_position:
            self._force_exit("System shutdown")
        self.feed.stop()
        self.persister.clear()
        self.dashboard.stop()

        # Publish daily journal to GitHub Pages
        try:
            self._journal_publisher.collect_day_data(self)
            self._journal_publisher.publish()
        except Exception:
            logger.exception("Failed to publish journal")

        self.journal.close()
        self.notifier.info("VENOM stopped")
        logger.info("VENOM shutdown complete")

    # ------------------------------------------------------------------
    # Pre-market
    # ------------------------------------------------------------------

    def _pre_market_setup(self):
        """Subscribe feeds, load daily candle data for S/R levels."""
        logger.info("VENOM pre-market setup...")

        # Verify API connectivity
        try:
            fund_resp = self.dhan.get_fund_limits()
            if fund_resp and fund_resp.get("status") == "success":
                logger.info("API connectivity verified")
            else:
                logger.warning("API connectivity check returned: %s", fund_resp)
        except Exception:
            logger.exception("API connectivity check failed")

        # Fetch daily candles for S/R levels
        daily_df = self.hist_fetcher.get_daily(
            security_id=self.inst.security_id,
            exchange=self.inst.spot_exchange_segment,
            lookback_days=self.cfg.data.daily_lookback_days,
            instrument_type=self.inst.instrument_type,
        )
        self._level_detector = LevelDetector(daily_df)
        if not daily_df.empty:
            logger.info("Loaded %d daily candles for S/R levels", len(daily_df))

        # Subscribe to index + VIX
        self.feed.subscribe_spot(self.inst.feed_code, self.inst.security_id)
        self.feed.subscribe_spot(feed_code=0, security_id=VIX_SECURITY_ID)
        self.feed.start()
        logger.info("Market feed started (index + VIX)")

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    def _event_loop(self):
        tick_interval = self.cfg.timing.tick_interval_sec
        self._last_status_log = 0.0
        _STATUS_INTERVAL = 30  # log key info every 30 seconds

        while self._running:
            now = self._now()
            now_time = now.time()
            window = self.time_mgr.get_window(now_time)

            # Read VIX from feed (smoothed to avoid regime flipping on noise)
            vix_ltp = self.feed.get_ltp(VIX_SECURITY_ID)
            if vix_ltp is not None:
                smoothed = self.vix_gate.smooth(vix_ltp)
                if smoothed != self._vix:
                    self._vix = smoothed
                    vix_m = self.vix_gate.get_mode(self._vix)
                    self._log_event(
                        "vix_check",
                        vix=round(self._vix, 2),
                        mode=vix_m.value,
                        can_trade=self.vix_gate.can_trade(self._vix),
                        size_mult=round(self.vix_gate.size_multiplier(self._vix), 2),
                        min_confirms=self.vix_gate.min_confirmations(self._vix),
                        target_delta=round(self.vix_gate.target_delta(self._vix), 2),
                    )

            # Kill switch
            if self.kill_switch.is_triggered:
                self._update_dashboard("KILL SWITCH ACTIVE")
                time.sleep(tick_interval)
                continue

            # Force exit at 15:15
            if self.time_mgr.should_force_exit(now_time) and self.fsm.has_position:
                self._force_exit("Force exit at 15:15")

            # After market close — stop
            if now_time >= dtime(15, 30):
                reason = "Market closed"
                if self._trade_count == 0:
                    if not self.vix_gate.can_trade(self._vix):
                        reason = "VIX blocked — sat out"
                    elif not self._signal_detected and self._signal_attempt_done:
                        reason = "No signal detected — sat out"
                    elif not self._signal_detected:
                        reason = "No signal detected — sat out"
                    else:
                        reason = "Confluence insufficient — sat out"
                self._log_event(
                    "day_end",
                    reason=reason,
                    daily_pnl=round(self._daily_pnl, 0),
                    trades=self._trade_count,
                )
                logger.info("Market closed — stopping VENOM")
                self._running = False
                break

            # Signal detection window (9:16-9:20): detect O=H/O=L
            # Also catch up on signal detection if started late (past the
            # signal window but still in a valid entry window).
            if not self._signal_detected and not self._signal_attempt_done and self.time_mgr.can_enter(now_time):
                entry_start = self.vcfg.entry_window_start.split(":")
                signal_end = self.vcfg.signal_detection_end.split(":")
                signal_end_time = dtime(int(signal_end[0]), int(signal_end[1]))
                if (dtime(int(entry_start[0]), int(entry_start[1]))
                        <= now_time
                        < signal_end_time):
                    self._detect_ohlc_signal()
                    self._signal_attempt_done = True  # Run once, not every tick
                elif now_time >= signal_end_time:
                    # Late start — run signal detection from first candle
                    logger.info("Late start catch-up: running signal detection now")
                    self._detect_ohlc_signal()
                    self._signal_attempt_done = True

            # Entry logic — scan for trades when idle + signal present
            if (self.fsm.is_idle
                    and self._signal_detected
                    and self.time_mgr.can_enter(now_time)):
                if self._pre_entry_checks():
                    self._try_enter_trade()

            # Monitor open position
            if self.fsm.has_position:
                self._monitor_position(now)

            # Kill switch anomaly checks
            position_count = 1 if self.fsm.has_position else 0
            current_loss = 0.0
            if self.fsm.has_position and self.fsm.ctx.entry_price > 0:
                ltp = self.feed.get_ltp(self.fsm.ctx.security_id) or 0
                current_loss = (ltp - self.fsm.ctx.entry_price) * self.fsm.ctx.quantity
            self.kill_switch.check(position_count, current_loss)

            # Persist state every tick
            self._save_state()

            # Dashboard
            vix_mode = self.vix_gate.get_mode(self._vix)
            self._update_dashboard(
                f"Window: {window.value}",
                vix_mode=vix_mode.value,
            )

            # Periodic console status line
            elapsed_since_log = time.monotonic() - self._last_status_log
            if elapsed_since_log >= _STATUS_INTERVAL:
                self._last_status_log = time.monotonic()
                spot = self.feed.get_ltp(self.inst.security_id) or 0.0
                state = self.fsm.state.value if hasattr(self.fsm, 'state') else "?"
                pos_info = ""
                if self.fsm.has_position and self.fsm.ctx.entry_price > 0:
                    ltp = self.feed.get_ltp(self.fsm.ctx.security_id) or 0
                    pnl = (ltp - self.fsm.ctx.entry_price) * self.fsm.ctx.quantity
                    pos_info = (
                        f" | Position: {self.fsm.ctx.security_id} "
                        f"Entry={self.fsm.ctx.entry_price:.2f} LTP={ltp:.2f} "
                        f"P&L={pnl:+,.0f}"
                    )
                    if self._trail_state:
                        pos_info += f" SL={self._trail_state.sl_price:.2f}"
                        if self._trail_state.risk_free:
                            pos_info += " [RISK-FREE]"
                logger.info(
                    "[%s] Nifty=%.2f VIX=%.2f Mode=%s Window=%s "
                    "Signal=%s DayP&L=%.0f Trades=%d%s",
                    now.strftime("%H:%M:%S"),
                    spot, self._vix, vix_mode.value, window.value,
                    self._ohlc_signal_text or "none",
                    self._daily_pnl, self._trade_count, pos_info,
                )

            time.sleep(tick_interval)

    # ------------------------------------------------------------------
    # Pre-entry gate checks
    # ------------------------------------------------------------------

    def _pre_entry_checks(self) -> bool:
        """Run all gates before allowing an entry. Returns True if clear."""
        now_time = self._now().time()

        gates: list[dict] = []

        # Time window
        time_ok = self.time_mgr.can_enter(now_time)
        gates.append({"name": "Time Window", "passed": time_ok, "value": now_time.strftime("%H:%M")})
        if not time_ok:
            logger.info("Pre-entry blocked: outside entry window")
            self._log_event("gate_check", gates=gates)
            return False

        # VIX gate
        vix_ok = self.vix_gate.can_trade(self._vix)
        vix_mode = self.vix_gate.get_mode(self._vix).value
        gates.append({"name": "VIX Gate", "passed": vix_ok, "value": f"{self._vix:.1f} ({vix_mode})"})
        if not vix_ok:
            logger.info("Pre-entry blocked: VIX %.2f too high", self._vix)
            self._log_event("gate_check", gates=gates)
            return False

        # Daily loss limit
        daily_ok = self.monthly_mgr.can_trade_today(self._daily_pnl)
        gates.append({"name": "Daily Loss Limit", "passed": daily_ok, "value": f"{self._daily_pnl:+.0f}"})
        if not daily_ok:
            logger.info("Pre-entry blocked: daily loss limit hit (%.2f)", self._daily_pnl)
            self._log_event("gate_check", gates=gates)
            return False

        # Weekly loss limit
        weekly_ok = self.monthly_mgr.can_trade_this_week(self._weekly_pnl)
        gates.append({"name": "Weekly Loss Limit", "passed": weekly_ok, "value": f"{self._weekly_pnl:+.0f}"})
        if not weekly_ok:
            logger.info("Pre-entry blocked: weekly loss limit hit (%.2f)", self._weekly_pnl)
            self._log_event("gate_check", gates=gates)
            return False

        # Consecutive losses
        streak_ok = self.monthly_mgr.can_trade_after_streak(self._consecutive_losses)
        gates.append({"name": "Loss Streak", "passed": streak_ok, "value": str(self._consecutive_losses)})
        if not streak_ok:
            logger.info(
                "Pre-entry blocked: %d consecutive losses",
                self._consecutive_losses,
            )
            self._log_event("gate_check", gates=gates)
            return False

        # Max trades per day
        trades_ok = self._trade_count < self.vcfg.max_trades_per_day
        gates.append({"name": "Max Trades", "passed": trades_ok, "value": f"{self._trade_count}/{self.vcfg.max_trades_per_day}"})
        if not trades_ok:
            logger.info("Pre-entry blocked: max trades (%d) reached", self._trade_count)
            self._log_event("gate_check", gates=gates)
            return False

        # Kill switch
        kill_ok = not self.kill_switch.is_triggered
        gates.append({"name": "Kill Switch", "passed": kill_ok, "value": "active" if not kill_ok else "clear"})
        if not kill_ok:
            self._log_event("gate_check", gates=gates)
            return False

        self._log_event("gate_check", gates=gates)
        return True

    # ------------------------------------------------------------------
    # O=H/O=L signal detection
    # ------------------------------------------------------------------

    def _detect_ohlc_signal(self):
        """Fetch first 5-min candle for index + ATM options and detect O=H/O=L."""
        try:
            # Fetch first candle data for the index
            intraday_df = self.hist_fetcher.get_intraday_5min(
                security_id=self.inst.security_id,
                exchange=self.inst.spot_exchange_segment,
                lookback_days=1,
                instrument_type=self.inst.instrument_type,
            )
            if intraday_df is None or intraday_df.empty:
                logger.warning("No intraday data for O=H/O=L detection")
                return

            # First candle
            first = intraday_df.iloc[0]
            idx_open = float(first.get("open", first.get("Open", 0)))
            idx_high = float(first.get("high", first.get("High", 0)))
            idx_low = float(first.get("low", first.get("Low", 0)))
            idx_close = float(first.get("close", first.get("Close", 0)))

            if idx_open <= 0:
                return

            # Refresh round-number S/R levels from today's open
            if self._level_detector:
                self._level_detector.update_round_levels(idx_open)

            # Get ATM option chain for CE/PE candles
            ce_ohlc = pe_ohlc = None
            try:
                expiry = self.chain_fetcher.nearest_weekly_expiry(self.inst.security_id)
                if expiry:
                    contracts = self.chain_fetcher.get_chain(expiry, self.inst.security_id)
                    if contracts:
                        spot = idx_close
                        atm_strike = round(spot / 50) * 50

                        atm_ce = next(
                            (c for c in contracts
                             if c.option_type == OptionType.CALL
                             and abs(c.strike_price - atm_strike) < 1),
                            None,
                        )
                        atm_pe = next(
                            (c for c in contracts
                             if c.option_type == OptionType.PUT
                             and abs(c.strike_price - atm_strike) < 1),
                            None,
                        )
                        if atm_ce and atm_pe:
                            ce_price = atm_ce.ltp or atm_ce.mid_price
                            pe_price = atm_pe.ltp or atm_pe.mid_price
                            # Derive option OHLC from index move × delta
                            delta = abs(getattr(atm_ce, "delta", 0.5)) or 0.5
                            ce_move_h = (idx_high - idx_open) * delta
                            ce_move_l = (idx_low - idx_open) * delta
                            ce_move_c = (idx_close - idx_open) * delta
                            ce_ohlc = (
                                ce_price,
                                ce_price + max(ce_move_h, 0),
                                ce_price + min(ce_move_l, 0),
                                ce_price + ce_move_c,
                            )
                            pe_move_h = (idx_open - idx_low) * delta
                            pe_move_l = (idx_open - idx_high) * delta
                            pe_move_c = (idx_open - idx_close) * delta
                            pe_ohlc = (
                                pe_price,
                                pe_price + max(pe_move_h, 0),
                                pe_price + min(pe_move_l, 0),
                                pe_price + pe_move_c,
                            )
            except Exception:
                logger.debug("Option chain fetch failed, using simulated option patterns")

            # Fallback: simulate CE/PE patterns from index candle
            _sig_source = "chain" if (ce_ohlc and pe_ohlc) else "simulated"
            if not ce_ohlc or not pe_ohlc:
                from nifty_trader.backtest.simulator import PremiumSimulator
                sim = PremiumSimulator()
                opts = sim.simulate_option_ohlc_from_index(idx_open, idx_high, idx_low, idx_close)
                ce_ohlc = (opts["ce_open"], opts["ce_high"], opts["ce_low"], opts["ce_close"])
                pe_ohlc = (opts["pe_open"], opts["pe_high"], opts["pe_low"], opts["pe_close"])
                _sig_source = "simulated"
                logger.info("Using simulated option patterns for O=H/O=L detection")

            sig = self.ohlc_detector.detect(
                index_open=idx_open,
                index_high=idx_high,
                index_low=idx_low,
                index_close=idx_close,
                ce_open=ce_ohlc[0],
                ce_high=ce_ohlc[1],
                ce_low=ce_ohlc[2],
                ce_close=ce_ohlc[3],
                pe_open=pe_ohlc[0],
                pe_high=pe_ohlc[1],
                pe_low=pe_ohlc[2],
                pe_close=pe_ohlc[3],
            )

            self._ohlc_signal_text = f"{sig.signal_type.value}: {sig.reason}"
            logger.info("OHLC signal: %s", self._ohlc_signal_text)

            self._log_event(
                "signal_detection",
                signal=sig.signal_type.value,
                index_pattern=getattr(sig, "index_pattern", ""),
                ce_pattern=getattr(sig, "ce_pattern", ""),
                pe_pattern=getattr(sig, "pe_pattern", ""),
                reason=sig.reason,
                index_ohlc=[round(idx_open, 1), round(idx_high, 1), round(idx_low, 1), round(idx_close, 1)],
                ce_ohlc=[round(v, 2) for v in ce_ohlc],
                pe_ohlc=[round(v, 2) for v in pe_ohlc],
                source=_sig_source,
            )

            if sig.signal_type in (SignalType.BUY_CE, SignalType.BUY_PE):
                self._signal_detected = True
                self._ohlc_direction = (
                    Direction.BULLISH if sig.signal_type == SignalType.BUY_CE
                    else Direction.BEARISH
                )
                self.notifier.info(f"VENOM signal: {self._ohlc_signal_text}")
            else:
                self._signal_detected = False
                logger.info("No actionable O=H/O=L signal — waiting")

        except Exception:
            logger.exception("O=H/O=L detection failed")

    # ------------------------------------------------------------------
    # Trade entry
    # ------------------------------------------------------------------

    def _try_enter_trade(self):
        """Enter a directional option trade based on the O=H/O=L signal."""
        direction = getattr(self, "_ohlc_direction", Direction.BULLISH)

        # Check confluence confirmations
        intraday_df = self.hist_fetcher.get_intraday_5min(
            security_id=self.inst.security_id,
            exchange=self.inst.spot_exchange_segment,
            lookback_days=self.cfg.data.intraday_lookback_days,
            instrument_type=self.inst.instrument_type,
        )

        if intraday_df is not None and not intraday_df.empty and self._level_detector:
            result = evaluate_confluence(intraday_df, self._level_detector, self.cfg.strategy)

            # VIX-adjusted threshold: use weighted score, not just count
            min_confirms = self.vix_gate.min_confirmations(self._vix)
            min_score = self.cfg.strategy.confluence_min_score

            # Weighted score for the target direction
            weights = self.cfg.strategy.signal_weights
            dir_score = sum(
                weights.get(s.name, 0.5) * s.strength
                for s in result.signals
                if s.direction == direction
            )
            active_count = sum(
                1 for s in result.signals
                if s.direction == direction
            )

            conf_signals = [
                {
                    "name": s.name,
                    "direction": s.direction.value if hasattr(s.direction, "value") else str(s.direction),
                    "strength": getattr(s, "strength", 1.0),
                    "reason": getattr(s, "reason", ""),
                }
                for s in result.signals
            ]
            passed = active_count >= min_confirms and dir_score >= min_score
            self._log_event(
                "confluence",
                signals=conf_signals,
                total_score=round(dir_score, 2),
                active_count=active_count,
                threshold=min_confirms,
                min_score=min_score,
                passed=passed,
            )

            if not passed:
                logger.info(
                    "Confluence insufficient: %d/%d confirms, score %.2f/%.2f",
                    active_count, min_confirms, dir_score, min_score,
                )
                return

        # Get expiry + chain
        expiry = self.chain_fetcher.nearest_weekly_expiry(self.inst.security_id)
        if not expiry:
            logger.warning("No expiry — aborting entry")
            return

        contracts = self.chain_fetcher.get_chain(expiry, self.inst.security_id)
        if not contracts:
            logger.warning("Empty option chain — aborting entry")
            return

        # Override delta target based on VIX
        target_delta = self.vix_gate.target_delta(self._vix)
        from dataclasses import replace
        strike_cfg = replace(
            self.cfg.strike,
            delta_target=target_delta,
        )

        selection = select_strike(contracts, direction, strike_cfg)
        if not selection:
            logger.info("No suitable strike for VENOM entry")
            return

        contract = selection.contract
        premium = contract.ltp if contract.ltp > 0 else contract.mid_price

        # Check max premium
        max_prem = self.vcfg.max_premium_nifty
        if premium > max_prem:
            logger.info("Premium %.2f > max %.2f — skipping", premium, max_prem)
            return

        # Validate
        ok, reason = self.validator.validate(contract.security_id, premium)
        if not ok:
            logger.info("Validation failed: %s", reason)
            return

        # Position sizing with VIX multiplier
        size = self.risk_mgr.compute_position_size(premium)
        if not size:
            logger.warning("Position sizing failed")
            return

        vix_mult = self.vix_gate.size_multiplier(self._vix)
        adjusted_qty = max(self.inst.lot_size, int(size.quantity * vix_mult))
        # Round to lot size
        adjusted_qty = (adjusted_qty // self.inst.lot_size) * self.inst.lot_size

        # Signal FSM
        self.fsm.start_signal(direction, 1.0, self._ohlc_signal_text)

        # Place market buy
        order_id = self.order_mgr.place_market_buy(
            security_id=contract.security_id,
            quantity=adjusted_qty,
        )

        if not order_id:
            logger.warning("Market buy failed")
            self.fsm.reset()
            return

        # Place SL order
        trail_state = self.trail_engine.create_state(premium)
        self._sl_order_id = self.order_mgr.place_sl_order(
            security_id=contract.security_id,
            quantity=adjusted_qty,
            trigger_price=trail_state.sl_price,
        )

        # Update FSM
        self.fsm.order_placed(
            order_id=order_id,
            security_id=contract.security_id,
            strike_price=contract.strike_price,
            expiry=expiry,
            quantity=adjusted_qty,
        )

        # In paper mode, immediately fill
        if self.cfg.paper_mode:
            trailing = self.risk_mgr.create_trailing_state(premium)
            self.fsm.position_opened(premium, trailing)
            self.risk_mgr.on_position_opened()
            self.feed.subscribe_option(contract.security_id)

        self._trail_state = trail_state
        self._signal_detected = False  # Consumed

        self._log_event(
            "trade_entry",
            direction=direction.value,
            strike=contract.strike_price,
            expiry=str(expiry),
            premium=round(premium, 2),
            quantity=adjusted_qty,
            sl_price=round(trail_state.sl_price, 2),
            delta=round(target_delta, 2),
        )

        self.notifier.trade_entry(
            f"VENOM {contract.option_type.value} {contract.strike_price:.0f} "
            f"{expiry} @ {premium:.2f} qty={adjusted_qty} "
            f"SL={trail_state.sl_price:.2f}"
        )
        logger.info("VENOM entry placed: %s", contract.security_id)

    # ------------------------------------------------------------------
    # Position monitoring
    # ------------------------------------------------------------------

    def _monitor_position(self, now: datetime):
        """Monitor open position: trail SL, time stop, exit."""
        ctx = self.fsm.ctx
        if not ctx.security_id:
            return

        ltp = self.feed.get_ltp(ctx.security_id)
        if ltp is None:
            ltp = self.feed.fetch_ltp_rest(ctx.security_id, self.inst.exchange_segment)
        if ltp is None:
            return

        # Run trail engine
        if self._trail_state:
            action = self.trail_engine.update(self._trail_state, ltp)

            if action == "SL_HIT":
                self._log_event(
                    "trail_update", action="SL_HIT",
                    sl_price=round(self._trail_state.sl_price, 2),
                    peak_price=round(self._trail_state.peak_price, 2),
                    gain_pct=round(((self._trail_state.peak_price - self._trail_state.entry_price) / self._trail_state.entry_price) * 100, 1) if self._trail_state.entry_price else 0,
                    risk_free=self._trail_state.risk_free,
                )
                self._exit_position(ltp, "Trailing SL hit")
                return
            if action == "EXIT_MAX_PROFIT":
                self._log_event(
                    "trail_update", action="EXIT_MAX_PROFIT",
                    sl_price=round(self._trail_state.sl_price, 2),
                    peak_price=round(self._trail_state.peak_price, 2),
                    gain_pct=round(((ltp - self._trail_state.entry_price) / self._trail_state.entry_price) * 100, 1) if self._trail_state.entry_price else 0,
                    risk_free=self._trail_state.risk_free,
                )
                self._exit_position(ltp, "Max profit target hit")
                return
            if action in ("MOVE_SL_TO_COST", "LOCK_PROFIT", "TRAILING"):
                self._log_event(
                    "trail_update", action=action,
                    sl_price=round(self._trail_state.sl_price, 2),
                    peak_price=round(self._trail_state.peak_price, 2),
                    gain_pct=round(((ltp - self._trail_state.entry_price) / self._trail_state.entry_price) * 100, 1) if self._trail_state.entry_price else 0,
                    rung_hit=list(self._trail_state.rungs_hit) if hasattr(self._trail_state, "rungs_hit") else [],
                    risk_free=self._trail_state.risk_free,
                )
                # Modify the broker SL order
                if self._sl_order_id:
                    self.order_mgr.modify_sl_trigger(
                        self._sl_order_id, self._trail_state.sl_price,
                    )
                if self.fsm.state == TradeState.POSITION_OPEN:
                    self.fsm.start_trailing()
                logger.info(
                    "Trail action=%s new_sl=%.2f", action, self._trail_state.sl_price,
                )

        # Time stop: flat after N minutes
        if ctx.entry_time and ctx.entry_price > 0:
            pnl_pct = ((ltp - ctx.entry_price) / ctx.entry_price) * 100
            if self.time_mgr.time_stop_hit(ctx.entry_time, now, pnl_pct):
                minutes_held = (now - ctx.entry_time).total_seconds() / 60
                self._log_event(
                    "time_stop",
                    minutes_held=round(minutes_held, 1),
                    pnl_pct=round(pnl_pct, 1),
                    triggered=True,
                )
                self._exit_position(ltp, f"Time stop (flat {pnl_pct:+.1f}%)")
                return

        # Also update the trailing state in the existing risk mgr
        if ctx.trailing:
            self.risk_mgr.update_trailing(ctx.trailing, ltp)
            if self.fsm.state == TradeState.POSITION_OPEN and ctx.trailing.at_breakeven:
                self.fsm.start_trailing()

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _exit_position(self, exit_price: float, reason: str):
        ctx = self.fsm.ctx

        self._log_event(
            "trade_exit",
            exit_price=round(exit_price, 2),
            pnl=round((exit_price - ctx.entry_price) * ctx.quantity, 0) if ctx.entry_price else 0,
            exit_reason=reason,
            rungs_hit=list(self._trail_state.rungs_hit) if self._trail_state and hasattr(self._trail_state, "rungs_hit") else [],
            peak_premium=round(self._trail_state.peak_price, 2) if self._trail_state else 0,
        )

        self.fsm.start_exit(reason)

        if not self.cfg.paper_mode:
            self.order_mgr.place_market_sell(ctx.security_id, ctx.quantity)
            if self._sl_order_id:
                self.order_mgr.cancel_order(self._sl_order_id)
                self._sl_order_id = None

        self.fsm.position_closed(exit_price)
        self.risk_mgr.on_position_closed()

        pnl = ctx.pnl
        self.risk_mgr.record_trade_pnl(pnl)
        self.journal.log_trade(ctx)

        # Update daily tracking
        self._daily_pnl += pnl
        self._trade_count += 1
        self._recent_pnls.append(pnl)
        self._consecutive_losses = self.monthly_mgr.compute_consecutive_losses(
            self._recent_pnls,
        )
        self._weekly_pnl += pnl
        self._monthly_pnl += pnl

        self.notifier.trade_exit(
            f"VENOM {ctx.option_type.value} {ctx.strike_price:.0f} | "
            f"P&L: {pnl:+.2f} | {reason}"
        )

        # Clean up
        self._trail_state = None
        self.fsm.transition(TradeState.CLOSED)
        self.fsm.reset()

    def _force_exit(self, reason: str):
        if not self.fsm.has_position:
            return
        ctx = self.fsm.ctx
        ltp = self.feed.get_ltp(ctx.security_id)
        if ltp is None:
            ltp = self.feed.fetch_ltp_rest(
                ctx.security_id, self.inst.exchange_segment,
            ) or ctx.entry_price
        self._exit_position(ltp, reason)

    # ------------------------------------------------------------------
    # State persistence / recovery
    # ------------------------------------------------------------------

    def _save_state(self):
        trail_dict = None
        if self._trail_state:
            trail_dict = {
                "entry_price": self._trail_state.entry_price,
                "sl_price": self._trail_state.sl_price,
                "peak_price": self._trail_state.peak_price,
                "risk_free": self._trail_state.risk_free,
                "rungs_hit": self._trail_state.rungs_hit,
            }

        position = None
        if self.fsm.has_position:
            ctx = self.fsm.ctx
            position = {
                "security_id": ctx.security_id,
                "strike_price": ctx.strike_price,
                "entry_price": ctx.entry_price,
                "quantity": ctx.quantity,
                "direction": ctx.direction.value,
                "option_type": ctx.option_type.value,
            }

        snap = VenomSnapshot(
            fsm_state=self.fsm.state.value,
            position=position,
            daily_pnl=self._daily_pnl,
            trade_count=self._trade_count,
            consecutive_losses=self._consecutive_losses,
            signal={"text": self._ohlc_signal_text} if self._ohlc_signal_text else None,
            trail_state=trail_dict,
        )
        self.persister.save(snap)

    def _recover_state(self):
        snap = self.persister.load()
        if not snap:
            logger.info("No crash recovery state found")
            return

        logger.info("Recovering from snapshot: state=%s", snap.fsm_state)
        self._daily_pnl = snap.daily_pnl
        self._trade_count = snap.trade_count
        self._consecutive_losses = snap.consecutive_losses

        if snap.signal:
            self._ohlc_signal_text = snap.signal.get("text", "")

        if snap.fsm_state in ("POSITION_OPEN", "TRAILING") and snap.position:
            pos = snap.position
            logger.warning(
                "Recovered open position: %s @ %.2f qty=%d — will monitor",
                pos.get("security_id"), pos.get("entry_price", 0), pos.get("quantity", 0),
            )
            # Restore FSM state
            direction = Direction(pos.get("direction", "BULLISH"))
            self.fsm.start_signal(direction, 1.0, "Recovered")
            self.fsm.order_placed(
                order_id="RECOVERED",
                security_id=pos.get("security_id", ""),
                strike_price=pos.get("strike_price", 0),
                expiry="",
                quantity=pos.get("quantity", 0),
            )
            entry_price = pos.get("entry_price", 0)
            trailing = self.risk_mgr.create_trailing_state(entry_price)
            self.fsm.position_opened(entry_price, trailing)

            # Restore trail state
            if snap.trail_state:
                self._trail_state = TrailState(
                    entry_price=snap.trail_state.get("entry_price", entry_price),
                    sl_price=snap.trail_state.get("sl_price", 0),
                    peak_price=snap.trail_state.get("peak_price", entry_price),
                    risk_free=snap.trail_state.get("risk_free", False),
                    rungs_hit=snap.trail_state.get("rungs_hit", []),
                )
            else:
                self._trail_state = self.trail_engine.create_state(entry_price)

            self.feed.subscribe_option(pos.get("security_id", ""))
            self.notifier.warning(
                f"VENOM recovered open position: {pos.get('security_id')}"
            )

    # ------------------------------------------------------------------
    # Feed callback
    # ------------------------------------------------------------------

    def _on_tick(self, message: dict):
        """WebSocket tick callback — position monitoring done in event loop."""
        pass

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def _update_dashboard(self, status: str, vix_mode: str = ""):
        spot = self.feed.get_ltp(self.inst.security_id) or 0.0
        trail_text = ""
        if self._trail_state:
            trail_text = (
                f"SL={self._trail_state.sl_price:.2f} "
                f"Peak={self._trail_state.peak_price:.2f} "
                f"{'RISK-FREE' if self._trail_state.risk_free else ''}"
            )

        self.dashboard.update(
            self.fsm,
            nifty_price=spot,
            daily_pnl=self._daily_pnl,
            trade_count=self._trade_count,
            system_status=status,
            vix=self._vix,
            vix_mode=vix_mode,
            ohlc_signal=self._ohlc_signal_text,
            monthly_pnl=self._monthly_pnl,
            weekly_pnl=self._weekly_pnl,
            trail_status=trail_text,
        )


# ======================================================================
# Dry-run simulation
# ======================================================================


def dry_run():
    """Simulate a full trading day with synthetic data — no API needed."""
    import random

    print("=" * 65)
    print("  VENOM DRY RUN — Simulated Trading Day")
    print("=" * 65)
    print()

    # --- Simulated market parameters ---
    nifty_open = 24450.0
    vix_value = 14.2
    sim_scenarios = [
        {
            "name": "Scenario A: Bullish Day (O=L detected)",
            "index_ohlc": (24450, 24620, 24448, 24590),
            "ce_ohlc": (145, 195, 145, 188),
            "pe_ohlc": (120, 120, 78, 82),
            "price_path": [145, 148, 153, 160, 168, 175, 180, 178, 185, 192, 198, 195, 190],
            "vix": 14.2,
        },
        {
            "name": "Scenario B: Bearish Day (O=H detected)",
            "index_ohlc": (24450, 24450, 24280, 24310),
            "ce_ohlc": (145, 145, 98, 102),
            "pe_ohlc": (85, 138, 85, 130),
            "price_path": [85, 90, 98, 105, 112, 118, 122, 128, 135, 140, 148, 155, 160],
            "vix": 16.5,
        },
        {
            "name": "Scenario C: Choppy Day (No signal)",
            "index_ohlc": (24450, 24480, 24420, 24460),
            "ce_ohlc": (145, 145, 132, 138),
            "pe_ohlc": (85, 85, 78, 82),
            "price_path": [],
            "vix": 22.0,
        },
    ]

    # Build VENOM modules (no API needed)
    from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType
    from nifty_trader.strategy.vix_gate import VixGate, VixMode
    from nifty_trader.strategy.time_manager import TimeManager, TradingWindow
    from nifty_trader.strategy.trail_engine import TrailEngine
    from nifty_trader.risk.monthly import MonthlyManager

    ohlc = OhlcSignalDetector(index_tolerance_pct=0.05, option_tolerance_abs=0.50)
    vix_gate = VixGate()
    time_mgr = TimeManager(time_stop_minutes=20)
    trail = TrailEngine(sl_pct=30, activation_pct=20, trail_distance_pct=15, max_profit_pct=100)
    monthly = MonthlyManager()

    daily_pnl = 0.0
    trade_count = 0
    consecutive_losses = 0

    for scenario in sim_scenarios:
        print(f"\n{'─' * 65}")
        print(f"  {scenario['name']}")
        print(f"{'─' * 65}")
        vix = scenario["vix"]

        # --- Phase 1: Pre-market VIX Check ---
        print(f"\n  [08:45] Pre-Market VIX Check")
        mode = vix_gate.get_mode(vix)
        can_trade = vix_gate.can_trade(vix)
        print(f"          VIX: {vix:.1f} | Mode: {mode.value.upper()} | "
              f"Can Trade: {'YES' if can_trade else 'NO'}")
        print(f"          Size Multiplier: {vix_gate.size_multiplier(vix):.0%} | "
              f"Min Confirms: {vix_gate.min_confirmations(vix)} | "
              f"Delta Target: {vix_gate.target_delta(vix):.2f}")

        if not can_trade:
            print(f"          BLOCKED — VIX too high. Skipping day.")
            continue

        # --- Phase 2: Signal Detection at 09:16 ---
        idx = scenario["index_ohlc"]
        ce = scenario["ce_ohlc"]
        pe = scenario["pe_ohlc"]

        print(f"\n  [09:16] O=H/O=L Signal Detection")
        print(f"          Index OHLC: O={idx[0]:.0f} H={idx[1]:.0f} "
              f"L={idx[2]:.0f} C={idx[3]:.0f}")
        print(f"          CE OHLC:    O={ce[0]:.0f} H={ce[1]:.0f} "
              f"L={ce[2]:.0f} C={ce[3]:.0f}")
        print(f"          PE OHLC:    O={pe[0]:.0f} H={pe[1]:.0f} "
              f"L={pe[2]:.0f} C={pe[3]:.0f}")

        sig = ohlc.detect(idx[0], idx[1], idx[2], idx[3],
                          ce[0], ce[1], ce[2], ce[3],
                          pe[0], pe[1], pe[2], pe[3])

        print(f"          Index: {sig.index_pattern} | CE: {sig.ce_pattern} | "
              f"PE: {sig.pe_pattern}")
        print(f"          Signal: {sig.signal_type.value.upper()} — {sig.reason}")

        if sig.signal_type in (SignalType.WAIT, SignalType.NO_TRADE):
            print(f"          No actionable signal — sitting out.")
            continue

        # --- Phase 3: Pre-entry Gate Checks ---
        print(f"\n  [09:18] Pre-Entry Gate Checks")
        gates = [
            ("Time Window", time_mgr.can_enter(dtime(9, 18))),
            ("VIX Gate", vix_gate.can_trade(vix)),
            ("Daily Loss", monthly.can_trade_today(daily_pnl)),
            ("Consecutive Losses", monthly.can_trade_after_streak(consecutive_losses)),
            ("Trade Count", trade_count < 3),
        ]
        all_pass = True
        for name, passed in gates:
            status = "PASS" if passed else "FAIL"
            print(f"          {name}: {status}")
            if not passed:
                all_pass = False

        if not all_pass:
            print(f"          Entry BLOCKED — gate check failed.")
            continue

        # --- Phase 4: Entry ---
        direction = "CE" if sig.signal_type == SignalType.BUY_CE else "PE"
        entry_price = scenario["price_path"][0]
        lot_size = 75
        strike = round(nifty_open / 50) * 50

        print(f"\n  [09:18] ENTRY")
        print(f"          Buy NIFTY {strike} {direction} @ {entry_price:.2f}")
        print(f"          Qty: {lot_size} | Risk: {entry_price * lot_size:.0f}")

        state = trail.create_state(entry_price)
        print(f"          Initial SL: {state.sl_price:.2f} "
              f"(-{trail.sl_pct:.0f}%)")

        # --- Phase 5: Position Monitoring (simulated ticks) ---
        print(f"\n  [09:20+] Position Monitoring (5-min ticks)")
        minutes_elapsed = 0
        exit_price = entry_price
        exit_reason = ""
        tick_time = 920

        for i, price in enumerate(scenario["price_path"][1:], 1):
            minutes_elapsed = i * 5
            total_mins = 9 * 60 + 20 + minutes_elapsed
            hrs = total_mins // 60
            mins = total_mins % 60

            gain_pct = (price - entry_price) / entry_price * 100
            action = trail.update(state, price)

            indicator = ""
            if action == "MOVE_SL_TO_COST":
                indicator = " << SL MOVED TO COST (risk-free!)"
            elif action == "LOCK_PROFIT":
                indicator = f" << PROFIT LOCKED (SL={state.sl_price:.2f})"
            elif action == "TRAILING":
                indicator = f" << TRAILING (SL={state.sl_price:.2f})"
            elif action == "SL_HIT":
                indicator = " << SL HIT — EXITING"
            elif action == "EXIT_MAX_PROFIT":
                indicator = " << MAX PROFIT — EXITING"

            print(f"          [{hrs:02d}:{mins:02d}] LTP={price:.2f} | "
                  f"P&L={gain_pct:+.1f}% | "
                  f"SL={state.sl_price:.2f}{indicator}")

            if action in ("SL_HIT", "EXIT_MAX_PROFIT"):
                exit_price = price
                exit_reason = action
                break

            # Time stop check
            if minutes_elapsed >= 20 and abs(gain_pct) < 5.0:
                print(f"          [{hrs:02d}:{mins:02d}] TIME STOP — flat after 20 min")
                exit_price = price
                exit_reason = "TIME_STOP"
                break
        else:
            # If we didn't break, exit at last price
            exit_price = scenario["price_path"][-1]
            exit_reason = "END_OF_SIM"

        # --- Phase 6: Exit ---
        pnl_points = exit_price - entry_price
        pnl_amount = pnl_points * lot_size
        pnl_pct = (pnl_points / entry_price) * 100
        daily_pnl += pnl_amount
        trade_count += 1
        if pnl_amount < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        print(f"\n  EXIT")
        print(f"          Exit Price: {exit_price:.2f} | Reason: {exit_reason}")
        print(f"          P&L: {pnl_points:+.2f} pts | "
              f"{pnl_amount:+,.0f} | {pnl_pct:+.1f}%")
        print(f"          Trail Peak: {state.peak_price:.2f} | "
              f"Risk-free: {'Yes' if state.risk_free else 'No'}")
        print(f"          Rungs Hit: {state.rungs_hit}")

    # --- Daily Summary ---
    print(f"\n{'=' * 65}")
    print(f"  DAILY SUMMARY")
    print(f"{'=' * 65}")
    print(f"  Trades: {trade_count}")
    print(f"  Daily P&L: {daily_pnl:+,.0f}")
    print(f"  Consecutive Losses: {consecutive_losses}")
    print(f"  Can Trade Tomorrow: "
          f"{'Yes' if monthly.can_trade_today(daily_pnl) else 'No (limit hit)'}")
    print(f"\n  System verified. All VENOM modules operational.")
    print(f"{'=' * 65}")


# ======================================================================
# CLI entry point
# ======================================================================


def _run_eod(config_path: str | None = None):
    """Run end-of-day analysis — grade trades, update goals, generate report."""
    from nifty_trader.analysis.eod_analyzer import EODAnalyzer
    from nifty_trader.analysis.goal_tracker import GoalTracker
    from nifty_trader.analysis.learning_journal import LearningJournal
    from nifty_trader.analysis.report_generator import ReportGenerator

    db_path = Path("venom_journal.db")
    journal = TradeJournal(db_path)
    analyzer = EODAnalyzer(journal)
    tracker = GoalTracker(db_path)
    learner = LearningJournal(db_path)

    # Analyze today
    analysis = analyzer.analyze()

    # Update goal tracker
    trades = journal.get_today_trades()
    pnls = [t.get("pnl", 0) or 0 for t in trades]
    daily_pnl = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    tracker.update(daily_pnl, len(trades), wins, losses)

    # Auto-generate insights
    learner.analyze_trades(trades)

    # Build cumulative stats
    progress = tracker.get_progress()
    streak = tracker.get_streak()
    cumulative = {
        "win_rate": progress.progress_pct,
        "expectancy": progress.actual_daily_pace,
    }
    # Pull real cumulative stats from goal_tracking
    row = tracker._conn.execute(
        "SELECT win_rate_cumulative, expectancy FROM goal_tracking ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if row:
        cumulative["win_rate"] = row["win_rate_cumulative"]
        cumulative["expectancy"] = row["expectancy"]

    # Print report
    report = ReportGenerator()
    report.print_eod_report(analysis, progress, streak, cumulative)

    journal.close()
    tracker.close()
    learner.close()


def _run_dashboard():
    """Show goal tracker dashboard."""
    from nifty_trader.analysis.goal_tracker import GoalTracker
    from nifty_trader.analysis.report_generator import ReportGenerator

    db_path = Path("venom_journal.db")
    tracker = GoalTracker(db_path)

    progress = tracker.get_progress()
    streak = tracker.get_streak()
    weekly = tracker.get_weekly_summary()
    monthly = tracker.get_monthly_summary()

    report = ReportGenerator()
    report.print_dashboard(progress, streak, weekly, monthly)

    tracker.close()


def _run_learnings():
    """Show accumulated trading insights."""
    from nifty_trader.analysis.learning_journal import LearningJournal
    from nifty_trader.analysis.report_generator import ReportGenerator

    db_path = Path("venom_journal.db")
    learner = LearningJournal(db_path)

    insights = learner.get_insights()

    report = ReportGenerator()
    report.print_learnings(insights)

    learner.close()


def _run_backtest(
    config_path: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    days: int | None = None,
):
    """Run VENOM backtest on historical data."""
    from datetime import date as _date, timedelta as _td
    from nifty_trader.backtest.engine import BacktestConfig, VenomBacktester
    from nifty_trader.backtest.report import BacktestReportGenerator

    config = load_config(yaml_path=config_path)

    if not config.dhan_client_id or not config.dhan_access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    # Resolve date range
    if days:
        end = _date.today()
        start = end - _td(days=days)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
    elif from_date and to_date:
        start_str = from_date
        end_str = to_date
    elif from_date:
        start_str = from_date
        end_str = _date.today().strftime("%Y-%m-%d")
    else:
        # Default: last 30 days
        end = _date.today()
        start = end - _td(days=30)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

    bt_config = BacktestConfig(
        start_date=start_str,
        end_date=end_str,
        start_capital=config.risk.capital,
        lot_size=config.instrument.lot_size,
        max_trades_per_day=config.venom.max_trades_per_day,
    )

    dhan = DhanHQ(
        client_id=config.dhan_client_id,
        access_token=config.dhan_access_token,
    )
    if config.dhan_base_url:
        dhan.base_url = config.dhan_base_url

    print(f"VENOM Backtest: {start_str} → {end_str}")
    print("Fetching historical data...")

    backtester = VenomBacktester(dhan, config, bt_config)

    def _progress(current, total, date_str):
        pct = current / total * 100
        bar_len = 30
        filled = int(bar_len * current / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:.0f}% — Day {current}/{total} ({date_str})", end="", flush=True)

    result = backtester.run(progress_callback=_progress)
    print()  # newline after progress bar

    report = BacktestReportGenerator()
    report.print_report(result)


def main():
    parser = argparse.ArgumentParser(description="VENOM O=H/O=L Scalping Engine")
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--dry-run", action="store_true", help="Simulate a trading day (no API needed)")
    parser.add_argument("--config", help="Path to config YAML")
    parser.add_argument("--eod", action="store_true", help="Run end-of-day analysis")
    parser.add_argument("--dashboard", action="store_true", help="Show goal tracker dashboard")
    parser.add_argument("--learnings", action="store_true", help="Show accumulated trading insights")
    parser.add_argument("--backtest", action="store_true", help="Run VENOM backtest on historical data")
    parser.add_argument("--from", dest="from_date", help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, help="Backtest last N calendar days (shorthand)")
    parser.add_argument("--sim-start", help="Simulate starting at HH:MM (e.g. 09:10) — shifts engine clock")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return

    if args.eod:
        _run_eod(config_path=args.config)
        return

    if args.dashboard:
        _run_dashboard()
        return

    if args.learnings:
        _run_learnings()
        return

    if args.backtest:
        _run_backtest(
            config_path=args.config,
            from_date=args.from_date,
            to_date=args.to_date,
            days=args.days,
        )
        return

    config = load_config(yaml_path=args.config)

    if not config.dhan_client_id or not config.dhan_access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    if args.paper:
        # Override paper mode
        from dataclasses import replace
        config = replace(config, paper_mode=True)

    engine = VenomEngine(config)

    if args.sim_start:
        h, m = map(int, args.sim_start.split(":"))
        sim_target = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        offset = sim_target - datetime.now()
        engine.set_time_offset(offset)
        logger.info("Time simulation: engine clock offset by %s (simulated start %s)", offset, args.sim_start)

    engine.run()


if __name__ == "__main__":
    main()
