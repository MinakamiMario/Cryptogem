# Sprint 4 -- sprint4_037_h4s4g01_vol3x_dczone_rsi40

- **Hypothesis**: Vol Capitulation 3x DCzone RSI40 (H4S4-G01)
- **Family**: Volume Capitulation
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.707, entries=8255/8255

## Results
| Metric | Value |
|--------|-------|
| Trades | 222 |
| Win Rate | 50.5% |
| P&L | $-87.83 |
| PF | 1.18 |
| Max DD | 79.7% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 8 | $+96.82 | 6 |
| DC TARGET | 26 | $+1,338.89 | 23 |
| RSI RECOVERY | 102 | $+7,046.25 | 81 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-14.89 | 1 |
| FIXED STOP | 41 | $-5,162.05 | 0 |
| TIME MAX | 42 | $-1,967.54 | 1 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.18 (PASS)
- [FAIL] G2:MAX_DD: DD 79.7% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.7% trades, 1.8% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 77tr PF=1.23 [PASS] | W2: 76tr PF=0.75 [FAIL] | W3: 68tr PF=1.60 [PASS]
- [OK] S1:TRADE_FREQ: 222 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-0.40 (negative or zero)
