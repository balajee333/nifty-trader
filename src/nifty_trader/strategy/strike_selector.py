"""Greeks-filtered strike picker — delta 0.3-0.5, liquidity, spread checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from nifty_trader.config import SpreadConfig, StrikeConfig
from nifty_trader.constants import Direction, OptionType
from nifty_trader.data.option_chain import OptionContract

logger = logging.getLogger(__name__)


@dataclass
class StrikeSelection:
    contract: OptionContract
    reason: str


@dataclass
class SpreadSelection:
    short_leg: OptionContract
    long_leg: OptionContract
    net_credit: float
    spread_width: float
    max_loss: float
    reason: str


def select_strike(
    contracts: list[OptionContract],
    direction: Direction,
    cfg: StrikeConfig,
) -> StrikeSelection | None:
    """Select the best option strike for the given direction.

    Returns None if no suitable strike passes all filters.
    """
    target_type = OptionType.CALL if direction == Direction.BULLISH else OptionType.PUT

    candidates = [c for c in contracts if c.option_type == target_type]
    if not candidates:
        logger.info("No %s contracts available", target_type.value)
        return None

    # Filter by delta range
    candidates = [
        c for c in candidates
        if cfg.delta_min <= abs(c.delta) <= cfg.delta_max
    ]
    if not candidates:
        logger.info("No contracts with delta in [%.2f, %.2f]", cfg.delta_min, cfg.delta_max)
        return None

    # Filter by IV rank
    candidates = [c for c in candidates if c.iv <= cfg.iv_rank_max]
    if not candidates:
        logger.info("No contracts with IV <= %.1f%%", cfg.iv_rank_max)
        return None

    # Filter by volume
    candidates = [c for c in candidates if c.volume >= cfg.min_volume]
    if not candidates:
        logger.info("No contracts with volume >= %d", cfg.min_volume)
        return None

    # Filter by OI
    candidates = [c for c in candidates if c.oi >= cfg.min_oi]
    if not candidates:
        logger.info("No contracts with OI >= %d", cfg.min_oi)
        return None

    # Filter by bid-ask spread
    candidates = [c for c in candidates if c.spread <= cfg.max_spread_pct]
    if not candidates:
        logger.info("No contracts with spread <= %.1f%%", cfg.max_spread_pct)
        return None

    # Sort by closeness to target delta, then by tightest spread
    candidates.sort(key=lambda c: (abs(abs(c.delta) - cfg.delta_target), c.spread))

    best = candidates[0]
    logger.info(
        "Selected %s %s @ %.0f | delta=%.2f iv=%.1f vol=%d oi=%d spread=%.2f%%",
        best.option_type.value,
        best.expiry,
        best.strike_price,
        best.delta,
        best.iv,
        best.volume,
        best.oi,
        best.spread,
    )
    return StrikeSelection(
        contract=best,
        reason=(
            f"Delta {best.delta:.2f} (target {cfg.delta_target}), "
            f"spread {best.spread:.2f}%, vol {best.volume}, OI {best.oi}"
        ),
    )


def select_spread(
    contracts: list[OptionContract],
    direction: Direction,
    cfg: SpreadConfig,
) -> SpreadSelection | None:
    """Select a credit spread for the given direction.

    BULLISH → Bull Put Spread (sell higher PUT, buy lower PUT)
    BEARISH → Bear Call Spread (sell lower CALL, buy higher CALL)

    Returns None if no suitable spread passes all filters.
    """
    target_type = OptionType.PUT if direction == Direction.BULLISH else OptionType.CALL
    typed = [c for c in contracts if c.option_type == target_type]
    if not typed:
        logger.info("No %s contracts for spread", target_type.value)
        return None

    # Filter short leg candidates: delta, volume, OI, bid-ask spread, IV rank
    short_candidates = [
        c for c in typed
        if cfg.short_delta_min <= abs(c.delta) <= cfg.short_delta_max
        and c.volume >= cfg.min_volume
        and c.oi >= cfg.min_oi
        and c.spread <= cfg.max_spread_pct
        and c.iv >= cfg.iv_rank_min
    ]
    if not short_candidates:
        logger.info("No short leg candidates pass filters")
        return None

    # Sort by closeness to target delta
    short_candidates.sort(key=lambda c: (abs(abs(c.delta) - cfg.short_delta_target), c.spread))

    for short in short_candidates:
        # Find long leg: same type, spread_width_points further OTM
        if target_type == OptionType.PUT:
            # Bull put: long leg has lower strike
            long_strike = short.strike_price - cfg.spread_width_points
        else:
            # Bear call: long leg has higher strike
            long_strike = short.strike_price + cfg.spread_width_points

        long_candidates = [
            c for c in typed
            if abs(c.strike_price - long_strike) < 1  # exact match
            and c.volume >= cfg.min_volume // 2  # relaxed for protection leg
            and c.oi >= cfg.min_oi // 2
        ]
        if not long_candidates:
            continue

        long = long_candidates[0]
        net_credit = short.mid_price - long.mid_price
        if net_credit < cfg.min_credit:
            logger.info(
                "Spread %s/%s credit %.2f < min %.2f",
                short.strike_price, long.strike_price, net_credit, cfg.min_credit,
            )
            continue

        spread_width = abs(short.strike_price - long.strike_price)
        max_loss = spread_width - net_credit

        logger.info(
            "Selected spread: SELL %s %.0f / BUY %s %.0f | credit=%.2f width=%.0f maxloss=%.2f",
            target_type.value, short.strike_price,
            target_type.value, long.strike_price,
            net_credit, spread_width, max_loss,
        )
        return SpreadSelection(
            short_leg=short,
            long_leg=long,
            net_credit=net_credit,
            spread_width=spread_width,
            max_loss=max_loss,
            reason=(
                f"SELL {short.strike_price:.0f}{target_type.value[0]} "
                f"/ BUY {long.strike_price:.0f}{target_type.value[0]} | "
                f"Credit {net_credit:.2f}, MaxLoss {max_loss:.2f}"
            ),
        )

    logger.info("No viable spread found after evaluating all short candidates")
    return None
