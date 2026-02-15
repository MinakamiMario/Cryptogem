# Multi-Timeframe Alignment Rules

## Scope
Rules governing how indicators, signals, and backtests operate across
different candle timeframes (4H, 1H, 15m) using the timeframe-agnostic
`agent_team_v3.py` engine.

## Core Principle
**The engine is bar-count based, not time-based.** All indicators (RSI-14,
BB-20, DC-20, ATR-14, vol_avg-20) use period counts, not wall-clock windows.
This means the same config at different timeframes produces different
wall-clock behavior.

## Close-Bar Rules

### Rule 1: No Partial Bar Features
Indicators must only use fully closed bars. The engine's `precompute_all()`
already enforces this by computing indicators from `closes[:bar+1]` where
`bar` is the *current* bar index (the bar is closed when used).

### Rule 2: Cross-TF Feature Mapping
When using 4H features on 1H data, you MUST map to the last **fully closed**
4H candle:
```
last_closed_4h_bar(bar_1h) = (bar_1h - 3) // 4   if bar_1h >= 3, else -1
last_closed_4h_bar_15m(bar_15m) = (bar_15m - 15) // 16  if bar_15m >= 15, else -1
```
This prevents look-ahead from partially formed higher-TF candles.

### Rule 3: No 4H Features on Sub-4H Data Without Mapping
Never use 4H indicator values (RSI, BB, etc.) directly indexed by a 1H bar
number. Always use the mapping function to get the correct 4H bar index.

## Wall-Clock Semantics

| Parameter | 4H | 1H | 15m |
|-----------|----|----|-----|
| COOLDOWN_BARS=4 | 16h | 4h | 1h |
| COOLDOWN_AFTER_STOP=8 | 32h | 8h | 2h |
| time_max_bars=15 (as-is) | 60h | 15h | 3.75h |
| time_max_bars=60 (scaled) | 240h | 60h | 15h |
| START_BAR=50 | ~8.3 days | ~2.1 days | ~12.5h |
| RSI_PERIOD=14 | 56h | 14h | 3.5h |
| BB_PERIOD=20 | 80h | 20h | 5h |
| DC_PERIOD=20 | 80h | 20h | 5h |

## A/B Config for 1H/15m Validation

To prevent false-negative conclusions from parameter mismatch:
- **Config A** ("as-is"): Use GRID_BEST/CHAMPION unchanged
- **Config B** ("wall-clock scaled"): Scale time_max_bars and cooldown
  proportionally to preserve wall-clock semantics from 4H

### 1H Scaling (×4):
- time_max_bars: 15 → 60
- Note: COOLDOWN_BARS is engine-constant (4), cannot be scaled

### 15m Scaling (×16):
- time_max_bars: 15 → 240
- Note: COOLDOWN_BARS is engine-constant (4), cannot be scaled

## Validation Protocol
1. Run alignment tests on 4H (always): `make hf-check`
2. Run alignment tests on 1H/15m (when available): `--include-mtf`
3. Run backtest with both Config A and Config B
4. Compare gate results side-by-side
5. Document findings in ADR

---
*Sprint 3 — 4H variant research*
