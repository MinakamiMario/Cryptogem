# Sprint 1 — sprint1_014_h4h04_lookback10_sl_pct8_time_limit25_tp_pct12_vol_mult2.0

- **Hypothesis**: Volume Breakout (H4H-04)
- **Category**: volume
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 275 |
| Win Rate | 32.4% |
| P&L | $-1,801.65 |
| PF | 0.63 |
| Max DD | 90.1% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.63 (below 1.3)
- [FAIL] G2:MAX_DD: DD 90.1% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.1% trades, 5.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 102tr PF=0.63 [FAIL] | W2: 83tr PF=0.63 [FAIL] | W3: 89tr PF=0.69 [FAIL]
- [OK] S1:TRADE_FREQ: 275 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.55 (negative or zero)
