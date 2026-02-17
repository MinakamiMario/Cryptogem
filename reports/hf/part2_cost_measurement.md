# Part 2: Execution Cost Measurement (P0-B)

**Datum**: 2026-02-16 09:51
**Agent**: P0-B | **Commit**: d617e6e
**Universum**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signaal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Data**: 721 bars (4.3 weken) | **Runtime**: 61.1s

## Doel

Meet echte all-in execution costs per trade uit candle data en vergelijk
met het Kaiko-gekalibreerde v2 model.

## 1. Baseline Backtest

- Trades: 56 | P&L: $3272.13 | PF: 2.834 | WR: 64.3% | Exp/wk: $762.44

## 2. Gemeten Cost Distributie ($200 trade size)

### ALL (56 trades)

| Component | P10 | P25 | P50 | P75 | P90 | P95 | P99 | Mean |
|-----------|-----|-----|-----|-----|-----|-----|-----|------|
| spread_bps | 81.63 | 185.83 | 723.02 | 1194.89 | 1752.62 | 2493.2 | 3260.0 | 831.55 |
| slippage_bps | 8.01 | 21.4 | 58.52 | 143.58 | 260.27 | 436.55 | 766.89 | 104.13 |
| total_per_side_bps | 147.68 | 351.81 | 802.98 | 1380.31 | 1935.66 | 2568.15 | 3350.05 | 945.68 |
| fill_rate | 0.07 | 0.33 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.74 |
| bar_volume_usd | 73.0 | 327.0 | 1729.0 | 4673.0 | 18089.0 | 32577.0 | 41115.0 | 5421.75 |

### TIER1 (18 trades)

| Component | P10 | P25 | P50 | P75 | P90 | P95 | P99 | Mean |
|-----------|-----|-----|-----|-----|-----|-----|-----|------|
| spread_bps | 112.35 | 157.17 | 781.94 | 1480.14 | 2524.47 | 3260.0 | 3260.0 | 956.25 |
| slippage_bps | 21.4 | 26.89 | 69.69 | 137.78 | 205.82 | 293.01 | 293.01 | 86.58 |
| total_per_side_bps | 211.45 | 351.81 | 816.99 | 1511.55 | 2568.15 | 3350.05 | 3350.05 | 1052.83 |
| fill_rate | 0.09 | 0.24 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.69 |
| bar_volume_usd | 85.0 | 239.0 | 1503.0 | 7214.0 | 24773.0 | 30456.0 | 30456.0 | 5270.83 |

### TIER2 (38 trades)

| Component | P10 | P25 | P50 | P75 | P90 | P95 | P99 | Mean |
|-----------|-----|-----|-----|-----|-----|-----|-----|------|
| spread_bps | 66.46 | 185.83 | 723.02 | 1142.36 | 1751.93 | 2392.37 | 2493.2 | 772.48 |
| slippage_bps | 6.2 | 12.56 | 47.39 | 147.02 | 270.83 | 722.53 | 766.89 | 112.45 |
| total_per_side_bps | 115.78 | 345.01 | 802.98 | 1299.38 | 1935.66 | 2532.95 | 2581.39 | 894.93 |
| fill_rate | 0.06 | 0.39 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.76 |
| bar_volume_usd | 60.0 | 390.0 | 1744.0 | 4148.0 | 18089.0 | 35656.0 | 41115.0 | 5493.24 |

## 3. Calm vs Volatile Split

### CALM (28 trades)

- Spread: 694.9 bps | Slippage: 101.2 bps | Total: 806.1 bps | Fill: 0.637

### VOLATILE (28 trades)

- Spread: 968.2 bps | Slippage: 107.1 bps | Total: 1085.3 bps | Fill: 0.837

## 4. v3 (gemeten) vs v2 (Kaiko-calibrated)

| Component | v2 T1 | v3 T1 P50 | Delta | v2 T2 | v3 T2 P50 | Delta |
|-----------|-------|-----------|-------|-------|-----------|-------|
| spread_bps | 1.7 | 781.9 | +780.2 | 9.2 | 723.0 | +713.8 |
| slippage_bps | 0.8 | 69.7 | +68.9 | 4.3 | 47.4 | +43.1 |
| exchange_fee_bps | 10.0 | 10.0 | +0.0 | 10.0 | 10.0 | +0.0 |
| total_per_side_bps | 12.5 | 817.0 | +804.5 | 23.5 | 803.0 | +779.5 |

## 5. Trade-Size Sensitivity

| Size | P50 Spread | P50 Slippage | P50 Total/Side | P50 Fill Rate |
|------|-----------|--------------|----------------|---------------|
| $100 | 723.02 | 41.38 | 789.85 | 1.0 |
| $200 | 723.02 | 58.52 | 802.98 | 1.0 |
| $500 | 723.02 | 92.53 | 821.38 | 0.69 |
| $1000 | 723.02 | 130.86 | 828.18 | 0.35 |
| $2000 | 723.02 | 185.06 | 914.02 | 0.17 |

## 6. Gate Evaluatie met Gemeten Fees

| Regime | T1 bps | T2 bps | Trades | PF | Exp/Wk | WF | Gates |
|--------|--------|--------|--------|----|--------|----|----|
| v2_baseline_p50 | 12.5 | 23.5 | 56 | 2.834 | $762.44 | 4/5 | **7/7 PASS** |
| measured_p50 | 861.6 | 780.4 | 56 | 0.000 | $-904.11 | 0/5 | 2/7 FAIL |
| measured_p90 | 2740.3 | 2032.7 | 19 | 0.000 | $-928.54 | 0/5 | 0/7 FAIL |

### v2_baseline_p50

| Gate | Waarde | Drempel | Verdict |
|------|--------|---------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 762.4382 | >$0 | PASS |
| G4_stress_exp_per_week | 571.413 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.6 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3418 | <0.35 | PASS |

### measured_p50

| Gate | Waarde | Drempel | Verdict |
|------|--------|---------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | -904.1134 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -928.1591 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 194.0 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

### measured_p90

| Gate | Waarde | Drempel | Verdict |
|------|--------|---------|---------|
| G1_trades_per_week | 4.43 | >=10/wk | **FAIL** |
| G2_max_gap_days | 17.54 | <=2.5d | **FAIL** |
| G3_exp_per_week | -928.5391 | >$0 | **FAIL** |
| G4_stress_exp_per_week | -959.0033 | >$0 (stress 2x) | **FAIL** |
| G5_max_dd_pct | 199.2 | <=20% | **FAIL** |
| G6_wf_folds_positive | 0 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 1.0 | <0.35 | **FAIL** |

## 7. Coin Flip-List

30 trades flippen van winnaar naar verliezer:

| Pair | Bar | v2 PnL | Cost/Side | Adj PnL | Reden |
|------|-----|--------|-----------|---------|-------|
| REKT/USD | 73 | $154.80 | 817.0bps | $-179.87 | PROFIT TARGET |
| BTT/USD | 256 | $1.51 | 211.4bps | $-78.62 | TIME MAX |
| SBR/USD | 290 | $43.75 | 1078.9bps | $-390.60 | TIME MAX |
| BANANAS31/USD | 330 | $8.04 | 147.7bps | $-47.72 | TIME MAX |
| ELX/USD | 496 | $151.37 | 768.4bps | $-156.12 | PROFIT TARGET |
| DOGS/USD | 505 | $39.30 | 1922.4bps | $-774.07 | TIME MAX |
| XL1/USD | 570 | $166.13 | 2568.2bps | $-974.82 | PROFIT TARGET |
| XL1/USD | 596 | $178.99 | 1120.9bps | $-354.16 | PROFIT TARGET |
| XAN/USD | 612 | $126.63 | 263.2bps | $-1.64 | TIME MAX |
| BTT/USD | 650 | $7.98 | 511.9bps | $-254.24 | TIME MAX |
| MEME/USD | 665 | $8.40 | 424.3bps | $-208.48 | TIME MAX |
| KOBAN/USD | 719 | $219.69 | 3350.1bps | $-1750.73 | PROFIT TARGET |
| XYO/USD | 89 | $33.01 | 476.8bps | $-163.89 | TIME MAX |
| BLZ/USD | 112 | $10.35 | 815.3bps | $-337.04 | TIME MAX |
| TOKEN/USD | 134 | $164.76 | 1169.6bps | $-358.15 | PROFIT TARGET |
| SIGMA/USD | 165 | $177.14 | 1701.9bps | $-646.18 | PROFIT TARGET |
| NYM/USD | 166 | $190.45 | 1281.8bps | $-473.15 | PROFIT TARGET |
| ALPHA/USD | 187 | $83.36 | 542.1bps | $-200.65 | TIME MAX |
| NOBODY/USD | 215 | $208.30 | 1411.9bps | $-592.55 | PROFIT TARGET |
| AURA/USD | 269 | $20.31 | 159.4bps | $-59.75 | TIME MAX |
| ... +10 meer | | | | | |

## 8. Breakeven Analyse

Breakeven fee multiplier: **6.5x**

| Mult | T1 bps | T2 bps | Trades | PF | Exp/Wk | OK? |
|------|--------|--------|--------|----|--------|-----|
| 1.0x | 12.5 | 23.5 | 56 | 2.834 | $762.44 | Ja |
| 1.5x | 18.8 | 35.2 | 56 | 2.553 | $663.30 | Ja |
| 2.0x | 25.0 | 47.0 | 56 | 2.306 | $571.41 | Ja |
| 2.5x | 31.2 | 58.8 | 56 | 2.084 | $486.20 | Ja |
| 3.0x | 37.5 | 70.5 | 56 | 1.884 | $407.15 | Ja |
| 3.5x | 43.8 | 82.2 | 56 | 1.707 | $333.77 | Ja |
| 4.0x | 50.0 | 94.0 | 56 | 1.548 | $265.63 | Ja |
| 4.5x | 56.2 | 105.8 | 56 | 1.408 | $202.31 | Ja |
| 5.0x | 62.5 | 117.5 | 56 | 1.283 | $143.44 | Ja |
| 5.5x | 68.8 | 129.2 | 56 | 1.171 | $88.67 | Ja |
| 6.0x | 75.0 | 141.0 | 56 | 1.072 | $37.68 | Ja |
| 6.5x | 81.2 | 152.8 | 56 | 0.982 | $-9.81 | **Nee** |

## Verdict

**v3 gemeten costs zijn HOGER dan v2 Kaiko-model** (+3317%)
  - v2 T2 total: 23.5 bps/side
  - v3 T2 P50:   803.0 bps/side

- v2_baseline_p50: 7/7 gates PASS
- measured_p50: 2/7 gates FAIL (G3_exp_per_week,G4_stress_exp_per_week,G5_max_dd_pct,G6_wf_folds_positive,G8_top1_fold_conc)
- measured_p90: 0/7 gates FAIL (G1_trades_per_week,G2_max_gap_days,G3_exp_per_week,G4_stress_exp_per_week,G5_max_dd_pct,G6_wf_folds_positive,G8_top1_fold_conc)

**Breakeven fee multiplier**: 6.5x
**Coin flips**: 30 trades veranderen van winnaar naar verliezer

**CONCLUSIE**: Strategie faalt zelfs bij gemeten P50 costs. Execution costs zijn een HOOG risico.

---
*Gegenereerd op 2026-02-16 09:51*