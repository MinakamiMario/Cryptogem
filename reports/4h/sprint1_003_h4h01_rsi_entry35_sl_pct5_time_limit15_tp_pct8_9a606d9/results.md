# Sprint 1 — sprint1_003_h4h01_rsi_entry35_sl_pct5_time_limit15_tp_pct8

- **Hypothesis**: RSI Mean Reversion (H4H-01)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.0s

## Results
| Metric | Value |
|--------|-------|
| Trades | 279 |
| Win Rate | 39.1% |
| P&L | $-1,220.78 |
| PF | 0.83 |
| Max DD | 67.6% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.83 (below 1.3)
- [FAIL] G2:MAX_DD: DD 67.6% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.8% trades, 6.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 94tr PF=0.84 [FAIL] | W2: 79tr PF=0.77 [FAIL] | W3: 105tr PF=0.87 [FAIL]
- [OK] S1:TRADE_FREQ: 279 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.38 (negative or zero)
