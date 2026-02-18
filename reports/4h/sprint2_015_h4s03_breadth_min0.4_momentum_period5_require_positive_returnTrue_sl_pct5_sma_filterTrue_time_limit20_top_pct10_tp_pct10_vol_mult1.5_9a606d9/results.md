# Sprint 2 — sprint2_015_h4s03_breadth_min0.4_momentum_period5_require_positive_returnTrue_sl_pct5_sma_filterTrue_time_limit20_top_pct10_tp_pct10_vol_mult1.5

- **Hypothesis**: Cross-Sectional Relative Strength (H4S-03)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 356 |
| Win Rate | 31.5% |
| P&L | $-1,564.79 |
| PF | 0.76 |
| Max DD | 80.6% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.76 (below 1.05)
- [FAIL] G2:MAX_DD: DD 80.6% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.8% trades, 8.8% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 151tr PF=0.68 [FAIL] | W2: 90tr PF=1.12 [PASS] | W3: 114tr PF=0.63 [FAIL]
- [OK] S1:TRADE_FREQ: 356 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.40 (negative or zero)
