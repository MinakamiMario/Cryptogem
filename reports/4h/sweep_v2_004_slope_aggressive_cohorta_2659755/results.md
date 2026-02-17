# 4H DualConfirm Backtest — sweep_v2_004_slope_aggressive_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:23.008113+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:slope_aggressive_cohortA (idx=4)
- **Dataset**: candle_cache_4h_kraken_v2.json (170 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)
- **Slope Sizing**: steep=-8.0%, mild=-2.0%, min_scale=0.2
- **Avg Scale**: 0.511, Full-size: 18, Reduced: 58

## Results
| Metric | Value |
|--------|-------|
| Trades | 76 |
| Win Rate | 56.6% |
| P&L | $+60.52 |
| PF | 1.09 |
| DD | 9.1% |

## Gates: NO-GO (3/5)
- G1:MIN_TRADES: PASS — 76 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 9.1% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 1.09 (below 1.3)
- G4:EXPECTANCY: PASS — EV/trade $0.80 (positive)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 33tr $-145 | H2: 43tr $+205 (FAIL)

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