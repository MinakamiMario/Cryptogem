# P0-5: Losers Cluster Diagnostics

**Agent**: C7-E
**Date**: 2026-02-16 01:30
**Commit**: 427d5e0
**Universe**: T1(100) + T2(216) = 316 coins
**Params**: dev=2.0, tp=8, sl=5, tl=10
**Fees**: T1=12.5bps, T2=23.5bps (stress 2x)
**Runtime**: 30.2s

## 1. Per-Coin P&L Attribution (All 316 Coins)

- Coins in universe: 316
- Coins with trades: 47
- Coins with NO trades: 269
- Net-negative: 21
- Net-positive: 26
- **Baseline P&L**: $370 (PF=1.138)

### Full Per-Coin Table (sorted worst first)

| # | Coin | Tier | P&L | Trades | WR% | Avg/Trade | Fees Est | Vol $/d |
|---|------|------|-----|--------|-----|-----------|----------|---------|
| 1 | KET/USD | T2 | $-301.24 | 3 | 0% | $-100.41 | $26 | $2413317 |
| 2 | TANSSI/USD | T2 | $-218.51 | 2 | 0% | $-109.26 | $19 | $6796003 |
| 3 | ANIME/USD | T2 | $-162.27 | 2 | 0% | $-81.13 | $20 | $1474946 |
| 4 | DBR/USD | T2 | $-144.67 | 2 | 0% | $-72.34 | $21 | $438139 |
| 5 | HOUSE/USD | T2 | $-128.54 | 1 | 0% | $-128.54 | $11 | $2967062 |
| 6 | ALKIMI/USD | T2 | $-117.25 | 4 | 25% | $-29.31 | $35 | $1845190 |
| 7 | TITCOIN/USD | T1 | $-115.35 | 1 | 0% | $-115.35 | $6 | $26079792 |
| 8 | LMWR/USD | T2 | $-109.60 | 1 | 0% | $-109.60 | $9 | $1786634 |
| 9 | ESX/USD | T2 | $-108.10 | 1 | 0% | $-108.10 | $9 | $822189 |
| 10 | ODOS/USD | T2 | $-103.61 | 1 | 0% | $-103.61 | $9 | $2628469 |
| 11 | MXC/USD | T1 | $-97.42 | 1 | 0% | $-97.42 | $5 | $29051722 |
| 12 | PERP/USD | T2 | $-93.42 | 1 | 0% | $-93.42 | $8 | $947275 |
| 13 | GST/USD | T1 | $-92.31 | 1 | 0% | $-92.31 | $4 | $3031881 |
| 14 | SUKU/USD | T2 | $-88.35 | 2 | 50% | $-44.18 | $18 | $489141 |
| 15 | TOSHI/USD | T1 | $-68.75 | 1 | 0% | $-68.75 | $5 | $487632728 |
| 16 | PNUT/USD | T2 | $-46.20 | 1 | 0% | $-46.20 | $10 | $2561871 |
| 17 | RARI/USD | T2 | $-32.04 | 1 | 0% | $-32.04 | $11 | $344726 |
| 18 | AI3/USD | T2 | $-26.78 | 2 | 0% | $-13.39 | $18 | $106728 |
| 19 | POLIS/USD | T2 | $-25.13 | 1 | 0% | $-25.13 | $8 | $126692 |
| 20 | CFG/USD | T2 | $-16.18 | 1 | 0% | $-16.18 | $9 | $268554 |
| 21 | WMTX/USD | T2 | $-1.19 | 1 | 0% | $-1.19 | $9 | $413706 |
| 22 | SIGMA/USD | T2 | $+2.57 | 3 | 33% | $+0.86 | $31 | $1165629 |
| 23 | MEME/USD | T1 | $+7.17 | 1 | 100% | $+7.17 | $6 | $16221031 |
| 24 | BANANAS31/USD | T1 | $+7.64 | 1 | 100% | $+7.64 | $5 | $10576749 |
| 25 | BTT/USD | T1 | $+8.24 | 2 | 100% | $+4.12 | $10 | $24531423471 |
| 26 | BLZ/USD | T2 | $+9.15 | 1 | 100% | $+9.15 | $9 | $878155 |
| 27 | XYO/USD | T2 | $+10.12 | 3 | 33% | $+3.37 | $28 | $3810659 |
| 28 | ELX/USD | T1 | $+16.12 | 2 | 50% | $+8.06 | $10 | $8166168 |
| 29 | OGN/USD | T2 | $+22.87 | 1 | 100% | $+22.87 | $8 | $268904 |
| 30 | DOGS/USD | T1 | $+33.53 | 1 | 100% | $+33.53 | $4 | $90165563 |
| 31 | SBR/USD | T1 | $+41.56 | 1 | 100% | $+41.56 | $5 | $4702556 |
| 32 | ALT/USD | T2 | $+44.58 | 1 | 100% | $+44.58 | $9 | $106531 |
| 33 | BODEN/USD | T2 | $+47.53 | 1 | 100% | $+47.53 | $8 | $3787930 |
| 34 | REKT/USD | T1 | $+49.10 | 2 | 50% | $+24.55 | $10 | $140788093644 |
| 35 | KOBAN/USD | T1 | $+84.58 | 2 | 50% | $+42.29 | $11 | $180484925 |
| 36 | XAN/USD | T1 | $+108.01 | 1 | 100% | $+108.01 | $5 | $1858204 |
| 37 | BILLY/USD | T2 | $+114.90 | 1 | 100% | $+114.90 | $7 | $2863589 |
| 38 | GOMINING/USD | T2 | $+121.39 | 2 | 50% | $+60.70 | $19 | $191131 |
| 39 | NYM/USD | T2 | $+123.78 | 2 | 50% | $+61.89 | $21 | $160532 |
| 40 | CVC/USD | T2 | $+132.81 | 1 | 100% | $+132.81 | $8 | $200509 |
| 41 | SPICE/USD | T2 | $+135.43 | 1 | 100% | $+135.43 | $8 | $4127279213 |
| 42 | TOKEN/USD | T2 | $+145.58 | 1 | 100% | $+145.58 | $9 | $1700100 |
| 43 | AUDIO/USD | T2 | $+148.38 | 1 | 100% | $+148.38 | $9 | $113269 |
| 44 | GHIBLI/USD | T1 | $+158.04 | 1 | 100% | $+158.04 | $5 | $63176232 |
| 45 | NOBODY/USD | T2 | $+164.95 | 2 | 100% | $+82.48 | $19 | $1370525 |
| 46 | AURA/USD | T2 | $+260.49 | 3 | 100% | $+86.83 | $26 | $360322 |
| 47 | XL1/USD | T1 | $+468.30 | 3 | 100% | $+156.10 | $15 | $13088231 |

## 2. Loser Analysis

- **Total losers**: 21 coins, total loss: $-2096.91
- **Total winners**: 26 coins, total gain: $+2466.82
- **Net**: $+369.91

### Tier Breakdown

| Group | T1 Count | T1 P&L | T2 Count | T2 P&L |
|-------|----------|--------|----------|--------|
| Losers | 4 | $-373.83 | 17 | $-1723.08 |
| Winners | 11 | $+982.29 | 15 | $+1484.53 |

### Volume Profiles

| Group | Count | Median $/d | P25 $/d | P75 $/d | Mean $/d |
|-------|-------|-----------|---------|---------|----------|
| losers | 21 | $1786634 | $438139 | $2967062 | $27248894 |
| winners | 26 | $3787930 | $360322 | $16221031 | $6532777453 |

## 3. Walk-Forward Fold Analysis

### Fold Summaries

| Fold | Trades | P&L | Positive |
|------|--------|-----|----------|
| 0 | 13 | $416 | YES |
| 1 | 16 | $-199 | NO |
| 2 | 13 | $-499 | NO |
| 3 | 15 | $227 | YES |
| 4 | 16 | $608 | YES |

### Persistent Losers (negative in >=3/5 folds): 1 coins

| Coin | Tier | Neg Folds | Fold P&Ls |
|------|------|-----------|-----------|
| ALKIMI/USD | T2 | 3/3 | F2=$-76, F3=$-34, F4=$-2 |

### Fold-Specific Losers (negative in 1-2 folds): 27 coins

| Coin | Tier | Neg Folds | Fold P&Ls |
|------|------|-----------|-----------|
| KET/USD | T2 | 2/2 | F0=$-110, F3=$-224 |
| ANIME/USD | T2 | 2/2 | F0=$-46, F2=$-108 |
| XYO/USD | T2 | 2/3 | F0=$+29, F1=$-8, F4=$-12 |
| TANSSI/USD | T2 | 2/2 | F2=$-109, F4=$-113 |
| AI3/USD | T2 | 2/2 | F2=$-11, F4=$-16 |
| ELX/USD | T1 | 1/2 | F0=$-113, F3=$+139 |
| HOUSE/USD | T2 | 1/1 | F0=$-129 |
| PNUT/USD | T2 | 1/1 | F0=$-10 |
| TITCOIN/USD | T1 | 1/1 | F1=$-105 |
| TOSHI/USD | T1 | 1/1 | F1=$-62 |
| REKT/USD | T1 | 1/2 | F0=$+155, F1=$-96 |
| DBR/USD | T2 | 1/1 | F1=$-137 |
| SIGMA/USD | T2 | 1/2 | F0=$+153, F1=$-142 |
| RARI/USD | T2 | 1/1 | F1=$-30 |
| NYM/USD | T2 | 1/2 | F0=$+165, F1=$-39 |
| KOBAN/USD | T1 | 1/2 | F2=$-105, F4=$+190 |
| GOMINING/USD | T2 | 1/2 | F1=$+150, F2=$-34 |
| LMWR/USD | T2 | 1/1 | F2=$-102 |
| ODOS/USD | T2 | 1/1 | F2=$-97 |
| SUKU/USD | T2 | 1/2 | F0=$+10, F2=$-91 |
| POLIS/USD | T2 | 1/1 | F2=$-23 |
| MXC/USD | T1 | 1/1 | F3=$-105 |
| GST/USD | T1 | 1/1 | F3=$-99 |
| PERP/USD | T2 | 1/1 | F3=$-109 |
| CFG/USD | T2 | 1/1 | F3=$-19 |
| WMTX/USD | T2 | 1/1 | F4=$-1 |
| ESX/USD | T2 | 1/1 | F4=$-120 |

### Per-Fold Negative Coins

**Fold 0**: 5 negative coins: ANIME/USD, ELX/USD, HOUSE/USD, KET/USD, PNUT/USD

**Fold 1**: 8 negative coins: DBR/USD, NYM/USD, RARI/USD, REKT/USD, SIGMA/USD, TITCOIN/USD, TOSHI/USD, XYO/USD

**Fold 2**: 10 negative coins: AI3/USD, ALKIMI/USD, ANIME/USD, GOMINING/USD, KOBAN/USD, LMWR/USD, ODOS/USD, POLIS/USD, SUKU/USD, TANSSI/USD

**Fold 3**: 6 negative coins: ALKIMI/USD, CFG/USD, GST/USD, KET/USD, MXC/USD, PERP/USD

**Fold 4**: 6 negative coins: AI3/USD, ALKIMI/USD, ESX/USD, TANSSI/USD, WMTX/USD, XYO/USD

## 4. T2 Volume Quartile Analysis

| Quartile | Coins | Trades | P&L | WR% | PF | Vol Median $/d | Neg Coins | Pos Coins | No Trades |
|----------|-------|--------|-----|-----|----|-----------      |-----------|-----------|-----------|
| Q1 | 54 | 12 | $+525.72 | 50.0% | 4.608 | $189617 | 3 | 6 | 45 |
| Q2 | 54 | 11 | $-104.71 | 45.5% | 0.727 | $526889 | 5 | 2 | 47 |
| Q3 | 54 | 14 | $-169.42 | 35.7% | 0.735 | $1275687 | 4 | 3 | 47 |
| Q4 | 54 | 14 | $-490.11 | 28.6% | 0.400 | $3153729 | 5 | 4 | 45 |

## 5. Exclusion Candidates

### Candidate Blacklist (14 coins)

| Coin | Tier | P&L | Trades | Vol $/d | In Excl-21 | Persistent | Reason |
|------|------|-----|--------|---------|------------|------------|--------|
| KET/USD | T2 | $-301.24 | 3 | $2413317 | YES | NO | large loss ($-301) |
| TANSSI/USD | T2 | $-218.51 | 2 | $6796003 | YES | NO | large loss ($-219) |
| ANIME/USD | T2 | $-162.27 | 2 | $1474946 | YES | NO | large loss ($-162) |
| DBR/USD | T2 | $-144.67 | 2 | $438139 | YES | NO | large loss ($-145) |
| HOUSE/USD | T2 | $-128.54 | 1 | $2967062 | YES | NO | single-trade loser (P&L < -$50) + large loss ($-129) |
| ALKIMI/USD | T2 | $-117.25 | 4 | $1845190 | YES | YES | persistent (3/5 folds negative) + large loss ($-117) |
| TITCOIN/USD | T1 | $-115.35 | 1 | $26079792 | YES | NO | single-trade loser (P&L < -$50) + large loss ($-115) |
| LMWR/USD | T2 | $-109.60 | 1 | $1786634 | YES | NO | single-trade loser (P&L < -$50) + large loss ($-110) |
| ESX/USD | T2 | $-108.10 | 1 | $822189 | YES | NO | single-trade loser (P&L < -$50) + large loss ($-108) |
| ODOS/USD | T2 | $-103.61 | 1 | $2628469 | YES | NO | single-trade loser (P&L < -$50) + large loss ($-104) |
| MXC/USD | T1 | $-97.42 | 1 | $29051722 | YES | NO | single-trade loser (P&L < -$50) |
| PERP/USD | T2 | $-93.42 | 1 | $947275 | YES | NO | single-trade loser (P&L < -$50) |
| GST/USD | T1 | $-92.31 | 1 | $3031881 | YES | NO | single-trade loser (P&L < -$50) |
| TOSHI/USD | T1 | $-68.75 | 1 | $487632728 | YES | NO | single-trade loser (P&L < -$50) |

### New Candidates NOT in EXCLUDED_21: 0

### Whitelist (should NOT exclude): 4

- **AI3/USD** [T2]: P&L=$-26.78, vol=$106728/d, small loss + high volume + not persistent
- **POLIS/USD** [T2]: P&L=$-25.13, vol=$126692/d, small loss + high volume + not persistent
- **CFG/USD** [T2]: P&L=$-16.18, vol=$268554/d, small loss + high volume + not persistent
- **WMTX/USD** [T2]: P&L=$-1.19, vol=$413706/d, small loss + high volume + not persistent

## 6. Gate Evaluation Comparison

| Strategy | Coins | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Score |
|----------|-------|--------|----|--------|-----|----|-----------|-------|
| full_316 | 316 | 72 | 1.138 | $86.07 | 53.1% | 3/5 | 48.6% | **3/7** |
| excl_21_current | 295 | 56 | 2.834 | $761.38 | 8.6% | 4/5 | 34.2% | **7/7** |
| excl_new_candidates | 295 | 56 | 2.834 | $761.38 | 8.6% | 4/5 | 34.2% | **7/7** |

### full_316 (316 coins)

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 16.75 | >= 10 | PASS |
| G2 | Max gap (days) | 1.42 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 86.07 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | -32.74 | > $0 | **FAIL** |
| G5 | Max DD% | 53.1 | <= 20% | **FAIL** |
| G6 | WF folds positive | 3/5 | >= 4/5 | **FAIL** |
| G8 | Top-1 fold conc. | 48.6% | < 35% | **FAIL** |

Walk-Forward Folds:

- Fold 0: 13 trades, $416, YES
- Fold 1: 16 trades, $-199, NO
- Fold 2: 13 trades, $-499, NO
- Fold 3: 15 trades, $227, YES
- Fold 4: 16 trades, $608, YES

### excl_21_current (295 coins)

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.03 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 761.38 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 570.62 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 34.2% | < 35% | PASS |

Walk-Forward Folds:

- Fold 0: 10 trades, $909, YES
- Fold 1: 13 trades, $58, YES
- Fold 2: 9 trades, $-18, NO
- Fold 3: 9 trades, $792, YES
- Fold 4: 15 trades, $913, YES

### excl_new_candidates (295 coins)

| Gate | Metric | Value | Threshold | Verdict |
|------|--------|-------|-----------|---------|
| G1 | Trades/week | 13.03 | >= 10 | PASS |
| G2 | Max gap (days) | 1.5 | <= 2.5 | PASS |
| G3 | Exp/week (market) | 761.38 | > $0 | PASS |
| G4 | Exp/week (P95 stress) | 570.62 | > $0 | PASS |
| G5 | Max DD% | 8.6 | <= 20% | PASS |
| G6 | WF folds positive | 4/5 | >= 4/5 | PASS |
| G8 | Top-1 fold conc. | 34.2% | < 35% | PASS |

Walk-Forward Folds:

- Fold 0: 10 trades, $909, YES
- Fold 1: 13 trades, $58, YES
- Fold 2: 9 trades, $-18, NO
- Fold 3: 9 trades, $792, YES
- Fold 4: 15 trades, $913, YES

## 7. Verdict

**PARTIAL: T2 dominates losses but not clearly low-volume concentrated**

- Loser T2%: 81.0% of losers are T2
- Loser T2 loss%: 82.2% of total loss from T2
- T2 Q1 (lowest vol) P&L: $+525.72
- T2 Q4 (highest vol) P&L: $-490.11
- Persistent losers (>=3/5 folds): 1 coins
- New exclusion candidates: 0 coins
- Current EXCLUDED_21 confirmed: 14/21

### All Net-Negative Coins

| # | Coin | Tier | P&L | Trades | WR% | Vol $/d | Persistent | In Excl-21 |
|---|------|------|-----|--------|-----|---------|------------|------------|
| 1 | KET/USD | T2 | $-301.24 | 3 | 0% | $2413317 | NO | YES |
| 2 | TANSSI/USD | T2 | $-218.51 | 2 | 0% | $6796003 | NO | YES |
| 3 | ANIME/USD | T2 | $-162.27 | 2 | 0% | $1474946 | NO | YES |
| 4 | DBR/USD | T2 | $-144.67 | 2 | 0% | $438139 | NO | YES |
| 5 | HOUSE/USD | T2 | $-128.54 | 1 | 0% | $2967062 | NO | YES |
| 6 | ALKIMI/USD | T2 | $-117.25 | 4 | 25% | $1845190 | YES | YES |
| 7 | TITCOIN/USD | T1 | $-115.35 | 1 | 0% | $26079792 | NO | YES |
| 8 | LMWR/USD | T2 | $-109.60 | 1 | 0% | $1786634 | NO | YES |
| 9 | ESX/USD | T2 | $-108.10 | 1 | 0% | $822189 | NO | YES |
| 10 | ODOS/USD | T2 | $-103.61 | 1 | 0% | $2628469 | NO | YES |
| 11 | MXC/USD | T1 | $-97.42 | 1 | 0% | $29051722 | NO | YES |
| 12 | PERP/USD | T2 | $-93.42 | 1 | 0% | $947275 | NO | YES |
| 13 | GST/USD | T1 | $-92.31 | 1 | 0% | $3031881 | NO | YES |
| 14 | SUKU/USD | T2 | $-88.35 | 2 | 50% | $489141 | NO | YES |
| 15 | TOSHI/USD | T1 | $-68.75 | 1 | 0% | $487632728 | NO | YES |
| 16 | PNUT/USD | T2 | $-46.20 | 1 | 0% | $2561871 | NO | YES |
| 17 | RARI/USD | T2 | $-32.04 | 1 | 0% | $344726 | NO | YES |
| 18 | AI3/USD | T2 | $-26.78 | 2 | 0% | $106728 | NO | YES |
| 19 | POLIS/USD | T2 | $-25.13 | 1 | 0% | $126692 | NO | YES |
| 20 | CFG/USD | T2 | $-16.18 | 1 | 0% | $268554 | NO | YES |
| 21 | WMTX/USD | T2 | $-1.19 | 1 | 0% | $413706 | NO | YES |

---
*Generated by run_part2_losers_cluster_001.py at 2026-02-16 01:30*