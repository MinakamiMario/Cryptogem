# 4H DualConfirm Backtest — sweep_v1_004_trail_rsi42_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:39.552653+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_rsi42 (idx=4)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 40 |
| Win Rate | 57.5% |
| P&L | $+5,185.33 |
| Final Equity | $7,185.33 |
| Profit Factor | 4.13 |
| Max Drawdown | 29.3% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 40 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.3% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.13 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $129.63 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-364 | H2: 22tr $+5549 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+852.31 | 10 |
| RSI RECOVERY | 9 | $+5,757.64 | 9 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+139.36 | 1 |
| TIME MAX | 8 | $-110.63 | 3 |
| TRAIL STOP | 12 | $-1,453.35 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 3.0,
  "breakeven": true,
  "exit_type": "trail",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 10,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
