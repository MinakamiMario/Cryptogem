# Sprint 2 — sprint2_003_h4s01_close_margin_pct0_dc_period20_min_range_atr0.5_sl_pct5_time_limit20_tp_pct10_vol_mult2.0

- **Hypothesis**: Breakout Anti-Fakeout (H4S-01)
- **Category**: breakout
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 512 |
| Win Rate | 21.9% |
| P&L | $-1,984.66 |
| PF | 0.38 |
| Max DD | 99.2% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.38 (below 1.05)
- [FAIL] G2:MAX_DD: DD 99.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 8.6% trades, 10.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 194tr PF=0.35 [FAIL] | W2: 145tr PF=0.51 [FAIL] | W3: 172tr PF=0.51 [FAIL]
- [OK] S1:TRADE_FREQ: 512 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.88 (negative or zero)
