# Data Quality Audit Report

**Generated**: 2026-02-15 00:04:06 UTC
**Dataset**: `candle_cache_research_all.json`
**Coins audited**: 2090

---

## Overview

| Metric | Value |
|--------|-------|
| Average quality | 89.1 |
| Median quality | 90.8 |
| Min quality | 56.7 |
| Max quality | 100.0 |
| Below 50 | 0 (0.0%) |
| Below 30 | 0 (0.0%) |

## Quality Distribution

```
    0-20:  0
   20-40:  0
   40-60:  9
   60-80: █████ 245
  80-100: ████████████████████████████████████████ 1836
```

| Bracket | Count | Percentage |
|---------|-------|------------|
| 0-20 | 0 | 0.0% |
| 20-40 | 0 | 0.0% |
| 40-60 | 9 | 0.4% |
| 60-80 | 245 | 11.7% |
| 80-100 | 1836 | 87.8% |

## Kraken vs MEXC Comparison

| Metric | Kraken (522 coins) | MEXC (1568 coins) |
|--------|------|------|
| Avg quality | 93.9 | 87.5 |
| Median quality | 98.0 | 90.6 |
| Below 50 | 0 (0.0%) | 0 (0.0%) |

## Filtering Recommendations

| Threshold | Filtered out | Remaining | % kept |
|-----------|-------------|-----------|--------|
| < 30 | 0 | 2090 | 100.0% |
| < 50 | 0 | 2090 | 100.0% |
| < 70 | 62 | 2028 | 97.0% |

## Top 50 Worst Offenders

| # | Coin | Score | Bars | Gaps | MaxGap(h) | Outliers | ZeroVol | FlatStreak | Issues |
|---|------|-------|------|------|-----------|----------|---------|------------|--------|
| 1 | MERIN/USD | 56.7 | 40 | 0 | 0.0 | 19 | 0 | 0 | low_coverage (6%), outlier_wicks (19) |
| 2 | SOMNUS/USD | 56.9 | 46 | 0 | 0.0 | 10 | 0 | 0 | low_coverage (6%), outlier_wicks (10) |
| 3 | SZNP/USD | 58.2 | 76 | 0 | 0.0 | 26 | 0 | 0 | low_coverage (11%), outlier_wicks (26) |
| 4 | NEXFI/USD | 58.4 | 82 | 0 | 0.0 | 17 | 0 | 0 | low_coverage (11%), outlier_wicks (17) |
| 5 | CLAWNCH/USD | 58.7 | 89 | 0 | 0.0 | 14 | 0 | 0 | low_coverage (12%), outlier_wicks (14) |
| 6 | PPTAI/USD | 58.7 | 88 | 0 | 0.0 | 20 | 0 | 0 | low_coverage (12%), outlier_wicks (20) |
| 7 | SUP/USD | 58.9 | 57 | 0 | 0.0 | 9 | 0 | 0 | low_coverage (8%), outlier_wicks (9) |
| 8 | CLAWDONBASE/USD | 59.7 | 113 | 0 | 0.0 | 21 | 0 | 0 | low_coverage (16%), outlier_wicks (21) |
| 9 | COPPERINU/USD | 59.7 | 114 | 0 | 0.0 | 11 | 0 | 0 | low_coverage (16%), outlier_wicks (11) |
| 10 | SGP/USD | 60.2 | 124 | 0 | 0.0 | 42 | 0 | 0 | low_coverage (17%), outlier_wicks (42) |
| 11 | WOJAK/USD | 60.2 | 88 | 0 | 0.0 | 9 | 0 | 0 | low_coverage (12%), outlier_wicks (9) |
| 12 | TAL/USD | 60.4 | 130 | 0 | 0.0 | 31 | 0 | 0 | low_coverage (18%), outlier_wicks (31) |
| 13 | MOLT/USD | 60.5 | 95 | 0 | 0.0 | 9 | 0 | 0 | low_coverage (13%), outlier_wicks (9) |
| 14 | DONT/USD | 60.9 | 141 | 0 | 0.0 | 18 | 0 | 0 | low_coverage (20%), outlier_wicks (18) |
| 15 | MEMES/USD | 61.2 | 149 | 0 | 0.0 | 13 | 0 | 0 | low_coverage (21%), outlier_wicks (13) |
| 16 | LEXAI/USD | 61.9 | 166 | 0 | 0.0 | 35 | 0 | 0 | low_coverage (23%), outlier_wicks (35) |
| 17 | NEURAART/USD | 61.9 | 166 | 0 | 0.0 | 32 | 0 | 0 | low_coverage (23%), outlier_wicks (32) |
| 18 | FSV/USD | 62.2 | 183 | 0 | 0.0 | 30 | 5 | 3 | low_coverage (25%), outlier_wicks (30) |
| 19 | PIKZ/USD | 62.2 | 194 | 0 | 0.0 | 29 | 11 | 3 | low_coverage (27%), outlier_wicks (29) |
| 20 | 死了么/USD | 62.2 | 184 | 0 | 0.0 | 34 | 6 | 1 | low_coverage (26%), outlier_wicks (34) |
| 21 | VERDAX/USD | 62.4 | 178 | 0 | 0.0 | 11 | 0 | 0 | low_coverage (25%), outlier_wicks (11) |
| 22 | EDOM/USD | 62.7 | 149 | 0 | 0.0 | 9 | 0 | 0 | low_coverage (21%), outlier_wicks (9) |
| 23 | PSYOPANIME/USD | 63.2 | 198 | 0 | 0.0 | 11 | 0 | 0 | low_coverage (27%), outlier_wicks (11) |
| 24 | TONIXAI/USD | 63.2 | 52 | 0 | 0.0 | 6 | 0 | 0 | low_coverage (7%), outlier_wicks (6) |
| 25 | ARCIEL/USD | 63.4 | 94 | 0 | 0.0 | 7 | 0 | 0 | low_coverage (13%), outlier_wicks (7) |
| 26 | DEB/USD | 63.7 | 500 | 0 | 0.0 | 21 | 404 | 54 | outlier_wicks (21), flat_volume_streak (54), high_zero_vol (404/500) |
| 27 | THENT/USD | 63.9 | 214 | 0 | 0.0 | 34 | 0 | 0 | low_coverage (30%), outlier_wicks (34) |
| 28 | TEM/USD | 64.4 | 52 | 0 | 0.0 | 5 | 1 | 1 | low_coverage (7%), outlier_wicks (5) |
| 29 | CENNZ/USD | 64.7 | 500 | 0 | 0.0 | 39 | 371 | 31 | outlier_wicks (39), flat_volume_streak (31), high_zero_vol (371/500) |
| 30 | 我踏马来了/USD | 64.7 | 233 | 0 | 0.0 | 12 | 0 | 0 | low_coverage (32%), outlier_wicks (12) |
| 31 | RALPH/USD | 64.9 | 239 | 0 | 0.0 | 51 | 0 | 0 | low_coverage (33%), outlier_wicks (51) |
| 32 | SOLTOMATO/USD | 64.9 | 239 | 0 | 0.0 | 18 | 0 | 0 | low_coverage (33%), outlier_wicks (18) |
| 33 | WARD/USD | 65.1 | 63 | 0 | 0.0 | 5 | 0 | 0 | low_coverage (9%), outlier_wicks (5) |
| 34 | COMAI/USD | 65.1 | 500 | 0 | 0.0 | 24 | 356 | 53 | outlier_wicks (24), flat_volume_streak (53), high_zero_vol (356/500) |
| 35 | XYZ/USD | 65.1 | 99 | 0 | 0.0 | 6 | 0 | 0 | low_coverage (14%), outlier_wicks (6) |
| 36 | 114514/USD | 65.2 | 245 | 0 | 0.0 | 17 | 0 | 0 | low_coverage (34%), outlier_wicks (17) |
| 37 | EON/USD | 65.7 | 500 | 0 | 0.0 | 8 | 436 | 166 | outlier_wicks (8), flat_volume_streak (166), high_zero_vol (436/500) |
| 38 | 人生K线/USD | 65.7 | 256 | 0 | 0.0 | 21 | 0 | 0 | low_coverage (36%), outlier_wicks (21) |
| 39 | SUMR/USD | 65.8 | 144 | 0 | 0.0 | 6 | 11 | 3 | low_coverage (20%), outlier_wicks (6) |
| 40 | DRB/USD | 65.9 | 191 | 0 | 0.0 | 8 | 0 | 0 | low_coverage (26%), outlier_wicks (8) |
| 41 | 哭哭马1/USD | 66.1 | 160 | 0 | 0.0 | 7 | 1 | 1 | low_coverage (22%), outlier_wicks (7) |
| 42 | MKIT/USD | 66.4 | 273 | 0 | 0.0 | 62 | 0 | 0 | low_coverage (38%), outlier_wicks (62) |
| 43 | OPS/USD | 66.5 | 280 | 0 | 0.0 | 61 | 3 | 1 | low_coverage (39%), outlier_wicks (61) |
| 44 | KOII/USD | 66.7 | 500 | 0 | 0.0 | 32 | 304 | 27 | outlier_wicks (32), flat_volume_streak (27), high_zero_vol (304/500) |
| 45 | ECHELON/USD | 67.1 | 75 | 0 | 0.0 | 4 | 0 | 0 | low_coverage (10%), outlier_wicks (4) |
| 46 | KLARA/USD | 67.1 | 292 | 0 | 0.0 | 36 | 0 | 0 | low_coverage (40%), outlier_wicks (36) |
| 47 | CLUB/USD | 67.2 | 500 | 0 | 0.0 | 9 | 338 | 15 | outlier_wicks (9), high_zero_vol (338/500) |
| 48 | POWERAI/USD | 67.2 | 40 | 0 | 0.0 | 3 | 0 | 0 | low_coverage (6%) |
| 49 | PRTG/USD | 67.4 | 500 | 0 | 0.0 | 10 | 280 | 21 | outlier_wicks (10), flat_volume_streak (21), high_zero_vol (280/500) |
| 50 | TACAI/USD | 67.4 | 298 | 0 | 0.0 | 45 | 0 | 0 | low_coverage (41%), outlier_wicks (45) |

---

## Scoring Methodology

Each coin is scored 0-100 based on weighted components:

- **Coverage** (30%): `bars / 721` -- how many of the expected bars are present
- **Gaps** (25%): `1 - min(gap_count / 20, 1)` -- penalizes missing time segments (>6.0h threshold)
- **Outliers** (15%): `1 - min(outlier_count / 10, 1)` -- penalizes extreme wick spikes (>50% of close)
- **Volume** (15%): `1 - zero_vol_bars / total_bars` -- penalizes zero-volume candles
- **Spacing** (15%): stdev of candle intervals; perfect if <2h stdev, degrades beyond that

Price integrity issues (zero/negative/NaN prices) apply an additional hard penalty.
