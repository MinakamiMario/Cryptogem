# 4H DualConfirm Backtest — sweep_v1_018_hnotrl_tm15_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:43.756640+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_tm15 (idx=18)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 43 |
| Win Rate | 72.1% |
| P&L | $+3,859.34 |
| Final Equity | $5,859.34 |
| Profit Factor | 4.54 |
| Max Drawdown | 20.7% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 43 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 20.7% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.54 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $89.75 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-30 | H2: 25tr $+3890 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-53.70 | 0 |
| DC TARGET | 13 | $+733.60 | 13 |
| RSI RECOVERY | 20 | $+4,146.87 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+57.38 | 1 |
| FIXED STOP | 5 | $-818.22 | 0 |
| TIME MAX | 3 | $-206.59 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 2,
  "max_stop_pct": 15.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 15,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
