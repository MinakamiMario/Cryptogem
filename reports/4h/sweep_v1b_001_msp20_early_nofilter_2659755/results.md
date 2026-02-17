# 4H DualConfirm Backtest — sweep_v1b_001_msp20_early_nofilter_2659755

## Metadata
- **Timestamp**: 2026-02-17T10:26:26.361154+00:00
- **Git**: 2659755
- **Config**: sweep_plan:msp20_early_nofilter (idx=1)
- **Dataset**: candle_cache_early_360.json (487 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Trades | 15 |
| Win Rate | 60.0% |
| P&L | $+4.11 |
| PF | 1.01 |
| DD | 18.5% |

## Gates: NO-GO (3/5)
- G1:MIN_TRADES: PASS — 15 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 18.5% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 1.01 (below 1.3)
- G4:EXPECTANCY: PASS — EV/trade $0.27 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 9tr $-286 | H2: 6tr $+290 (FAIL)

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