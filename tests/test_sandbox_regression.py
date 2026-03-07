"""Regression tests against DhanHQ Sandbox API.

Exercises every data/order/risk layer against the live sandbox to verify
the implementation handles real API responses correctly.

Run: pytest tests/test_sandbox_regression.py -v -s
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from nifty_trader.config import load_config, AppConfig
from nifty_trader.constants import (
    NIFTY_SECURITY_ID,
    NIFTY_LOT_SIZE,
    Direction,
    ExchangeSegment,
    OptionType,
    TradeState,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config() -> AppConfig:
    cfg = load_config(
        yaml_path=Path(__file__).resolve().parents[1] / "config" / "settings.yaml",
        env_path=Path(__file__).resolve().parents[1] / ".env",
    )
    if not cfg.dhan_client_id or not cfg.dhan_access_token:
        pytest.skip("DHAN credentials not configured in .env")
    return cfg


@pytest.fixture(scope="session")
def dhan(config):
    from dhanhq import dhanhq as DhanHQ
    client = DhanHQ(
        client_id=config.dhan_client_id,
        access_token=config.dhan_access_token,
    )
    if config.dhan_base_url:
        client.base_url = config.dhan_base_url
    return client


# ===================================================================
# 1. API CONNECTIVITY
# ===================================================================
class TestAPIConnectivity:
    """Verify sandbox accepts our credentials."""

    def test_fund_limits(self, dhan):
        """Fund limits endpoint should respond (may return empty in sandbox)."""
        resp = dhan.get_fund_limits()
        assert resp is not None
        # Sandbox may return FUND_LIMIT_ERROR but should not return auth errors
        if resp.get("status") == "failure":
            err = resp.get("remarks", {}).get("error_type", "")
            assert err != "Invalid_Authentication", f"Auth failed: {resp}"
            logger.info("Fund limits (sandbox): %s", err)
        else:
            logger.info("Fund limits: %s", resp.get("data"))

    def test_positions(self, dhan):
        """Positions endpoint should respond."""
        resp = dhan.get_positions()
        assert resp is not None
        logger.info("Positions response status: %s", resp.get("status"))

    def test_order_list(self, dhan):
        """Order list endpoint should respond."""
        resp = dhan.get_order_list()
        assert resp is not None
        logger.info("Order list response status: %s", resp.get("status"))


# ===================================================================
# 2. HISTORICAL DATA
# ===================================================================
class TestHistoricalData:
    """Verify candle data fetching and parsing."""

    def test_daily_candles(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        fetcher = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        df = fetcher.get_daily(lookback_days=30)
        logger.info("Daily candles: %d rows", len(df))

        if df.empty:
            pytest.skip("Sandbox returned no daily data")

        # Validate DataFrame structure
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns
        assert "timestamp" in df.columns

        # Validate data integrity
        assert (df["high"] >= df["low"]).all(), "High should be >= Low"
        assert (df["close"] > 0).all(), "Close should be positive"
        assert df["timestamp"].is_monotonic_increasing, "Timestamps should be sorted"

        logger.info(
            "Daily range: %s to %s | Last close: %.2f",
            df["timestamp"].iloc[0], df["timestamp"].iloc[-1], df["close"].iloc[-1],
        )

    def test_intraday_5min_candles(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        fetcher = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        df = fetcher.get_intraday_5min(lookback_days=5)
        logger.info("Intraday 5min candles: %d rows", len(df))

        if df.empty:
            pytest.skip("Sandbox returned no intraday data")

        assert len(df) > 0
        assert "close" in df.columns
        assert (df["close"] > 0).all()

        logger.info(
            "Intraday range: %s to %s | Candles: %d",
            df["timestamp"].iloc[0], df["timestamp"].iloc[-1], len(df),
        )


# ===================================================================
# 3. INDICATORS ON REAL DATA
# ===================================================================
class TestIndicatorsOnRealData:
    """Run indicators on sandbox candle data and verify outputs."""

    @pytest.fixture
    def intraday_df(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        fetcher = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        df = fetcher.get_intraday_5min(lookback_days=5)
        if df.empty or len(df) < 5:
            pytest.skip("Insufficient intraday data from sandbox")
        return df

    def test_ema(self, intraday_df):
        from nifty_trader.data.indicators import ema
        fast = ema(intraday_df["close"], 9)
        slow = ema(intraday_df["close"], 21)
        assert len(fast) == len(intraday_df)
        assert not fast.isna().all()
        assert not slow.isna().all()
        logger.info("EMA9=%.2f  EMA21=%.2f", fast.iloc[-1], slow.iloc[-1])

    def test_rsi(self, intraday_df):
        from nifty_trader.data.indicators import rsi
        r = rsi(intraday_df["close"], 14)
        valid = r.dropna()
        assert len(valid) > 0
        assert (valid >= 0).all() and (valid <= 100).all()
        logger.info("RSI(14)=%.2f", valid.iloc[-1])

    def test_vwap(self, intraday_df):
        from nifty_trader.data.indicators import vwap
        v = vwap(intraday_df["high"], intraday_df["low"], intraday_df["close"], intraday_df["volume"])
        assert not v.isna().all()
        logger.info("VWAP=%.2f", v.iloc[-1])

    def test_volume_spike(self, intraday_df):
        from nifty_trader.data.indicators import is_volume_spike
        spikes = is_volume_spike(intraday_df["volume"], 20, 1.5)
        spike_count = spikes.sum()
        logger.info("Volume spikes detected: %d / %d candles", spike_count, len(intraday_df))


# ===================================================================
# 4. STRATEGY SIGNALS ON REAL DATA
# ===================================================================
class TestSignalsOnRealData:
    """Evaluate all five signals on live sandbox data."""

    @pytest.fixture
    def market_data(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        fetcher = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        intraday = fetcher.get_intraday_5min(lookback_days=5)
        time.sleep(0.5)  # rate limit
        daily = fetcher.get_daily(lookback_days=60)
        if intraday.empty or len(intraday) < 5:
            pytest.skip("Insufficient intraday data")
        if daily.empty:
            pytest.skip("No daily data")
        return intraday, daily

    def test_all_signals(self, market_data, config):
        from nifty_trader.strategy.signals import (
            evaluate_ema, evaluate_vwap, evaluate_rsi,
            evaluate_volume, evaluate_levels,
        )
        from nifty_trader.strategy.levels import LevelDetector

        intraday, daily = market_data
        detector = LevelDetector(daily)

        signals = {
            "EMA": evaluate_ema(intraday, config.strategy),
            "VWAP": evaluate_vwap(intraday, config.strategy),
            "RSI": evaluate_rsi(intraday, config.strategy),
            "Volume": evaluate_volume(intraday, config.strategy),
            "Levels": evaluate_levels(intraday, detector, config.strategy),
        }

        for name, sig in signals.items():
            assert sig.direction in (Direction.BULLISH, Direction.BEARISH, Direction.NEUTRAL)
            assert 0.0 <= sig.strength <= 1.0
            logger.info("  %s: %s (strength=%.1f) — %s", name, sig.direction.value, sig.strength, sig.reason)

    def test_confluence(self, market_data, config):
        from nifty_trader.strategy.confluence import evaluate_confluence
        from nifty_trader.strategy.levels import LevelDetector

        intraday, daily = market_data
        detector = LevelDetector(daily)
        result = evaluate_confluence(intraday, detector, config.strategy)

        assert result.direction in (Direction.BULLISH, Direction.BEARISH)
        assert len(result.signals) == 5
        logger.info(
            "Confluence: %s score=%.2f triggered=%s",
            result.direction.value, result.score, result.triggered,
        )
        logger.info("  Summary: %s", result.summary)


# ===================================================================
# 5. SUPPORT / RESISTANCE LEVELS
# ===================================================================
class TestLevels:
    """Verify S/R level computation on real daily data."""

    def test_pivot_levels(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        from nifty_trader.strategy.levels import LevelDetector

        fetcher = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        daily = fetcher.get_daily(lookback_days=30)
        if daily.empty:
            pytest.skip("No daily data")

        detector = LevelDetector(daily)
        levels = detector.all_levels
        assert len(levels) > 0

        last_close = float(daily["close"].iloc[-1])
        supports = detector.supports_below(last_close)
        resistances = detector.resistances_above(last_close)

        logger.info("Last close: %.2f", last_close)
        logger.info("Total levels: %d (supports: %d, resistances: %d)",
                     len(levels), len(supports), len(resistances))
        if supports:
            logger.info("Nearest support: %.2f (%s)", supports[-1].price, supports[-1].kind)
        if resistances:
            logger.info("Nearest resistance: %.2f (%s)", resistances[0].price, resistances[0].kind)


# ===================================================================
# 6. OPTION CHAIN
# ===================================================================
class TestOptionChain:
    """Verify option chain fetching and parsing."""

    def test_expiry_list(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        expiries = fetcher.get_expiries()
        logger.info("Expiries returned: %d — %s", len(expiries), expiries[:5])
        # Sandbox may not return expiries
        if not expiries:
            pytest.skip("Sandbox returned no expiries")
        assert all(isinstance(e, str) for e in expiries)

    def test_nearest_expiry(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        nearest = fetcher.nearest_weekly_expiry()
        logger.info("Nearest expiry: %s", nearest)
        if nearest is None:
            pytest.skip("No expiry available in sandbox")
        assert isinstance(nearest, str)

    def test_option_chain_data(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        nearest = fetcher.nearest_weekly_expiry()
        if not nearest:
            pytest.skip("No expiry available")

        time.sleep(3)  # respect rate limit
        contracts = fetcher.get_chain(nearest)
        logger.info("Option chain contracts: %d", len(contracts))

        if not contracts:
            pytest.skip("Sandbox returned no option chain data")

        # Validate structure
        calls = [c for c in contracts if c.option_type == OptionType.CALL]
        puts = [c for c in contracts if c.option_type == OptionType.PUT]
        logger.info("  CALLs: %d  PUTs: %d", len(calls), len(puts))

        for c in contracts[:3]:
            logger.info(
                "  %s %s @ %.0f | LTP=%.2f Bid=%.2f Ask=%.2f Vol=%d OI=%d Delta=%.3f IV=%.1f",
                c.option_type.value, c.expiry, c.strike_price,
                c.ltp, c.bid, c.ask, c.volume, c.oi, c.delta, c.iv,
            )
            assert c.strike_price > 0
            assert c.ltp >= 0


# ===================================================================
# 7. STRIKE SELECTION
# ===================================================================
class TestStrikeSelection:
    """Verify strike selector against real option chain."""

    def test_select_call(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        from nifty_trader.strategy.strike_selector import select_strike

        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        nearest = fetcher.nearest_weekly_expiry()
        if not nearest:
            pytest.skip("No expiry")

        time.sleep(3)
        contracts = fetcher.get_chain(nearest)
        if not contracts:
            pytest.skip("No option chain data")

        result = select_strike(contracts, Direction.BULLISH, config.strike)
        if result is None:
            logger.info("No CALL strike passed filters (expected in sandbox with thin data)")
        else:
            c = result.contract
            logger.info(
                "Selected CALL: strike=%.0f delta=%.3f spread=%.2f%% reason=%s",
                c.strike_price, c.delta, c.spread, result.reason,
            )
            assert c.option_type == OptionType.CALL
            assert config.strike.delta_min <= abs(c.delta) <= config.strike.delta_max

    def test_select_put(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        from nifty_trader.strategy.strike_selector import select_strike

        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        nearest = fetcher.nearest_weekly_expiry()
        if not nearest:
            pytest.skip("No expiry")

        time.sleep(3)
        contracts = fetcher.get_chain(nearest)
        if not contracts:
            pytest.skip("No option chain data")

        result = select_strike(contracts, Direction.BEARISH, config.strike)
        if result is None:
            logger.info("No PUT strike passed filters (expected in sandbox)")
        else:
            c = result.contract
            logger.info(
                "Selected PUT: strike=%.0f delta=%.3f spread=%.2f%%",
                c.strike_price, c.delta, c.spread,
            )
            assert c.option_type == OptionType.PUT


# ===================================================================
# 8. RISK MANAGER WITH REAL PREMIUMS
# ===================================================================
class TestRiskWithRealData:
    """Verify position sizing against real premium prices."""

    def test_position_sizing(self, config):
        from nifty_trader.risk.manager import RiskManager
        mgr = RiskManager(config.risk)

        # Use a realistic NIFTY option premium range
        for premium in [50, 100, 200, 350, 500]:
            size = mgr.compute_position_size(premium)
            if size:
                cost = premium * size.quantity
                logger.info(
                    "Premium=%.0f → lots=%d qty=%d risk=%.0f cost=%.0f",
                    premium, size.lots, size.quantity, size.risk_amount, cost,
                )
                assert cost <= config.risk.capital, f"Cost {cost} exceeds capital"
                assert size.lots >= 1
            else:
                logger.info("Premium=%.0f → insufficient capital", premium)


# ===================================================================
# 9. ORDER PLACEMENT (SANDBOX)
# ===================================================================
class TestOrderPlacement:
    """Test order placement against sandbox (won't execute real trades)."""

    def test_paper_order_flow(self, dhan, config):
        """Full paper order lifecycle."""
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker

        tracker = OrderTracker()
        journal = TradeJournal(":memory:")  # in-memory DB for test
        mgr = OrderManager(dhan, tracker, journal, paper_mode=True)

        # Place paper buy
        order_id = mgr.place_market_buy(security_id="99999", quantity=25)
        assert order_id is not None
        assert order_id.startswith("PAPER-")
        assert tracker.get_order(order_id).status == "PAPER_FILLED"
        logger.info("Paper BUY order: %s", order_id)

        # Place paper SL
        sl_id = mgr.place_sl_order(security_id="99999", quantity=25, trigger_price=130.0)
        assert sl_id is not None
        logger.info("Paper SL order: %s", sl_id)

        # Duplicate should be blocked
        dup_id = mgr.place_market_buy(security_id="99999", quantity=25)
        assert dup_id is None
        logger.info("Duplicate correctly blocked")

        # Paper sell
        sell_id = mgr.place_market_sell(security_id="99999", quantity=25)
        assert sell_id is not None
        logger.info("Paper SELL order: %s", sell_id)

        journal.close()

    def test_sandbox_order_placement(self, dhan, config):
        """Place an actual order against sandbox API (sandbox won't execute)."""
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker

        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        mgr = OrderManager(dhan, tracker, journal, paper_mode=False)

        # Use a dummy security ID — sandbox should accept or reject gracefully
        order_id = mgr.place_market_buy(security_id="49081", quantity=NIFTY_LOT_SIZE)
        logger.info("Sandbox order result: %s", order_id)
        # We don't assert success — sandbox may reject, but it should NOT crash
        if order_id:
            logger.info("Sandbox accepted order: %s", order_id)
            # Try cancel
            mgr.cancel_order(order_id)

        journal.close()


# ===================================================================
# 10. SUPER ORDER (SANDBOX)
# ===================================================================
class TestSuperOrder:
    """Test Super Order placement against sandbox."""

    def test_paper_super_order(self, dhan, config):
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.super_order import SuperOrderManager
        from nifty_trader.orders.tracker import OrderTracker

        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        mgr = SuperOrderManager(dhan, tracker, journal, paper_mode=True)

        order_id = mgr.place_super_order(
            security_id="99999",
            quantity=25,
            sl_price=130.0,
            target_price=340.0,
        )
        assert order_id is not None
        assert "SUPER" in order_id
        logger.info("Paper Super Order: %s", order_id)

        journal.close()


# ===================================================================
# 11. TRADE STATE MACHINE (FULL CYCLE)
# ===================================================================
class TestFSMFullCycle:
    """Simulate a complete trade lifecycle through the FSM."""

    def test_full_trade_cycle(self):
        from nifty_trader.risk.manager import RiskManager, TrailingState
        from nifty_trader.state import TradeFSM

        fsm = TradeFSM()
        risk = RiskManager(load_config().risk)

        # 1. Signal
        fsm.start_signal(Direction.BULLISH, 2.5, "EMA+VWAP confluence")
        assert fsm.state == TradeState.SIGNAL_DETECTED

        # 2. Order placed
        fsm.order_placed("ORD-123", "49081", 22500.0, "2026-03-13", 25)
        assert fsm.state == TradeState.ORDER_PLACED

        # 3. Position opened
        entry = 200.0
        trailing = risk.create_trailing_state(entry)
        fsm.position_opened(entry, trailing)
        assert fsm.state == TradeState.POSITION_OPEN
        assert fsm.has_position
        risk.on_position_opened()

        # 4. Price moves to 50% of target → breakeven
        sl, target = risk.compute_sl_target(entry)
        mid_target = entry + (target - entry) * 0.5
        risk.update_trailing(trailing, mid_target)
        assert trailing.at_breakeven
        assert trailing.sl_price == pytest.approx(entry)

        fsm.start_trailing()
        assert fsm.state == TradeState.TRAILING

        # 5. Target hit
        should_exit, reason = risk.should_exit(trailing, target)
        assert should_exit

        fsm.start_exit(reason)
        assert fsm.state == TradeState.EXITING

        fsm.position_closed(target)
        assert fsm.state == TradeState.CLOSED
        assert fsm.ctx.pnl > 0

        risk.on_position_closed()
        risk.record_trade_pnl(fsm.ctx.pnl)

        logger.info(
            "Trade cycle: entry=%.2f exit=%.2f pnl=%.2f reason=%s",
            entry, target, fsm.ctx.pnl, reason,
        )

        # 6. Reset
        fsm.reset()
        assert fsm.is_idle


# ===================================================================
# 12. JOURNAL DATABASE
# ===================================================================
class TestJournal:
    """Verify trade journal records correctly."""

    def test_log_and_retrieve(self):
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.state import TradeContext

        journal = TradeJournal(":memory:")

        ctx = TradeContext(
            direction=Direction.BULLISH,
            option_type=OptionType.CALL,
            security_id="49081",
            strike_price=22500,
            expiry="2026-03-13",
            entry_price=200.0,
            exit_price=340.0,
            quantity=25,
            pnl=3500.0,
            entry_time=datetime.now() - timedelta(minutes=30),
            exit_time=datetime.now(),
            exit_reason="Target hit",
            confluence_score=2.5,
            signals_summary="EMA+VWAP",
        )
        journal.log_trade(ctx)

        trades = journal.get_today_trades()
        assert len(trades) == 1
        assert trades[0]["pnl"] == 3500.0
        assert trades[0]["direction"] == "BULLISH"
        logger.info("Journal trade recorded: pnl=%.2f", trades[0]["pnl"])

        # Log event
        journal.log_event("TEST", "Regression test event")

        # Update daily summary
        journal.update_daily_summary(100_000)

        journal.close()


# ===================================================================
# 13. ORDER VALIDATOR
# ===================================================================
class TestOrderValidator:
    """Verify pre-order validation checks."""

    def test_time_check_after_cutoff(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        risk = RiskManager(config.risk)
        validator = OrderValidator(config, risk)

        # This will pass or fail depending on current time
        ok, reason = validator.validate("99999", 200.0)
        now = datetime.now().time()
        cutoff_parts = config.timing.no_entry_after.split(":")
        from datetime import time as dtime
        cutoff = dtime(int(cutoff_parts[0]), int(cutoff_parts[1]))
        market_open = dtime(9, 15)

        if now < market_open or now >= cutoff:
            assert not ok, "Should reject outside trading hours"
            logger.info("Validator correctly rejected: %s", reason)
        else:
            logger.info("Validator result during market hours: ok=%s reason=%s", ok, reason)

    def test_daily_loss_rejection(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        risk = RiskManager(config.risk)
        risk.record_trade_pnl(-5000)  # Exceed 3% of 1L
        validator = OrderValidator(config, risk)

        # Test the individual check directly (bypasses time check)
        ok, reason = validator._check_daily_loss()
        assert not ok
        assert "loss" in reason.lower()
        logger.info("Daily loss rejection: %s", reason)

    def test_duplicate_rejection(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        risk = RiskManager(config.risk)
        validator = OrderValidator(config, risk)

        validator._last_order_security_id = "99999"
        validator._last_order_time = datetime.now()

        # Test the individual check directly (bypasses time check)
        ok, reason = validator._check_duplicate("99999")
        assert not ok
        assert "Duplicate" in reason
        logger.info("Duplicate rejection: %s", reason)


# ===================================================================
# 14. KILL SWITCH
# ===================================================================
class TestKillSwitch:
    """Verify kill switch triggers correctly."""

    def test_consecutive_rejections(self, dhan, config):
        from nifty_trader.alerts.notifier import Notifier
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.kill_switch import KillSwitch

        tracker = OrderTracker()
        notifier = Notifier(console_enabled=False)
        ks = KillSwitch(dhan, tracker, notifier, capital=100_000, max_consecutive_rejections=3)

        # Simulate 3 consecutive rejections
        tracker._consecutive_rejections = 3
        triggered = ks.check(internal_position_count=0)
        assert triggered
        assert ks.is_triggered
        logger.info("Kill switch triggered on consecutive rejections: OK")

    def test_loss_threshold(self, dhan, config):
        from nifty_trader.alerts.notifier import Notifier
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.kill_switch import KillSwitch

        tracker = OrderTracker()
        notifier = Notifier(console_enabled=False)
        ks = KillSwitch(dhan, tracker, notifier, capital=100_000, max_single_loss_pct=5.0)

        # Loss exceeding 5% of capital
        triggered = ks.check(internal_position_count=0, current_loss=-6000)
        assert triggered
        logger.info("Kill switch triggered on excess loss: OK")


# ===================================================================
# 15. END-TO-END: SIGNAL → RISK → ORDER (PAPER)
# ===================================================================
class TestEndToEnd:
    """End-to-end flow: data → signals → risk → order (paper mode)."""

    def test_full_pipeline(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        from nifty_trader.data.option_chain import OptionChainFetcher
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.strategy.confluence import evaluate_confluence
        from nifty_trader.strategy.levels import LevelDetector
        from nifty_trader.strategy.strike_selector import select_strike
        from nifty_trader.state import TradeFSM

        # 1. Fetch data
        hist = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        intraday = hist.get_intraday_5min(lookback_days=5)
        time.sleep(0.5)
        daily = hist.get_daily(lookback_days=30)

        if intraday.empty or len(intraday) < 5:
            pytest.skip("Insufficient intraday data from sandbox")

        # 2. Compute levels and signals
        detector = LevelDetector(daily)
        result = evaluate_confluence(intraday, detector, config.strategy)
        logger.info("E2E confluence: %s score=%.2f triggered=%s",
                     result.direction.value, result.score, result.triggered)

        # 3. Fetch option chain
        chain_fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        expiry = chain_fetcher.nearest_weekly_expiry()
        if not expiry:
            logger.info("E2E: No expiry — skipping order phase")
            return

        time.sleep(3)
        contracts = chain_fetcher.get_chain(expiry)
        if not contracts:
            logger.info("E2E: No contracts — skipping order phase")
            return

        # 4. Select strike (use the confluence direction, even if not triggered)
        selection = select_strike(contracts, result.direction, config.strike)
        if not selection:
            logger.info("E2E: No suitable strike passed filters")
            return

        # 5. Risk check
        risk = RiskManager(config.risk)
        premium = selection.contract.ltp or selection.contract.mid_price
        size = risk.compute_position_size(premium)
        if not size:
            logger.info("E2E: Position sizing failed for premium=%.2f", premium)
            return

        sl, target = risk.compute_sl_target(premium)

        # 6. Paper order
        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        mgr = OrderManager(dhan, tracker, journal, paper_mode=True)
        order_id = mgr.place_market_buy(
            security_id=selection.contract.security_id,
            quantity=size.quantity,
        )
        assert order_id is not None

        logger.info(
            "E2E complete: %s %s @ %.0f | premium=%.2f qty=%d SL=%.2f TGT=%.2f | order=%s",
            selection.contract.option_type.value,
            expiry,
            selection.contract.strike_price,
            premium,
            size.quantity,
            sl, target,
            order_id,
        )

        journal.close()
