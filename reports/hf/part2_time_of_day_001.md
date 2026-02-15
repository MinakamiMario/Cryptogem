# Part 2 -- Time-of-Day Analysis (Agent C4-A3)

**Date**: 2026-02-16 00:45
**Commit**: 16cf97f
**Universe**: T1(96) + T2(199) = 295 coins (295-coin universe)
**Params**: dev=2.0, tp=8, sl=5, tl=10
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x: T1=25.0bps, T2=47.0bps)
**Runtime**: 28.7s

## 1. Baseline Summary

- Trades: 56
- P&L: $3272.13
- PF: 2.834
- WR: 64.3%
- Exp/week: $762.44

## 2. Per-Hour Breakdown (UTC)

| Hour | Trades | Wins | WR% | Avg P&L | Total P&L | PF | Avg P&L% |
|------|--------|------|-----|---------|-----------|-----|----------|
| 00:00 | 2 | 1 | 50.0% | $+16.78 | $+33.55 | 4.29 | +0.92% |
| 01:00 | 1 | 0 | 0.0% | $-176.71 | $-176.71 | 0.00 | -5.46% |
| 02:00 | 1 | 1 | 100.0% | $+20.31 | $+20.31 | inf | +0.69% |
| 03:00 | 2 | 1 | 50.0% | $+25.29 | $+50.57 | 1.24 | +1.03% |
| 04:00 | 1 | 0 | 0.0% | $-36.12 | $-36.12 | 0.00 | -1.33% |
| 05:00 | 0 | 0 | 0.0% | $+0.00 | $+0.00 | 0.00 | +0.00% |
| 06:00 | 2 | 0 | 0.0% | $-59.40 | $-118.81 ** | 0.00 | -2.75% |
| 07:00 | 3 | 1 | 33.3% | $+53.03 | $+159.08 | 2.37 | +0.89% |
| 08:00 | 3 | 2 | 66.7% | $+184.14 | $+552.41 | 13.17 | +4.61% |
| 09:00 | 1 | 1 | 100.0% | $+96.21 | $+96.21 | inf | +2.66% |
| 10:00 | 1 | 1 | 100.0% | $+126.63 | $+126.63 | inf | +5.08% |
| 11:00 | 1 | 1 | 100.0% | $+214.20 | $+214.20 | inf | +7.51% |
| 12:00 | 2 | 1 | 50.0% | $+28.27 | $+56.54 | 1.52 | +1.13% |
| 13:00 | 6 | 5 | 83.3% | $+82.32 | $+493.93 | 5.37 | +3.01% |
| 14:00 | 2 | 1 | 50.0% | $-24.27 | $-48.54 ** | 0.49 | -0.64% |
| 15:00 | 8 | 6 | 75.0% | $+65.27 | $+522.13 | 9.14 | +2.20% |
| 16:00 | 3 | 3 | 100.0% | $+133.24 | $+399.71 | inf | +6.12% |
| 17:00 | 3 | 2 | 66.7% | $+56.87 | $+170.61 | 5.96 | +2.58% |
| 18:00 | 1 | 1 | 100.0% | $+178.99 | $+178.99 | inf | +7.74% |
| 19:00 | 3 | 1 | 33.3% | $-39.79 | $-119.36 ** | 0.60 | +0.07% |
| 20:00 | 3 | 2 | 66.7% | $+93.68 | $+281.03 | 3.02 | +3.77% |
| 21:00 | 3 | 2 | 66.7% | $+86.02 | $+258.06 | 2.52 | +3.26% |
| 22:00 | 1 | 1 | 100.0% | $+39.30 | $+39.30 | inf | +1.87% |
| 23:00 | 3 | 2 | 66.7% | $+39.47 | $+118.41 | 3.67 | +2.20% |

*Rows marked with ** have negative total P&L with >= 2 trades.*

## 3. Distribution Summary

- Active hours (>= 1 trade): 23 (00, 01, 02, 03, 04, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
- Inactive hours (0 trades): 1 (05)
- Total trades mapped to hours: 56/56

## 4. Best and Worst Hours

### Top 5 Best Hours (by total P&L)

| Hour | Trades | WR% | Total P&L | PF |
|------|--------|-----|-----------|-----|
| 08:00 | 3 | 66.7% | $+552.41 | 13.17 |
| 15:00 | 8 | 75.0% | $+522.13 | 9.14 |
| 13:00 | 6 | 83.3% | $+493.93 | 5.37 |
| 16:00 | 3 | 100.0% | $+399.71 | inf |
| 20:00 | 3 | 66.7% | $+281.03 | 3.02 |

### Top 5 Worst Hours (by total P&L)

| Hour | Trades | WR% | Total P&L | PF |
|------|--------|-----|-----------|-----|
| 19:00 | 3 | 33.3% | $-119.36 | 0.60 |
| 06:00 | 2 | 0.0% | $-118.81 | 0.00 |
| 14:00 | 2 | 50.0% | $-48.54 | 0.49 |
| 00:00 | 2 | 50.0% | $+33.55 | 4.29 |
| 03:00 | 2 | 50.0% | $+50.57 | 1.24 |

## 5. Negative Hours Analysis

**Hours with negative total P&L (>= 2 trades)**: 06:00, 14:00, 19:00
- Combined trades: 7
- Combined P&L: $-286.71

**Hours with WR < 40% (>= 3 trades)**: 07:00, 19:00

## 6. Gate Comparison

### Full Baseline

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.05 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 762.44 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 571.41 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 34.2% | < 35% | PASS |

**Metrics**: 56 trades, PF=2.834, exp/wk=$762.44, DD=8.6%
**Stress**: PF=2.306, exp/wk=$571.41
**Walk-Forward**: 4/5 folds positive

### Filtered (exclude hours [6, 14, 19])

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 11.42 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 829.24 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 648.19 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 5/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 38.5% | < 35% | **FAIL** |

**Metrics**: 49 trades, PF=3.795, exp/wk=$829.24, DD=8.6%
**Stress**: PF=3.046, exp/wk=$648.19
**Walk-Forward**: 5/5 folds positive

### Comparison: Full vs Filtered

| Metric | Full | Filtered | Delta |
|--------|------|----------|-------|
| Trades | 56 | 49 | -7 |
| PF | 2.834 | 3.795 | +0.961 |
| WR% | 64.3 | 69.4 | +5.1 |
| Exp/wk | $762.44 | $829.24 | $+66.80 |
| DD% | 8.6 | 8.6 | +0.0 |
| Gates | 7/7 | 6/7 | -1 |
| WF folds | 4/5 | 5/5 | +1 |

## 7. Verdict

**REGRESSION: Filtering hours [6, 14, 19] reduces gate score from 7/7 to 6/7.**

Recommendation: Time-of-day filtering is NOT worth the added complexity. The signal performs broadly across hours without significant negative clusters.

---
*Generated by run_part2_time_of_day.py at 2026-02-16 00:45*