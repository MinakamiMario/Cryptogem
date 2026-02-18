# Sprint 2 — sprint2_024_h4s04_momentum_lookback5_regime_typeC_rsi_max30_sl_pct5_time_limit10_tp_pct5_vol_floor_mult1.0

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 158 |
| Win Rate | 38.6% |
| P&L | $-1,081.38 |
| PF | 0.50 |
| Max DD | 54.1% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.50 (below 1.05)
- [FAIL] G2:MAX_DD: DD 54.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.9% trades, 13.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 58tr PF=0.44 [FAIL] | W2: 43tr PF=0.74 [FAIL] | W3: 56tr PF=0.41 [FAIL]
- [OK] S1:TRADE_FREQ: 158 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.84 (negative or zero)
