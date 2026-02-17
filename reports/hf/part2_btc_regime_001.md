# Part 2 -- BTC Regime Analysis (Agent C5-A3)

**Date**: 2026-02-16 00:59
**Commit**: d689875
**Universe**: T1(96) + T2(199) = 295 coins (295-coin universe)
**Params**: dev=2.0, tp=8, sl=5, tl=10
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x: T1=25.0bps, T2=47.0bps)
**Runtime**: 28.2s

## 1. BTC Regime Definition

- **SMA Period**: 48 bars (2 days)
- **Return Period**: 48 bars
- **Return Threshold**: +/-1%
- **BTC Key**: BTC/USD (fetched) (719 bars)

| Regime | Definition |
|--------|-----------|
| BULL | BTC close > SMA(48) AND 48-bar return > +1% |
| BEAR | BTC close < SMA(48) AND 48-bar return < -1% |
| SIDEWAYS | Everything else |

## 2. Regime Duration

| Regime | Bars | Days | % of Time |
|--------|------|------|-----------|
| BULL | 118 | 4.9 | 17.5% |
| BEAR | 338 | 14.1 | 50.2% |
| SIDEWAYS | 217 | 9.0 | 32.2% |
| *Total classifiable* | 673 | 28.0 | 100% |

**Dominant regime**: BEAR (50.2%)

## 3. Baseline Summary

- Trades: 56
- P&L: $3272.13
- PF: 2.834
- WR: 64.3%
- Exp/week: $762.44

## 4. Per-Regime Performance

| Regime | Trades | Wins | WR% | Total P&L | Avg P&L | PF | Median P&L |
|--------|--------|------|-----|-----------|---------|-----|------------|
| BULL | 13 | 10 | 76.9% | $+1104.39 | $+84.95 | 5.65 | $+46.96 |
| BEAR | 25 | 13 | 52.0% | $+584.60 | $+23.38 | 1.57 | $+7.98 |
| SIDEWAYS | 18 | 13 | 72.2% | $+1583.13 | $+87.95 | 4.08 | $+164.76 |

### Worst and Best Trades per Regime

| Regime | Worst Trade | Worst P&L | Best Trade | Best P&L |
|--------|------------|-----------|------------|----------|
| BULL | DRV/USD (TIME MAX) | $-139.32 | INIT/USD (PROFIT TARGET) | $+311.41 |
| BEAR | PUPS/USD (FIXED STOP) | $-215.17 | SPICE/USD (PROFIT TARGET) | $+275.41 |
| SIDEWAYS | GLMR/USD (FIXED STOP) | $-243.29 | CVC/USD (PROFIT TARGET) | $+265.74 |

## 5. Walk-Forward by Regime

| Fold | BULL Trades | BULL P&L | BEAR Trades | BEAR P&L | SIDEWAYS Trades | SIDEWAYS P&L | Total P&L |
|------|--------|---------|--------|---------|--------|---------|-----------|
| 0 | 2 | $+335.18 | 4 | $+348.39 | 4 | $+225.52 | $+909.08 |
| 1 | 3 | $+15.49 | 6 | $-81.88 | 4 | $+123.92 | $+57.53 |
| 2 | 0 | $+0.00 | 7 | $-164.35 | 2 | $+146.77 | $-17.57 |
| 3 | 2 | $-120.68 | 2 | $+305.02 | 5 | $+608.10 | $+792.44 |
| 4 | 6 | $+576.88 | 6 | $+122.72 | 3 | $+213.83 | $+913.43 |

## 6. Full Baseline Gate Evaluation

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.05 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 762.44 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 571.41 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 34.2% | < 35% | PASS |

**Metrics**: 56 trades, PF=2.834, exp/wk=$762.44, DD=8.6%
**Stress**: PF=2.306, exp/wk=$571.41
**Walk-Forward**: 4/5 folds positive

## 7. Conditional Filter Tests

### No BTC BEAR trades

- Allowed regimes: ['BULL', 'SIDEWAYS']
- Trades kept: 31, removed: 25

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 7.22 | >= 10 | **FAIL** |
| G2 | Max gap (days) | 4.46 | <= 2.5 | **FAIL** |
| G3 | Exp/week (market) | 626.22 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 502.04 | > $0 | PASS |
| G5 | Max DD% | 5.4 | <= 20% | PASS |
| G6 | WF folds positive | 5/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 37.2% | < 35% | **FAIL** |

**Metrics**: 31 trades, PF=4.576, exp/wk=$626.22, DD=5.4%
**Stress**: PF=3.744, exp/wk=$502.04
**Walk-Forward**: 5/5 folds positive
**Gates**: 4/7

### Only BTC BULL trades

- Allowed regimes: ['BULL']
- Trades kept: 13, removed: 43

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 3.03 | >= 10 | **FAIL** |
| G2 | Max gap (days) | 10.33 | <= 2.5 | **FAIL** |
| G3 | Exp/week (market) | 257.33 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 197.82 | > $0 | PASS |
| G5 | Max DD% | 8.2 | <= 20% | PASS |
| G6 | WF folds positive | 3/5 | >= 4/5 | **FAIL** |
| G8 | Top-1 fold conc. | 62.2% | < 35% | **FAIL** |

**Metrics**: 13 trades, PF=5.647, exp/wk=$257.33, DD=8.2%
**Stress**: PF=4.305, exp/wk=$197.82
**Walk-Forward**: 3/5 folds positive
**Gates**: 3/7

### Only SIDEWAYS trades

- Allowed regimes: ['SIDEWAYS']
- Trades kept: 18, removed: 38

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 4.19 | >= 10 | **FAIL** |
| G2 | Max gap (days) | 5.08 | <= 2.5 | **FAIL** |
| G3 | Exp/week (market) | 368.89 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 304.22 | > $0 | PASS |
| G5 | Max DD% | 6.7 | <= 20% | PASS |
| G6 | WF folds positive | 5/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 46.1% | < 35% | **FAIL** |

**Metrics**: 18 trades, PF=4.081, exp/wk=$368.89, DD=6.7%
**Stress**: PF=3.471, exp/wk=$304.22
**Walk-Forward**: 5/5 folds positive
**Gates**: 4/7

### Comparison: Full vs Filtered Variants

| Variant | Trades | P&L | PF | WR% | Exp/wk | DD% | Gates |
|---------|--------|-----|-----|------|--------|-----|-------|
| Full baseline | 56 | $3272.13 | 2.834 | 64.3 | $762.44 | 8.6 | 7/7 |
| No BTC BEAR trades | 31 | $2687.53 | 4.576 | 74.2 | $626.22 | 5.4 | 4/7 |
| Only BTC BULL trades | 13 | $1104.39 | 5.647 | 76.9 | $257.33 | 8.2 | 3/7 |
| Only SIDEWAYS trades | 18 | $1583.13 | 4.081 | 72.2 | $368.89 | 6.7 | 4/7 |

## 8. Verdict

**BEAR trades: 25 trades, $+584.60 total P&L (NOT consistently negative). REGRESSION or NO DATA: Filtering BEAR trades does not help. Dominant regime: BEAR (50% of time). Regime concentration risk: MODERATE.**

**Recommendation**: BTC regime filtering NOT recommended -- signal is regime-robust

### Interpretation

- BEAR regime trades are NOT consistently negative ($+584.60), suggesting the signal works across all regimes.
- BULL regime trades: $+1104.39
- SIDEWAYS regime trades: $+1583.13
- Dominant regime (BEAR) accounts for 50% of classifiable bars.

---
*Generated by run_part2_btc_regime.py at 2026-02-16 00:59*