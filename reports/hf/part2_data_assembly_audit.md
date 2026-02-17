# Part 2 -- Data / Selection Audit (Agent P0-A)

**Datum**: 2026-02-16 09:51
**Commit**: d617e6e
**Universe**: T1(100)+T2(216)
**Signal**: H20 VWAP_DEVIATION v5
**Runtime**: 78.0s

## Doel

Kwantificeer de werkelijke waarde van de EXCLUDED_21 coin exclusion 
en bewijs eventuele biases in de data-assemblage. De exclusion is 
100% in-sample (circulair) en werd NIET bevestigd door expanding-window OOS.

## 1. Data Provenance

| Item | Waarde |
|------|--------|
| Coins in cache | 442 |
| T1 coins | 100 |
| T2 coins | 216 |
| Totaal tiered | 316 |
| Bars (min/max/avg) | 81 / 722 / 710.8 |
| Datumbereik | None tot None |
| EXCLUDED_21 | 21 coins |

## 2. Survivorship Scan

| Categorie | Aantal |
|-----------|--------|
| Short-lived (<200 bars) | 2 |
| Zero-vol tail (>=48 bars) | 6 |
| Gezond | 434 |

**Short-lived coins** (eerste 10):

| Coin | Bars |
|------|------|
| ESP/USD | 81 |
| AZTEC/USD | 86 |

**Zero-vol tail coins** (eerste 10):

| Coin | Trailing zero-vol | Totaal bars |
|------|-------------------|-------------|
| FLY/USD | 278 | 721 |
| EVAA/USD | 189 | 721 |
| ART/USD | 89 | 721 |
| HOLO/USD | 82 | 721 |
| GAIA/USD | 61 | 721 |
| FOREST/USD | 53 | 721 |

## 3. EXCLUDED_21 Circulariteit

Full-sample 316-coin backtest: **72 trades**, PF=1.138, P&L=$370

| Item | Waarde |
|------|--------|
| Coins met trades | 47 |
| Netto-negatieve coins (afgeleid) | 21 |
| Overlap met EXCLUDED_21 | 21 (100.0% Jaccard) |
| Alleen in afgeleid | geen |
| Alleen in EXCLUDED_21 | geen |
| EXCLUDED_21 totaal PnL | $-2096.91 |
| **Circulair?** | **JA** |

**PnL per EXCLUDED_21 coin**:

| Coin | PnL |
|------|-----|
| KET/USD | $-301.24 |
| TANSSI/USD | $-218.51 |
| ANIME/USD | $-162.27 |
| DBR/USD | $-144.67 |
| HOUSE/USD | $-128.54 |
| ALKIMI/USD | $-117.25 |
| TITCOIN/USD | $-115.35 |
| LMWR/USD | $-109.60 |
| ESX/USD | $-108.10 |
| ODOS/USD | $-103.61 |
| MXC/USD | $-97.42 |
| PERP/USD | $-93.42 |
| GST/USD | $-92.31 |
| SUKU/USD | $-88.35 |
| TOSHI/USD | $-68.75 |
| PNUT/USD | $-46.20 |
| RARI/USD | $-32.04 |
| AI3/USD | $-26.78 |
| POLIS/USD | $-25.13 |
| CFG/USD | $-16.18 |
| WMTX/USD | $-1.19 |

## 4. Random-21 Placebo Test

**Pool**: 47 coins met trades, 100 random-21 trekkingen

| Metric | EXCLUDED_21 | Placebo mediaan | Placebo P5-P95 |
|--------|-------------|-----------------|----------------|
| PnL | $3272 | $444 | $-366 tot $1591 |
| Lift vs baseline | $+2902 | $+74 | - |

**Placebo runs >= EXCLUDED_21**: 0/100 (0.0%)
**EXCLUDED_21 percentiel**: P100

> **Conclusie**: EXCLUDED_21 presteert significant beter dan random exclusion.

## 5. Cross-Validation Exclusion

**Methode**: 5-fold CV, embargo=10 bars

| Fold | Train trades | N excluded | Test+excl PnL | Test-excl PnL | Lift |
|------|-------------|------------|---------------|---------------|------|
| 0 | 59 | 23 | $513 | $407 | $+106 |
| 1 | 54 | 17 | $-341 | $-199 | $-141 |
| 2 | 57 | 16 | $-204 | $-499 | $+295 |
| 3 | 56 | 18 | $266 | $221 | $+45 |
| 4 | 57 | 20 | $385 | $608 | $-223 |

**Totale CV lift**: $+81.69
**Gemiddelde lift per fold**: $+16.34
**Folds met positieve lift**: 3/5
**Jaccard stabiliteit**: avg=0.580, min=0.500, max=0.654
**Coins in alle folds excluded**: 5 coins
  AI3/USD, ALKIMI/USD, ANIME/USD, KET/USD, TANSSI/USD

## 6. Universe-as-of Analyse

**Snapshots**: 4 wekelijkse punten
**Bereik**: 429 - 442 beschikbare coins

| Bar | Jaccard vs 295 | Beschikbaar | Alleen dynamic | Alleen static |
|-----|---------------|-------------|----------------|---------------|
| 50 | 0.6674 | 442 | 147 | 0 |
| 180 | 0.6751 | 437 | 142 | 0 |
| 361 | 0.6782 | 435 | 140 | 0 |
| 541 | 0.6876 | 429 | 134 | 0 |
| 721 | 0.0000 | 1 | 1 | 295 |

## 7. Leakage Scorecard

| Check | Resultaat | Risico |
|-------|-----------|--------|
| Data completeness | 442 coins, 722 max bars | LOW |
| Survivorship bias | 2 short-lived, 6 zero-vol tail | LOW |
| EXCLUDED_21 circularity | 100% in-sample (Jaccard=1.00) | **HIGH** |
| Random-21 placebo test | 0.0% random >= EXCLUDED_21 | LOW |
| CV exclusion lift | Avg lift: $+16.34, 3/5 folds positive | MEDIUM |
| Universe drift | 429-442 coins (2.9% range) | LOW |

**Totaal risico**: **MEDIUM** (score 1.50/3.0)

## Verdict

### Samenvatting

1. **EXCLUDED_21 is 100% circulair**: De exclusion list is afgeleid van full-sample backtest resultaten. Dit is forward-looking bias.
2. **Placebo test: SIGNIFICANT** (slechts 0% random runs >= EXCLUDED_21).
3. **CV exclusion: POSITIEF** (avg lift $+16.34, 3/5 folds positief). Exclusion heeft enige OOS waarde.
4. **Universe drift: 2.9%** (429-442 coins over 4 weken).

### Aanbeveling

**GEMIDDELD RISICO**: De exclusion heeft enige OOS onderbouwing maar is niet volledig robuust. Gebruik rolling lookback exclusion in productie.

---
*Gegenereerd door run_part2_data_assembly_audit.py op 2026-02-16 09:51*