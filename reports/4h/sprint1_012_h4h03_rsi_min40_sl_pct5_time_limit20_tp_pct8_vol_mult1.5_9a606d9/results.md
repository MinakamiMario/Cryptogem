# Sprint 1 — sprint1_012_h4h03_rsi_min40_sl_pct5_time_limit20_tp_pct8_vol_mult1.5

- **Hypothesis**: EMA Cross + RSI (H4H-03)
- **Category**: trend_following
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 347 |
| Win Rate | 28.2% |
| P&L | $-1,779.38 |
| PF | 0.51 |
| Max DD | 89.8% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.51 (below 1.3)
- [FAIL] G2:MAX_DD: DD 89.8% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 10.7% trades, 5.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 132tr PF=0.52 [FAIL] | W2: 109tr PF=0.48 [FAIL] | W3: 104tr PF=0.48 [FAIL]
- [OK] S1:TRADE_FREQ: 347 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.13 (negative or zero)
