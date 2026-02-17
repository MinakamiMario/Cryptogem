# 4H DualConfirm Backtest — sweep_v1_004_hnotrl_mp1_late_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:00:15.719224+00:00
- **Git**: 2659755
- **Config**: sweep_plan:hnotrl_mp1_late (idx=4)
- **Dataset**: candle_cache_532 (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Initial Capital**: $2000
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 17 |
| Win Rate | 82.4% |
| P&L | $+6,256.70 |
| Final Equity | $8,256.70 |
| Profit Factor | 7.02 |
| Max Drawdown | 29.3% |
| Broke | No |

## Gates-Lite
- **Verdict**: NO-GO
- **Passed**: 4/5

| Gate | Result | Detail |
|------|--------|--------|
| G1:MIN_TRADES | PASS | 17 trades (sufficient) |
| G2:MAX_DRAWDOWN | PASS | DD 29.3% (within limit) |
| G3:PROFIT_FACTOR | PASS | PF 7.02 (edge confirmed) |
| G4:EXPECTANCY | PASS | EV/trade $368.04 (positive) |
| G5:ROBUSTNESS_SPLIT | FAIL | H1: 7tr $-60 | H2: 10tr $+6316 (FAIL) |

## Exit Classes

### Class A
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| DC TARGET | 2 | $+354.66 | 2 |
| RSI RECOVERY | 11 | $+6,781.58 | 11 |

### Class B
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+160.13 | 1 |
| FIXED STOP | 2 | $-736.12 | 0 |
| TIME MAX | 1 | $-303.55 | 0 |

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
