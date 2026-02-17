# 4H DualConfirm Backtest — sweep_v1_020_hnotrl_mp1_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:44.348928+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_mp1 (idx=20)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 34 |
| Win Rate | 70.6% |
| P&L | $+5,177.28 |
| Final Equity | $7,177.28 |
| Profit Factor | 3.81 |
| Max Drawdown | 29.2% |
| Broke | No |

## Gates-Lite
- **Verdict**: GO
- **Passed**: 5/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 34 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.2% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.81 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $152.27 (positive) |
| G5:ROBUSTNESS_SPLIT | PASS | H1: 15tr $+16 | H2: 19tr $+5162 (PASS) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-106.90 | 0 |
| DC TARGET | 10 | $+728.19 | 10 |
| RSI RECOVERY | 18 | $+5,813.50 | 13 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+139.20 | 1 |
| FIXED STOP | 3 | $-1,082.47 | 0 |
| TIME MAX | 1 | $-314.23 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
