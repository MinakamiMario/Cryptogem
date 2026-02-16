# Part 2 -- Hybrid Exclusion Strategy (Agent C5-A1)

**Date**: 2026-02-16 00:57
**Commit**: d689875
**Universe**: T1(100) + T2(216) = 316 coins
**Params**: dev=2.0, tp=8, sl=5, tl=10
**Fees**: T1=12.5bps, T2=23.5bps
**Stress**: 2x fees (T1=25.0bps, T2=47.0bps)
**Runtime**: 30.9s

## Objective

Test a **hybrid exclusion** approach that combines:

1. **Static Core** (12 worst coins): always excluded, high confidence from all prior analyses
2. **Dynamic Layer**: rolling lookback windows (168/336/504 bars) identify ADDITIONAL coins to exclude from the remaining 304
3. **Combined**: static 12 + dynamic N

Compare against: Full 316 (no exclusion), Static 12 only (304), Oracle 21 (295).

### Prior Results

| Approach | Result |
|----------|--------|
| Rolling lookback only (C3-A2) | MARGINAL: 22% oracle retention |
| Expanding window OOS (C4-A2) | NOT_CONFIRMED: exclusion did not help OOS |
| Static 12 persistent (C3-A2) | 6/7 gates (G8 FAIL: fold conc 36.3%) |
| Oracle 21 (full-sample) | 7/7 gates, leader |

**Hypothesis**: Combining the reliable static-12 exclusion with a dynamic rolling layer may capture additional bad coins that emerge over time, potentially recovering some oracle performance without forward-looking bias.

## 1. Reference Configurations (Full Gate Evaluation)

| Config | Coins | Trades | PF | P&L | Exp/Wk | DD% | WF | G8 Conc | Gates |
|--------|-------|--------|----|-----|--------|-----|----|---------| ------|
| Full 316 | 316 | 72 | 1.138 | $370 | $86.07 | 53.1% | 3/5 | 48.6% | 3/7 |
| Static 12 (304) | 304 | 58 | 2.518 | $2403 | $559.17 | 11.8% | 4/5 | 34.0% | 7/7 |
| Oracle 21 (295) | 295 | 56 | 2.834 | $3272 | $761.38 | 8.6% | 4/5 | 34.2% | 7/7 |
| Hybrid best (25excl) | 291 | 47 | 4.112 | $3002 | $698.49 | 7.0% | 5/5 | 35.3% | 6/7 |

### Walk-Forward Fold Details

**Full 316**:
  - Fold 0: 13 trades, P&L=$416 (+)
  - Fold 1: 16 trades, P&L=$-199 (-)
  - Fold 2: 13 trades, P&L=$-499 (-)
  - Fold 3: 15 trades, P&L=$227 (+)
  - Fold 4: 16 trades, P&L=$608 (+)

**Static 12 (304)**:
  - Fold 0: 10 trades, P&L=$732 (+)
  - Fold 1: 14 trades, P&L=$27 (+)
  - Fold 2: 10 trades, P&L=$-48 (-)
  - Fold 3: 10 trades, P&L=$668 (+)
  - Fold 4: 14 trades, P&L=$723 (+)

**Oracle 21 (295)**:
  - Fold 0: 10 trades, P&L=$909 (+)
  - Fold 1: 13 trades, P&L=$58 (+)
  - Fold 2: 9 trades, P&L=$-18 (-)
  - Fold 3: 9 trades, P&L=$792 (+)
  - Fold 4: 15 trades, P&L=$913 (+)

**Hybrid best (25excl)**:
  - Fold 0: 9 trades, P&L=$723 (+)
  - Fold 1: 11 trades, P&L=$241 (+)
  - Fold 2: 7 trades, P&L=$143 (+)
  - Fold 3: 8 trades, P&L=$895 (+)
  - Fold 4: 13 trades, P&L=$533 (+)

## 2. Hybrid Rolling Results

Static 12 always excluded + dynamic layer from rolling lookback.

| Label | Lookback | Segs | Trades | PF | P&L | Exp/Wk | Avg Excl | Dyn Stability |
|-------|----------|------|--------|----|-----|--------|----------|---------------|
| hybrid_s12_lb168 | 1.0wk | 3 | 45 | 2.034 | $1051 | $350.46 | 18 | 0% |
| hybrid_s12_lb336 | 2.0wk | 2 | 28 | 2.528 | $1051 | $525.59 | 22 | 24% |
| hybrid_s12_lb504 | 3.0wk | 1 | 15 | 6.154 | $778 | $777.88 | 25 | 0% |
| pure_dynamic_lb336 | 2.0wk | 2 | 31 | 1.445 | $509 | $254.64 | 18 | 35% |

### Best Hybrid Segment Details

**hybrid_s12_lb504**

| Seg | Bars | Static | Dynamic | Combined | Active | Trades | P&L |
|-----|------|--------|---------|----------|--------|--------|-----|
| 0 | 554-722 | 12 | 13 | 25 | 291 | 15 | $+778 |

### Persistent Dynamic Excludes (>50% of segments)

These coins were dynamically excluded in more than half of all rolling segments:

| Coin | Excl Freq (%) | In Oracle 21? | In Static 12? |
|------|--------------|---------------|---------------|
| ARPA/USD | 100% | no | N/A |
| CAMP/USD | 100% | no | N/A |
| DEEP/USD | 100% | no | N/A |
| DRV/USD | 100% | no | N/A |
| GST/USD | 100% | YES | N/A |
| KOBAN/USD | 100% | no | N/A |
| POLIS/USD | 100% | YES | N/A |
| RARI/USD | 100% | YES | N/A |
| SAMO/USD | 100% | no | N/A |
| SAROS/USD | 100% | no | N/A |
| SGB/USD | 100% | no | N/A |
| SIGMA/USD | 100% | no | N/A |
| SUKU/USD | 100% | YES | N/A |

## 3. Best Hybrid -- Full Gate Evaluation

Combined exclusion list: static 12 + 13 persistent dynamic = 25 total coins excluded.

- In oracle 21: 16 coins
- New (not in oracle): 9 coins ['ARPA/USD', 'CAMP/USD', 'DEEP/USD', 'DRV/USD', 'KOBAN/USD', 'SAMO/USD', 'SAROS/USD', 'SGB/USD', 'SIGMA/USD']

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 10.94 | >= 10 | PASS |
| G2 | Max gap (days) | 1.83 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 698.49 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 545.89 | > $0 | PASS |
| G5 | Max DD% | 7.0 | <= 20% | PASS |
| G6 | WF folds positive | 5/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 35.3% | < 35% | **FAIL** |

**Gate score: 6/7**

- Baseline: trades=47, PF=4.112, P&L=$3002, exp/wk=$698.49, DD=7.0%
- Stress (2x): PF=3.119, P&L=$2346, exp/wk=$545.89
- WF: 5/5 positive
- Fold conc: 35.3%

## 4. Verdict

### **HYBRID_DEGRADES**

Hybrid exclusion degrades performance vs static-12: 6/7 vs 7/7 gates. Dynamic layer is counterproductive.

### Key Comparison

| Approach | Coins Excl | Gates | P&L | PF | Exp/Wk |
|----------|-----------|-------|-----|----| -------|
| Full 316 | 0 | 3/7 | $370 | 1.138 | $86.07 |
| Static 12 (304) | 12 | 7/7 | $2403 | 2.518 | $559.17 |
| Hybrid best (25) | 25 | 6/7 | $3002 | 4.112 | $698.49 |
| Oracle 21 (295) | 21 | 7/7 | $3272 | 2.834 | $761.38 |

### Production Recommendation

Dynamic layer is counterproductive. Use static-12 exclusion only.

---
*Generated by run_part2_hybrid_exclusion.py at 2026-02-16 00:57*