# Sprint 2 — sprint2_023_h4s04_momentum_lookback20_regime_typeC_rsi_max40_sl_pct8_time_limit15_tp_pct8_vol_floor_mult0.8

- **Hypothesis**: RSI + Regime Filter (H4S-04)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 159 |
| Win Rate | 41.5% |
| P&L | $-1,138.95 |
| PF | 0.60 |
| Max DD | 57.9% |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.60 (below 1.05)
- [FAIL] G2:MAX_DD: DD 57.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.0% trades, 19.0% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 55tr PF=0.48 [FAIL] | W2: 55tr PF=0.81 [FAIL] | W3: 48tr PF=0.62 [FAIL]
- [OK] S1:TRADE_FREQ: 159 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.16 (negative or zero)
