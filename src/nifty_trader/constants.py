"""DhanHQ constants and NIFTY instrument metadata."""

from enum import Enum

# NIFTY 50 Index
NIFTY_SECURITY_ID = "13"
NIFTY_EXCHANGE_SEGMENT = "IDX_I"
NIFTY_LOT_SIZE = 25

# DhanHQ exchange segments
class ExchangeSegment(str, Enum):
    NSE_EQ = "NSE_EQ"
    NSE_FNO = "NSE_FNO"
    IDX_I = "IDX_I"
    MCX_COMM = "MCX_COMM"

class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_MARKET = "SL-M"

class ProductType(str, Enum):
    INTRADAY = "INTRADAY"
    CNC = "CNC"
    MARGIN = "MARGIN"

class Validity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"

class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"

class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class StrategyMode(str, Enum):
    DIRECTIONAL = "directional"
    CREDIT_SPREAD = "credit_spread"
    BOTH = "both"


class TradeState(str, Enum):
    IDLE = "IDLE"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    ORDER_PLACED = "ORDER_PLACED"
    POSITION_OPEN = "POSITION_OPEN"
    TRAILING = "TRAILING"
    EXITING = "EXITING"
    CLOSED = "CLOSED"
    ERROR = "ERROR"
    DAILY_STOPPED = "DAILY_STOPPED"

# DhanHQ API rate limits
RATE_LIMIT_ORDERS_PER_SEC = 10
RATE_LIMIT_DATA_PER_SEC = 5
RATE_LIMIT_OPTION_CHAIN_SEC = 3

# Trading hours
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
