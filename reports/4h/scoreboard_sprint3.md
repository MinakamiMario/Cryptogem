# Sprint 3 Scoreboard — Exit-Intelligence Porting

- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Git**: 9a606d9
- **Generated**: 2026-02-17T19:48:33.448439+00:00
- **Total configs**: 18
- **GO (PF > 1.05)**: 0
- **Stage 0 gate**: PF > 1.05 (relaxed)
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)

## All Configs (by PF)

| # | Verdict | Config | Family | Cat | Tr | PF | DD | P&L |
|---|---------|--------|--------|-----|-----|------|------|-------|
| 1 | NO-GO | sprint3_017_h4s302_bbw80_dec2_dc_medium | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 390 | 0.95 | 68.0% | $-888.35 |
| 2 | NO-GO | sprint3_015_h4s302_bbw70_dec1_dc_wide | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 379 | 0.95 | 55.6% | $-289.62 |
| 3 | NO-GO | sprint3_016_h4s302_bbw80_dec2_dc_tight | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 449 | 0.93 | 58.1% | $-524.24 |
| 4 | NO-GO | sprint3_014_h4s302_bbw70_dec1_dc_medium | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 358 | 0.89 | 52.2% | $-547.32 |
| 5 | NO-GO | sprint3_002_h4s304_regime_typeB_rsi_max35_dc_medium | RSI + Regime Filter (DC Exits) | mean_reversion | 242 | 0.81 | 56.3% | $-684.61 |
| 6 | NO-GO | sprint3_003_h4s304_regime_typeB_rsi_max35_dc_wide | RSI + Regime Filter (DC Exits) | mean_reversion | 246 | 0.81 | 62.9% | $-643.92 |
| 7 | NO-GO | sprint3_001_h4s304_regime_typeB_rsi_max35_dc_tight | RSI + Regime Filter (DC Exits) | mean_reversion | 277 | 0.79 | 63.7% | $-806.61 |
| 8 | NO-GO | sprint3_008_h4s303_breadth04_top5_dc_medium | Cross-Sectional Relative Strength (DC Exits) | momentum | 823 | 0.79 | 88.6% | $-1,538.54 |
| 9 | NO-GO | sprint3_007_h4s303_breadth04_top5_dc_tight | Cross-Sectional Relative Strength (DC Exits) | momentum | 824 | 0.78 | 88.4% | $-1,597.58 |
| 10 | NO-GO | sprint3_009_h4s303_breadth04_top5_dc_wide | Cross-Sectional Relative Strength (DC Exits) | momentum | 823 | 0.77 | 89.2% | $-1,564.04 |
| 11 | NO-GO | sprint3_013_h4s302_bbw70_dec1_dc_tight | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 411 | 0.71 | 67.4% | $-1,249.74 |
| 12 | NO-GO | sprint3_018_h4s302_bbw80_dec2_dc_wide | Volatility Exhaustion Fade (DC Exits) | mean_reversion | 378 | 0.68 | 76.6% | $-1,473.57 |
| 13 | NO-GO | sprint3_004_h4s304_regime_typeA_rsi_max40_dc_tight | RSI + Regime Filter (DC Exits) | mean_reversion | 290 | 0.67 | 67.2% | $-1,315.98 |
| 14 | NO-GO | sprint3_011_h4s303_breadth03_top10_dc_medium | Cross-Sectional Relative Strength (DC Exits) | momentum | 1294 | 0.65 | 98.2% | $-1,951.83 |
| 15 | NO-GO | sprint3_010_h4s303_breadth03_top10_dc_tight | Cross-Sectional Relative Strength (DC Exits) | momentum | 1299 | 0.65 | 98.3% | $-1,953.56 |
| 16 | NO-GO | sprint3_012_h4s303_breadth03_top10_dc_wide | Cross-Sectional Relative Strength (DC Exits) | momentum | 1295 | 0.65 | 98.2% | $-1,952.73 |
| 17 | NO-GO | sprint3_006_h4s304_regime_typeA_rsi_max40_dc_wide | RSI + Regime Filter (DC Exits) | mean_reversion | 235 | 0.63 | 65.1% | $-1,288.46 |
| 18 | NO-GO | sprint3_005_h4s304_regime_typeA_rsi_max40_dc_medium | RSI + Regime Filter (DC Exits) | mean_reversion | 254 | 0.63 | 66.6% | $-1,294.49 |

## Family Summary

| Family | Cat | Configs | GO | Best PF | Avg PF | Best P&L |
|--------|-----|---------|-----|---------|--------|----------|
| Volatility Exhaustion Fade (DC Exits) | mean_reversion | 6 | 0 | 0.95 | 0.85 | $-289.62 |
| Cross-Sectional Relative Strength (DC Exits) | momentum | 6 | 0 | 0.79 | 0.72 | $-1,538.54 |
| RSI + Regime Filter (DC Exits) | mean_reversion | 6 | 0 | 0.81 | 0.73 | $-643.92 |
