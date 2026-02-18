# Sprint 4 -- sprint4_012_h4s4b05_dclow_wick40_rsi40_highvol

- **Hypothesis**: Wick Rejection DClow 40pct RSI40 HighVol (H4S4-B05)
- **Family**: Wick Rejection
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.6961, entries=5629/5629

## Results
| Metric | Value |
|--------|-------|
| Trades | 232 |
| Win Rate | 45.7% |
| P&L | $-1,456.88 |
| PF | 0.67 |
| Max DD | 76.5% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 7 | $+294.23 | 5 |
| DC TARGET | 31 | $+592.33 | 27 |
| RSI RECOVERY | 104 | $+1,735.16 | 72 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $+2.09 | 1 |
| FIXED STOP | 39 | $-2,694.94 | 0 |
| TIME MAX | 49 | $-1,385.76 | 1 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.67 (below 1.05)
- [FAIL] G2:MAX_DD: DD 76.5% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.9% trades, 15.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 83tr PF=0.69 [FAIL] | W2: 74tr PF=0.84 [FAIL] | W3: 74tr PF=0.34 [FAIL]
- [OK] S1:TRADE_FREQ: 232 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.28 (negative or zero)
