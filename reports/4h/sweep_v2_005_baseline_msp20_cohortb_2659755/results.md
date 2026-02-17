# 4H DualConfirm Backtest — sweep_v2_005_baseline_msp20_cohortb_2659755

## Metadata
- **Timestamp**: 2026-02-17T12:04:23.532967+00:00
- **Git**: 2659755
- **Config**: sweep_plan_v2:baseline_msp20_cohortB (idx=5)
- **Dataset**: candle_cache_4h_kraken_v2.json (242 coins)
- **Exchange**: kraken (fee: 26.0 bps/side)

## Results
| Metric | Value |
|--------|-------|
| Trades | 97 |
| Win Rate | 58.8% |
| P&L | $-480.75 |
| PF | 0.80 |
| DD | 51.8% |

## Gates: NO-GO (1/5)
- G1:MIN_TRADES: PASS — 97 trades (sufficient)
- G2:MAX_DRAWDOWN: FAIL — DD 51.8% (exceeds 40.0%)
- G3:PROFIT_FACTOR: FAIL — PF 0.80 (below 1.3)
- G4:EXPECTANCY: FAIL — EV/trade $-4.96 (negative or zero)
- G5:ROBUSTNESS_SPLIT: FAIL — H1: 49tr $-997 | H2: 48tr $+516 (FAIL)

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