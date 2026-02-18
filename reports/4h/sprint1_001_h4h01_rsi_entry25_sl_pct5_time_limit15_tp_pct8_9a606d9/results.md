# Sprint 1 — sprint1_001_h4h01_rsi_entry25_sl_pct5_time_limit15_tp_pct8

- **Hypothesis**: RSI Mean Reversion (H4H-01)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 280 |
| Win Rate | 41.1% |
| P&L | $-513.12 |
| PF | 0.89 |
| Max DD | 37.9% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.89 (below 1.3)
- [FAIL] G2:MAX_DD: DD 37.9% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.1% trades, 4.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 94tr PF=0.88 [FAIL] | W2: 79tr PF=0.89 [FAIL] | W3: 105tr PF=0.89 [FAIL]
- [OK] S1:TRADE_FREQ: 280 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.83 (negative or zero)
