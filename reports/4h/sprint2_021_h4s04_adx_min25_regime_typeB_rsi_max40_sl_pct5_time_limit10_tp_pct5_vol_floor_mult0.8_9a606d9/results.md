# Sprint 2 — sprint2_021_h4s04_adx_min25_regime_typeB_rsi_max40_sl_pct5_time_limit10_tp_pct5_vol_floor_mult0.8

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 416 |
| Win Rate | 45.0% |
| P&L | $-1,298.62 |
| PF | 0.68 |
| Max DD | 71.9% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.68 (below 1.05)
- [FAIL] G2:MAX_DD: DD 71.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.9% trades, 3.4% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 154tr PF=0.59 [FAIL] | W2: 124tr PF=0.85 [FAIL] | W3: 137tr PF=0.71 [FAIL]
- [OK] S1:TRADE_FREQ: 416 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.12 (negative or zero)
