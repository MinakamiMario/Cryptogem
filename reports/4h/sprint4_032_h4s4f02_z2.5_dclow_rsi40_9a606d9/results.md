# Sprint 4 -- sprint4_032_h4s4f02_z2.5_dclow_rsi40

- **Hypothesis**: Z-Score -2.5 DClow RSI40 (H4S4-F02)
- **Family**: Z-Score Extreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.6977, entries=5885/5885

## Results
| Metric | Value |
|--------|-------|
| Trades | 206 |
| Win Rate | 52.9% |
| P&L | $+4,915.03 |
| PF | 1.35 |
| Max DD | 44.0% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 5 | $+435.35 | 5 |
| DC TARGET | 29 | $+8,827.89 | 24 |
| RSI RECOVERY | 90 | $+8,797.59 | 80 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-223.11 | 0 |
| FIXED STOP | 34 | $-8,954.40 | 0 |
| TIME MAX | 45 | $-3,968.28 | 0 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.35 (PASS)
- [FAIL] G2:MAX_DD: DD 44.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 15.0% trades, 10.1% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 66tr PF=0.84 [FAIL] | W2: 68tr PF=2.43 [PASS] | W3: 71tr PF=0.80 [FAIL]
- [OK] S1:TRADE_FREQ: 206 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $23.86 (positive)
