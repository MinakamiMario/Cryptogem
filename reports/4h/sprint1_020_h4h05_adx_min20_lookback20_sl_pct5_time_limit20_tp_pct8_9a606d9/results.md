# Sprint 1 — sprint1_020_h4h05_adx_min20_lookback20_sl_pct5_time_limit20_tp_pct8

- **Hypothesis**: Momentum Trend (HH/HL + ADX) (H4H-05)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 443 |
| Win Rate | 32.3% |
| P&L | $-1,706.44 |
| PF | 0.65 |
| Max DD | 85.3% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.3)
- [FAIL] G2:MAX_DD: DD 85.3% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.3% trades, 9.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 178tr PF=0.60 [FAIL] | W2: 104tr PF=0.98 [FAIL] | W3: 160tr PF=0.54 [FAIL]
- [OK] S1:TRADE_FREQ: 443 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.85 (negative or zero)
