# Sprint 2 — sprint2_019_h4s04_regime_typeA_rsi_max40_sl_pct5_slope_lookback5_time_limit15_tp_pct8_vol_floor_mult0.8

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 250 |
| Win Rate | 35.2% |
| P&L | $-1,266.22 |
| PF | 0.61 |
| Max DD | 63.3% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.61 (below 1.05)
- [FAIL] G2:MAX_DD: DD 63.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.4% trades, 12.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 103tr PF=0.53 [FAIL] | W2: 82tr PF=0.89 [FAIL] | W3: 64tr PF=0.52 [FAIL]
- [OK] S1:TRADE_FREQ: 250 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.06 (negative or zero)
