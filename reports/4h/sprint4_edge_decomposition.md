# Sprint 4 Edge Decomposition Report

## Summary
- Total configs: 10
- STRONG LEADs: 8
- WEAK LEADs: 1
- NEGATIVE: 1
- INSUFFICIENT: 0

## Recommendations
1. 8 STRONG LEAD(s) found: sprint4_005_h4s4a05_bblow_rsi40_vol1.5, sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5, sprint4_032_h4s4f02_z2.5_dclow_rsi40, sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol, sprint4_037_h4s4g01_vol3x_dczone_rsi40 -- advance to truth-pass (agent_team_v3.py full validation)
2. Family 'Z-Score Extreme' has best avg PF (1.26) -- focus further tuning here
3. Family 'Wick Rejection' has lowest stopout ratio (17%) -- entries have good geometric merit
4. RSI RECOVERY generates most profit across all configs ($48062 total, 856 exits) -- entries should maximize probability of this exit firing
5. Class A exits dominate in 100% of configs -- DC exit intelligence is working, focus on entry quality
6. 2 config(s) profitable at lower fees but not Kraken (26 bps) -- consider MEXC (10 bps) for these

## Config Scoreboard

| Config | PF | Trades | WR% | A Share | Stopout | Grade | BE Fee |
|--------|-----|--------|------|---------|---------|-------|--------|
| sprint4_041_h4s4g05_vol3x_bblow_rsi40 | 1.41 | 216 | 54.6 | 100% | 18% | STRONG_LEAD | 50 bps |
| sprint4_032_h4s4f02_z2.5_dclow_rsi40 | 1.35 | 206 | 52.9 | 100% | 17% | STRONG_LEAD | 50 bps |
| sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | 1.28 | 214 | 53.3 | 100% | 21% | STRONG_LEAD | 50 bps |
| sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | 1.25 | 101 | 54.5 | 99% | 17% | STRONG_LEAD | 50 bps |
| sprint4_037_h4s4g01_vol3x_dczone_rsi40 | 1.18 | 222 | 50.5 | 100% | 18% | STRONG_LEAD | 40 bps |
| sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | 1.16 | 206 | 49.5 | 100% | 19% | STRONG_LEAD | 50 bps |
| sprint4_005_h4s4a05_bblow_rsi40_vol1.5 | 1.07 | 155 | 50.3 | 100% | 23% | STRONG_LEAD | 41 bps |
| sprint4_038_h4s4g02_vol4x_dczone_rsi40 | 0.98 | 226 | 50.9 | 100% | 21% | STRONG_LEAD | 14 bps |
| sprint4_039_h4s4g03_vol5x_dczone_rsi35 | 0.98 | 219 | 48.4 | 100% | 20% | WEAK_LEAD | 18 bps |
| sprint4_012_h4s4b05_dclow_wick40_rsi40_highvol | 0.67 | 232 | 45.7 | 100% | 17% | NEGATIVE | 0 bps |

## Family Analysis

| Family | Configs | Avg PF | Avg Stopout | Avg A Share | Best Config | Grade |
|--------|---------|--------|-------------|-------------|-------------|-------|
| Z-Score Extreme | 2 | 1.26 | 18% | 100% | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | STRONG_LEAD |
| Volume Capitulation | 5 | 1.16 | 20% | 100% | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | STRONG_LEAD |
| DC-Lite | 2 | 1.16 | 20% | 100% | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | STRONG_LEAD |
| Wick Rejection | 1 | 0.67 | 17% | 100% | sprint4_012_h4s4b05_dclow_wick40_rsi40_highvol | NEGATIVE |

## Exit Intelligence
- Best exit reason: RSI RECOVERY
- Worst exit reason: FIXED STOP
- Class A dominance: 100%

| Exit Reason | Total P&L | Total Count |
|-------------|-----------|-------------|
| RSI RECOVERY | $48062 | 856 |
| DC TARGET | $20082 | 278 |
| BB TARGET | $2757 | 64 |
| END | $-434 | 25 |
| TIME MAX | $-15524 | 394 |
| FIXED STOP | $-43594 | 380 |

## Top Config Details

### sprint4_041_h4s4g05_vol3x_bblow_rsi40
- PF: 1.41 | Trades: 216 | WR: 54.6% | DD: 49.8%
- Class A: 134 trades, $11438 P&L, 87% WR
- Class B: 82 trades, $-8089 P&L, 2% WR
- Stopout: 18% ratio, $-5826 cost
- Fee: gross $4115, fees $1035, BE fee 50 bps
- Bars: winners 6.9, losers 11.4, Class A 7.5
- Notes:
  - STRONG LEAD: PF=1.41, Class A share=100%, stopout ratio=18%
  - Best exit: RSI RECOVERY ($8134, 93 trades, 85% WR)
  - Worst exit: FIXED STOP ($-5826, 39 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 18% -- entries have good geometric placement

### sprint4_032_h4s4f02_z2.5_dclow_rsi40
- PF: 1.35 | Trades: 206 | WR: 52.9% | DD: 44.0%
- Class A: 124 trades, $18061 P&L, 88% WR
- Class B: 82 trades, $-13146 P&L, 0% WR
- Stopout: 17% ratio, $-8954 cost
- Fee: gross $5988, fees $1711, BE fee 50 bps
- Bars: winners 7.1, losers 11.7, Class A 7.7
- Notes:
  - STRONG LEAD: PF=1.35, Class A share=100%, stopout ratio=17%
  - Best exit: DC TARGET ($8828, 29 trades, 83% WR)
  - Worst exit: FIXED STOP ($-8954, 34 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 17% -- entries have good geometric placement

### sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35
- PF: 1.28 | Trades: 214 | WR: 53.3% | DD: 59.1%
- Class A: 127 trades, $8171 P&L, 87% WR
- Class B: 87 trades, $-6354 P&L, 3% WR
- Stopout: 21% ratio, $-5109 cost
- Fee: gross $2646, fees $769, BE fee 50 bps
- Bars: winners 7.0, losers 10.9, Class A 7.5
- Notes:
  - STRONG LEAD: PF=1.28, Class A share=100%, stopout ratio=21%
  - Best exit: RSI RECOVERY ($5789, 84 trades, 84% WR)
  - Worst exit: FIXED STOP ($-5109, 44 trades)
  - Breakeven fee: 50.0 bps per side

### sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5
- PF: 1.25 | Trades: 101 | WR: 54.5% | DD: 40.8%
- Class A: 64 trades, $2566 P&L, 83% WR
- Class B: 37 trades, $-2028 P&L, 5% WR
- Stopout: 17% ratio, $-1486 cost
- Fee: gross $811, fees $291, BE fee 50 bps
- Bars: winners 7.4, losers 11.5, Class A 8.3
- Notes:
  - STRONG LEAD: PF=1.25, Class A share=99%, stopout ratio=17%
  - Best exit: RSI RECOVERY ($2028, 48 trades, 79% WR)
  - Worst exit: FIXED STOP ($-1486, 17 trades)
  - Breakeven fee: 50.0 bps per side
  - LOW STOPOUT: 17% -- entries have good geometric placement

### sprint4_037_h4s4g01_vol3x_dczone_rsi40
- PF: 1.18 | Trades: 222 | WR: 50.5% | DD: 79.7%
- Class A: 136 trades, $8482 P&L, 81% WR
- Class B: 86 trades, $-7144 P&L, 2% WR
- Stopout: 18% ratio, $-5162 cost
- Fee: gross $1323, fees $850, BE fee 40 bps
- Bars: winners 7.1, losers 10.8, Class A 7.7
- Notes:
  - STRONG LEAD: PF=1.18, Class A share=100%, stopout ratio=18%
  - Best exit: RSI RECOVERY ($7046, 102 trades, 79% WR)
  - Worst exit: FIXED STOP ($-5162, 41 trades)
  - Breakeven fee: 40.5 bps per side
  - LOW STOPOUT: 18% -- entries have good geometric placement
