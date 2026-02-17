# 4H DualConfirm Backtest — sweep_v1_009_trail_tm6_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:41.042605+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_tm6 (idx=9)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 41 |
| Win Rate | 53.7% |
| P&L | $+4,704.52 |
| Final Equity | $6,704.52 |
| Profit Factor | 3.90 |
| Max Drawdown | 29.8% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 41 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.8% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.90 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $114.74 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 20tr $-331 | H2: 21tr $+5036 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 6 | $+633.29 | 6 |
| RSI RECOVERY | 5 | $+2,058.81 | 5 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+130.03 | 1 |
| TIME MAX | 20 | $+2,772.35 | 10 |
| TRAIL STOP | 9 | $-889.97 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 3.0,
  "breakeven": true,
  "exit_type": "trail",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 40,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 6,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
