# Sprint 1 — sprint1_002_h4h01_rsi_entry30_sl_pct5_time_limit15_tp_pct8

- **Hypothesis**: RSI Mean Reversion (H4H-01)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.0s

## Results
| Metric | Value |
|--------|-------|
| Trades | 287 |
| Win Rate | 39.0% |
| P&L | $-755.46 |
| PF | 0.83 |
| Max DD | 43.2% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.83 (below 1.3)
- [FAIL] G2:MAX_DD: DD 43.2% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.1% trades, 2.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 100tr PF=0.87 [FAIL] | W2: 78tr PF=0.74 [FAIL] | W3: 108tr PF=0.86 [FAIL]
- [OK] S1:TRADE_FREQ: 287 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.63 (negative or zero)
