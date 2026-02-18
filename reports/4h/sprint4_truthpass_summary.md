# Sprint 4 Truth-Pass Summary

- **Timestamp**: 2026-02-17T21:08:12.795772+00:00
- **Configs tested**: 5
- **VERIFIED**: 1
- **CONDITIONAL**: 1
- **FAILED**: 3

## Scoreboard

| # | Config | Verdict | Full PF | Full P&L | Trades | Window | WF | Bootstrap (P5 PF / %Prof) |
|---|--------|---------|---------|----------|--------|--------|----|---------------------------|
| 1 | sprint4_041_h4s4g05_vol3x_bblow_rsi40 | **VERIFIED** | 1.41 | $+2,283.84 | 216 | PASS | PASS | PASS (0.92 / 91%) |
| 2 | sprint4_032_h4s4f02_z2.5_dclow_rsi40 | **FAILED** | 1.35 | $+4,915.03 | 206 | FAIL | FAIL | FAIL (0.74 / 74%) |
| 3 | sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 | **CONDITIONAL** | 1.28 | $+823.92 | 214 | PASS | PASS | FAIL (0.78 / 78%) |
| 4 | sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 | **FAILED** | 1.25 | $+537.94 | 101 | PASS | FAIL | FAIL (0.62 / 65%) |
| 5 | sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol | **FAILED** | 1.16 | $+810.21 | 206 | PASS | FAIL | FAIL (0.56 / 60%) |

### sprint4_041_h4s4g05_vol3x_bblow_rsi40 -- VERIFIED

- Window early [+]: 71tr PF=1.38 P&L=$+874.96
- Window mid [-]: 72tr PF=0.88 P&L=$-189.32
- Window late [+]: 75tr PF=1.39 P&L=$+276.63
- WF Early->Mid+Late [+]: cal=71tr PF=1.38, test=144tr PF=1.37
- WF Early+Mid->Late [+]: cal=144tr PF=1.17, test=75tr PF=1.39
- Bootstrap [+]: P5_PF=0.92 median_PF=1.38 %prof=91%

### sprint4_032_h4s4f02_z2.5_dclow_rsi40 -- FAILED

- Window early [-]: 66tr PF=0.71 P&L=$-491.26
- Window mid [+]: 72tr PF=2.51 P&L=$+9,858.20
- Window late [-]: 67tr PF=0.63 P&L=$-608.16
- WF Early->Mid+Late [-]: cal=66tr PF=0.71, test=144tr PF=1.46
- WF Early+Mid->Late [-]: cal=134tr PF=1.97, test=67tr PF=0.63
- Bootstrap [-]: P5_PF=0.74 median_PF=1.32 %prof=74%

### sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35 -- CONDITIONAL

- Window early [+]: 72tr PF=1.02 P&L=$+48.18
- Window mid [+]: 74tr PF=1.00 P&L=$-0.03
- Window late [+]: 67tr PF=1.18 P&L=$-141.68
- WF Early->Mid+Late [+]: cal=72tr PF=1.02, test=141tr PF=1.40
- WF Early+Mid->Late [+]: cal=147tr PF=1.02, test=67tr PF=1.18
- Bootstrap [-]: P5_PF=0.78 median_PF=1.26 %prof=78%

### sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5 -- FAILED

- Window early [-]: 33tr PF=0.38 P&L=$-622.21
- Window mid [+]: 35tr PF=1.67 P&L=$+438.74
- Window late [+]: 34tr PF=1.81 P&L=$+722.63
- WF Early->Mid+Late [-]: cal=33tr PF=0.38, test=68tr PF=2.00
- WF Early+Mid->Late [-]: cal=68tr PF=0.78, test=34tr PF=1.81
- Bootstrap [-]: P5_PF=0.62 median_PF=1.17 %prof=65%

### sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol -- FAILED

- Window early [-]: 74tr PF=0.47 P&L=$-974.14
- Window mid [+]: 67tr PF=1.10 P&L=$+192.82
- Window late [+]: 75tr PF=1.64 P&L=$+2,056.81
- WF Early->Mid+Late [-]: cal=74tr PF=0.47, test=135tr PF=1.53
- WF Early+Mid->Late [-]: cal=138tr PF=0.73, test=75tr PF=1.64
- Bootstrap [-]: P5_PF=0.56 median_PF=1.13 %prof=60%

