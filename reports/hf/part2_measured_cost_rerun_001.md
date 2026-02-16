# Part 2: Measured Orderbook Cost Rerun (P0-3)

**Date**: 2026-02-16 14:43
**Commit**: 458d2b5
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5/sl7 variants
**Data**: 721 bars (4.3 weeks)
**Runtime**: 69.2s
**Matrix**: 2 configs x 4 regimes x 3 sizes = 24 combinations

## Objective

Test strategy resilience under measured orderbook cost regimes with:
- **Configs**: v5 baseline (sl=5) and sl7 variant (sl=7)
- **Regimes**: Measured maker/taker costs at P50 and P90 from live orderbook data
- **Sizes**: $200, $500, $2000 per trade (size-dependent slippage for taker)
- **Fill model**: Bar-structure fill probability for maker limit orders

STRICT gate thresholds: G1>=10 trades/wk, G2<=2.5d gap, G3/G4>$0 exp/wk,
G5<=20% DD, G6>=4/5 WF folds, G8<35% fold concentration.

## Summary Scoreboard

| Config | Regime | Size | T1 bps | T2 bps | Pre-Fill | Post-Fill | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|--------|----------|-----------|----|----|-----|----|----|
| v5 | measured_ob_maker_p50 | $200 | 3.1 | 4.1 | 56 | 56 | 3.379 | $94.12 | 7.9 | 5/5 | **7/7** |
| v5 | measured_ob_maker_p50 | $500 | 3.1 | 4.1 | 56 | 56 | 3.379 | $235.30 | 7.9 | 5/5 | **7/7** |
| v5 | measured_ob_maker_p50 | $2000 | 3.1 | 4.1 | 56 | 56 | 3.379 | $941.21 | 7.9 | 5/5 | **7/7** |
| v5 | measured_ob_maker_p90 | $200 | 29.2 | 11.4 | 56 | 56 | 2.981 | $81.50 | 8.5 | 5/5 | **7/7** |
| v5 | measured_ob_maker_p90 | $500 | 29.2 | 11.4 | 56 | 56 | 2.981 | $203.74 | 8.5 | 5/5 | **7/7** |
| v5 | measured_ob_maker_p90 | $2000 | 29.2 | 11.4 | 56 | 56 | 2.981 | $814.97 | 8.5 | 5/5 | **7/7** |
| v5 | measured_ob_taker_p50 | $200 | 31.9 | 29.9 | 56 | 56 | 2.557 | $66.84 | 10.7 | 4/5 | 6/7 |
| v5 | measured_ob_taker_p50 | $500 | 34.1 | 31.4 | 56 | 56 | 2.511 | $163.16 | 11.1 | 3/5 | 5/7 |
| v5 | measured_ob_taker_p50 | $2000 | 29.9 | 36.7 | 56 | 56 | 2.446 | $626.28 | 11.7 | 3/5 | 5/7 |
| v5 | measured_ob_taker_p90 | $200 | 214.2 | 100.2 | 56 | 56 | 0.929 | $-4.20 | 41.2 | 3/5 | 2/7 |
| v5 | measured_ob_taker_p90 | $500 | 369.8 | 106.4 | 56 | 56 | 0.667 | $-54.85 | 58.7 | 2/5 | 2/7 |
| v5 | measured_ob_taker_p90 | $2000 | 268.4 | 151.0 | 56 | 56 | 0.559 | $-282.14 | 67.4 | 2/5 | 2/7 |
| sl7 | measured_ob_maker_p50 | $200 | 3.1 | 4.1 | 55 | 55 | 3.209 | $92.01 | 8.6 | 5/5 | **7/7** |
| sl7 | measured_ob_maker_p50 | $500 | 3.1 | 4.1 | 55 | 55 | 3.209 | $230.02 | 8.6 | 5/5 | **7/7** |
| sl7 | measured_ob_maker_p50 | $2000 | 3.1 | 4.1 | 55 | 55 | 3.209 | $920.08 | 8.6 | 5/5 | **7/7** |
| sl7 | measured_ob_maker_p90 | $200 | 29.2 | 11.4 | 55 | 55 | 2.857 | $79.87 | 9.5 | 5/5 | **7/7** |
| sl7 | measured_ob_maker_p90 | $500 | 29.2 | 11.4 | 55 | 55 | 2.857 | $199.68 | 9.5 | 5/5 | **7/7** |
| sl7 | measured_ob_maker_p90 | $2000 | 29.2 | 11.4 | 55 | 55 | 2.857 | $798.71 | 9.5 | 5/5 | **7/7** |
| sl7 | measured_ob_taker_p50 | $200 | 31.9 | 29.9 | 55 | 55 | 2.468 | $65.41 | 10.6 | 5/5 | **7/7** |
| sl7 | measured_ob_taker_p50 | $500 | 34.1 | 31.4 | 55 | 55 | 2.426 | $159.69 | 10.7 | 4/5 | **7/7** |
| sl7 | measured_ob_taker_p50 | $2000 | 29.9 | 36.7 | 55 | 55 | 2.365 | $612.20 | 11.3 | 4/5 | 6/7 |
| sl7 | measured_ob_taker_p90 | $200 | 214.2 | 100.2 | 55 | 55 | 0.936 | $-3.73 | 36.6 | 2/5 | 2/7 |
| sl7 | measured_ob_taker_p90 | $500 | 369.8 | 106.4 | 55 | 55 | 0.674 | $-53.18 | 55.6 | 2/5 | 2/7 |
| sl7 | measured_ob_taker_p90 | $2000 | 268.4 | 151.0 | 55 | 55 | 0.568 | $-274.17 | 64.4 | 2/5 | 2/7 |

## Gate Results Summary

- **Passing ALL gates**: 14/24

  - v5/measured_ob_maker_p50/$200
  - v5/measured_ob_maker_p50/$500
  - v5/measured_ob_maker_p50/$2000
  - v5/measured_ob_maker_p90/$200
  - v5/measured_ob_maker_p90/$500
  - v5/measured_ob_maker_p90/$2000
  - sl7/measured_ob_maker_p50/$200
  - sl7/measured_ob_maker_p50/$500
  - sl7/measured_ob_maker_p50/$2000
  - sl7/measured_ob_maker_p90/$200
  - sl7/measured_ob_maker_p90/$500
  - sl7/measured_ob_maker_p90/$2000
  - sl7/measured_ob_taker_p50/$200
  - sl7/measured_ob_taker_p50/$500

- **Failing**: 10/24

  - v5/measured_ob_taker_p50/$200: fails G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$500: fails G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$2000: fails G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$200: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$500: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$2000: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$2000: fails G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$200: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$500: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$2000: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc

## Fill Model Impact (Maker Regimes)

| Config | Regime | Size | Pre-Fill Trades | Post-Fill Trades | Fill Rate | Pre PnL | Post PnL |
|--------|--------|------|-----------------|------------------|-----------|---------|----------|
| v5 | measured_ob_maker_p50 | $200 | 56 | 56 | 100.0% | $404 | $404 |
| v5 | measured_ob_maker_p50 | $500 | 56 | 56 | 100.0% | $1010 | $1010 |
| v5 | measured_ob_maker_p50 | $2000 | 56 | 56 | 100.0% | $4039 | $4039 |
| v5 | measured_ob_maker_p90 | $200 | 56 | 56 | 100.0% | $350 | $350 |
| v5 | measured_ob_maker_p90 | $500 | 56 | 56 | 100.0% | $874 | $874 |
| v5 | measured_ob_maker_p90 | $2000 | 56 | 56 | 100.0% | $3498 | $3498 |
| sl7 | measured_ob_maker_p50 | $200 | 55 | 55 | 100.0% | $395 | $395 |
| sl7 | measured_ob_maker_p50 | $500 | 55 | 55 | 100.0% | $987 | $987 |
| sl7 | measured_ob_maker_p50 | $2000 | 55 | 55 | 100.0% | $3949 | $3949 |
| sl7 | measured_ob_maker_p90 | $200 | 55 | 55 | 100.0% | $343 | $343 |
| sl7 | measured_ob_maker_p90 | $500 | 55 | 55 | 100.0% | $857 | $857 |
| sl7 | measured_ob_maker_p90 | $2000 | 55 | 55 | 100.0% | $3428 | $3428 |

### v5 / measured_ob_maker_p50 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 56tr, PF=3.379, WR=69.6%, P&L=$404, Exp/Wk=$94.12, DD=7.9%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=3.247, Exp/Wk=$89.86
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.333

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 94.1214 | >$0 | PASS |
| G4_stress_exp_per_week | 89.8617 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 7.9 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3326 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $99 | Yes |
| 1 | 13 | $15 | Yes |
| 2 | 9 | $5 | Yes |
| 3 | 9 | $86 | Yes |
| 4 | 15 | $102 | Yes |

### v5 / measured_ob_maker_p50 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 56tr, PF=3.379, WR=69.6%, P&L=$1010, Exp/Wk=$235.30, DD=7.9%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=3.247, Exp/Wk=$224.65
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.333

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 235.3035 | >$0 | PASS |
| G4_stress_exp_per_week | 224.6543 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 7.9 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3326 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $249 | Yes |
| 1 | 13 | $37 | Yes |
| 2 | 9 | $12 | Yes |
| 3 | 9 | $215 | Yes |
| 4 | 15 | $256 | Yes |

### v5 / measured_ob_maker_p50 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 56tr, PF=3.379, WR=69.6%, P&L=$4039, Exp/Wk=$941.21, DD=7.9%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=3.247, Exp/Wk=$898.62
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.333

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 941.2142 | >$0 | PASS |
| G4_stress_exp_per_week | 898.6173 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 7.9 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3326 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $994 | Yes |
| 1 | 13 | $149 | Yes |
| 2 | 9 | $47 | Yes |
| 3 | 9 | $862 | Yes |
| 4 | 15 | $1023 | Yes |

### v5 / measured_ob_maker_p90 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 56tr, PF=2.981, WR=58.9%, P&L=$350, Exp/Wk=$81.50, DD=8.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=2.494, Exp/Wk=$65.96
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.341

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 81.4974 | >$0 | PASS |
| G4_stress_exp_per_week | 65.9641 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3411 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $93 | Yes |
| 1 | 13 | $8 | Yes |
| 2 | 9 | $1 | Yes |
| 3 | 9 | $80 | Yes |
| 4 | 15 | $91 | Yes |

### v5 / measured_ob_maker_p90 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 56tr, PF=2.981, WR=58.9%, P&L=$874, Exp/Wk=$203.74, DD=8.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=2.494, Exp/Wk=$164.91
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.341

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 203.7435 | >$0 | PASS |
| G4_stress_exp_per_week | 164.9102 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3411 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $233 | Yes |
| 1 | 13 | $20 | Yes |
| 2 | 9 | $1 | Yes |
| 3 | 9 | $201 | Yes |
| 4 | 15 | $228 | Yes |

### v5 / measured_ob_maker_p90 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 56tr, PF=2.981, WR=58.9%, P&L=$3498, Exp/Wk=$814.97, DD=8.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=2.494, Exp/Wk=$659.64
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.341

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 814.9739 | >$0 | PASS |
| G4_stress_exp_per_week | 659.6408 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3411 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $933 | Yes |
| 1 | 13 | $80 | Yes |
| 2 | 9 | $5 | Yes |
| 3 | 9 | $804 | Yes |
| 4 | 15 | $912 | Yes |

### v5 / measured_ob_taker_p50 / $200

- **Execution mode**: taker_market
- **Fees**: T1=31.9bps, T2=29.9bps per side
- **Baseline**: 56tr, PF=2.557, WR=58.9%, P&L=$287, Exp/Wk=$66.84, DD=10.7%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=1.863, Exp/Wk=$40.67
- **Walk-Forward**: 4/5 folds positive, top1 conc=0.353

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 66.8406 | >$0 | PASS |
| G4_stress_exp_per_week | 40.6739 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 10.7 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3527 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $86 | Yes |
| 1 | 13 | $0 | Yes |
| 2 | 9 | $-5 | No |
| 3 | 9 | $75 | Yes |
| 4 | 15 | $83 | Yes |

### v5 / measured_ob_taker_p50 / $500

- **Execution mode**: taker_market
- **Fees**: T1=34.1bps, T2=31.4bps per side
- **Baseline**: 56tr, PF=2.511, WR=57.1%, P&L=$700, Exp/Wk=$163.16, DD=11.1%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=1.799, Exp/Wk=$95.15
- **Walk-Forward**: 3/5 folds positive, top1 conc=0.354

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 163.161 | >$0 | PASS |
| G4_stress_exp_per_week | 95.1476 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 11.1 | <=20% | PASS |
| G6_wf_folds_positive | 3 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.3539 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $213 | Yes |
| 1 | 13 | $-1 | No |
| 2 | 9 | $-14 | No |
| 3 | 9 | $185 | Yes |
| 4 | 15 | $204 | Yes |

### v5 / measured_ob_taker_p50 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=29.9bps, T2=36.7bps per side
- **Baseline**: 56tr, PF=2.446, WR=58.9%, P&L=$2688, Exp/Wk=$626.28, DD=11.7%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=1.716, Exp/Wk=$341.98
- **Walk-Forward**: 3/5 folds positive, top1 conc=0.353

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 626.284 | >$0 | PASS |
| G4_stress_exp_per_week | 341.9785 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 11.7 | <=20% | PASS |
| G6_wf_folds_positive | 3 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.3527 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $838 | Yes |
| 1 | 13 | $-20 | No |
| 2 | 9 | $-69 | No |
| 3 | 9 | $731 | Yes |
| 4 | 15 | $807 | Yes |

### v5 / measured_ob_taker_p90 / $200

- **Execution mode**: taker_market
- **Fees**: T1=214.2bps, T2=100.2bps per side
- **Baseline**: 56tr, PF=0.929, WR=44.6%, P&L=$-18, Exp/Wk=$-4.20, DD=41.2%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=0.276, Exp/Wk=$-52.82
- **Walk-Forward**: 3/5 folds positive, top1 conc=0.513

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -4.2005 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -52.8157 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 41.2 | <=20% | **FAIL** |
| G6_wf_folds_positive | 3 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.5132 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $38 | Yes |
| 1 | 13 | $-51 | No |
| 2 | 9 | $-38 | No |
| 3 | 9 | $31 | Yes |
| 4 | 15 | $5 | Yes |

### v5 / measured_ob_taker_p90 / $500

- **Execution mode**: taker_market
- **Fees**: T1=369.8bps, T2=106.4bps per side
- **Baseline**: 56tr, PF=0.667, WR=42.9%, P&L=$-235, Exp/Wk=$-54.85, DD=58.7%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=0.215, Exp/Wk=$-164.94
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.638

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -54.8473 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -164.9449 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 58.7 | <=20% | **FAIL** |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6378 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $45 | Yes |
| 1 | 13 | $-183 | No |
| 2 | 9 | $-128 | No |
| 3 | 9 | $26 | Yes |
| 4 | 15 | $-84 | No |

### v5 / measured_ob_taker_p90 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=268.4bps, T2=151.0bps per side
- **Baseline**: 56tr, PF=0.559, WR=41.1%, P&L=$-1211, Exp/Wk=$-282.14, DD=67.4%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 56tr, PF=0.086, Exp/Wk=$-720.03
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.576

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -282.1407 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -720.0312 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 67.4 | <=20% | **FAIL** |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.5762 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $152 | Yes |
| 1 | 13 | $-753 | No |
| 2 | 9 | $-554 | No |
| 3 | 9 | $112 | Yes |
| 4 | 15 | $-257 | No |

### sl7 / measured_ob_maker_p50 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 55tr, PF=3.209, WR=69.1%, P&L=$395, Exp/Wk=$92.01, DD=8.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=3.090, Exp/Wk=$87.84
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.314

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 92.0076 | >$0 | PASS |
| G4_stress_exp_per_week | 87.8397 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.6 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3141 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $95 | Yes |
| 1 | 12 | $16 | Yes |
| 2 | 9 | $10 | Yes |
| 3 | 9 | $86 | Yes |
| 4 | 15 | $95 | Yes |

### sl7 / measured_ob_maker_p50 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 55tr, PF=3.209, WR=69.1%, P&L=$987, Exp/Wk=$230.02, DD=8.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=3.090, Exp/Wk=$219.60
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.314

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 230.019 | >$0 | PASS |
| G4_stress_exp_per_week | 219.5993 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.6 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3141 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $237 | Yes |
| 1 | 12 | $40 | Yes |
| 2 | 9 | $25 | Yes |
| 3 | 9 | $215 | Yes |
| 4 | 15 | $236 | Yes |

### sl7 / measured_ob_maker_p50 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=3.1bps, T2=4.1bps per side
- **Baseline**: 55tr, PF=3.209, WR=69.1%, P&L=$3949, Exp/Wk=$920.08, DD=8.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=3.090, Exp/Wk=$878.40
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.314

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 920.0759 | >$0 | PASS |
| G4_stress_exp_per_week | 878.3972 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.6 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3141 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $948 | Yes |
| 1 | 12 | $161 | Yes |
| 2 | 9 | $101 | Yes |
| 3 | 9 | $862 | Yes |
| 4 | 15 | $946 | Yes |

### sl7 / measured_ob_maker_p90 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 55tr, PF=2.857, WR=60.0%, P&L=$343, Exp/Wk=$79.87, DD=9.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=2.421, Exp/Wk=$64.83
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.330

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 79.8712 | >$0 | PASS |
| G4_stress_exp_per_week | 64.83 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 9.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.33 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $89 | Yes |
| 1 | 12 | $10 | Yes |
| 2 | 9 | $6 | Yes |
| 3 | 9 | $80 | Yes |
| 4 | 15 | $84 | Yes |

### sl7 / measured_ob_maker_p90 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 55tr, PF=2.857, WR=60.0%, P&L=$857, Exp/Wk=$199.68, DD=9.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=2.421, Exp/Wk=$162.07
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.330

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 199.678 | >$0 | PASS |
| G4_stress_exp_per_week | 162.0749 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 9.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.33 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $222 | Yes |
| 1 | 12 | $25 | Yes |
| 2 | 9 | $15 | Yes |
| 3 | 9 | $201 | Yes |
| 4 | 15 | $209 | Yes |

### sl7 / measured_ob_maker_p90 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=29.2bps, T2=11.4bps per side
- **Baseline**: 55tr, PF=2.857, WR=60.0%, P&L=$3428, Exp/Wk=$798.71, DD=9.5%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=2.421, Exp/Wk=$648.30
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.330

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 798.712 | >$0 | PASS |
| G4_stress_exp_per_week | 648.2997 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 9.5 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.33 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $887 | Yes |
| 1 | 12 | $102 | Yes |
| 2 | 9 | $59 | Yes |
| 3 | 9 | $804 | Yes |
| 4 | 15 | $836 | Yes |

### sl7 / measured_ob_taker_p50 / $200

- **Execution mode**: taker_market
- **Fees**: T1=31.9bps, T2=29.9bps per side
- **Baseline**: 55tr, PF=2.468, WR=60.0%, P&L=$281, Exp/Wk=$65.41, DD=10.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=1.828, Exp/Wk=$39.87
- **Walk-Forward**: 5/5 folds positive, top1 conc=0.347

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 65.4096 | >$0 | PASS |
| G4_stress_exp_per_week | 39.873 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 10.6 | <=20% | PASS |
| G6_wf_folds_positive | 5 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3475 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $81 | Yes |
| 1 | 12 | $3 | Yes |
| 2 | 9 | $0 | Yes |
| 3 | 9 | $75 | Yes |
| 4 | 15 | $75 | Yes |

### sl7 / measured_ob_taker_p50 / $500

- **Execution mode**: taker_market
- **Fees**: T1=34.1bps, T2=31.4bps per side
- **Baseline**: 55tr, PF=2.426, WR=58.2%, P&L=$685, Exp/Wk=$159.69, DD=10.7%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=1.768, Exp/Wk=$93.32
- **Walk-Forward**: 4/5 folds positive, top1 conc=0.349

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 159.6922 | >$0 | PASS |
| G4_stress_exp_per_week | 93.3199 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 10.7 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3494 | <0.35 | PASS |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $201 | Yes |
| 1 | 12 | $5 | Yes |
| 2 | 9 | $-1 | No |
| 3 | 9 | $185 | Yes |
| 4 | 15 | $185 | Yes |

### sl7 / measured_ob_taker_p50 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=29.9bps, T2=36.7bps per side
- **Baseline**: 55tr, PF=2.365, WR=60.0%, P&L=$2627, Exp/Wk=$612.20, DD=11.3%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=1.686, Exp/Wk=$334.31
- **Walk-Forward**: 4/5 folds positive, top1 conc=0.350

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 612.202 | >$0 | PASS |
| G4_stress_exp_per_week | 334.3104 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 11.3 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3503 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $792 | Yes |
| 1 | 12 | $4 | Yes |
| 2 | 9 | $-18 | No |
| 3 | 9 | $731 | Yes |
| 4 | 15 | $734 | Yes |

### sl7 / measured_ob_taker_p90 / $200

- **Execution mode**: taker_market
- **Fees**: T1=214.2bps, T2=100.2bps per side
- **Baseline**: 55tr, PF=0.936, WR=45.5%, P&L=$-16, Exp/Wk=$-3.73, DD=36.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=0.280, Exp/Wk=$-51.89
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.523

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -3.7306 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -51.8937 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 36.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.5228 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $34 | Yes |
| 1 | 12 | $-43 | No |
| 2 | 9 | $-34 | No |
| 3 | 9 | $31 | Yes |
| 4 | 15 | $-1 | No |

### sl7 / measured_ob_taker_p90 / $500

- **Execution mode**: taker_market
- **Fees**: T1=369.8bps, T2=106.4bps per side
- **Baseline**: 55tr, PF=0.674, WR=43.6%, P&L=$-228, Exp/Wk=$-53.18, DD=55.6%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=0.217, Exp/Wk=$-163.89
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.581

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -53.179 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -163.8893 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 55.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.5809 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $36 | Yes |
| 1 | 12 | $-153 | No |
| 2 | 9 | $-117 | No |
| 3 | 9 | $26 | Yes |
| 4 | 15 | $-100 | No |

### sl7 / measured_ob_taker_p90 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=268.4bps, T2=151.0bps per side
- **Baseline**: 55tr, PF=0.568, WR=41.8%, P&L=$-1177, Exp/Wk=$-274.17, DD=64.4%
- **Max Gap**: 1.42d (34 bars)
- **Stress 2x**: 55tr, PF=0.087, Exp/Wk=$-710.85
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.501

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 12.82 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -274.1721 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -710.8526 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 64.4 | <=20% | **FAIL** |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.5014 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $111 | Yes |
| 1 | 12 | $-653 | No |
| 2 | 9 | $-513 | No |
| 3 | 9 | $112 | Yes |
| 4 | 15 | $-317 | No |

## Verdict

**Combinations passing ALL STRICT gates**: 14/24

**Passing combinations**:
  - v5/measured_ob_maker_p50/$200: 56tr PF=3.379 Exp/wk=$94.12
  - v5/measured_ob_maker_p50/$500: 56tr PF=3.379 Exp/wk=$235.30
  - v5/measured_ob_maker_p50/$2000: 56tr PF=3.379 Exp/wk=$941.21
  - v5/measured_ob_maker_p90/$200: 56tr PF=2.981 Exp/wk=$81.50
  - v5/measured_ob_maker_p90/$500: 56tr PF=2.981 Exp/wk=$203.74
  - v5/measured_ob_maker_p90/$2000: 56tr PF=2.981 Exp/wk=$814.97
  - sl7/measured_ob_maker_p50/$200: 55tr PF=3.209 Exp/wk=$92.01
  - sl7/measured_ob_maker_p50/$500: 55tr PF=3.209 Exp/wk=$230.02
  - sl7/measured_ob_maker_p50/$2000: 55tr PF=3.209 Exp/wk=$920.08
  - sl7/measured_ob_maker_p90/$200: 55tr PF=2.857 Exp/wk=$79.87
  - sl7/measured_ob_maker_p90/$500: 55tr PF=2.857 Exp/wk=$199.68
  - sl7/measured_ob_maker_p90/$2000: 55tr PF=2.857 Exp/wk=$798.71
  - sl7/measured_ob_taker_p50/$200: 55tr PF=2.468 Exp/wk=$65.41
  - sl7/measured_ob_taker_p50/$500: 55tr PF=2.426 Exp/wk=$159.69

**Failing combinations**:
  - v5/measured_ob_taker_p50/$200: fails G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$500: fails G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$2000: fails G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$200: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$500: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$2000: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$2000: fails G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$200: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$500: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$2000: fails G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc

**Size sensitivity** (v5 config, same regime):
  measured_ob_maker_p50:
    $200: 56tr PF=3.379 Exp/wk=$94.12 PASS
    $500: 56tr PF=3.379 Exp/wk=$235.30 PASS
    $2000: 56tr PF=3.379 Exp/wk=$941.21 PASS
  measured_ob_maker_p90:
    $200: 56tr PF=2.981 Exp/wk=$81.50 PASS
    $500: 56tr PF=2.981 Exp/wk=$203.74 PASS
    $2000: 56tr PF=2.981 Exp/wk=$814.97 PASS
  measured_ob_taker_p50:
    $200: 56tr PF=2.557 Exp/wk=$66.84 FAIL
    $500: 56tr PF=2.511 Exp/wk=$163.16 FAIL
    $2000: 56tr PF=2.446 Exp/wk=$626.28 FAIL
  measured_ob_taker_p90:
    $200: 56tr PF=0.929 Exp/wk=$-4.20 FAIL
    $500: 56tr PF=0.667 Exp/wk=$-54.85 FAIL
    $2000: 56tr PF=0.559 Exp/wk=$-282.14 FAIL

**Maker vs Taker** (v5 config, $200 size):
  p50: maker 56tr Exp/wk=$94.12 vs taker 56tr Exp/wk=$66.84
  p90: maker 56tr Exp/wk=$81.50 vs taker 56tr Exp/wk=$-4.20

**CONCLUSION**: Strategy passes STRICT gates in 14/24 combinations. Some regimes/sizes erode edge. Review failing combinations.

---
*Generated by strategies/hf/screening/run_part2_measured_cost_rerun.py at 2026-02-16 14:43*