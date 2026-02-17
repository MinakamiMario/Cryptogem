# 4H DualConfirm Backtest — sweep_v1_013_hnotrl_baseline_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:42.226251+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_baseline (idx=13)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 43 |
| Win Rate | 72.1% |
| P&L | $+3,664.96 |
| Final Equity | $5,664.96 |
| Profit Factor | 4.19 |
| Max Drawdown | 20.2% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 43 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 20.2% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.19 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $85.23 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-25 | H2: 25tr $+3690 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-53.70 | 0 |
| DC TARGET | 13 | $+720.86 | 13 |
| RSI RECOVERY | 22 | $+3,895.82 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+55.47 | 1 |
| FIXED STOP | 5 | $-807.52 | 0 |
| TIME MAX | 1 | $-145.97 | 0 |

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
  "vol_spike_mult": 3.0
}
```
