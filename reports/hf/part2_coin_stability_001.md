# C8-E: Coin Stability / Edge Persistence Analysis

**Date**: 2026-02-16 01:42 | **Commit**: 1787377 | **Runtime**: 27.5s
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Fees**: MEXC Market T1=12.5bps T2=23.5bps | Stress 2x T1=25.0bps T2=47.0bps

## Verdict

| Check | Result |
|-------|--------|
| Edge Persistence | **WEAK** |
| Full 295 Gates | **PASS** |
| Stable-Winners-Only Gates | **FAIL** |

**Recommendation**: Limited stable winners (1 coins). WARNING: One-shot coins dominate profit (51%). Stable-winners-only fails: G1_throughput, G2_max_gap, G5_top1_share, G6_wf_folds.

## Gate Check: Full 295 Universe

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_throughput | 13.05 | >= 10/wk | PASS |
| G2_max_gap | 1.42 | <= 2.5d | PASS |
| G3_pnl | 3272.13 | > $0 | PASS |
| G5_top1_share | 6.16 | <= 20% | PASS |
| G6_wf_folds | 4.00 | >= 4/5 | PASS |
| G8_dd | 8.63 | < 35% | PASS |
| G4_stress_pnl | 2452.31 | > $0 | PASS |

**Baseline**: 56 trades, PF=2.834, WR=64.3%, P&L=$3272.13, DD=8.6%

### Walk-Forward Detail (5-Fold)

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 10 | $909.08 | YES |
| 1 | 13 | $57.53 | YES |
| 2 | 9 | $-17.57 | no |
| 3 | 9 | $792.44 | YES |
| 4 | 15 | $913.43 | YES |

## Coin Stability Analysis

| Category | Count | P&L | Coins |
|----------|-------|-----|-------|
| Stable Winners (>=3/5 positive) | 1 | $486.12 | AURA/USD |
| Stable Losers (>=3/5 negative) | 0 | $0.00 |  |
| One-Shot (1 fold) | 31 | $1451.33 | ALPHA/USD, ALT/USD, ARPA/USD, AUDIO/USD, BANANAS31/USD, BILLY/USD, BLZ/USD, BODEN/USD... |
| Mixed | 9 | $1334.69 | BTT/USD, ELX/USD, GOMINING/USD, KOBAN/USD, NYM/USD, REKT/USD, SIGMA/USD, XL1/USD... |

### Profit Concentration

| Source | % of Total Profit |
|--------|-------------------|
| Stable Winners | 9.8% |
| One-Shots | 50.9% |
| Total Profit | $5056.61 |

### Fold Diversity

| Fold | Unique Coins | Trades | P&L |
|------|-------------|--------|-----|
| 0 | 10 | 10 | $909.08 |
| 1 | 11 | 13 | $57.53 |
| 2 | 9 | 9 | $-17.57 |
| 3 | 9 | 9 | $792.44 |
| 4 | 14 | 15 | $913.43 |

## Per-Coin Profiles

| Coin | Class | Folds Present | Folds Positive | Full P&L | Full Trades | Consistency | Fold P&Ls |
|------|-------|--------------|----------------|----------|-------------|-------------|-----------|
| XL1/USD | mixed | 2 | 2 | $549.02 | 3 | 1.000 | F3:$169.9, F4:$331.1 |
| AURA/USD | stable_winner | 3 | 3 | $486.12 | 4 | 1.000 | F1:$9.5, F2:$153.7, F3:$161.5 |
| INIT/USD | one_shot | 1 | 1 | $311.41 | 1 | 1.000 | F4:$167.6 |
| SPICE/USD | one_shot | 1 | 1 | $275.41 | 1 | 1.000 | F4:$148.3 |
| CVC/USD | one_shot | 1 | 1 | $265.74 | 1 | 1.000 | F3:$173.6 |
| SIGMA/USD | mixed | 3 | 2 | $259.21 | 4 | 0.667 | F0:$177.1, F1:$-151.9, F4:$154.2 |
| BILLY/USD | one_shot | 1 | 1 | $229.90 | 1 | 1.000 | F3:$150.2 |
| AUDIO/USD | one_shot | 1 | 1 | $214.20 | 1 | 1.000 | F2:$145.6 |
| NOBODY/USD | one_shot | 1 | 1 | $208.30 | 1 | 1.000 | F1:$154.9 |
| TOKEN/USD | one_shot | 1 | 1 | $164.76 | 1 | 1.000 | F0:$164.8 |
| GOMINING/USD | mixed | 2 | 1 | $164.30 | 2 | 0.500 | F1:$161.7, F2:$-36.1 |
| GHIBLI/USD | one_shot | 1 | 1 | $158.04 | 1 | 1.000 | F0:$158.0 |
| JUNO/USD | one_shot | 1 | 1 | $150.22 | 1 | 1.000 | F0:$150.2 |
| NYM/USD | mixed | 2 | 1 | $137.49 | 2 | 0.500 | F0:$190.4, F1:$-39.4 |
| XAN/USD | one_shot | 1 | 1 | $126.63 | 1 | 1.000 | F4:$109.5 |
| KOBAN/USD | mixed | 2 | 1 | $111.46 | 2 | 0.500 | F2:$-105.3, F4:$190.0 |
| BODEN/USD | one_shot | 1 | 1 | $96.21 | 1 | 1.000 | F3:$62.9 |
| ALT/USD | one_shot | 1 | 1 | $85.76 | 1 | 1.000 | F4:$46.2 |
| ALPHA/USD | one_shot | 1 | 1 | $83.36 | 1 | 1.000 | F1:$62.0 |
| OGN/USD | one_shot | 1 | 1 | $47.35 | 1 | 1.000 | F4:$25.5 |
| PHA/USD | one_shot | 1 | 1 | $46.96 | 1 | 1.000 | F4:$25.3 |
| SBR/USD | one_shot | 1 | 1 | $43.75 | 1 | 1.000 | F1:$39.8 |
| REKT/USD | mixed | 2 | 1 | $43.54 | 2 | 0.500 | F0:$154.8, F1:$-101.2 |
| DOGS/USD | one_shot | 1 | 1 | $39.30 | 1 | 1.000 | F3:$40.2 |
| ELX/USD | mixed | 2 | 1 | $38.38 | 2 | 0.500 | F0:$-113.0, F3:$154.8 |
| XYO/USD | mixed | 2 | 1 | $21.80 | 2 | 0.500 | F0:$33.0, F1:$-8.3 |
| BLZ/USD | one_shot | 1 | 1 | $10.35 | 1 | 1.000 | F0:$10.3 |
| BTT/USD | mixed | 2 | 2 | $9.49 | 2 | 1.000 | F1:$1.4, F4:$6.9 |
| MEME/USD | one_shot | 1 | 1 | $8.40 | 1 | 1.000 | F4:$7.3 |
| BANANAS31/USD | one_shot | 1 | 1 | $8.04 | 1 | 1.000 | F2:$7.8 |
| DEEP/USD | one_shot | 1 | 0 | $-10.19 | 1 | 0.000 | F2:$-6.9 |
| CAMP/USD | one_shot | 1 | 0 | $-36.12 | 1 | 0.000 | F0:$-16.7 |
| SAMO/USD | one_shot | 1 | 0 | $-38.34 | 1 | 0.000 | F2:$-26.1 |
| ARPA/USD | one_shot | 1 | 0 | $-44.37 | 1 | 0.000 | F2:$-30.1 |
| SAROS/USD | one_shot | 1 | 0 | $-45.37 | 1 | 0.000 | F3:$-29.6 |
| SGB/USD | one_shot | 1 | 0 | $-77.99 | 1 | 0.000 | F1:$-70.9 |
| SUSHI/USD | one_shot | 1 | 0 | $-95.89 | 1 | 0.000 | F4:$-51.6 |
| DRV/USD | one_shot | 1 | 0 | $-139.32 | 1 | 0.000 | F3:$-91.0 |
| MF/USD | one_shot | 1 | 0 | $-176.71 | 1 | 0.000 | F2:$-120.1 |
| PUPS/USD | one_shot | 1 | 0 | $-215.17 | 1 | 0.000 | F4:$-115.8 |
| GLMR/USD | one_shot | 1 | 0 | $-243.29 | 1 | 0.000 | F4:$-131.0 |

## Stable-Winners-Only Backtest

**Universe**: 1 coins (T1:0 T2:1)

**Baseline**: 4 trades, PF=64.611, WR=75.0%, P&L=$321.87, DD=0.2%

**Walk-Forward**: 3/5 positive

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 0 | $0.00 | no |
| 1 | 2 | $8.77 | YES |
| 2 | 1 | $150.22 | YES |
| 3 | 1 | $150.22 | YES |
| 4 | 0 | $0.00 | no |

**Stress 2x**: PF=20.295, P&L=$279.20

### Gate Check (Stable Winners Only)

| Gate | Value | Threshold | Verdict |
|------|-------|-----------|---------|
| G1_throughput | 0.93 | >= 10/wk | **FAIL** |
| G2_max_gap | 9.21 | <= 2.5d | **FAIL** |
| G3_pnl | 321.87 | > $0 | PASS |
| G5_top1_share | 49.62 | <= 20% | **FAIL** |
| G6_wf_folds | 3.00 | >= 4/5 | **FAIL** |
| G8_dd | 0.25 | < 35% | PASS |
| G4_stress_pnl | 279.20 | > $0 | PASS |

**All gates**: FAIL

---
*Generated by strategies/hf/screening/run_part2_coin_stability_001.py at 2026-02-16 01:42*