# Backtest Engine — Fix & Improve

**Date:** 2026-03-09
**Goal:** Apply F&O audit fixes to the backtester and add decision event logging

## Issues Found

### Bugs (from live engine audit, not yet applied to backtester)

1. **Lot size hardcoded to 25** — should be 75 (current NIFTY contract spec)
2. **Position sizing never reduces** — `max(size, lot_size)` clamps at full lot regardless of VIX
3. **Confluence uses wrong comparison** — compares raw score to confirmation count, not weighted score
4. **No theta decay in candle walk** — premium_at_index_price ignores time decay
5. **Time stop never fires** — isinstance check fails on pandas Timestamp

### Enhancements

6. **Round level refresh** — LevelDetector not refreshed from day's open
7. **Decision events** — No event trail captured (live engine now has this)
8. **Day classification** — Simplistic classifier doesn't match publisher logic

## Files to Modify

- `src/nifty_trader/backtest/engine.py` — all 8 fixes

## Approach

Fix bugs and add events in-place. No new files needed. Keep Rich terminal output as primary.

## Verification

Run `venom --backtest --days 30` and compare terminal report before/after.
