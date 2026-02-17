# 4H DualConfirm Backtest — sweep_v1_022_hnotrl_vspk25_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:44.950049+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_vspk25 (idx=22)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 46 |
| Win Rate | 69.6% |
| P&L | $+3,048.41 |
| Final Equity | $5,048.41 |
| Profit Factor | 3.41 |
| Max Drawdown | 24.0% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 46 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 24.0% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.41 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $66.27 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 21tr $-240 | H2: 25tr $+3288 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-49.47 | 0 |
| DC TARGET | 14 | $+659.49 | 14 |
| RSI RECOVERY | 22 | $+3,472.88 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+49.44 | 1 |
| FIXED STOP | 6 | $-883.71 | 0 |
| TIME MAX | 2 | $-200.22 | 0 |

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
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 2.5
}
```
