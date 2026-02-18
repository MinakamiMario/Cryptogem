# Sprint 4 -- sprint4_039_h4s4g03_vol5x_dczone_rsi35

- **Hypothesis**: Vol Capitulation 5x DCzone RSI35 (H4S4-G03)
- **Family**: Volume Capitulation
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7301, entries=2885/2885

## Results
| Metric | Value |
|--------|-------|
| Trades | 219 |
| Win Rate | 48.4% |
| P&L | $-846.82 |
| PF | 0.98 |
| Max DD | 83.9% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 9 | $+169.16 | 8 |
| DC TARGET | 28 | $+1,122.63 | 24 |
| RSI RECOVERY | 91 | $+3,700.82 | 70 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+15.93 | 2 |
| FIXED STOP | 44 | $-3,983.43 | 0 |
| TIME MAX | 44 | $-1,159.99 | 2 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.98 (below 1.05)
- [FAIL] G2:MAX_DD: DD 83.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 18.3% trades, 16.5% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 73tr PF=1.00 [FAIL] | W2: 75tr PF=0.59 [FAIL] | W3: 70tr PF=1.40 [PASS]
- [OK] S1:TRADE_FREQ: 219 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.87 (negative or zero)
