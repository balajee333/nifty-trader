"""Benchmark every decision path in the VENOM engine.

Measures wall-clock time (µs) for each component across all scenarios.
Run:  PYTHONPATH=src python3 benchmarks/bench_decisions.py
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Callable

import pandas as pd
import numpy as np

# ── Components under test ────────────────────────────────────────────
from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector
from nifty_trader.strategy.confluence import evaluate_confluence
from nifty_trader.strategy.trail_engine import TrailEngine
from nifty_trader.strategy.time_manager import TimeManager
from nifty_trader.strategy.vix_gate import VixGate
from nifty_trader.strategy.levels import LevelDetector
from nifty_trader.data.indicators import (
    ema, rsi, vwap, volume_sma, is_volume_spike,
    ema_crossover, pivot_levels, round_number_levels,
)
from nifty_trader.backtest.simulator import PremiumSimulator


# ── Helpers ───────────────────────────────────────────────────────────

ITERATIONS = 10_000  # per scenario
WARMUP = 100


def _bench(fn: Callable, iterations: int = ITERATIONS) -> dict:
    """Run fn() `iterations` times and return timing stats in µs."""
    # Warmup
    for _ in range(WARMUP):
        fn()
    # Timed runs
    times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        times.append((t1 - t0) / 1_000)  # ns → µs
    return {
        "min_us": round(min(times), 2),
        "median_us": round(statistics.median(times), 2),
        "p95_us": round(sorted(times)[int(len(times) * 0.95)], 2),
        "p99_us": round(sorted(times)[int(len(times) * 0.99)], 2),
        "max_us": round(max(times), 2),
        "mean_us": round(statistics.mean(times), 2),
    }


def _make_intraday_df(n_candles: int = 75, base: float = 23800.0) -> pd.DataFrame:
    """Generate a synthetic intraday DataFrame (5-min candles)."""
    np.random.seed(42)
    timestamps = pd.date_range("2026-03-09 09:15", periods=n_candles, freq="5min")
    closes = base + np.cumsum(np.random.randn(n_candles) * 15)
    opens = closes + np.random.randn(n_candles) * 5
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n_candles) * 10)
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n_candles) * 10)
    volumes = np.random.randint(500_000, 2_000_000, n_candles).astype(float)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _make_daily_df(n_days: int = 40, base: float = 23500.0) -> pd.DataFrame:
    """Generate synthetic daily candles for level detection."""
    np.random.seed(99)
    dates = pd.date_range(end="2026-03-09", periods=n_days, freq="B")
    closes = base + np.cumsum(np.random.randn(n_days) * 50)
    opens = closes + np.random.randn(n_days) * 20
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n_days) * 30)
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n_days) * 30)
    return pd.DataFrame({
        "timestamp": dates, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": np.random.randint(1e6, 5e6, n_days).astype(float),
    })


# ── Section printers ─────────────────────────────────────────────────

def _header(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _row(label: str, stats: dict):
    print(
        f"  {label:<45s}  "
        f"med={stats['median_us']:>8.1f}µs  "
        f"p95={stats['p95_us']:>8.1f}µs  "
        f"p99={stats['p99_us']:>8.1f}µs"
    )


# ══════════════════════════════════════════════════════════════════════
#  1. OHLC Signal Detection
# ══════════════════════════════════════════════════════════════════════

def bench_ohlc_signal():
    _header("1. OHLC Signal Detection (12 params → SignalType)")
    det = OhlcSignalDetector(index_tolerance_pct=0.10, option_tolerance_abs=1.00)

    scenarios = {
        # Strong bullish: O=L index, O=L CE, O=H PE
        "Strong Bullish (O=L)": (23800, 23900, 23800, 23880,   # index: O=L
                                  140, 170, 140, 165,           # CE: O=L (premium rises)
                                  160, 160, 130, 135),          # PE: O=H (premium drops)
        # Strong bearish: O=H index, O=H CE, O=L PE
        "Strong Bearish (O=H)": (23900, 23900, 23800, 23820,   # index: O=H
                                  170, 170, 140, 142,           # CE: O=H (premium drops)
                                  130, 165, 130, 160),          # PE: O=L (premium rises)
        # Partial bullish: O=L index, neutral options
        "Partial Bullish": (23800, 23880, 23800, 23870,
                            150, 165, 145, 160,
                            150, 155, 140, 142),
        # Partial bearish: O=H index, neutral options
        "Partial Bearish": (23900, 23900, 23830, 23840,
                            150, 152, 135, 138,
                            145, 160, 145, 158),
        # Choppy: CE O=H AND PE O=H (both sold)
        "Choppy (NO_TRADE)": (23850, 23870, 23830, 23855,
                               160, 160, 140, 145,
                               155, 155, 135, 140),
        # Indecisive: mid patterns
        "Indecisive (WAIT)": (23850, 23870, 23830, 23850,
                               150, 158, 143, 150,
                               150, 157, 144, 150),
        # Edge: exactly at tolerance boundary
        "Edge: tolerance boundary": (23850, 23850 * 1.001, 23850 * 0.999, 23845,
                                      150, 150.5, 149, 149.5,
                                      150, 150.5, 149, 149.5),
    }

    for name, args in scenarios.items():
        stats = _bench(lambda a=args: det.detect(*a))
        _row(name, stats)


# ══════════════════════════════════════════════════════════════════════
#  2. VIX Gate (all methods)
# ══════════════════════════════════════════════════════════════════════

def bench_vix_gate():
    _header("2. VIX Gate — Regime Classification & Sizing")
    vg = VixGate()

    vix_values = {
        "FULL (VIX=10)": 10.0,
        "SELECTIVE (VIX=15)": 15.0,
        "CAUTION (VIX=20)": 20.0,
        "RESTRICTED (VIX=25)": 25.0,
        "BLOCKED (VIX=35)": 35.0,
        "Edge: boundary 13.0": 13.0,
        "Edge: boundary 30.0": 30.0,
    }

    # get_mode
    print("  ── get_mode ──")
    for name, v in vix_values.items():
        stats = _bench(lambda v=v: vg.get_mode(v))
        _row(f"get_mode  {name}", stats)

    # size_multiplier
    print("  ── size_multiplier ──")
    for name, v in vix_values.items():
        stats = _bench(lambda v=v: vg.size_multiplier(v))
        _row(f"size_mult {name}", stats)

    # smooth (stateful — 10-reading SMA)
    print("  ── smooth (SMA-10) ──")
    vg2 = VixGate()
    # Pre-fill 9 readings
    for i in range(9):
        vg2.smooth(20.0 + i * 0.5)
    stats = _bench(lambda: vg2.smooth(24.0))
    _row("smooth (10th reading onward)", stats)

    # Combined: full decision (smooth → mode → can_trade → size → confirms → delta)
    print("  ── Full VIX decision pipeline ──")
    vg3 = VixGate()
    for i in range(9):
        vg3.smooth(20.0 + i * 0.3)

    def full_vix_decision():
        s = vg3.smooth(24.0)
        m = vg3.get_mode(s)
        c = vg3.can_trade(s)
        sz = vg3.size_multiplier(s)
        mc = vg3.min_confirmations(s)
        td = vg3.target_delta(s)
        return m, c, sz, mc, td

    stats = _bench(full_vix_decision)
    _row("Full pipeline (smooth→mode→size→delta)", stats)


# ══════════════════════════════════════════════════════════════════════
#  3. Time Manager
# ══════════════════════════════════════════════════════════════════════

def bench_time_manager():
    _header("3. Time Manager — Window Classification & Time Stop")
    tm = TimeManager(time_stop_minutes=15)

    windows = {
        "PRE_MARKET (09:00)": dt_time(9, 0),
        "SIGNAL_DETECTION (09:16)": dt_time(9, 16),
        "PRIME_ENTRY (09:30)": dt_time(9, 30),
        "MORNING_ENTRY (10:30)": dt_time(10, 30),
        "NO_TRADE (12:00)": dt_time(12, 0),
        "AFTERNOON_ENTRY (14:00)": dt_time(14, 0),
        "CLOSING (14:45)": dt_time(14, 45),
        "MARKET_CLOSE (15:20)": dt_time(15, 20),
        "AFTER_HOURS (16:00)": dt_time(16, 0),
    }

    print("  ── get_window ──")
    for name, t in windows.items():
        stats = _bench(lambda t=t: tm.get_window(t))
        _row(f"get_window {name}", stats)

    print("  ── can_enter ──")
    for name, t in windows.items():
        stats = _bench(lambda t=t: tm.can_enter(t))
        _row(f"can_enter  {name}", stats)

    print("  ── should_force_exit ──")
    stats = _bench(lambda: tm.should_force_exit(dt_time(15, 16)))
    _row("should_force_exit (15:16, True)", stats)
    stats = _bench(lambda: tm.should_force_exit(dt_time(14, 0)))
    _row("should_force_exit (14:00, False)", stats)

    print("  ── time_stop_hit ──")
    entry = datetime(2026, 3, 9, 9, 30)
    now_16min = entry + timedelta(minutes=16)
    now_10min = entry + timedelta(minutes=10)

    stats = _bench(lambda: tm.time_stop_hit(entry, now_16min, pnl_pct=2.0))
    _row("time_stop (16min, pnl=2%, → True)", stats)
    stats = _bench(lambda: tm.time_stop_hit(entry, now_10min, pnl_pct=2.0))
    _row("time_stop (10min, pnl=2%, → False)", stats)
    stats = _bench(lambda: tm.time_stop_hit(entry, now_16min, pnl_pct=12.0))
    _row("time_stop (16min, pnl=12%, → False exempt)", stats)


# ══════════════════════════════════════════════════════════════════════
#  4. Trail Engine
# ══════════════════════════════════════════════════════════════════════

def bench_trail_engine():
    _header("4. Trail Engine — SL Management & Rung System")
    te = TrailEngine(sl_pct=30, activation_pct=20, trail_distance_pct=15, max_profit_pct=100)

    print("  ── create_state ──")
    stats = _bench(lambda: te.create_state(150.0))
    _row("create_state (entry=150)", stats)

    print("  ── update (various scenarios) ──")

    # No action — price between SL and entry
    state = te.create_state(150.0)
    stats = _bench(lambda: te.update(state, 140.0))
    _row("update: no action (price=140, SL=105)", stats)

    # SL hit
    state = te.create_state(150.0)
    stats = _bench(lambda: te.update(state, 100.0))
    _row("update: SL hit (price=100)", stats)

    # Rung 1: +20% gain → move SL to cost
    state = te.create_state(150.0)
    stats = _bench(lambda: te.update(state, 182.0))
    _row("update: Rung 1 hit (+21%, SL→cost)", stats)

    # Rung 2: +40% gain
    state = te.create_state(150.0)
    state.peak_price = 210.0
    state.rungs_hit = [0]
    state.sl_price = 150.0
    stats = _bench(lambda: te.update(state, 212.0))
    _row("update: Rung 2 hit (+41%, SL→+20%)", stats)

    # Rung 3: +70% gain
    state = te.create_state(150.0)
    state.peak_price = 255.0
    state.rungs_hit = [0, 1]
    state.sl_price = 180.0
    stats = _bench(lambda: te.update(state, 258.0))
    _row("update: Rung 3 hit (+72%, SL→+45%)", stats)

    # Max profit exit
    state = te.create_state(150.0)
    state.peak_price = 300.0
    state.rungs_hit = [0, 1, 2]
    state.sl_price = 217.5
    stats = _bench(lambda: te.update(state, 302.0))
    _row("update: Max profit exit (+101%)", stats)

    # Trailing (above activation, between rungs)
    state = te.create_state(150.0)
    state.peak_price = 195.0
    state.rungs_hit = [0]
    state.risk_free = True
    state.sl_price = 150.0
    stats = _bench(lambda: te.update(state, 190.0))
    _row("update: Trailing (price=190, peak=195)", stats)


# ══════════════════════════════════════════════════════════════════════
#  5. Level Detector
# ══════════════════════════════════════════════════════════════════════

def bench_levels():
    _header("5. Level Detector — S/R Queries")
    daily_df = _make_daily_df()
    ld = LevelDetector(daily_df)
    price = 23850.0

    print(f"  Levels loaded: {len(ld.all_levels)}")

    stats = _bench(lambda: ld.nearest_support(price))
    _row("nearest_support", stats)

    stats = _bench(lambda: ld.nearest_resistance(price))
    _row("nearest_resistance", stats)

    stats = _bench(lambda: ld.is_near_support(price, 0.5))
    _row("is_near_support (0.5%)", stats)

    stats = _bench(lambda: ld.is_near_resistance(price, 0.5))
    _row("is_near_resistance (0.5%)", stats)

    stats = _bench(lambda: ld.supports_below(price))
    _row("supports_below (list)", stats)

    stats = _bench(lambda: ld.resistances_above(price))
    _row("resistances_above (list)", stats)

    print("  ── Construction ──")
    stats = _bench(lambda: LevelDetector(daily_df), iterations=5_000)
    _row("LevelDetector.__init__ (40 daily candles)", stats)

    stats = _bench(lambda: ld.update_round_levels(23900.0))
    _row("update_round_levels", stats)


# ══════════════════════════════════════════════════════════════════════
#  6. Indicators (pandas vectorized)
# ══════════════════════════════════════════════════════════════════════

def bench_indicators():
    _header("6. Technical Indicators (vectorized on 75-candle DF)")
    df = _make_intraday_df(75)

    stats = _bench(lambda: ema(df["close"], 9), iterations=5_000)
    _row("EMA(9) — 75 candles", stats)

    stats = _bench(lambda: ema(df["close"], 21), iterations=5_000)
    _row("EMA(21) — 75 candles", stats)

    stats = _bench(lambda: rsi(df["close"], 14), iterations=5_000)
    _row("RSI(14) — 75 candles", stats)

    stats = _bench(lambda: vwap(df["high"], df["low"], df["close"], df["volume"]), iterations=5_000)
    _row("VWAP — 75 candles", stats)

    stats = _bench(lambda: volume_sma(df["volume"], 20), iterations=5_000)
    _row("Volume SMA(20) — 75 candles", stats)

    stats = _bench(lambda: is_volume_spike(df["volume"], 20, 1.5), iterations=5_000)
    _row("Volume Spike detect — 75 candles", stats)

    fast = ema(df["close"], 9)
    slow = ema(df["close"], 21)
    stats = _bench(lambda: ema_crossover(fast, slow), iterations=5_000)
    _row("EMA crossover — 75 candles", stats)

    stats = _bench(lambda: pivot_levels(23900, 23750, 23850))
    _row("Pivot levels (scalar)", stats)

    stats = _bench(lambda: round_number_levels(23850))
    _row("Round number levels (scalar)", stats)


# ══════════════════════════════════════════════════════════════════════
#  7. Confluence Scoring
# ══════════════════════════════════════════════════════════════════════

def bench_confluence():
    _header("7. Confluence Scoring (5 signals on 75-candle DF)")
    df = _make_intraday_df(75)
    daily_df = _make_daily_df()
    ld = LevelDetector(daily_df)

    from nifty_trader.config import load_config
    cfg = load_config()

    stats = _bench(lambda: evaluate_confluence(df, ld, cfg.strategy), iterations=2_000)
    _row("evaluate_confluence (full pipeline)", stats)


# ══════════════════════════════════════════════════════════════════════
#  8. Premium Simulator
# ══════════════════════════════════════════════════════════════════════

def bench_simulator():
    _header("8. Premium Simulator")
    sim = PremiumSimulator(scaling_factor=0.4, atm_delta=0.50, slippage_pct=0.5)

    stats = _bench(lambda: sim.estimate_base_premium(23850, 24.0, 5.0))
    _row("estimate_base_premium", stats)

    stats = _bench(lambda: sim.get_entry_premium(23850, 24.0, 5.0))
    _row("get_entry_premium (with slippage)", stats)

    stats = _bench(lambda: sim.simulate_option_ohlc_from_index(23850, 23920, 23790, 23880))
    _row("simulate_option_ohlc_from_index", stats)

    stats = _bench(lambda: sim.premium_at_index_price(23900, 23850, 150.0, "BULLISH"))
    _row("premium_at_index_price (BULLISH)", stats)

    stats = _bench(lambda: sim.premium_at_index_price(23800, 23850, 150.0, "BEARISH"))
    _row("premium_at_index_price (BEARISH)", stats)

    # Premium path with 75 candles
    df = _make_intraday_df(75)
    candles = df.to_dict("records")
    stats = _bench(lambda: sim.simulate_premium_path(candles, "BULLISH", 24.0, 5.0), iterations=2_000)
    _row("simulate_premium_path (75 candles, BULLISH)", stats)

    stats = _bench(lambda: sim.simulate_premium_path(candles, "BEARISH", 24.0, 5.0), iterations=2_000)
    _row("simulate_premium_path (75 candles, BEARISH)", stats)


# ══════════════════════════════════════════════════════════════════════
#  9. Event Logging (simulated _log_event)
# ══════════════════════════════════════════════════════════════════════

def bench_event_logging():
    _header("9. Decision Event Logging Overhead")
    events: list[dict] = []
    now = datetime.now()

    def log_event(event_type: str, **kwargs):
        events.append({"type": event_type, "time": now.strftime("%H:%M:%S"), **kwargs})

    # VIX check event (small payload)
    stats = _bench(lambda: log_event("vix_check", vix=24.0, mode="restricted", can_trade=True, size_mult=0.35))
    _row("log_event: vix_check (4 fields)", stats)

    events.clear()

    # Signal detection event (large payload)
    stats = _bench(lambda: log_event(
        "signal_detection", signal="wait", index_pattern="MID",
        ce_pattern="MID", pe_pattern="MID", reason="No clear O=H/O=L",
        index_ohlc=[23868, 23959, 23698, 23880], source="chain",
    ))
    _row("log_event: signal_detection (8 fields)", stats)

    events.clear()

    # Gate check event (nested dicts)
    gates = [
        {"name": "Time Window", "passed": True, "value": "signal_detection"},
        {"name": "VIX Gate", "passed": True, "value": "24.0 (restricted)"},
        {"name": "Signal", "passed": False, "value": "WAIT"},
    ]
    stats = _bench(lambda: log_event("gate_check", gates=gates))
    _row("log_event: gate_check (nested list)", stats)

    events.clear()

    # Measure list growth impact (simulate full day of events)
    for i in range(100):
        log_event("tick", i=i)
    stats = _bench(lambda: log_event("tick", i=999))
    _row("log_event: after 100 events in list", stats)


# ══════════════════════════════════════════════════════════════════════
#  10. End-to-End Decision Pipeline
# ══════════════════════════════════════════════════════════════════════

def bench_e2e_pipeline():
    _header("10. End-to-End Decision Pipelines")

    # Setup all components
    det = OhlcSignalDetector(index_tolerance_pct=0.10, option_tolerance_abs=1.00)
    vg = VixGate()
    tm = TimeManager(time_stop_minutes=15)
    te = TrailEngine(sl_pct=30, activation_pct=20, trail_distance_pct=15, max_profit_pct=100)
    sim = PremiumSimulator()
    daily_df = _make_daily_df()
    ld = LevelDetector(daily_df)
    df = _make_intraday_df(75)

    from nifty_trader.config import load_config
    cfg = load_config()

    # Pre-fill VIX smoother
    for i in range(9):
        vg.smooth(20.0 + i * 0.3)

    # Pipeline A: Pre-entry decision (no trade → full check)
    # VIX smooth → mode → window → signal detect → gate checks
    def pipeline_no_trade():
        v = vg.smooth(24.0)
        mode = vg.get_mode(v)
        can = vg.can_trade(v)
        window = tm.get_window(dt_time(9, 16))
        entry_ok = tm.can_enter(dt_time(9, 16))
        sig = det.detect(23850, 23870, 23830, 23850,  # index MID
                         150, 158, 143, 150,           # CE MID
                         150, 157, 144, 150)           # PE MID
        # Signal is WAIT → no confluence needed
        return mode, sig.signal_type

    stats = _bench(pipeline_no_trade)
    _row("Pipeline A: No-trade (VIX→signal→WAIT)", stats)

    # Pipeline B: Full entry decision (signal → confluence → strike → entry)
    def pipeline_full_entry():
        v = vg.smooth(15.0)
        mode = vg.get_mode(v)
        can = vg.can_trade(v)
        sz = vg.size_multiplier(v)
        window = tm.get_window(dt_time(9, 16))
        sig = det.detect(23800, 23900, 23800, 23880,  # index O=L
                         140, 170, 140, 165,           # CE O=L
                         160, 160, 130, 135)           # PE O=H
        # Signal is BUY_CE → check confluence
        conf = evaluate_confluence(df, ld, cfg.strategy)
        # Premium estimate
        premium = sim.get_entry_premium(23880, 15.0, 5.0)
        return sig.signal_type, conf.triggered, premium

    stats = _bench(pipeline_full_entry, iterations=2_000)
    _row("Pipeline B: Full entry (VIX→signal→confluence→premium)", stats)

    # Pipeline C: Position monitoring tick (trail update + time stop)
    state = te.create_state(150.0)
    entry_dt = datetime(2026, 3, 9, 9, 30)
    now_dt = datetime(2026, 3, 9, 9, 45)

    def pipeline_monitor_tick():
        action = te.update(state, 165.0)
        ts = tm.time_stop_hit(entry_dt, now_dt, pnl_pct=10.0)
        fe = tm.should_force_exit(dt_time(9, 45))
        return action, ts, fe

    stats = _bench(pipeline_monitor_tick)
    _row("Pipeline C: Monitor tick (trail+time_stop+force_exit)", stats)

    # Pipeline D: VIX blocked → immediate skip
    def pipeline_vix_blocked():
        v = vg.smooth(35.0)
        mode = vg.get_mode(v)
        can = vg.can_trade(v)
        return can  # False

    stats = _bench(pipeline_vix_blocked)
    _row("Pipeline D: VIX blocked → skip", stats)


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║       VENOM Engine — Decision Speed Benchmark                  ║")
    print("║       10,000 iterations per scenario (unless noted)            ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    bench_ohlc_signal()
    bench_vix_gate()
    bench_time_manager()
    bench_trail_engine()
    bench_levels()
    bench_indicators()
    bench_confluence()
    bench_simulator()
    bench_event_logging()
    bench_e2e_pipeline()

    print(f"\n{'=' * 70}")
    print("  BENCHMARK COMPLETE")
    print(f"{'=' * 70}")
    print("  Interpretation:")
    print("    < 10µs   = instant (pure logic, no allocations)")
    print("    10-100µs = fast (small data structures)")
    print("    100µs-1ms = acceptable (pandas vectorized ops)")
    print("    1-10ms   = slow (full confluence pipeline)")
    print("    > 10ms   = investigate (should not happen for decisions)")
    print()
    print("  The 30-second event loop gives 30,000,000µs budget per tick.")
    print("  Even the heaviest pipeline should use < 0.1% of that budget.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
