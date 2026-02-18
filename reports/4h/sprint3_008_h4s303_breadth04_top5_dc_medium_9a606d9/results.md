# Sprint 3 — sprint3_008_h4s303_breadth04_top5_dc_medium

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_medium
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 823 |
| Win Rate | 34.5% |
| P&L | $-1,538.54 |
| PF | 0.79 |
| Max DD | 88.6% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 150 | $-703.89 | 29 |
| DC TARGET | 606 | $+2,178.00 | 252 |
| RSI RECOVERY | 18 | $-259.59 | 3 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-1.61 | 0 |
| FIXED STOP | 47 | $-2,751.45 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.79 (below 1.05)
- [FAIL] G2:MAX_DD: DD 88.6% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.5% trades, 2.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 299tr PF=0.78 [FAIL] | W2: 285tr PF=0.62 [FAIL] | W3: 237tr PF=1.04 [FAIL]
- [OK] S1:TRADE_FREQ: 823 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.87 (negative or zero)
