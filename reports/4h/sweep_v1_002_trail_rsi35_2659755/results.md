# 4H DualConfirm Backtest — sweep_v1_002_trail_rsi35_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:38.963407+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_rsi35 (idx=2)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 36 |
| Win Rate | 55.6% |
| P&L | $+4,605.41 |
| Final Equity | $6,605.41 |
| Profit Factor | 4.13 |
| Max Drawdown | 29.3% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 36 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.3% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.13 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $127.93 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-364 | H2: 18tr $+4969 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 9 | $+796.15 | 9 |
| RSI RECOVERY | 7 | $+5,058.50 | 7 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+128.11 | 1 |
| TIME MAX | 8 | $-111.44 | 3 |
| TRAIL STOP | 11 | $-1,265.91 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 3.0,
  "breakeven": true,
  "exit_type": "trail",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 35,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 10,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
