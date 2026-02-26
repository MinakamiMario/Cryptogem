# Sprint 4 Edge Decomposition Report

## Summary
- Total configs: 30
- STRONG LEADs: 6
- WEAK LEADs: 1
- NEGATIVE: 23
- INSUFFICIENT: 0

## Recommendations
1. 6 STRONG LEAD(s) found: sweep_v1_004_sv1a04_rsi35_p8_atr1.5, sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh, sweep_v1_002_sv1a02_rsi40_p5_atr1.5, sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45, sweep_v1_006_sv1a06_rsi45_p8_atr2.0 -- advance to truth-pass (agent_team_v3.py full validation)
2. Family 'SwingFractalBounce' has best avg PF (1.17) -- focus further tuning here
3. Family 'SwingFractalBounce' has lowest stopout ratio (12%) -- entries have good geometric merit
4. RSI RECOVERY generates most profit across all configs ($85589 total, 3423 exits) -- entries should maximize probability of this exit firing
5. Class A exits dominate in 100% of configs -- DC exit intelligence is working, focus on entry quality
6. 1 config(s) profitable at lower fees but not Kraken (26 bps) -- consider MEXC (10 bps) for these

## Config Scoreboard

| Config | PF | Trades | WR% | A Share | Stopout | Grade | BE Fee |
|--------|-----|--------|------|---------|---------|-------|--------|
| sweep_v1_006_sv1a06_rsi45_p8_atr2.0 | 1.52 | 347 | 58.8 | 100% | 10% | STRONG_LEAD | 50 bps |
| sweep_v1_002_sv1a02_rsi40_p5_atr1.5 | 1.35 | 306 | 57.8 | 100% | 11% | STRONG_LEAD | 50 bps |
| sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh | 1.24 | 313 | 53.4 | 100% | 14% | STRONG_LEAD | 50 bps |
| sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45 | 1.09 | 259 | 59.1 | 100% | 14% | STRONG_LEAD | 41 bps |
| sweep_v1_003_sv1a03_rsi45_p5_atr2.0 | 1.06 | 308 | 56.8 | 100% | 13% | STRONG_LEAD | 36 bps |
| sweep_v1_004_sv1a04_rsi35_p8_atr1.5 | 1.01 | 286 | 55.9 | 100% | 12% | STRONG_LEAD | 28 bps |
| sweep_v1_016_sv1c04_hh1_sw8_tol1.5 | 0.95 | 239 | 53.1 | 100% | 13% | WEAK_LEAD | 17 bps |
| sweep_v1_013_sv1c01_hh1_sw5_tol1.0 | 0.87 | 238 | 53.4 | 100% | 17% | NEGATIVE | 0 bps |
| sweep_v1_007_sv1b01_dclow_rsi40_vol1.5_sw0.3 | 0.86 | 231 | 54.5 | 100% | 16% | NEGATIVE | 0 bps |
| sweep_v1_001_sv1a01_rsi35_p5_atr1.0 | 0.83 | 284 | 56.3 | 100% | 14% | NEGATIVE | 0 bps |
| sweep_v1_011_sv1b05_dclow_rsi45_vol1.0_sw0.3 | 0.82 | 245 | 54.7 | 100% | 16% | NEGATIVE | 0 bps |
| sweep_v1_023_sv1d05_pctile30_sq5_expand_rsi45 | 0.78 | 261 | 55.9 | 100% | 13% | NEGATIVE | 0 bps |
| sweep_v1_009_sv1b03_pivot_rsi40_vol1.5_sw0.3 | 0.78 | 277 | 55.2 | 100% | 15% | NEGATIVE | 0 bps |
| sweep_v1_017_sv1c05_hh2_sw8_tol1.0_rsi35 | 0.75 | 123 | 51.2 | 100% | 13% | NEGATIVE | 0 bps |
| sweep_v1_014_sv1c02_hh2_sw5_tol1.5 | 0.73 | 183 | 55.2 | 100% | 14% | NEGATIVE | 0 bps |
| sweep_v1_021_sv1d03_pctile40_sq3_expand | 0.72 | 243 | 53.5 | 100% | 14% | NEGATIVE | 0 bps |
| sweep_v1_024_sv1d06_pctile30_sq3_volhigh | 0.70 | 248 | 54.0 | 100% | 13% | NEGATIVE | 0 bps |
| sweep_v1_025_sv1e01_pctile5_gap10 | 0.69 | 205 | 42.9 | 99% | 19% | NEGATIVE | 0 bps |
| sweep_v1_030_sv1e06_pctile5_gap15_rsi35 | 0.69 | 205 | 42.9 | 99% | 19% | NEGATIVE | 0 bps |
| sweep_v1_008_sv1b02_dclow_rsi35_vol2.0_sw0.5 | 0.69 | 185 | 50.3 | 100% | 15% | NEGATIVE | 0 bps |
| sweep_v1_015_sv1c03_hh3_sw5_tol2.0 | 0.65 | 61 | 55.7 | 100% | 13% | NEGATIVE | 0 bps |
| sweep_v1_020_sv1d02_pctile30_sq5 | 0.62 | 263 | 52.1 | 100% | 13% | NEGATIVE | 0 bps |
| sweep_v1_026_sv1e02_pctile10_gap10 | 0.62 | 202 | 41.6 | 100% | 19% | NEGATIVE | 0 bps |
| sweep_v1_027_sv1e03_pctile15_gap15 | 0.62 | 202 | 41.6 | 100% | 19% | NEGATIVE | 0 bps |
| sweep_v1_028_sv1e04_pctile10_gap5_rsi35 | 0.61 | 202 | 42.1 | 100% | 20% | NEGATIVE | 0 bps |
| sweep_v1_010_sv1b04_both_rsi40_vol2.0_sw0.5 | 0.59 | 210 | 48.6 | 100% | 10% | NEGATIVE | 0 bps |
| sweep_v1_019_sv1d01_pctile20_sq3 | 0.56 | 253 | 50.2 | 100% | 11% | NEGATIVE | 0 bps |
| sweep_v1_022_sv1d04_pctile20_sq8_rsi35 | 0.52 | 197 | 47.2 | 100% | 15% | NEGATIVE | 0 bps |
| sweep_v1_029_sv1e05_pctile20_gap5_volhigh | 0.49 | 203 | 41.4 | 100% | 21% | NEGATIVE | 0 bps |
| sweep_v1_012_sv1b06_pivot8_rsi35_vol3.0_sw0.5 | 0.45 | 118 | 48.3 | 100% | 17% | NEGATIVE | 0 bps |

## Family Analysis

| Family | Configs | Avg PF | Avg Stopout | Avg A Share | Best Config | Grade |
|--------|---------|--------|-------------|-------------|-------------|-------|
| SwingFractalBounce | 6 | 1.17 | 12% | 100% | sweep_v1_006_sv1a06_rsi45_p8_atr2.0 | STRONG_LEAD |
| TrendPullback | 6 | 0.84 | 14% | 100% | sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45 | STRONG_LEAD |
| WickSweepReclaim | 6 | 0.70 | 15% | 100% | sweep_v1_007_sv1b01_dclow_rsi40_vol1.5_sw0.3 | NEGATIVE |
| ATRExhaustion | 6 | 0.65 | 13% | 100% | sweep_v1_023_sv1d05_pctile30_sq5_expand_rsi45 | NEGATIVE |
| CrossRSIExtreme | 6 | 0.62 | 19% | 100% | sweep_v1_025_sv1e01_pctile5_gap10 | NEGATIVE |

## Exit Intelligence
- Best exit reason: RSI RECOVERY
- Worst exit reason: FIXED STOP
- Class A dominance: 100%

| Exit Reason | Total P&L | Total Count |
|-------------|-----------|-------------|
| RSI RECOVERY | $85589 | 3423 |
| DC TARGET | $23708 | 823 |
| BB TARGET | $11207 | 298 |
| END | $-581 | 77 |
| TIME MAX | $-45541 | 1281 |
| FIXED STOP | $-86035 | 995 |

## Top Config Details

### sweep_v1_006_sv1a06_rsi45_p8_atr2.0
- PF: 1.52 | Trades: 347 | WR: 58.8% | DD: 63.1%
- Class A: 264 trades, $16816 P&L, 77% WR
- Class B: 83 trades, $-10782 P&L, 1% WR
- Stopout: 10% ratio, $-6961 cost
- Fee: gross $8339, fees $2306, BE fee 50 bps
- Bars: winners 4.1, losers 8.0, Class A 4.2
- Notes:
  - STRONG LEAD: PF=1.52, Class A share=100%, stopout ratio=10%
  - Best exit: RSI RECOVERY ($12760, 218 trades, 74% WR)
  - Worst exit: FIXED STOP ($-6961, 36 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 10% -- entries have good geometric placement

### sweep_v1_002_sv1a02_rsi40_p5_atr1.5
- PF: 1.35 | Trades: 306 | WR: 57.8% | DD: 56.8%
- Class A: 232 trades, $10533 P&L, 76% WR
- Class B: 74 trades, $-7591 P&L, 0% WR
- Stopout: 11% ratio, $-4623 cost
- Fee: gross $4563, fees $1621, BE fee 50 bps
- Bars: winners 4.8, losers 8.9, Class A 5.1
- Notes:
  - STRONG LEAD: PF=1.35, Class A share=100%, stopout ratio=11%
  - Best exit: RSI RECOVERY ($8927, 197 trades, 75% WR)
  - Worst exit: FIXED STOP ($-4623, 34 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 11% -- entries have good geometric placement

### sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh
- PF: 1.24 | Trades: 313 | WR: 53.4% | DD: 41.9%
- Class A: 227 trades, $13996 P&L, 74% WR
- Class B: 86 trades, $-11149 P&L, 0% WR
- Stopout: 14% ratio, $-7942 cost
- Fee: gross $4705, fees $1857, BE fee 50 bps
- Bars: winners 3.8, losers 9.1, Class A 4.6
- Notes:
  - STRONG LEAD: PF=1.24, Class A share=100%, stopout ratio=14%
  - Best exit: RSI RECOVERY ($9814, 175 trades, 69% WR)
  - Worst exit: FIXED STOP ($-7942, 43 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 14% -- entries have good geometric placement

### sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45
- PF: 1.09 | Trades: 259 | WR: 59.1% | DD: 55.9%
- Class A: 180 trades, $7193 P&L, 83% WR
- Class B: 79 trades, $-6590 P&L, 4% WR
- Stopout: 14% ratio, $-4513 cost
- Fee: gross $1632, fees $1030, BE fee 41 bps
- Bars: winners 6.0, losers 10.1, Class A 6.4
- Notes:
  - STRONG LEAD: PF=1.09, Class A share=100%, stopout ratio=14%
  - Best exit: RSI RECOVERY ($4894, 149 trades, 81% WR)
  - Worst exit: FIXED STOP ($-4513, 36 trades)
  - Breakeven fee: 41.2 bps per side
  - LOW STOPOUT: 14% -- entries have good geometric placement

### sweep_v1_003_sv1a03_rsi45_p5_atr2.0
- PF: 1.06 | Trades: 308 | WR: 56.8% | DD: 55.3%
- Class A: 226 trades, $8081 P&L, 77% WR
- Class B: 82 trades, $-7562 P&L, 2% WR
- Stopout: 13% ratio, $-5116 cost
- Fee: gross $1842, fees $1323, BE fee 36 bps
- Bars: winners 4.7, losers 8.8, Class A 5.0
- Notes:
  - STRONG LEAD: PF=1.06, Class A share=100%, stopout ratio=13%
  - Best exit: RSI RECOVERY ($6574, 189 trades, 75% WR)
  - Worst exit: FIXED STOP ($-5116, 40 trades)
  - Breakeven fee: 36.3 bps per side
  - LOW STOPOUT: 13% -- entries have good geometric placement
