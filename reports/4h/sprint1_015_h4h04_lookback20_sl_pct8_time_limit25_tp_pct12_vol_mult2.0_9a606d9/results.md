# Sprint 1 — sprint1_015_h4h04_lookback20_sl_pct8_time_limit25_tp_pct12_vol_mult2.0

- **Hypothesis**: Volume Breakout (H4H-04)
- **Category**: volume
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 304 |
| Win Rate | 28.6% |
| P&L | $-1,947.28 |
| PF | 0.54 |
| Max DD | 97.4% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.54 (below 1.3)
- [FAIL] G2:MAX_DD: DD 97.4% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 10.9% trades, 8.4% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 124tr PF=0.52 [FAIL] | W2: 71tr PF=0.64 [FAIL] | W3: 108tr PF=0.50 [FAIL]
- [OK] S1:TRADE_FREQ: 304 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.41 (negative or zero)
