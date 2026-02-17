# 4H DualConfirm Backtest — sweep_v2_006_slope_moderate_cohortb_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:24.018690+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:slope_moderate_cohortB (idx=6)
- **Dataset**: candle_cache_4h_kraken_v2.json (242 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Slope Sizing**: steep=-10.0%, mild=-3.0%, min_scale=0.3
- **Avg Scale**: 0.53, Full-size: 19, Reduced: 78

## Results
| Metric | Value |
|--------|-------|
| Trades | 97 |
| Win Rate | 58.8% |
| P&L | $+205.49 |
| PF | 1.20 |
| DD | 19.2% |

## Gates: NO-GO (3/5)
- G1:MIN_TRADES: PASS — 97 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 19.2% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 1.20 (below 1.3)
- G4:EXPECTANCY: PASS — EV/trade $2.12 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 49tr $-309 | H2: 48tr $+515 (FAIL)

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