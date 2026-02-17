# Part 2: Execution Realism Upgrade (P0-3) -- BUGFIX v002

**Date**: 2026-02-16 01:42
**Agent**: C8-B
**Commit**: 1787377
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Data**: 721 bars (4.3 weeks)
**Runtime**: 28.8s

## Bugfix Note (v002)

**Bug in v001**: `compute_max_gap()` used `entry_bar` for inter-trade gaps and
end-gap computation. This overstated the max gap because trades occupy bars
[entry_bar, exit_bar]. The correct gap between consecutive trades is
`next_entry_bar - prev_exit_bar`, and the end gap is `total_bars - last_exit_bar`.

**Impact**: G2 was reported as 2.75d (FAIL) in v001. Corrected value is ~1.5d (PASS).

## Objective

Test strategy resilience under 3 progressively more realistic execution regimes:
1. **Market Conservative (P90)**: Wider spreads+slippage (P90 instead of P50)
2. **Hybrid Realistic**: Blended maker/taker fills (60/40 entry, 30/70 exit)
3. **Adverse Selection**: Winners get 5-10bps extra cost (worse fills on profits)

STRICT gate thresholds: G1>=10 trades/wk, G2<=2.5d gap, G3/G4>$0 exp/wk,
G5<=20% DD, G6>=4/5 WF folds, G8<35% fold concentration.

## Summary Comparison

| Regime | T1 bps | T2 bps | Trades | PF | P&L | Exp/Wk | DD% | WF | Fold Conc | Gates |
|--------|--------|--------|--------|----|-----|--------|-----|----|-----------|----|
| baseline_p50 | 12.5 | 23.5 | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.342 | **7/7 PASS** |
| market_conservative_p90 | 15.6 | 41.4 | 56 | 2.465 | $2705 | $630.31 | 11.5 | 3/5 | 0.348 | 6/7 FAIL |
| hybrid_realistic | 8.0 | 19.0 | 56 | 2.968 | $3467 | $807.86 | 8.4 | 4/5 | 0.341 | **7/7 PASS** |
| adverse_selection_5bps | 12.5 | 23.5 | 56 | 2.778 | $3173 | $739.35 | 8.8 | 4/5 | 0.343 | **7/7 PASS** |
| adverse_selection_10bps | 12.5 | 23.5 | 56 | 2.720 | $3074 | $716.26 | 9.2 | 4/5 | 0.345 | **7/7 PASS** |

## Regime: baseline_p50

**Description**: MEXC taker P50 (reference baseline)

- Fees: T1=12.5 bps, T2=23.5 bps per side
- Baseline: 56tr, PF=2.834, WR=64.3%, P&L=$3272, Exp/Wk=$762.44, DD=8.6%
- Max Gap: 1.42d (34 bars)
- Stress 2x: 56tr, PF=2.306, Exp/Wk=$571.41
- Walk-Forward: 4/5 folds positive

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 762.4382 | >$0 | PASS |
| G4_stress_exp_per_week | 571.413 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.6 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3418 | <0.35 | PASS |

**Walk-Forward Fold Details**:

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $909 | Yes |
| 1 | 13 | $58 | Yes |
| 2 | 9 | $-18 | No |
| 3 | 9 | $792 | Yes |
| 4 | 15 | $913 | Yes |

## Regime: market_conservative_p90

**Description**: MEXC taker P90 spread+slippage

- Fees: T1=15.6 bps, T2=41.4 bps per side
- Baseline: 56tr, PF=2.465, WR=64.3%, P&L=$2705, Exp/Wk=$630.31, DD=11.5%
- Max Gap: 1.42d (34 bars)
- Stress 2x: 56tr, PF=1.777, Exp/Wk=$360.44
- Walk-Forward: 3/5 folds positive

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 630.3079 | >$0 | PASS |
| G4_stress_exp_per_week | 360.4364 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 11.5 | <=20% | PASS |
| G6_wf_folds_positive | 3 | >=4/5 | **FAIL** |
| G8_top1_fold_conc | 0.3484 | <0.35 | PASS |

**Walk-Forward Fold Details**:

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $839 | Yes |
| 1 | 13 | $-16 | No |
| 2 | 9 | $-72 | No |
| 3 | 9 | $737 | Yes |
| 4 | 15 | $832 | Yes |

## Regime: hybrid_realistic

**Description**: Hybrid: entry 60%maker+40%taker, exit 30%maker+70%taker

- Fees: T1=8.0 bps, T2=19.0 bps per side
- Baseline: 56tr, PF=2.968, WR=64.3%, P&L=$3467, Exp/Wk=$807.86, DD=8.4%
- Max Gap: 1.42d (34 bars)
- Stress 2x: 56tr, PF=2.522, Exp/Wk=$651.67
- Walk-Forward: 4/5 folds positive

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 807.8633 | >$0 | PASS |
| G4_stress_exp_per_week | 651.6695 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.4 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3413 | <0.35 | PASS |

**Walk-Forward Fold Details**:

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $932 | Yes |
| 1 | 13 | $82 | Yes |
| 2 | 9 | $-1 | No |
| 3 | 9 | $812 | Yes |
| 4 | 15 | $946 | Yes |

## Regime: adverse_selection_5bps

**Description**: Adverse selection: winners penalized 5bps/side each way

- Fees: T1=12.5 bps, T2=23.5 bps per side
- Baseline: 56tr, PF=2.778, WR=62.5%, P&L=$3173, Exp/Wk=$739.35, DD=8.8%
- Max Gap: 1.42d (34 bars)
- Stress 2x: 56tr, PF=2.255, Exp/Wk=$550.38
- Walk-Forward: 4/5 folds positive
- Adverse penalty: 5bps/side each way
- Total penalty extracted: $99.10 from 36 winners

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 739.348 | >$0 | PASS |
| G4_stress_exp_per_week | 550.3761 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 8.8 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3427 | <0.35 | PASS |

**Walk-Forward Fold Details**:

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $892 | Yes |
| 1 | 13 | $45 | Yes |
| 2 | 9 | $-24 | No |
| 3 | 9 | $777 | Yes |
| 4 | 15 | $888 | Yes |

## Regime: adverse_selection_10bps

**Description**: Adverse selection: winners penalized 10bps/side each way

- Fees: T1=12.5 bps, T2=23.5 bps per side
- Baseline: 56tr, PF=2.720, WR=62.5%, P&L=$3074, Exp/Wk=$716.26, DD=9.2%
- Max Gap: 1.42d (34 bars)
- Stress 2x: 56tr, PF=2.202, Exp/Wk=$529.34
- Walk-Forward: 4/5 folds positive
- Adverse penalty: 10bps/side each way
- Total penalty extracted: $198.19 from 36 winners

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_trades_per_week | 13.05 | >=10/wk | PASS |
| G2_max_gap_days | 1.42 | <=2.5d | PASS |
| G3_exp_per_week | 716.2577 | >$0 | PASS |
| G4_stress_exp_per_week | 529.3392 | >$0 (stress 2x) | PASS |
| G5_max_dd_pct | 9.2 | <=20% | PASS |
| G6_wf_folds_positive | 4 | >=4/5 | PASS |
| G8_top1_fold_conc | 0.3453 | <0.35 | PASS |

**Walk-Forward Fold Details**:

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $874 | Yes |
| 1 | 13 | $33 | Yes |
| 2 | 9 | $-30 | No |
| 3 | 9 | $762 | Yes |
| 4 | 15 | $862 | Yes |

## Sensitivity: Expectancy vs. Fill-Rate Impact

| Regime | Avg Cost/Side (bps) | Exp/Trade | Exp/Wk | Fill-Rate Equiv |
|--------|---------------------|-----------|--------|-----------------|
| baseline_p50 | 18.0 | $58.43 | $762.44 | 100.0% of baseline |
| market_conservative_p90 | 28.5 | $48.30 | $630.31 | 82.7% of baseline |
| hybrid_realistic | 13.5 | $61.91 | $807.86 | 106.0% of baseline |
| adverse_selection_5bps | 18.0 | $56.66 | $739.35 | 97.0% of baseline |
| adverse_selection_10bps | 18.0 | $54.89 | $716.26 | 93.9% of baseline |

## Adverse Selection Impact

| Penalty | Winners Affected | Total Penalty | PF | P&L | Exp/Wk | vs Baseline |
|---------|-----------------|---------------|----|----|--------|-------------|
| 5bps | 36 | $99 | 2.778 | $3173 | $739.35 | -99 |
| 10bps | 36 | $198 | 2.720 | $3074 | $716.26 | -198 |

## Verdict

**Regimes passing ALL STRICT gates**: baseline_p50, hybrid_realistic, adverse_selection_5bps, adverse_selection_10bps

**Regimes failing**: market_conservative_p90
  - market_conservative_p90: fails G6_wf_folds_positive

**Expectancy degradation by regime**:
  - baseline_p50: $762.44/wk (+0.0% vs baseline)
  - market_conservative_p90: $630.31/wk (-17.3% vs baseline)
  - hybrid_realistic: $807.86/wk (+6.0% vs baseline)
  - adverse_selection_5bps: $739.35/wk (-3.0% vs baseline)
  - adverse_selection_10bps: $716.26/wk (-6.1% vs baseline)

**Bugfix impact (v002 vs v001)**:
  - v001: G2=2.75d (FAIL) -- used entry_bar for gap computation
  - v002: G2 corrected using exit_bar -- expected ~1.5d (PASS)

**CONCLUSION**: Strategy fails STRICT gates under realistic execution. STRICT thresholds are very demanding. Review gate calibration.

---
*Generated by strategies/hf/screening/run_part2_exec_realism_002.py at 2026-02-16 01:42*