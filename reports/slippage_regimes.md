# Slippage Regime Stress Test Report
*Generated: 2026-02-15 08:41:05*
*Runtime: 109.9s*

## Methodology
- Base fee: 0.26% per side (Kraken taker)
- Fee multipliers: [1, 2, 3]
- Slippage: [0, 10, 20, 35] bps per side
- Special: 1-candle-later fill = 2x fees + 50bps gap (eff. fee = 0.0102 = 1.020% per side)
- Initial capital: $2,000

## Verdicts Legend
- **GO**: Positive P&L at 2x fees + 20bps AND at 1-candle-later fill
- **SOFT-GO**: Positive at 2x fees + 20bps BUT negative at 1-candle-later
- **NO-GO**: Negative at 2x fees + 20bps

---
## Universe: TRADEABLE

### Config: C1 -- [GO]

Breakeven slippage at 2x fees: **98 bps**

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass/Fail |
|--------|---------|--------|-----|-----|----|-----|-----------|
| 1x_fees_0bps | 0.260% | 27 | $1,930.37 | 66.7% | 1.83 | 29.3% | PASS |
| 1x_fees_10bps | 0.360% | 27 | $1,724.96 | 66.7% | 1.75 | 30.0% | PASS |
| 1x_fees_20bps | 0.460% | 27 | $1,529.91 | 66.7% | 1.67 | 30.7% | PASS |
| 1x_fees_35bps | 0.610% | 27 | $1,255.65 | 66.7% | 1.56 | 31.8% | PASS |
| 2x_fees_0bps | 0.520% | 27 | $1,417.63 | 66.7% | 1.62 | 31.1% | PASS |
| 2x_fees_10bps | 0.620% | 27 | $1,238.11 | 66.7% | 1.55 | 31.8% | PASS |
| 2x_fees_20bps | 0.720% | 27 | $1,067.69 | 66.7% | 1.48 | 32.5% | PASS |
| 2x_fees_35bps | 0.870% | 27 | $828.14 | 66.7% | 1.38 | 33.6% | PASS |
| 3x_fees_0bps | 0.780% | 27 | $969.61 | 66.7% | 1.44 | 33.0% | PASS |
| 3x_fees_10bps | 0.880% | 27 | $812.83 | 66.7% | 1.37 | 33.7% | PASS |
| 3x_fees_20bps | 0.980% | 27 | $664.03 | 63.0% | 1.30 | 34.4% | PASS |
| 3x_fees_35bps | 1.130% | 27 | $454.96 | 63.0% | 1.21 | 35.4% | PASS |
| **1-candle-later** | 1.020% | 27 | $606.66 | 63.0% | 1.28 | 34.6% | PASS |

### Config: GRID_BEST -- [GO]

Breakeven slippage at 2x fees: **162 bps**

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass/Fail |
|--------|---------|--------|-----|-----|----|-----|-----------|
| 1x_fees_0bps | 0.260% | 32 | $4,718.27 | 68.8% | 2.61 | 16.4% | PASS |
| 1x_fees_10bps | 0.360% | 32 | $4,307.10 | 68.8% | 2.49 | 16.8% | PASS |
| 1x_fees_20bps | 0.460% | 32 | $3,920.36 | 68.8% | 2.37 | 17.1% | PASS |
| 1x_fees_35bps | 0.610% | 32 | $3,382.99 | 68.8% | 2.20 | 17.7% | PASS |
| 2x_fees_0bps | 0.520% | 32 | $3,699.45 | 68.8% | 2.30 | 17.3% | PASS |
| 2x_fees_10bps | 0.620% | 32 | $3,348.89 | 68.8% | 2.19 | 17.7% | PASS |
| 2x_fees_20bps | 0.720% | 32 | $3,019.26 | 68.8% | 2.08 | 18.0% | PASS |
| 2x_fees_35bps | 0.870% | 32 | $2,561.42 | 68.8% | 1.93 | 18.6% | PASS |
| 3x_fees_0bps | 0.780% | 32 | $2,831.02 | 68.8% | 2.02 | 18.2% | PASS |
| 3x_fees_10bps | 0.880% | 32 | $2,532.38 | 68.8% | 1.93 | 18.6% | PASS |
| 3x_fees_20bps | 0.980% | 32 | $2,251.66 | 65.6% | 1.83 | 19.4% | PASS |
| 3x_fees_35bps | 1.130% | 32 | $1,861.91 | 65.6% | 1.70 | 20.7% | PASS |
| **1-candle-later** | 1.020% | 32 | $2,144.16 | 65.6% | 1.80 | 19.8% | PASS |


---
## Universe: LIVE_CURRENT

### Config: C1 -- [GO]

Breakeven slippage at 2x fees: **149 bps**

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass/Fail |
|--------|---------|--------|-----|-----|----|-----|-----------|
| 1x_fees_0bps | 0.260% | 30 | $3,745.50 | 70.0% | 3.31 | 27.9% | PASS |
| 1x_fees_10bps | 0.360% | 30 | $3,414.81 | 70.0% | 3.10 | 28.2% | PASS |
| 1x_fees_20bps | 0.460% | 30 | $3,102.56 | 70.0% | 2.91 | 28.5% | PASS |
| 1x_fees_35bps | 0.610% | 30 | $2,666.58 | 70.0% | 2.64 | 29.0% | PASS |
| 2x_fees_0bps | 0.520% | 30 | $2,923.64 | 70.0% | 2.80 | 28.7% | PASS |
| 2x_fees_10bps | 0.620% | 30 | $2,638.83 | 70.0% | 2.62 | 29.0% | PASS |
| 2x_fees_20bps | 0.720% | 30 | $2,369.98 | 70.0% | 2.46 | 29.3% | PASS |
| 2x_fees_35bps | 0.870% | 30 | $1,994.74 | 70.0% | 2.23 | 29.8% | PASS |
| 3x_fees_0bps | 0.780% | 30 | $2,215.96 | 70.0% | 2.37 | 29.5% | PASS |
| 3x_fees_10bps | 0.880% | 30 | $1,970.86 | 66.7% | 2.22 | 29.8% | PASS |
| 3x_fees_20bps | 0.980% | 30 | $1,739.56 | 60.0% | 2.07 | 30.1% | PASS |
| 3x_fees_35bps | 1.130% | 30 | $1,416.85 | 56.7% | 1.86 | 30.6% | PASS |
| **1-candle-later** | 1.020% | 30 | $1,650.73 | 60.0% | 2.01 | 30.2% | PASS |

### Config: GRID_BEST -- [GO]

Breakeven slippage at 2x fees: **66 bps**

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass/Fail |
|--------|---------|--------|-----|-----|----|-----|-----------|
| 1x_fees_0bps | 0.260% | 35 | $1,833.39 | 60.0% | 1.68 | 23.6% | PASS |
| 1x_fees_10bps | 0.360% | 35 | $1,575.18 | 60.0% | 1.59 | 24.0% | PASS |
| 1x_fees_20bps | 0.460% | 35 | $1,333.89 | 60.0% | 1.51 | 24.3% | PASS |
| 1x_fees_35bps | 0.610% | 35 | $1,001.37 | 60.0% | 1.39 | 24.8% | PASS |
| 2x_fees_0bps | 0.520% | 35 | $1,196.80 | 60.0% | 1.46 | 24.5% | PASS |
| 2x_fees_10bps | 0.620% | 35 | $980.38 | 60.0% | 1.38 | 24.8% | PASS |
| 2x_fees_20bps | 0.720% | 35 | $778.23 | 60.0% | 1.30 | 25.1% | PASS |
| 2x_fees_35bps | 0.870% | 35 | $499.74 | 60.0% | 1.20 | 25.6% | PASS |
| 3x_fees_0bps | 0.780% | 35 | $663.39 | 60.0% | 1.26 | 25.3% | PASS |
| 3x_fees_10bps | 0.880% | 35 | $482.18 | 57.1% | 1.19 | 25.6% | PASS |
| 3x_fees_20bps | 0.980% | 35 | $312.96 | 51.4% | 1.13 | 25.9% | PASS |
| 3x_fees_35bps | 1.130% | 35 | $79.96 | 48.6% | 1.03 | 26.8% | PASS |
| **1-candle-later** | 1.020% | 35 | $248.46 | 51.4% | 1.10 | 26.1% | PASS |


---
## Summary

| Universe | Config | Verdict | Breakeven (2x fees) | P&L @baseline | P&L @2x+20bps | P&L @1-candle |
|----------|--------|---------|---------------------|---------------|---------------|---------------|
| TRADEABLE | C1 | [GO] | 98 bps | $1,930.37 | $1,067.69 | $606.66 |
| TRADEABLE | GRID_BEST | [GO] | 162 bps | $4,718.27 | $3,019.26 | $2,144.16 |
| LIVE_CURRENT | C1 | [GO] | 149 bps | $3,745.50 | $2,369.98 | $1,650.73 |
| LIVE_CURRENT | GRID_BEST | [GO] | 66 bps | $1,833.39 | $778.23 | $248.46 |
