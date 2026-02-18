# Sprint 2 — sprint2_008_h4s02_bb_width_pct_high70_decline_bars1_expansion_lookback15_no_new_low_bars3_rsi_max40_sl_pct5_time_limit15_tp_pct8_vol_decline_max1.0

- **Hypothesis**: Volatility Exhaustion Fade (H4S-02)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 256 |
| Win Rate | 37.5% |
| P&L | $-1,332.65 |
| PF | 0.75 |
| Max DD | 69.4% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.75 (below 1.05)
- [FAIL] G2:MAX_DD: DD 69.4% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 37.1% trades, 20.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 92tr PF=0.77 [FAIL] | W2: 85tr PF=0.87 [FAIL] | W3: 78tr PF=0.57 [FAIL]
- [OK] S1:TRADE_FREQ: 256 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.21 (negative or zero)
