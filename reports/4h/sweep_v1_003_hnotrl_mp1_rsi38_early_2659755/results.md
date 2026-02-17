# 4H DualConfirm Backtest — sweep_v1_003_hnotrl_mp1_rsi38_early_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:00:01.916976+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_mp1_rsi38_early (idx=3)
- **Dataset**: candle_cache_532 (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 12 |
| Win Rate | 58.3% |
| P&L | $-10.10 |
| Final Equity | $1,989.90 |
| Profit Factor | 0.99 |
| Max Drawdown | 29.1% |
| Broke | No |

## Gates-Lite
- **Verdict**: INSUFFICIENT_SAMPLE
- **Passed**: 1/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | FAIL | 12 trades (need >= 15) |
| G2:MAX_DRAWDOWN | PASS | DD 29.1% (within limit) |
| G3:PROFIT_FACTOR | FAIL | PF 0.99 (below 1.3) |
| G4:EXPECTANCY | FAIL | EV/trade $-0.84 (negative or zero) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 7tr $-415 | H2: 5tr $+405 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-106.59 | 0 |
| DC TARGET | 5 | $+523.07 | 5 |
| RSI RECOVERY | 5 | $-102.60 | 2 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 1 | $-323.98 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 38,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
