# 4H DualConfirm Backtest — sweep_v1_028_tpsl_rsi35_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:46.775791+00:00
- **Git**: 2659755
- **Config**: sweep_plan:tpsl_rsi35 (idx=28)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 38 |
| Win Rate | 52.6% |
| P&L | $+233.54 |
| Final Equity | $2,233.54 |
| Profit Factor | 1.12 |
| Max Drawdown | 32.6% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 3/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 38 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 32.6% (within limit) |
| G3:PROFIT_FACTOR | FAIL | PF 1.12 (below 1.3) |
| G4:EXPECTANCY | PASS | EV/trade $6.15 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 18tr $-110 | H2: 20tr $+344 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| PROFIT TARGET | 16 | $+1,923.07 | 16 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 7 | $-1,457.33 | 0 |
| TIME MAX | 15 | $-232.20 | 4 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 35,
  "rsi_recovery": false,
  "sl_pct": 10.0,
  "time_max_bars": 10,
  "tp_pct": 7.0,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
