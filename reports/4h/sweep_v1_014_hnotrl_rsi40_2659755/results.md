# 4H DualConfirm Backtest — sweep_v1_014_hnotrl_rsi40_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:42.548754+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_rsi40 (idx=14)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 42 |
| Win Rate | 71.4% |
| P&L | $+3,409.70 |
| Final Equity | $5,409.70 |
| Profit Factor | 4.01 |
| Max Drawdown | 20.5% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 42 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 20.5% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.01 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $81.18 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-25 | H2: 24tr $+3435 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-53.70 | 0 |
| DC TARGET | 13 | $+703.25 | 13 |
| RSI RECOVERY | 21 | $+3,646.03 | 16 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+52.97 | 1 |
| FIXED STOP | 5 | $-792.87 | 0 |
| TIME MAX | 1 | $-145.97 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 2,
  "max_stop_pct": 15.0,
  "rsi_max": 40,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
