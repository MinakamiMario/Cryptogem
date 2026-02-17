# 4H DualConfirm Backtest — sweep_v1b_012_msp20_full_slope_m10_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:27:43.083745+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_full_slope_m10 (idx=12)
- **Dataset**: candle_cache_532.json (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -10.0%

## Results
| Trades | 13 |
| Win Rate | 69.2% |
| P&L | $+2,490.73 |
| PF | 8.71 |
| DD | 16.7% |

## Gates: INSUFFICIENT_SAMPLE (3/5)
- G1:MIN_TRADES: FAIL — 13 trades (need >= 15)
- G2:MAX_DRAWDOWN: PASS — DD 16.7% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 8.71 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $191.59 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 5tr $-173 | H2: 8tr $+2664 (FAIL)

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