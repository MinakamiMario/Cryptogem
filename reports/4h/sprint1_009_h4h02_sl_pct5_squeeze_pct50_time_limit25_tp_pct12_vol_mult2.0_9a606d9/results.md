# Sprint 1 — sprint1_009_h4h02_sl_pct5_squeeze_pct50_time_limit25_tp_pct12_vol_mult2.0

- **Hypothesis**: BB Squeeze Breakout (H4H-02)
- **Category**: volatility
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s

## Results
| Metric | Value |
|--------|-------|
| Trades | 361 |
| Win Rate | 23.6% |
| P&L | $-1,752.08 |
| PF | 0.59 |
| Max DD | 88.5% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.59 (below 1.3)
- [FAIL] G2:MAX_DD: DD 88.5% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.1% trades, 5.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 120tr PF=0.56 [FAIL] | W2: 102tr PF=0.71 [FAIL] | W3: 138tr PF=0.51 [FAIL]
- [OK] S1:TRADE_FREQ: 361 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.85 (negative or zero)
