# 4H DualConfirm Backtest — sweep_v1_026_tpsl_tp10_sl10_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:46.185871+00:00
- **Git**: 2659755
- **Config**: sweep_plan:tpsl_tp10_sl10 (idx=26)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 38 |
| Win Rate | 50.0% |
| P&L | $+233.87 |
| Final Equity | $2,233.87 |
| Profit Factor | 1.11 |
| Max Drawdown | 29.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 38 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.4% (within limit) |
| G3:PROFIT_FACTOR | FAIL | PF 1.11 (below 1.3) |
| G4:EXPECTANCY | PASS | EV/trade $6.15 (positive) |
| G5:ROBUSTNESS_SPLIT | PASS | H1: 18tr $+77 | H2: 20tr $+157 (PASS) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| PROFIT TARGET | 10 | $+1,847.17 | 10 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+43.32 | 1 |
| FIXED STOP | 7 | $-1,572.65 | 0 |
| TIME MAX | 20 | $-83.97 | 8 |

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
  "tp_pct": 10.0,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
