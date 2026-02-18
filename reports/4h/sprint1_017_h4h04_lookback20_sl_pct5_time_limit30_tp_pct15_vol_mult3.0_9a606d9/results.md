# Sprint 1 — sprint1_017_h4h04_lookback20_sl_pct5_time_limit30_tp_pct15_vol_mult3.0

- **Hypothesis**: Volume Breakout (H4H-04)
- **Category**: volume
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 588 |
| Win Rate | 20.1% |
| P&L | $-1,839.46 |
| PF | 0.55 |
| Max DD | 92.1% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.55 (below 1.3)
- [FAIL] G2:MAX_DD: DD 92.1% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 8.5% trades, 3.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 218tr PF=0.49 [FAIL] | W2: 168tr PF=0.70 [FAIL] | W3: 200tr PF=0.61 [FAIL]
- [OK] S1:TRADE_FREQ: 588 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.13 (negative or zero)
