"""Multi-signal confluence scorer — weighted consensus for trade decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from nifty_trader.config import StrategyConfig
from nifty_trader.constants import Direction
from nifty_trader.strategy.levels import LevelDetector
from nifty_trader.strategy.signals import (
    SignalResult,
    evaluate_ema,
    evaluate_levels,
    evaluate_rsi,
    evaluate_volume,
    evaluate_vwap,
)

logger = logging.getLogger(__name__)


@dataclass
class ConfluenceResult:
    direction: Direction
    score: float
    signals: list[SignalResult] = field(default_factory=list)
    triggered: bool = False

    @property
    def summary(self) -> str:
        active = [s for s in self.signals if s.direction != Direction.NEUTRAL]
        names = ", ".join(f"{s.name}({s.direction.value})" for s in active)
        return f"{self.direction.value} score={self.score:.2f} [{names}]"


def evaluate_confluence(
    df: pd.DataFrame,
    level_detector: LevelDetector,
    cfg: StrategyConfig,
) -> ConfluenceResult:
    """Run all signal evaluators and compute weighted consensus."""
    signals = [
        evaluate_ema(df, cfg),
        evaluate_vwap(df, cfg),
        evaluate_rsi(df, cfg),
        evaluate_volume(df, cfg),
        evaluate_levels(df, level_detector, cfg),
    ]

    weights = cfg.signal_weights
    bullish_score = 0.0
    bearish_score = 0.0

    for sig in signals:
        w = weights.get(sig.name, 0.5)
        if sig.direction == Direction.BULLISH:
            bullish_score += w * sig.strength
        elif sig.direction == Direction.BEARISH:
            bearish_score += w * sig.strength

    min_score = cfg.confluence_min_score

    if bullish_score >= min_score and bullish_score > bearish_score:
        return ConfluenceResult(
            direction=Direction.BULLISH,
            score=bullish_score,
            signals=signals,
            triggered=True,
        )
    if bearish_score >= min_score and bearish_score > bullish_score:
        return ConfluenceResult(
            direction=Direction.BEARISH,
            score=bearish_score,
            signals=signals,
            triggered=True,
        )

    # No consensus
    dominant = Direction.BULLISH if bullish_score >= bearish_score else Direction.BEARISH
    return ConfluenceResult(
        direction=dominant,
        score=max(bullish_score, bearish_score),
        signals=signals,
        triggered=False,
    )
