# 4H DualConfirm Backtest — sweep_v1b_005_msp20_late_nofilter_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:26:45.443312+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_late_nofilter (idx=5)
- **Dataset**: candle_cache_late_360.json (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Trades | 20 |
| Win Rate | 85.0% |
| P&L | $+3,513.68 |
| PF | 9.40 |
| DD | 12.0% |

## Gates: GO (5/5)
- G1:MIN_TRADES: PASS — 20 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 12.0% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 9.40 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $175.68 (positive)
- G5:ROBUSTNESS_SPLIT: PASS — H1: 8tr $+158 | H2: 12tr $+3356 (PASS)

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