# Sprint 2 — sprint2_022_h4s04_momentum_lookback10_regime_typeC_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_floor_mult1.0

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 61 |
| Win Rate | 39.3% |
| P&L | $-254.95 |
| PF | 0.78 |
| Max DD | 23.6% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.78 (below 1.05)
- [PASS] G2:MAX_DD: DD 23.6% (PASS)
- [PASS] G3:TOP10_CONC: Top10: 24.6% trades, 18.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 17tr PF=0.79 [FAIL] | W2: 24tr PF=0.74 [FAIL] | W3: 19tr PF=0.71 [FAIL]
- [OK] S1:TRADE_FREQ: 61 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.18 (negative or zero)
