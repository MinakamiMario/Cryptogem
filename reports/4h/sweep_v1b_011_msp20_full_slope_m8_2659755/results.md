# 4H DualConfirm Backtest — sweep_v1b_011_msp20_full_slope_m8_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:27:42.827762+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_full_slope_m8 (idx=11)
- **Dataset**: candle_cache_532.json (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Regime Filter**: SMA50 slope <= -8.0%

## Results
| Trades | 16 |
| Win Rate | 68.8% |
| P&L | $+2,985.71 |
| PF | 6.95 |
| DD | 17.3% |

## Gates: NO-GO (4/5)
- G1:MIN_TRADES: PASS — 16 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 17.3% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 6.95 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $186.61 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 6tr $-92 | H2: 10tr $+3077 (FAIL)

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