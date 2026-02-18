# Sprint 1 — sprint1_013_h4h03_rsi_min50_sl_pct8_time_limit30_tp_pct15_vol_mult1.5

- **Hypothesis**: EMA Cross + RSI (H4H-03)
- **Category**: trend_following
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 323 |
| Win Rate | 28.5% |
| P&L | $-1,546.91 |
| PF | 0.65 |
| Max DD | 79.5% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.3)
- [FAIL] G2:MAX_DD: DD 79.5% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.9% trades, 4.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 125tr PF=0.80 [FAIL] | W2: 91tr PF=0.45 [FAIL] | W3: 106tr PF=0.51 [FAIL]
- [OK] S1:TRADE_FREQ: 323 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.79 (negative or zero)
