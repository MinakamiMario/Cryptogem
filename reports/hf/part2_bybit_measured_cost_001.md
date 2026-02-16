# BYBIT Multi-Exchange Validation Report

**Date**: 2026-02-16 20:54
**Commit**: 336c2e8
**Exchange**: BYBIT
**Fees**: maker=10.0bps, taker=10.0bps (regular)
**Universe**: T1(114) + T2(340) = 454 coins (excl 0)
**Signal**: H20 VWAP_DEVIATION v5/sl7 variants
**Data**: 721 bars (4.3 weeks)
**Runtime**: 111.6s
**Matrix**: 2 configs x 4 regimes x 3 sizes = 24 combinations

## Objective

Test H20 VWAP_DEVIATION signal on BYBIT under measured orderbook cost regimes with 7 STRICT gates.

## Summary Scoreboard

| Config | Regime | Size | T1 bps | T2 bps | Pre-Fill | Post-Fill | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|--------|----------|-----------|----|----|-----|----|----|
| v5 | measured_ob_maker_p50 | $200 | 11.9 | 15.0 | 15 | 15 | 0.672 | $-4.67 | 14.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p50 | $500 | 11.9 | 15.0 | 15 | 15 | 0.672 | $-11.68 | 14.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p50 | $2000 | 11.9 | 15.0 | 15 | 15 | 0.672 | $-46.73 | 14.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $200 | 14.6 | 22.0 | 15 | 15 | 0.627 | $-5.47 | 15.3 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $500 | 14.6 | 22.0 | 15 | 15 | 0.627 | $-13.67 | 15.3 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $2000 | 14.6 | 22.0 | 15 | 15 | 0.627 | $-54.68 | 15.3 | 2/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $200 | 17.3 | 31.5 | 15 | 15 | 0.572 | $-6.51 | 17.1 | 2/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $500 | 17.5 | 36.4 | 15 | 15 | 0.547 | $-17.54 | 18.0 | 2/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $2000 | 18.8 | 46.0 | 15 | 15 | 0.499 | $-80.05 | 19.7 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p90 | $200 | 26.0 | 70.6 | 15 | 15 | 0.394 | $-10.52 | 24.1 | 1/5 | 0/7 |
| v5 | measured_ob_taker_p90 | $500 | 27.1 | 89.4 | 15 | 15 | 0.335 | $-30.64 | 27.5 | 0/5 | 0/7 |
| v5 | measured_ob_taker_p90 | $2000 | 34.1 | 112.3 | 15 | 15 | 0.276 | $-143.80 | 31.5 | 0/5 | 0/7 |
| sl7 | measured_ob_maker_p50 | $200 | 11.9 | 15.0 | 15 | 15 | 0.530 | $-8.21 | 21.6 | 1/5 | 0/7 |
| sl7 | measured_ob_maker_p50 | $500 | 11.9 | 15.0 | 15 | 15 | 0.530 | $-20.53 | 21.6 | 1/5 | 0/7 |
| sl7 | measured_ob_maker_p50 | $2000 | 11.9 | 15.0 | 15 | 15 | 0.530 | $-82.12 | 21.6 | 1/5 | 0/7 |
| sl7 | measured_ob_maker_p90 | $200 | 14.6 | 22.0 | 15 | 15 | 0.498 | $-8.96 | 22.9 | 1/5 | 0/7 |
| sl7 | measured_ob_maker_p90 | $500 | 14.6 | 22.0 | 15 | 15 | 0.498 | $-22.40 | 22.9 | 1/5 | 0/7 |
| sl7 | measured_ob_maker_p90 | $2000 | 14.6 | 22.0 | 15 | 15 | 0.498 | $-89.62 | 22.9 | 1/5 | 0/7 |
| sl7 | measured_ob_taker_p50 | $200 | 17.3 | 31.5 | 15 | 15 | 0.458 | $-9.94 | 24.6 | 1/5 | 0/7 |
| sl7 | measured_ob_taker_p50 | $500 | 17.5 | 36.4 | 15 | 15 | 0.440 | $-26.05 | 25.4 | 1/5 | 0/7 |
| sl7 | measured_ob_taker_p50 | $2000 | 18.8 | 46.0 | 15 | 15 | 0.405 | $-113.51 | 27.0 | 1/5 | 0/7 |
| sl7 | measured_ob_taker_p90 | $200 | 26.0 | 70.6 | 15 | 15 | 0.326 | $-13.72 | 31.2 | 1/5 | 0/7 |
| sl7 | measured_ob_taker_p90 | $500 | 27.1 | 89.4 | 15 | 15 | 0.280 | $-38.39 | 34.3 | 0/5 | 0/7 |
| sl7 | measured_ob_taker_p90 | $2000 | 34.1 | 112.3 | 15 | 15 | 0.235 | $-173.57 | 38.2 | 0/5 | 0/7 |

## Gate Results Summary

- **Passing ALL gates**: 0/24

- **Failing**: 24/24

  - v5/measured_ob_maker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc

## Fill Model Impact (Maker Regimes)

| Config | Regime | Size | Pre-Fill | Post-Fill | Fill Rate | Pre PnL | Post PnL |
|--------|--------|------|----------|-----------|-----------|---------|----------|
| v5 | measured_ob_maker_p50 | $200 | 15 | 15 | 100.0% | $-20 | $-20 |
| v5 | measured_ob_maker_p50 | $500 | 15 | 15 | 100.0% | $-50 | $-50 |
| v5 | measured_ob_maker_p50 | $2000 | 15 | 15 | 100.0% | $-201 | $-201 |
| v5 | measured_ob_maker_p90 | $200 | 15 | 15 | 100.0% | $-23 | $-23 |
| v5 | measured_ob_maker_p90 | $500 | 15 | 15 | 100.0% | $-59 | $-59 |
| v5 | measured_ob_maker_p90 | $2000 | 15 | 15 | 100.0% | $-235 | $-235 |
| sl7 | measured_ob_maker_p50 | $200 | 15 | 15 | 100.0% | $-35 | $-35 |
| sl7 | measured_ob_maker_p50 | $500 | 15 | 15 | 100.0% | $-88 | $-88 |
| sl7 | measured_ob_maker_p50 | $2000 | 15 | 15 | 100.0% | $-352 | $-352 |
| sl7 | measured_ob_maker_p90 | $200 | 15 | 15 | 100.0% | $-38 | $-38 |
| sl7 | measured_ob_maker_p90 | $500 | 15 | 15 | 100.0% | $-96 | $-96 |
| sl7 | measured_ob_maker_p90 | $2000 | 15 | 15 | 100.0% | $-385 | $-385 |

### v5 / measured_ob_maker_p50 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.672, WR=40.0%, P&L=$-20, Exp/Wk=$-4.67, DD=14.0%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.573, Exp/Wk=$-6.48
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.602

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -4.673 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -6.4775 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 14.0 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6022 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-19 | No |
| 2 | 6 | $5 | Yes |
| 3 | 1 | $-10 | No |
| 4 | 4 | $8 | Yes |

### v5 / measured_ob_maker_p50 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.672, WR=40.0%, P&L=$-50, Exp/Wk=$-11.68, DD=14.0%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.573, Exp/Wk=$-16.19
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.602

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -11.6825 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -16.1937 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 14.0 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6022 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-9 | No |
| 1 | 3 | $-47 | No |
| 2 | 6 | $13 | Yes |
| 3 | 1 | $-26 | No |
| 4 | 4 | $20 | Yes |

### v5 / measured_ob_maker_p50 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.672, WR=40.0%, P&L=$-201, Exp/Wk=$-46.73, DD=14.0%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.573, Exp/Wk=$-64.77
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.602

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -46.7298 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -64.7747 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 14.0 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6022 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-37 | No |
| 1 | 3 | $-189 | No |
| 2 | 6 | $53 | Yes |
| 3 | 1 | $-105 | No |
| 4 | 4 | $81 | Yes |

### v5 / measured_ob_maker_p90 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.627, WR=40.0%, P&L=$-23, Exp/Wk=$-5.47, DD=15.3%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.499, Exp/Wk=$-8.00
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.664

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -5.4682 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -8.0024 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 15.3 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6639 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-20 | No |
| 2 | 6 | $4 | Yes |
| 3 | 1 | $-11 | No |
| 4 | 4 | $7 | Yes |

### v5 / measured_ob_maker_p90 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.627, WR=40.0%, P&L=$-59, Exp/Wk=$-13.67, DD=15.3%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.499, Exp/Wk=$-20.01
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.664

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -13.6704 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -20.0061 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 15.3 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6639 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-10 | No |
| 1 | 3 | $-49 | No |
| 2 | 6 | $9 | Yes |
| 3 | 1 | $-26 | No |
| 4 | 4 | $18 | Yes |

### v5 / measured_ob_maker_p90 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.627, WR=40.0%, P&L=$-235, Exp/Wk=$-54.68, DD=15.3%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.499, Exp/Wk=$-80.02
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.664

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -54.6817 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -80.0242 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 15.3 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.6639 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-40 | No |
| 1 | 3 | $-196 | No |
| 2 | 6 | $36 | Yes |
| 3 | 1 | $-106 | No |
| 4 | 4 | $72 | Yes |

### v5 / measured_ob_taker_p50 / $200

- **Execution mode**: taker_market
- **Fees**: T1=17.3bps, T2=31.5bps per side
- **Baseline**: 15tr, PF=0.572, WR=40.0%, P&L=$-28, Exp/Wk=$-6.51, DD=17.1%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.415, Exp/Wk=$-9.96
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.819

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -6.5091 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -9.9595 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 17.1 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.819 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-21 | No |
| 2 | 6 | $1 | Yes |
| 3 | 1 | $-11 | No |
| 4 | 4 | $6 | Yes |

### v5 / measured_ob_taker_p50 / $500

- **Execution mode**: taker_market
- **Fees**: T1=17.5bps, T2=36.4bps per side
- **Baseline**: 15tr, PF=0.547, WR=40.0%, P&L=$-75, Exp/Wk=$-17.54, DD=18.0%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.380, Exp/Wk=$-27.23
- **Walk-Forward**: 2/5 folds positive, top1 conc=0.976

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -17.5363 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -27.2271 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 18.0 | <=20% | PASS |
| G6_wf_folds_positive | 2 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.976 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-11 | No |
| 1 | 3 | $-53 | No |
| 2 | 6 | $0 | Yes |
| 3 | 1 | $-27 | No |
| 4 | 4 | $13 | Yes |

### v5 / measured_ob_taker_p50 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=18.8bps, T2=46.0bps per side
- **Baseline**: 15tr, PF=0.499, WR=40.0%, P&L=$-344, Exp/Wk=$-80.05, DD=19.7%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.321, Exp/Wk=$-126.87
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -80.0486 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -126.8675 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 19.7 | <=20% | PASS |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-49 | No |
| 1 | 3 | $-223 | No |
| 2 | 6 | $-22 | No |
| 3 | 1 | $-107 | No |
| 4 | 4 | $42 | Yes |

### v5 / measured_ob_taker_p90 / $200

- **Execution mode**: taker_market
- **Fees**: T1=26.0bps, T2=70.6bps per side
- **Baseline**: 15tr, PF=0.394, WR=33.3%, P&L=$-45, Exp/Wk=$-10.52, DD=24.1%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.218, Exp/Wk=$-17.08
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -10.5152 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -17.0755 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 24.1 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-6 | No |
| 1 | 3 | $-25 | No |
| 2 | 6 | $-8 | No |
| 3 | 1 | $-11 | No |
| 4 | 4 | $1 | Yes |

### v5 / measured_ob_taker_p90 / $500

- **Execution mode**: taker_market
- **Fees**: T1=27.1bps, T2=89.4bps per side
- **Baseline**: 15tr, PF=0.335, WR=33.3%, P&L=$-132, Exp/Wk=$-30.64, DD=27.5%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.181, Exp/Wk=$-49.85
- **Walk-Forward**: 0/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -30.6413 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -49.8548 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 27.5 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-17 | No |
| 1 | 3 | $-67 | No |
| 2 | 6 | $-31 | No |
| 3 | 1 | $-28 | No |
| 4 | 4 | $-3 | No |

### v5 / measured_ob_taker_p90 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=34.1bps, T2=112.3bps per side
- **Baseline**: 15tr, PF=0.276, WR=26.7%, P&L=$-617, Exp/Wk=$-143.80, DD=31.5%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.143, Exp/Wk=$-233.06
- **Walk-Forward**: 0/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -143.8015 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -233.0602 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 31.5 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-76 | No |
| 1 | 3 | $-294 | No |
| 2 | 6 | $-175 | No |
| 3 | 1 | $-113 | No |
| 4 | 4 | $-39 | No |

### sl7 / measured_ob_maker_p50 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.530, WR=40.0%, P&L=$-35, Exp/Wk=$-8.21, DD=21.6%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.459, Exp/Wk=$-9.92
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -8.2118 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -9.9189 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 21.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-23 | No |
| 2 | 6 | $-3 | No |
| 3 | 1 | $-14 | No |
| 4 | 4 | $8 | Yes |

### sl7 / measured_ob_maker_p50 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.530, WR=40.0%, P&L=$-88, Exp/Wk=$-20.53, DD=21.6%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.459, Exp/Wk=$-24.80
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -20.5296 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -24.7971 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 21.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-9 | No |
| 1 | 3 | $-57 | No |
| 2 | 6 | $-8 | No |
| 3 | 1 | $-36 | No |
| 4 | 4 | $20 | Yes |

### sl7 / measured_ob_maker_p50 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=11.9bps, T2=15.0bps per side
- **Baseline**: 15tr, PF=0.530, WR=40.0%, P&L=$-352, Exp/Wk=$-82.12, DD=21.6%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.459, Exp/Wk=$-99.19
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -82.1185 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -99.1885 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 21.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-37 | No |
| 1 | 3 | $-227 | No |
| 2 | 6 | $-32 | No |
| 3 | 1 | $-145 | No |
| 4 | 4 | $81 | Yes |

### sl7 / measured_ob_maker_p90 / $200

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.498, WR=40.0%, P&L=$-38, Exp/Wk=$-8.96, DD=22.9%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.405, Exp/Wk=$-11.36
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -8.962 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -11.3574 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 22.9 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-23 | No |
| 2 | 6 | $-5 | No |
| 3 | 1 | $-15 | No |
| 4 | 4 | $7 | Yes |

### sl7 / measured_ob_maker_p90 / $500

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.498, WR=40.0%, P&L=$-96, Exp/Wk=$-22.40, DD=22.9%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.405, Exp/Wk=$-28.39
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -22.4049 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -28.3935 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 22.9 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-10 | No |
| 1 | 3 | $-59 | No |
| 2 | 6 | $-12 | No |
| 3 | 1 | $-36 | No |
| 4 | 4 | $18 | Yes |

### sl7 / measured_ob_maker_p90 / $2000

- **Execution mode**: maker_limit
- **Fees**: T1=14.6bps, T2=22.0bps per side
- **Baseline**: 15tr, PF=0.498, WR=40.0%, P&L=$-385, Exp/Wk=$-89.62, DD=22.9%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.405, Exp/Wk=$-113.57
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -89.6198 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -113.574 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 22.9 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-40 | No |
| 1 | 3 | $-234 | No |
| 2 | 6 | $-49 | No |
| 3 | 1 | $-146 | No |
| 4 | 4 | $72 | Yes |

### sl7 / measured_ob_taker_p50 / $200

- **Execution mode**: taker_market
- **Fees**: T1=17.3bps, T2=31.5bps per side
- **Baseline**: 15tr, PF=0.458, WR=40.0%, P&L=$-43, Exp/Wk=$-9.94, DD=24.6%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.341, Exp/Wk=$-13.20
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -9.9432 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -13.2022 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 24.6 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-4 | No |
| 1 | 3 | $-24 | No |
| 2 | 6 | $-7 | No |
| 3 | 1 | $-15 | No |
| 4 | 4 | $6 | Yes |

### sl7 / measured_ob_taker_p50 / $500

- **Execution mode**: taker_market
- **Fees**: T1=17.5bps, T2=36.4bps per side
- **Baseline**: 15tr, PF=0.440, WR=40.0%, P&L=$-112, Exp/Wk=$-26.05, DD=25.4%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.315, Exp/Wk=$-35.20
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -26.0466 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -35.1952 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 25.4 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-11 | No |
| 1 | 3 | $-63 | No |
| 2 | 6 | $-21 | No |
| 3 | 1 | $-37 | No |
| 4 | 4 | $13 | Yes |

### sl7 / measured_ob_taker_p50 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=18.8bps, T2=46.0bps per side
- **Baseline**: 15tr, PF=0.405, WR=40.0%, P&L=$-487, Exp/Wk=$-113.51, DD=27.0%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.269, Exp/Wk=$-157.69
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -113.51 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -157.6863 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 27.0 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-49 | No |
| 1 | 3 | $-260 | No |
| 2 | 6 | $-105 | No |
| 3 | 1 | $-147 | No |
| 4 | 4 | $42 | Yes |

### sl7 / measured_ob_taker_p90 / $200

- **Execution mode**: taker_market
- **Fees**: T1=26.0bps, T2=70.6bps per side
- **Baseline**: 15tr, PF=0.326, WR=33.3%, P&L=$-59, Exp/Wk=$-13.72, DD=31.2%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.189, Exp/Wk=$-19.91
- **Walk-Forward**: 1/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -13.7174 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -19.9057 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 31.2 | <=20% | **FAIL** |
| G6_wf_folds_positive | 1 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-6 | No |
| 1 | 3 | $-29 | No |
| 2 | 6 | $-16 | No |
| 3 | 1 | $-15 | No |
| 4 | 4 | $1 | Yes |

### sl7 / measured_ob_taker_p90 / $500

- **Execution mode**: taker_market
- **Fees**: T1=27.1bps, T2=89.4bps per side
- **Baseline**: 15tr, PF=0.280, WR=33.3%, P&L=$-165, Exp/Wk=$-38.39, DD=34.3%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.159, Exp/Wk=$-56.50
- **Walk-Forward**: 0/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -38.3885 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -56.5025 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 34.3 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-17 | No |
| 1 | 3 | $-77 | No |
| 2 | 6 | $-51 | No |
| 3 | 1 | $-38 | No |
| 4 | 4 | $-3 | No |

### sl7 / measured_ob_taker_p90 / $2000

- **Execution mode**: taker_market
- **Fees**: T1=34.1bps, T2=112.3bps per side
- **Baseline**: 15tr, PF=0.235, WR=26.7%, P&L=$-745, Exp/Wk=$-173.57, DD=38.2%
- **Max Gap**: 6.17d (148 bars)
- **Stress 2x**: 15tr, PF=0.128, Exp/Wk=$-257.73
- **Walk-Forward**: 0/5 folds positive, top1 conc=1.000

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 3.5 | >=10/wk | **FAIL** |
| G2_max_gap_days | 6.17 | <=2.5d | **FAIL** |
| G3_exp_per_week | -173.5748 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -257.7299 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 38.2 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 1 | $-76 | No |
| 1 | 3 | $-331 | No |
| 2 | 6 | $-252 | No |
| 3 | 1 | $-153 | No |
| 4 | 4 | $-39 | No |

## Verdict

**BYBIT — Combinations passing ALL STRICT gates**: 0/24

**Failing combinations**:
  - v5/measured_ob_maker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_maker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc
  - sl7/measured_ob_taker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G5_max_dd_pct, G6_wf_folds_positive, G8_top1_fold_conc

**Maker vs Taker** (v5 config, $200 size):
  p50: maker 15tr Exp/wk=$-4.67 vs taker 15tr Exp/wk=$-6.51
  p90: maker 15tr Exp/wk=$-5.47 vs taker 15tr Exp/wk=$-10.52

**CONCLUSION**: Strategy fails STRICT gates in majority of combinations (24/24) on BYBIT. Cost structure may be prohibitive.

---
*Generated by run_multi_exchange_validation.py at 2026-02-16 20:54*