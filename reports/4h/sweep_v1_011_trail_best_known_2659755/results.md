# 4H DualConfirm Backtest — sweep_v1_011_trail_best_known_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:41.627325+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_best_known (idx=11)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 42 |
| Win Rate | 54.8% |
| P&L | $+5,787.24 |
| Final Equity | $7,787.24 |
| Profit Factor | 4.63 |
| Max Drawdown | 20.0% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 42 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 20.0% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.63 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $137.79 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 20tr $-198 | H2: 22tr $+5985 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 6 | $+689.57 | 6 |
| RSI RECOVERY | 5 | $+2,355.77 | 5 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+151.03 | 1 |
| HARD STOP | 1 | $-280.37 | 0 |
| TIME MAX | 21 | $+3,424.88 | 11 |
| TRAIL STOP | 8 | $-553.63 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 2.0,
  "breakeven": true,
  "exit_type": "trail",
  "max_pos": 1,
  "max_stop_pct": 12.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 6,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
