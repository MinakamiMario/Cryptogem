# Sprint 1 — sprint1_005_h4h01_rsi_entry30_sl_pct5_time_limit20_tp_pct5

- **Hypothesis**: RSI Mean Reversion (H4H-01)
- **Category**: mean_reversion
- **Exit template**: mr
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 531 |
| Win Rate | 43.7% |
| P&L | $-1,450.92 |
| PF | 0.66 |
| Max DD | 73.2% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.66 (below 1.3)
- [FAIL] G2:MAX_DD: DD 73.2% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.5% trades, 3.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 197tr PF=0.66 [FAIL] | W2: 148tr PF=0.67 [FAIL] | W3: 185tr PF=0.65 [FAIL]
- [OK] S1:TRADE_FREQ: 531 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.73 (negative or zero)
