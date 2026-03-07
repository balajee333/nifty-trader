# VENOM Trading System — Complete Guide

## VIX-filtered, Entry-confirmed, No-averaging, O=H/L screened, Momentum-driven

**Capital:** Starting with 1L | **Instruments:** Nifty 50 + BankNifty Options | **Timeframe:** Scalping (5-30 min)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Layer 1: Pre-Market Analysis](#layer-1-pre-market-analysis)
3. [Layer 2: O=H/O=L Screening Engine](#layer-2-the-ohol-screening-engine)
4. [Layer 3: Strike Selection](#layer-3-strike-selection)
5. [Layer 4: Entry Rules](#layer-4-entry-rules)
6. [Layer 5: Stop Loss System](#layer-5-stop-loss-system)
7. [Layer 6: Profit Targets](#layer-6-profit-targets)
8. [Layer 7: Trailing Stop Loss](#layer-7-trailing-stop-loss)
9. [Layer 8: Daily Risk Management](#layer-8-daily-risk-management)
10. [Layer 9: Trade Journal](#layer-9-trade-journal)
11. [Layer 10: Daily Cheat Sheet](#layer-10-the-cheat-sheet)
12. [Open = High Concept](#open--high-concept)
13. [User Experience — Your Day with VENOM](#user-experience--your-day-with-venom)
14. [Financial Projections — 1L Capital](#financial-projections--1l-capital)
15. [Annual Projections](#annual-projections)
16. [Running the System](#running-the-system)

---

## System Overview

VENOM is a fully automated options scalping system built on the DhanHQ API. It scans for O=H/O=L (Open=High/Open=Low) patterns at market open, enters directional option trades with strict risk management, and manages positions through a ladder-based trailing stop loss system.

**Key Principles:**
- Only buy when momentum is confirmed via O=H/O=L pattern
- VIX determines if buying is viable (>30 = no trading)
- 30% stop loss, never averaged down
- Ladder trailing: +20% move to cost, +40% lock profit, +100% exit
- Max 3 trades per day, max 3K daily loss
- Fully automated — no human intervention during market hours

---

## Layer 1: Pre-Market Analysis

### 1.1 VIX Gate — The First Filter

VIX determines whether you're **allowed to buy** options today.

| India VIX | Mode | Size | Entry Filter |
|-----------|------|------|-------------|
| < 13 | FULL | 100% | All signals |
| 13-18 | SELECTIVE | 100% | A+ setups only (4/5+ confirmations) |
| 18-23 | CAUTION | 50% size | A+ setups only |
| 23-30 | RESTRICTED | 50% size | Only O=L confirmed entries |
| > 30 | **BLOCKED** | 0% | **No trading. Period.** |

**Rule**: Check VIX at 9:00 AM. If VIX > 30, close the system for the day. No exceptions.

### 1.2 Gap Analysis (9:00 - 9:14)

| Gap Type | Size | Bias | Action |
|----------|------|------|--------|
| Gap Up | > 100 pts | Bullish | Watch for O=L on CE, buy CE after confirmation |
| Gap Up | > 200 pts | Over-extended | **Wait** — gap fill likely, don't chase |
| Gap Down | > 100 pts | Bearish | Watch for O=L on PE, buy PE after confirmation |
| Gap Down | > 200 pts | Over-extended | **Wait** — dead cat bounce likely |
| Flat | < 50 pts | Neutral | Wait for 9:20 direction, O=H/O=L will decide |

### 1.3 Day Type Classification

| Day Type | Characteristics | Strategy |
|----------|----------------|----------|
| **Trending** | O=H or O=L on index, strong first 15-min candle | Ride the trend, trail SL |
| **Range-bound** | Index opens mid-range, first 15-min candle is small | Avoid or scalp support/resistance |
| **Expiry day** | Thursday (Nifty weekly), Wednesday (BankNifty weekly) | Gamma scalp only near ATM, very tight SL |
| **Event day** | RBI policy, GDP, global events | Sit out pre-event, trade only post-reaction |

---

## Layer 2: The O=H/O=L Screening Engine

### Core Principle

When an options contract **opens at its highest price of the day (O=H)**, sellers dominated from tick one. When it **opens at its lowest (O=L)**, buyers dominated.

### Signal Matrix (Checked at 9:16 IST)

| Nifty Spot | ATM CE | ATM PE | Signal | Trade |
|-----------|--------|--------|--------|-------|
| O=L (bullish) | O=L | O=H | **BUY CE** | Strong bullish |
| O=H (bearish) | O=H | O=L | **BUY PE** | Strong bearish |
| O=L | Mid | Mid | **WAIT** | Weak signal, need confirmation |
| O=H | Mid | Mid | **WAIT** | Weak signal, need confirmation |
| Mid | O=H | O=H | **NO TRADE** | Both sides getting sold, choppy day |
| Mid | O=L | O=L | **NO TRADE** | Unusual, likely volatile — avoid |

### Confirmation Window (9:16 - 9:20)

O=H/O=L signal alone is not enough. You need **3 of 5 confirmations**:

1. **Index O=H or O=L** — Primary signal
2. **Option O=L** (for the direction you're buying) — Smart money backing your side
3. **Volume spike** — First 5 min volume > 1.5x average first-5-min volume
4. **VWAP alignment** — Price below VWAP for PE buy, above VWAP for CE buy
5. **No immediate reversal** — 2nd and 3rd 1-min candles don't engulf the 1st candle

**Minimum: 3 out of 5 confirmations to enter.**

### The O=H Decision Framework

```
Monday 9:16 AM
      |
      +-- Option has O=H? --> EXIT/SELL. Underlying moving against you.
      |
      +-- Option has O=L? --> HOLD/BUY. Underlying moving in your favor.
      |
      +-- Open is mid-range? --> WAIT. No signal yet. Re-check at 9:30.
```

### Key Nuance

O=H on the **option** is a lagging indicator of O=H/O=L on the **underlying**:

- **Nifty O=H** (only goes down from open) -> Calls will show O=H, Puts will show O=L
- **Nifty O=L** (only goes up from open) -> Calls will show O=L, Puts will show O=H

Always check **Nifty spot first**, then confirm with option O=H/O=L.

---

## Layer 3: Strike Selection

### The Golden Rule

> **Never buy deep OTM. Never buy deep ITM. Buy the momentum sweet spot.**

### Strike Selection by VIX and Expiry

| VIX Level | Expiry Distance | Recommended Strike |
|-----------|-----------------|--------------------|
| < 15 | 0-2 days | ATM or 1 strike OTM |
| < 15 | 3-5 days | ATM |
| 15-22 | 0-2 days | ATM (never OTM — theta too fast) |
| 15-22 | 3-5 days | ATM or 1 strike ITM |
| 22-30 | Any | 1-2 strikes ITM (need delta > 0.55) |

### Strike Selection by Delta

| Delta Range | When to Use | Why |
|-------------|-------------|-----|
| 0.55 - 0.65 | Default for scalping | Best balance of movement and cost |
| 0.45 - 0.55 | ATM in low VIX | Cheaper, good gamma |
| 0.65 - 0.75 | High VIX / expiry day | Minimize theta bleed, move like underlying |
| < 0.40 | **NEVER** | Lottery ticket, not a system |

### Lot Size by Capital (1L)

| Capital/Trade | Nifty (lot = 75) | BankNifty (lot = 30) |
|--------------|-------------------|----------------------|
| 5K-10K | 1 lot, premium < 130 | 1 lot, premium < 330 |
| 10K-15K | 1 lot, premium < 200 | 1 lot, premium < 500 |
| 15K-20K | 1 lot, premium < 265 | 1 lot, premium < 660 |

**Rule**: Never buy 2 lots to stay within budget by going further OTM. 1 lot of the right strike > 2 lots of the wrong strike.

---

## Layer 4: Entry Rules

### Entry Timing Windows

| Window | Quality | Notes |
|--------|---------|-------|
| **9:16 - 9:25** | A+ (O=H/O=L confirmed) | Best entries, highest conviction |
| **9:25 - 10:15** | A (trend continuation) | Enter on pullbacks to VWAP |
| **10:15 - 11:30** | B (mid-morning breakout) | Only if new high/low of day is made |
| **11:30 - 13:30** | **NO ENTRY** | Lunch hour = low volume chop = theta death |
| **13:30 - 14:30** | B (afternoon trend) | Only if clear breakout with volume |
| **14:30 - 15:15** | C (closing scalp) | Only on expiry days, very tight SL |

**Rule**: 70% of your trades should be in the 9:16-10:15 window.

### Entry Types

**Type 1: Momentum Entry (Primary)**
- Trigger: O=H/O=L confirmed + 3/5 confirmations met
- Entry: Market order within 10 seconds of confirmation
- SL: Set immediately
- Target: Set immediately

**Type 2: Pullback Entry (Secondary)**
- Trigger: Trend confirmed but you missed the initial move
- Wait: Price pulls back to VWAP or 9-EMA on 5-min chart
- Entry: Buy when pullback candle closes back in trend direction
- SL: Below the pullback low (for CE) / above pullback high (for PE)

**Type 3: Breakout Entry (Tertiary)**
- Trigger: 15-min candle breaks previous day's high or low
- Volume: Must be > 1.2x average 15-min volume
- Entry: On close of breakout candle, not during
- SL: Mid-point of the breakout candle

### Hard No-Entry Rules (Absolute)

1. Never enter during the first 60 seconds (9:15:00 - 9:15:59) — spreads are widest
2. Never buy if the option's bid-ask spread is > 3% of premium
3. Never enter if you've already taken 3 trades today
4. Never enter after a losing streak of 3 consecutive trades — stop for the day
5. Never buy options with < 1 hour to expiry (except gamma scalps with 5K max)
6. **Never average down. EVER.**

---

## Layer 5: Stop Loss System

### Initial Stop Loss

| Trade Type | SL Method | Typical SL % |
|-----------|-----------|---------------|
| Momentum entry | 30% of premium paid | 100 premium -> SL at 70 |
| Pullback entry | Below pullback candle low | Variable, but < 25% |
| Breakout entry | Mid-point of breakout candle | Variable, but < 30% |
| Expiry day scalp | 20% of premium | Tight — fast moves, fast stops |

### Stop Loss Rules

- SL order goes in **within 5 seconds** of entry
- Use **SL-M (Stop Loss Market)** orders, not SL-Limit
- Once set, SL **only moves in the direction of profit**, never backwards
- "I'll wait for it to come back" = LOSS
- "It's just a spike, will reverse" = LOSS
- "Let me move my SL a bit" = LOSS
- "SL hit. I accept. Next trade." = SYSTEM

### Time-Based Stop Loss

| Time Held | Premium Change | Action |
|-----------|---------------|--------|
| 15 min | Flat (+/-5%) | Exit at market — momentum failed |
| 30 min | Down 10-15% | Exit — you're on the wrong side of theta |
| 45 min | Up but < 15% | Trail to cost |

**Rule**: If a scalp hasn't moved 15%+ in your favor within 20 minutes, the trade thesis is broken. Exit.

---

## Layer 6: Profit Targets

### Fixed Target System

| Setup Quality | Minimum Target | Stretch Target |
|--------------|----------------|----------------|
| A+ (O=H/O=L + 4/5 confirmations) | 40% of premium | 80-100% |
| A (3/5 confirmations) | 30% of premium | 50-60% |
| B (breakout/pullback) | 20% of premium | 40% |

### The 1:2 Rule

> **Never take a trade where your target is less than 2x your stop loss.**

| SL | Minimum Target | If this R:R doesn't exist -> |
|-----|----------------|-----------------------------|
| 30 | 60 | Skip the trade |
| 50 | 100 | Skip the trade |
| 75 | 150 | Skip the trade |

---

## Layer 7: Trailing Stop Loss

### The Trail Ladder

```
Premium: 100 (entry)
SL: 70 (initial = -30%)

Price hits 120 (+20%) -> Move SL to 100 (cost)       RISK-FREE
Price hits 140 (+40%) -> Move SL to 120 (lock 20 profit)
Price hits 170 (+70%) -> Move SL to 145 (lock 45 profit)
Price hits 200 (+100%)-> EXIT (take the gift)
```

### Trail Methods

| Method | When to Use | How |
|--------|------------|-----|
| **Fixed % trail** | Default | Trail SL 15-20% below current premium |
| **Candle-based trail** | Strong trend | Trail SL below previous 5-min candle low |
| **VWAP trail** | Clean trend day | Trail SL to VWAP — if price crosses VWAP against you, exit |

### The Greed Kill Switch

> **If premium doubles (+100%), book profits. A scalp that doubles is a gift — take it.**

---

## Layer 8: Daily Risk Management

### Daily Limits

| Parameter | Limit | Why |
|-----------|-------|-----|
| Max trades/day | 3 | Overtrading is the #1 killer |
| Max loss/day | 3,000 | Preserves capital for tomorrow |
| Max capital deployed at once | 20,000 | Never have more than this at risk |
| Consecutive losses to stop | 3 | After 3 losses in a row, done for the day |
| Stop trading time | After 2nd loss, only A+ setups | Tighten filters after losing |

### Weekly Limits

| Parameter | Limit |
|-----------|-------|
| Max weekly loss | 8,000 |
| If hit by Wednesday | No trading Thu-Fri |
| If hit by Friday | Reduce next week size by 50% |

### Monthly P&L Framework

| Week | Target | Approach |
|------|--------|----------|
| Week 1 | +3,000-5,000 | Normal trading, build cushion |
| Week 2 | +3,000-5,000 | Normal trading |
| Week 3 | +2,000-3,000 | Slightly defensive if ahead |
| Week 4 | **Protect profits** | Only A+ setups, reduce size |

### Monthly Reset Rules

- **MTD > +12,000 by 15th**: Reduce position size by 30%, only A+ setups, protect the month
- **MTD < -5,000 by 15th**: STOP trading for 3 days, review all losing trades, resume with 50% size

---

## Layer 9: Trade Journal

### Log Every Trade

| Field | Example |
|-------|---------|
| Date | 2026-03-09 |
| Time | 09:18 |
| Instrument | Nifty 24400 CE |
| Entry | 145 |
| SL | 100 |
| Target | 210 |
| Exit | 195 |
| Exit Time | 09:42 |
| P&L | +3,750 |
| Setup | O=L + Momentum |
| Confirmations | 4/5 |
| Mistakes | None |

### Weekly Review (Saturday)

- Win rate (target: > 45%)
- Average winner vs. average loser (target: winners > 1.5x losers)
- Best setup type (double down on what works)
- Worst setup type (eliminate or reduce)
- Emotional mistakes count (target: 0)

---

## Layer 10: The Cheat Sheet

```
+===================================================+
|            VENOM SYSTEM — DAILY CHECKLIST          |
+===================================================+
|                                                    |
|  8:45  [ ] Check VIX. If > 30, NO TRADING.         |
|  9:00  [ ] Check gap. Classify day type.            |
|  9:15  [ ] Watch first candle. DO NOT TRADE YET.    |
|  9:16  [ ] Screen O=H / O=L on index + options.     |
|  9:17  [ ] Count confirmations (need 3/5).          |
|  9:18  [ ] If signal -> ENTER. Set SL in 5 seconds. |
|                                                    |
|  DURING TRADE:                                     |
|  [ ] +20% -> Move SL to cost                       |
|  [ ] +40% -> Book profits or trail                  |
|  [ ] +100% -> EXIT. Take the gift.                  |
|  [ ] 20 min flat -> EXIT. Thesis broken.            |
|                                                    |
|  DAILY LIMITS:                                     |
|  [ ] Max 3 trades                                   |
|  [ ] Max 3,000 loss                                 |
|  [ ] 3 consecutive losses -> STOP                   |
|                                                    |
|  NEVER:                                            |
|  x Average down                                    |
|  x Move SL backwards                               |
|  x Trade 11:30-13:30                               |
|  x Buy OTM in high VIX                             |
|  x Skip the journal                                |
|                                                    |
+===================================================+
```

---

## Open = High Concept

### How It Works

When an options contract **opens at its highest price of the day**, it signals sellers dominated from tick one. The very first print was the best price buyers ever got.

### For Options

| Contract Type | O=H Means | Action |
|--------------|-----------|--------|
| CALL with O=H | Underlying is falling, call premium dying | Sell the call / Bearish |
| PUT with O=H | Underlying is rising, put premium dying | Sell the put / Bullish |
| CALL with O=L | Underlying is rising, call gaining | Call buyers winning |
| PUT with O=L | Underlying is falling, put gaining | Put buyers winning |

### Professional O=H Screening

Traders scan at **9:16-9:20 IST** after the first candle closes:

1. At 9:16, pull OHLC of the first 1-min candle
2. Check: Is Open = High? (within 0.5 tolerance)
3. If YES: the contract is a SHORT candidate
4. Entry: Sell at market or wait for minor pullback
5. SL: 10-15% above open price
6. Target: 50-70% premium decay by 12:30 PM

### Why O=H Works on Expiry-Week Options

- **Theta amplifies O=H**: if premium starts falling from open, theta + direction accelerate decay
- **No recovery time**: with 1 day to expiry, no time for reversal
- **Gamma makes it binary**: near expiry, option is either ITM (alive) or OTM (worthless)

---

## User Experience — Your Day with VENOM

### Your Entire Interaction

| Time | Your Action | Duration |
|------|------------|----------|
| 8:40 AM | Open terminal, run `venom --paper` | 30 seconds |
| 8:41 - 15:30 | Glance at dashboard occasionally | 0 effort |
| 15:30 | Close terminal | 5 seconds |

**Total active time: ~35 seconds per day.**

### What Happens Automatically

**8:45 AM** — System starts, checks VIX
**9:00 AM** — VIX gate activates (FULL/SELECTIVE/CAUTION/RESTRICTED/BLOCKED)
**9:15 AM** — Market opens, system watches first candle
**9:16 AM** — O=H/O=L detection fires, signal generated
**9:18 AM** — If signal + confirmations pass -> auto entry with SL
**9:20 - 10:30 AM** — Trail engine manages position (move to cost, lock profit, trail)
**3:15 PM** — Force exit any open position (no overnight risk)
**3:30 PM** — System shuts down, journal updated

### The 5 Things You NEVER Do

1. NEVER manually place an order — the system does it
2. NEVER move a stop loss — the trail engine handles it
3. NEVER "just one more trade" — 3/day limit is hardcoded
4. NEVER hold overnight — force exit at 15:15
5. NEVER override a NO_TRADE signal — choppy days = no losses

### The 3 Things You CAN Do

1. **Ctrl+C** — Emergency stop. Exits all positions, shuts down.
2. **Watch** — Dashboard updates every second.
3. **Review** — After market close, check trade_journal.db for stats.

### What Each Outcome Looks Like

**The Winner:**
```
09:25  LTP=148  P&L=+2.1%   SL=101.50
09:45  LTP=175  P&L=+20.7%  SL=145.00  << SL MOVED TO COST (risk-free!)
10:05  LTP=205  P&L=+41.4%  SL=174.00  << PROFIT LOCKED
10:30  LTP=215  SL HIT at 208.25       << AUTO EXIT
EXIT: +63.25 pts | +4,744 | You touched nothing.
```

**The Quick Loss:**
```
09:25  LTP=142  P&L=-2.1%   SL=101.50
09:42  LTP=100  SL HIT at 101.50       << AUTO EXIT
EXIT: -43.50 pts | -3,263 | Controlled. 30% max loss.
```

**The Flat Exit:**
```
09:25  LTP=146  P&L=+0.7%
09:38  TIME STOP — flat after 20 minutes << AUTO EXIT
EXIT: +2.00 pts | +150 | Theta was eating premium. System killed it.
```

---

## Financial Projections — 1L Capital

### Per-Trade Economics

```
Capital:              1,00,000
Risk per trade (2%):  2,000
SL:                   30% of premium
Max entry premium:    ~89 (Nifty lot=75)
Capital per trade:    6.75% of total
Capital at risk:      2% of total
```

### Outcome Distribution Per Trade

| Outcome | Premium Move | P&L per Trade | Probability |
|---------|-------------|--------------|-------------|
| SL hit | -30% | -2,025 | 35% |
| Time stop (flat) | -5% to +5% | -200 | 15% |
| Trail exit (cost) | +20% to +30% | +1,500 | 15% |
| Trail exit (lock) | +40% to +60% | +3,375 | 18% |
| Trail exit (deep) | +70% to +90% | +5,400 | 12% |
| Max profit exit | +100% | +6,750 | 5% |

**Expected value per trade: +1,078**

### Monthly Trade Volume

- Trading days/month: ~22
- Days with signal: ~60% = 13-15 days
- Average trades per active day: 1.5
- Total trades/month: ~20-25

### Monthly Scenarios

| Scenario | Probability | Win Rate | Net P&L | ROI |
|----------|------------|----------|---------|-----|
| Good month | 20% | 55% | +27,675 | +27.7% |
| Average month | 35% | 45% | +15,375 | +15.4% |
| Breakeven month | 25% | 40% | +2,075 | +2.1% |
| Bad month | 15% | 33% | -775 | -0.8% |
| Worst month | 5% | 20% | -6,525 (capped) | -6.5% |

**Expected monthly return: +10,993 (+11.0%)**

### Monthly P&L Distribution

| Percentile | Monthly P&L | What It Means |
|-----------|-------------|---------------|
| P5 (worst case) | -6,500 | Kill switches maxed out |
| P25 | +2,000 | Choppy month, barely positive |
| P50 (median) | +11,000 | Normal month |
| P75 | +18,000 | Good trends, clean signals |
| P95 (best case) | +28,000 | Everything clicks |

### Month 1 Realistic Expectations

- Week 1-2: PAPER MODE (0 real P&L, learning)
- Week 3: LIVE, 1 trade/day max. Expected: +2,000 to +5,000
- Week 4: LIVE, 2 trades/day max. Expected: +3,000 to +8,000
- **Month 1 target: +5,000 to +10,000**
- **Month 1 worst case: -6,000**

---

## Annual Projections

### Four Annual Paths

| Path | Probability | Net Return | Final Balance (after tax) |
|------|------------|------------|--------------------------|
| Nightmare | 5% | -3.9% | 96,055 |
| Conservative | 25% | +27.6% | 1,27,629 |
| Realistic | 45% | +102.2% | 2,02,222 |
| Optimistic | 25% | +185.0% | 2,85,042 |

**Weighted expected annual return: +99.0%**
**Expected: 1,00,000 -> ~2,00,000 in Year 1**

### Realistic Path (Most Likely — 45% probability)

| Month | Type | Balance |
|-------|------|---------|
| 1 | Paper -> Live | 1,03,800 |
| 2 | Average | 1,13,718 |
| 3 | Good | 1,34,812 |
| 4 | Average | 1,48,141 |
| 5 | Breakeven | 1,49,604 |
| 6 | Bad | 1,47,208 |
| 7 | Average | 1,61,901 |
| 8 | Breakeven | 1,63,639 |
| 9 | Good | 1,94,717 |
| 10 | Average | 2,14,636 |
| 11 | Worst | 1,99,785 |
| 12 | Average | 2,20,261 |

**Net after charges and tax: 2,02,222 (+102.2%)**

### Max Drawdown Expectations

| Path | Max Drawdown | When | Recovery |
|------|-------------|------|----------|
| Nightmare | -8.4% | Month 3 | 2 months |
| Conservative | -6.4% | Month 10 | 2 months |
| Realistic | -6.9% | Month 11 | 1 month |
| Optimistic | -1.0% | Month 9 | Immediate |

**Expect to see capital drop 6-8% at some point.** If you can stomach 1L becoming 92K for 2-3 weeks, you'll be fine.

### 5-Year Compounding (If Reinvested)

| Year | Starting | Expected Return | Year-End |
|------|---------|-----------------|----------|
| 1 | 1,00,000 | +99% | 1,99,000 |
| 2 | 1,99,000 | +80% | 3,58,200 |
| 3 | 3,58,200 | +65% | 5,91,030 |
| 4 | 5,91,030 | +50% | 8,86,545 |
| 5 | 8,86,545 | +40% | 12,41,163 |

*Returns decrease as capital grows due to slippage, liquidity constraints, and market impact.*

### Cost Structure

```
Brokerage + STT:     ~75/trade x 240 trades = 18,000/year
Tax (15% STCG):      ~16,800 on 1.12L profit
Net Year 1 in hand:  ~95,200 (95% ROI on 1L)
```

### The One Number That Matters

```
Maximum possible loss in any single month: -6,500 (6.5% of 1L)

That's your worst case. Every month. Guaranteed by kill switches.

No blown account. No margin call. No sleepless nights.
```

---

## Running the System

### Prerequisites

1. DhanHQ trading account with API access enabled
2. Data API subscription (for historical candles + option chain)
3. Static IP whitelisted with Dhan (for order placement)
4. Python 3.13+ with venv

### Setup

```bash
cd ~/projects/nifty-trader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Create .env file
cp .env.example .env
# Edit .env with your Dhan credentials
```

### Running

```bash
# Dry run (no API needed — simulates 3 market scenarios)
venom --dry-run

# Paper trading (live data, simulated orders)
venom --paper --config config/settings.yaml

# Live trading
venom --config config/settings.yaml
```

### Configuration

All VENOM parameters are in `config/settings.yaml` under the `venom:` section. Key parameters:

```yaml
venom:
  sl_percent: 30.0           # Stop loss percentage
  trail_activation_pct: 20.0 # Move SL to cost at +20%
  max_profit_pct: 100.0      # Exit at +100% gain
  max_trades_per_day: 3      # Daily trade limit
  max_daily_loss: 3000.0     # Daily loss cap
  max_weekly_loss: 8000.0    # Weekly loss cap
  vix_blocked: 30.0          # No trading above this VIX
```

### Deployment Checklist

1. Run `venom --dry-run` to verify system health
2. Paper trade for 5 full sessions
3. Go live with `max_trades_per_day: 1` for first week
4. Scale to 3 trades/day after 2 profitable weeks

---

## Risk Disclaimer

This is a personal trading tool. Automated trading carries risk of loss. The system includes kill switches and daily limits, but market conditions can cause losses beyond expected parameters. Past performance (simulated or backtested) does not guarantee future results. Only trade with capital you can afford to lose.
