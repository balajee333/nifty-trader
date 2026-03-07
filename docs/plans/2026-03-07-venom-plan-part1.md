# VENOM Implementation Plan — Part 1 (Tasks 1-5)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade existing nifty-trader into fully automated VENOM scalping bot

**Architecture:** Add 7 new modules (O=H/O=L, VIX gate, time manager, trail engine, state persister, monthly manager, VENOM orchestrator) to existing codebase, wire through new `venom.py` entry point

**Tech Stack:** Python 3.13, dhanhq SDK, rich, SQLite, asyncio, pyyaml

---

## Task 1: VENOM Config Additions

**Files:**
- Modify: `src/nifty_trader/config.py`
- Modify: `config/settings.yaml`
- Test: `tests/test_config_venom.py`

**Step 1: Write failing test**

```python
# tests/test_config_venom.py
import pytest
from nifty_trader.config import load_config, VenomConfig

def test_venom_config_loads_defaults():
    cfg = load_config("config/settings.yaml")
    v = cfg.venom
    assert isinstance(v, VenomConfig)
    assert v.ohlc_tolerance_index_pct == 0.05
    assert v.min_confirmations == 3
    assert v.vix_blocked == 30
    assert v.sl_percent == 30
    assert v.max_trades_per_day == 3
    assert v.max_daily_loss == 3000
    assert v.max_weekly_loss == 8000
    assert v.time_stop_minutes == 20
    assert v.trail_activation_pct == 20
    assert v.max_profit_pct == 100
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/balajrajendran/projects/nifty-trader && python -m pytest tests/test_config_venom.py -v`
Expected: FAIL — `VenomConfig` not defined

**Step 3: Implement VenomConfig dataclass**

Add to `src/nifty_trader/config.py`:

```python
@dataclass(frozen=True)
class VenomConfig:
    # O=H/O=L detection
    ohlc_tolerance_index_pct: float = 0.05
    ohlc_tolerance_option_abs: float = 0.50
    min_confirmations: int = 3

    # VIX gates
    vix_full: float = 13.0
    vix_selective: float = 18.0
    vix_caution: float = 23.0
    vix_restricted: float = 30.0
    vix_blocked: float = 30.0

    # Entry windows
    entry_window_start: str = "09:16"
    entry_window_end: str = "14:30"
    no_trade_start: str = "11:30"
    no_trade_end: str = "13:30"
    signal_detection_end: str = "09:20"

    # Strike selection by VIX
    target_delta_low_vix: float = 0.50
    target_delta_high_vix: float = 0.65
    max_premium_nifty: float = 265.0
    max_premium_banknifty: float = 660.0

    # Risk
    sl_percent: float = 30.0
    trail_activation_pct: float = 20.0
    trail_distance_pct: float = 15.0
    max_profit_pct: float = 100.0
    time_stop_minutes: int = 20
    max_trades_per_day: int = 3
    max_daily_loss: float = 3000.0
    max_weekly_loss: float = 8000.0
    consecutive_loss_limit: int = 3

    # Monthly
    mtd_protection_threshold: float = 12000.0
    mtd_protection_size_reduction: float = 0.30
    mtd_stop_threshold: float = -5000.0
    mtd_stop_days: int = 3
    mtd_resume_size_reduction: float = 0.50
```

Add `venom: VenomConfig` field to `AppConfig` dataclass. Update `load_config()` to parse `venom:` section from YAML with `_make_sub(raw.get("venom", {}), VenomConfig)`.

Add `venom:` section to `config/settings.yaml` with all defaults.

**Step 4: Run test to verify pass**

Run: `cd /Users/balajrajendran/projects/nifty-trader && python -m pytest tests/test_config_venom.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add VenomConfig dataclass with all VENOM parameters"
```

---

## Task 2: Time Manager

**Files:**
- Create: `src/nifty_trader/strategy/time_manager.py`
- Test: `tests/strategy/test_time_manager.py`

**Step 1: Write failing test**

```python
# tests/strategy/test_time_manager.py
import pytest
from datetime import time
from nifty_trader.strategy.time_manager import TimeManager, TradingWindow

def test_signal_detection_window():
    tm = TimeManager()
    assert tm.get_window(time(9, 16)) == TradingWindow.SIGNAL_DETECTION
    assert tm.get_window(time(9, 19)) == TradingWindow.SIGNAL_DETECTION

def test_prime_entry_window():
    tm = TimeManager()
    assert tm.get_window(time(9, 21)) == TradingWindow.PRIME_ENTRY
    assert tm.get_window(time(10, 14)) == TradingWindow.PRIME_ENTRY

def test_no_trade_zone():
    tm = TimeManager()
    assert tm.get_window(time(11, 30)) == TradingWindow.NO_TRADE
    assert tm.get_window(time(13, 0)) == TradingWindow.NO_TRADE
    assert not tm.can_enter(time(12, 0))

def test_can_enter():
    tm = TimeManager()
    assert tm.can_enter(time(9, 18))
    assert tm.can_enter(time(10, 0))
    assert not tm.can_enter(time(12, 0))
    assert not tm.can_enter(time(15, 20))

def test_should_force_exit():
    tm = TimeManager()
    assert not tm.should_force_exit(time(15, 0))
    assert tm.should_force_exit(time(15, 15))

def test_time_stop(self):
    tm = TimeManager(time_stop_minutes=20)
    from datetime import datetime
    entry = datetime(2026, 3, 9, 9, 20, 0)
    now_ok = datetime(2026, 3, 9, 9, 35, 0)
    now_stop = datetime(2026, 3, 9, 9, 41, 0)
    assert not tm.time_stop_hit(entry, now_ok, pnl_pct=2.0)
    assert tm.time_stop_hit(entry, now_stop, pnl_pct=2.0)  # flat + 20min
    assert not tm.time_stop_hit(entry, now_stop, pnl_pct=25.0)  # profitable, no stop
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/strategy/time_manager.py
from dataclasses import dataclass
from datetime import time, datetime
from enum import Enum

class TradingWindow(Enum):
    PRE_MARKET = "pre_market"
    SIGNAL_DETECTION = "signal_detection"
    PRIME_ENTRY = "prime_entry"
    MORNING_ENTRY = "morning_entry"
    NO_TRADE = "no_trade"
    AFTERNOON_ENTRY = "afternoon_entry"
    CLOSING = "closing"
    MARKET_CLOSE = "market_close"
    AFTER_HOURS = "after_hours"

class TimeManager:
    def __init__(self, time_stop_minutes: int = 20):
        self.time_stop_minutes = time_stop_minutes
        self._windows = [
            (time(8, 45), time(9, 15), TradingWindow.PRE_MARKET),
            (time(9, 15), time(9, 21), TradingWindow.SIGNAL_DETECTION),
            (time(9, 21), time(10, 15), TradingWindow.PRIME_ENTRY),
            (time(10, 15), time(11, 30), TradingWindow.MORNING_ENTRY),
            (time(11, 30), time(13, 30), TradingWindow.NO_TRADE),
            (time(13, 30), time(14, 30), TradingWindow.AFTERNOON_ENTRY),
            (time(14, 30), time(15, 15), TradingWindow.CLOSING),
            (time(15, 15), time(15, 30), TradingWindow.MARKET_CLOSE),
        ]
        self._entry_windows = {
            TradingWindow.SIGNAL_DETECTION,
            TradingWindow.PRIME_ENTRY,
            TradingWindow.MORNING_ENTRY,
            TradingWindow.AFTERNOON_ENTRY,
        }

    def get_window(self, t: time) -> TradingWindow:
        for start, end, window in self._windows:
            if start <= t < end:
                return window
        return TradingWindow.AFTER_HOURS

    def can_enter(self, t: time) -> bool:
        return self.get_window(t) in self._entry_windows

    def should_force_exit(self, t: time) -> bool:
        return t >= time(15, 15)

    def time_stop_hit(self, entry_time: datetime, now: datetime, pnl_pct: float) -> bool:
        if pnl_pct > 15.0:
            return False
        elapsed = (now - entry_time).total_seconds() / 60
        return elapsed >= self.time_stop_minutes and abs(pnl_pct) < 5.0
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add TimeManager with trading windows and time-based stops"
```

---

## Task 3: VIX Gate

**Files:**
- Create: `src/nifty_trader/strategy/vix_gate.py`
- Test: `tests/strategy/test_vix_gate.py`

**Step 1: Write failing test**

```python
# tests/strategy/test_vix_gate.py
from nifty_trader.strategy.vix_gate import VixGate, VixMode

def test_full_mode():
    gate = VixGate()
    assert gate.get_mode(12.0) == VixMode.FULL
    assert gate.size_multiplier(12.0) == 1.0
    assert gate.can_trade(12.0)

def test_selective_mode():
    gate = VixGate()
    assert gate.get_mode(15.0) == VixMode.SELECTIVE
    assert gate.min_confirmations(15.0) == 4

def test_caution_mode():
    gate = VixGate()
    assert gate.get_mode(20.0) == VixMode.CAUTION
    assert gate.size_multiplier(20.0) == 0.5

def test_restricted_mode():
    gate = VixGate()
    assert gate.get_mode(25.0) == VixMode.RESTRICTED
    assert gate.size_multiplier(25.0) == 0.5
    assert gate.min_confirmations(25.0) == 4

def test_blocked_mode():
    gate = VixGate()
    assert gate.get_mode(31.0) == VixMode.BLOCKED
    assert not gate.can_trade(31.0)
    assert gate.size_multiplier(31.0) == 0.0

def test_target_delta():
    gate = VixGate()
    assert gate.target_delta(12.0) == 0.50
    assert gate.target_delta(22.0) == 0.65
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/strategy/vix_gate.py
from enum import Enum

class VixMode(Enum):
    FULL = "full"
    SELECTIVE = "selective"
    CAUTION = "caution"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"

class VixGate:
    def __init__(self, full=13.0, selective=18.0, caution=23.0, blocked=30.0,
                 delta_low=0.50, delta_high=0.65):
        self._full = full
        self._selective = selective
        self._caution = caution
        self._blocked = blocked
        self._delta_low = delta_low
        self._delta_high = delta_high

    def get_mode(self, vix: float) -> VixMode:
        if vix >= self._blocked:
            return VixMode.BLOCKED
        if vix >= self._caution:
            return VixMode.RESTRICTED
        if vix >= self._selective:
            return VixMode.CAUTION
        if vix >= self._full:
            return VixMode.SELECTIVE
        return VixMode.FULL

    def can_trade(self, vix: float) -> bool:
        return self.get_mode(vix) != VixMode.BLOCKED

    def size_multiplier(self, vix: float) -> float:
        mode = self.get_mode(vix)
        if mode == VixMode.BLOCKED:
            return 0.0
        if mode in (VixMode.CAUTION, VixMode.RESTRICTED):
            return 0.5
        return 1.0

    def min_confirmations(self, vix: float) -> int:
        mode = self.get_mode(vix)
        if mode in (VixMode.SELECTIVE, VixMode.RESTRICTED):
            return 4
        return 3

    def target_delta(self, vix: float) -> float:
        return self._delta_high if vix >= self._selective else self._delta_low
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add VixGate with trading mode selection by VIX level"
```

---

## Task 4: O=H/O=L Detector (Core VENOM Signal)

**Files:**
- Create: `src/nifty_trader/strategy/ohlc_signal.py`
- Test: `tests/strategy/test_ohlc_signal.py`

**Step 1: Write failing test**

```python
# tests/strategy/test_ohlc_signal.py
import pytest
from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, OhlcSignal, SignalType

def test_bullish_signal_index_open_eq_low():
    detector = OhlcSignalDetector(index_tolerance_pct=0.05)
    signal = detector.detect(
        index_open=24450.0, index_high=24520.0, index_low=24450.0, index_close=24510.0,
        ce_open=145.0, ce_high=180.0, ce_low=145.0, ce_close=175.0,
        pe_open=120.0, pe_high=120.0, pe_low=85.0, pe_close=90.0,
    )
    assert signal.signal_type == SignalType.BUY_CE
    assert signal.index_pattern == "O=L"
    assert signal.ce_pattern == "O=L"
    assert signal.pe_pattern == "O=H"

def test_bearish_signal_index_open_eq_high():
    detector = OhlcSignalDetector(index_tolerance_pct=0.05)
    signal = detector.detect(
        index_open=24450.0, index_high=24450.0, index_low=24380.0, index_close=24390.0,
        ce_open=145.0, ce_high=145.0, ce_low=100.0, ce_close=105.0,
        pe_open=85.0, pe_high=130.0, pe_low=85.0, pe_close=125.0,
    )
    assert signal.signal_type == SignalType.BUY_PE
    assert signal.index_pattern == "O=H"

def test_no_signal_mid_range():
    detector = OhlcSignalDetector(index_tolerance_pct=0.05)
    signal = detector.detect(
        index_open=24450.0, index_high=24480.0, index_low=24420.0, index_close=24460.0,
        ce_open=145.0, ce_high=155.0, ce_low=138.0, ce_close=150.0,
        pe_open=85.0, pe_high=92.0, pe_low=80.0, pe_close=88.0,
    )
    assert signal.signal_type == SignalType.WAIT

def test_choppy_both_oh():
    detector = OhlcSignalDetector(index_tolerance_pct=0.05)
    signal = detector.detect(
        index_open=24450.0, index_high=24460.0, index_low=24420.0, index_close=24430.0,
        ce_open=145.0, ce_high=145.0, ce_low=130.0, ce_close=132.0,
        pe_open=85.0, pe_high=85.0, pe_low=72.0, pe_close=74.0,
    )
    assert signal.signal_type == SignalType.NO_TRADE

def test_tolerance_applied():
    detector = OhlcSignalDetector(index_tolerance_pct=0.05, option_tolerance_abs=0.50)
    # Index open=100, high=100.04 → within 0.05% tolerance → O=H
    assert detector._is_open_eq_high(100.0, 100.04, is_index=True)
    assert not detector._is_open_eq_high(100.0, 100.06, is_index=True)
    # Option open=150, high=150.40 → within 0.50 abs → O=H
    assert detector._is_open_eq_high(150.0, 150.40, is_index=False)
    assert not detector._is_open_eq_high(150.0, 150.60, is_index=False)
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/strategy/ohlc_signal.py
from dataclasses import dataclass
from enum import Enum

class SignalType(Enum):
    BUY_CE = "buy_ce"
    BUY_PE = "buy_pe"
    WAIT = "wait"
    NO_TRADE = "no_trade"

@dataclass
class OhlcSignal:
    signal_type: SignalType
    index_pattern: str   # "O=H", "O=L", "MID"
    ce_pattern: str
    pe_pattern: str
    reason: str

class OhlcSignalDetector:
    def __init__(self, index_tolerance_pct: float = 0.05,
                 option_tolerance_abs: float = 0.50):
        self._idx_tol = index_tolerance_pct / 100.0
        self._opt_tol = option_tolerance_abs

    def _is_open_eq_high(self, open_p: float, high: float, is_index: bool) -> bool:
        if is_index:
            return (high - open_p) <= open_p * self._idx_tol
        return (high - open_p) <= self._opt_tol

    def _is_open_eq_low(self, open_p: float, low: float, is_index: bool) -> bool:
        if is_index:
            return (open_p - low) <= open_p * self._idx_tol
        return (open_p - low) <= self._opt_tol

    def _pattern(self, open_p: float, high: float, low: float, is_index: bool) -> str:
        if self._is_open_eq_high(open_p, high, is_index):
            return "O=H"
        if self._is_open_eq_low(open_p, low, is_index):
            return "O=L"
        return "MID"

    def detect(self, index_open, index_high, index_low, index_close,
               ce_open, ce_high, ce_low, ce_close,
               pe_open, pe_high, pe_low, pe_close) -> OhlcSignal:
        idx = self._pattern(index_open, index_high, index_low, is_index=True)
        ce = self._pattern(ce_open, ce_high, ce_low, is_index=False)
        pe = self._pattern(pe_open, pe_high, pe_low, is_index=False)

        # Strong bullish: index O=L + CE O=L + PE O=H
        if idx == "O=L" and ce == "O=L" and pe == "O=H":
            return OhlcSignal(SignalType.BUY_CE, idx, ce, pe,
                              "Strong bullish: index + CE opening at low, PE capped")
        # Strong bearish: index O=H + CE O=H + PE O=L
        if idx == "O=H" and ce == "O=H" and pe == "O=L":
            return OhlcSignal(SignalType.BUY_PE, idx, ce, pe,
                              "Strong bearish: index + CE capped at open, PE climbing")
        # Partial bullish: index O=L with mixed options
        if idx == "O=L" and (ce == "O=L" or pe == "O=H"):
            return OhlcSignal(SignalType.BUY_CE, idx, ce, pe,
                              "Partial bullish: index O=L with supporting option signal")
        # Partial bearish: index O=H with mixed options
        if idx == "O=H" and (ce == "O=H" or pe == "O=L"):
            return OhlcSignal(SignalType.BUY_PE, idx, ce, pe,
                              "Partial bearish: index O=H with supporting option signal")
        # Choppy: both options O=H (sellers dominating both sides)
        if ce == "O=H" and pe == "O=H":
            return OhlcSignal(SignalType.NO_TRADE, idx, ce, pe,
                              "Choppy: both CE and PE sold from open")
        # No clear signal
        return OhlcSignal(SignalType.WAIT, idx, ce, pe,
                          "No clear O=H/O=L pattern detected")
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add O=H/O=L signal detector — core VENOM entry logic"
```

---

## Task 5: Trail Engine (Ladder-Based Trailing SL)

**Files:**
- Create: `src/nifty_trader/strategy/trail_engine.py`
- Test: `tests/strategy/test_trail_engine.py`

**Step 1: Write failing test**

```python
# tests/strategy/test_trail_engine.py
from nifty_trader.strategy.trail_engine import TrailEngine, TrailState

def test_initial_sl():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    assert state.sl_price == 70.0
    assert state.peak_price == 100.0
    assert not state.risk_free

def test_move_to_cost_at_20pct():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    action = engine.update(state, current_price=120.0)
    assert state.sl_price == 100.0
    assert state.risk_free
    assert action == "MOVE_SL_TO_COST"

def test_lock_profit_at_40pct():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    engine.update(state, 120.0)  # activate
    action = engine.update(state, 140.0)
    assert state.sl_price == 120.0
    assert action == "LOCK_PROFIT"

def test_lock_more_at_70pct():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    engine.update(state, 120.0)
    engine.update(state, 140.0)
    action = engine.update(state, 170.0)
    assert state.sl_price == 145.0

def test_exit_at_100pct():
    engine = TrailEngine(sl_pct=30, activation_pct=20, max_profit_pct=100)
    state = engine.create_state(entry_price=100.0)
    engine.update(state, 120.0)
    engine.update(state, 140.0)
    engine.update(state, 170.0)
    action = engine.update(state, 200.0)
    assert action == "EXIT_MAX_PROFIT"

def test_sl_hit():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    action = engine.update(state, 69.0)
    assert action == "SL_HIT"

def test_sl_not_lowered():
    engine = TrailEngine(sl_pct=30, activation_pct=20)
    state = engine.create_state(entry_price=100.0)
    engine.update(state, 125.0)  # SL moves to 100
    engine.update(state, 110.0)  # price drops but SL stays at 100
    assert state.sl_price == 100.0
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/strategy/trail_engine.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TrailState:
    entry_price: float
    sl_price: float
    peak_price: float
    risk_free: bool = False
    rungs_hit: list = field(default_factory=list)

class TrailEngine:
    def __init__(self, sl_pct: float = 30, activation_pct: float = 20,
                 trail_distance_pct: float = 15, max_profit_pct: float = 100):
        self.sl_pct = sl_pct
        self.activation_pct = activation_pct
        self.trail_distance_pct = trail_distance_pct
        self.max_profit_pct = max_profit_pct
        # Ladder rungs: (gain_pct, sl_at_pct_of_entry)
        self._rungs = [
            (20, 0),     # +20% → SL at cost (0% gain)
            (40, 20),    # +40% → SL at +20%
            (70, 45),    # +70% → SL at +45%
        ]

    def create_state(self, entry_price: float) -> TrailState:
        sl = entry_price * (1 - self.sl_pct / 100)
        return TrailState(entry_price=entry_price, sl_price=sl, peak_price=entry_price)

    def update(self, state: TrailState, current_price: float) -> Optional[str]:
        # Check SL hit
        if current_price <= state.sl_price:
            return "SL_HIT"

        # Update peak
        if current_price > state.peak_price:
            state.peak_price = current_price

        gain_pct = (current_price - state.entry_price) / state.entry_price * 100

        # Check max profit exit
        if gain_pct >= self.max_profit_pct:
            return "EXIT_MAX_PROFIT"

        # Check ladder rungs
        action = None
        for rung_gain, sl_at in self._rungs:
            if gain_pct >= rung_gain and rung_gain not in state.rungs_hit:
                new_sl = state.entry_price * (1 + sl_at / 100)
                if new_sl > state.sl_price:
                    state.sl_price = new_sl
                    state.rungs_hit.append(rung_gain)
                    if sl_at == 0:
                        state.risk_free = True
                        action = "MOVE_SL_TO_COST"
                    else:
                        action = "LOCK_PROFIT"

        # Continuous trail above highest rung
        if state.rungs_hit and gain_pct > self._rungs[-1][0]:
            trail_sl = state.peak_price * (1 - self.trail_distance_pct / 100)
            if trail_sl > state.sl_price:
                state.sl_price = trail_sl
                action = "TRAILING"

        return action
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add TrailEngine with ladder-based trailing stop loss"
```
