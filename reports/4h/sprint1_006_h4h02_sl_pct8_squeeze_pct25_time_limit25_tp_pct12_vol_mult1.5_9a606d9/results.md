# Sprint 1 — sprint1_006_h4h02_sl_pct8_squeeze_pct25_time_limit25_tp_pct12_vol_mult1.5

- **Hypothesis**: BB Squeeze Breakout (H4H-02)
- **Category**: volatility
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 174 |
| Win Rate | 32.2% |
| P&L | $-1,875.81 |
| PF | 0.58 |
| Max DD | 94.4% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.58 (below 1.3)
- [FAIL] G2:MAX_DD: DD 94.4% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.4% trades, 5.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 59tr PF=0.44 [FAIL] | W2: 45tr PF=0.83 [FAIL] | W3: 69tr PF=0.66 [FAIL]
- [LOW] S1:TRADE_FREQ: 174 trades (below 180)
- [LOW] S2:EV_TRADE: EV/trade $-10.78 (negative or zero)
