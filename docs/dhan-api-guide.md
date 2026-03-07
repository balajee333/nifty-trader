# DhanHQ API Guide — nifty-trader

Complete reference for accessing the DhanHQ trading API used by the nifty-trader system.

---

## 1. Account & API Access Setup

### Step 1: Create a Dhan Account
1. Go to [dhan.co](https://dhan.co) and sign up for a trading account
2. Complete KYC verification (Aadhaar + PAN)
3. Fund your account (minimum for options trading varies)

### Step 2: Enable API Access
1. Log in to [dhan.co](https://dhan.co)
2. Navigate to **Profile > API & Developer** section
3. Create a new **App** — this generates your credentials:
   - **Client ID**: Your unique account identifier (format: `10000XXXXX`)
   - **Access Token**: JWT token for API authentication

### Step 3: Generate Access Token
1. Go to the [DhanHQ Developer Kit](https://api.dhan.co/v2/#)
2. Log in with your Dhan credentials
3. Generate a new access token
4. **Token validity**: Tokens are valid for one trading day and must be regenerated daily, or you can create a longer-lived token from the developer console

### Step 4: Static IP Whitelisting
**Important**: Order placement, modification, and cancellation APIs require your server's static IP to be whitelisted.
1. Go to **Profile > API & Developer > IP Whitelisting**
2. Add the public IP of the machine running nifty-trader
3. For development/paper trading, this may not be enforced

---

## 2. Environment Configuration

### `.env` File Setup

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

```env
# Required — Dhan API credentials
DHAN_CLIENT_ID=10000XXXXX
DHAN_ACCESS_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGciOi...

# Optional — Custom API base URL (for sandbox testing)
DHAN_BASE_URL=

# Optional — Telegram notifications
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Trading mode (default: true = paper trading, no real orders)
PAPER_MODE=true
```

### Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DHAN_CLIENT_ID` | Yes | Your Dhan client ID (e.g., `1000000123`) |
| `DHAN_ACCESS_TOKEN` | Yes | JWT access token from developer console |
| `DHAN_BASE_URL` | No | Override API base URL (default: `https://api.dhan.co/v2/`) |
| `PAPER_MODE` | No | `true` = simulated trades, `false` = live orders (default: `true`) |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for trade alerts |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for notifications |

---

## 3. API Authentication

### Base URL
- **Production**: `https://api.dhan.co/v2/`
- **Developer Kit / Sandbox**: `https://api.dhan.co/v2/#`

### Authentication Header
Every API request requires the JWT access token:

```
access-token: eyJ0eXAiOiJKV1QiLCJhbGciOi...
```

### Python SDK Initialization
```python
from dhanhq import dhanhq as DhanHQ

dhan = DhanHQ(
    client_id="10000XXXXX",
    access_token="eyJ0eXAiOiJKV1QiLCJhbGciOi...",
)

# Optional: override base URL for sandbox
dhan.base_url = "https://api.dhan.co/v2/"
```

**SDK Installation:**
```bash
pip install dhanhq>=2.0.0
```

---

## 4. API Rate Limits

| API Category | Rate Limit |
|-------------|-----------|
| **Order APIs** (place/modify/cancel) | 10/sec, 250/min, 1,000/hr, 7,000/day |
| **Data APIs** (historical, option chain) | 5/sec |
| **Quote APIs** (market quote) | 1/sec |
| **Non-Trading APIs** (positions, funds) | 20/sec |
| **Order Modifications** | Max 25 per order |
| **Option Chain** | 1 unique request per 3 seconds per underlying/expiry |

The nifty-trader system enforces these limits via internal rate limiters:
- `rate_limit_data_per_sec: 5` (historical data calls)
- `rate_limit_option_chain_sec: 3` (option chain cooldown)

---

## 5. Exchange Segments

| Enum Value | Code | Exchange | Description |
|-----------|------|----------|-------------|
| `IDX_I` | 0 | Index | Index values (NIFTY 50, Bank NIFTY) |
| `NSE_EQ` | 1 | NSE | Equity cash segment |
| `NSE_FNO` | 2 | NSE | Futures & Options |
| `NSE_CURRENCY` | 3 | NSE | Currency derivatives |
| `BSE_EQ` | 4 | BSE | BSE equity cash |
| `MCX_COMM` | 5 | MCX | Commodity derivatives |
| `BSE_CURRENCY` | 7 | BSE | BSE currency |
| `BSE_FNO` | 8 | BSE | BSE F&O |

### How nifty-trader Uses Segments

| Instrument | Order Segment | Spot/Data Segment | Feed Code |
|-----------|--------------|-------------------|-----------|
| NIFTY options | `NSE_FNO` | `IDX_I` | 0 |
| MCX Crude Oil Mini | `MCX_COMM` | `MCX_COMM` | 5 |
| MCX Gold Mini | `MCX_COMM` | `MCX_COMM` | 5 |

---

## 6. Instrument Types

| Type | Description | Exchange |
|------|-------------|----------|
| `INDEX` | Index (NIFTY 50, Bank NIFTY) | NSE |
| `FUTIDX` | Index Futures | NSE |
| `OPTIDX` | Index Options | NSE |
| `EQUITY` | Equity Cash | NSE/BSE |
| `FUTSTK` | Stock Futures | NSE |
| `OPTSTK` | Stock Options | NSE |
| `FUTCOM` | Commodity Futures | MCX |
| `OPTFUT` | Commodity Options (on Futures) | MCX |
| `FUTCUR` | Currency Futures | NSE/BSE |
| `OPTCUR` | Currency Options | NSE/BSE |

---

## 7. Instrument Master (Security IDs)

Every tradeable instrument has a unique `security_id`. Download the master list to find them.

### Download URLs

```bash
# Compact CSV (recommended)
curl -O https://images.dhan.co/api-data/api-scrip-master.csv

# Detailed CSV (includes margin info, bracket order eligibility)
curl -O https://images.dhan.co/api-data/api-scrip-master-detailed.csv

# Per-segment API
curl https://api.dhan.co/v2/instrument/MCX_COMM
```

### Key CSV Columns

| Column | Description | Example |
|--------|-------------|---------|
| `SEM_SMST_SECURITY_ID` | Security ID (used in all API calls) | `13` |
| `SEM_TRADING_SYMBOL` | Trading symbol | `NIFTY`, `CRUDEOILM24MAR` |
| `SEM_EXM_EXCH_ID` | Exchange | `NSE`, `MCX` |
| `SEM_SEGMENT` | Segment code | `D` (Derivatives) |
| `SEM_INSTRUMENT_NAME` | Instrument type | `FUTCOM`, `OPTFUT`, `OPTIDX` |
| `SEM_EXPIRY_DATE` | Expiry date | `2024-03-28` |
| `SEM_LOT_UNITS` | Lot size | `10`, `25`, `100` |
| `SEM_STRIKE_PRICE` | Strike price (options) | `22500` |

### Using the download script

```bash
# Download and cache instrument master
python scripts/download_instruments.py

# Find security IDs for a specific commodity
python scripts/download_instruments.py --find CRUDEOILM

# Find NIFTY contracts
python scripts/download_instruments.py --find NIFTY
```

---

## 8. Order Placement API

### Endpoint
```
POST /v2/orders
```

### Order Types

| Type | Value | Description |
|------|-------|-------------|
| Market | `MARKET` | Execute at best available price |
| Limit | `LIMIT` | Execute at specified price or better |
| Stop Loss | `STOP_LOSS` | Limit order triggered at stop price |
| Stop Loss Market | `STOP_LOSS_MARKET` | Market order triggered at stop price |

### Transaction Types
- `BUY` — Buy / Go Long
- `SELL` — Sell / Go Short or Exit

### Product Types

| Type | Description |
|------|-------------|
| `INTRADAY` | Squared off by end of day (used by nifty-trader) |
| `CNC` | Cash & Carry / Delivery |
| `MARGIN` | Margin trading |
| `MTF` | Margin Trade Financing |
| `CO` | Cover Order |
| `BO` | Bracket Order |

### Validity
- `DAY` — Valid for the trading session
- `IOC` — Immediate or Cancel

### Python SDK Examples

```python
# Market buy order (option contract)
resp = dhan.place_order(
    security_id="12345",
    exchange_segment="NSE_FNO",    # or "MCX_COMM"
    transaction_type="BUY",
    quantity=25,                    # Must be multiple of lot size
    order_type="MARKET",
    product_type="INTRADAY",
    validity="DAY",
    price=0,
)
# Response: {"status": "success", "data": {"orderId": "ORD123456"}}

# Stop Loss Market order
resp = dhan.place_order(
    security_id="12345",
    exchange_segment="NSE_FNO",
    transaction_type="SELL",
    quantity=25,
    order_type="SL-M",
    product_type="INTRADAY",
    validity="DAY",
    price=0,
    trigger_price=180.50,          # Trigger price for SL
)

# Modify SL trigger price
resp = dhan.modify_order(
    order_id="ORD123456",
    order_type="SL-M",
    trigger_price=195.00,          # New trigger
)

# Cancel a specific order
resp = dhan.cancel_order(order_id="ORD123456")

# Cancel ALL pending orders
resp = dhan.cancel_order(order_id="all")
```

---

## 9. Super Order API

Atomic order that bundles entry + stop loss + profit target in a single API call.

### Endpoint
```
POST   /super/orders              — Place
PUT    /super/orders/{order-id}   — Modify
DELETE /super/orders/{order-id}/{order-leg}  — Cancel leg
GET    /super/orders              — List all
```

### Parameters

| Parameter | Description |
|-----------|-------------|
| `securityId` | Instrument security ID |
| `exchangeSegment` | Exchange segment enum |
| `transactionType` | `BUY` or `SELL` |
| `quantity` | Order quantity |
| `orderType` | `MARKET` or `LIMIT` |
| `productType` | `INTRADAY` |
| `price` | Entry price (0 for market) |
| `stopLossPrice` | Stop loss price |
| `targetPrice` | Profit target price |
| `trailingJump` | Trailing SL jump in points (0 = no trailing) |

### Python SDK Example

```python
resp = dhan.place_super_order(
    security_id="12345",
    exchange_segment="NSE_FNO",
    transaction_type="BUY",
    quantity=25,
    order_type="MARKET",
    product_type="INTRADAY",
    validity="DAY",
    price=0,
    trigger_price=0,
    sl_value=180.00,         # Stop loss price
    target_value=220.00,     # Profit target
    trailing_jump=5.0,       # Trail SL by 5 points (optional)
)
```

### Modifying Legs
Use `legName` parameter:
- `TARGET_LEG` — Modify profit target
- `STOP_LOSS_LEG` — Modify stop loss

---

## 10. Option Chain API

### Endpoint
```
POST /v2/optionchain
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `UnderlyingScrip` | Yes | Security ID of underlying (int) |
| `UnderlyingSeg` | Yes | Exchange segment (`NSE_FNO`, `MCX_COMM`) |
| `Expiry` | No | Expiry date `YYYY-MM-DD` (omit for all) |

### Supported Exchanges
NSE, BSE, and **MCX** traded options.

### Response Fields (per strike)

| Field | Description |
|-------|-------------|
| `security_id` | Contract security ID |
| `last_price` | Last traded price |
| `top_bid_price` / `top_ask_price` | Best bid/ask |
| `oi` | Open interest |
| `volume` | Trading volume |
| `previous_oi` / `previous_volume` | Previous session values |
| `implied_volatility` | IV |
| `delta` | Option delta |
| `theta` | Time decay |
| `gamma` | Delta sensitivity |
| `vega` | IV sensitivity |

### Rate Limit
1 unique request per 3 seconds per underlying/expiry combination.

### Python SDK Example

```python
# Get available expiries
expiries = dhan.expiry_list(
    under_security_id=13,            # NIFTY
    under_exchange_segment="NSE_FNO",
)

# Get option chain for specific expiry
chain = dhan.option_chain(
    under_security_id=13,
    under_exchange_segment="NSE_FNO",
    expiry="2024-03-28",
)
# Response: {"status": "success", "data": [...]}
# Each entry has strike_price, ce (call data), pe (put data)
```

---

## 11. Historical Data API

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /charts/historical` | Daily OHLCV candles |
| `POST /charts/intraday` | Intraday minute candles |

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `securityId` | Yes | Security ID (string) |
| `exchangeSegment` | Yes | Exchange segment enum |
| `instrument` | Yes | Instrument type (`INDEX`, `FUTCOM`, etc.) |
| `fromDate` | Yes | Start date |
| `toDate` | Yes | End date |
| `interval` | Intraday only | Candle interval: `1`, `5`, `15`, `25`, `60` minutes |
| `oi` | No | Include open interest (boolean) |

### Date Formats
- **Daily**: `YYYY-MM-DD` (e.g., `"2024-01-08"`)
- **Intraday**: `YYYY-MM-DD HH:MM:SS` (e.g., `"2024-09-11 09:30:00"`)

### Data Limits
- **Daily**: Available since security inception
- **Intraday**: Last 5 years, max 90 days per request

### Response Fields
Arrays of: `open`, `high`, `low`, `close`, `volume`, `timestamp` (epoch), `open_interest`

### Python SDK Example

```python
# Daily candles — 60 days for S/R levels
resp = dhan.historical_daily_data(
    security_id="13",
    exchange_segment="IDX_I",       # Spot index segment
    instrument_type="INDEX",
    from_date="2024-01-01",
    to_date="2024-03-28",
)

# 5-minute intraday candles
resp = dhan.intraday_minute_data(
    security_id="13",
    exchange_segment="IDX_I",
    instrument_type="INDEX",
    from_date="2024-03-25",
    to_date="2024-03-28",
)
```

---

## 12. WebSocket Market Feed (DhanFeed)

### Connection URL
```
wss://api-feed.dhan.co?version=2&token=<ACCESS_TOKEN>&clientId=<CLIENT_ID>&authType=2
```

### Limits
- Max **5,000 instruments** per connection
- Max **5 connections** per user

### Feed Types

| Type | Request Code | Data Included |
|------|-------------|---------------|
| **Ticker** | 15 (subscribe), 16 (unsubscribe) | LTP, last traded time |
| **Quote** | 17 (subscribe), 18 (unsubscribe) | LTP + volume, bid/ask quantities, OI |
| **Full** | 21 (subscribe), 22 (unsubscribe) | Quote + 5-level market depth |

### Subscription Message Format

```json
{
  "RequestCode": 15,
  "InstrumentCount": 2,
  "InstrumentList": [
    {"ExchangeSegment": "IDX_I", "SecurityId": "13"},
    {"ExchangeSegment": "MCX_COMM", "SecurityId": "888"}
  ]
}
```

### Response Format
- **Request**: JSON
- **Response**: Binary (Little Endian)
- 8-byte response header + payload

### Response Codes

| Code | Packet Type |
|------|------------|
| 1 | Index data |
| 2 | Ticker |
| 4 | Quote |
| 5 | Open Interest |
| 6 | Previous Close |
| 7 | Market Status |
| 8 | Full Packet |
| 50 | Disconnect |

### Heartbeat
- Server sends ping every **10 seconds**
- Connection closes after **40 seconds** without response

### Python SDK Example

```python
from dhanhq.marketfeed import DhanFeed

# Define subscriptions: list of (exchange_code, security_id, feed_type)
instruments = [
    (0, "13", 17),       # NIFTY index, quote feed
    (5, "888", 17),      # MCX commodity, quote feed
]

feed = DhanFeed(
    client_id="10000XXXXX",
    access_token="eyJ0eXAiOiJKV1Q...",
    instruments=instruments,
)

feed.run_forever()       # Starts in background thread

# Poll for latest data
data = feed.data         # Dict keyed by security_id

# Get LTP for a security
ltp = data.get("13", {}).get("ltp")

# Cleanup
feed.close_connection()
```

---

## 13. Position & Account APIs

### Fund Limits
```python
resp = dhan.get_fund_limits()
# Returns available margin, used margin, etc.
# Used by nifty-trader for API connectivity check at startup
```

### Open Positions
```python
resp = dhan.get_positions()
# Returns all open positions with security_id, quantity, avg_price, pnl
# Used by kill switch for position count verification
# Used by reconciler for end-of-day cross-check
```

### Trade History
```python
resp = dhan.get_trade_history(
    from_date="2024-03-28",
    to_date="2024-03-28",
)
# Returns all executed trades for the day
# Used by reconciler for P&L verification
```

### Kill Switch
```python
dhan.kill_switch(action="activate")    # Emergency halt — cancel all orders
dhan.kill_switch(action="deactivate")  # Resume trading
```

---

## 14. Market Quote (REST Fallback)

When WebSocket feed is unavailable, LTP can be fetched via REST:

```python
resp = dhan.get_market_quote(
    security_id="12345",
    exchange_segment="NSE_FNO",
)
# Returns: last_price, bid, ask, volume, oi
# Rate limit: 1/sec
```

---

## 15. How nifty-trader Uses Each API

| System Component | API Methods Used | Purpose |
|-----------------|-----------------|---------|
| **Startup** | `get_fund_limits()` | Verify API connectivity |
| **Pre-market** | `historical_daily_data()`, `intraday_minute_data()` | Compute S/R levels, indicators |
| **Signal scan** | `intraday_minute_data()` | Refresh 5-min candles every interval |
| **Strike selection** | `expiry_list()`, `option_chain()` | Find optimal spread contracts |
| **Order entry** | `place_super_order()`, `place_order()` | Place entry + SL atomically |
| **Position monitor** | DhanFeed WebSocket, `get_market_quote()` | Real-time LTP for P&L tracking |
| **SL trailing** | `modify_order()` | Advance stop loss trigger |
| **Exit** | `place_order()` (market sell) | Close position |
| **Cancel** | `cancel_order()` | Cancel pending SL/target orders |
| **Kill switch** | `get_positions()`, `cancel_order("all")`, `kill_switch()` | Emergency halt |
| **Reconciliation** | `get_positions()`, `get_trade_history()` | Verify no ghost positions |

---

## 16. Paper Mode vs Live Mode

| Aspect | Paper Mode (`PAPER_MODE=true`) | Live Mode (`PAPER_MODE=false`) |
|--------|-------------------------------|-------------------------------|
| Orders | Simulated with IDs like `PAPER-1001` | Real API calls to DhanHQ |
| Fills | Instant at mid-price | Depends on market liquidity |
| P&L | Tracked locally in SQLite | Real money gains/losses |
| IP whitelist | Not required | **Required** for order APIs |
| WebSocket | Still connects for real-time data | Same |
| Historical data | Real API calls | Same |
| Kill switch | Simulated | Cancels real orders |

**Recommendation**: Always start with `PAPER_MODE=true` and verify the system behaves correctly before switching to live.

---

## 17. Quick Start Checklist

```bash
# 1. Install dependencies
pip install -e .

# 2. Download instrument master
python scripts/download_instruments.py

# 3. Find your instrument's security ID
python scripts/download_instruments.py --find CRUDEOILM

# 4. Update security_id in config
#    Edit config/mcx-crudeoilm.yaml → instrument.security_id

# 5. Set up credentials
cp .env.example .env
# Edit .env with your DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN

# 6. Dry run (paper mode, verifies everything works)
nifty-trader --dry-run --config config/mcx-crudeoilm.yaml

# 7. Paper trading session
PAPER_MODE=true nifty-trader --config config/mcx-crudeoilm.yaml

# 8. Live trading (when ready)
PAPER_MODE=false nifty-trader --config config/mcx-crudeoilm.yaml
```

---

## 18. Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | Invalid or expired access token | Regenerate token from developer console |
| `403 IP not whitelisted` | Server IP not registered | Add IP in Profile > API > IP Whitelisting |
| `429 Too Many Requests` | Rate limit exceeded | System handles this via built-in rate limiters |
| `No expiry available` | Market closed or no contracts | Check if MCX market hours (09:00-23:30) |
| `Empty option chain` | Security ID wrong or no liquidity | Run `download_instruments.py --find <SYMBOL>` |
| `WebSocket disconnect` | Network issue or token expired | System auto-detects via heartbeat timeout (15s) |
| `Kill switch triggered` | Position mismatch or large loss | Check logs, resolve manually, restart |

---

## References

- [DhanHQ API Docs v2](https://dhanhq.co/docs/v2/)
- [DhanHQ Developer Kit](https://api.dhan.co/v2/#)
- [dhanhq Python SDK on PyPI](https://pypi.org/project/dhanhq/)
- [Instrument Master CSV](https://images.dhan.co/api-data/api-scrip-master.csv)
- [Instrument Master Detailed CSV](https://images.dhan.co/api-data/api-scrip-master-detailed.csv)
