# MS Sprint 2 Truth-Pass Summary

- **Timestamp**: 2026-03-02T22:19:02.167479+00:00
- **Configs tested**: 4
- **VERIFIED**: 4
- **CONDITIONAL**: 0
- **FAILED**: 0

## Scoreboard

| # | Config | Family | Verdict | Full PF | Full P&L | Trades | DD | Window | WF | Bootstrap (P5 PF / %Prof) |
|---|--------|--------|---------|---------|----------|--------|-----|--------|----|---------------------------|
| 1 | ms_018_mse_shallow | shift_pb | **VERIFIED** | 2.08 | $+46,016.70 | 697 | 21.3% | PASS | PASS | PASS (1.48 / 100%) |
| 2 | ms_005_msb_base | fvg_fill | **VERIFIED** | 1.65 | $+18,755.99 | 429 | 19.5% | PASS | PASS | PASS (1.19 / 100%) |
| 3 | ms_017_mse_fib618 | shift_pb | **VERIFIED** | 1.80 | $+27,497.56 | 475 | 28.0% | PASS | PASS | PASS (1.28 / 100%) |
| 4 | ms_007_msb_deep | fvg_fill | **VERIFIED** | 1.66 | $+9,337.95 | 344 | 22.9% | PASS | PASS | PASS (1.24 / 99%) |

### ms_018_mse_shallow (shift_pb) -- VERIFIED

- Window early [+]: 232tr PF=1.71 P&L=$+1,991.32
- Window mid [+]: 255tr PF=2.65 P&L=$+5,035.60
- Window late [+]: 220tr PF=2.01 P&L=$+5,117.75
- WF Early->Mid+Late [+]: cal=232tr PF=1.71, test=472tr PF=2.11
- WF Early+Mid->Late [+]: cal=480tr PF=2.32, test=220tr PF=2.01
- Bootstrap [+]: P5_PF=1.48 median_PF=2.08 %prof=100%

### ms_005_msb_base (fvg_fill) -- VERIFIED

- Window early [+]: 148tr PF=2.05 P&L=$+4,228.19
- Window mid [+]: 138tr PF=2.21 P&L=$+1,910.56
- Window late [+]: 143tr PF=1.56 P&L=$+2,234.36
- WF Early->Mid+Late [+]: cal=148tr PF=2.05, test=282tr PF=1.62
- WF Early+Mid->Late [+]: cal=285tr PF=2.01, test=143tr PF=1.56
- Bootstrap [+]: P5_PF=1.19 median_PF=1.65 %prof=100%

### ms_017_mse_fib618 (shift_pb) -- VERIFIED

- Window early [+]: 155tr PF=1.62 P&L=$+1,419.87
- Window mid [+]: 174tr PF=5.06 P&L=$+9,164.25
- Window late [+]: 149tr PF=1.35 P&L=$+1,008.91
- WF Early->Mid+Late [+]: cal=155tr PF=1.62, test=325tr PF=1.82
- WF Early+Mid->Late [+]: cal=324tr PF=3.73, test=149tr PF=1.35
- Bootstrap [+]: P5_PF=1.28 median_PF=1.83 %prof=100%

### ms_007_msb_deep (fvg_fill) -- VERIFIED

- Window early [+]: 115tr PF=1.78 P&L=$+2,969.65
- Window mid [+]: 113tr PF=1.40 P&L=$+632.60
- Window late [+]: 123tr PF=1.95 P&L=$+2,256.88
- WF Early->Mid+Late [+]: cal=115tr PF=1.78, test=233tr PF=1.68
- WF Early+Mid->Late [+]: cal=224tr PF=1.51, test=123tr PF=1.95
- Bootstrap [+]: P5_PF=1.24 median_PF=1.65 %prof=99%

