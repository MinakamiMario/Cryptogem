# Part 2 Baseline Gate Evaluation: 316 vs 295 (STRICT)

**Agent**: C7-F Integrator
**Date**: 2026-02-16 01:30
**Commit**: 427d5e0
**Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x: T1=25.0bps, T2=47.0bps)
**Runtime**: 30.1s

## Verdict

| Universe | Gates Pass | Verdict | Failing |
|----------|-----------|---------|---------|
| **316 coins** | 3/7 | **NO-GO** | G4, G5, G6, G8 |
| **295 coins** | 7/7 | **GO** | None |

## Gate Comparison

| Gate | Name | Threshold | 316 Value | 316 | 295 Value | 295 |
|------|------|-----------|-----------|-----|-----------|-----|
| G1 | Throughput | >= 10/wk | 16.75 | PASS | 13.03 | PASS |
| G2 | Max Gap | <= 2.5d | 1.42 | PASS | 1.5 | PASS |
| G3 | Edge (baseline) | > $0 | 86.07 | PASS | 761.38 | PASS |
| G4 | Edge (stress 2x) | > $0 | -32.74 | **FAIL** | 570.62 | PASS |
| G5 | Max Drawdown | <= 20% | 53.1 | **FAIL** | 8.6 | PASS |
| G6 | Walk-Forward | >= 4/5 | 3/5 | **FAIL** | 4/5 | PASS |
| G8 | Fold Concentration | < 35% | 48.6 | **FAIL** | 34.2 | PASS |

## Metrics Comparison

| Metric | 316 coins | 295 coins | Delta |
|--------|-----------|-----------|-------|
| trades | 72 | 56 | -16 |
| pnl | 369.91 | 3272.13 | +2902.22 |
| pf | 1.14 | 2.83 | +1.70 |
| wr | 47.22 | 64.29 | +17.07 |
| dd | 53.11 | 8.63 | +-44.48 |
| trades_per_week | 16.75 | 13.03 | -3.72 |
| exp_per_week | 86.07 | 761.38 | +675.31 |
| fee_drag_pct | 17.44 | 12.27 | +-5.17 |

## Stress Test (2x fees)

| Metric | 316 coins | 295 coins |
|--------|-----------|-----------|
| trades | 72 | 56 |
| pnl | -140.69 | 2452.31 |
| pf | 0.949 | 2.306 |
| wr | 43.06 | 62.5 |
| dd | 62.22 | 13.12 |
| exp_per_week | -32.7368 | 570.6216 |

## Walk-Forward Detail (5-fold)

### 316 coins

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 13 | $416 | PASS | NYM/USD | $165 |
| F1 | 16 | $-199 | **FAIL** | NOBODY/USD | $155 |
| F2 | 13 | $-499 | **FAIL** | AUDIO/USD | $139 |
| F3 | 15 | $227 | PASS | KET/USD | $-224 |
| F4 | 16 | $608 | PASS | XL1/USD | $331 |

### 295 coins

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 10 | $909 | PASS | NYM/USD | $190 |
| F1 | 13 | $58 | PASS | GOMINING/USD | $162 |
| F2 | 9 | $-18 | **FAIL** | AURA/USD | $154 |
| F3 | 9 | $792 | PASS | CVC/USD | $174 |
| F4 | 15 | $913 | PASS | XL1/USD | $331 |

## Gap Analysis: 316 -> Passing

### G4: Edge (stress 2x)

- **316 value**: -32.74
- **295 value**: 570.62 (status: PASS)
- **Threshold**: > $0
- **Analysis**: 316-coin stress exp/wk = $-32.74 (need > $0). 295-coin = $570.62. The 21 excluded T2 coins with high fees drag edge below zero under 2x stress.
- **Suggestions**:
  - Reduce T2 exposure (fee drag dominates under stress)
  - Tighten SL to reduce loss magnitude per trade
  - Raise dev_thresh to filter weak signals (fewer but cleaner trades)
  - Consider T2 fee rebate or maker-order strategy

### G5: Max Drawdown

- **316 value**: 53.1
- **295 value**: 8.6 (status: PASS)
- **Threshold**: <= 20%
- **Analysis**: 316-coin DD = 53.1% (need <= 20%). Need 33.1% DD reduction. 295-coin DD = 8.6%.
- **Suggestions**:
  - Reduce position size (currently 100% of capital)
  - Tighten stop loss (sl_pct from 5% to 3-4%)
  - Add max_pos > 1 for diversification
  - Time-based risk reduction (shorter time_limit)

### G6: Walk-Forward

- **316 value**: 3/5
- **295 value**: 4/5 (status: PASS)
- **Threshold**: >= 4/5
- **Analysis**: 316-coin WF = 3/5 (need >= 4/5). 295-coin WF = 4/5. Failing folds: F1 ($-199, 16 trades, top: NOBODY/USD), F2 ($-499, 13 trades, top: AUDIO/USD)
- **Suggestions**:
  - Investigate failing fold periods for regime shifts
  - Test adaptive parameters per market regime
  - Check if excluded coins drive fold losses
  - Consider 3/5 threshold for GO with caveats

### G8: Fold Concentration

- **316 value**: 48.6
- **295 value**: 34.2 (status: PASS)
- **Threshold**: < 35%
- **Analysis**: 316-coin fold_conc = 48.6% (need < 35%). 295-coin fold_conc = 34.2%.
- **Suggestions**:
  - More uniform edge across folds needed
  - Check if one fold has an outlier coin
  - Diversify signal sources across time periods

## Worst Coins (316 universe)

| Coin | Trades | P&L | Wins | Losses |
|------|--------|-----|------|--------|
| KET/USD | 3 | $-301.24 | 0 | 3 |
| TANSSI/USD | 2 | $-218.51 | 0 | 2 |
| ANIME/USD | 2 | $-162.27 | 0 | 2 |
| DBR/USD | 2 | $-144.67 | 0 | 2 |
| HOUSE/USD | 1 | $-128.54 | 0 | 1 |
| ALKIMI/USD | 4 | $-117.25 | 1 | 3 |
| TITCOIN/USD | 1 | $-115.35 | 0 | 1 |
| LMWR/USD | 1 | $-109.60 | 0 | 1 |
| ESX/USD | 1 | $-108.10 | 0 | 1 |
| ODOS/USD | 1 | $-103.61 | 0 | 1 |

## Best Coins (316 universe)

| Coin | Trades | P&L | Wins | Losses |
|------|--------|-----|------|--------|
| XL1/USD | 3 | $468.30 | 3 | 0 |
| AURA/USD | 3 | $260.49 | 3 | 0 |
| NOBODY/USD | 2 | $164.95 | 2 | 0 |
| GHIBLI/USD | 1 | $158.04 | 1 | 0 |
| AUDIO/USD | 1 | $148.38 | 1 | 0 |
| TOKEN/USD | 1 | $145.58 | 1 | 0 |
| SPICE/USD | 1 | $135.43 | 1 | 0 |
| CVC/USD | 1 | $132.81 | 1 | 0 |
| NYM/USD | 2 | $123.78 | 1 | 1 |
| GOMINING/USD | 2 | $121.39 | 1 | 1 |

## Worst Trades (316 universe)

| Coin | P&L | P&L% | Reason | Bars | Entry Bar | Tier |
|------|-----|------|--------|------|-----------|------|
| HOUSE/USD | $-128.54 | -5.5% | FIXED STOP | 8 | 173 | tier2 |
| SIGMA/USD | $-123.63 | -5.5% | FIXED STOP | 4 | 311 | tier2 |
| DBR/USD | $-121.63 | -5.5% | FIXED STOP | 1 | 297 | tier2 |
| TANSSI/USD | $-116.88 | -5.5% | FIXED STOP | 2 | 321 | tier2 |
| ANIME/USD | $-115.92 | -5.5% | FIXED STOP | 3 | 370 | tier2 |
| TITCOIN/USD | $-115.35 | -5.2% | FIXED STOP | 2 | 224 | tier1 |
| ELX/USD | $-112.99 | -5.2% | FIXED STOP | 1 | 160 | tier1 |
| KET/USD | $-109.69 | -5.5% | FIXED STOP | 3 | 85 | tier2 |
| LMWR/USD | $-109.60 | -5.5% | FIXED STOP | 1 | 381 | tier2 |
| ESX/USD | $-108.10 | -5.5% | FIXED STOP | 5 | 694 | tier2 |

## Exit Reason Breakdown

### 316 coins

| Reason | Count | P&L | WR% |
|--------|-------|-----|-----|
| FIXED STOP | 20 | $-2148.75 | 0.0% |
| TIME MAX | 33 | $-141.72 | 45.5% |
| END | 1 | $1.19 | 100.0% |
| PROFIT TARGET | 18 | $2659.20 | 100.0% |

### 295 coins

| Reason | Count | P&L | WR% |
|--------|-------|-----|-----|
| FIXED STOP | 7 | $-1137.58 | 0.0% |
| TIME MAX | 28 | $12.03 | 53.6% |
| PROFIT TARGET | 21 | $4397.68 | 100.0% |

## Best-Next-Test Suggestions

Based on failing gates on 316:

- [G4] Reduce T2 exposure (fee drag dominates under stress)
- [G4] Tighten SL to reduce loss magnitude per trade
- [G4] Raise dev_thresh to filter weak signals (fewer but cleaner trades)
- [G4] Consider T2 fee rebate or maker-order strategy
- [G5] Reduce position size (currently 100% of capital)
- [G5] Tighten stop loss (sl_pct from 5% to 3-4%)
- [G5] Add max_pos > 1 for diversification
- [G5] Time-based risk reduction (shorter time_limit)
- [G6] Investigate failing fold periods for regime shifts
- [G6] Test adaptive parameters per market regime
- [G6] Check if excluded coins drive fold losses
- [G6] Consider 3/5 threshold for GO with caveats
- [G8] More uniform edge across folds needed
- [G8] Check if one fold has an outlier coin
- [G8] Diversify signal sources across time periods

---
*Generated by strategies/hf/screening/run_part2_baseline_316_001.py
at 2026-02-16 01:30*