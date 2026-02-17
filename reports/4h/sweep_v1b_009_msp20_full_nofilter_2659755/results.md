# 4H DualConfirm Backtest — sweep_v1b_009_msp20_full_nofilter_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:27:42.191081+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_full_nofilter (idx=9)
- **Dataset**: candle_cache_532.json (526 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Trades | 43 |
| Win Rate | 72.1% |
| P&L | $+3,330.68 |
| PF | 3.61 |
| DD | 22.8% |

## Gates: GO (5/5)
- G1:MIN_TRADES: PASS — 43 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 22.8% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 3.61 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $77.46 (positive)
- G5:ROBUSTNESS_SPLIT: PASS — H1: 18tr $+17 | H2: 25tr $+3314 (PASS)

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