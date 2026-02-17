# 4H DualConfirm Backtest — sweep_v1_027_tpsl_rsi42_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:46.476995+00:00
- **Git**: 2659755
- **Config**: sweep_plan:tpsl_rsi42 (idx=27)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 40 |
| Win Rate | 55.0% |
| P&L | $+456.48 |
| Final Equity | $2,456.48 |
| Profit Factor | 1.22 |
| Max Drawdown | 29.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 3/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 40 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.4% (within limit) |
| G3:PROFIT_FACTOR | FAIL | PF 1.22 (below 1.3) |
| G4:EXPECTANCY | PASS | EV/trade $11.41 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-110 | H2: 22tr $+567 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| PROFIT TARGET | 18 | $+2,256.14 | 18 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 7 | $-1,513.34 | 0 |
| TIME MAX | 15 | $-286.32 | 4 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 42,
  "rsi_recovery": false,
  "sl_pct": 10.0,
  "time_max_bars": 10,
  "tp_pct": 7.0,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
