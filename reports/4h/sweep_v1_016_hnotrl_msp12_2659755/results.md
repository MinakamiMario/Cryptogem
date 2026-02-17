# 4H DualConfirm Backtest — sweep_v1_016_hnotrl_msp12_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:43.139008+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_msp12 (idx=16)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 45 |
| Win Rate | 71.1% |
| P&L | $+3,673.87 |
| Final Equity | $5,673.87 |
| Profit Factor | 4.03 |
| Max Drawdown | 20.8% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 45 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 20.8% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.03 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $81.64 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 19tr $-30 | H2: 26tr $+3704 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $+44.12 | 1 |
| DC TARGET | 13 | $+716.24 | 13 |
| RSI RECOVERY | 21 | $+4,003.44 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+55.56 | 1 |
| FIXED STOP | 9 | $-1,145.49 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 2,
  "max_stop_pct": 12.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
