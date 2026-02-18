# Sprint 1 — sprint1_008_h4h02_sl_pct5_squeeze_pct25_time_limit20_tp_pct8_vol_mult2.0

- **Hypothesis**: BB Squeeze Breakout (H4H-02)
- **Category**: volatility
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 264 |
| Win Rate | 31.8% |
| P&L | $-1,865.73 |
| PF | 0.56 |
| Max DD | 93.9% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.56 (below 1.3)
- [FAIL] G2:MAX_DD: DD 93.9% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.4% trades, 5.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 90tr PF=0.46 [FAIL] | W2: 76tr PF=0.64 [FAIL] | W3: 96tr PF=0.71 [FAIL]
- [OK] S1:TRADE_FREQ: 264 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.07 (negative or zero)
