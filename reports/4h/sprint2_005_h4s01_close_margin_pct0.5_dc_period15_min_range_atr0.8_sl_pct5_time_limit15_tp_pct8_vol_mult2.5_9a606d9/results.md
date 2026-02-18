# Sprint 2 — sprint2_005_h4s01_close_margin_pct0.5_dc_period15_min_range_atr0.8_sl_pct5_time_limit15_tp_pct8_vol_mult2.5

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 611 |
| Win Rate | 25.7% |
| P&L | $-1,995.97 |
| PF | 0.38 |
| Max DD | 99.8% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.38 (below 1.05)
- [FAIL] G2:MAX_DD: DD 99.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 8.0% trades, 1.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 229tr PF=0.37 [FAIL] | W2: 170tr PF=0.43 [FAIL] | W3: 211tr PF=0.53 [FAIL]
- [OK] S1:TRADE_FREQ: 611 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.27 (negative or zero)
