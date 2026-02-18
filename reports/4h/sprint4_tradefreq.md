# Sprint 4 -- Trade Frequency Sensitivity Analysis

- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Fee model**: Kraken spot 26 bps/side
- **Git**: 9a606d9
- **Generated**: 2026-02-17T21:09:25.311619+00:00
- **Quality gates**: stopout <= 30%, class_a >= 50%, PF >= 1.0
- **Dataset span**: ~120 days (~17.1 weeks)

## Summary

- **Total tests**: 40
- **Quality pass**: 40
- **Best frequency**: sprint4_041_h4s4g05_vol3x_bblow_rsi40 ({'rsi_max': 45}) (1.9 trades/day)
- **Best PF**: sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol ({'vol_floor_mult': 1.0}) (PF=1.5726)

### Recommendations
- 32 config(s) achieve >=1 trade/day while passing quality gates.
- Full pool (526 coins) adds avg +0 trades vs 487-coin universe.
- RSI sensitivity: 15/15 configs pass quality gates.
- Volume sensitivity: 15/15 configs pass quality gates.

## Test 1: Full Pool (526 coins vs 487 coins)

| Config | Universe | Trades | Tr/wk | Tr/day | PF | WR | P&L | DD | Stop% | A% | Quality |
|--------|----------|--------|-------|--------|------|------|------|------|-------|-----|---------|
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | universe_487 | 216 | 12.6 | 1.8 | 1.41 | 54.6% | $+2,283.84 | 49.8% | 0.18 | 1.00 | PASS |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | all_526 | 213 | 12.5 | 1.8 | 1.46 | 55.9% | $+3,271.38 | 49.8% | 0.16 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | universe_487 | 206 | 12.1 | 1.7 | 1.35 | 52.9% | $+4,915.03 | 44.0% | 0.17 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | all_526 | 205 | 12.0 | 1.7 | 1.24 | 51.7% | $+2,227.01 | 44.0% | 0.17 | 1.00 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | universe_487 | 214 | 12.5 | 1.8 | 1.28 | 53.3% | $+823.92 | 59.1% | 0.21 | 0.99 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | all_526 | 216 | 12.6 | 1.8 | 1.50 | 54.2% | $+3,149.31 | 59.1% | 0.19 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | universe_487 | 101 | 5.9 | 0.8 | 1.25 | 54.5% | $+537.94 | 40.8% | 0.17 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | all_526 | 101 | 5.9 | 0.8 | 1.25 | 54.5% | $+541.21 | 40.8% | 0.17 | 0.99 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | universe_487 | 206 | 12.1 | 1.7 | 1.16 | 49.5% | $+810.21 | 53.2% | 0.19 | 1.00 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | all_526 | 210 | 12.3 | 1.8 | 1.20 | 52.4% | $+1,141.82 | 40.1% | 0.19 | 0.99 | PASS |

## Test 2: RSI Threshold Sensitivity

| Config | RSI | Trades | Tr/day | PF | WR | P&L | DD | Stop% | A% | Quality |
|--------|-----|--------|--------|------|------|------|------|-------|-----|---------|
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | 40 | 216 | 1.8 | 1.41 | 54.6% | $+2,283.84 | 49.8% | 0.18 | 1.00 | PASS |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | 42 | 222 | 1.9 | 1.39 | 56.3% | $+2,367.71 | 53.8% | 0.19 | 1.00 | PASS |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | 45 | 229 | 1.9 | 1.42 | 56.8% | $+2,665.62 | 53.5% | 0.19 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | 40 | 206 | 1.7 | 1.35 | 52.9% | $+4,915.03 | 44.0% | 0.17 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | 42 | 211 | 1.8 | 1.50 | 54.5% | $+7,884.99 | 35.4% | 0.17 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | 45 | 212 | 1.8 | 1.54 | 54.7% | $+8,571.55 | 33.2% | 0.17 | 1.00 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | 35 | 214 | 1.8 | 1.28 | 53.3% | $+823.92 | 59.1% | 0.21 | 0.99 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | 38 | 206 | 1.7 | 1.38 | 52.4% | $+2,174.57 | 54.5% | 0.17 | 1.00 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | 40 | 207 | 1.7 | 1.51 | 53.1% | $+3,615.68 | 46.9% | 0.16 | 1.00 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | 40 | 101 | 0.8 | 1.25 | 54.5% | $+537.94 | 40.8% | 0.17 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | 42 | 102 | 0.8 | 1.28 | 54.9% | $+619.55 | 40.8% | 0.17 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | 45 | 102 | 0.8 | 1.15 | 54.9% | $-245.18 | 52.5% | 0.17 | 0.99 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | 45 | 206 | 1.7 | 1.16 | 49.5% | $+810.21 | 53.2% | 0.19 | 1.00 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | 47 | 206 | 1.7 | 1.16 | 49.5% | $+810.21 | 53.2% | 0.19 | 1.00 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | 50 | 206 | 1.7 | 1.16 | 49.5% | $+810.21 | 53.2% | 0.19 | 1.00 | PASS |

## Test 3: Volume Threshold Sensitivity

| Config | Param | Value | Trades | Tr/day | PF | P&L | DD | Stop% | A% | Quality |
|--------|-------|-------|--------|--------|------|------|------|-------|-----|---------|
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_mult | 2.5 | 223 | 1.9 | 1.05 | $-188.52 | 67.8% | 0.21 | 1.00 | PASS |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_mult | 3.0 | 216 | 1.8 | 1.41 | $+2,283.84 | 49.8% | 0.18 | 1.00 | PASS |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_mult | 3.5 | 220 | 1.8 | 1.56 | $+4,225.46 | 49.8% | 0.18 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_floor_mult | 0.3 | 213 | 1.8 | 1.30 | $+3,517.61 | 40.9% | 0.17 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_floor_mult | 0.5 | 206 | 1.7 | 1.35 | $+4,915.03 | 44.0% | 0.17 | 1.00 | PASS |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_floor_mult | 0.7 | 203 | 1.7 | 1.44 | $+3,323.48 | 49.8% | 0.15 | 1.00 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_mult | 3.5 | 213 | 1.8 | 1.03 | $-633.91 | 71.3% | 0.23 | 0.99 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_mult | 4.0 | 214 | 1.8 | 1.28 | $+823.92 | 59.1% | 0.21 | 0.99 | PASS |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_mult | 4.5 | 195 | 1.6 | 1.31 | $+641.84 | 57.0% | 0.17 | 0.98 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | vol_spike_mult | 1.0 | 113 | 0.9 | 1.07 | $+158.15 | 42.6% | 0.17 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | vol_spike_mult | 1.5 | 101 | 0.8 | 1.25 | $+537.94 | 40.8% | 0.17 | 0.99 | PASS |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | vol_spike_mult | 2.0 | 89 | 0.7 | 1.41 | $+804.17 | 33.6% | 0.18 | 0.99 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_floor_mult | 1.0 | 214 | 1.8 | 1.57 | $+10,299.02 | 42.1% | 0.21 | 1.00 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_floor_mult | 1.5 | 206 | 1.7 | 1.16 | $+810.21 | 53.2% | 0.19 | 1.00 | PASS |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_floor_mult | 2.0 | 210 | 1.8 | 1.25 | $+1,691.08 | 46.4% | 0.19 | 1.00 | PASS |

## Trade Frequency Overview (all tests, sorted by trades/day)

| # | Config | Test | Overrides | Tr/day | Tr/wk | Trades | PF | Quality |
|---|--------|------|-----------|--------|-------|--------|------|---------|
| 1 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | rsi_sensitivity | {"rsi_max": 45} | 1.9 | 13.4 | 229 | 1.42 | PASS |
| 2 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_sensitivity | {"vol_mult": 2.5} | 1.9 | 13.0 | 223 | 1.05 | PASS |
| 3 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | rsi_sensitivity | {"rsi_max": 42} | 1.9 | 13.0 | 222 | 1.39 | PASS |
| 4 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_sensitivity | {"vol_mult": 3.5} | 1.8 | 12.9 | 220 | 1.56 | PASS |
| 5 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | full_pool | - | 1.8 | 12.6 | 216 | 1.41 | PASS |
| 6 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | full_pool | - | 1.8 | 12.6 | 216 | 1.50 | PASS |
| 7 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | rsi_sensitivity | {"rsi_max": 40} | 1.8 | 12.6 | 216 | 1.41 | PASS |
| 8 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_sensitivity | {"vol_mult": 3.0} | 1.8 | 12.6 | 216 | 1.41 | PASS |
| 9 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | full_pool | - | 1.8 | 12.5 | 214 | 1.28 | PASS |
| 10 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | rsi_sensitivity | {"rsi_max": 35} | 1.8 | 12.5 | 214 | 1.28 | PASS |
| 11 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_sensitivity | {"vol_mult": 4.0} | 1.8 | 12.5 | 214 | 1.28 | PASS |
| 12 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_sensitivity | {"vol_floor_mult": 1.0} | 1.8 | 12.5 | 214 | 1.57 | PASS |
| 13 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | full_pool | - | 1.8 | 12.5 | 213 | 1.46 | PASS |
| 14 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | rsi_sensitivity | {"rsi_max": 45} | 1.8 | 12.4 | 212 | 1.54 | PASS |
| 15 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_sensitivity | {"vol_floor_mult": 0.3} | 1.8 | 12.5 | 213 | 1.30 | PASS |
| 16 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_sensitivity | {"vol_mult": 3.5} | 1.8 | 12.5 | 213 | 1.03 | PASS |
| 17 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | rsi_sensitivity | {"rsi_max": 42} | 1.8 | 12.3 | 211 | 1.50 | PASS |
| 18 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | full_pool | - | 1.8 | 12.3 | 210 | 1.20 | PASS |
| 19 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_sensitivity | {"vol_floor_mult": 2.0} | 1.8 | 12.3 | 210 | 1.25 | PASS |
| 20 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | rsi_sensitivity | {"rsi_max": 40} | 1.7 | 12.1 | 207 | 1.51 | PASS |
| 21 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | full_pool | - | 1.7 | 12.1 | 206 | 1.35 | PASS |
| 22 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | full_pool | - | 1.7 | 12.1 | 206 | 1.16 | PASS |
| 23 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | rsi_sensitivity | {"rsi_max": 40} | 1.7 | 12.1 | 206 | 1.35 | PASS |
| 24 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | rsi_sensitivity | {"rsi_max": 38} | 1.7 | 12.1 | 206 | 1.38 | PASS |
| 25 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | rsi_sensitivity | {"rsi_max": 45} | 1.7 | 12.1 | 206 | 1.16 | PASS |
| 26 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | rsi_sensitivity | {"rsi_max": 47} | 1.7 | 12.1 | 206 | 1.16 | PASS |
| 27 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | rsi_sensitivity | {"rsi_max": 50} | 1.7 | 12.1 | 206 | 1.16 | PASS |
| 28 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_sensitivity | {"vol_floor_mult": 0.5} | 1.7 | 12.1 | 206 | 1.35 | PASS |
| 29 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_sensitivity | {"vol_floor_mult": 1.5} | 1.7 | 12.1 | 206 | 1.16 | PASS |
| 30 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | full_pool | - | 1.7 | 12.0 | 205 | 1.24 | PASS |

