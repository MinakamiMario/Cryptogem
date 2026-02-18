# Sprint 1 — sprint1_007_h4h02_sl_pct8_squeeze_pct50_time_limit25_tp_pct12_vol_mult1.5

- **Hypothesis**: BB Squeeze Breakout (H4H-02)
- **Category**: volatility
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 181 |
| Win Rate | 29.3% |
| P&L | $-1,709.86 |
| PF | 0.53 |
| Max DD | 86.2% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.53 (below 1.3)
- [FAIL] G2:MAX_DD: DD 86.2% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.4% trades, 1.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 60tr PF=0.56 [FAIL] | W2: 53tr PF=0.68 [FAIL] | W3: 67tr PF=0.33 [FAIL]
- [OK] S1:TRADE_FREQ: 181 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-9.45 (negative or zero)
