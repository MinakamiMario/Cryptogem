# Sprint 2 Scoreboard — Entry-Edge Discovery

- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Git**: 9a606d9
- **Generated**: 2026-02-17T18:51:47.134716+00:00
- **Total configs**: 24
- **GO (PF > 1.05)**: 0
- **Stage 0 gate**: PF > 1.05 (relaxed)

## All Configs (by PF)

| # | Verdict | Config | Family | Cat | Tr | PF | DD | P&L |
|---|---------|--------|--------|-----|-----|------|------|-------|
| 1 | NO-GO | sprint2_020_h4s04_adx_min20_regime_typeB_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_floor_mult1.0 | RSI + Regime Filter | mean_reversion | 258 | 0.85 | 40.1% | $-608.83 |
| 2 | NO-GO | sprint2_013_h4s03_breadth_min0.4_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterTrue_time_limit25_top_pct5_tp_pct12_vol_mult2.0 | Cross-Sectional Relative Strength | momentum | 234 | 0.81 | 80.7% | $-1,553.49 |
| 3 | NO-GO | sprint2_010_h4s02_bb_width_pct_high70_decline_bars1_expansion_lookback30_no_new_low_bars3_rsi_max45_sl_pct8_time_limit15_tp_pct8_vol_decline_max1.0 | Volatility Exhaustion Fade | mean_reversion | 209 | 0.81 | 63.0% | $-1,195.21 |
| 4 | NO-GO | sprint2_017_h4s03_breadth_min0.3_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterFalse_time_limit25_top_pct10_tp_pct12_vol_mult1.5 | Cross-Sectional Relative Strength | momentum | 249 | 0.80 | 58.9% | $-1,098.38 |
| 5 | NO-GO | sprint2_022_h4s04_momentum_lookback10_regime_typeC_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_floor_mult1.0 | RSI + Regime Filter | mean_reversion | 61 | 0.78 | 23.6% | $-254.95 |
| 6 | NO-GO | sprint2_012_h4s03_breadth_min0.4_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterTrue_time_limit25_top_pct10_tp_pct12_vol_mult1.5 | Cross-Sectional Relative Strength | momentum | 242 | 0.78 | 78.8% | $-1,448.48 |
| 7 | NO-GO | sprint2_016_h4s03_breadth_min0.4_momentum_period20_require_positive_returnTrue_sl_pct8_sma_filterTrue_time_limit25_top_pct10_tp_pct12_vol_mult1.5 | Cross-Sectional Relative Strength | momentum | 242 | 0.78 | 78.8% | $-1,448.48 |
| 8 | NO-GO | sprint2_015_h4s03_breadth_min0.4_momentum_period5_require_positive_returnTrue_sl_pct5_sma_filterTrue_time_limit20_top_pct10_tp_pct10_vol_mult1.5 | Cross-Sectional Relative Strength | momentum | 356 | 0.76 | 80.6% | $-1,564.79 |
| 9 | NO-GO | sprint2_008_h4s02_bb_width_pct_high70_decline_bars1_expansion_lookback15_no_new_low_bars3_rsi_max40_sl_pct5_time_limit15_tp_pct8_vol_decline_max1.0 | Volatility Exhaustion Fade | mean_reversion | 256 | 0.75 | 69.4% | $-1,332.65 |
| 10 | NO-GO | sprint2_014_h4s03_breadth_min0.3_momentum_period10_require_positive_returnTrue_sl_pct5_sma_filterTrue_time_limit20_top_pct20_tp_pct8_vol_mult1.0 | Cross-Sectional Relative Strength | momentum | 381 | 0.73 | 81.0% | $-1,599.18 |
| 11 | NO-GO | sprint2_011_h4s02_bb_width_pct_high80_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_decline_max0.8 | Volatility Exhaustion Fade | mean_reversion | 264 | 0.69 | 56.1% | $-1,073.01 |
| 12 | NO-GO | sprint2_021_h4s04_adx_min25_regime_typeB_rsi_max40_sl_pct5_time_limit10_tp_pct5_vol_floor_mult0.8 | RSI + Regime Filter | mean_reversion | 416 | 0.68 | 71.9% | $-1,298.62 |
| 13 | NO-GO | sprint2_007_h4s02_bb_width_pct_high75_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_decline_max1.0 | Volatility Exhaustion Fade | mean_reversion | 275 | 0.66 | 60.5% | $-1,194.09 |
| 14 | NO-GO | sprint2_009_h4s02_bb_width_pct_high80_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max40_sl_pct5_time_limit10_tp_pct5_vol_decline_max0.8 | Volatility Exhaustion Fade | mean_reversion | 358 | 0.61 | 68.0% | $-1,321.08 |
| 15 | NO-GO | sprint2_019_h4s04_regime_typeA_rsi_max40_sl_pct5_slope_lookback5_time_limit15_tp_pct8_vol_floor_mult0.8 | RSI + Regime Filter | mean_reversion | 250 | 0.61 | 63.3% | $-1,266.22 |
| 16 | NO-GO | sprint2_023_h4s04_momentum_lookback20_regime_typeC_rsi_max40_sl_pct8_time_limit15_tp_pct8_vol_floor_mult0.8 | RSI + Regime Filter | mean_reversion | 159 | 0.60 | 57.9% | $-1,138.95 |
| 17 | NO-GO | sprint2_018_h4s04_regime_typeA_rsi_max35_sl_pct5_slope_lookback10_time_limit15_tp_pct8_vol_floor_mult1.0 | RSI + Regime Filter | mean_reversion | 219 | 0.56 | 62.0% | $-1,232.32 |
| 18 | NO-GO | sprint2_024_h4s04_momentum_lookback5_regime_typeC_rsi_max30_sl_pct5_time_limit10_tp_pct5_vol_floor_mult1.0 | RSI + Regime Filter | mean_reversion | 158 | 0.50 | 54.1% | $-1,081.38 |
| 19 | NO-GO | sprint2_004_h4s01_close_margin_pct0.5_dc_period25_min_range_atr0.8_sl_pct8_time_limit25_tp_pct12_vol_mult2.5 | Breakout Anti-Fakeout | breakout | 361 | 0.47 | 98.8% | $-1,977.03 |
| 20 | NO-GO | sprint2_002_h4s01_close_margin_pct0.5_dc_period20_min_range_atr0.8_sl_pct5_time_limit20_tp_pct10_vol_mult2.5 | Breakout Anti-Fakeout | breakout | 530 | 0.46 | 98.9% | $-1,978.48 |
| 21 | NO-GO | sprint2_001_h4s01_close_margin_pct1.0_dc_period20_min_range_atr1.0_sl_pct5_time_limit20_tp_pct10_vol_mult3.0 | Breakout Anti-Fakeout | breakout | 553 | 0.44 | 98.2% | $-1,963.91 |
| 22 | NO-GO | sprint2_006_h4s01_close_margin_pct1.0_dc_period20_min_range_atr1.2_sl_pct8_time_limit25_tp_pct12_vol_mult3.0 | Breakout Anti-Fakeout | breakout | 368 | 0.43 | 98.2% | $-1,965.05 |
| 23 | NO-GO | sprint2_005_h4s01_close_margin_pct0.5_dc_period15_min_range_atr0.8_sl_pct5_time_limit15_tp_pct8_vol_mult2.5 | Breakout Anti-Fakeout | breakout | 611 | 0.38 | 99.8% | $-1,995.97 |
| 24 | NO-GO | sprint2_003_h4s01_close_margin_pct0_dc_period20_min_range_atr0.5_sl_pct5_time_limit20_tp_pct10_vol_mult2.0 | Breakout Anti-Fakeout | breakout | 512 | 0.38 | 99.2% | $-1,984.66 |

## Family Summary

| Family | Cat | Configs | GO | Best PF | Avg PF | Best P&L |
|--------|-----|---------|-----|---------|--------|----------|
| Breakout Anti-Fakeout | breakout | 6 | 0 | 0.47 | 0.43 | $-1,963.91 |
| Volatility Exhaustion Fade | mean_reversion | 5 | 0 | 0.81 | 0.70 | $-1,073.01 |
| Cross-Sectional Relative Strength | momentum | 6 | 0 | 0.81 | 0.78 | $-1,098.38 |
| RSI + Regime Filter | mean_reversion | 7 | 0 | 0.85 | 0.65 | $-254.95 |
