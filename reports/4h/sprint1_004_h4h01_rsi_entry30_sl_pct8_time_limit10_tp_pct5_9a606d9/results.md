# Sprint 1 — sprint1_004_h4h01_rsi_entry30_sl_pct8_time_limit10_tp_pct5

- **Hypothesis**: RSI Mean Reversion (H4H-01)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 356 |
| Win Rate | 46.1% |
| P&L | $-1,765.61 |
| PF | 0.57 |
| Max DD | 89.3% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.57 (below 1.3)
- [FAIL] G2:MAX_DD: DD 89.3% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.9% trades, 5.7% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 132tr PF=0.56 [FAIL] | W2: 104tr PF=0.59 [FAIL] | W3: 119tr PF=0.58 [FAIL]
- [OK] S1:TRADE_FREQ: 356 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.96 (negative or zero)
