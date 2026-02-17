# 4H DualConfirm Backtest — sweep_v1_021_hnotrl_tight_combo_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:44.656628+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_tight_combo (idx=21)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 36 |
| Win Rate | 66.7% |
| P&L | $+3,407.29 |
| Final Equity | $5,407.29 |
| Profit Factor | 2.71 |
| Max Drawdown | 38.0% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 36 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 38.0% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 2.71 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $94.65 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 17tr $-301 | H2: 19tr $+3708 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $+68.75 | 1 |
| DC TARGET | 10 | $+601.66 | 10 |
| RSI RECOVERY | 16 | $+4,466.49 | 12 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+104.87 | 1 |
| FIXED STOP | 8 | $-1,834.47 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 1,
  "max_stop_pct": 12.0,
  "rsi_max": 40,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
