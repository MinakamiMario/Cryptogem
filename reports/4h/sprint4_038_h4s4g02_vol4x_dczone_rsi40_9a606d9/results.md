# Sprint 4 -- sprint4_038_h4s4g02_vol4x_dczone_rsi40

- **Hypothesis**: Vol Capitulation 4x DCzone RSI40 (H4S4-G02)
- **Family**: Volume Capitulation
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7075, entries=5113/5113

## Results
| Metric | Value |
|--------|-------|
| Trades | 226 |
| Win Rate | 50.9% |
| P&L | $-1,251.03 |
| PF | 0.98 |
| Max DD | 89.5% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 6 | $+124.49 | 5 |
| DC TARGET | 21 | $+572.58 | 20 |
| RSI RECOVERY | 109 | $+4,240.11 | 87 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+3.82 | 2 |
| FIXED STOP | 47 | $-3,837.10 | 0 |
| TIME MAX | 40 | $-1,187.49 | 1 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.98 (below 1.05)
- [FAIL] G2:MAX_DD: DD 89.5% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.7% trades, 13.1% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 78tr PF=0.92 [FAIL] | W2: 78tr PF=0.84 [FAIL] | W3: 69tr PF=1.43 [PASS]
- [OK] S1:TRADE_FREQ: 226 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.54 (negative or zero)
