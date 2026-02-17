# 4H DualConfirm Backtest — sweep_v1_010_trail_tm15_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:41.335914+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_tm15 (idx=10)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 38 |
| Win Rate | 50.0% |
| P&L | $+3,323.66 |
| Final Equity | $5,323.66 |
| Profit Factor | 2.91 |
| Max Drawdown | 31.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 38 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 31.4% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 2.91 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $87.46 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-350 | H2: 20tr $+3674 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $+77.91 | 1 |
| DC TARGET | 9 | $+597.35 | 9 |
| RSI RECOVERY | 10 | $+4,265.57 | 8 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+103.25 | 1 |
| TRAIL STOP | 17 | $-1,720.43 | 0 |

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
  "time_max_bars": 15,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
