# 4H DualConfirm Backtest — sweep_v2_001_baseline_msp20_cohorta_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:21.744401+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:baseline_msp20_cohortA (idx=1)
- **Dataset**: candle_cache_4h_kraken_v2.json (170 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Metric | Value |
|--------|-------|
| Trades | 76 |
| Win Rate | 56.6% |
| P&L | $-668.67 |
| PF | 0.64 |
| DD | 41.7% |

## Gates: NO-GO (1/5)
- G1:MIN_TRADES: PASS — 76 trades (sufficient)
- G2:MAX_DRAWDOWN: FAIL — DD 41.7% (exceeds 40.0%)
- G3:PROFIT_FACTOR: FAIL — PF 0.64 (below 1.3)
- G4:EXPECTANCY: FAIL — EV/trade $-8.80 (negative or zero)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 33tr $-782 | H2: 43tr $+114 (FAIL)

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