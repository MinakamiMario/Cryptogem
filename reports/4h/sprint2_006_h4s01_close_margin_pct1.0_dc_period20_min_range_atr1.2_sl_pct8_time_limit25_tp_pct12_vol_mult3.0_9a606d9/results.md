# Sprint 2 — sprint2_006_h4s01_close_margin_pct1.0_dc_period20_min_range_atr1.2_sl_pct8_time_limit25_tp_pct12_vol_mult3.0

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 368 |
| Win Rate | 26.4% |
| P&L | $-1,965.05 |
| PF | 0.43 |
| Max DD | 98.2% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.43 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.8% trades, 15.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 146tr PF=0.42 [FAIL] | W2: 98tr PF=0.41 [FAIL] | W3: 123tr PF=0.61 [FAIL]
- [OK] S1:TRADE_FREQ: 368 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.34 (negative or zero)
