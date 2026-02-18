# Sprint 1 — sprint1_016_h4h04_lookback10_sl_pct5_time_limit20_tp_pct8_vol_mult3.0

- **Hypothesis**: Volume Breakout (H4H-04)
- **Category**: volume
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 431 |
| Win Rate | 24.8% |
| P&L | $-1,965.19 |
| PF | 0.43 |
| Max DD | 98.3% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.43 (below 1.3)
- [FAIL] G2:MAX_DD: DD 98.3% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.7% trades, 0.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 152tr PF=0.39 [FAIL] | W2: 115tr PF=0.53 [FAIL] | W3: 163tr PF=0.45 [FAIL]
- [OK] S1:TRADE_FREQ: 431 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.56 (negative or zero)
