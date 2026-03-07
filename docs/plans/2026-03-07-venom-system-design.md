# VENOM System Design
## VIX-filtered, Entry-confirmed, No-averaging, O=H/L screened, Momentum-driven

**Date**: 2026-03-07
**Status**: Approved
**Project**: nifty-trader (existing codebase upgrade)

---

## Overview

Upgrade the existing `nifty-trader` project into a fully automated options scalping bot (VENOM) for Nifty + BankNifty. The system runs locally on Mac, connects to DhanHQ API, and executes 1-lot directional option buys with full risk management — completely hands-off.

**Scope**: Scalping (5-30 min holds), ₹5K-20K per trade, 1-3 trades/day, target ₹8K-15K/month.

---

## Architecture

Single-process async Python application (Approach A from brainstorming).

```
┌─────────────────────────────────────────────────┐
│                  VENOM Bot (Python)              │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ WebSocket │→ │ Strategy │→ │ Order Engine  │  │
│  │ Feed      │  │ Engine   │  │ (DhanHQ API)  │  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│       ↓              ↓              ↓            │
│  ┌──────────────────────────────────────────┐   │
│  │         State Manager (in-memory+disk)    │   │
│  └──────────────────────────────────────────┘   │
│       ↓                                          │
│  ┌──────────┐  ┌───────────────────────────┐    │
│  │ SQLite   │  │ Rich Terminal Dashboard   │    │
│  └──────────┘  └───────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

---

## What Exists vs. What To Build

### Existing Modules (Keep & Enhance)

| Module | File | Status | Enhancement Needed |
|--------|------|--------|--------------------|
| Config | `config.py` | 100% | Add VENOM-specific params (O=H/O=L, time stops, monthly limits) |
| State | `state.py` | 100% | Add disk persistence (pickle every 10s), crash recovery |
| Feed | `data/feed.py` | 70% | Upgrade from polling to event-driven callbacks |
| Option Chain | `data/option_chain.py` | 100% | Add periodic Greeks refresh during position (every 30s) |
| Indicators | `data/indicators.py` | 100% | No changes needed |
| Historical | `data/historical.py` | 100% | No changes needed |
| Confluence | `strategy/confluence.py` | 100% | Wire to VENOM 5-point confirmation system |
| Strike Selector | `strategy/strike_selector.py` | 100% | Add VIX-based delta targeting |
| Levels | `strategy/levels.py` | 100% | No changes needed |
| Order Manager | `orders/manager.py` | 90% | Add retry logic (3 attempts, exponential backoff) |
| Order Tracker | `orders/tracker.py` | 100% | Add partial fill handling |
| Super Order | `orders/super_order.py` | 80% | No changes needed |
| Risk Manager | `risk/manager.py` | 95% | Add weekly/monthly loss limits |
| Kill Switch | `risk/kill_switch.py` | 90% | Add soft warnings at 50% limit |
| Validator | `risk/validator.py` | 90% | Add VIX gate check |
| Journal DB | `journal/database.py` | 95% | Add monthly stats queries |
| Reconciler | `journal/reconciler.py` | 80% | No changes needed |
| Dashboard | `dashboard/console.py` | 100% | Add signal panel, monthly stats panel |
| Notifier | `alerts/notifier.py` | 100% | No changes needed |
| Constants | `constants.py` | 100% | Add VENOM enums |

### New Modules To Build

| Module | File | Purpose |
|--------|------|---------|
| **O=H/O=L Detector** | `strategy/ohlc_signal.py` | Core VENOM signal — detect Open=High/Open=Low on index + options at 9:16 |
| **VIX Gate** | `strategy/vix_gate.py` | Pre-market VIX check, trading mode selection (full/selective/restricted/blocked) |
| **Time Manager** | `strategy/time_manager.py` | Trading windows, no-trade zones, time-based stops |
| **Trail Engine** | `strategy/trail_engine.py` | Ladder trailing SL (+20% → cost, +40% → lock profit, etc.) |
| **State Persister** | `core/persister.py` | Periodic state dump to disk, crash recovery on startup |
| **Monthly Manager** | `risk/monthly.py` | Weekly/monthly P&L tracking, auto-size reduction, protection mode |
| **VENOM Orchestrator** | `venom.py` | Top-level orchestrator wiring all VENOM components together |

---

## New Module Designs

### 1. O=H/O=L Detector (`strategy/ohlc_signal.py`)

The heartbeat of VENOM. Runs at 9:16 IST after the first 1-min candle closes.

**Input**: First candle OHLC for Nifty spot, BankNifty spot, ATM CE, ATM PE
**Output**: Signal (BUY_CE, BUY_PE, WAIT, NO_TRADE)

```
Signal Matrix:
  Index O=L + CE O=L + PE O=H → BUY_CE (strong bullish)
  Index O=H + CE O=H + PE O=L → BUY_PE (strong bearish)
  Index O=L + options mixed   → WAIT (weak signal)
  Both options O=H            → NO_TRADE (choppy)
```

**Detection logic**:
- Fetch 1-min candle OHLC at 9:16 via historical API or WebSocket accumulated data
- O=H: `abs(open - high) <= tolerance` (tolerance = 0.05% of price or ₹0.50 for options)
- O=L: `abs(open - low) <= tolerance`
- Cache signal for the day — O=H/O=L is a one-time morning check

### 2. VIX Gate (`strategy/vix_gate.py`)

Pre-market and continuous VIX monitoring.

**Modes**:
| VIX | Mode | Position Size | Entry Filter |
|-----|------|--------------|--------------|
| < 13 | FULL | 100% | All signals |
| 13-18 | SELECTIVE | 100% | A+ setups only (4/5+ confirmations) |
| 18-23 | CAUTION | 50% | A+ setups only |
| 23-30 | RESTRICTED | 50% | Only O=L confirmed |
| > 30 | BLOCKED | 0% | No trading |

**Implementation**: Fetch India VIX LTP from WebSocket feed. Check at 9:00 (pre-market gate) and continuously during session (VIX spike gate).

### 3. Time Manager (`strategy/time_manager.py`)

Controls when the system is allowed to act.

**Windows**:
- `PRE_MARKET`: 08:45-09:14 — analysis only
- `SIGNAL_DETECTION`: 09:15-09:20 — O=H/O=L + confirmations
- `PRIME_ENTRY`: 09:16-10:15 — best entries (70% of trades here)
- `MORNING_ENTRY`: 10:15-11:30 — only breakout entries
- `NO_TRADE`: 11:30-13:30 — lunch hour dead zone
- `AFTERNOON_ENTRY`: 13:30-14:30 — only if clear breakout
- `CLOSING`: 14:30-15:15 — expiry day gamma scalps only
- `MARKET_CLOSE`: 15:15-15:30 — square off all positions

**Time-based stop**: If position is flat (±5%) after 20 minutes → exit.

### 4. Trail Engine (`strategy/trail_engine.py`)

Ladder-based trailing stop loss.

**Trail Ladder** (configurable):
```
+20% from entry → Move SL to cost (risk-free)
+40% from entry → Move SL to +20% (lock profit)
+70% from entry → Move SL to +45% (lock more)
+100% from entry → EXIT (take the gift)
```

**Trail Methods**:
- `LADDER` (default): Fixed % ladder as above
- `CANDLE`: Trail below previous 5-min candle low/high
- `VWAP`: Exit if price crosses VWAP against position

**Implementation**: On every tick, check if premium has reached next ladder rung. If yes, modify SL order via DhanHQ API.

### 5. State Persister (`core/persister.py`)

Crash recovery system.

**Persistence**: Every 10 seconds, pickle the following to `~/.venom/state.pkl`:
- Current FSM state
- Open positions (instrument, qty, entry price, SL order ID)
- Order tracker state (pending orders)
- Daily P&L
- Trade count
- Signal state (O=H/O=L result)

**Recovery on startup**:
1. Check if `state.pkl` exists and is < 1 hour old
2. Load state
3. Verify positions against DhanHQ `get_positions()` API
4. If mismatch → reconcile (API is source of truth)
5. Resume trading from recovered state

### 6. Monthly Manager (`risk/monthly.py`)

Tracks weekly/monthly P&L and enforces limits.

**Limits**:
- Daily loss: ₹3,000 → stop trading
- Weekly loss: ₹8,000 → stop until next Monday
- 3 consecutive losses → stop for the day
- MTD > +₹12,000 by 15th → reduce size 30%, A+ only
- MTD < -₹5,000 by 15th → stop 3 days, resume at 50% size

**Storage**: SQLite table `monthly_stats` with columns: date, daily_pnl, trades, wins, losses.

### 7. VENOM Orchestrator (`venom.py`)

Top-level entry point that wires everything together.

```python
async def run():
    # 1. Load config
    # 2. Initialize DhanHQ client
    # 3. Check crash recovery
    # 4. Start WebSocket feed
    # 5. Pre-market: VIX gate check
    # 6. 9:15: Start signal detection
    # 7. On signal: validate → select strike → enter
    # 8. On position: monitor → trail → exit
    # 9. 15:15: Square off all positions
    # 10. EOD: Journal, stats, state cleanup
```

---

## Config Additions

Add to existing YAML config:

```yaml
venom:
  # O=H/O=L
  ohlc_tolerance_index_pct: 0.05  # % tolerance for index O=H/O=L
  ohlc_tolerance_option_abs: 0.50  # ₹ tolerance for option O=H/O=L
  min_confirmations: 3

  # VIX gates
  vix_full: 13
  vix_selective: 18
  vix_caution: 23
  vix_restricted: 30

  # Entry
  entry_window_start: "09:16"
  entry_window_end: "14:30"
  no_trade_start: "11:30"
  no_trade_end: "13:30"

  # Strike selection by VIX
  target_delta_low_vix: 0.50   # VIX < 18
  target_delta_high_vix: 0.65  # VIX > 18
  max_premium_nifty: 265
  max_premium_banknifty: 660

  # Risk
  sl_percent: 30
  trail_activation_pct: 20
  trail_distance_pct: 15
  max_profit_pct: 100
  time_stop_minutes: 20
  max_trades_per_day: 3
  max_daily_loss: 3000
  max_weekly_loss: 8000
  consecutive_loss_limit: 3

  # Monthly
  mtd_protection_threshold: 12000
  mtd_protection_size_reduction: 0.30
  mtd_stop_threshold: -5000
  mtd_stop_days: 3
  mtd_resume_size_reduction: 0.50
```

---

## Dashboard Enhancements

Add two new panels to the existing Rich console:

**Signal Panel** (top):
```
┌─ SIGNALS ──────────────────────────────────────────────┐
│ 09:16 NIFTY  O=L detected │ CE signal │ 4/5 confirmed │
│ 09:16 BNIFTY O=H detected │ PE signal │ 2/5 waiting.. │
└────────────────────────────────────────────────────────┘
```

**Monthly Stats Panel** (bottom):
```
┌─ MONTHLY ──────────────────────────────────────────────┐
│ MTD P&L: +₹8,230 │ Win Rate: 47% │ Avg W/L: 1.8x     │
│ Week P&L: +₹2,100 │ Trades: 7 │ Status: NORMAL       │
└────────────────────────────────────────────────────────┘
```

---

## Testing Strategy

1. **Paper mode first**: Run with existing paper trading mode for 2 weeks
2. **Unit tests**: O=H/O=L detection, VIX gate, time windows, trail ladder
3. **Integration tests**: Signal → strike selection → order placement flow
4. **Replay testing**: Feed historical tick data through the system
5. **Live with 1 trade/day**: First week of live, limit to 1 trade max

---

## Deployment

- **Platform**: Local Mac (user's MacBook)
- **Runtime**: Python 3.13+ with venv
- **Start**: `nifty-trader --mode venom` or `nifty-trader --mode venom --paper`
- **Auto-start**: Optional launchd plist to start at 08:45 IST on weekdays
- **Monitoring**: Rich terminal dashboard (already built)

---

## Risk Disclaimer

This is a personal trading tool. Automated trading carries risk of loss. The system includes kill switches and daily limits, but market conditions can cause losses beyond expected parameters. Always monitor during initial live deployment.
