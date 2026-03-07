"""Backtest harness — replay historical 5-min candles through the strategy engine."""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from nifty_trader.config import load_config
from nifty_trader.constants import Direction
from nifty_trader.data.indicators import ema, rsi, vwap
from nifty_trader.strategy.confluence import evaluate_confluence
from nifty_trader.strategy.levels import LevelDetector

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    entry_idx: int
    entry_price: float
    direction: Direction
    sl_price: float
    target_price: float
    exit_idx: int = -1
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0


def run_backtest(csv_path: str, config_path: str | None = None) -> BacktestResult:
    """Run backtest on historical 5-min CSV data.

    CSV must have columns: timestamp, open, high, low, close, volume
    """
    cfg = load_config(yaml_path=config_path)
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)

    if len(df) < 50:
        print("Insufficient data for backtest (need 50+ candles)")
        return BacktestResult()

    # Build level detector from daily aggregation
    daily = df.resample("D", on="timestamp").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()
    level_detector = LevelDetector(daily.reset_index())

    trades: list[BacktestTrade] = []
    in_trade = False
    current_trade: BacktestTrade | None = None
    window = 50  # Minimum lookback for indicators

    for i in range(window, len(df)):
        slice_df = df.iloc[i - window : i + 1].reset_index(drop=True)

        if in_trade and current_trade:
            # Check exit conditions
            price = float(df.iloc[i]["close"])
            high = float(df.iloc[i]["high"])
            low = float(df.iloc[i]["low"])

            # Check SL/target on candle extremes
            hit_sl = low <= current_trade.sl_price
            hit_target = high >= current_trade.target_price

            if hit_sl:
                current_trade.exit_idx = i
                current_trade.exit_price = current_trade.sl_price
                current_trade.exit_reason = "SL hit"
                current_trade.pnl = current_trade.exit_price - current_trade.entry_price
                trades.append(current_trade)
                in_trade = False
                current_trade = None
            elif hit_target:
                current_trade.exit_idx = i
                current_trade.exit_price = current_trade.target_price
                current_trade.exit_reason = "Target hit"
                current_trade.pnl = current_trade.exit_price - current_trade.entry_price
                trades.append(current_trade)
                in_trade = False
                current_trade = None
            continue

        # Evaluate signals
        result = evaluate_confluence(slice_df, level_detector, cfg.strategy)
        if not result.triggered:
            continue

        entry_price = float(df.iloc[i]["close"])
        sl_pct = cfg.risk.sl_pct / 100
        sl_amount = entry_price * sl_pct
        sl_price = entry_price - sl_amount
        target_price = entry_price + sl_amount * cfg.risk.reward_risk_ratio

        current_trade = BacktestTrade(
            entry_idx=i,
            entry_price=entry_price,
            direction=result.direction,
            sl_price=sl_price,
            target_price=target_price,
        )
        in_trade = True

    # Close any open trade at end
    if current_trade and in_trade:
        current_trade.exit_idx = len(df) - 1
        current_trade.exit_price = float(df.iloc[-1]["close"])
        current_trade.exit_reason = "End of data"
        current_trade.pnl = current_trade.exit_price - current_trade.entry_price
        trades.append(current_trade)

    # Compute results
    total_pnl = sum(t.pnl for t in trades)
    winners = sum(1 for t in trades if t.pnl > 0)
    win_rate = (winners / len(trades) * 100) if trades else 0.0

    # Max drawdown
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)

    result = BacktestResult(
        trades=trades,
        total_pnl=total_pnl,
        win_rate=win_rate,
        max_drawdown=max_dd,
        num_trades=len(trades),
    )

    # Print summary
    print(f"\n{'='*50}")
    print(f"BACKTEST RESULTS")
    print(f"{'='*50}")
    print(f"Data points: {len(df)}")
    print(f"Trades:      {result.num_trades}")
    print(f"Win rate:    {result.win_rate:.1f}%")
    print(f"Total P&L:   {result.total_pnl:+.2f}")
    print(f"Max DD:      {result.max_drawdown:.2f}")
    print(f"{'='*50}")

    for i, t in enumerate(trades, 1):
        marker = "W" if t.pnl > 0 else "L"
        print(
            f"  [{marker}] Trade {i}: {t.direction.value} entry={t.entry_price:.2f} "
            f"exit={t.exit_price:.2f} pnl={t.pnl:+.2f} ({t.exit_reason})"
        )

    return result


def main():
    parser = argparse.ArgumentParser(description="Backtest NIFTY strategy")
    parser.add_argument("csv_file", help="Path to 5-min OHLCV CSV file")
    parser.add_argument("--config", help="Path to settings.yaml", default=None)
    args = parser.parse_args()
    run_backtest(args.csv_file, args.config)


if __name__ == "__main__":
    main()
