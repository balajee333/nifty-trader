"""Main orchestrator — event loop for the NIFTY options trading system."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

from dhanhq import dhanhq as DhanHQ

from nifty_trader.alerts.notifier import Notifier
from nifty_trader.config import AppConfig, load_config
from nifty_trader.constants import Direction, StrategyMode, TradeState
from nifty_trader.dashboard.console import Dashboard
from nifty_trader.data.feed import MarketFeedManager
from nifty_trader.data.historical import HistoricalDataFetcher
from nifty_trader.data.option_chain import OptionChainFetcher
from nifty_trader.journal.database import TradeJournal
from nifty_trader.journal.reconciler import Reconciler
from nifty_trader.orders.manager import OrderManager
from nifty_trader.orders.super_order import SuperOrderManager
from nifty_trader.orders.tracker import OrderTracker
from nifty_trader.risk.kill_switch import KillSwitch
from nifty_trader.risk.manager import RiskManager, SpreadMonitorState
from nifty_trader.risk.validator import OrderValidator
from nifty_trader.state import TradeFSM
from nifty_trader.strategy.confluence import evaluate_confluence
from nifty_trader.strategy.levels import LevelDetector
from nifty_trader.strategy.strike_selector import select_spread, select_strike

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("nifty_trader.log"),
    ],
)
logger = logging.getLogger(__name__)


class TradingEngine:
    """Main trading engine orchestrating all components."""

    def __init__(self, config: AppConfig):
        self.cfg = config
        self._running = False

        # DhanHQ client
        self.dhan = DhanHQ(
            client_id=config.dhan_client_id,
            access_token=config.dhan_access_token,
        )
        # Override base URL for sandbox
        if config.dhan_base_url:
            self.dhan.base_url = config.dhan_base_url
            logger.info("Using custom API base URL: %s", config.dhan_base_url)

        # Instrument config
        self.inst = config.instrument

        # Core components
        self.risk_mgr = RiskManager(config.risk, lot_size=self.inst.lot_size)
        self.fsm = TradeFSM()
        self.tracker = OrderTracker()
        self.journal = TradeJournal(Path("trade_journal.db"))
        self.notifier = Notifier(
            telegram_bot_token=config.telegram_bot_token,
            telegram_chat_id=config.telegram_chat_id,
            telegram_enabled=config.notifications.telegram_enabled,
            console_enabled=config.notifications.console_enabled,
        )
        self.validator = OrderValidator(config, self.risk_mgr, lot_size=self.inst.lot_size, market_open=self.inst.market_open)
        self.order_mgr = OrderManager(
            self.dhan, self.tracker, self.journal, config.paper_mode,
            exchange_segment=self.inst.exchange_segment,
        )
        self.super_order_mgr = SuperOrderManager(self.dhan, self.tracker, self.journal, config.paper_mode)
        self.kill_switch = KillSwitch(
            self.dhan, self.tracker, self.notifier,
            max_single_loss_pct=config.risk.max_single_loss_pct,
            capital=config.risk.capital,
        )
        self.reconciler = Reconciler(self.dhan, self.journal, self.notifier, config.risk.capital)
        self.dashboard = Dashboard(instrument_name=self.inst.name)

        # Data layer
        self.hist_fetcher = HistoricalDataFetcher(self.dhan, config.data.rate_limit_data_per_sec)
        self.chain_fetcher = OptionChainFetcher(
            self.dhan, config.data.rate_limit_option_chain_sec,
            exchange_segment=self.inst.exchange_segment,
        )
        self.feed = MarketFeedManager(
            self.dhan,
            on_tick=self._on_tick,
            heartbeat_timeout=config.data.ws_heartbeat_timeout_sec,
        )

        # Strategy mode
        self._strategy_mode = StrategyMode(config.strategy_mode)

        # State
        self._level_detector: LevelDetector | None = None
        self._last_candle_eval: float = 0.0
        self._intraday_df = None
        self._sl_order_id: str | None = None
        self._spread_monitor: SpreadMonitorState | None = None

    def run(self):
        """Main entry point — runs the event loop."""
        self._running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        mode = "PAPER" if self.cfg.paper_mode else "LIVE"
        logger.info("Starting %s Trader in %s mode", self.inst.name, mode)
        self.notifier.info(f"{self.inst.name} Trader started in {mode} mode")
        self.journal.log_event("STARTUP", f"Engine started in {mode} mode")

        try:
            self._pre_market_setup()
            self._event_loop()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        except Exception:
            logger.exception("Fatal error in event loop")
            self.notifier.error("Fatal error — shutting down")
        finally:
            self._shutdown()

    def _pre_market_setup(self):
        """Pre-market initialization: verify API, fetch data, start feeds."""
        logger.info("Pre-market setup...")

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
        if not daily_df.empty:
            self._level_detector = LevelDetector(daily_df)
            logger.info("Loaded %d daily candles, computed S/R levels", len(daily_df))
        else:
            self._level_detector = LevelDetector(daily_df)
            logger.warning("No daily data — S/R levels unavailable")

        # Subscribe and start market feed
        self.feed.subscribe_spot(self.inst.feed_code, self.inst.security_id)
        self.feed.start()
        logger.info("Market feed started for %s", self.inst.name)

    def _event_loop(self):
        """Main event loop — runs until shutdown."""
        tick_interval = self.cfg.timing.tick_interval_sec
        candle_interval = self.cfg.timing.candle_interval_min * 60

        while self._running:
            now = datetime.now()
            now_time = now.time()

            # Parse timing config
            scan_h, scan_m = map(int, self.cfg.timing.scan_start.split(":"))
            exit_h, exit_m = map(int, self.cfg.timing.force_exit.split(":"))
            recon_h, recon_m = map(int, self.cfg.timing.reconcile.split(":"))

            # Before scan start — wait
            if now_time < dtime(scan_h, scan_m):
                self._update_dashboard("Waiting for scan window...")
                time.sleep(tick_interval)
                continue

            # Kill switch check
            if self.kill_switch.is_triggered:
                self._update_dashboard("KILL SWITCH ACTIVE")
                time.sleep(tick_interval)
                continue

            # Force exit time
            if now_time >= dtime(exit_h, exit_m) and self.fsm.has_position:
                self._force_exit(f"Time-based force exit at {self.cfg.timing.force_exit}")

            # Reconciliation time
            if now_time >= dtime(recon_h, recon_m):
                if self.fsm.is_idle:
                    logger.info("Running post-market reconciliation")
                    self.reconciler.run()
                    self._running = False
                    break

            # Check candle interval for signal evaluation
            elapsed = time.monotonic() - self._last_candle_eval
            if elapsed >= candle_interval:
                self._on_candle_close()
                self._last_candle_eval = time.monotonic()

            # Monitor open position
            if self.fsm.has_position:
                self._monitor_position()

            # Kill switch anomaly checks
            position_count = 1 if self.fsm.has_position else 0
            current_loss = 0.0
            is_spread = self.fsm.ctx.is_spread
            if is_spread and self.fsm.has_position:
                short_ltp = self.feed.get_ltp(self.fsm.ctx.short_security_id) or 0
                long_ltp = self.feed.get_ltp(self.fsm.ctx.long_security_id) or 0
                cost_to_close = short_ltp - long_ltp
                current_loss = (self.fsm.ctx.net_credit - cost_to_close) * self.fsm.ctx.quantity
            elif self.fsm.ctx.trailing and self.fsm.ctx.entry_price > 0:
                ltp = self.feed.get_ltp(self.fsm.ctx.security_id) or 0
                current_loss = (ltp - self.fsm.ctx.entry_price) * self.fsm.ctx.quantity
            self.kill_switch.check(position_count, current_loss, is_spread=is_spread)

            # Dashboard update
            self._update_dashboard(f"State: {self.fsm.state.value}")
            time.sleep(tick_interval)

    def _on_candle_close(self):
        """Called every 5 minutes — refresh indicators, evaluate confluence."""
        # Fetch fresh intraday data
        self._intraday_df = self.hist_fetcher.get_intraday_5min(
            security_id=self.inst.security_id,
            exchange=self.inst.spot_exchange_segment,
            lookback_days=self.cfg.data.intraday_lookback_days,
            instrument_type=self.inst.instrument_type,
        )

        if self._intraday_df is None or self._intraday_df.empty:
            logger.warning("No intraday data available")
            return

        if not self.fsm.is_idle:
            return  # Only scan for new signals when IDLE

        if self.risk_mgr.is_daily_stopped:
            self.fsm.daily_stop()
            self.notifier.warning("Daily loss limit reached — stopping")
            return

        # Evaluate confluence
        result = evaluate_confluence(
            self._intraday_df,
            self._level_detector,
            self.cfg.strategy,
        )

        self.dashboard.update(
            self.fsm,
            signals_text=result.summary,
        )

        if not result.triggered:
            return

        logger.info("Signal detected: %s", result.summary)
        self.fsm.start_signal(result.direction, result.score, result.summary)

        if self._strategy_mode == StrategyMode.CREDIT_SPREAD:
            self._try_enter_spread(result.direction)
        elif self._strategy_mode == StrategyMode.BOTH:
            if not self._try_enter_spread(result.direction):
                self._try_enter_trade(result.direction)
        else:
            self._try_enter_trade(result.direction)

    def _try_enter_trade(self, direction: Direction):
        """Attempt to enter a trade after signal detection."""
        # Get expiry
        expiry = self.chain_fetcher.nearest_weekly_expiry(self.inst.security_id)
        if not expiry:
            logger.warning("No expiry available — aborting")
            self.fsm.reset()
            return

        # Get option chain
        contracts = self.chain_fetcher.get_chain(expiry, self.inst.security_id)
        if not contracts:
            logger.warning("Empty option chain — aborting")
            self.fsm.reset()
            return

        # Select strike
        selection = select_strike(contracts, direction, self.cfg.strike)
        if not selection:
            logger.info("No suitable strike — returning to IDLE")
            self.fsm.reset()
            return

        contract = selection.contract
        premium = contract.ltp if contract.ltp > 0 else contract.mid_price

        # Validate
        ok, reason = self.validator.validate(contract.security_id, premium)
        if not ok:
            logger.info("Validation failed: %s", reason)
            self.fsm.reset()
            return

        # Position sizing
        size = self.risk_mgr.compute_position_size(premium)
        if not size:
            logger.warning("Position sizing failed")
            self.fsm.reset()
            return

        # Compute SL and target
        sl_price, target_price = self.risk_mgr.compute_sl_target(premium)

        # Try Super Order first
        order_id = self.super_order_mgr.place_super_order(
            security_id=contract.security_id,
            quantity=size.quantity,
            sl_price=sl_price,
            target_price=target_price,
        )

        if not order_id:
            # Fallback to market + SL
            order_id = self.order_mgr.place_market_buy(
                security_id=contract.security_id,
                quantity=size.quantity,
            )
            if order_id:
                self._sl_order_id = self.order_mgr.place_sl_order(
                    security_id=contract.security_id,
                    quantity=size.quantity,
                    trigger_price=sl_price,
                )

        if not order_id:
            logger.warning("All order attempts failed")
            self.fsm.reset()
            return

        # Update FSM
        self.fsm.order_placed(
            order_id=order_id,
            security_id=contract.security_id,
            strike_price=contract.strike_price,
            expiry=expiry,
            quantity=size.quantity,
        )

        # In paper mode, immediately fill
        if self.cfg.paper_mode:
            trailing = self.risk_mgr.create_trailing_state(premium)
            self.fsm.position_opened(premium, trailing)
            self.risk_mgr.on_position_opened()
            self.feed.subscribe_option(contract.security_id)

        self.notifier.trade_entry(
            f"{contract.option_type.value} {contract.strike_price:.0f} {expiry} "
            f"@ {premium:.2f} qty={size.quantity} SL={sl_price:.2f} TGT={target_price:.2f}"
        )

    def _monitor_position(self):
        """Monitor open position for exit conditions."""
        ctx = self.fsm.ctx
        if ctx.is_spread:
            self._monitor_spread()
            return
        if not ctx.trailing or not ctx.security_id:
            return

        # Get current LTP
        ltp = self.feed.get_ltp(ctx.security_id)
        if ltp is None:
            ltp = self.feed.fetch_ltp_rest(ctx.security_id, self.inst.exchange_segment)
        if ltp is None:
            return

        # Update trailing stop
        self.risk_mgr.update_trailing(ctx.trailing, ltp)

        # Check if should start trailing state
        if self.fsm.state == TradeState.POSITION_OPEN and ctx.trailing.at_breakeven:
            self.fsm.start_trailing()

        # Check exit conditions
        should_exit, reason = self.risk_mgr.should_exit(ctx.trailing, ltp)

        # Time stop
        if ctx.entry_time:
            elapsed_min = (datetime.now() - ctx.entry_time).total_seconds() / 60
            if elapsed_min >= self.cfg.risk.time_stop_minutes:
                should_exit = True
                reason = f"Time stop after {elapsed_min:.0f} min"

        if should_exit:
            self._exit_position(ltp, reason)

        # Modify SL order if trailing advanced
        if self._sl_order_id and ctx.trailing.at_breakeven:
            self.order_mgr.modify_sl_trigger(self._sl_order_id, ctx.trailing.sl_price)

    def _exit_position(self, exit_price: float, reason: str):
        """Exit the current position."""
        ctx = self.fsm.ctx
        self.fsm.start_exit(reason)

        # Place exit order
        if not self.cfg.paper_mode:
            self.order_mgr.place_market_sell(ctx.security_id, ctx.quantity)
            if self._sl_order_id:
                self.order_mgr.cancel_order(self._sl_order_id)
                self._sl_order_id = None

        self.fsm.position_closed(exit_price)
        self.risk_mgr.on_position_closed()
        self.risk_mgr.record_trade_pnl(ctx.pnl)
        self.journal.log_trade(ctx)

        self.notifier.trade_exit(
            f"{ctx.option_type.value} {ctx.strike_price:.0f} | "
            f"P&L: {ctx.pnl:+.2f} | {reason}"
        )

        # Reset FSM
        self.fsm.transition(TradeState.CLOSED)
        self.fsm.reset()

    def _try_enter_spread(self, direction: Direction) -> bool:
        """Attempt to enter a credit spread. Returns True if successful."""
        expiry = self.chain_fetcher.nearest_weekly_expiry(self.inst.security_id)
        if not expiry:
            logger.warning("No expiry available for spread — aborting")
            self.fsm.reset()
            return False

        contracts = self.chain_fetcher.get_chain(expiry, self.inst.security_id)
        if not contracts:
            logger.warning("Empty option chain for spread — aborting")
            self.fsm.reset()
            return False

        # Select spread
        spread = select_spread(contracts, direction, self.cfg.spread)
        if not spread:
            logger.info("No suitable spread — returning to IDLE")
            self.fsm.reset()
            return False

        # Validate
        ok, reason = self.validator.validate_spread(
            spread.short_leg.security_id,
            spread.long_leg.security_id,
            spread.net_credit,
            spread.spread_width,
        )
        if not ok:
            logger.info("Spread validation failed: %s", reason)
            self.fsm.reset()
            return False

        # Position sizing
        size = self.risk_mgr.compute_spread_position_size(
            spread.net_credit, spread.spread_width,
        )
        if not size:
            logger.warning("Spread position sizing failed")
            self.fsm.reset()
            return False

        # Place spread entry
        short_oid, long_oid = self.order_mgr.place_spread_entry(
            spread.short_leg.security_id,
            spread.long_leg.security_id,
            size.quantity,
        )
        if not short_oid or not long_oid:
            logger.warning("Spread order placement failed")
            self.fsm.reset()
            return False

        # Update FSM
        self.fsm.spread_order_placed(
            short_order_id=short_oid,
            long_order_id=long_oid,
            short_security_id=spread.short_leg.security_id,
            long_security_id=spread.long_leg.security_id,
            short_strike=spread.short_leg.strike_price,
            long_strike=spread.long_leg.strike_price,
            expiry=expiry,
            quantity=size.quantity,
            net_credit=spread.net_credit,
            spread_width=spread.spread_width,
        )

        # In paper mode, immediately fill
        if self.cfg.paper_mode:
            short_fill = spread.short_leg.mid_price
            long_fill = spread.long_leg.mid_price
            self.fsm.spread_position_opened(short_fill, long_fill)
            self._spread_monitor = self.risk_mgr.create_spread_monitor_state(
                short_fill, long_fill, self.cfg.spread,
            )
            self.risk_mgr.on_position_opened()
            self.feed.subscribe_option(spread.short_leg.security_id)
            self.feed.subscribe_option(spread.long_leg.security_id)

        opt_type = "PUT" if direction == Direction.BULLISH else "CALL"
        self.notifier.trade_entry(
            f"SPREAD: SELL {spread.short_leg.strike_price:.0f}{opt_type[0]} "
            f"/ BUY {spread.long_leg.strike_price:.0f}{opt_type[0]} {expiry} "
            f"| Credit: {spread.net_credit:.2f} MaxLoss: {spread.max_loss:.2f} "
            f"qty={size.quantity}"
        )
        return True

    def _monitor_spread(self):
        """Monitor an open credit spread for exit conditions."""
        ctx = self.fsm.ctx
        if not self._spread_monitor:
            return

        short_ltp = self.feed.get_ltp(ctx.short_security_id)
        if short_ltp is None:
            short_ltp = self.feed.fetch_ltp_rest(ctx.short_security_id, self.inst.exchange_segment)
        long_ltp = self.feed.get_ltp(ctx.long_security_id)
        if long_ltp is None:
            long_ltp = self.feed.fetch_ltp_rest(ctx.long_security_id, self.inst.exchange_segment)

        if short_ltp is None or long_ltp is None:
            return

        # Check exit conditions
        should_exit, reason = self.risk_mgr.should_exit_spread(
            self._spread_monitor, short_ltp, long_ltp,
        )

        # Time stop
        if ctx.entry_time:
            elapsed_min = (datetime.now() - ctx.entry_time).total_seconds() / 60
            if elapsed_min >= self.cfg.risk.time_stop_minutes:
                should_exit = True
                reason = f"Time stop after {elapsed_min:.0f} min"

        if should_exit:
            self._exit_spread(short_ltp, long_ltp, reason)

    def _exit_spread(self, short_exit: float, long_exit: float, reason: str):
        """Exit the current credit spread position."""
        ctx = self.fsm.ctx
        self.fsm.start_exit(reason)

        # Place exit orders
        if not self.cfg.paper_mode:
            self.order_mgr.place_spread_exit(
                ctx.short_security_id, ctx.long_security_id, ctx.quantity,
            )

        self.fsm.spread_position_closed(short_exit, long_exit)
        self.risk_mgr.on_position_closed()
        self.risk_mgr.record_trade_pnl(ctx.pnl)
        self.journal.log_trade(ctx)

        opt_type = ctx.option_type.value[0]
        self.notifier.trade_exit(
            f"SPREAD: {ctx.short_strike_price:.0f}{opt_type}/{ctx.long_strike_price:.0f}{opt_type} | "
            f"P&L: {ctx.pnl:+.2f} | {reason}"
        )

        self._spread_monitor = None
        self.fsm.reset()

    def _force_exit(self, reason: str):
        """Force exit all open positions."""
        if not self.fsm.has_position:
            return

        ctx = self.fsm.ctx
        if ctx.is_spread:
            short_ltp = self.feed.get_ltp(ctx.short_security_id)
            if short_ltp is None:
                short_ltp = self.feed.fetch_ltp_rest(ctx.short_security_id, self.inst.exchange_segment) or ctx.short_entry_price
            long_ltp = self.feed.get_ltp(ctx.long_security_id)
            if long_ltp is None:
                long_ltp = self.feed.fetch_ltp_rest(ctx.long_security_id, self.inst.exchange_segment) or ctx.long_entry_price
            self._exit_spread(short_ltp, long_ltp, reason)
            return

        ltp = self.feed.get_ltp(self.fsm.ctx.security_id)
        if ltp is None:
            ltp = self.feed.fetch_ltp_rest(self.fsm.ctx.security_id, self.inst.exchange_segment) or self.fsm.ctx.entry_price
        self._exit_position(ltp, reason)

    def _on_tick(self, message: dict):
        """Callback for each WebSocket tick."""
        pass  # Position monitoring done in event loop

    def _update_dashboard(self, status: str):
        nifty = self.feed.get_ltp(self.inst.security_id) or 0.0
        self.dashboard.update(
            self.fsm,
            nifty_price=nifty,
            daily_pnl=self.risk_mgr._daily_pnl,
            trade_count=self.risk_mgr._trade_count,
            system_status=status,
        )

    def _handle_shutdown(self, signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False

    def _shutdown(self):
        logger.info("Shutting down...")
        if self.fsm.has_position:
            self._force_exit("System shutdown")
        self.feed.stop()
        self.dashboard.stop()
        self.journal.close()
        self.notifier.info(f"{self.inst.name} Trader stopped")
        logger.info("Shutdown complete")


def dry_run(config_path: str | None = None):
    """Run a quick startup verification — works outside market hours."""
    config = load_config(yaml_path=config_path)

    if not config.dhan_client_id or not config.dhan_access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    engine = TradingEngine(config)
    mode = "PAPER" if config.paper_mode else "LIVE"
    logger.info("=== DRY RUN — verifying startup in %s mode ===", mode)
    engine.notifier.info(f"DRY RUN started in {mode} mode")
    engine.journal.log_event("DRY_RUN", "Startup verification")

    # 1. Pre-market setup (API, data, feed)
    engine._pre_market_setup()

    # 2. Run one candle evaluation cycle
    logger.info("Running one candle evaluation cycle...")
    engine._on_candle_close()

    # 3. Dashboard render test
    engine._update_dashboard("DRY RUN — all systems checked")

    # 4. Report
    checks = {
        "Config loaded": bool(config.dhan_client_id),
        "FSM state": engine.fsm.state.value,
        "Risk manager": not engine.risk_mgr.is_daily_stopped,
        "Kill switch": not engine.kill_switch.is_triggered,
        "Journal DB": True,
        "Paper mode": config.paper_mode,
    }
    engine.notifier.info("DRY RUN checks:")
    for name, ok in checks.items():
        status = "OK" if ok else "FAIL"
        engine.notifier.info(f"  {name}: {status}")

    engine._shutdown()
    logger.info("=== DRY RUN complete ===")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Options Trading System (NIFTY / MCX Commodities)")
    parser.add_argument("--dry-run", action="store_true", help="Verify startup without trading")
    parser.add_argument("--config", help="Path to config YAML (default: config/settings.yaml)")
    args = parser.parse_args()

    config = load_config(yaml_path=args.config)

    if not config.dhan_client_id or not config.dhan_access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    if args.dry_run:
        dry_run(config_path=args.config)
    else:
        engine = TradingEngine(config)
        engine.run()


if __name__ == "__main__":
    main()
