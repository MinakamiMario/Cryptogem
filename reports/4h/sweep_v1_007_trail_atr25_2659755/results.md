# 4H DualConfirm Backtest — sweep_v1_007_trail_atr25_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:40.461447+00:00
- **Git**: 2659755
- **Config**: sweep_plan:trail_atr25 (idx=7)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 39 |
| Win Rate | 56.4% |
| P&L | $+4,098.76 |
| Final Equity | $6,098.76 |
| Profit Factor | 3.32 |
| Max Drawdown | 34.7% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 39 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 34.7% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.32 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $105.10 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-303 | H2: 21tr $+4402 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 10 | $+814.22 | 10 |
| RSI RECOVERY | 8 | $+4,839.21 | 8 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+118.28 | 1 |
| HARD STOP | 1 | $-297.34 | 0 |
| TIME MAX | 10 | $-353.52 | 3 |
| TRAIL STOP | 9 | $-1,022.09 | 0 |

## Config
```json
{
  "atr_mult": 2.5,
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
