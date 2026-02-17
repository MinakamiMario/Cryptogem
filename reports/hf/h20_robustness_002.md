# H20 VWAP_DEVIATION Robustness Neighborhood Grid

**Date**: 2026-02-15 23:14
**Commit**: 2246e21
**Universe**: T1(43) + T2(92)
**Timeframe**: 1H
**Cost Regime**: MEXC Market (T1=5bps, T2=20bps)
**Stress**: 2x fees (T1=10bps, T2=40bps)
**Runtime**: 13.8s
**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)

## Grid Design

12 variants perturbing one parameter at a time from v5 baseline.

## All Variants (MEXC Market)

| # | Label | dev | tp | sl | tl | Trades | PF | WR% | Exp/Tr | Exp/Wk | DD% | Fee% | WF | Score |
|---|-------|-----|----|----|----|----|-----|------|--------|--------|------|------|-----|-------|
| 0 | v5 baseline | 2.0 | 8 | 5 | 10 | 43 | 1.847 | 55.8 | $24.99 | $250.04 | 11.4 | 16.8 | 5/5 | 215.0362 |
| 1 | dev_thresh -0.2 | 1.8 | 8 | 5 | 10 | 50 | 1.691 | 56.0 | $21.92 | $255.04 | 14.6 | 16.8 | 4/5 | 204.0297 |
| 2 | dev_thresh +0.2 | 2.2 | 8 | 5 | 10 | 38 | 1.431 | 52.6 | $13.84 | $122.35 | 11.0 | 18.5 | 5/5 | 92.9837 |
| 3 | dev_thresh +0.5 | 2.5 | 8 | 5 | 10 | 30 | 1.119 | 46.7 | $3.59 | $25.07 | 16.9 | 22.6 | 3/5 | 9.0234 |
| 4 | tp_pct -2 | 2.0 | 6 | 5 | 10 | 43 | 1.705 | 58.1 | $17.33 | $173.43 | 11.6 | 20.2 | 4/5 | 119.3224 |
| 5 | tp_pct +2 | 2.0 | 10 | 5 | 10 | 43 | 1.956 | 53.5 | $32.61 | $326.24 | 11.2 | 15.0 | 5/5 | 280.5693 |
| 6 | tp_pct +4 | 2.0 | 12 | 5 | 10 | 43 | 1.593 | 48.8 | $20.64 | $206.49 | 17.4 | 15.3 | 3/5 | 106.5471 |
| 7 | sl_pct -2 | 2.0 | 8 | 3 | 10 | 44 | 2.025 | 52.3 | $24.31 | $248.86 | 14.3 | 18.5 | 4/5 | 175.1968 |
| 8 | sl_pct +2 | 2.0 | 8 | 7 | 10 | 43 | 1.563 | 55.8 | $19.26 | $192.69 | 13.6 | 16.9 | 4/5 | 132.5682 |
| 9 | time_limit -2 | 2.0 | 8 | 5 | 8 | 47 | 1.460 | 51.1 | $12.80 | $139.95 | 10.2 | 20.7 | 5/5 | 131.5484 |
| 10 | time_limit +2 | 2.0 | 8 | 5 | 12 | 41 | 1.820 | 51.2 | $26.02 | $248.25 | 11.6 | 15.7 | 4/5 | 162.8494 |
| 11 | time_limit +5 | 2.0 | 8 | 5 | 15 | 41 | 1.852 | 58.5 | $26.65 | $254.24 | 15.2 | 15.1 | 3/5 | 125.0841 |

## Stress Test (2x Fees)

| # | Label | PF | Exp/Wk | Trades | WR% | DD% |
|---|-------|----|--------|--------|------|------|
| 0 | v5 baseline | 1.577 | $177.90 | 43 | 55.8 | 12.3 |
| 1 | dev_thresh -0.2 | 1.477 | $181.40 | 50 | 56.0 | 17.4 |
| 2 | dev_thresh +0.2 | 1.233 | $69.11 | 38 | 52.6 | 13.4 |
| 3 | dev_thresh +0.5 | 0.951 | $-11.00 | 30 | 46.7 | 20.4 |
| 4 | tp_pct -2 | 1.411 | $107.40 | 43 | 55.8 | 14.0 |
| 5 | tp_pct +2 | 1.679 | $240.71 | 43 | 53.5 | 12.1 |
| 6 | tp_pct +4 | 1.372 | $134.29 | 43 | 48.8 | 19.1 |
| 7 | sl_pct -2 | 1.680 | $177.30 | 44 | 52.3 | 15.8 |
| 8 | sl_pct +2 | 1.353 | $124.36 | 43 | 55.8 | 14.8 |
| 9 | time_limit -2 | 1.231 | $73.84 | 47 | 42.5 | 13.3 |
| 10 | time_limit +2 | 1.564 | $177.47 | 41 | 51.2 | 16.2 |
| 11 | time_limit +5 | 1.600 | $185.09 | 41 | 51.2 | 18.7 |

## Walk-Forward Detail (5-Fold)

| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |
|---|-------|--------|--------|--------|--------|--------|----------|
| 0 | v5 baseline | $108 | $81 | $9 | $569 | $189 | 5/5 |
| 1 | dev_thresh -0.2 | $332 | $228 | $-69 | $569 | $91 | 4/5 |
| 2 | dev_thresh +0.2 | $21 | $92 | $9 | $357 | $37 | 5/5 |
| 3 | dev_thresh +0.5 | $21 | $-56 | $-44 | $45 | $153 | 3/5 |
| 4 | tp_pct -2 | $31 | $90 | $-65 | $394 | $234 | 4/5 |
| 5 | tp_pct +2 | $184 | $121 | $84 | $459 | $271 | 5/5 |
| 6 | tp_pct +4 | $-66 | $161 | $-167 | $606 | $355 | 3/5 |
| 7 | sl_pct -2 | $151 | $89 | $-138 | $613 | $283 | 4/5 |
| 8 | sl_pct +2 | $65 | $81 | $-34 | $525 | $118 | 4/5 |
| 9 | time_limit -2 | $71 | $45 | $98 | $310 | $56 | 5/5 |
| 10 | time_limit +2 | $66 | $6 | $-24 | $547 | $325 | 4/5 |
| 11 | time_limit +5 | $-3 | $-8 | $17 | $639 | $334 | 3/5 |

## Ranking (Composite Score)

```
score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)
```

### #1: tp_pct +2 (variant 5)

- **Params**: dev_thresh=2.0, tp_pct=10, sl_pct=5, time_limit=10
- **Composite Score**: 280.5693
- **Baseline**: 43 trades, PF=1.956, WR=53.5%, Exp/Wk=$326.24, DD=11.2%
- **Walk-Forward**: 5/5 positive folds
- **Stress 2x**: PF=1.679, Exp/Wk=$240.71

### #2: v5 baseline (variant 0)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10
- **Composite Score**: 215.0362
- **Baseline**: 43 trades, PF=1.847, WR=55.8%, Exp/Wk=$250.04, DD=11.4%
- **Walk-Forward**: 5/5 positive folds
- **Stress 2x**: PF=1.577, Exp/Wk=$177.90

### #3: dev_thresh -0.2 (variant 1)

- **Params**: dev_thresh=1.8, tp_pct=8, sl_pct=5, time_limit=10
- **Composite Score**: 204.0297
- **Baseline**: 50 trades, PF=1.691, WR=56.0%, Exp/Wk=$255.04, DD=14.6%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=1.477, Exp/Wk=$181.40

### Full Ranking

| Rank | # | Label | Score | Exp/Wk | WF | Trades |
|------|---|-------|-------|--------|----|--------|
| 1 | 5 | tp_pct +2 | 280.5693 | $326.24 | 5/5 | 43 |
| 2 | 0 | v5 baseline | 215.0362 | $250.04 | 5/5 | 43 |
| 3 | 1 | dev_thresh -0.2 | 204.0297 | $255.04 | 4/5 | 50 |
| 4 | 7 | sl_pct -2 | 175.1968 | $248.86 | 4/5 | 44 |
| 5 | 10 | time_limit +2 | 162.8494 | $248.25 | 4/5 | 41 |
| 6 | 8 | sl_pct +2 | 132.5682 | $192.69 | 4/5 | 43 |
| 7 | 9 | time_limit -2 | 131.5484 | $139.95 | 5/5 | 47 |
| 8 | 11 | time_limit +5 | 125.0841 | $254.24 | 3/5 | 41 |
| 9 | 4 | tp_pct -2 | 119.3224 | $173.43 | 4/5 | 43 |
| 10 | 6 | tp_pct +4 | 106.5471 | $206.49 | 3/5 | 43 |
| 11 | 2 | dev_thresh +0.2 | 92.9837 | $122.35 | 5/5 | 38 |
| 12 | 3 | dev_thresh +0.5 | 9.0234 | $25.07 | 3/5 | 30 |

## Parameter Sensitivity Summary

Comparing each perturbation to v5 baseline (variant 0):

| Param | Change | Trades | Exp/Wk | Score | Delta Score |
|-------|--------|--------|--------|-------|-------------|
| v5 baseline | vs baseline | 43 | $250.04 | 215.0362 | +0.0000 |
| dev_thresh -0.2 | vs baseline | 50 | $255.04 | 204.0297 | -11.0065 |
| dev_thresh +0.2 | vs baseline | 38 | $122.35 | 92.9837 | -122.0525 |
| dev_thresh +0.5 | vs baseline | 30 | $25.07 | 9.0234 | -206.0128 |
| tp_pct -2 | vs baseline | 43 | $173.43 | 119.3224 | -95.7138 |
| tp_pct +2 | vs baseline | 43 | $326.24 | 280.5693 | +65.5331 |
| tp_pct +4 | vs baseline | 43 | $206.49 | 106.5471 | -108.4891 |
| sl_pct -2 | vs baseline | 44 | $248.86 | 175.1968 | -39.8394 |
| sl_pct +2 | vs baseline | 43 | $192.69 | 132.5682 | -82.4680 |
| time_limit -2 | vs baseline | 47 | $139.95 | 131.5484 | -83.4878 |
| time_limit +2 | vs baseline | 41 | $248.25 | 162.8494 | -52.1868 |
| time_limit +5 | vs baseline | 41 | $254.24 | 125.0841 | -89.9521 |

---
*Generated by strategies/hf/screening/run_h20_robustness.py at 2026-02-15 23:14*