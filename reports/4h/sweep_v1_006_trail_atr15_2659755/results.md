# 4H DualConfirm Backtest — sweep_v1_006_trail_atr15_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:40.138580+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_atr15 (idx=6)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 43 |
| Win Rate | 53.5% |
| P&L | $+5,449.95 |
| Final Equity | $7,449.95 |
| Profit Factor | 4.07 |
| Max Drawdown | 26.8% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 43 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 26.8% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.07 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $126.74 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 21tr $-149 | H2: 22tr $+5599 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+887.46 | 10 |
| RSI RECOVERY | 10 | $+6,116.48 | 10 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+144.49 | 1 |
| TIME MAX | 7 | $-81.46 | 2 |
| TRAIL STOP | 15 | $-1,617.03 | 0 |

## Config
```json
{
  "atr_mult": 1.5,
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
  "vol_spike_mult": 3.0
}
```
