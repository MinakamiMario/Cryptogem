# Sweep v1 Scoreboard

- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Git**: 57a688e3
- **Generated**: 2026-02-26T05:04:46.281945+00:00
- **Total configs**: 30
- **Strict LEADs (PF > 1.05 + gates)**: 0
- **Research LEADs (PF > 1.0)**: 6
- **STRONG LEADs (edge decomp)**: 6
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Fee**: 26 bps per side (Kraken)

## Research LEADs (PF > 1.0, not strict)

| # | ID | Family | PF | Trades | DD% | WR% | P&L | EV/t | A% | Grade | Gates |
|---|-----|--------|-----|--------|------|------|------|-------|-----|-------|-------|
| 1 | sweep_v1_006_sv1a06_rsi45_p8_atr2.0 | SwingFractalBounce | 1.52 | 347 | 63.1% | 58.8% | $+3,425.19 | $+9.87 | 100% | STRONG_LEAD | 3/4 |
| 2 | sweep_v1_002_sv1a02_rsi40_p5_atr1.5 | SwingFractalBounce | 1.35 | 306 | 56.8% | 57.8% | $+744.52 | $+2.43 | 100% | STRONG_LEAD | 2/4 |
| 3 | sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh | SwingFractalBounce | 1.24 | 313 | 41.9% | 53.4% | $+2,847.68 | $+9.10 | 100% | STRONG_LEAD | 2/4 |
| 4 | sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45 | TrendPullback | 1.09 | 259 | 55.9% | 59.1% | $-367.57 | $-1.42 | 100% | STRONG_LEAD | 3/4 |
| 5 | sweep_v1_003_sv1a03_rsi45_p5_atr2.0 | SwingFractalBounce | 1.06 | 308 | 55.3% | 56.8% | $-171.42 | $-0.56 | 100% | STRONG_LEAD | 2/4 |
| 6 | sweep_v1_004_sv1a04_rsi35_p8_atr1.5 | SwingFractalBounce | 1.01 | 286 | 68.7% | 55.9% | $-685.19 | $-2.40 | 100% | STRONG_LEAD | 1/4 |

## All Results

| # | ID | Family | PF | Trades | DD% | P&L | EV/t | A% | Stopout | Grade | Compat |
|---|-----|--------|-----|--------|------|------|-------|-----|---------|-------|--------|
| 1 | sweep_v1_006_sv1a06_rsi45_p8_atr2.0 | SwingFractalBounce | 1.52 | 347 | 63.1% | $+3,425.19 | $+9.87 | 100% | 10% | STRONG_LEAD | 0.5106 |
| 2 | sweep_v1_002_sv1a02_rsi40_p5_atr1.5 | SwingFractalBounce | 1.35 | 306 | 56.8% | $+744.52 | $+2.43 | 100% | 11% | STRONG_LEAD | 0.5564 |
| 3 | sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh | SwingFractalBounce | 1.24 | 313 | 41.9% | $+2,847.68 | $+9.10 | 100% | 14% | STRONG_LEAD | 0.5998 |
| 4 | sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45 | TrendPullback | 1.09 | 259 | 55.9% | $-367.57 | $-1.42 | 100% | 14% | STRONG_LEAD | 0.5290 |
| 5 | sweep_v1_003_sv1a03_rsi45_p5_atr2.0 | SwingFractalBounce | 1.06 | 308 | 55.3% | $-171.42 | $-0.56 | 100% | 13% | STRONG_LEAD | 0.5061 |
| 6 | sweep_v1_004_sv1a04_rsi35_p8_atr1.5 | SwingFractalBounce | 1.01 | 286 | 68.7% | $-685.19 | $-2.40 | 100% | 12% | STRONG_LEAD | 0.6014 |
| 7 | sweep_v1_016_sv1c04_hh1_sw8_tol1.5 | TrendPullback | 0.95 | 239 | 63.9% | $-926.90 | $-3.88 | 100% | 13% | WEAK_LEAD | 0.5477 |
| 8 | sweep_v1_013_sv1c01_hh1_sw5_tol1.0 | TrendPullback | 0.87 | 238 | 79.0% | $-1,465.88 | $-6.16 | 100% | 17% | NEGATIVE | 0.5852 |
| 9 | sweep_v1_007_sv1b01_dclow_rsi40_vol1.5_sw0.3 | WickSweepReclaim | 0.86 | 231 | 63.3% | $-803.31 | $-3.48 | 100% | 16% | NEGATIVE | 0.7294 |
| 10 | sweep_v1_001_sv1a01_rsi35_p5_atr1.0 | SwingFractalBounce | 0.83 | 284 | 67.3% | $-1,186.11 | $-4.18 | 100% | 14% | NEGATIVE | 0.6112 |
| 11 | sweep_v1_011_sv1b05_dclow_rsi45_vol1.0_sw0.3 | WickSweepReclaim | 0.82 | 245 | 61.2% | $-920.58 | $-3.76 | 100% | 16% | NEGATIVE | 0.6976 |
| 12 | sweep_v1_023_sv1d05_pctile30_sq5_expand_rsi45 | ATRExhaustion | 0.78 | 261 | 83.1% | $-1,460.32 | $-5.60 | 100% | 13% | NEGATIVE | 0.4891 |
| 13 | sweep_v1_009_sv1b03_pivot_rsi40_vol1.5_sw0.3 | WickSweepReclaim | 0.78 | 277 | 58.0% | $-992.30 | $-3.58 | 100% | 15% | NEGATIVE | 0.6326 |
| 14 | sweep_v1_017_sv1c05_hh2_sw8_tol1.0_rsi35 | TrendPullback | 0.75 | 123 | 55.4% | $-1,087.34 | $-8.84 | 100% | 13% | NEGATIVE | 0.6422 |
| 15 | sweep_v1_014_sv1c02_hh2_sw5_tol1.5 | TrendPullback | 0.73 | 183 | 59.0% | $-757.06 | $-4.14 | 100% | 14% | NEGATIVE | 0.5847 |
| 16 | sweep_v1_021_sv1d03_pctile40_sq3_expand | ATRExhaustion | 0.72 | 243 | 79.8% | $-1,289.71 | $-5.31 | 100% | 14% | NEGATIVE | 0.5215 |
| 17 | sweep_v1_024_sv1d06_pctile30_sq3_volhigh | ATRExhaustion | 0.70 | 248 | 84.3% | $-1,655.64 | $-6.68 | 100% | 13% | NEGATIVE | 0.5289 |
| 18 | sweep_v1_025_sv1e01_pctile5_gap10 | CrossRSIExtreme | 0.69 | 205 | 75.0% | $-1,460.63 | $-7.13 | 99% | 19% | NEGATIVE | 0.7180 |
| 19 | sweep_v1_030_sv1e06_pctile5_gap15_rsi35 | CrossRSIExtreme | 0.69 | 205 | 75.0% | $-1,460.63 | $-7.13 | 99% | 19% | NEGATIVE | 0.7177 |
| 20 | sweep_v1_008_sv1b02_dclow_rsi35_vol2.0_sw0.5 | WickSweepReclaim | 0.69 | 185 | 53.0% | $-1,040.19 | $-5.62 | 100% | 15% | NEGATIVE | 0.7422 |
| 21 | sweep_v1_015_sv1c03_hh3_sw5_tol2.0 | TrendPullback | 0.65 | 61 | 24.3% | $-437.54 | $-7.17 | 100% | 13% | NEGATIVE | 0.6298 |
| 22 | sweep_v1_020_sv1d02_pctile30_sq5 | ATRExhaustion | 0.62 | 263 | 88.2% | $-1,743.54 | $-6.63 | 100% | 13% | NEGATIVE | 0.4982 |
| 23 | sweep_v1_026_sv1e02_pctile10_gap10 | CrossRSIExtreme | 0.62 | 202 | 81.5% | $-1,589.69 | $-7.87 | 100% | 19% | NEGATIVE | 0.6870 |
| 24 | sweep_v1_027_sv1e03_pctile15_gap15 | CrossRSIExtreme | 0.62 | 202 | 81.5% | $-1,589.69 | $-7.87 | 100% | 19% | NEGATIVE | 0.6548 |
| 25 | sweep_v1_028_sv1e04_pctile10_gap5_rsi35 | CrossRSIExtreme | 0.61 | 202 | 81.3% | $-1,602.37 | $-7.93 | 100% | 20% | NEGATIVE | 0.6916 |
| 26 | sweep_v1_010_sv1b04_both_rsi40_vol2.0_sw0.5 | WickSweepReclaim | 0.59 | 210 | 61.0% | $-1,217.13 | $-5.80 | 100% | 10% | NEGATIVE | 0.6110 |
| 27 | sweep_v1_019_sv1d01_pctile20_sq3 | ATRExhaustion | 0.56 | 253 | 91.2% | $-1,800.50 | $-7.12 | 100% | 11% | NEGATIVE | 0.4987 |
| 28 | sweep_v1_022_sv1d04_pctile20_sq8_rsi35 | ATRExhaustion | 0.52 | 197 | 84.8% | $-1,657.33 | $-8.41 | 100% | 15% | NEGATIVE | 0.5415 |
| 29 | sweep_v1_029_sv1e05_pctile20_gap5_volhigh | CrossRSIExtreme | 0.49 | 203 | 80.8% | $-1,612.92 | $-7.95 | 100% | 21% | NEGATIVE | 0.6809 |
| 30 | sweep_v1_012_sv1b06_pivot8_rsi35_vol3.0_sw0.5 | WickSweepReclaim | 0.45 | 118 | 62.0% | $-1,225.40 | $-10.38 | 100% | 17% | NEGATIVE | 0.6656 |

## Family Summary

| Family | Cat | Configs | Strict | Research | Best PF | Avg PF | Avg Compat | Best P&L |
|--------|-----|---------|--------|----------|---------|--------|------------|----------|
| ATRExhaustion | mean_reversion | 6 | 0 | 0 | 0.78 | 0.65 | 0.5130 | $-1,289.71 |
| CrossRSIExtreme | mean_reversion | 6 | 0 | 0 | 0.69 | 0.62 | 0.6917 | $-1,460.63 |
| SwingFractalBounce | mean_reversion | 6 | 0 | 5 | 1.52 | 1.17 | 0.5643 | $+3,425.19 |
| TrendPullback | trend_following | 6 | 0 | 1 | 1.09 | 0.84 | 0.5864 | $-367.57 |
| WickSweepReclaim | mean_reversion | 6 | 0 | 0 | 0.86 | 0.70 | 0.6797 | $-803.31 |

