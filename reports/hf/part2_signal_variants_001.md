# C8-D: Signal Variant Exploration (P1-7)

**Date**: 2026-02-16 01:41
**Agent**: C8-D
**Commit**: 1787377
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0)
**Cost**: MEXC Market (T1=12.5bps, T2=23.5bps)
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 30.3s

## Gate Thresholds (STRICT)

| Gate | Metric | Threshold |
|------|--------|-----------|
| G1 | trades/week | >= 10 |
| G2 | max gap | <= 2.5 days |
| G3 | exp/week | > $0 |
| G4 | exp/week (stress 2x) | > $0 |
| G5 | max DD | <= 20% |
| G6 | WF positive folds | >= 4/5 |
| G8 | fold concentration | < 35% |

## Variant Matrix

| Label | TP% | SL% | TL | R:R | Category |
|-------|-----|-----|----|-----|----------|
| baseline_v5 | 8 | 5 | 10 | 1.6:1 | baseline |
| tp10_sl3 | 10 | 3 | 10 | 3.3:1 | asymmetric R:R |
| tp10_sl4 | 10 | 4 | 10 | 2.5:1 | asymmetric R:R |
| tp12_sl5 | 12 | 5 | 10 | 2.4:1 | asymmetric R:R |
| tp6_sl3 | 6 | 3 | 10 | 2.0:1 | asymmetric R:R |
| tl6 | 8 | 5 | 6 | 1.6:1 | time limit |
| tl8 | 8 | 5 | 8 | 1.6:1 | time limit |
| sl7_tp6 | 6 | 7 | 10 | 0.9:1 | sl7 combos |
| sl7_tp10 | 10 | 7 | 10 | 1.4:1 | sl7 combos |
| sl7_tp12 | 12 | 7 | 10 | 1.7:1 | sl7 combos |

## Results: All Variants

| Label | TP | SL | TL | R:R | Trades | PF | P&L | Exp/Wk | DD%% | WF | FC | Gap | Gates |
|-------|----|----|----|----|--------|----|-----|--------|------|----|----|-----|-------|
| baseline_v5 | 8 | 5 | 10 | 1.6 | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.4 | **ALL** |
| tp10_sl3 | 10 | 3 | 10 | 3.3 | 57 | 2.807 | $2874 | $669.68 | 12.0 | 3/5 | 0.38 | 1.4 | 5/7 |
| tp10_sl4 | 10 | 4 | 10 | 2.5 | 57 | 2.490 | $2864 | $667.28 | 11.4 | 4/5 | 0.37 | 1.4 | 6/7 |
| tp12_sl5 | 12 | 5 | 10 | 2.4 | 55 | 2.867 | $3564 | $830.34 | 13.7 | 4/5 | 0.36 | 1.3 | 6/7 |
| tp6_sl3 | 6 | 3 | 10 | 2.0 | 58 | 2.427 | $1889 | $440.22 | 16.4 | 4/5 | 0.43 | 1.4 | 6/7 |
| tl6 | 8 | 5 | 6 | 1.6 | 61 | 2.517 | $2451 | $571.06 | 12.9 | 5/5 | 0.37 | 1.4 | 6/7 |
| tl8 | 8 | 5 | 8 | 1.6 | 59 | 2.949 | $3112 | $725.13 | 11.4 | 4/5 | 0.35 | 1.4 | **ALL** |
| sl7_tp6 | 6 | 7 | 10 | 0.9 | 55 | 2.604 | $2264 | $527.61 | 9.8 | 4/5 | 0.36 | 1.4 | 6/7 |
| sl7_tp10 | 10 | 7 | 10 | 1.4 | 54 | 2.712 | $3064 | $713.99 | 9.5 | 5/5 | 0.36 | 1.4 | 6/7 |
| sl7_tp12 | 12 | 7 | 10 | 1.7 | 54 | 2.664 | $3378 | $787.16 | 16.9 | 4/5 | 0.36 | 1.3 | 6/7 |

## Gate Detail Per Variant

| Label | G1 | G2 | G3 | G4 | G5 | G6 | G8 | Total |
|-------|----|----|----|----|----|----|-----|-------|
| baseline_v5 | P | P | P | P | P | P | P | **ALL** |
| tp10_sl3 | P | P | P | P | P | **F** | **F** | 5/7 |
| tp10_sl4 | P | P | P | P | P | P | **F** | 6/7 |
| tp12_sl5 | P | P | P | P | P | P | **F** | 6/7 |
| tp6_sl3 | P | P | P | P | P | P | **F** | 6/7 |
| tl6 | P | P | P | P | P | P | **F** | 6/7 |
| tl8 | P | P | P | P | P | P | P | **ALL** |
| sl7_tp6 | P | P | P | P | P | P | **F** | 6/7 |
| sl7_tp10 | P | P | P | P | P | P | **F** | 6/7 |
| sl7_tp12 | P | P | P | P | P | P | **F** | 6/7 |

## Stress Test (2x fees)

| Label | Baseline PF | Stress PF | Baseline Exp/Wk | Stress Exp/Wk | Survives? |
|-------|-------------|-----------|-----------------|---------------|-----------|
| baseline_v5 | 2.834 | 2.306 | $762.44 | $571.41 | YES |
| tp10_sl3 | 2.807 | 2.202 | $669.68 | $490.48 | YES |
| tp10_sl4 | 2.490 | 2.009 | $667.28 | $484.02 | YES |
| tp12_sl5 | 2.867 | 2.321 | $830.34 | $634.12 | YES |
| tp6_sl3 | 2.427 | 1.860 | $440.22 | $291.56 | YES |
| tl6 | 2.517 | 1.927 | $571.06 | $390.60 | YES |
| tl8 | 2.949 | 2.294 | $725.13 | $528.15 | YES |
| sl7_tp6 | 2.604 | 2.035 | $527.61 | $367.47 | YES |
| sl7_tp10 | 2.712 | 2.175 | $713.99 | $528.12 | YES |
| sl7_tp12 | 2.664 | 2.182 | $787.16 | $596.87 | YES |

## Walk-Forward Fold Detail

### baseline_v5 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $909.08 | YES |
| 1 | 13 | $57.53 | YES |
| 2 | 9 | $-17.57 | NO |
| 3 | 9 | $792.44 | YES |
| 4 | 15 | $913.43 | YES |

### tp10_sl3 (WF=3/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $900.95 | YES |
| 1 | 14 | $-31.18 | NO |
| 2 | 9 | $-157.48 | NO |
| 3 | 9 | $734.85 | YES |
| 4 | 15 | $996.67 | YES |

### tp10_sl4 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $894.16 | YES |
| 1 | 14 | $-48.77 | NO |
| 2 | 9 | $33.40 | YES |
| 3 | 9 | $706.02 | YES |
| 4 | 15 | $808.54 | YES |

### tp12_sl5 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $1098.00 | YES |
| 1 | 13 | $30.11 | YES |
| 2 | 9 | $-200.59 | NO |
| 3 | 9 | $865.05 | YES |
| 4 | 14 | $1111.56 | YES |

### tp6_sl3 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $463.45 | YES |
| 1 | 14 | $68.45 | YES |
| 2 | 9 | $-226.71 | NO |
| 3 | 9 | $578.72 | YES |
| 4 | 16 | $836.48 | YES |

### tl6 (WF=5/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 12 | $792.26 | YES |
| 1 | 14 | $14.48 | YES |
| 2 | 9 | $24.98 | YES |
| 3 | 10 | $558.68 | YES |
| 4 | 16 | $823.00 | YES |

### tl8 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 11 | $851.03 | YES |
| 1 | 14 | $-26.33 | NO |
| 2 | 9 | $82.10 | YES |
| 3 | 10 | $756.03 | YES |
| 4 | 15 | $893.00 | YES |

### sl7_tp6 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $588.01 | YES |
| 1 | 12 | $111.29 | YES |
| 2 | 9 | $-45.32 | NO |
| 3 | 9 | $572.90 | YES |
| 4 | 15 | $722.49 | YES |

### sl7_tp10 (WF=5/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $822.00 | YES |
| 1 | 12 | $9.52 | YES |
| 2 | 9 | $115.93 | YES |
| 3 | 9 | $639.04 | YES |
| 4 | 14 | $882.27 | YES |

### sl7_tp12 (WF=4/5)

| Fold | Trades | P&L | Positive? |
|------|--------|-----|-----------|
| 0 | 10 | $1048.12 | YES |
| 1 | 12 | $47.38 | YES |
| 2 | 9 | $-198.38 | NO |
| 3 | 9 | $819.58 | YES |
| 4 | 14 | $1061.71 | YES |

## Delta vs Baseline

| Label | dExp/Wk | dDD%% | dTrades | dPF | Better? |
|-------|---------|-------|---------|-----|---------|
| tp10_sl3 | -92.76 | +3.3 | +1 | -0.027 | no |
| tp10_sl4 | -95.15 | +2.8 | +1 | -0.344 | no |
| tp12_sl5 | +67.90 | +5.1 | -1 | +0.033 | no |
| tp6_sl3 | -322.22 | +7.7 | +2 | -0.407 | no |
| tl6 | -191.38 | +4.3 | +5 | -0.317 | no |
| tl8 | -37.31 | +2.8 | +3 | +0.115 | no |
| sl7_tp6 | -234.82 | +1.2 | -1 | -0.230 | no |
| sl7_tp10 | -48.45 | +0.9 | -2 | -0.122 | no |
| sl7_tp12 | +24.72 | +8.3 | -2 | -0.170 | no |

## Verdict

**2 variant(s) pass ALL 7 strict gates**: baseline_v5, tl8

Best overall: **baseline_v5** (exp/wk=$762.44, DD=8.6%)

No variant beats the baseline exp/wk while passing all gates.

### Key Findings

**R:R Ratio Analysis** (sorted by R:R):
- R:R=0.9 (sl7_tp6): exp/wk=$527.61, DD=9.8%
- R:R=1.4 (sl7_tp10): exp/wk=$713.99, DD=9.5%
- R:R=1.6 (baseline_v5): exp/wk=$762.44, DD=8.6%
- R:R=1.6 (tl6): exp/wk=$571.06, DD=12.9%
- R:R=1.6 (tl8): exp/wk=$725.13, DD=11.4%
- R:R=1.7 (sl7_tp12): exp/wk=$787.16, DD=16.9%
- R:R=2.0 (tp6_sl3): exp/wk=$440.22, DD=16.4%
- R:R=2.4 (tp12_sl5): exp/wk=$830.34, DD=13.7%
- R:R=2.5 (tp10_sl4): exp/wk=$667.28, DD=11.4%
- R:R=3.3 (tp10_sl3): exp/wk=$669.68, DD=12.0%

**Time Limit Effect**:
- tl=10 (baseline_v5): trades=56, exp/wk=$762.44, DD=8.6%
- tl=6 (tl6): trades=61, exp/wk=$571.06, DD=12.9%
- tl=8 (tl8): trades=59, exp/wk=$725.13, DD=11.4%

**SL=7%% Family**:
- sl7_tp6: trades=55, exp/wk=$527.61, DD=9.8%, gates=6/7
- sl7_tp10: trades=54, exp/wk=$713.99, DD=9.5%, gates=6/7
- sl7_tp12: trades=54, exp/wk=$787.16, DD=16.9%, gates=6/7

---
*Generated by strategies/hf/screening/run_part2_signal_variants_001.py at 2026-02-16 01:41*