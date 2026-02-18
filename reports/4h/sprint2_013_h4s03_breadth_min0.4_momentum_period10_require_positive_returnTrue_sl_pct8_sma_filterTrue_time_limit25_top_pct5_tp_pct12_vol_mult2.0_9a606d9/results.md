# Sprint 2 — sprint2_013_h4s03_breadth_min0.4_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterTrue_time_limit25_top_pct5_tp_pct12_vol_mult2.0

- **Hypothesis**: Cross-Sectional Relative Strength (H4S-03)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 234 |
| Win Rate | 38.9% |
| P&L | $-1,553.49 |
| PF | 0.81 |
| Max DD | 80.7% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.81 (below 1.05)
- [FAIL] G2:MAX_DD: DD 80.7% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.1% trades, 7.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 92tr PF=0.74 [FAIL] | W2: 61tr PF=1.02 [FAIL] | W3: 80tr PF=0.82 [FAIL]
- [OK] S1:TRADE_FREQ: 234 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.64 (negative or zero)
