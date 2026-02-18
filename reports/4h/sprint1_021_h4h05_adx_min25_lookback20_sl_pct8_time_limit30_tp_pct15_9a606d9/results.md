# Sprint 1 — sprint1_021_h4h05_adx_min25_lookback20_sl_pct8_time_limit30_tp_pct15

- **Hypothesis**: Momentum Trend (HH/HL + ADX) (H4H-05)
- **Category**: momentum
- **Exit template**: trend
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s

## Results
| Metric | Value |
|--------|-------|
| Trades | 426 |
| Win Rate | 31.2% |
| P&L | $-1,469.19 |
| PF | 0.76 |
| Max DD | 74.5% |

## Gates
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.76 (below 1.3)
- [FAIL] G2:MAX_DD: DD 74.5% (exceeds 15.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.0% trades, 12.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 169tr PF=0.83 [FAIL] | W2: 98tr PF=0.78 [FAIL] | W3: 158tr PF=0.60 [FAIL]
- [OK] S1:TRADE_FREQ: 426 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.45 (negative or zero)
