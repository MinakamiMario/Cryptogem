# 4H DualConfirm Backtest — sweep_v1_005_hnotrl_msp20_late_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:00:15.893893+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_msp20_late (idx=5)
- **Dataset**: candle_cache_532 (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 20 |
| Win Rate | 85.0% |
| P&L | $+3,513.68 |
| Final Equity | $5,513.68 |
| Profit Factor | 9.40 |
| Max Drawdown | 12.0% |
| Broke | No |

## Gates-Lite
- **Verdict**: GO
- **Passed**: 5/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 20 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 12.0% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 9.40 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $175.68 (positive) |
| G5:ROBUSTNESS_SPLIT | PASS | H1: 8tr $+158 | H2: 12tr $+3356 (PASS) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 4 | $+212.19 | 3 |
| RSI RECOVERY | 13 | $+3,643.69 | 13 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+53.99 | 1 |
| FIXED STOP | 1 | $-239.66 | 0 |
| TIME MAX | 1 | $-156.53 | 0 |

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
