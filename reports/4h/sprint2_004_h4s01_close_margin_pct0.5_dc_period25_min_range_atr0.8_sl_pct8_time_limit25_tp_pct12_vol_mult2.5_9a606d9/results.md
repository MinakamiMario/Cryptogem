# Sprint 2 — sprint2_004_h4s01_close_margin_pct0.5_dc_period25_min_range_atr0.8_sl_pct8_time_limit25_tp_pct12_vol_mult2.5

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 361 |
| Win Rate | 28.0% |
| P&L | $-1,977.03 |
| PF | 0.47 |
| Max DD | 98.8% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.47 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 10.2% trades, 15.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 140tr PF=0.46 [FAIL] | W2: 106tr PF=0.45 [FAIL] | W3: 114tr PF=0.65 [FAIL]
- [OK] S1:TRADE_FREQ: 361 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.48 (negative or zero)
