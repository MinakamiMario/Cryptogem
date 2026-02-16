# C8-A: Dev Threshold Sensitivity Sweep (295 coins)

**Agent**: C8-A
**Date**: 2026-02-16 01:41
**Commit**: 1787377
**Signal**: H20 VWAP_DEVIATION
**Sweep**: dev_thresh = [1.5, 1.8, 2.0, 2.2, 2.5, 3.0]
**Fixed**: tp_pct=8, sl_pct=5, time_limit=10
**Universe**: 295 coins (T1=96, T2=199, excl 21)
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x: T1=25.0bps, T2=47.0bps)
**Runtime**: 29.5s

## Key Finding

**Optimal dev_thresh**: 2.0 (passes 7/7 gates)

- dev=1.5 vs 2.0: +34 trades, $-331.38 exp/wk, -3 gates (4/7)
- dev=1.8 vs 2.0: +12 trades, $+49.48 exp/wk, -1 gates (6/7)
- dev=2.0 (baseline): 56 trades, 7/7 gates
- dev=2.2 vs 2.0: -8 trades, $-268.88 exp/wk, -2 gates (5/7)
- dev=2.5 vs 2.0: -21 trades, $-488.79 exp/wk, -3 gates (4/7)
- dev=3.0 vs 2.0: -36 trades, $-497.57 exp/wk, -3 gates (4/7)

## Sweep Results

| dev | Trades | T1/T2 | PF | WR% | Exp/Wk | DD% | WF | Gap(d) | Conc% | Gates |
|-----|--------|-------|----|----|--------|-----|----|----|------|-------|
| 1.5 | 90 | 38/52 | 1.600 | 53.3 | $431.06 | 39.4 | 3/5 | 0.7 | 54.3 | 4/7 |
| 1.8 | 68 | 26/42 | 2.547 | 61.8 | $811.92 | 14.1 | 4/5 | 1.2 | 36.7 | 6/7 |
| 2.0 * | 56 | 18/38 | 2.834 | 64.3 | $762.44 | 8.6 | 4/5 | 1.4 | 34.2 | 7/7 |
| 2.2 | 48 | 16/32 | 2.654 | 60.4 | $493.56 | 9.8 | 3/5 | 2.0 | 52.2 | 5/7 |
| 2.5 | 35 | 10/25 | 2.306 | 54.3 | $273.65 | 11.8 | 3/5 | 2.0 | 52.9 | 4/7 |
| 3.0 | 20 | 5/15 | 4.446 | 70.0 | $264.86 | 7.0 | 4/5 | 3.9 | 55.9 | 4/7 |

\* = current baseline

## Gate Pass/Fail Matrix

| Gate | Threshold | 1.5 | 1.8 | 2.0 | 2.2 | 2.5 | 3.0 |
|------|-----------|-----|-----|-----|-----|-----|-----|
| G1 | >= 10/wk | PASS | PASS | PASS | PASS | **FAIL** | **FAIL** |
| G2 | <= 2.5d | PASS | PASS | PASS | PASS | PASS | **FAIL** |
| G3 | > $0 | PASS | PASS | PASS | PASS | PASS | PASS |
| G4 | > $0 | PASS | PASS | PASS | PASS | PASS | PASS |
| G5 | <= 20% | **FAIL** | PASS | PASS | PASS | PASS | PASS |
| G6 | >= 4/5 | **FAIL** | PASS | PASS | **FAIL** | **FAIL** | PASS |
| G8 | < 35% | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | **FAIL** |
| **Total** | | **4/7** | **6/7** | **7/7** | **5/7** | **4/7** | **4/7** |

## Gate Values

| Gate | Metric | 1.5 | 1.8 | 2.0 | 2.2 | 2.5 | 3.0 |
|------|--------|-----|-----|-----|-----|-----|-----|
| G1 | Throughput | 20.97 | 15.84 | 13.05 | 11.18 | 8.16 | 4.66 |
| G2 | Max Gap | 0.67 | 1.25 | 1.42 | 2.04 | 2.04 | 3.92 |
| G3 | Edge (baseline) | 431.06 | 811.92 | 762.44 | 493.56 | 273.65 | 264.86 |
| G4 | Edge (stress 2x) | 205.38 | 586.37 | 571.41 | 360.16 | 188.39 | 214.55 |
| G5 | Max Drawdown | 39.4 | 14.1 | 8.6 | 9.8 | 11.8 | 7.0 |
| G6 | Walk-Forward | 3/5 | 4/5 | 4/5 | 3/5 | 3/5 | 4/5 |
| G8 | Fold Concentration | 54.3 | 36.7 | 34.2 | 52.2 | 52.9 | 55.9 |

## Stress Test (2x fees)

| dev | Trades | PF | WR% | Exp/Wk | DD% |
|-----|--------|----|----|--------|-----|
| 1.5 | 90 | 1.280 | 50.0 | $205.38 | 46.7 |
| 1.8 | 68 | 2.074 | 58.8 | $586.37 | 19.4 |
| 2.0 | 56 | 2.306 | 62.5 | $571.41 | 13.1 |
| 2.2 | 48 | 2.112 | 58.3 | $360.16 | 13.5 |
| 2.5 | 35 | 1.788 | 51.4 | $188.39 | 15.5 |
| 3.0 | 20 | 3.355 | 65.0 | $214.55 | 8.2 |

## Walk-Forward Detail (5-fold)

### dev_thresh=1.5 (3/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 16 | $704 | PASS | NYM/USD | $175 |
| F1 | 19 | $-238 | **FAIL** | NOBODY/USD | $160 |
| F2 | 19 | $-44 | **FAIL** | AURA/USD | $145 |
| F3 | 18 | $1166 | PASS | ELX/USD | $334 |
| F4 | 18 | $276 | PASS | INIT/USD | $154 |

### dev_thresh=1.8 (4/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 11 | $1151 | PASS | NYM/USD | $190 |
| F1 | 17 | $-170 | **FAIL** | GOMINING/USD | $154 |
| F2 | 12 | $191 | PASS | AURA/USD | $152 |
| F3 | 11 | $945 | PASS | TOKEN/USD | $187 |
| F4 | 17 | $847 | PASS | XL1/USD | $331 |

### dev_thresh=2.0 (4/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 10 | $909 | PASS | NYM/USD | $190 |
| F1 | 13 | $58 | PASS | GOMINING/USD | $162 |
| F2 | 9 | $-18 | **FAIL** | AURA/USD | $154 |
| F3 | 9 | $792 | PASS | CVC/USD | $174 |
| F4 | 15 | $913 | PASS | XL1/USD | $331 |

### dev_thresh=2.2 (3/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 8 | $377 | PASS | NYM/USD | $164 |
| F1 | 10 | $-90 | **FAIL** | GOMINING/USD | $151 |
| F2 | 9 | $-18 | **FAIL** | AURA/USD | $154 |
| F3 | 7 | $580 | PASS | XL1/USD | $167 |
| F4 | 14 | $1044 | PASS | XL1/USD | $331 |

### dev_thresh=2.5 (3/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 9 | $747 | PASS | SIGMA/USD | $337 |
| F1 | 6 | $-120 | **FAIL** | SIGMA/USD | $-134 |
| F2 | 7 | $-51 | **FAIL** | AUDIO/USD | $146 |
| F3 | 4 | $291 | PASS | ELX/USD | $155 |
| F4 | 9 | $374 | PASS | XL1/USD | $322 |

### dev_thresh=3.0 (4/5 positive)

| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |
|------|--------|-----|--------|----------|-------------|
| F0 | 5 | $652 | PASS | SIGMA/USD | $336 |
| F1 | 4 | $-91 | **FAIL** | SIGMA/USD | $-134 |
| F2 | 2 | $45 | PASS | AUDIO/USD | $150 |
| F3 | 4 | $291 | PASS | ELX/USD | $155 |
| F4 | 5 | $177 | PASS | XL1/USD | $155 |

## Exit Reason Breakdown

| dev | Reason | Count | P&L | WR% |
|-----|--------|-------|-----|-----|
| 1.5 | FIXED STOP | 15 | $-1888.70 | 0.0% |
| 1.5 | TIME MAX | 51 | $-409.99 | 47.1% |
| 1.5 | END | 1 | $50.92 | 100.0% |
| 1.5 | PROFIT TARGET | 23 | $4097.72 | 100.0% |
| 1.8 | FIXED STOP | 7 | $-1134.02 | 0.0% |
| 1.8 | TIME MAX | 37 | $-407.37 | 48.6% |
| 1.8 | PROFIT TARGET | 24 | $5025.87 | 100.0% |
| 2.0 | FIXED STOP | 7 | $-1137.58 | 0.0% |
| 2.0 | TIME MAX | 28 | $12.03 | 53.6% |
| 2.0 | PROFIT TARGET | 21 | $4397.68 | 100.0% |
| 2.2 | FIXED STOP | 6 | $-779.52 | 0.0% |
| 2.2 | TIME MAX | 26 | $2.76 | 50.0% |
| 2.2 | PROFIT TARGET | 16 | $2894.97 | 100.0% |
| 2.5 | FIXED STOP | 4 | $-515.66 | 0.0% |
| 2.5 | END | 1 | $-10.56 | 0.0% |
| 2.5 | TIME MAX | 20 | $9.68 | 45.0% |
| 2.5 | PROFIT TARGET | 10 | $1690.96 | 100.0% |
| 3.0 | FIXED STOP | 2 | $-250.61 | 0.0% |
| 3.0 | END | 1 | $-10.50 | 0.0% |
| 3.0 | TIME MAX | 10 | $249.48 | 70.0% |
| 3.0 | PROFIT TARGET | 7 | $1148.34 | 100.0% |

## Sensitivity Curve

```
dev_thresh  trades  exp/wk   gates
  1.5         90   $431.06  4/7  ######################################################################################
  1.8         68   $811.92  6/7  ##################################################################################################################################################################
  2.0         56   $762.44  7/7  ########################################################################################################################################################
  2.2         48   $493.56  5/7  ##################################################################################################
  2.5         35   $273.65  4/7  ######################################################
  3.0         20   $264.86  4/7  ####################################################
```

## Conclusion

dev_thresh=2.0 (baseline) remains optimal. No improvement found.

**GO candidates** (6+ gates): dev=1.8 (6/7), dev=2.0 (7/7)

---
*Generated by strategies/hf/screening/run_part2_dev_thresh_sweep_001.py
at 2026-02-16 01:41*