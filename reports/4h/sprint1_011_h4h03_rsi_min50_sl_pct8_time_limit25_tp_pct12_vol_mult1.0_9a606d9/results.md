# Sprint 1 — sprint1_011_h4h03_rsi_min50_sl_pct8_time_limit25_tp_pct12_vol_mult1.0

- **Hypothesis**: EMA Cross + RSI (H4H-03)
- **Category**: trend_following
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 234 |
| Win Rate | 30.3% |
| P&L | $-1,699.65 |
| PF | 0.61 |
| Max DD | 87.0% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.61 (below 1.3)
- [FAIL] G2:MAX_DD: DD 87.0% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.2% trades, 9.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 93tr PF=0.76 [FAIL] | W2: 62tr PF=0.41 [FAIL] | W3: 77tr PF=0.37 [FAIL]
- [OK] S1:TRADE_FREQ: 234 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.26 (negative or zero)
