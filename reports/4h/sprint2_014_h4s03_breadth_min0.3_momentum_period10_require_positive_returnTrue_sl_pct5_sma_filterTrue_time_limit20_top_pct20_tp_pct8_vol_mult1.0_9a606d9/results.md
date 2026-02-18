# Sprint 2 — sprint2_014_h4s03_breadth_min0.3_momentum_period10_require_positive_returnTrue_sl_pct5_sma_filterTrue_time_limit20_top_pct20_tp_pct8_vol_mult1.0

- **Hypothesis**: Cross-Sectional Relative Strength (H4S-03)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 381 |
| Win Rate | 34.9% |
| P&L | $-1,599.18 |
| PF | 0.73 |
| Max DD | 81.0% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.73 (below 1.05)
- [FAIL] G2:MAX_DD: DD 81.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.4% trades, 8.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 155tr PF=0.69 [FAIL] | W2: 102tr PF=0.93 [FAIL] | W3: 122tr PF=0.63 [FAIL]
- [OK] S1:TRADE_FREQ: 381 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.20 (negative or zero)
