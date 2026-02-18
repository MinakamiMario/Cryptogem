# Sprint 2 — sprint2_009_h4s02_bb_width_pct_high80_decline_bars2_expansion_lookback20_no_new_low_bars5_rsi_max40_sl_pct5_time_limit10_tp_pct5_vol_decline_max0.8

- **Hypothesis**: Volatility Exhaustion Fade (H4S-02)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 358 |
| Win Rate | 42.2% |
| P&L | $-1,321.08 |
| PF | 0.61 |
| Max DD | 68.0% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.61 (below 1.05)
- [FAIL] G2:MAX_DD: DD 68.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 30.2% trades, 11.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 139tr PF=0.53 [FAIL] | W2: 95tr PF=0.69 [FAIL] | W3: 123tr PF=0.77 [FAIL]
- [OK] S1:TRADE_FREQ: 358 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.69 (negative or zero)
