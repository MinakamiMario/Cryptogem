# Part 2: T1-Only Test -- H20 VWAP_DEVIATION

**Date**: 2026-02-16 00:13
**Commit**: e96951c
**Universe**: T1 only (100 coins)
**Data**: 722 bars (4.3 weeks)
**Fee**: MEXC T1 = 12.5 bps/side
**Stress**: 2x = 25.0 bps/side
**Runtime**: 10.5s

## Context

DualConfirm at 4H had near-zero edge on T1 (liquid coins).
H20 VWAP_DEVIATION is microstructure-based -- does it work differently on T1?

Key comparisons:
- Full 316 coins: PF=1.138, DD=53%, WF=3/5 (FAIL)
- 135 coins (alphabetical): PF=1.85, WF=5/5 (PASS)
- T1 fee is much lower (12.5bps vs 23.5bps per side)

## Head-to-Head: v5 (tp=8) vs tp=10

| Metric | v5 (tp=8) | tp=10 | Winner |
|--------|-----------|-------|--------|
| Trades | 21 | 21 | tie |
| PnL ($) | $608.43 | $430.86 | v5 |
| PF | 1.875 | 1.532 | v5 |
| Exp/Wk ($) | $141.5748 | $100.2564 | v5 |
| DD (%) | 24.2% | 28.1% | v5 |
| WF Folds | 3/5 | 2/5 | v5 |
| Stress Exp/Wk | $110.6264 | $71.3645 | v5 |

## v5_tp8

### Baseline Metrics

| Metric | Value |
|--------|-------|
| Trades | 21 |
| PnL | $608.43 |
| PF | 1.875 |
| WR | 66.7% |
| Expectancy | $28.9731 |
| Exp/Week | $141.5748 |
| Trades/Week | 4.89 |
| Max DD | 24.2% |
| Fee Drag | 7.8% |
| Max Gap | 4.83d (116 bars) |

### Walk-Forward (5-fold)

**Result: 3/5** | Top-1 fold conc: 66.6%

| Fold | Trades | PnL | Positive |
|------|--------|-----|----------|
| 0 | 3 | $199.84 | YES |
| 1 | 5 | $-224.38 | NO |
| 2 | 2 | $-97.46 | NO |
| 3 | 5 | $123.37 | YES |
| 4 | 6 | $644.84 | YES |

### Stress 2x

PF=1.658 | Exp/Wk=$110.6264 | Trades=21 | DD=25.9%

### Coin Breakdown

- Coins with trades: 15
- Top-1 coin concentration: 47.7%
- Top-3 coin concentration: 74.8%
- Top 5: XL1/USD ($468), GHIBLI/USD ($158), XAN/USD ($108), KOBAN/USD ($85), REKT/USD ($49)
- Worst 3: TITCOIN/USD ($-115), MXC/USD ($-97), GST/USD ($-92)

### Gate Verdicts

| Gate | Value | Threshold | Pass |
|------|-------|-----------|------|
| G1_trades_per_week | 4.89 | >=0.5/wk | PASS |
| G2_max_gap_days | 4.83 | <=21d | PASS |
| G3_exp_per_week_mkt | 141.5748 | >$0 | PASS |
| G4_exp_per_week_2x | 110.6264 | >$0 | PASS |
| G5_max_dd_pct | 24.17 | <=50% | PASS |
| G6_wf_folds_positive | 3 | >=3/5 | PASS |
| G8_top1_fold_conc | 0.6661 | <0.60 | **FAIL** |

**VERDICT: FAIL**
Failed gates: G8_top1_fold_conc

## v5_tp10

### Baseline Metrics

| Metric | Value |
|--------|-------|
| Trades | 21 |
| PnL | $430.86 |
| PF | 1.532 |
| WR | 61.9% |
| Expectancy | $20.5173 |
| Exp/Week | $100.2564 |
| Trades/Week | 4.89 |
| Max DD | 28.1% |
| Fee Drag | 8.1% |
| Max Gap | 4.83d (116 bars) |

### Walk-Forward (5-fold)

**Result: 2/5** | Top-1 fold conc: 69.8%

| Fold | Trades | PnL | Positive |
|------|--------|-----|----------|
| 0 | 3 | $282.17 | YES |
| 1 | 5 | $-224.38 | NO |
| 2 | 2 | $-97.46 | NO |
| 3 | 5 | $-97.89 | NO |
| 4 | 6 | $652.25 | YES |

### Stress 2x

PF=1.366 | Exp/Wk=$71.3645 | Trades=21 | DD=30.0%

### Coin Breakdown

- Coins with trades: 15
- Top-1 coin concentration: 53.0%
- Top-3 coin concentration: 82.5%
- Top 5: XL1/USD ($548), GHIBLI/USD ($203), XAN/USD ($102), REKT/USD ($85), SBR/USD ($43)
- Worst 3: ELX/USD ($-206), TITCOIN/USD ($-120), MXC/USD ($-101)

### Gate Verdicts

| Gate | Value | Threshold | Pass |
|------|-------|-----------|------|
| G1_trades_per_week | 4.89 | >=0.5/wk | PASS |
| G2_max_gap_days | 4.83 | <=21d | PASS |
| G3_exp_per_week_mkt | 100.2564 | >$0 | PASS |
| G4_exp_per_week_2x | 71.3645 | >$0 | PASS |
| G5_max_dd_pct | 28.15 | <=50% | PASS |
| G6_wf_folds_positive | 2 | >=3/5 | **FAIL** |
| G8_top1_fold_conc | 0.698 | <0.60 | **FAIL** |

**VERDICT: FAIL**
Failed gates: G6_wf_folds_positive, G8_top1_fold_conc

## Conclusion

- v5 (tp=8): FAIL -- 21tr PF=1.875 Exp/wk=$141.5748
- tp=10: FAIL -- 21tr PF=1.532 Exp/wk=$100.2564

T1 coins have lower fees (12.5bps vs ~23.5bps) but also fewer microstructure
dislocations. The question is whether the fee advantage compensates.

---
*Generated at 2026-02-16 00:13*