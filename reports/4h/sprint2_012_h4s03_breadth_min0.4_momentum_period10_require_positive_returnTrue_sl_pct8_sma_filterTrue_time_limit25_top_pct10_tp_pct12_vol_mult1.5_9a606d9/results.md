# Sprint 2 — sprint2_012_h4s03_breadth_min0.4_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterTrue_time_limit25_top_pct10_tp_pct12_vol_mult1.5

- **Hypothesis**: Cross-Sectional Relative Strength (H4S-03)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 242 |
| Win Rate | 37.6% |
| P&L | $-1,448.48 |
| PF | 0.78 |
| Max DD | 78.8% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.78 (below 1.05)
- [FAIL] G2:MAX_DD: DD 78.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 15.3% trades, 10.0% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 96tr PF=0.66 [FAIL] | W2: 66tr PF=1.02 [FAIL] | W3: 79tr PF=0.90 [FAIL]
- [OK] S1:TRADE_FREQ: 242 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.99 (negative or zero)
