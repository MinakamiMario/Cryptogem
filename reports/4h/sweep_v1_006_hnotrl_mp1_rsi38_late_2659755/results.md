# 4H DualConfirm Backtest — sweep_v1_006_hnotrl_mp1_rsi38_late_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:00:16.045695+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_mp1_rsi38_late (idx=6)
- **Dataset**: candle_cache_532 (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 15 |
| Win Rate | 80.0% |
| P&L | $+5,042.25 |
| Final Equity | $7,042.25 |
| Profit Factor | 6.35 |
| Max Drawdown | 35.4% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 15 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 35.4% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 6.35 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $336.15 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 6tr $-189 | H2: 9tr $+5231 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 2 | $+302.49 | 2 |
| RSI RECOVERY | 9 | $+5,546.16 | 9 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+136.58 | 1 |
| FIXED STOP | 2 | $-659.64 | 0 |
| TIME MAX | 1 | $-283.33 | 0 |

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
