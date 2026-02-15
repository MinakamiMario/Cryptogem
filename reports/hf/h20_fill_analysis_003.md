# H20 VWAP_DEVIATION Fill Model Analysis (003)

**Date**: 2026-02-15 23:38
**Commit**: da5db72
**Universe**: T1(100) + T2(216), 722 bars (4.3 wk)
**Fees**: MEXC Market (T1=12.5bps, T2=23.5bps)
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 29.7s

## Head-to-Head: v5 (tp=8) vs tp=10

| Metric | v5 (tp=8) | tp=10 | Delta | Winner |
|--------|-----------|-------|-------|--------|
| Trades | 72 | 72 | +0 | v5 |
| PnL ($) | 369.91 | 232.99 | -136.92 | v5 |
| PF | 1.14 | 1.08 | -0.05 | v5 |
| WR (%) | 47.22 | 44.44 | -2.78 | v5 |
| Exp/Week ($) | 86.07 | 54.21 | -31.86 | v5 |
| DD (%) | 53.11 | 52.44 | -0.67 | tp=10 |
| Fee Drag (%) | 17.44 | 17.33 | -0.11 | tp=10 |
| WF Folds | 3 | 3 | +0 | v5 |
| Composite Score | 51.64 | 32.53 | -19.12 | v5 |
| Stress PF | 0.95 | 0.90 | -0.05 | v5 |
| Stress Exp/Wk ($) | -32.74 | -64.56 | -31.82 | v5 |

## v5_baseline_tp8

Baseline: 72tr PF=1.138 WR=47.2% PnL=$369.91 Exp/Wk=$86.07
WF: 3/5 | Score: 51.6

### Fill Model (T1)

| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |
|------|-------|--------|---------|------------|-------|
| market | 100% | 72 | $777.86 | $181.00 | $407.95 |
| limit_moderate | 72% | 52 | $-1190.24 | $-276.95 | $-1560.15 |
| limit_conservative | 55% | 40 | $-1607.26 | $-373.99 | $-1977.17 |
| hybrid_optimistic | 90% | 65 | $109.05 | $25.37 | $-260.87 |
| hybrid_conservative | 85% | 61 | $-478.68 | $-111.38 | $-848.59 |

### Fill Model (T2)

| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |
|------|-------|--------|---------|------------|-------|
| market | 100% | 72 | $232.85 | $54.18 | $-137.06 |
| limit_moderate | 72% | 52 | $-1251.48 | $-291.20 | $-1621.39 |
| limit_conservative | 55% | 40 | $-1670.81 | $-388.77 | $-2040.72 |
| hybrid_optimistic | 90% | 65 | $-161.62 | $-37.61 | $-531.54 |
| hybrid_conservative | 85% | 61 | $-729.63 | $-169.77 | $-1099.54 |

### Stress 2x: PF=0.949 Exp/Wk=$-32.74 DD=62.2%

## tp10_variant

Baseline: 72tr PF=1.085 WR=44.4% PnL=$232.99 Exp/Wk=$54.21
WF: 3/5 | Score: 32.5

### Fill Model (T1)

| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |
|------|-------|--------|---------|------------|-------|
| market | 100% | 72 | $624.93 | $145.41 | $391.95 |
| limit_moderate | 72% | 52 | $-1353.34 | $-314.90 | $-1586.33 |
| limit_conservative | 55% | 40 | $-1778.10 | $-413.74 | $-2011.09 |
| hybrid_optimistic | 90% | 65 | $-31.85 | $-7.41 | $-264.84 |
| hybrid_conservative | 85% | 61 | $-763.97 | $-177.77 | $-996.96 |

### Fill Model (T2)

| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |
|------|-------|--------|---------|------------|-------|
| market | 100% | 72 | $98.03 | $22.81 | $-134.96 |
| limit_moderate | 72% | 52 | $-1413.00 | $-328.79 | $-1645.99 |
| limit_conservative | 55% | 40 | $-1840.15 | $-428.18 | $-2073.13 |
| hybrid_optimistic | 90% | 65 | $-293.13 | $-68.21 | $-526.12 |
| hybrid_conservative | 85% | 61 | $-1008.82 | $-234.74 | $-1241.80 |

### Stress 2x: PF=0.902 Exp/Wk=$-64.56 DD=61.5%

## Verdict

**Winner: v5 baseline (tp=8)** (scores: v5=51.6, tp10=32.5)

Fill model impact summary:
- **v5_baseline_tp8**: base=$370, best=market ($778), worst=limit_conservative ($-1607)
- **tp10_variant**: base=$233, best=market ($625), worst=limit_conservative ($-1778)

---
*Generated at 2026-02-15 23:38*