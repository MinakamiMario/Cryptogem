# Part 2 -- Deep Stress Analysis: 295 Coins + tp10_sl4_tl8 (C2-A6)

**Date**: 2026-02-16 00:26
**Commit**: ad313f6
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**tp10 Params**: dev=2.0, tp=10, sl=4, tl=8
**v5 Params**: dev=2.0, tp=8, sl=5, tl=10
**Base Fees**: T1=12.5bps, T2=23.5bps
**Runtime**: 33.5s

## Part A: Fee Ladder

### tp10_sl4_tl8

| Mult | T1 bps | T2 bps | Trades | PF | WR% | Exp/Wk | DD% | Fee Drag | T1 P&L | T2 P&L | G4 |
|------|--------|--------|--------|----|-----|--------|-----|----------|--------|--------|----|
| 1.00x | 12.5 | 23.5 | 61 | 2.392 | 57.4 | $644.59 | 12.2 | 13.7% | $900 | $1867 | **PASS** |
| 1.25x | 15.6 | 29.4 | 61 | 2.261 | 54.1 | $593.47 | 13.5 | 17.0% | $866 | $1681 | **PASS** |
| 1.50x | 18.8 | 35.2 | 61 | 2.136 | 54.1 | $544.47 | 14.8 | 20.3% | $832 | $1505 | **PASS** |
| 1.75x | 21.9 | 41.1 | 61 | 2.020 | 50.8 | $497.48 | 16.1 | 23.6% | $799 | $1336 | **PASS** |
| 2.00x | 25.0 | 47.0 | 61 | 1.912 | 49.2 | $452.42 | 17.4 | 26.9% | $766 | $1176 | **PASS** |
| 2.25x | 28.1 | 52.9 | 61 | 1.812 | 49.2 | $409.21 | 18.7 | 30.2% | $733 | $1023 | **PASS** |
| 2.50x | 31.2 | 58.8 | 61 | 1.718 | 47.5 | $367.75 | 20.0 | 33.4% | $701 | $877 | **PASS** |

### v5 baseline (same 295 coins)

| Mult | Trades | PF | WR% | Exp/Wk | DD% | T1 P&L | T2 P&L | G4 |
|------|--------|----|-----|--------|-----|--------|--------|----|
| 1.00x | 56 | 2.834 | 64.3 | $762.44 | 8.6 | $1058 | $2214 | **PASS** |
| 1.25x | 56 | 2.689 | 64.3 | $711.93 | 9.5 | $1024 | $2031 | **PASS** |
| 1.50x | 56 | 2.553 | 62.5 | $663.30 | 10.7 | $991 | $1856 | **PASS** |
| 1.75x | 56 | 2.425 | 62.5 | $616.49 | 11.9 | $957 | $1688 | **PASS** |
| 2.00x | 56 | 2.306 | 62.5 | $571.41 | 13.1 | $925 | $1528 | **PASS** |
| 2.25x | 56 | 2.193 | 58.9 | $528.01 | 14.4 | $892 | $1374 | **PASS** |
| 2.50x | 56 | 2.084 | 55.4 | $486.20 | 16.2 | $860 | $1227 | **PASS** |

## Breakeven Analysis

| Config | Breakeven Mult | T1 bps | T2 bps | Survives 2x? |
|--------|---------------|--------|--------|--------------|
| tp10_sl4_tl8 | **5.328x** | 66.6 | 125.2 | **YES** |
| v5 baseline | **6.394x** | 79.9 | 150.3 | **YES** |
| A5 ref (316 coins) | 1.71x | — | — | NO |

## Part B: Walk-Forward Comparison

| Fold | tp10 Trades | tp10 P&L | v5 Trades | v5 P&L |
|------|------------|----------|----------|--------|
| 0 | 11 | $838.70 | 10 | $909.08 |
| 1 | 15 | $21.38 | 13 | $57.53 |
| 2 | 9 | $134.55 | 9 | $-17.57 |
| 3 | 10 | $546.97 | 9 | $792.44 |
| 4 | 16 | $779.56 | 15 | $913.43 |
| **Total** | — | **5/5 pos** | — | **4/5 pos** |
| **Fold Conc** | — | **36.1%** | — | **34.2%** |

## Per-Fold Top-5 Coins (tp10_sl4_tl8)

### Fold 0 (P&L=$838.70, 11 trades, 11 coins)

| Coin | P&L | Trades | WR% |
|------|-----|--------|-----|
| NYM/USD | $+221.20 | 1 | 100% |
| GHIBLI/USD | $+204.64 | 1 | 100% |
| SIGMA/USD | $+202.00 | 1 | 100% |
| REKT/USD | $+194.75 | 1 | 100% |
| JUNO/USD | $+190.13 | 1 | 100% |

### Fold 1 (P&L=$21.38, 15 trades, 13 coins)

| Coin | P&L | Trades | WR% |
|------|-----|--------|-----|
| GOMINING/USD | $+198.94 | 1 | 100% |
| NOBODY/USD | $+149.27 | 1 | 100% |
| ALPHA/USD | $+61.98 | 1 | 100% |
| AURA/USD | $+9.58 | 2 | 50% |
| SBR/USD | $+4.29 | 1 | 100% |

### Fold 2 (P&L=$134.55, 9 trades, 9 coins)

| Coin | P&L | Trades | WR% |
|------|-----|--------|-----|
| AURA/USD | $+200.99 | 1 | 100% |
| AUDIO/USD | $+178.92 | 1 | 100% |
| DEEP/USD | $+61.14 | 1 | 100% |
| BANANAS31/USD | $+7.82 | 1 | 100% |
| ARPA/USD | $-7.86 | 1 | 0% |

### Fold 3 (P&L=$546.97, 10 trades, 10 coins)

| Coin | P&L | Trades | WR% |
|------|-----|--------|-----|
| AURA/USD | $+208.20 | 1 | 100% |
| BILLY/USD | $+190.13 | 1 | 100% |
| XL1/USD | $+189.96 | 1 | 100% |
| TLM/USD | $+98.77 | 1 | 100% |
| CVC/USD | $+61.19 | 1 | 100% |

### Fold 4 (P&L=$779.56, 16 trades, 15 coins)

| Coin | P&L | Trades | WR% |
|------|-----|--------|-----|
| XL1/USD | $+422.07 | 2 | 100% |
| SPICE/USD | $+175.51 | 1 | 100% |
| XAN/USD | $+114.71 | 1 | 100% |
| KOBAN/USD | $+106.17 | 1 | 100% |
| SIGMA/USD | $+93.11 | 1 | 100% |

## Cross-Fold Consistency

- **Always profitable** (all folds appeared): 3 coins
- **Mostly profitable** (>=60% folds): 0 coins
- **Fold-specific** (1 fold only): 25 coins

### Always-Profitable Coins

| Coin | Folds | Pos Folds | Total P&L |
|------|-------|-----------|-----------|
| AURA/USD | 3 | 3 | $+418.77 |
| XL1/USD | 2 | 2 | $+612.03 |
| NOBODY/USD | 2 | 2 | $+150.69 |

## Key Findings

1. **tp10 breakeven**: 5.328x (v5: 6.394x on same 295 coins, A5: 1.71x on 316 coins)
2. **v5 more stress-resilient**: v5 survives 1.07x more fee stress
3. **Fold concentration**: tp10=36.1% vs v5=34.2%
   - v5 has better fold distribution (lower is better)
4. **Walk-forward**: tp10=5/5 vs v5=4/5
5. **Consistent coins**: 3 always-profitable across all folds
6. **Fold-specific coins**: 25 appear in only 1 fold (noise risk)

## Recommendation

tp10_sl4_tl8 breakeven at 5.33x (v5 at 6.39x on same 295 coins). tp10 SURVIVES 2x uniform stress. WF: tp10 5/5 fold_conc=36.1%, v5 4/5 fold_conc=34.2%. 3 coins consistently profitable across all folds.

---
*Generated by run_part2_stress_295.py at 2026-02-16 00:26*