# Sprint 4 DD-Fix Scoreboard -- Risk Wrappers for Drawdown Reduction

- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Git**: 9a606d9
- **Generated**: 2026-02-17T20:40:26.980581+00:00
- **Initial capital**: $2,000
- **Fee**: 26.0 bps per side
- **Total combos**: 55
- **DEPLOY_CANDIDATE** (DD <= 20%, PF >= 1.15): 1
- **INVESTIGATE** (DD <= 25%, PF >= 1.10): 3
- **NOT_VIABLE**: 51

## Methodology

Post-hoc equity simulation applying risk wrappers to existing trade lists.
Entry and exit logic are UNCHANGED. Only sizing or trade admission is modified.

### Wrappers
1. **DD Throttle**: Scale position size by factor when DD > threshold
2. **Vol Scaling**: Size inversely proportional to ATR (capped 0.25x-2.0x)
3. **Adaptive MaxPos**: Reduce max concurrent positions (3/2/1) by DD level
4. **Cooldown Ext**: Extend post-stop cooldown beyond default 8 bars

## DEPLOY CANDIDATES (DD <= 20%, PF >= 1.15)

| Config | Wrapper | Params | Orig DD | New DD | DD delta | Orig PF | New PF | PF delta | Trades | P&L |
|--------|---------|--------|---------|--------|----------|---------|--------|----------|--------|-----|
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_scale | atr14,pctl=25 | 52.5% | 18.8% | +64.1% | 1.16 | 1.82 | +56.9% | 206 | $+2,794.38 |

## INVESTIGATE (DD <= 25%, PF >= 1.10)

| Config | Wrapper | Params | Orig DD | New DD | DD delta | Orig PF | New PF | PF delta | Trades | P&L |
|--------|---------|--------|---------|--------|----------|---------|--------|----------|--------|-----|
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | adaptive_maxpos | 3/2/1 by DD | 44.7% | 23.2% | +48.1% | 1.35 | 1.60 | +17.7% | 158 | $+6,145.70 |
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>10%,scale=0.25 | 36.4% | 22.8% | +37.4% | 1.41 | 1.16 | -17.5% | 216 | $+598.39 |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_scale | atr14,pctl=25 | 31.8% | 20.3% | +35.9% | 1.28 | 1.51 | +17.8% | 214 | $+2,246.43 |

## All Combos (sorted by DD reduction, PF >= 1.10 first)

| # | Verdict | Config | Wrapper | Params | Orig DD | New DD | DD delta | Orig PF | New PF | Trades | P&L |
|---|---------|--------|---------|--------|---------|--------|----------|---------|--------|--------|-----|
| 1 | DEPLOY_CANDIDATE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_scale | atr14,pctl=25 | 52.5% | 18.8% | +64.1% | 1.16 | 1.82 | 206 | $+2,794.38 |
| 2 | INVESTIGATE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | adaptive_maxpos | 3/2/1 by DD | 44.7% | 23.2% | +48.1% | 1.35 | 1.60 | 158 | $+6,145.70 |
| 3 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | vol_scale | atr14,pctl=50 | 52.5% | 30.9% | +41.1% | 1.16 | 1.63 | 206 | $+3,350.87 |
| 4 | INVESTIGATE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>10%,scale=0.25 | 36.4% | 22.8% | +37.4% | 1.41 | 1.16 | 216 | $+598.39 |
| 5 | INVESTIGATE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_scale | atr14,pctl=25 | 31.8% | 20.3% | +35.9% | 1.28 | 1.51 | 214 | $+2,246.43 |
| 6 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | dd_throttle | dd>10%,scale=0.5 | 37.7% | 25.0% | +33.6% | 1.25 | 1.16 | 101 | $+217.68 |
| 7 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | dd_throttle | dd>10%,scale=0.5 | 44.7% | 32.7% | +26.9% | 1.35 | 1.56 | 206 | $+4,757.14 |
| 8 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | dd_throttle | dd>20%,scale=0.5 | 44.7% | 34.2% | +23.4% | 1.35 | 1.42 | 206 | $+4,614.58 |
| 9 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_scale | atr14,pctl=25 | 36.4% | 28.1% | +22.7% | 1.41 | 1.59 | 216 | $+3,557.30 |
| 10 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | vol_scale | atr14,pctl=25 | 37.7% | 29.1% | +22.7% | 1.25 | 1.49 | 101 | $+772.04 |
| 11 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>10%,scale=0.5 | 36.4% | 28.7% | +21.2% | 1.41 | 1.29 | 216 | $+1,654.68 |
| 12 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>20%,scale=0.5 | 36.4% | 29.9% | +17.6% | 1.41 | 1.26 | 216 | $+1,827.32 |
| 13 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>15%,scale=0.5 | 36.4% | 30.0% | +17.6% | 1.41 | 1.27 | 216 | $+1,763.99 |
| 14 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | adaptive_maxpos | 3/2/1 by DD | 36.4% | 30.1% | +17.3% | 1.41 | 1.55 | 159 | $+3,559.71 |
| 15 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | dd_throttle | dd>15%,scale=0.5 | 44.7% | 37.6% | +15.8% | 1.35 | 1.45 | 206 | $+4,383.57 |
| 16 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | dd_throttle | dd>10%,scale=0.25 | 44.7% | 38.2% | +14.5% | 1.35 | 1.14 | 206 | $+669.80 |
| 17 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | dd_throttle | dd>10%,scale=0.5 | 31.8% | 28.6% | +9.8% | 1.28 | 1.12 | 214 | $+485.39 |
| 18 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | cooldown_ext | cd=12bars | 36.4% | 36.4% | +0.0% | 1.41 | 1.41 | 216 | $+3,349.79 |
| 19 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | cooldown_ext | cd=16bars | 36.4% | 36.4% | +0.0% | 1.41 | 1.41 | 216 | $+3,349.79 |
| 20 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | cooldown_ext | cd=20bars | 36.4% | 36.4% | +0.0% | 1.41 | 1.41 | 216 | $+3,349.79 |
| 21 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | cooldown_ext | cd=12bars | 44.7% | 44.7% | +0.0% | 1.35 | 1.35 | 206 | $+4,915.03 |
| 22 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | cooldown_ext | cd=16bars | 44.7% | 44.7% | +0.0% | 1.35 | 1.35 | 206 | $+4,915.03 |
| 23 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | cooldown_ext | cd=20bars | 44.7% | 44.7% | +0.0% | 1.35 | 1.35 | 206 | $+4,915.03 |
| 24 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | cooldown_ext | cd=12bars | 31.8% | 31.8% | +0.0% | 1.28 | 1.28 | 214 | $+1,817.28 |
| 25 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | cooldown_ext | cd=16bars | 31.8% | 31.8% | +0.0% | 1.28 | 1.28 | 214 | $+1,817.28 |
| 26 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | cooldown_ext | cd=20bars | 31.8% | 31.8% | +0.0% | 1.28 | 1.28 | 214 | $+1,817.28 |
| 27 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | cooldown_ext | cd=12bars | 37.7% | 37.7% | +0.0% | 1.25 | 1.25 | 101 | $+537.94 |
| 28 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | cooldown_ext | cd=16bars | 37.7% | 37.7% | +0.0% | 1.25 | 1.25 | 101 | $+537.94 |
| 29 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | cooldown_ext | cd=20bars | 37.7% | 37.7% | +0.0% | 1.25 | 1.25 | 101 | $+537.94 |
| 30 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | cooldown_ext | cd=12bars | 52.5% | 52.5% | +0.0% | 1.16 | 1.16 | 206 | $+810.21 |
| 31 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | cooldown_ext | cd=16bars | 52.5% | 52.5% | +0.0% | 1.16 | 1.16 | 206 | $+810.21 |
| 32 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | cooldown_ext | cd=20bars | 52.5% | 52.5% | +0.0% | 1.16 | 1.16 | 206 | $+810.21 |
| 33 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | vol_scale | atr14,pctl=50 | 37.7% | 40.4% | -7.2% | 1.25 | 1.71 | 101 | $+1,665.32 |
| 34 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | vol_scale | atr14,pctl=50 | 36.4% | 39.3% | -8.0% | 1.41 | 1.55 | 216 | $+5,232.66 |
| 35 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | vol_scale | atr14,pctl=50 | 31.8% | 39.4% | -24.2% | 1.28 | 1.46 | 214 | $+3,217.21 |
| 36 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_scale | atr14,pctl=25 | 44.7% | 56.5% | -26.4% | 1.35 | 1.34 | 206 | $+2,945.36 |
| 37 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | vol_scale | atr14,pctl=50 | 44.7% | 63.2% | -41.4% | 1.35 | 1.17 | 206 | $+2,480.03 |
| 38 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | dd_throttle | dd>10%,scale=0.25 | 52.5% | 22.1% | +57.8% | 1.16 | 0.90 | 206 | $-161.15 |
| 39 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | dd_throttle | dd>10%,scale=0.25 | 37.7% | 18.7% | +50.4% | 1.25 | 1.06 | 101 | $+57.55 |
| 40 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | dd_throttle | dd>15%,scale=0.25 | 52.5% | 27.5% | +47.5% | 1.16 | 0.79 | 206 | $-405.17 |
| 41 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | dd_throttle | dd>15%,scale=0.25 | 37.7% | 21.7% | +42.4% | 1.25 | 1.00 | 101 | $-2.56 |
| 42 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | dd_throttle | dd>10%,scale=0.25 | 31.8% | 20.5% | +35.4% | 1.28 | 1.01 | 214 | $+38.76 |
| 43 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | dd_throttle | dd>15%,scale=0.5 | 52.5% | 34.2% | +34.7% | 1.16 | 1.00 | 206 | $-0.04 |
| 44 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | dd_throttle | dd>10%,scale=0.5 | 52.5% | 34.5% | +34.2% | 1.16 | 1.00 | 206 | $-5.07 |
| 45 | NOT_VIABLE | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | dd_throttle | dd>15%,scale=0.25 | 36.4% | 25.8% | +29.2% | 1.41 | 1.08 | 216 | $+345.70 |
| 46 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | dd_throttle | dd>15%,scale=0.5 | 37.7% | 27.0% | +28.3% | 1.25 | 1.09 | 101 | $+131.83 |
| 47 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | dd_throttle | dd>20%,scale=0.5 | 52.5% | 37.9% | +27.8% | 1.16 | 0.94 | 206 | $-175.88 |
| 48 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | adaptive_maxpos | 3/2/1 by DD | 31.8% | 25.5% | +19.6% | 1.28 | 1.09 | 141 | $+357.90 |
| 49 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | dd_throttle | dd>15%,scale=0.25 | 31.8% | 25.8% | +18.6% | 1.28 | 0.96 | 214 | $-123.93 |
| 50 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | dd_throttle | dd>20%,scale=0.5 | 37.7% | 31.3% | +17.0% | 1.25 | 1.04 | 101 | $+66.21 |
| 51 | NOT_VIABLE | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | adaptive_maxpos | 3/2/1 by DD | 37.7% | 31.5% | +16.5% | 1.25 | 0.77 | 65 | $-392.60 |
| 52 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | dd_throttle | dd>15%,scale=0.5 | 31.8% | 30.6% | +3.6% | 1.28 | 1.07 | 214 | $+313.03 |
| 53 | NOT_VIABLE | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | dd_throttle | dd>15%,scale=0.25 | 44.7% | 45.7% | -2.2% | 1.35 | 1.07 | 206 | $+351.81 |
| 54 | NOT_VIABLE | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | dd_throttle | dd>20%,scale=0.5 | 31.8% | 33.2% | -4.6% | 1.28 | 1.06 | 214 | $+320.71 |
| 55 | NOT_VIABLE | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | adaptive_maxpos | 3/2/1 by DD | 52.5% | 64.8% | -23.6% | 1.16 | 0.46 | 81 | $-1,206.99 |

## Strategy Summary

| Strategy | Combos | Deploy | Investigate | Avg DD Reduction | Avg PF Change |
|----------|--------|--------|-------------|------------------|---------------|
| dd_throttle | 25 | 0 | 1 | +25.5% | -13.7% |
| vol_scale | 10 | 1 | 1 | +7.9% | +19.5% |
| adaptive_maxpos | 5 | 0 | 1 | +15.6% | -17.2% |
| cooldown_ext | 15 | 0 | 0 | +0.0% | +0.0% |
