# Sprint 4 -- sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35

- **Hypothesis**: Vol Capitulation 4x DCzone+BBlow RSI35 (H4S4-G06)
- **Family**: Volume Capitulation
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7525, entries=2498/2498

## Results
| Metric | Value |
|--------|-------|
| Trades | 214 |
| Win Rate | 53.3% |
| P&L | $+823.92 |
| PF | 1.28 |
| Max DD | 59.1% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 7 | $+460.86 | 6 |
| DC TARGET | 36 | $+1,921.34 | 34 |
| RSI RECOVERY | 84 | $+5,788.71 | 71 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-41.38 | 1 |
| FIXED STOP | 44 | $-5,109.42 | 0 |
| TIME MAX | 40 | $-1,202.84 | 2 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.28 (PASS)
- [FAIL] G2:MAX_DD: DD 59.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.4% trades, 33.7% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 71tr PF=0.96 [FAIL] | W2: 75tr PF=1.11 [PASS] | W3: 67tr PF=1.70 [PASS]
- [OK] S1:TRADE_FREQ: 214 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $3.85 (positive)
