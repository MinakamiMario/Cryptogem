# 4H DualConfirm Backtest — sweep_v1b_002_msp20_early_slope_m6_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:26:26.513964+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_early_slope_m6 (idx=2)
- **Dataset**: candle_cache_early_360.json (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -6.0%

## Results
| Trades | 7 |
| Win Rate | 57.1% |
| P&L | $-44.63 |
| PF | 0.87 |
| DD | 16.7% |

## Gates: INSUFFICIENT_SAMPLE (1/5)
- G1:MIN_TRADES: FAIL — 7 trades (need >= 15)
- G2:MAX_DRAWDOWN: PASS — DD 16.7% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 0.87 (below 1.3)
- G4:EXPECTANCY: FAIL — EV/trade $-6.38 (negative or zero)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 4tr $-271 | H2: 3tr $+226 (FAIL)

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