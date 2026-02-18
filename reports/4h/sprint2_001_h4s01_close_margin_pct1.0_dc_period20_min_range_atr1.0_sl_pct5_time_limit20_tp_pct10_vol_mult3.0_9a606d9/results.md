# Sprint 2 — sprint2_001_h4s01_close_margin_pct1.0_dc_period20_min_range_atr1.0_sl_pct5_time_limit20_tp_pct10_vol_mult3.0

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 553 |
| Win Rate | 22.8% |
| P&L | $-1,963.91 |
| PF | 0.44 |
| Max DD | 98.2% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.44 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 8.1% trades, 8.7% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 205tr PF=0.43 [FAIL] | W2: 148tr PF=0.48 [FAIL] | W3: 199tr PF=0.53 [FAIL]
- [OK] S1:TRADE_FREQ: 553 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.55 (negative or zero)
