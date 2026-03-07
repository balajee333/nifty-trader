"""Sandbox regression tests for credit spread support.

Exercises the full spread pipeline against live DhanHQ data (mock trading day).
Uses paper mode — no real orders executed.

Run: pytest tests/test_spread_sandbox.py -v -s
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nifty_trader.config import load_config, AppConfig
from nifty_trader.constants import (
    NIFTY_LOT_SIZE,
    Direction,
    OptionType,
    StrategyMode,
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
# 1. CONFIG — SPREAD SETTINGS LOAD CORRECTLY
# ===================================================================
class TestSpreadConfig:
    """Verify spread config loads from settings.yaml."""

    def test_strategy_mode(self, config):
        mode = StrategyMode(config.strategy_mode)
        assert mode in (StrategyMode.DIRECTIONAL, StrategyMode.CREDIT_SPREAD, StrategyMode.BOTH)
        logger.info("Strategy mode: %s", mode.value)

    def test_spread_config_loaded(self, config):
        sc = config.spread
        assert sc.short_delta_min > 0
        assert sc.short_delta_max > sc.short_delta_min
        assert sc.spread_width_points > 0
        assert sc.min_credit > 0
        assert sc.profit_target_pct > 0
        assert sc.loss_threshold_multiplier > 0
        logger.info(
            "SpreadConfig: delta=[%.2f, %.2f] target=%.2f width=%.0f "
            "min_credit=%.1f profit_target=%.0f%% loss_mult=%.0f iv_min=%.0f",
            sc.short_delta_min, sc.short_delta_max, sc.short_delta_target,
            sc.spread_width_points, sc.min_credit,
            sc.profit_target_pct, sc.loss_threshold_multiplier, sc.iv_rank_min,
        )


# ===================================================================
# 2. SPREAD STRIKE SELECTION ON REAL OPTION CHAIN
# ===================================================================
class TestSpreadSelection:
    """Select spreads from live option chain data."""

    @pytest.fixture
    def chain_data(self, dhan, config):
        from nifty_trader.data.option_chain import OptionChainFetcher
        fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        expiry = fetcher.nearest_weekly_expiry()
        if not expiry:
            pytest.skip("No expiry available")

        time.sleep(3)
        contracts = fetcher.get_chain(expiry)
        if not contracts:
            pytest.skip("No option chain data")

        logger.info("Option chain: %d contracts for expiry %s", len(contracts), expiry)
        puts = [c for c in contracts if c.option_type == OptionType.PUT]
        calls = [c for c in contracts if c.option_type == OptionType.CALL]
        logger.info("  PUTs: %d  CALLs: %d", len(puts), len(calls))

        # Log available deltas for debugging
        for c in sorted(puts, key=lambda x: x.strike_price, reverse=True)[:10]:
            logger.info(
                "  PUT %.0f | delta=%.3f bid=%.2f ask=%.2f vol=%d oi=%d iv=%.1f spread=%.2f%%",
                c.strike_price, c.delta, c.bid, c.ask, c.volume, c.oi, c.iv, c.spread,
            )

        return contracts, expiry

    def test_bull_put_spread(self, chain_data, config):
        from nifty_trader.strategy.strike_selector import select_spread

        contracts, expiry = chain_data
        result = select_spread(contracts, Direction.BULLISH, config.spread)

        if result is None:
            logger.info("No bull put spread found (may be normal — thin data or low IV)")
            # Log why — check each filter stage
            puts = [c for c in contracts if c.option_type == OptionType.PUT]
            delta_ok = [c for c in puts if config.spread.short_delta_min <= abs(c.delta) <= config.spread.short_delta_max]
            logger.info("  PUTs with delta [%.2f, %.2f]: %d",
                        config.spread.short_delta_min, config.spread.short_delta_max, len(delta_ok))
            vol_ok = [c for c in delta_ok if c.volume >= config.spread.min_volume]
            logger.info("  After volume filter (>=%d): %d", config.spread.min_volume, len(vol_ok))
            oi_ok = [c for c in vol_ok if c.oi >= config.spread.min_oi]
            logger.info("  After OI filter (>=%d): %d", config.spread.min_oi, len(oi_ok))
            spread_ok = [c for c in oi_ok if c.spread <= config.spread.max_spread_pct]
            logger.info("  After bid-ask spread filter (<=%.1f%%): %d", config.spread.max_spread_pct, len(spread_ok))
            iv_ok = [c for c in spread_ok if c.iv >= config.spread.iv_rank_min]
            logger.info("  After IV filter (>=%.0f): %d", config.spread.iv_rank_min, len(iv_ok))
            pytest.skip("No bull put spread passed all filters")

        logger.info(
            "Bull Put Spread selected:\n"
            "  SHORT: %s %.0f PUT @ bid=%.2f ask=%.2f mid=%.2f delta=%.3f\n"
            "  LONG:  %s %.0f PUT @ bid=%.2f ask=%.2f mid=%.2f delta=%.3f\n"
            "  Credit: %.2f | Width: %.0f | MaxLoss: %.2f",
            result.short_leg.security_id, result.short_leg.strike_price,
            result.short_leg.bid, result.short_leg.ask, result.short_leg.mid_price,
            result.short_leg.delta,
            result.long_leg.security_id, result.long_leg.strike_price,
            result.long_leg.bid, result.long_leg.ask, result.long_leg.mid_price,
            result.long_leg.delta,
            result.net_credit, result.spread_width, result.max_loss,
        )

        assert result.short_leg.option_type == OptionType.PUT
        assert result.long_leg.option_type == OptionType.PUT
        assert result.short_leg.strike_price > result.long_leg.strike_price
        assert result.net_credit >= config.spread.min_credit
        assert result.spread_width == pytest.approx(config.spread.spread_width_points)
        assert result.max_loss == pytest.approx(result.spread_width - result.net_credit)

    def test_bear_call_spread(self, chain_data, config):
        from nifty_trader.strategy.strike_selector import select_spread

        contracts, expiry = chain_data
        result = select_spread(contracts, Direction.BEARISH, config.spread)

        if result is None:
            logger.info("No bear call spread found (may be normal)")
            pytest.skip("No bear call spread passed all filters")

        logger.info(
            "Bear Call Spread selected:\n"
            "  SHORT: %s %.0f CALL @ mid=%.2f delta=%.3f\n"
            "  LONG:  %s %.0f CALL @ mid=%.2f delta=%.3f\n"
            "  Credit: %.2f | Width: %.0f | MaxLoss: %.2f",
            result.short_leg.security_id, result.short_leg.strike_price,
            result.short_leg.mid_price, result.short_leg.delta,
            result.long_leg.security_id, result.long_leg.strike_price,
            result.long_leg.mid_price, result.long_leg.delta,
            result.net_credit, result.spread_width, result.max_loss,
        )

        assert result.short_leg.option_type == OptionType.CALL
        assert result.long_leg.option_type == OptionType.CALL
        assert result.long_leg.strike_price > result.short_leg.strike_price
        assert result.net_credit >= config.spread.min_credit


# ===================================================================
# 3. SPREAD POSITION SIZING WITH REAL PREMIUMS
# ===================================================================
class TestSpreadSizing:
    """Verify spread position sizing produces valid results."""

    def test_sizing_with_real_credit(self, config):
        from nifty_trader.risk.manager import RiskManager

        mgr = RiskManager(config.risk)
        # Test a range of realistic net credits and widths
        risk_budget = config.risk.capital * config.risk.risk_per_trade_pct / 100

        # Cases that should produce valid sizes
        valid_cases = [
            (5.0, 100.0),   # tight credit
            (12.0, 100.0),  # moderate credit
            (25.0, 100.0),  # wide credit
            (10.0, 50.0),   # narrow spread
        ]
        for credit, width in valid_cases:
            size = mgr.compute_spread_position_size(credit, width)
            assert size is not None, f"Expected valid size for credit={credit} width={width}"
            logger.info(
                "Credit=%.1f Width=%.0f → lots=%d qty=%d risk=%.0f",
                credit, width, size.lots, size.quantity, size.max_risk,
            )
            assert size.lots >= 1
            assert size.quantity == size.lots * NIFTY_LOT_SIZE

        # Case that's too wide — max_loss/lot = (200-20)*25 = 4500 > 2×2000 = 4000
        size = mgr.compute_spread_position_size(20.0, 200.0)
        assert size is None, "200-point spread should be rejected as too risky"
        logger.info("Credit=20 Width=200 → correctly rejected (too risky)")


# ===================================================================
# 4. SPREAD VALIDATION
# ===================================================================
class TestSpreadValidation:
    """Verify spread-specific validation checks."""

    def test_spread_margin_check(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        risk = RiskManager(config.risk)
        validator = OrderValidator(config, risk)

        # Spread margin check independent of time
        ok, reason = validator._check_spread_margin(net_credit=12.0, spread_width=100.0)
        max_loss_per_lot = (100 - 12) * NIFTY_LOT_SIZE  # 2200
        risk_limit = config.risk.capital * config.risk.risk_per_trade_pct / 100

        if max_loss_per_lot > risk_limit:
            assert not ok, "Should reject spread exceeding risk limit"
            logger.info("Spread margin rejected (expected): %s", reason)
        else:
            assert ok
            logger.info("Spread margin check passed: max_loss/lot=%.0f <= limit=%.0f",
                        max_loss_per_lot, risk_limit)

    def test_spread_duplicate_prevention(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        risk = RiskManager(config.risk)
        validator = OrderValidator(config, risk)

        # Mark a recent order
        validator._last_order_security_id = "P22500"
        validator._last_order_time = datetime.now()

        ok, reason = validator._check_duplicate("P22500")
        assert not ok
        logger.info("Spread duplicate prevention: %s", reason)


# ===================================================================
# 5. SPREAD PAPER ORDER FLOW
# ===================================================================
class TestSpreadOrders:
    """Test spread order placement and rollback in paper mode."""

    def test_paper_spread_entry(self, dhan, config):
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker

        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        mgr = OrderManager(dhan, tracker, journal, paper_mode=True)

        short_oid, long_oid = mgr.place_spread_entry(
            short_security_id="P22500",
            long_security_id="P22400",
            quantity=25,
        )
        assert short_oid is not None
        assert long_oid is not None
        assert short_oid.startswith("PAPER-")
        assert long_oid.startswith("PAPER-")

        # Verify both orders tracked
        short_rec = tracker.get_order(short_oid)
        long_rec = tracker.get_order(long_oid)
        assert short_rec.transaction_type == "SELL"
        assert long_rec.transaction_type == "BUY"

        logger.info("Paper spread entry: short=%s long=%s", short_oid, long_oid)
        journal.close()

    def test_paper_spread_exit(self, dhan, config):
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker

        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        mgr = OrderManager(dhan, tracker, journal, paper_mode=True)

        buy_back_oid, sell_long_oid = mgr.place_spread_exit(
            short_security_id="P22500",
            long_security_id="P22400",
            quantity=25,
        )
        assert buy_back_oid is not None
        assert sell_long_oid is not None

        # Verify exit directions
        bb_rec = tracker.get_order(buy_back_oid)
        sl_rec = tracker.get_order(sell_long_oid)
        assert bb_rec.transaction_type == "BUY"   # buy back short
        assert sl_rec.transaction_type == "SELL"  # sell long

        logger.info("Paper spread exit: buy_back=%s sell_long=%s", buy_back_oid, sell_long_oid)
        journal.close()


# ===================================================================
# 6. SPREAD FSM FULL CYCLE (WITH REAL PRICES)
# ===================================================================
class TestSpreadFSMCycle:
    """Full spread lifecycle through FSM with realistic price simulation."""

    def test_winning_spread(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.state import TradeFSM

        fsm = TradeFSM()
        risk = RiskManager(config.risk)

        # 1. Signal detected
        fsm.start_signal(Direction.BULLISH, 2.5, "EMA+VWAP bullish confluence")
        assert fsm.state == TradeState.SIGNAL_DETECTED

        # 2. Spread order placed
        fsm.spread_order_placed(
            short_order_id="PAPER-100",
            long_order_id="PAPER-101",
            short_security_id="P22500",
            long_security_id="P22400",
            short_strike=22500,
            long_strike=22400,
            expiry="2026-03-13",
            quantity=25,
            net_credit=15.0,
            spread_width=100.0,
        )
        assert fsm.state == TradeState.ORDER_PLACED
        assert fsm.ctx.is_spread
        assert fsm.ctx.max_profit == pytest.approx(15.0)
        assert fsm.ctx.max_loss == pytest.approx(85.0)

        # 3. Spread filled
        fsm.spread_position_opened(short_fill=42.0, long_fill=27.0)
        assert fsm.state == TradeState.POSITION_OPEN
        assert fsm.has_position
        assert fsm.ctx.net_credit == pytest.approx(15.0)
        risk.on_position_opened()

        # 4. Monitor — check exit conditions
        monitor = risk.create_spread_monitor_state(42.0, 27.0, config.spread)
        assert monitor.net_credit == pytest.approx(15.0)

        # Simulate theta decay — spread narrows, profit target hit
        # 50% profit: cost to close = 7.5 → short=34.5, long=27.0
        should, reason = risk.should_exit_spread(monitor, 34.5, 27.0)
        assert should
        assert "Profit target" in reason
        logger.info("Exit trigger: %s", reason)

        # 5. Exit spread (skip TRAILING — go straight from POSITION_OPEN to EXITING)
        fsm.start_exit(reason)
        assert fsm.state == TradeState.EXITING

        fsm.spread_position_closed(34.5, 27.0)
        assert fsm.state == TradeState.CLOSED
        # PnL = (15.0 - 7.5) * 25 = 187.5
        assert fsm.ctx.pnl == pytest.approx(187.5)

        risk.on_position_closed()
        risk.record_trade_pnl(fsm.ctx.pnl)

        logger.info(
            "Winning spread: credit=%.2f exit_cost=%.2f pnl=%.2f reason=%s",
            15.0, 7.5, fsm.ctx.pnl, reason,
        )

        fsm.reset()
        assert fsm.is_idle

    def test_losing_spread(self, config):
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.state import TradeFSM

        fsm = TradeFSM()
        risk = RiskManager(config.risk)

        fsm.start_signal(Direction.BULLISH, 2.0, "test")
        fsm.spread_order_placed(
            short_order_id="PAPER-200",
            long_order_id="PAPER-201",
            short_security_id="P22500",
            long_security_id="P22400",
            short_strike=22500, long_strike=22400,
            expiry="2026-03-13", quantity=25,
            net_credit=12.0, spread_width=100.0,
        )
        fsm.spread_position_opened(37.0, 25.0)
        risk.on_position_opened()

        monitor = risk.create_spread_monitor_state(37.0, 25.0, config.spread)

        # Market moves against — short leg inflates, loss threshold hit
        # 2× credit = 24, cost_to_close = 49 - 25 = 24
        should, reason = risk.should_exit_spread(monitor, 49.0, 25.0)
        assert should
        assert "Loss threshold" in reason

        fsm.start_exit(reason)
        fsm.spread_position_closed(49.0, 25.0)
        # PnL = (12 - 24) * 25 = -300
        assert fsm.ctx.pnl == pytest.approx(-300.0)
        assert fsm.ctx.pnl < 0

        risk.on_position_closed()
        risk.record_trade_pnl(fsm.ctx.pnl)

        logger.info(
            "Losing spread: credit=%.2f exit_cost=%.2f pnl=%.2f reason=%s",
            12.0, 24.0, fsm.ctx.pnl, reason,
        )

        fsm.reset()
        assert fsm.is_idle


# ===================================================================
# 7. SPREAD JOURNAL PERSISTENCE
# ===================================================================
class TestSpreadJournal:
    """Verify spread trades are persisted correctly to journal."""

    def test_spread_trade_logged(self):
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.state import TradeContext

        journal = TradeJournal(":memory:")

        ctx = TradeContext(
            direction=Direction.BULLISH,
            option_type=OptionType.PUT,
            security_id="",  # spread uses short/long IDs
            strike_price=0.0,
            expiry="2026-03-13",
            entry_price=15.0,  # net credit
            exit_price=7.5,    # cost to close
            quantity=25,
            pnl=187.5,
            entry_time=datetime.now() - timedelta(minutes=30),
            exit_time=datetime.now(),
            exit_reason="Profit target: 50% captured",
            confluence_score=2.5,
            signals_summary="EMA+VWAP",
            is_spread=True,
            short_security_id="P22500",
            short_strike_price=22500,
            long_security_id="P22400",
            long_strike_price=22400,
            net_credit=15.0,
            spread_width=100.0,
            max_profit=15.0,
            max_loss=85.0,
        )
        journal.log_trade(ctx)

        trades = journal.get_today_trades()
        assert len(trades) == 1
        t = trades[0]
        assert t["is_spread"] == 1
        assert t["short_security_id"] == "P22500"
        assert t["long_security_id"] == "P22400"
        assert t["short_strike_price"] == 22500
        assert t["long_strike_price"] == 22400
        assert t["net_credit"] == pytest.approx(15.0)
        assert t["spread_width"] == pytest.approx(100.0)
        assert t["max_profit"] == pytest.approx(15.0)
        assert t["max_loss"] == pytest.approx(85.0)
        assert t["pnl"] == pytest.approx(187.5)

        logger.info("Spread journal entry verified: %s", {k: v for k, v in t.items() if v is not None})
        journal.close()


# ===================================================================
# 8. KILL SWITCH WITH SPREAD AWARENESS
# ===================================================================
class TestSpreadKillSwitch:
    """Verify kill switch correctly counts spread positions."""

    def test_spread_position_count(self, dhan):
        from nifty_trader.alerts.notifier import Notifier
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.kill_switch import KillSwitch

        tracker = OrderTracker()
        notifier = Notifier(console_enabled=False)
        ks = KillSwitch(dhan, tracker, notifier, capital=100_000)

        # Spread: 1 internal position = 2 API positions
        # If API returns 2 and we say internal=1, is_spread=True → no mismatch
        triggered = ks.check(internal_position_count=1, current_loss=0, is_spread=True)
        # Should NOT trigger (unless API returns something unexpected)
        logger.info("Kill switch with spread (1 internal, 2 expected API): triggered=%s", triggered)

    def test_spread_loss_threshold(self, dhan):
        from nifty_trader.alerts.notifier import Notifier
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.kill_switch import KillSwitch

        tracker = OrderTracker()
        notifier = Notifier(console_enabled=False)
        ks = KillSwitch(dhan, tracker, notifier, capital=100_000, max_single_loss_pct=5.0)

        # Spread loss exceeding limit
        triggered = ks.check(
            internal_position_count=1,
            current_loss=-6000,  # > 5% of 100k
            is_spread=True,
        )
        assert triggered
        logger.info("Kill switch triggered on spread loss: OK")


# ===================================================================
# 9. END-TO-END SPREAD PIPELINE (PAPER MODE)
# ===================================================================
class TestSpreadEndToEnd:
    """Full spread pipeline: data → signal → spread selection → risk → paper order → exit."""

    def test_full_spread_pipeline(self, dhan, config):
        from nifty_trader.data.historical import HistoricalDataFetcher
        from nifty_trader.data.option_chain import OptionChainFetcher
        from nifty_trader.journal.database import TradeJournal
        from nifty_trader.orders.manager import OrderManager
        from nifty_trader.orders.tracker import OrderTracker
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator
        from nifty_trader.state import TradeFSM
        from nifty_trader.strategy.confluence import evaluate_confluence
        from nifty_trader.strategy.levels import LevelDetector
        from nifty_trader.strategy.strike_selector import select_spread

        logger.info("=== SPREAD E2E PIPELINE START ===")

        # 1. Fetch market data
        hist = HistoricalDataFetcher(dhan, config.data.rate_limit_data_per_sec)
        intraday = hist.get_intraday_5min(lookback_days=5)
        time.sleep(0.5)
        daily = hist.get_daily(lookback_days=30)

        if intraday.empty or len(intraday) < 5:
            pytest.skip("Insufficient intraday data")

        # 2. Evaluate confluence
        detector = LevelDetector(daily)
        result = evaluate_confluence(intraday, detector, config.strategy)
        logger.info(
            "Confluence: %s score=%.2f triggered=%s\n  %s",
            result.direction.value, result.score, result.triggered, result.summary,
        )
        # Use the direction even if not triggered (testing the pipeline)
        direction = result.direction

        # 3. Fetch option chain
        chain_fetcher = OptionChainFetcher(dhan, config.data.rate_limit_option_chain_sec)
        expiry = chain_fetcher.nearest_weekly_expiry()
        if not expiry:
            pytest.skip("No expiry available")

        time.sleep(3)
        contracts = chain_fetcher.get_chain(expiry)
        if not contracts:
            pytest.skip("No option chain data")

        logger.info("Option chain: %d contracts for %s", len(contracts), expiry)

        # 4. Select spread
        spread = select_spread(contracts, direction, config.spread)
        if spread is None:
            logger.info("No spread found for %s — pipeline ends here (OK for mock day)", direction.value)
            # Try the other direction
            alt = Direction.BEARISH if direction == Direction.BULLISH else Direction.BULLISH
            spread = select_spread(contracts, alt, config.spread)
            if spread is None:
                pytest.skip("No spread found in either direction")
            direction = alt

        logger.info(
            "Spread selected: SELL %.0f / BUY %.0f (%s)\n"
            "  Credit=%.2f Width=%.0f MaxLoss=%.2f\n  %s",
            spread.short_leg.strike_price, spread.long_leg.strike_price,
            spread.short_leg.option_type.value,
            spread.net_credit, spread.spread_width, spread.max_loss,
            spread.reason,
        )

        # 5. Validate
        risk = RiskManager(config.risk)
        validator = OrderValidator(config, risk)
        ok, val_reason = validator._check_spread_margin(spread.net_credit, spread.spread_width)
        logger.info("Spread margin check: ok=%s reason=%s", ok, val_reason)

        # 6. Position sizing
        size = risk.compute_spread_position_size(spread.net_credit, spread.spread_width)
        if not size:
            pytest.skip("Position sizing returned None")

        logger.info(
            "Position size: lots=%d qty=%d max_risk=%.0f",
            size.lots, size.quantity, size.max_risk,
        )

        # 7. Paper order
        tracker = OrderTracker()
        journal = TradeJournal(":memory:")
        order_mgr = OrderManager(dhan, tracker, journal, paper_mode=True)

        short_oid, long_oid = order_mgr.place_spread_entry(
            spread.short_leg.security_id,
            spread.long_leg.security_id,
            size.quantity,
        )
        assert short_oid is not None, "Short leg order failed"
        assert long_oid is not None, "Long leg order failed"
        logger.info("Orders placed: short=%s long=%s", short_oid, long_oid)

        # 8. FSM lifecycle
        fsm = TradeFSM()
        fsm.start_signal(direction, result.score, result.summary)
        fsm.spread_order_placed(
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

        short_fill = spread.short_leg.mid_price
        long_fill = spread.long_leg.mid_price
        fsm.spread_position_opened(short_fill, long_fill)
        risk.on_position_opened()

        assert fsm.state == TradeState.POSITION_OPEN
        assert fsm.ctx.is_spread
        logger.info(
            "Position OPEN: short_fill=%.2f long_fill=%.2f credit=%.2f",
            short_fill, long_fill, fsm.ctx.net_credit,
        )

        # 9. Monitor — simulate profit target exit
        monitor = risk.create_spread_monitor_state(short_fill, long_fill, config.spread)

        # Simulate theta decay — close at 50% profit
        target_cost = spread.net_credit * 0.5  # cost to close at 50% profit
        sim_short_ltp = long_fill + target_cost  # short price has decayed
        sim_long_ltp = long_fill  # long leg unchanged

        should, exit_reason = risk.should_exit_spread(monitor, sim_short_ltp, sim_long_ltp)
        logger.info(
            "Monitor check: should_exit=%s reason=%s\n"
            "  sim_short=%.2f sim_long=%.2f cost_to_close=%.2f",
            should, exit_reason, sim_short_ltp, sim_long_ltp, sim_short_ltp - sim_long_ltp,
        )

        if should:
            # 10. Exit
            fsm.start_exit(exit_reason)

            # Paper exit
            bb_oid, sl_oid = order_mgr.place_spread_exit(
                spread.short_leg.security_id,
                spread.long_leg.security_id,
                size.quantity,
            )
            assert bb_oid is not None
            assert sl_oid is not None

            fsm.spread_position_closed(sim_short_ltp, sim_long_ltp)
            risk.on_position_closed()
            risk.record_trade_pnl(fsm.ctx.pnl)

            # Log to journal
            journal.log_trade(fsm.ctx)

            logger.info(
                "SPREAD TRADE CLOSED:\n"
                "  Direction: %s\n"
                "  Short: %.0f %s @ entry=%.2f exit=%.2f\n"
                "  Long:  %.0f %s @ entry=%.2f exit=%.2f\n"
                "  Credit: %.2f | Exit cost: %.2f\n"
                "  P&L: %+.2f\n"
                "  Reason: %s",
                direction.value,
                spread.short_leg.strike_price, spread.short_leg.option_type.value,
                short_fill, sim_short_ltp,
                spread.long_leg.strike_price, spread.long_leg.option_type.value,
                long_fill, sim_long_ltp,
                fsm.ctx.net_credit, fsm.ctx.exit_price,
                fsm.ctx.pnl, exit_reason,
            )

            # Verify journal
            trades = journal.get_today_trades()
            assert len(trades) == 1
            assert trades[0]["is_spread"] == 1
            assert trades[0]["pnl"] is not None

            fsm.reset()
            assert fsm.is_idle

        logger.info("=== SPREAD E2E PIPELINE COMPLETE ===")
        journal.close()
