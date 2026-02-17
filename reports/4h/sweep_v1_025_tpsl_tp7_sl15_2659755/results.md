# 4H DualConfirm Backtest — sweep_v1_025_tpsl_tp7_sl15_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:45.873532+00:00
- **Git**: 2659755
- **Config**: sweep_plan:tpsl_tp7_sl15 (idx=25)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 38 |
| Win Rate | 57.9% |
| P&L | $+636.90 |
| Final Equity | $2,636.90 |
| Profit Factor | 1.36 |
| Max Drawdown | 35.9% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 38 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 35.9% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 1.36 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $16.76 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-189 | H2: 20tr $+826 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| PROFIT TARGET | 18 | $+2,202.61 | 18 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 3 | $-926.56 | 0 |
| TIME MAX | 17 | $-639.16 | 4 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 40,
  "rsi_recovery": false,
  "sl_pct": 15.0,
  "time_max_bars": 10,
  "tp_pct": 7.0,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
