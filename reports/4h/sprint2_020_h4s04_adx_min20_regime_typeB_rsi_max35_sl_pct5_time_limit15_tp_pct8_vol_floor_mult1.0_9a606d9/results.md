# Sprint 2 — sprint2_020_h4s04_adx_min20_regime_typeB_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_floor_mult1.0

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 258 |
| Win Rate | 39.5% |
| P&L | $-608.83 |
| PF | 0.85 |
| Max DD | 40.1% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.85 (below 1.05)
- [FAIL] G2:MAX_DD: DD 40.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.7% trades, 14.3% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 94tr PF=0.81 [FAIL] | W2: 72tr PF=1.10 [PASS] | W3: 90tr PF=0.71 [FAIL]
- [OK] S1:TRADE_FREQ: 258 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.36 (negative or zero)
