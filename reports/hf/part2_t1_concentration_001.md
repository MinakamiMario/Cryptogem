# Part 2: T1 Concentration Risk Analysis

## Objective

XL1/USD accounts for 48.3% of T1 P&L ($549 of $1058). This analysis
studies whether the strategy remains viable when top T1 contributors are
excluded, to quantify concentration risk and determine if T1 edge is
dependent on a single coin.

**Date**: 2026-02-16 01:11
**Commit**: 80eebf8
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Fees**: T1=12.5bps/side, T2=23.5bps/side
**Data**: 721 bars (4.3 weeks)
**Runtime**: 28.2s

## Comparison Table: All Variants

| Metric | Baseline (295) | Excl XL1/USD | Excl Top-3 T1 | T2-Only |
|--------|--------|--------|--------|--------|
| Coins (T1+T2) | 96+199=295 | 95+199=294 | 93+199=292 | 0+199=199 |
| Trades | 56 | 53 | 51 | 38 |
| PnL ($) | $3272.13 | $2659.28 | $2373.84 | $2214.08 |
| PF | 2.834 | 2.490 | 2.346 | 2.611 |
| WR (%) | 64.3 | 62.3 | 60.8 | 57.9 |
| Exp/Wk ($) | $762.4382 | $619.6371 | $553.1289 | $515.9011 |
| Tr/Wk | 13.05 | 12.35 | 11.88 | 8.85 |
| DD (%) | 8.6 | 8.6 | 8.8 | 8.4 |
| Max Gap (d) | 2.75 | 2.75 | 2.75 | 2.75 |
| WF (+/5) | 4/5 | 4/5 | 4/5 | 5/5 |
| Fold Conc | 34.18% | 42.56% | 40.21% | 42.38% |
| Stress PF | 2.306 | 2.003 | 1.872 | 2.056 |
| Stress Exp/Wk | $571.4130 | $438.8065 | $377.1001 | $355.9660 |
| HHI | 0.0566 | 0.0570 | 0.0630 | 0.0782 |
| HHI Class | DIVERSIFIED | DIVERSIFIED | DIVERSIFIED | DIVERSIFIED |
| Gates | PASS | PASS | PASS | PASS |

## Per-Variant Gate Details

### Baseline (295) (PASS)

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| G1_trades_per_week | 13.1 | >=0.5/wk | PASS |
| G2_max_gap_days | 2.7500 | <=21d | PASS |
| G3_exp_per_week_mkt | 762.4 | >$0 | PASS |
| G4_exp_per_week_2x | 571.4 | >$0 | PASS |
| G5_max_dd_pct | 8.6300 | <=50% | PASS |
| G6_wf_folds_positive | 4 | >=3/5 | PASS |
| G8_top1_fold_conc | 0.3418 | <0.60 | PASS |

### Excl XL1/USD (PASS)

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| G1_trades_per_week | 12.3 | >=0.5/wk | PASS |
| G2_max_gap_days | 2.7500 | <=21d | PASS |
| G3_exp_per_week_mkt | 619.6 | >$0 | PASS |
| G4_exp_per_week_2x | 438.8 | >$0 | PASS |
| G5_max_dd_pct | 8.6300 | <=50% | PASS |
| G6_wf_folds_positive | 4 | >=3/5 | PASS |
| G8_top1_fold_conc | 0.4256 | <0.60 | PASS |

### Excl Top-3 T1 (PASS)

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| G1_trades_per_week | 11.9 | >=0.5/wk | PASS |
| G2_max_gap_days | 2.7500 | <=21d | PASS |
| G3_exp_per_week_mkt | 553.1 | >$0 | PASS |
| G4_exp_per_week_2x | 377.1 | >$0 | PASS |
| G5_max_dd_pct | 8.7900 | <=50% | PASS |
| G6_wf_folds_positive | 4 | >=3/5 | PASS |
| G8_top1_fold_conc | 0.4021 | <0.60 | PASS |

### T2-Only (PASS)

| Gate | Value | Threshold | Result |
|------|-------|-----------|--------|
| G1_trades_per_week | 8.8500 | >=0.5/wk | PASS |
| G2_max_gap_days | 2.7500 | <=21d | PASS |
| G3_exp_per_week_mkt | 515.9 | >$0 | PASS |
| G4_exp_per_week_2x | 356.0 | >$0 | PASS |
| G5_max_dd_pct | 8.4000 | <=50% | PASS |
| G6_wf_folds_positive | 5 | >=3/5 | PASS |
| G8_top1_fold_conc | 0.4238 | <0.60 | PASS |

## Walk-Forward Detail (5-Fold)

| Fold | Baseline (295) | Excl XL1/USD | Excl Top-3 T1 | T2-Only |
|------|------|------|------|------|
| 0 | 10tr $909 (+) | 10tr $909 (+) | 9tr $751 (+) | 7tr $709 (+) |
| 1 | 13tr $58 (+) | 13tr $58 (+) | 13tr $58 (+) | 9tr $188 (+) |
| 2 | 9tr $-18 (-) | 9tr $-18 (-) | 9tr $-18 (-) | 7tr $80 (+) |
| 3 | 9tr $792 (+) | 8tr $623 (+) | 8tr $623 (+) | 6tr $428 (+) |
| 4 | 15tr $913 (+) | 13tr $547 (+) | 12tr $437 (+) | 9tr $269 (+) |

## HHI Concentration Analysis

The Herfindahl-Hirschman Index (HHI) measures P&L concentration across coins.
HHI uses positive profit attribution (only winning P&L counts).

| Variant | HHI | Interpretation | Coins Active | Top-1 Coin Conc | Top-3 Coin Conc |
|---------|-----|---------------|-------------|----------------|----------------|
| Baseline (295) | 0.0566 | DIVERSIFIED | 41 | 12.5% | 30.6% |
| Excl XL1/USD | 0.0570 | DIVERSIFIED | 40 | 12.8% | 28.4% |
| Excl Top-3 T1 | 0.0630 | DIVERSIFIED | 38 | 13.9% | 30.7% |
| T2-Only | 0.0782 | DIVERSIFIED | 29 | 14.9% | 32.9% |

**HHI thresholds**: <0.10 = diversified, 0.10-0.15 = mildly concentrated, 
0.15-0.25 = moderately concentrated, >0.25 = highly concentrated.

## Per-Variant Top Coin Attribution

### Baseline (295)

**Top 5:**
- XL1/USD: $549.02
- AURA/USD: $486.12
- INIT/USD: $311.41
- SPICE/USD: $275.41
- CVC/USD: $265.74

**Worst 5:**
- GLMR/USD: $-243.29
- PUPS/USD: $-215.17
- MF/USD: $-176.71
- DRV/USD: $-139.32
- SUSHI/USD: $-95.89

### Excl XL1/USD

**Top 5:**
- AURA/USD: $486.12
- INIT/USD: $311.41
- SPICE/USD: $275.41
- CVC/USD: $265.74
- SIGMA/USD: $259.21

**Worst 5:**
- GLMR/USD: $-243.29
- PUPS/USD: $-215.17
- MF/USD: $-176.71
- DRV/USD: $-139.32
- SUSHI/USD: $-95.89

### Excl Top-3 T1

**Top 5:**
- AURA/USD: $486.12
- INIT/USD: $311.41
- SPICE/USD: $275.41
- CVC/USD: $265.74
- SIGMA/USD: $259.21

**Worst 5:**
- GLMR/USD: $-243.29
- PUPS/USD: $-215.17
- MF/USD: $-176.71
- DRV/USD: $-139.32
- SUSHI/USD: $-95.89

### T2-Only

**Top 5:**
- AURA/USD: $486.12
- INIT/USD: $311.41
- SPICE/USD: $275.41
- CVC/USD: $265.74
- SIGMA/USD: $259.21

**Worst 5:**
- GLMR/USD: $-243.29
- PUPS/USD: $-215.17
- MF/USD: $-176.71
- DRV/USD: $-139.32
- SUSHI/USD: $-95.89

## Impact Analysis

**Excl XL1/USD vs Baseline:**
- PnL delta: $-612.85 (-18.7%)
- Trade delta: -3
- PF delta: -0.344
- HHI: 0.0570 vs 0.0566 (worse diversification)
- Gates: PASS (baseline: PASS)

**Excl Top-3 T1 vs Baseline:**
- PnL delta: $-898.29 (-27.5%)
- Trade delta: -5
- PF delta: -0.488
- HHI: 0.0630 vs 0.0566 (worse diversification)
- Gates: PASS (baseline: PASS)

**T2-Only vs Baseline:**
- PnL delta: $-1058.05 (-32.3%)
- Trade delta: -18
- PF delta: -0.223
- HHI: 0.0782 vs 0.0566 (worse diversification)
- Gates: PASS (baseline: PASS)

## Verdict: T1 Concentration Risk

1. **XL1/USD exclusion impact**: $-612.85 (-18.7% of total PnL)
   - Gates: PASS
   - Strategy SURVIVES without XL1/USD

2. **Top-3 T1 exclusion impact**: $-898.29 (-27.5% of total PnL)
   - Gates: PASS
   - Strategy SURVIVES without top-3 T1 coins

3. **T2-only viability**: $2214.08 (67.7% of baseline PnL)
   - Gates: PASS
   - T2 alone IS viable as standalone

**OVERALL**: T1 concentration risk is **MANAGEABLE**. The strategy passes all gates
even without the top-3 T1 contributors. The edge is distributed, not concentrated.

---
*Generated by strategies/hf/screening/run_part2_t1_concentration.py at 2026-02-16 01:11*