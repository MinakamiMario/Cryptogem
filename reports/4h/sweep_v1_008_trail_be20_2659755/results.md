# 4H DualConfirm Backtest — sweep_v1_008_trail_be20_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:40.754457+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_be20 (idx=8)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 39 |
| Win Rate | 56.4% |
| P&L | $+5,088.65 |
| Final Equity | $7,088.65 |
| Profit Factor | 4.20 |
| Max Drawdown | 24.7% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 39 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 24.7% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 4.20 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $130.48 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-234 | H2: 21tr $+5322 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+871.78 | 10 |
| RSI RECOVERY | 8 | $+5,570.59 | 8 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+137.48 | 1 |
| TIME MAX | 8 | $-121.65 | 3 |
| TRAIL STOP | 12 | $-1,369.55 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 2.0,
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
