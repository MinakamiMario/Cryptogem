# Sweep v1 Truth-Pass Summary

- **Timestamp**: 2026-02-26T05:21:59.424759+00:00
- **Configs tested**: 3
- **Min trades gate**: 80
- **VERIFIED**: 1
- **CONDITIONAL**: 1
- **FAILED**: 1

## Scoreboard

| # | Config | Verdict | Full PF | Full P&L | Trades | Window | WF | Bootstrap (P5 PF / %Prof) |
|---|--------|---------|---------|----------|--------|--------|----|---------------------------|
| 1 | sweep_v1_006_sv1a06_rsi45_p8_atr2.0 | **VERIFIED** | 1.52 | $+3,425.19 | 347 | PASS | PASS | PASS (0.98 / 94%) |
| 2 | sweep_v1_002_sv1a02_rsi40_p5_atr1.5 | **CONDITIONAL** | 1.35 | $+744.52 | 306 | PASS | PASS | FAIL (0.82 / 82%) |
| 3 | sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh | **FAILED** | 1.24 | $+2,847.68 | 313 | FAIL | FAIL | FAIL (0.76 / 74%) |

### sweep_v1_006_sv1a06_rsi45_p8_atr2.0 -- VERIFIED

- Window early [-]: 112tr PF=0.79 P&L=$-382.41
- Window mid [+]: 119tr PF=4.41 P&L=$+7,654.50
- Window late [+]: 124tr PF=1.15 P&L=$-414.68
- WF Early->Mid+Late [-]: cal=112tr PF=0.79, test=236tr PF=1.69
- WF Early+Mid->Late [+]: cal=230tr PF=2.36, test=124tr PF=1.15
- Bootstrap [+]: P5_PF=0.98 median_PF=1.51 %prof=94%

### sweep_v1_002_sv1a02_rsi40_p5_atr1.5 -- CONDITIONAL

- Window early [-]: 103tr PF=0.89 P&L=$-260.60
- Window mid [+]: 102tr PF=3.58 P&L=$+4,528.85
- Window late [+]: 105tr PF=1.19 P&L=$-676.16
- WF Early->Mid+Late [-]: cal=103tr PF=0.89, test=205tr PF=1.58
- WF Early+Mid->Late [+]: cal=203tr PF=1.83, test=105tr PF=1.19
- Bootstrap [-]: P5_PF=0.82 median_PF=1.34 %prof=82%

### sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh -- FAILED

- Window early [-]: 109tr PF=0.91 P&L=$-269.06
- Window mid [+]: 99tr PF=2.86 P&L=$+5,095.55
- Window late [-]: 110tr PF=0.80 P&L=$-449.34
- WF Early->Mid+Late [-]: cal=109tr PF=0.91, test=206tr PF=1.35
- WF Early+Mid->Late [-]: cal=206tr PF=1.75, test=110tr PF=0.80
- Bootstrap [-]: P5_PF=0.76 median_PF=1.20 %prof=74%

