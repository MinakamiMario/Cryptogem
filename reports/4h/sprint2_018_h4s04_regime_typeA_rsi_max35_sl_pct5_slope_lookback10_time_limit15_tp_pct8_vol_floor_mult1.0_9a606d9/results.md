# Sprint 2 — sprint2_018_h4s04_regime_typeA_rsi_max35_sl_pct5_slope_lookback10_time_limit15_tp_pct8_vol_floor_mult1.0

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 219 |
| Win Rate | 34.7% |
| P&L | $-1,232.32 |
| PF | 0.56 |
| Max DD | 62.0% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.56 (below 1.05)
- [FAIL] G2:MAX_DD: DD 62.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.0% trades, 14.3% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 88tr PF=0.38 [FAIL] | W2: 74tr PF=1.24 [PASS] | W3: 56tr PF=0.47 [FAIL]
- [OK] S1:TRADE_FREQ: 219 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.63 (negative or zero)
