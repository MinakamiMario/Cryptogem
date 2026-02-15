# Part 2 Robustness Sweep - Full 316-coin Universe

**Date**: 2026-02-16 00:09
**Commit**: e96951c
**Universe**: T1(100) + T2(216) = 316 coins
**Previous run**: T1(43) + T2(92) = 135 coins (h20_robustness_002)
**Timeframe**: 1H
**Cost Regime**: MEXC Market (costs_mexc_v2)
**Fees**: T1=12.5bps, T2=23.5bps
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 33.2s
**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)

## G7 Gate: Neighbor Stability

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Profitable neighbors (PF>1.0) | 9/12 | >=8/12 | **PASS** |
| Stress profitable (2x fees PF>1.0) | 5/12 | info | - |
| Stress positive exp/wk | 5/12 | info | - |
| WF >= 3/5 folds | 11/12 | info | - |

## All Variants (MEXC Market)

| # | Label | dev | tp | sl | tl | Trades | T1 | T2 | PF | WR%% | Exp/Wk | DD%% | Fee%% | WF | Score |
|---|-------|-----|----|----|----|----|----|----|-----|------|--------|------|------|-----|-------|
| 0 | v5 baseline | 2.0 | 8 | 5 | 10 | 72 | 21 | 51 | 1.138 | 47.2 | $86.07 | 53.1 | 17.4 | 3/5 | 51.6441 |
| 1 | dev_thresh -0.2 | 1.8 | 8 | 5 | 10 | 82 | 29 | 53 | 1.196 | 47.6 | $134.82 | 48.9 | 16.9 | 3/5 | 80.8936 |
| 2 | dev_thresh +0.2 | 2.2 | 8 | 5 | 10 | 65 | 18 | 47 | 0.994 | 46.1 | $-2.90 | 54.4 | 19.2 | 3/5 | 0.0000 |
| 3 | dev_thresh +0.5 | 2.5 | 8 | 5 | 10 | 55 | 11 | 44 | 0.855 | 41.8 | $-70.97 | 50.0 | 22.2 | 2/5 | 0.0000 |
| 4 | tp_pct -2 | 2.0 | 6 | 5 | 10 | 72 | 21 | 51 | 0.919 | 47.2 | $-46.18 | 57.2 | 21.0 | 3/5 | 0.0000 |
| 5 | tp_pct +2 | 2.0 | 10 | 5 | 10 | 72 | 21 | 51 | 1.085 | 44.4 | $54.21 | 52.4 | 17.3 | 3/5 | 32.5277 |
| 6 | tp_pct +4 | 2.0 | 12 | 5 | 10 | 72 | 21 | 51 | 1.162 | 43.1 | $106.56 | 56.9 | 15.8 | 3/5 | 63.9354 |
| 7 | sl_pct -2 | 2.0 | 8 | 3 | 10 | 75 | 22 | 53 | 1.333 | 42.7 | $163.23 | 44.5 | 19.3 | 3/5 | 97.9388 |
| 8 | sl_pct +2 | 2.0 | 8 | 7 | 10 | 70 | 19 | 51 | 1.285 | 51.4 | $193.05 | 53.6 | 15.7 | 3/5 | 115.8274 |
| 9 | time_limit -2 | 2.0 | 8 | 5 | 8 | 76 | 21 | 55 | 1.280 | 52.6 | $173.01 | 51.4 | 17.3 | 3/5 | 103.8071 |
| 10 | time_limit +2 | 2.0 | 8 | 5 | 12 | 69 | 21 | 48 | 1.264 | 49.3 | $163.60 | 46.8 | 16.2 | 3/5 | 98.1608 |
| 11 | time_limit +5 | 2.0 | 8 | 5 | 15 | 62 | 21 | 41 | 1.344 | 51.6 | $164.56 | 48.5 | 15.9 | 3/5 | 98.7378 |

## Stress Test (2x Fees)

| # | Label | PF | Exp/Wk | P&L | Trades | WR%% | DD%% |
|---|-------|----|--------|------|--------|------|------|
| 0 | v5 baseline | 0.949 | $-32.74 | $-141 | 72 | 43.1 | 62.2 |
| 1 | dev_thresh -0.2 | 0.992 | $-5.67 | $-24 | 82 | 41.5 | 59.0 |
| 2 | dev_thresh +0.2 | 0.822 | $-97.24 | $-418 | 65 | 40.0 | 62.9 |
| 3 | dev_thresh +0.5 | 0.710 | $-147.50 | $-634 | 55 | 38.2 | 56.5 |
| 4 | tp_pct -2 | 0.753 | $-145.96 | $-627 | 72 | 43.1 | 66.2 |
| 5 | tp_pct +2 | 0.902 | $-64.56 | $-277 | 72 | 40.3 | 61.5 |
| 6 | tp_pct +4 | 0.978 | $-14.67 | $-63 | 72 | 38.9 | 65.0 |
| 7 | sl_pct -2 | 1.063 | $32.90 | $141 | 75 | 38.7 | 53.9 |
| 8 | sl_pct +2 | 1.079 | $54.58 | $235 | 70 | 48.6 | 61.7 |
| 9 | time_limit -2 | 1.044 | $27.88 | $120 | 76 | 40.8 | 61.3 |
| 10 | time_limit +2 | 1.047 | $30.10 | $129 | 69 | 43.5 | 56.4 |
| 11 | time_limit +5 | 1.087 | $43.91 | $189 | 62 | 46.8 | 57.0 |

## Walk-Forward Detail (5-Fold)

| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |
|---|-------|--------|--------|--------|--------|--------|----------|
| 0 | v5 baseline | $416 | $-199 | $-499 | $227 | $608 | 3/5 |
| 1 | dev_thresh -0.2 | $657 | $-395 | $-348 | $489 | $550 | 3/5 |
| 2 | dev_thresh +0.2 | $105 | $-274 | $-499 | $156 | $608 | 3/5 |
| 3 | dev_thresh +0.5 | $418 | $-211 | $-518 | $-202 | $308 | 2/5 |
| 4 | tp_pct -2 | $214 | $-166 | $-558 | $34 | $427 | 3/5 |
| 5 | tp_pct +2 | $360 | $-246 | $-439 | $125 | $652 | 3/5 |
| 6 | tp_pct +4 | $521 | $-210 | $-640 | $283 | $785 | 3/5 |
| 7 | sl_pct -2 | $279 | $-146 | $-447 | $453 | $691 | 3/5 |
| 8 | sl_pct +2 | $647 | $-263 | $-601 | $856 | $526 | 3/5 |
| 9 | time_limit -2 | $505 | $-235 | $-446 | $290 | $822 | 3/5 |
| 10 | time_limit +2 | $439 | $-152 | $-405 | $319 | $681 | 3/5 |
| 11 | time_limit +5 | $139 | $-41 | $-523 | $408 | $852 | 3/5 |

## Ranking (Composite Score)

```
score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)
```

### #1: sl_pct +2 (variant 8)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=7, time_limit=10
- **Composite Score**: 115.8274
- **Baseline**: 70 trades, PF=1.285, WR=51.4%, Exp/Wk=$193.05, DD=53.6%
- **Walk-Forward**: 3/5 positive folds
- **Stress 2x**: PF=1.079, Exp/Wk=$54.58

### #2: time_limit -2 (variant 9)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=8
- **Composite Score**: 103.8071
- **Baseline**: 76 trades, PF=1.280, WR=52.6%, Exp/Wk=$173.01, DD=51.4%
- **Walk-Forward**: 3/5 positive folds
- **Stress 2x**: PF=1.044, Exp/Wk=$27.88

### #3: time_limit +5 (variant 11)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=15
- **Composite Score**: 98.7378
- **Baseline**: 62 trades, PF=1.344, WR=51.6%, Exp/Wk=$164.56, DD=48.5%
- **Walk-Forward**: 3/5 positive folds
- **Stress 2x**: PF=1.087, Exp/Wk=$43.91

### Full Ranking

| Rank | # | Label | Score | Exp/Wk | WF | Trades |
|------|---|-------|-------|--------|----|--------|
| 1 | 8 | sl_pct +2 | 115.8274 | $193.05 | 3/5 | 70 |
| 2 | 9 | time_limit -2 | 103.8071 | $173.01 | 3/5 | 76 |
| 3 | 11 | time_limit +5 | 98.7378 | $164.56 | 3/5 | 62 |
| 4 | 10 | time_limit +2 | 98.1608 | $163.60 | 3/5 | 69 |
| 5 | 7 | sl_pct -2 | 97.9388 | $163.23 | 3/5 | 75 |
| 6 | 1 | dev_thresh -0.2 | 80.8936 | $134.82 | 3/5 | 82 |
| 7 | 6 | tp_pct +4 | 63.9354 | $106.56 | 3/5 | 72 |
| 8 | 0 | v5 baseline | 51.6441 | $86.07 | 3/5 | 72 |
| 9 | 5 | tp_pct +2 | 32.5277 | $54.21 | 3/5 | 72 |
| 10 | 2 | dev_thresh +0.2 | 0.0000 | $-2.90 | 3/5 | 65 |
| 11 | 3 | dev_thresh +0.5 | 0.0000 | $-70.97 | 2/5 | 55 |
| 12 | 4 | tp_pct -2 | 0.0000 | $-46.18 | 3/5 | 72 |

## Parameter Sensitivity Summary

Comparing each perturbation to v5 baseline (variant 0):

| Param | Change | Trades | Exp/Wk | Score | Delta Score |
|-------|--------|--------|--------|-------|-------------|
| v5 baseline | vs baseline | 72 | $86.07 | 51.6441 | +0.0000 |
| dev_thresh -0.2 | vs baseline | 82 | $134.82 | 80.8936 | +29.2495 |
| dev_thresh +0.2 | vs baseline | 65 | $-2.90 | 0.0000 | -51.6441 |
| dev_thresh +0.5 | vs baseline | 55 | $-70.97 | 0.0000 | -51.6441 |
| tp_pct -2 | vs baseline | 72 | $-46.18 | 0.0000 | -51.6441 |
| tp_pct +2 | vs baseline | 72 | $54.21 | 32.5277 | -19.1164 |
| tp_pct +4 | vs baseline | 72 | $106.56 | 63.9354 | +12.2913 |
| sl_pct -2 | vs baseline | 75 | $163.23 | 97.9388 | +46.2947 |
| sl_pct +2 | vs baseline | 70 | $193.05 | 115.8274 | +64.1833 |
| time_limit -2 | vs baseline | 76 | $173.01 | 103.8071 | +52.1630 |
| time_limit +2 | vs baseline | 69 | $163.60 | 98.1608 | +46.5167 |
| time_limit +5 | vs baseline | 62 | $164.56 | 98.7378 | +47.0937 |

## Comparison: 316 vs 135 coins

This run uses the full T1(100)+T2(216) universe vs the previous
partial T1(43)+T2(92) download. Key differences to watch:
- More T2 coins means higher fee drag (T2=23.5bps vs T1=12.5bps)
- More coins = more trade opportunities but also more noise
- G7 threshold unchanged: >= 8/12 profitable neighbors

---
*Generated by strategies/hf/screening/run_part2_robustness_316.py at 2026-02-16 00:09*