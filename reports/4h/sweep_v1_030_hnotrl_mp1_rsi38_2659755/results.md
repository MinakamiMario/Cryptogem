# 4H DualConfirm Backtest — sweep_v1_030_hnotrl_mp1_rsi38_2659755

## Metadata
- **Timestamp**: 2026-02-17T09:45:47.399013+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_mp1_rsi38 (idx=30)
- **Dataset**: candle_cache_532 (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.3s

## Results
| Metric | Value |
|--------|-------|
| Trades | 31 |
| Win Rate | 67.7% |
| P&L | $+4,025.74 |
| Final Equity | $6,025.74 |
| Profit Factor | 3.35 |
| Max Drawdown | 35.3% |
| Broke | No |

## Gates-Lite
- **Verdict**: GO
- **Passed**: 5/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 31 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 35.3% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 3.35 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $129.86 (positive) |
| G5:ROBUSTNESS_SPLIT | PASS | H1: 15tr $+16 | H2: 16tr $+4010 (PASS) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 1 | $-106.90 | 0 |
| DC TARGET | 9 | $+672.83 | 9 |
| RSI RECOVERY | 16 | $+4,624.63 | 11 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+116.87 | 1 |
| FIXED STOP | 3 | $-992.98 | 0 |
| TIME MAX | 1 | $-288.71 | 0 |

## Config
```json
{
  "breakeven": false,
  "exit_type": "hybrid_notrl",
  "max_pos": 1,
  "max_stop_pct": 15.0,
  "rsi_max": 38,
  "rsi_rec_target": 45,
  "rsi_recovery": true,
  "time_max_bars": 20,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```
