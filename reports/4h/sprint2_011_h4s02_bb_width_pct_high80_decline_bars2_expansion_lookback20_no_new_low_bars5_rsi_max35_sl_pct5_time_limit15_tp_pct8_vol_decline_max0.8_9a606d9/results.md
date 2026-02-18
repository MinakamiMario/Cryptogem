# Sprint 2 — sprint2_011_h4s02_bb_width_pct_high80_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max35_sl_pct5_time_limit15_tp_pct8_vol_decline_max0.8

- **Hypothesis**: Volatility Exhaustion Fade (H4S-02)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 264 |
| Win Rate | 37.1% |
| P&L | $-1,073.01 |
| PF | 0.69 |
| Max DD | 56.1% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.69 (below 1.05)
- [FAIL] G2:MAX_DD: DD 56.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 24.2% trades, 17.0% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 108tr PF=0.59 [FAIL] | W2: 66tr PF=0.92 [FAIL] | W3: 89tr PF=0.74 [FAIL]
- [OK] S1:TRADE_FREQ: 264 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.06 (negative or zero)
