# Sprint 2 — sprint2_017_h4s03_breadth_min0.3_momentum_period10_require_positive_returnTrue_sl_pct8_sma_filterFalse_time_limit25_top_pct10_tp_pct12_vol_mult1.5

- **Hypothesis**: Cross-Sectional Relative Strength (H4S-03)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 249 |
| Win Rate | 38.5% |
| P&L | $-1,098.38 |
| PF | 0.80 |
| Max DD | 58.9% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.80 (below 1.05)
- [FAIL] G2:MAX_DD: DD 58.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.9% trades, 8.9% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 105tr PF=0.68 [FAIL] | W2: 67tr PF=1.25 [PASS] | W3: 76tr PF=0.77 [FAIL]
- [OK] S1:TRADE_FREQ: 249 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.41 (negative or zero)
