# Sprint 2 — sprint2_002_h4s01_close_margin_pct0.5_dc_period20_min_range_atr0.8_sl_pct5_time_limit20_tp_pct10_vol_mult2.5

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 530 |
| Win Rate | 23.6% |
| P&L | $-1,978.48 |
| PF | 0.46 |
| Max DD | 98.9% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.46 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 8.7% trades, 8.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 199tr PF=0.44 [FAIL] | W2: 146tr PF=0.51 [FAIL] | W3: 184tr PF=0.57 [FAIL]
- [OK] S1:TRADE_FREQ: 530 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.73 (negative or zero)
