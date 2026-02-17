# 4H DualConfirm Backtest — sweep_v1_001_trail_baseline_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:38.661897+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_baseline (idx=1)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 39 |
| Win Rate | 56.4% |
| P&L | $+4,565.71 |
| Final Equity | $6,565.71 |
| Profit Factor | 3.79 |
| Max Drawdown | 29.7% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 39 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.7% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.79 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $117.07 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-364 | H2: 21tr $+4930 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+821.55 | 10 |
| RSI RECOVERY | 8 | $+5,159.64 | 8 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+127.34 | 1 |
| TIME MAX | 8 | $-112.68 | 3 |
| TRAIL STOP | 12 | $-1,430.15 | 0 |

## Config
```json
{
  "atr_mult": 2.0,
  "be_trigger": 3.0,
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
