# 4H DualConfirm Backtest — sweep_v1_012_trail_vspk25_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:41.921294+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_vspk25 (idx=12)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 40 |
| Win Rate | 55.0% |
| P&L | $+3,943.65 |
| Final Equity | $5,943.65 |
| Profit Factor | 3.36 |
| Max Drawdown | 34.7% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 40 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 34.7% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.36 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $98.59 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 19tr $-519 | H2: 21tr $+4463 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+743.72 | 10 |
| RSI RECOVERY | 8 | $+4,670.80 | 8 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+115.27 | 1 |
| TIME MAX | 8 | $-102.00 | 3 |
| TRAIL STOP | 13 | $-1,484.14 | 0 |

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
  "time_max_bars": 10,
  "vol_confirm": true,
  "vol_spike_mult": 2.5
}
```
