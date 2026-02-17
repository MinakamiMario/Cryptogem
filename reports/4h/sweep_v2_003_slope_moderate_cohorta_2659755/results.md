# 4H DualConfirm Backtest — sweep_v2_003_slope_moderate_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:22.596881+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:slope_moderate_cohortA (idx=3)
- **Dataset**: candle_cache_4h_kraken_v2.json (170 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Slope Sizing**: steep=-10.0%, mild=-3.0%, min_scale=0.3
- **Avg Scale**: 0.516, Full-size: 13, Reduced: 63

## Results
| Metric | Value |
|--------|-------|
| Trades | 76 |
| Win Rate | 56.6% |
| P&L | $+61.62 |
| PF | 1.09 |
| DD | 10.5% |

## Gates: NO-GO (3/5)
- G1:MIN_TRADES: PASS — 76 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 10.5% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 1.09 (below 1.3)
- G4:EXPECTANCY: PASS — EV/trade $0.81 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 33tr $-183 | H2: 43tr $+245 (FAIL)

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