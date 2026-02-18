# Sprint 2 — sprint2_007_h4s02_bb_width_pct_high75_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_decline_max1.0

- **Hypothesis**: Volatility Exhaustion Fade (H4S-02)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 275 |
| Win Rate | 37.1% |
| P&L | $-1,194.09 |
| PF | 0.66 |
| Max DD | 60.5% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.66 (below 1.05)
- [FAIL] G2:MAX_DD: DD 60.5% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 24.7% trades, 16.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 108tr PF=0.57 [FAIL] | W2: 74tr PF=0.88 [FAIL] | W3: 92tr PF=0.65 [FAIL]
- [OK] S1:TRADE_FREQ: 275 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.34 (negative or zero)
