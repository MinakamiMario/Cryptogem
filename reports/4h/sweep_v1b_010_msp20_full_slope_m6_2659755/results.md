# 4H DualConfirm Backtest — sweep_v1b_010_msp20_full_slope_m6_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:27:42.529230+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_full_slope_m6 (idx=10)
- **Dataset**: candle_cache_532.json (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -6.0%

## Results
| Trades | 21 |
| Win Rate | 71.4% |
| P&L | $+3,315.22 |
| PF | 6.82 |
| DD | 16.7% |

## Gates: NO-GO (4/5)
- G1:MIN_TRADES: PASS — 21 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 16.7% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 6.82 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $157.87 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 9tr $-2 | H2: 12tr $+3317 (FAIL)

## Config
```json
{
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