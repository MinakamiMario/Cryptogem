# 4H DualConfirm Backtest — sweep_v1_023_tpsl_tp7_sl10_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:45.282239+00:00
- **Git**: 2659755
- **Config**: sweep_plan:tpsl_tp7_sl10 (idx=23)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 39 |
| Win Rate | 53.8% |
| P&L | $+307.38 |
| Final Equity | $2,307.38 |
| Profit Factor | 1.15 |
| Max Drawdown | 30.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 3/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 39 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 30.4% (within limit) |
| G3:PROFIT_FACTOR | FAIL | PF 1.15 (below 1.3) |
| G4:EXPECTANCY | PASS | EV/trade $7.88 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-110 | H2: 21tr $+418 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| PROFIT TARGET | 17 | $+2,081.82 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 7 | $-1,485.02 | 0 |
| TIME MAX | 15 | $-289.41 | 4 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 40,
  "rsi_recovery": false,
  "sl_pct": 10.0,
  "time_max_bars": 10,
  "tp_pct": 7.0,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
