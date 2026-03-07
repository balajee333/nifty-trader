# VENOM Implementation Plan — Part 2 (Tasks 6-8)

---

## Task 6: Monthly Manager

**Files:**
- Create: `src/nifty_trader/risk/monthly.py`
- Test: `tests/risk/test_monthly.py`

**Step 1: Write failing test**

```python
# tests/risk/test_monthly.py
import pytest
import sqlite3
from nifty_trader.risk.monthly import MonthlyManager

def _make_db(trades):
    """Helper: create in-memory DB with trades."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE trades (
        id INTEGER PRIMARY KEY, timestamp TEXT, pnl REAL,
        entry_time TEXT, exit_time TEXT, exit_reason TEXT)""")
    for t in trades:
        conn.execute("INSERT INTO trades (timestamp, pnl, entry_time, exit_time, exit_reason) VALUES (?,?,?,?,?)", t)
    conn.commit()
    return conn

def test_daily_pnl_limit():
    mm = MonthlyManager(max_daily_loss=3000)
    assert mm.can_trade_today(daily_pnl=-2000)
    assert not mm.can_trade_today(daily_pnl=-3100)

def test_weekly_pnl_limit():
    mm = MonthlyManager(max_weekly_loss=8000)
    assert mm.can_trade_this_week(weekly_pnl=-7000)
    assert not mm.can_trade_this_week(weekly_pnl=-8100)

def test_consecutive_loss_limit():
    mm = MonthlyManager(consecutive_loss_limit=3)
    assert mm.can_trade_after_streak(consecutive_losses=2)
    assert not mm.can_trade_after_streak(consecutive_losses=3)

def test_mtd_protection_mode():
    mm = MonthlyManager(mtd_protection_threshold=12000)
    mode = mm.get_monthly_mode(mtd_pnl=13000, day_of_month=14)
    assert mode.size_reduction == 0.30
    assert mode.only_a_plus

def test_mtd_stop_mode():
    mm = MonthlyManager(mtd_stop_threshold=-5000)
    mode = mm.get_monthly_mode(mtd_pnl=-6000, day_of_month=14)
    assert mode.stopped
    assert mode.stop_days == 3

def test_normal_mode():
    mm = MonthlyManager()
    mode = mm.get_monthly_mode(mtd_pnl=3000, day_of_month=10)
    assert not mode.stopped
    assert mode.size_reduction == 0.0
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/risk/monthly.py
from dataclasses import dataclass

@dataclass
class MonthlyMode:
    stopped: bool = False
    stop_days: int = 0
    size_reduction: float = 0.0
    only_a_plus: bool = False
    resume_size_reduction: float = 0.0

class MonthlyManager:
    def __init__(self, max_daily_loss: float = 3000, max_weekly_loss: float = 8000,
                 consecutive_loss_limit: int = 3, mtd_protection_threshold: float = 12000,
                 mtd_protection_size_reduction: float = 0.30,
                 mtd_stop_threshold: float = -5000, mtd_stop_days: int = 3,
                 mtd_resume_size_reduction: float = 0.50):
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.consecutive_loss_limit = consecutive_loss_limit
        self.mtd_protection_threshold = mtd_protection_threshold
        self.mtd_protection_size_reduction = mtd_protection_size_reduction
        self.mtd_stop_threshold = mtd_stop_threshold
        self.mtd_stop_days = mtd_stop_days
        self.mtd_resume_size_reduction = mtd_resume_size_reduction

    def can_trade_today(self, daily_pnl: float) -> bool:
        return daily_pnl > -self.max_daily_loss

    def can_trade_this_week(self, weekly_pnl: float) -> bool:
        return weekly_pnl > -self.max_weekly_loss

    def can_trade_after_streak(self, consecutive_losses: int) -> bool:
        return consecutive_losses < self.consecutive_loss_limit

    def get_monthly_mode(self, mtd_pnl: float, day_of_month: int) -> MonthlyMode:
        if day_of_month <= 15 and mtd_pnl <= self.mtd_stop_threshold:
            return MonthlyMode(stopped=True, stop_days=self.mtd_stop_days,
                               resume_size_reduction=self.mtd_resume_size_reduction)
        if day_of_month <= 15 and mtd_pnl >= self.mtd_protection_threshold:
            return MonthlyMode(size_reduction=self.mtd_protection_size_reduction,
                               only_a_plus=True)
        return MonthlyMode()

    def compute_consecutive_losses(self, recent_pnls: list[float]) -> int:
        count = 0
        for pnl in reversed(recent_pnls):
            if pnl < 0:
                count += 1
            else:
                break
        return count
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add MonthlyManager with daily/weekly/monthly risk limits"
```

---

## Task 7: State Persister

**Files:**
- Create: `src/nifty_trader/core/__init__.py`
- Create: `src/nifty_trader/core/persister.py`
- Test: `tests/core/test_persister.py`

**Step 1: Write failing test**

```python
# tests/core/test_persister.py
import pytest
import os
import tempfile
from nifty_trader.core.persister import StatePersister, VenomSnapshot

def test_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        persister = StatePersister(path)
        snap = VenomSnapshot(
            fsm_state="POSITION_OPEN",
            position={"security_id": "12345", "entry_price": 145.0,
                      "quantity": 75, "sl_order_id": "ORD-001"},
            daily_pnl=-500.0,
            trade_count=1,
            consecutive_losses=0,
            signal={"type": "BUY_CE", "index_pattern": "O=L"},
            trail_state={"sl_price": 145.0, "peak_price": 160.0, "risk_free": True},
        )
        persister.save(snap)
        loaded = persister.load()
        assert loaded is not None
        assert loaded.fsm_state == "POSITION_OPEN"
        assert loaded.position["entry_price"] == 145.0
        assert loaded.daily_pnl == -500.0
        assert loaded.trail_state["risk_free"] is True

def test_load_missing_file():
    persister = StatePersister("/tmp/nonexistent_venom_state.json")
    assert persister.load() is None

def test_stale_state_rejected():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        persister = StatePersister(path, max_age_seconds=1)
        snap = VenomSnapshot(fsm_state="IDLE")
        persister.save(snap)
        import time; time.sleep(1.5)
        assert persister.load() is None

def test_clear():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        persister = StatePersister(path)
        persister.save(VenomSnapshot(fsm_state="IDLE"))
        persister.clear()
        assert persister.load() is None
```

**Step 2: Run to verify fail**

**Step 3: Implement**

```python
# src/nifty_trader/core/__init__.py
# empty

# src/nifty_trader/core/persister.py
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class VenomSnapshot:
    fsm_state: str = "IDLE"
    position: Optional[dict] = None
    daily_pnl: float = 0.0
    trade_count: int = 0
    consecutive_losses: int = 0
    signal: Optional[dict] = None
    trail_state: Optional[dict] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

class StatePersister:
    def __init__(self, path: str = "~/.venom/state.json",
                 max_age_seconds: int = 3600):
        self._path = os.path.expanduser(path)
        self._max_age = max_age_seconds

    def save(self, snapshot: VenomSnapshot) -> None:
        snapshot.timestamp = time.time()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(snapshot), f)
        os.replace(tmp, self._path)

    def load(self) -> Optional[VenomSnapshot]:
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path) as f:
                data = json.load(f)
            snap = VenomSnapshot(**data)
            if time.time() - snap.timestamp > self._max_age:
                return None
            return snap
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def clear(self) -> None:
        if os.path.exists(self._path):
            os.remove(self._path)
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add StatePersister for crash recovery with JSON snapshots"
```

---

## Task 8: Dashboard Enhancements

**Files:**
- Modify: `src/nifty_trader/dashboard/console.py`
- Test: `tests/dashboard/test_console.py`

**Step 1: Write failing test**

```python
# tests/dashboard/test_console.py
from nifty_trader.dashboard.console import Dashboard

def test_dashboard_accepts_venom_params():
    dash = Dashboard(instrument_name="NIFTY")
    # Should accept new VENOM fields without error
    dash.update(
        fsm=None, nifty_price=24450.0, daily_pnl=2500.0,
        trade_count=1, signals_text="O=L detected", system_status="LIVE",
        vix=14.2, vix_mode="FULL",
        ohlc_signal="BUY_CE: O=L + CE O=L + PE O=H",
        monthly_pnl=8230.0, weekly_pnl=2100.0,
        win_rate=47.0, avg_wl_ratio=1.8,
        trail_status="SL at cost (risk-free)",
    )
    # Verify stored values
    assert dash._vix == 14.2
    assert dash._ohlc_signal == "BUY_CE: O=L + CE O=L + PE O=H"
    assert dash._monthly_pnl == 8230.0
```

**Step 2: Run to verify fail**

**Step 3: Modify `console.py`**

Add new instance variables and update `update()` signature to accept:
- `vix`, `vix_mode` — VIX display
- `ohlc_signal` — O=H/O=L signal display
- `monthly_pnl`, `weekly_pnl`, `win_rate`, `avg_wl_ratio` — monthly stats
- `trail_status` — current trailing SL status

Add two new panels to `_build_layout()`:

**Signal Panel** (between market and position panels):
```python
def _signal_panel(self) -> Panel:
    content = f"VIX: {self._vix:.1f} ({self._vix_mode})\n"
    content += f"O=H/O=L: {self._ohlc_signal or 'Waiting for 09:16...'}\n"
    content += f"Trail: {self._trail_status or 'No position'}"
    return Panel(content, title="Signals", border_style="cyan")
```

**Monthly Stats Panel** (at bottom):
```python
def _monthly_panel(self) -> Panel:
    content = f"MTD: {self._fmt_pnl(self._monthly_pnl)} | "
    content += f"Week: {self._fmt_pnl(self._weekly_pnl)} | "
    content += f"Win%: {self._win_rate:.0f}% | "
    content += f"W/L: {self._avg_wl_ratio:.1f}x"
    return Panel(content, title="Monthly", border_style="blue")
```

**Step 4: Run tests, verify pass**

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add signal and monthly stats panels to dashboard"
```
