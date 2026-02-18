# Sprint 1 — sprint1_018_h4h05_adx_min20_lookback10_sl_pct8_time_limit25_tp_pct12

- **Hypothesis**: Momentum Trend (HH/HL + ADX) (H4H-05)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 266 |
| Win Rate | 36.1% |
| P&L | $-1,445.36 |
| PF | 0.73 |
| Max DD | 73.5% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.73 (below 1.3)
- [FAIL] G2:MAX_DD: DD 73.5% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.0% trades, 8.9% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 107tr PF=0.80 [FAIL] | W2: 70tr PF=0.65 [FAIL] | W3: 87tr PF=0.68 [FAIL]
- [OK] S1:TRADE_FREQ: 266 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.43 (negative or zero)
