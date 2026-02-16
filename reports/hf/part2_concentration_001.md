# Part 2 -- Concentration Control (Agent C7-D, P0-2)

**Date**: 2026-02-16 01:29
**Commit**: 427d5e0
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Params**: v5 (dev=2.0, tp=8, sl=5, tl=10)
**Fees**: T1=12.5bps, T2=23.5bps
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 30.4s

## STRICT Gate Thresholds

| Gate | Threshold |
|------|-----------|
| G1 | trades/week >= 10 |
| G2 | max gap <= 2.5d |
| G3 | exp/week > $0 |
| G4 | exp/week > $0 (stress 2x) |
| G5 | DD <= 20% |
| G6 | WF >= 4/5 |
| G8 | fold_conc < 35% |

## 1. Diagnosis: What Drives Concentration

**Baseline**: 56 trades, PF=2.834, exp/wk=$762.44
**Fold concentration**: 34.2%
**Total positive P&L**: $4394.90
**Coins with trades**: 41

### Top-5 Coins by P&L

| Rank | Coin | P&L | Share% | Trades |
|------|------|-----|--------|--------|
| 1 | XL1/USD | $549.02 | 12.5% | 3 |
| 2 | AURA/USD | $486.12 | 11.1% | 4 |
| 3 | INIT/USD | $311.41 | 7.1% | 1 |
| 4 | SPICE/USD | $275.41 | 6.3% | 1 |
| 5 | CVC/USD | $265.74 | 6.0% | 1 |

### Per-Fold P&L Breakdown

| Fold | P&L | Share% | Trades | Positive |
|------|-----|--------|--------|----------|
| 0 | $909.08 | 34.0% | 10 | YES |
| 1 | $57.53 | 2.2% | 13 | YES |
| 2 | $-17.57 | 0.0% | 9 | NO |
| 3 | $792.44 | 29.7% | 9 | YES |
| 4 | $913.43 | 34.2% | 15 | YES |

**Highest concentration fold**: Fold 4 (34.2% of positive P&L)

### Top-3 Coins per Fold

- **Fold 0**: NYM/USD ($190.4), SIGMA/USD ($177.1), TOKEN/USD ($164.8)
- **Fold 1**: GOMINING/USD ($161.7), NOBODY/USD ($154.9), ALPHA/USD ($62.0)
- **Fold 2**: AURA/USD ($153.7), AUDIO/USD ($145.6), BANANAS31/USD ($7.8)
- **Fold 3**: CVC/USD ($173.6), XL1/USD ($169.9), AURA/USD ($161.5)
- **Fold 4**: XL1/USD ($331.1), KOBAN/USD ($190.0), INIT/USD ($167.6)

### Baseline Gate Evaluation

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.05 | >= 10 | PASS |
| G2 | Max gap (days) | 2.75 | <= 2.5 | **FAIL** |
| G3 | Exp/week (market) | 762.4382 | > $0 | PASS |
| G4 | Exp/week (2x stress) | 571.413 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Fold concentration | 34.2% | < 35% | PASS |

## 2. Summary Comparison: All Controls

| Variant | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Top1 Coin% | Gates | Verdict |
|---------|--------|----|--------|-----|----|-----------|-----------:|-------|---------|
| Baseline | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 12.5% | 6/7 | FAIL: G2 |
| Cap 1/coin | 41 | 2.600 | $504.03 | 9.6 | 4/5 | 34.9% | 8.9% | 5/7 | FAIL: G1,G2 |
| Cap 2/coin | 51 | 2.535 | $577.49 | 10.3 | 4/5 | 34.2% | 9.6% | 6/7 | FAIL: G2 |
| Cap 3/coin | 54 | 2.535 | $638.12 | 8.6 | 4/5 | 34.2% | 14.1% | 6/7 | FAIL: G2 |
| PnL cap 10% | 55 | 2.741 | $723.73 | 8.6 | 0/5 | 100.0% | 11.5% | 4/7 | FAIL: G2,G6,G8 |
| PnL cap 15% | 56 | 2.834 | $762.44 | 8.6 | 2/5 | 72.2% | 12.5% | 4/7 | FAIL: G2,G6,G8 |
| PnL cap 20% | 56 | 2.834 | $762.44 | 8.6 | 3/5 | 37.0% | 12.5% | 4/7 | FAIL: G2,G6,G8 |
| PnL cap 25% | 56 | 2.834 | $762.44 | 8.6 | 3/5 | 37.0% | 12.5% | 4/7 | FAIL: G2,G6,G8 |
| max_pos=1 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 12.5% | 6/7 | FAIL: G2 |
| max_pos=2 | 59 | 2.699 | $305.06 | 5.0 | 4/5 | 34.1% | 14.3% | 6/7 | FAIL: G2 |
| max_pos=3 | 77 | 2.732 | $219.88 | 4.3 | 4/5 | 36.9% | 12.9% | 5/7 | FAIL: G2,G8 |
| max_pos=5 | 88 | 2.860 | $142.44 | 2.9 | 3/5 | 36.2% | 12.0% | 4/7 | FAIL: G2,G6,G8 |
| str>=0 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 12.5% | 6/7 | FAIL: G2 |
| str>=0.5 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 12.5% | 6/7 | FAIL: G2 |
| str>=1.0 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 12.5% | 6/7 | FAIL: G2 |
| str>=1.5 | 20 | 4.446 | $264.86 | 7.0 | 4/5 | 55.9% | 13.8% | 4/7 | FAIL: G1,G2,G8 |
| str>=2.0 | 6 | 1.278 | $15.60 | 11.2 | 2/5 | 51.0% | 79.2% | 3/7 | FAIL: G1,G2,G6,G8 |

## 3. Before/After: Cap per Coin

| max_trades | Trades | PF | DD% | WF | Fold Conc | Top1% | Top3% | Gates |
|-----------|--------|----|-----|----|-----------:|------:|------:|-------|
| baseline | 56 | 2.834 | 8.6 | 4/5 | 34.2% | 12.5% | 30.6% | 6/7 |
| 1 | 41 | 2.600 | 9.6 | 4/5 | 34.9% | 8.9% | 24.3% | 5/7 |
| 2 | 51 | 2.535 | 10.3 | 4/5 | 34.2% | 9.6% | 25.9% | 6/7 |
| 3 | 54 | 2.535 | 8.6 | 4/5 | 34.2% | 14.1% | 29.2% | 6/7 |

## 4. Before/After: P&L Share Cap

| max_share | Trades | PF | DD% | WF | Fold Conc | Top1% | Top3% | Gates |
|----------|--------|----|-----|----|-----------:|------:|------:|-------|
| baseline | 56 | 2.834 | 8.6 | 4/5 | 34.2% | 12.5% | 30.6% | 6/7 |
| 10% | 55 | 2.741 | 8.6 | 0/5 | 100.0% | 11.5% | 27.9% | 4/7 |
| 15% | 56 | 2.834 | 8.6 | 2/5 | 72.2% | 12.5% | 30.6% | 4/7 |
| 20% | 56 | 2.834 | 8.6 | 3/5 | 37.0% | 12.5% | 30.6% | 4/7 |
| 25% | 56 | 2.834 | 8.6 | 3/5 | 37.0% | 12.5% | 30.6% | 4/7 |

## 5. Before/After: max_pos Tuning

| max_pos | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Gates |
|---------|--------|----|--------|-----|----|-----------:|-------|
| 1 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 6/7 |
| 2 | 59 | 2.699 | $305.06 | 5.0 | 4/5 | 34.1% | 6/7 |
| 3 | 77 | 2.732 | $219.88 | 4.3 | 4/5 | 36.9% | 5/7 |
| 5 | 88 | 2.860 | $142.44 | 2.9 | 3/5 | 36.2% | 4/7 |

## 6. Before/After: Signal Strength Filter

| strength_min | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Gates |
|-------------|--------|----|--------|-----|----|-----------:|-------|
| 0 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 6/7 |
| 0.5 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 6/7 |
| 1.0 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | 34.2% | 6/7 |
| 1.5 | 20 | 4.446 | $264.86 | 7.0 | 4/5 | 55.9% | 4/7 |
| 2.0 | 6 | 1.278 | $15.60 | 11.2 | 2/5 | 51.0% | 3/7 |

## 7. Per-Variant Gate Tables

### Cap 1/coin

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 9.55 | >= 10 | **FAIL** |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 504.0253 | > $0 | PASS |
| G4 | 371.8566 | > $0 | PASS |
| G5 | 9.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.9% | < 35% | PASS |

### Cap 2/coin

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 11.88 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 577.4945 | > $0 | PASS |
| G4 | 421.3097 | > $0 | PASS |
| G5 | 10.3 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### Cap 3/coin

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 12.58 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 638.1166 | > $0 | PASS |
| G4 | 470.0749 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### PnL cap 10%

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 12.82 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 723.7291 | > $0 | PASS |
| G4 | 535.0188 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 0/5 | >= 4/5 | **FAIL** |
| G8 | 100.0% | < 35% | **FAIL** |

### PnL cap 15%

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 2/5 | >= 4/5 | **FAIL** |
| G8 | 72.2% | < 35% | **FAIL** |

### PnL cap 20%

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 3/5 | >= 4/5 | **FAIL** |
| G8 | 37.0% | < 35% | **FAIL** |

### PnL cap 25%

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 3/5 | >= 4/5 | **FAIL** |
| G8 | 37.0% | < 35% | **FAIL** |

### max_pos=1

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### max_pos=2

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.75 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 305.0584 | > $0 | PASS |
| G4 | 231.6256 | > $0 | PASS |
| G5 | 5.0 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.1% | < 35% | PASS |

### max_pos=3

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 17.94 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 219.8791 | > $0 | PASS |
| G4 | 165.8787 | > $0 | PASS |
| G5 | 4.3 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 36.9% | < 35% | **FAIL** |

### max_pos=5

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 20.5 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 142.4428 | > $0 | PASS |
| G4 | 107.5625 | > $0 | PASS |
| G5 | 2.9 | <= 20% | PASS |
| G6 | 3/5 | >= 4/5 | **FAIL** |
| G8 | 36.2% | < 35% | **FAIL** |

### str>=0

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### str>=0.5

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### str>=1.0

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 2.75 | <= 2.5 | **FAIL** |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.6 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 34.2% | < 35% | PASS |

### str>=1.5

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 4.66 | >= 10 | **FAIL** |
| G2 | 4.0 | <= 2.5 | **FAIL** |
| G3 | 264.864 | > $0 | PASS |
| G4 | 214.552 | > $0 | PASS |
| G5 | 7.0 | <= 20% | PASS |
| G6 | 4/5 | >= 4/5 | PASS |
| G8 | 55.9% | < 35% | **FAIL** |

### str>=2.0

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1 | 1.4 | >= 10 | **FAIL** |
| G2 | 7.92 | <= 2.5 | **FAIL** |
| G3 | 15.6019 | > $0 | PASS |
| G4 | 2.7459 | > $0 | PASS |
| G5 | 11.2 | <= 20% | PASS |
| G6 | 2/5 | >= 4/5 | **FAIL** |
| G8 | 51.0% | < 35% | **FAIL** |

## 8. Verdict: Which Controls Help G8

9 variant(s) pass G8 (fold_conc < 35%):

| Variant | Fold Conc | Gates | Trades | PF | Exp/Wk | Failed |
|---------|-----------|-------|--------|----|--------|--------|
| max_pos=2 | 34.1% | 6/7 | 59 | 2.699 | $305.06 | G2 |
| Baseline (295, mp1) | 34.2% | 6/7 | 56 | 2.834 | $762.44 | G2 |
| Cap 2/coin | 34.2% | 6/7 | 51 | 2.535 | $577.49 | G2 |
| Cap 3/coin | 34.2% | 6/7 | 54 | 2.535 | $638.12 | G2 |
| max_pos=1 | 34.2% | 6/7 | 56 | 2.834 | $762.44 | G2 |
| strength>=0 | 34.2% | 6/7 | 56 | 2.834 | $762.44 | G2 |
| strength>=0.5 | 34.2% | 6/7 | 56 | 2.834 | $762.44 | G2 |
| strength>=1.0 | 34.2% | 6/7 | 56 | 2.834 | $762.44 | G2 |
| Cap 1/coin | 34.9% | 5/7 | 41 | 2.600 | $504.03 | G1, G2 |

**No variant passes all 7 strict gates simultaneously.** 
Concentration control alone is insufficient to pass the strict gate set.

---
*Generated by strategies/hf/screening/run_part2_concentration_001.py at 2026-02-16 01:29*