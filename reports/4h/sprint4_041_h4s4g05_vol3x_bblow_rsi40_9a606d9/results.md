# Sprint 4 -- sprint4_041_h4s4g05_vol3x_bblow_rsi40

- **Hypothesis**: Vol Capitulation 3x BBlow RSI40 (H4S4-G05)
- **Family**: Volume Capitulation
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7395, entries=4390/4390

## Results
| Metric | Value |
|--------|-------|
| Trades | 216 |
| Win Rate | 54.6% |
| P&L | $+2,283.84 |
| PF | 1.41 |
| Max DD | 49.8% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 9 | $+544.52 | 8 |
| DC TARGET | 32 | $+2,759.68 | 29 |
| RSI RECOVERY | 93 | $+8,134.09 | 79 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-183.63 | 0 |
| FIXED STOP | 39 | $-5,826.31 | 0 |
| TIME MAX | 40 | $-2,078.57 | 2 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.41 (PASS)
- [FAIL] G2:MAX_DD: DD 49.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.2% trades, 7.2% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 70tr PF=1.30 [PASS] | W2: 72tr PF=1.02 [FAIL] | W3: 73tr PF=1.82 [PASS]
- [OK] S1:TRADE_FREQ: 216 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $10.57 (positive)
