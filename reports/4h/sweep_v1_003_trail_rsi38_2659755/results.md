# 4H DualConfirm Backtest — sweep_v1_003_trail_rsi38_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:39.255367+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_rsi38 (idx=3)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 37 |
| Win Rate | 54.1% |
| P&L | $+4,032.49 |
| Final Equity | $6,032.49 |
| Profit Factor | 3.54 |
| Max Drawdown | 35.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 37 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 35.4% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.54 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $108.99 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-364 | H2: 19tr $+4396 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 9 | $+767.71 | 9 |
| RSI RECOVERY | 7 | $+4,645.71 | 7 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+117.00 | 1 |
| TIME MAX | 8 | $-106.37 | 3 |
| TRAIL STOP | 12 | $-1,391.55 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 3.0,
  "breakeven": true,
  "exit_type": "trail",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 38,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 10,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
