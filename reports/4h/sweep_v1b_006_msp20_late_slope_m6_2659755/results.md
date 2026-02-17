# 4H DualConfirm Backtest — sweep_v1b_006_msp20_late_slope_m6_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:26:45.597395+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_late_slope_m6 (idx=6)
- **Dataset**: candle_cache_late_360.json (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -6.0%

## Results
| Trades | 11 |
| Win Rate | 90.9% |
| P&L | $+3,010.12 |
| PF | 14.89 |
| DD | 11.1% |

## Gates: INSUFFICIENT_SAMPLE (4/5)
- G1:MIN_TRADES: FAIL — 11 trades (need >= 15)
- G2:MAX_DRAWDOWN: PASS — DD 11.1% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 14.89 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $273.65 (positive)
- G5:ROBUSTNESS_SPLIT: PASS — H1: 5tr $+67 | H2: 6tr $+2943 (PASS)

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