# Sprint 1 — sprint1_010_h4h03_rsi_min40_sl_pct8_time_limit25_tp_pct12_vol_mult1.0

- **Hypothesis**: EMA Cross + RSI (H4H-03)
- **Category**: trend_following
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 231 |
| Win Rate | 29.4% |
| P&L | $-1,721.41 |
| PF | 0.58 |
| Max DD | 88.0% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.58 (below 1.3)
- [FAIL] G2:MAX_DD: DD 88.0% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.4% trades, 16.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 90tr PF=0.71 [FAIL] | W2: 62tr PF=0.41 [FAIL] | W3: 77tr PF=0.36 [FAIL]
- [OK] S1:TRADE_FREQ: 231 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.45 (negative or zero)
