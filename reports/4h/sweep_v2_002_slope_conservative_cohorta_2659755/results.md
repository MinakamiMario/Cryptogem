# 4H DualConfirm Backtest — sweep_v2_002_slope_conservative_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:22.178990+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:slope_conservative_cohortA (idx=2)
- **Dataset**: candle_cache_4h_kraken_v2.json (170 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Slope Sizing**: steep=-10.0%, mild=-3.0%, min_scale=0.5
- **Avg Scale**: 0.654, Full-size: 13, Reduced: 63

## Results
| Metric | Value |
|--------|-------|
| Trades | 76 |
| Win Rate | 56.6% |
| P&L | $-147.04 |
| PF | 0.86 |
| DD | 17.7% |

## Gates: NO-GO (2/5)
- G1:MIN_TRADES: PASS — 76 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 17.7% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 0.86 (below 1.3)
- G4:EXPECTANCY: FAIL — EV/trade $-1.93 (negative or zero)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 33tr $-355 | H2: 43tr $+208 (FAIL)

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