# Sprint 4 Scoreboard -- DC-Compatible Entry Mining (RESEARCH: PF > 1.00)

- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Git**: 9a606d9
- **Generated**: 2026-02-17T20:14:07.842427+00:00
- **Total configs**: 10
- **GO (PF > 1.0)**: 7
- **PF threshold**: 1.0 (research)
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- Research leads threshold. Configs worth deeper investigation.

## GO Configs (PF > 1.0)

| # | Verdict | Config | Family | CompatScore | Tr | WR | PF | DD | P&L | Gates |
|---|---------|--------|--------|-------------|-----|-----|------|------|-------|-------|
| 1 | NO-GO | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | Volume Capitulation | 0.7395 | 216 | 54.6% | 1.41 | 49.8% | $+2,283.84 | 3/4 |
| 2 | NO-GO | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | Z-Score Extreme | 0.6977 | 206 | 52.9% | 1.35 | 44.0% | $+4,915.03 | 3/4 |
| 3 | NO-GO | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | Volume Capitulation | 0.7525 | 214 | 53.3% | 1.28 | 59.1% | $+823.92 | 3/4 |
| 4 | NO-GO | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | DC-Lite | 0.7385 | 101 | 54.5% | 1.25 | 40.8% | $+537.94 | 3/4 |
| 5 | NO-GO | sprint4_037_h4s4g01_vol3x_dczone_rsi40 | Volume Capitulation | 0.7070 | 222 | 50.5% | 1.18 | 79.7% | $-87.83 | 3/4 |
| 6 | NO-GO | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | Z-Score Extreme | 0.7200 | 206 | 49.5% | 1.16 | 53.2% | $+810.21 | 3/4 |
| 7 | NO-GO | sprint4_005_h4s4a05_bblow_rsi40_vol1.5 | DC-Lite | 0.7085 | 155 | 50.3% | 1.07 | 46.8% | $+257.40 | 3/4 |

## All Configs (by PF)

| # | Verdict | Config | Family | CompatScore | Tr | PF | DD | P&L |
|---|---------|--------|--------|-------------|-----|------|------|-------|
| 1 | NO-GO | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | Volume Capitulation | 0.7395 | 216 | 1.41 | 49.8% | $+2,283.84 |
| 2 | NO-GO | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | Z-Score Extreme | 0.6977 | 206 | 1.35 | 44.0% | $+4,915.03 |
| 3 | NO-GO | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | Volume Capitulation | 0.7525 | 214 | 1.28 | 59.1% | $+823.92 |
| 4 | NO-GO | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | DC-Lite | 0.7385 | 101 | 1.25 | 40.8% | $+537.94 |
| 5 | NO-GO | sprint4_037_h4s4g01_vol3x_dczone_rsi40 | Volume Capitulation | 0.7070 | 222 | 1.18 | 79.7% | $-87.83 |
| 6 | NO-GO | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | Z-Score Extreme | 0.7200 | 206 | 1.16 | 53.2% | $+810.21 |
| 7 | NO-GO | sprint4_005_h4s4a05_bblow_rsi40_vol1.5 | DC-Lite | 0.7085 | 155 | 1.07 | 46.8% | $+257.40 |
| 8 | NO-GO | sprint4_038_h4s4g02_vol4x_dczone_rsi40 | Volume Capitulation | 0.7075 | 226 | 0.98 | 89.5% | $-1,251.03 |
| 9 | NO-GO | sprint4_039_h4s4g03_vol5x_dczone_rsi35 | Volume Capitulation | 0.7301 | 219 | 0.98 | 83.9% | $-846.82 |
| 10 | NO-GO | sprint4_012_h4s4b05_dclow_wick40_rsi40_highvol | Wick Rejection | 0.6961 | 232 | 0.67 | 76.5% | $-1,456.88 |

## Family Summary

| Family | Cat | Configs | GO | Best PF | Avg PF | Avg Compat | Best P&L |
|--------|-----|---------|-----|---------|--------|------------|----------|
| DC-Lite | mean_reversion | 2 | 2 | 1.25 | 1.16 | 0.7235 | $+537.94 |
| Volume Capitulation | mean_reversion | 5 | 3 | 1.41 | 1.16 | 0.7273 | $+2,283.84 |
| Wick Rejection | mean_reversion | 1 | 0 | 0.67 | 0.67 | 0.6961 | $-1,456.88 |
| Z-Score Extreme | mean_reversion | 2 | 2 | 1.35 | 1.26 | 0.7088 | $+4,915.03 |
