# Sprint 2 — sprint2_010_h4s02_bb_width_pct_high70_decline_bars1_expansion_lookback30_no_new_low_bars3_rsi_max45_sl_pct8_time_limit15_tp_pct8_vol_decline_max1.0

- **Hypothesis**: Volatility Exhaustion Fade (H4S-02)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 209 |
| Win Rate | 46.4% |
| P&L | $-1,195.21 |
| PF | 0.81 |
| Max DD | 63.0% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.81 (below 1.05)
- [FAIL] G2:MAX_DD: DD 63.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 48.8% trades, 15.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 82tr PF=0.85 [FAIL] | W2: 57tr PF=0.91 [FAIL] | W3: 69tr PF=0.69 [FAIL]
- [OK] S1:TRADE_FREQ: 209 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.72 (negative or zero)
