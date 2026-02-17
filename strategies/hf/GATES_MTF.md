# GATES_MTF.md — Multi-Timeframe Gate Parameters

Addendum to GATES.md for 1H and 15m validation runs.

## Timeframe-Scaled Parameters

| Parameter | 4H | 1H | 15m | Scaling Rule |
|-----------|----|----|-----|-------------|
| ROLLING_WINDOW_BARS | 180 | 720 | 2880 | 30 days × bars_per_day |
| WF_EMBARGO | 2 | 2 | 8 | ~2h wall-clock |
| start_bar | 50 | 50 | 200 | indicator warmup |
| MIN_TRADES | 20 | 20 | 20 | absolute minimum |
| fold_size | auto | auto | auto | (n_bars - start_bar) / 5 |
| bars_per_day | 6 | 24 | 96 | 24h / interval_hours |

## Gate Definitions (Unchanged)

All 5 hard gates + 1 informational gate apply identically across timeframes.
Only the bar-count parameters scale; thresholds remain the same.

| Gate | Name | Threshold | Type |
|------|------|-----------|------|
| G1 | Minimum Trades | ≥ 20 | Hard |
| G2 | Walk-Forward Profitability | ≥ 3/5 folds profitable | Hard |
| G3 | Maximum Drawdown | < 50% | Hard |
| G4 | Outlier Dependency | top trade < 80% of total P&L | Hard |
| G5 | Friction Stress Survival | P&L > 0 at 2× per-tier fees | Hard |
| G6 | Coin Concentration | max coin < 80% of total P&L | Informational |

## A/B Config Specification

To prevent false-negative conclusions from parameter mismatch at lower timeframes:

### Config A: "As-Is"
Use GRID_BEST / CHAMPION_H2 unchanged.
- `time_max_bars = 15` → 15 hours at 1H, 3.75 hours at 15m

### Config B: "Wall-Clock Scaled"
Scale time-dependent parameters to preserve wall-clock semantics from 4H.

| Parameter | 4H Value | 1H Scaled | 15m Scaled | Rule |
|-----------|----------|-----------|------------|------|
| time_max_bars | 15 | 60 | 240 | × bars_per_4h_bar |
| COOLDOWN_BARS | 4 (constant) | 4 (constant) | 4 (constant) | Engine constant, cannot scale |
| COOLDOWN_AFTER_STOP | 8 (constant) | 8 (constant) | 8 (constant) | Engine constant, cannot scale |

### Interpretation Matrix

| Config A | Config B | Conclusion |
|----------|----------|------------|
| PASS | PASS | Strong edge — works with any params |
| PASS | FAIL | Edge exists but sensitive to hold time |
| FAIL | PASS | Edge exists only with TF-scaled params; grid-search needed |
| FAIL | FAIL | No edge at this timeframe for DualConfirm |

## Walk-Forward Details

### Fold Structure
```
n_bars = len(data[coin])  # e.g., 2880 for 1H
usable = n_bars - start_bar  # e.g., 2830
fold_size = usable // 5       # e.g., 566

Fold 0: [start_bar, start_bar + fold_size)
Fold 1: [start_bar + fold_size + embargo, start_bar + 2*fold_size)
...
Fold 4: [start_bar + 4*fold_size + 4*embargo, n_bars)
```

### Embargo Purpose
Prevents data leakage between adjacent folds. Set to ~2h wall-clock
to match the minimum cooldown window. At 15m, this is 8 bars (2h);
at 1H and 4H, 2 bars suffice.

## Per-Tier Fee Model (Unchanged)

| Tier | Fee Per Side | Round Trip |
|------|-------------|------------|
| T1 (Liquid) | 31 bps | 62 bps |
| T2 (Mid) | 56 bps | 112 bps |
| T3 (Illiquid) | excluded | excluded |

T3 excluded per UNIVERSE_POLICY.md.

## Friction Stress (Gate 5)

2× stress = double the slippage component only:
- T1: 36 bps/side (72 bps RT)
- T2: 86 bps/side (172 bps RT)

---
*Sprint 3 — 4H variant research*
