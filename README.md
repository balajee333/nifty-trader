# NIFTY Trader

Algorithmic options trading system for NIFTY 50 on the NSE, built on the DhanHQ API. Supports two strategies:

- **Directional** — Buy ATM/NTM calls or puts based on a 5-signal confluence engine
- **Credit Spreads** — Sell OTM Bull Put Spreads (bullish) or Bear Call Spreads (bearish), where theta works in your favor and risk is capped

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| DhanHQ account | [signup](https://dhanhq.co) |
| DhanHQ Data API subscription | Required for live/paper trading |
| OS | macOS / Linux / Windows (WSL recommended) |

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/balajee333/nifty-trader.git
cd nifty-trader
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode along with test dependencies (`pytest`, `pytest-asyncio`).

### 4. Configure credentials

Copy the example env file and fill in your DhanHQ credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
DHAN_BASE_URL=                          # leave empty for production, or set sandbox URL
TELEGRAM_BOT_TOKEN=your_bot_token       # optional
TELEGRAM_CHAT_ID=your_chat_id           # optional
PAPER_MODE=true                         # set to false for live trading
```

**Where to get DhanHQ credentials:**

1. Log in to [DhanHQ Developer Portal](https://dhanhq.co/developers)
2. Create an app to get your **Client ID**
3. Generate an **Access Token** (valid for 1 day; regenerate daily or use the token refresh flow)
4. Subscribe to the **Data API** plan (required for historical candles, option chain, WebSocket feeds)

### 5. Configure strategy

Edit `config/settings.yaml` to tune the strategy:

```yaml
# Choose strategy mode
strategy_mode: "credit_spread"   # "directional" | "credit_spread" | "both"
```

**Key sections:**

| Section | What it controls |
|---|---|
| `strategy_mode` | Which strategy to run |
| `strategy` | Signal parameters (EMA periods, RSI thresholds, confluence scoring) |
| `risk` | Capital, risk per trade %, daily loss cap, SL/target ratios, trailing stops |
| `strike` | Directional mode: delta range (0.30-0.50), liquidity filters |
| `spread` | Credit spread mode: short delta (0.15-0.30), spread width, min credit, exit thresholds |
| `timing` | Scan window, entry cutoff, force exit, reconciliation times |
| `data` | Lookback periods, rate limits |
| `notifications` | Telegram and console toggle |

## Running

### Dry run (verify setup without trading)

```bash
nifty-trader --dry-run
```

Or:

```bash
python -m nifty_trader.main --dry-run
```

This verifies API connectivity, fetches data, runs one signal evaluation cycle, and reports system status. Safe to run outside market hours.

### Paper trading

Ensure `.env` has `PAPER_MODE=true`, then:

```bash
nifty-trader
```

Paper mode generates synthetic `PAPER-*` order IDs, simulates immediate fills, and logs everything to the journal — no real orders hit the exchange.

### Live trading

```bash
# In .env, set:
# PAPER_MODE=false
nifty-trader
```

**Warning:** Live mode places real orders on your DhanHQ account. Start with paper mode to validate your configuration.

## How It Works

### Signal Engine

Every 5 minutes, the system evaluates 5 signals on NIFTY 50 intraday candles:

| Signal | What it measures | Weight |
|---|---|---|
| **EMA Crossover** | EMA(9) vs EMA(21) cross + trend confirmation | 1.0 |
| **VWAP** | Price position relative to VWAP for N candles | 0.8 |
| **RSI** | Oversold/overbought reversal zones | 0.7 |
| **Volume Spike** | Volume surge + directional candle confirmation | 0.5 |
| **S/R Levels** | Support bounce or resistance rejection | 0.5 |

Signals are combined into a weighted confluence score. A trade triggers when the score exceeds `confluence_min_score` (default: 2.0).

### Directional Mode

1. Signal triggers BULLISH → buy CALL, BEARISH → buy PUT
2. Strike selected by delta (0.30-0.50), filtered by IV rank, volume, OI, bid-ask spread
3. Position sized by risk per trade % and stop-loss amount
4. Trailing stop: breakeven at 50% of target, trail at 75% of target
5. Exit on SL hit, target hit, or time stop (45 min)

### Credit Spread Mode

1. Same signal engine determines direction
2. **Bullish** → Bull Put Spread: SELL higher-strike PUT + BUY lower-strike PUT (100 points apart)
3. **Bearish** → Bear Call Spread: SELL lower-strike CALL + BUY higher-strike CALL
4. Short leg filtered by delta (0.15-0.30), IV rank ≥ 30, liquidity checks
5. Position sized so max loss per lot fits within risk budget
6. Exit when 50% of credit captured (profit target) or spread cost reaches 2× credit (loss threshold)
7. No trailing stops — spreads use fixed profit/loss targets

### Risk Controls

- **Daily loss cap**: Stops trading if daily P&L drops below -3% of capital
- **Kill switch**: Emergency halt on position count mismatch, single loss exceeding 5%, or 3+ consecutive order rejections
- **Order validation**: Time window, duplicate prevention, fund check, spread margin check
- **Spread rollback**: If long leg order fails, short leg is immediately bought back to avoid a naked position

## Project Structure

```
nifty-trader/
├── config/
│   └── settings.yaml          # Strategy, risk, timing configuration
├── src/nifty_trader/
│   ├── main.py                # TradingEngine orchestrator + event loop
│   ├── state.py               # Trade FSM (finite state machine)
│   ├── config.py              # YAML + .env → frozen dataclasses
│   ├── constants.py           # Enums (Direction, TradeState, StrategyMode, etc.)
│   ├── strategy/
│   │   ├── signals.py         # 5 individual signal evaluators
│   │   ├── confluence.py      # Weighted signal aggregation
│   │   ├── strike_selector.py # Directional strike + credit spread selection
│   │   └── levels.py          # Pivot and round-number S/R levels
│   ├── risk/
│   │   ├── manager.py         # Position sizing, trailing stops, spread exits
│   │   ├── validator.py       # Pre-order validation checks
│   │   └── kill_switch.py     # Emergency halt on anomalies
│   ├── orders/
│   │   ├── manager.py         # DhanHQ order placement (single + spread)
│   │   ├── super_order.py     # Atomic entry + SL + target
│   │   └── tracker.py         # Order state tracking
│   ├── data/
│   │   ├── historical.py      # Daily + intraday candle fetching
│   │   ├── option_chain.py    # Option chain with greeks
│   │   ├── indicators.py      # EMA, RSI, VWAP, volume spike
│   │   └── feed.py            # WebSocket market feed
│   ├── journal/
│   │   ├── database.py        # SQLite trade journal
│   │   └── reconciler.py      # Post-market reconciliation
│   ├── dashboard/
│   │   └── console.py         # Rich terminal UI
│   └── alerts/
│       └── notifier.py        # Telegram + console notifications
├── tests/
│   ├── test_state.py          # FSM transitions
│   ├── test_risk.py           # Position sizing, trailing, daily loss
│   ├── test_spread.py         # Credit spread unit tests
│   ├── test_spread_sandbox.py # Spread integration tests (live API)
│   ├── test_signals.py        # Signal evaluators
│   ├── test_indicators.py     # Technical indicators
│   └── test_sandbox_regression.py  # Full API regression suite
├── scripts/
│   ├── backtest.py            # Backtesting harness
│   └── download_instruments.py # DhanHQ instrument master download
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Testing

### Run all tests

```bash
pytest tests/ -v
```

### Run only unit tests (no API needed)

```bash
pytest tests/test_state.py tests/test_risk.py tests/test_spread.py tests/test_signals.py tests/test_indicators.py -v
```

### Run sandbox/integration tests (requires DhanHQ credentials)

```bash
pytest tests/test_sandbox_regression.py tests/test_spread_sandbox.py -v -s
```

Tests that require live API data will skip gracefully if credentials are missing or data is unavailable.

## Configuration Reference

### `config/settings.yaml`

<details>
<summary>Full default configuration</summary>

```yaml
strategy_mode: "credit_spread"   # "directional" | "credit_spread" | "both"

strategy:
  ema_fast: 9                    # Fast EMA period
  ema_slow: 21                   # Slow EMA period
  rsi_period: 14                 # RSI lookback
  rsi_bullish_entry: 35          # RSI below this = bullish signal
  rsi_bearish_entry: 65          # RSI above this = bearish signal
  rsi_oversold: 30               # RSI oversold threshold
  rsi_overbought: 70             # RSI overbought threshold
  vwap_confirm_candles: 3        # Candles above/below VWAP to confirm
  volume_spike_multiplier: 1.5   # Volume must exceed SMA × this
  volume_sma_period: 20          # Volume SMA lookback
  level_proximity_pct: 0.3       # % distance to count as "near" S/R level
  confluence_min_score: 2.0      # Minimum weighted score to trigger
  signal_weights:                # Per-signal weights for confluence
    ema: 1.0
    vwap: 0.8
    rsi: 0.7
    volume: 0.5
    levels: 0.5

risk:
  capital: 100000                # Trading capital (INR)
  risk_per_trade_pct: 2.0        # Max risk per trade (% of capital)
  daily_loss_limit_pct: 3.0      # Stop trading if daily loss exceeds this %
  max_positions: 1               # Max concurrent positions
  sl_pct: 35.0                   # Stop-loss % (directional mode)
  reward_risk_ratio: 2.0         # Target = SL × this ratio
  trailing_breakeven_pct: 50.0   # Move SL to breakeven at this % of target
  trailing_advance_pct: 75.0     # Start trailing at this % of target
  time_stop_minutes: 45          # Exit after N minutes regardless
  max_single_loss_pct: 5.0       # Kill switch: single loss > this % of capital

strike:                          # Directional mode strike selection
  delta_min: 0.30
  delta_max: 0.50
  delta_target: 0.40
  iv_rank_max: 80.0
  min_volume: 1000
  min_oi: 10000
  max_spread_pct: 2.0            # Max bid-ask spread %

spread:                          # Credit spread mode
  short_delta_min: 0.15          # Short leg min delta
  short_delta_max: 0.30          # Short leg max delta
  short_delta_target: 0.20       # Ideal short leg delta
  spread_width_points: 100       # Distance between legs (NIFTY strike gap)
  min_credit: 5.0                # Min net credit to collect (INR per unit)
  profit_target_pct: 50.0        # Exit when this % of credit captured
  loss_threshold_multiplier: 2.0 # Exit when spread costs this × credit
  min_volume: 500                # Min volume for short leg
  min_oi: 5000                   # Min OI for short leg
  max_spread_pct: 3.0            # Max bid-ask spread %
  iv_rank_min: 30.0              # Prefer selling high IV

timing:
  scan_start: "09:20"            # Start scanning for signals (IST)
  no_entry_after: "14:30"        # No new entries after this time
  force_exit: "15:15"            # Force exit all positions
  reconcile: "15:35"             # Post-market reconciliation
  candle_interval_min: 5         # Signal evaluation interval
  tick_interval_sec: 10          # Position monitoring interval

data:
  intraday_lookback_days: 5
  daily_lookback_days: 60
  ws_heartbeat_timeout_sec: 15
  rate_limit_data_per_sec: 5
  rate_limit_option_chain_sec: 3

notifications:
  telegram_enabled: false
  console_enabled: true
```

</details>

### Environment variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `DHAN_CLIENT_ID` | Yes | DhanHQ app client ID |
| `DHAN_ACCESS_TOKEN` | Yes | DhanHQ access token (regenerate daily) |
| `DHAN_BASE_URL` | No | Override API base URL (for sandbox) |
| `PAPER_MODE` | No | `true` (default) or `false` for live |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for alerts |

## Telegram Alerts (Optional)

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Get the bot token and your chat ID
3. Add them to `.env`
4. Set `telegram_enabled: true` in `config/settings.yaml`

You'll receive alerts for trade entries, exits, kill switch triggers, and daily summaries.

## Troubleshooting

| Issue | Fix |
|---|---|
| `DH-902 Invalid_Access` | Subscribe to DhanHQ Data API plan |
| `Invalid_Authentication` | Regenerate access token (tokens expire daily) |
| No signals triggering | Lower `confluence_min_score` or check market hours |
| No spread found | Widen delta range, lower `min_credit`, or check IV (`iv_rank_min`) |
| Spread sizing returns None | Spread max loss/lot exceeds risk budget — reduce `spread_width_points` or increase `capital` |
| Kill switch triggered | Check logs for reason — position mismatch, excess loss, or consecutive rejections |
