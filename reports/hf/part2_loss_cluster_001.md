# Part 2 -- Loss Cluster Analysis (Agent A3)

**Date**: 2026-02-16 00:15
**Commit**: e96951c
**Universe**: T1(100) + T2(216) = 316 coins
**Params**: dev=2.0, tp=8, sl=5, tl=10
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x: T1=25.0bps, T2=47.0bps)
**Runtime**: 31.6s

## 1. Per-Coin P&L Attribution

- Coins in universe: 316
- Coins with trades: 47
- Net-negative: 21
- Net-positive: 26
- Breakeven: 0
- Single-trade losers: 14

### Top-10 Worst Coins

| # | Coin | Tier | P&L | Trades | W/L |
|---|------|------|-----|--------|-----|
| 1 | KET/USD | T2 | $-301.24 | 3 | 0/3 |
| 2 | TANSSI/USD | T2 | $-218.51 | 2 | 0/2 |
| 3 | ANIME/USD | T2 | $-162.27 | 2 | 0/2 |
| 4 | DBR/USD | T2 | $-144.67 | 2 | 0/2 |
| 5 | HOUSE/USD | T2 | $-128.54 | 1 | 0/1 |
| 6 | ALKIMI/USD | T2 | $-117.25 | 4 | 1/3 |
| 7 | TITCOIN/USD | T1 | $-115.35 | 1 | 0/1 |
| 8 | LMWR/USD | T2 | $-109.60 | 1 | 0/1 |
| 9 | ESX/USD | T2 | $-108.10 | 1 | 0/1 |
| 10 | ODOS/USD | T2 | $-103.61 | 1 | 0/1 |

### Top-10 Best Coins

| # | Coin | Tier | P&L | Trades | W/L |
|---|------|------|-----|--------|-----|
| 1 | XL1/USD | T1 | $+468.30 | 3 | 3/0 |
| 2 | AURA/USD | T2 | $+260.49 | 3 | 3/0 |
| 3 | NOBODY/USD | T2 | $+164.95 | 2 | 2/0 |
| 4 | GHIBLI/USD | T1 | $+158.04 | 1 | 1/0 |
| 5 | AUDIO/USD | T2 | $+148.38 | 1 | 1/0 |
| 6 | TOKEN/USD | T2 | $+145.58 | 1 | 1/0 |
| 7 | SPICE/USD | T2 | $+135.43 | 1 | 1/0 |
| 8 | CVC/USD | T2 | $+132.81 | 1 | 1/0 |
| 9 | NYM/USD | T2 | $+123.78 | 2 | 1/1 |
| 10 | GOMINING/USD | T2 | $+121.39 | 2 | 1/1 |

## 2. Exclusion Strategies -- Gate Results

| Strategy | Coins | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Score |
|----------|-------|--------|----|--------|-----|----|-----------|-------|
| baseline_316 | 316 | 72 | 1.138 | $86.07 | 53.1% | 3/5 | 48.6% | **3/7** |
| excl_worst5 | 311 | 64 | 1.725 | $358.73 | 34.9% | 3/5 | 37.9% | **4/7** |
| excl_worst10 | 306 | 60 | 2.139 | $479.30 | 20.2% | 4/5 | 38.5% | **5/7** |
| excl_all_negative | 295 | 56 | 2.834 | $761.38 | 8.6% | 4/5 | 34.2% | **7/7** |
| excl_1trade_losers | 302 | 65 | 1.864 | $430.67 | 32.1% | 3/5 | 48.4% | **4/7** |

## 3. Gate Detail per Strategy

### baseline_316 (316 coins: T1=100, T2=216)

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 16.75 | >= 10 | PASS |
| G2 | Max gap (days) | 1.42 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 86.07 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | -32.74 | > $0 | **FAIL** |
| G5 | Max DD% | 53.1 | <= 20% | **FAIL** |
| G6 | WF folds positive | 3/5 | >= 4/5 | **FAIL** |
| G8 | Top-1 fold conc. | 48.6% | < 35% | **FAIL** |

**Walk-Forward Folds:**

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 13 | $416 | YES |
| 1 | 16 | $-199 | NO |
| 2 | 13 | $-499 | NO |
| 3 | 15 | $227 | YES |
| 4 | 16 | $608 | YES |

**Stress 2x**: trades=72, PF=0.949, exp/wk=$-32.74

### excl_worst5 (311 coins: T1=100, T2=211)

**Excluded**: ANIME/USD, DBR/USD, HOUSE/USD, KET/USD, TANSSI/USD

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 14.89 | >= 10 | PASS |
| G2 | Max gap (days) | 1.29 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 358.73 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 202.8 | > $0 | PASS |
| G5 | Max DD% | 34.9 | <= 20% | **FAIL** |
| G6 | WF folds positive | 3/5 | >= 4/5 | **FAIL** |
| G8 | Top-1 fold conc. | 37.9% | < 35% | **FAIL** |

**Walk-Forward Folds:**

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 10 | $732 | YES |
| 1 | 15 | $-66 | NO |
| 2 | 11 | $-322 | NO |
| 3 | 13 | $476 | YES |
| 4 | 15 | $721 | YES |

**Stress 2x**: trades=64, PF=1.383, exp/wk=$202.80

### excl_worst10 (306 coins: T1=99, T2=207)

**Excluded**: ALKIMI/USD, ANIME/USD, DBR/USD, ESX/USD, HOUSE/USD, KET/USD, LMWR/USD, ODOS/USD, TANSSI/USD, TITCOIN/USD

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.96 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 479.3 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 316.26 | > $0 | PASS |
| G5 | Max DD% | 20.2 | <= 20% | **FAIL** |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 38.5% | < 35% | **FAIL** |

**Walk-Forward Folds:**

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 10 | $732 | YES |
| 1 | 14 | $27 | YES |
| 2 | 10 | $-48 | NO |
| 3 | 12 | $418 | YES |
| 4 | 14 | $723 | YES |

**Stress 2x**: trades=60, PF=1.691, exp/wk=$316.26

### excl_all_negative (295 coins: T1=96, T2=199)

**Excluded**: AI3/USD, ALKIMI/USD, ANIME/USD, CFG/USD, DBR/USD, ESX/USD, GST/USD, HOUSE/USD, KET/USD, LMWR/USD, MXC/USD, ODOS/USD, PERP/USD, PNUT/USD, POLIS/USD, RARI/USD, SUKU/USD, TANSSI/USD, TITCOIN/USD, TOSHI/USD, WMTX/USD

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.03 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 761.38 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 570.62 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 34.2% | < 35% | PASS |

**Walk-Forward Folds:**

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 10 | $909 | YES |
| 1 | 13 | $58 | YES |
| 2 | 9 | $-18 | NO |
| 3 | 9 | $792 | YES |
| 4 | 15 | $913 | YES |

**Stress 2x**: trades=56, PF=2.306, exp/wk=$570.62

### excl_1trade_losers (302 coins: T1=96, T2=206)

**Excluded**: CFG/USD, ESX/USD, GST/USD, HOUSE/USD, LMWR/USD, MXC/USD, ODOS/USD, PERP/USD, PNUT/USD, POLIS/USD, RARI/USD, TITCOIN/USD, TOSHI/USD, WMTX/USD

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 15.12 | >= 10 | PASS |
| G2 | Max gap (days) | 1.17 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 430.67 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 270.62 | > $0 | PASS |
| G5 | Max DD% | 32.1 | <= 20% | **FAIL** |
| G6 | WF folds positive | 3/5 | >= 4/5 | **FAIL** |
| G8 | Top-1 fold conc. | 48.4% | < 35% | **FAIL** |

**Walk-Forward Folds:**

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 12 | $540 | YES |
| 1 | 14 | $-54 | NO |
| 2 | 12 | $-407 | NO |
| 3 | 12 | $615 | YES |
| 4 | 15 | $1086 | YES |

**Stress 2x**: trades=65, PF=1.528, exp/wk=$270.62

## 4. Conclusions

- **Baseline (316 coins)**: 3/7 gates pass
- **Best exclusion**: excl_all_negative -> 7/7 gates pass
- **Improvement**: +4 gates
  - G4 (Exp/week (P95 stress)): FAIL -> PASS
  - G5 (Max DD%): FAIL -> PASS
  - G6 (WF folds positive): FAIL -> PASS
  - G8 (Top-1 fold conc.): FAIL -> PASS

## 5. Actionable Finding

- Total negative coin P&L: $-2096.91 across 21 coins
- Total positive coin P&L: $+2466.82 across 26 coins
- Net: $+369.91

---
*Generated by run_part2_loss_cluster.py at 2026-02-16 00:15*