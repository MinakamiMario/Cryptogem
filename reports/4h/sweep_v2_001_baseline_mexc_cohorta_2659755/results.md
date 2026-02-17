# 4H DualConfirm Backtest — sweep_v2_001_baseline_mexc_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T15:21:27.625809+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:baseline_mexc_cohortA (idx=1)
- **Dataset**: candle_cache_4h_mexc_v1.json (144 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Metric | Value |
|--------|-------|
| Trades | 23 |
| Win Rate | 65.2% |
| P&L | $-58.09 |
| PF | 0.92 |
| DD | 33.0% |

## Gates: NO-GO (2/5)
- G1:MIN_TRADES: PASS — 23 trades (sufficient)
- G2:MAX_DRAWDOWN: PASS — DD 33.0% (within limit)
- G3:PROFIT_FACTOR: FAIL — PF 0.92 (below 1.3)
- G4:EXPECTANCY: FAIL — EV/trade $-2.53 (negative or zero)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 12tr $-386 | H2: 11tr $+328 (FAIL)

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