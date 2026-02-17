# 4H DualConfirm Backtest — sweep_v2_002_slope_moderate_mexc_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T15:21:27.861136+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:slope_moderate_mexc_cohortA (idx=2)
- **Dataset**: candle_cache_4h_mexc_v1.json (144 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Slope Sizing**: steep=-10.0%, mild=-3.0%, min_scale=0.3
- **Avg Scale**: 0.513, Full-size: 4, Reduced: 19

## Results
| Metric | Value |
|--------|-------|
| Trades | 23 |
| Win Rate | 65.2% |
| P&L | $+158.77 |
| PF | 1.51 |
| DD | 13.5% |

## Gates: NO-GO (4/5)
- G1:MIN_TRADES: PASS — 23 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 13.5% (within limit)
- G3:PROFIT_FACTOR: PASS — PF 1.51 (edge confirmed)
- G4:EXPECTANCY: PASS — EV/trade $6.90 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 12tr $-114 | H2: 11tr $+273 (FAIL)

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