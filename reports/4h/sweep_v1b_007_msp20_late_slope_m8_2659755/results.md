# 4H DualConfirm Backtest — sweep_v1b_007_msp20_late_slope_m8_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:26:45.724610+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_late_slope_m8 (idx=7)
- **Dataset**: candle_cache_late_360.json (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -8.0%

## Results
| Trades | 9 |
| Win Rate | 88.9% |
| P&L | $+2,920.42 |
| PF | 14.63 |
| DD | 11.0% |

## Gates: INSUFFICIENT_SAMPLE (4/5)
- G1:MIN_TRADES: FAIL — 9 trades (need >= 15)
- G2:MAX_DRAWDOWN: PASS — DD 11.0% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 14.63 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $324.49 (positive)
- G5:ROBUSTNESS_SPLIT: PASS — H1: 4tr $+44 | H2: 5tr $+2876 (PASS)

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