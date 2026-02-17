# 4H DualConfirm Backtest — sweep_v1_017_hnotrl_msp20_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:43.448356+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_msp20 (idx=17)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 43 |
| Win Rate | 72.1% |
| P&L | $+3,330.68 |
| Final Equity | $5,330.68 |
| Profit Factor | 3.61 |
| Max Drawdown | 22.8% |
| Broke | No |

## Gates-Lite
- **Verdict**: GO
- **Passed**: 5/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 43 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 22.8% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.61 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $77.46 (positive) |
| G5:ROBUSTNESS_SPLIT | PASS | H1: 18tr $+17 | H2: 25tr $+3314 (PASS) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-53.70 | 0 |
| DC TARGET | 14 | $+642.65 | 13 |
| RSI RECOVERY | 22 | $+3,697.91 | 17 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+52.20 | 1 |
| FIXED STOP | 4 | $-863.32 | 0 |
| TIME MAX | 1 | $-145.06 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 2,
  "max_stop_pct": 20.0,
  "rsi_max": 42,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
