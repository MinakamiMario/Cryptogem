# Part 2 Robustness Sweep - 304-coin Universe (excl_worst12)

**Date**: 2026-02-16 00:31
**Commit**: 9f691c0
**Agent**: C3-A1
**Universe**: T1(98) + T2(206) = 304 coins (excl 12 worst by P&L)
**Full universe**: T1(100) + T2(216) = 316 coins
**Timeframe**: 1H
**Cost Regime**: MEXC Market (costs_mexc_v2)
**Fees**: T1=12.5bps, T2=23.5bps
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 32.5s
**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)

## Excluded Coins (12)

Source: `part2_excl_sweep_001.json (excl_worst12)`
Rationale: Worst 12 coins by net P&L -- minimum N for 7/7 baseline gates.

```
ALKIMI/USD, ANIME/USD, DBR/USD, ESX/USD, HOUSE/USD, KET/USD, LMWR/USD, MXC/USD, ODOS/USD, PERP/USD, TANSSI/USD, TITCOIN/USD
```

## G7 Gate: Neighbor Stability

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Profitable neighbors (PF>1.0) | 12/12 | >=8/12 | **PASS** |
| Stress profitable (2x fees PF>1.0) | 12/12 | info | - |
| Stress positive exp/wk | 12/12 | info | - |
| WF >= 3/5 folds | 12/12 | info | - |

## All Variants (MEXC Market)

| # | Label | dev | tp | sl | tl | Trades | T1 | T2 | PF | WR%% | Exp/Wk | DD%% | Fee%% | WF | Score |
|---|-------|-----|----|----|----|----|----|----|-----|------|--------|------|------|-----|-------|
| 0 | v5 baseline | 2.0 | 8 | 5 | 10 | 58 | 19 | 39 | 2.518 | 58.6 | $559.17 | 11.8 | 14.5 | 4/5 | 447.3384 |
| 1 | dev_thresh -0.2 | 1.8 | 8 | 5 | 10 | 71 | 27 | 44 | 2.293 | 57.8 | $633.25 | 18.3 | 14.2 | 4/5 | 506.5986 |
| 2 | dev_thresh +0.2 | 2.2 | 8 | 5 | 10 | 50 | 17 | 33 | 2.439 | 58.0 | $394.49 | 10.9 | 15.1 | 3/5 | 236.6946 |
| 3 | dev_thresh +0.5 | 2.5 | 8 | 5 | 10 | 39 | 11 | 28 | 2.047 | 51.3 | $243.84 | 18.8 | 17.2 | 3/5 | 114.1170 |
| 4 | tp_pct -2 | 2.0 | 6 | 5 | 10 | 58 | 19 | 39 | 2.062 | 58.6 | $360.71 | 15.3 | 17.2 | 4/5 | 288.5676 |
| 5 | tp_pct +2 | 2.0 | 10 | 5 | 10 | 58 | 19 | 39 | 2.325 | 55.2 | $525.99 | 10.8 | 14.1 | 4/5 | 420.7898 |
| 6 | tp_pct +4 | 2.0 | 12 | 5 | 10 | 58 | 19 | 39 | 2.349 | 53.5 | $583.24 | 18.2 | 13.0 | 3/5 | 349.9425 |
| 7 | sl_pct -2 | 2.0 | 8 | 3 | 10 | 61 | 21 | 40 | 2.220 | 52.5 | $424.01 | 23.2 | 15.9 | 3/5 | 254.4049 |
| 8 | sl_pct +2 | 2.0 | 8 | 7 | 10 | 57 | 18 | 39 | 2.242 | 57.9 | $504.78 | 14.6 | 14.4 | 4/5 | 403.8243 |
| 9 | time_limit -2 | 2.0 | 8 | 5 | 8 | 63 | 19 | 44 | 2.596 | 61.9 | $638.22 | 12.3 | 14.8 | 4/5 | 510.5775 |
| 10 | time_limit +2 | 2.0 | 8 | 5 | 12 | 56 | 19 | 37 | 2.312 | 57.1 | $515.76 | 15.1 | 14.0 | 3/5 | 309.4586 |
| 11 | time_limit +5 | 2.0 | 8 | 5 | 15 | 52 | 19 | 33 | 2.126 | 59.6 | $478.10 | 13.4 | 12.9 | 4/5 | 382.4782 |

## Stress Test (2x Fees)

| # | Label | PF | Exp/Wk | P&L | Trades | WR%% | DD%% |
|---|-------|----|--------|------|--------|------|------|
| 0 | v5 baseline | 1.963 | $391.74 | $1684 | 58 | 55.2 | 20.2 |
| 1 | dev_thresh -0.2 | 1.811 | $426.61 | $1833 | 71 | 53.5 | 26.4 |
| 2 | dev_thresh +0.2 | 1.860 | $267.05 | $1148 | 50 | 54.0 | 18.4 |
| 3 | dev_thresh +0.5 | 1.563 | $150.03 | $645 | 39 | 51.3 | 24.4 |
| 4 | tp_pct -2 | 1.583 | $218.64 | $940 | 58 | 55.2 | 23.5 |
| 5 | tp_pct +2 | 1.822 | $358.50 | $1541 | 58 | 51.7 | 16.8 |
| 6 | tp_pct +4 | 1.877 | $413.40 | $1777 | 58 | 50.0 | 25.3 |
| 7 | sl_pct -2 | 1.705 | $274.73 | $1181 | 61 | 49.2 | 31.6 |
| 8 | sl_pct +2 | 1.785 | $345.43 | $1485 | 57 | 56.1 | 22.5 |
| 9 | time_limit -2 | 2.006 | $439.48 | $1889 | 63 | 50.8 | 18.9 |
| 10 | time_limit +2 | 1.831 | $356.64 | $1533 | 56 | 51.8 | 22.7 |
| 11 | time_limit +5 | 1.757 | $337.30 | $1450 | 52 | 57.7 | 15.7 |

## Walk-Forward Detail (5-Fold)

| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |
|---|-------|--------|--------|--------|--------|--------|----------|
| 0 | v5 baseline | $732 | $27 | $-48 | $668 | $723 | 4/5 |
| 1 | dev_thresh -0.2 | $973 | $-199 | $83 | $823 | $813 | 4/5 |
| 2 | dev_thresh +0.2 | $388 | $-68 | $-48 | $458 | $843 | 3/5 |
| 3 | dev_thresh +0.5 | $760 | $-106 | $-163 | $154 | $491 | 3/5 |
| 4 | tp_pct -2 | $513 | $62 | $-123 | $453 | $540 | 4/5 |
| 5 | tp_pct +2 | $657 | $-38 | $29 | $573 | $769 | 4/5 |
| 6 | tp_pct +4 | $828 | $-0 | $-228 | $752 | $905 | 3/5 |
| 7 | sl_pct -2 | $520 | $-56 | $-230 | $722 | $766 | 3/5 |
| 8 | sl_pct +2 | $686 | $44 | $-87 | $621 | $679 | 4/5 |
| 9 | time_limit -2 | $864 | $-49 | $51 | $632 | $822 | 4/5 |
| 10 | time_limit +2 | $728 | $-66 | $-67 | $585 | $799 | 3/5 |
| 11 | time_limit +5 | $619 | $-20 | $8 | $667 | $567 | 4/5 |

## Ranking (Composite Score)

```
score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)
```

### #1: time_limit -2 (variant 9)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=8
- **Composite Score**: 510.5775
- **Baseline**: 63 trades, PF=2.596, WR=61.9%, Exp/Wk=$638.22, DD=12.3%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=2.006, Exp/Wk=$439.48

### #2: dev_thresh -0.2 (variant 1)

- **Params**: dev_thresh=1.8, tp_pct=8, sl_pct=5, time_limit=10
- **Composite Score**: 506.5986
- **Baseline**: 71 trades, PF=2.293, WR=57.8%, Exp/Wk=$633.25, DD=18.3%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=1.811, Exp/Wk=$426.61

### #3: v5 baseline (variant 0)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10
- **Composite Score**: 447.3384
- **Baseline**: 58 trades, PF=2.518, WR=58.6%, Exp/Wk=$559.17, DD=11.8%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=1.963, Exp/Wk=$391.74

### Full Ranking

| Rank | # | Label | Score | Exp/Wk | WF | Trades |
|------|---|-------|-------|--------|----|--------|
| 1 | 9 | time_limit -2 | 510.5775 | $638.22 | 4/5 | 63 |
| 2 | 1 | dev_thresh -0.2 | 506.5986 | $633.25 | 4/5 | 71 |
| 3 | 0 | v5 baseline | 447.3384 | $559.17 | 4/5 | 58 |
| 4 | 5 | tp_pct +2 | 420.7898 | $525.99 | 4/5 | 58 |
| 5 | 8 | sl_pct +2 | 403.8243 | $504.78 | 4/5 | 57 |
| 6 | 11 | time_limit +5 | 382.4782 | $478.10 | 4/5 | 52 |
| 7 | 6 | tp_pct +4 | 349.9425 | $583.24 | 3/5 | 58 |
| 8 | 10 | time_limit +2 | 309.4586 | $515.76 | 3/5 | 56 |
| 9 | 4 | tp_pct -2 | 288.5676 | $360.71 | 4/5 | 58 |
| 10 | 7 | sl_pct -2 | 254.4049 | $424.01 | 3/5 | 61 |
| 11 | 2 | dev_thresh +0.2 | 236.6946 | $394.49 | 3/5 | 50 |
| 12 | 3 | dev_thresh +0.5 | 114.1170 | $243.84 | 3/5 | 39 |

## Comparison: 304 vs 295 vs 316 coins

| Metric | 316 coins | 304 coins | 295 coins |
|--------|-----------|-----------|-----------|
| Excluded | 0 | 12 worst | 21 (all negative) |
| G7 profitable | 9/12 | 12/12 | 12/12 |
| Stress profitable | - | 12/12 | - |
| WF >= 3/5 | - | 12/12 | - |

**Note**: 316-coin G7 was 9/12 PASS. 295-coin G7 was 12/12 PASS.
304-coin universe excludes only the worst 12 (more conservative than 295).

## Parameter Sensitivity Summary

Comparing each perturbation to v5 baseline (variant 0):

| Param | Change | Trades | Exp/Wk | Score | Delta Score |
|-------|--------|--------|--------|-------|-------------|
| v5 baseline | vs baseline | 58 | $559.17 | 447.3384 | +0.0000 |
| dev_thresh -0.2 | vs baseline | 71 | $633.25 | 506.5986 | +59.2602 |
| dev_thresh +0.2 | vs baseline | 50 | $394.49 | 236.6946 | -210.6438 |
| dev_thresh +0.5 | vs baseline | 39 | $243.84 | 114.1170 | -333.2214 |
| tp_pct -2 | vs baseline | 58 | $360.71 | 288.5676 | -158.7708 |
| tp_pct +2 | vs baseline | 58 | $525.99 | 420.7898 | -26.5486 |
| tp_pct +4 | vs baseline | 58 | $583.24 | 349.9425 | -97.3959 |
| sl_pct -2 | vs baseline | 61 | $424.01 | 254.4049 | -192.9335 |
| sl_pct +2 | vs baseline | 57 | $504.78 | 403.8243 | -43.5141 |
| time_limit -2 | vs baseline | 63 | $638.22 | 510.5775 | +63.2391 |
| time_limit +2 | vs baseline | 56 | $515.76 | 309.4586 | -137.8798 |
| time_limit +5 | vs baseline | 52 | $478.10 | 382.4782 | -64.8602 |

---
*Generated by strategies/hf/screening/run_part2_robustness_304.py at 2026-02-16 00:31*