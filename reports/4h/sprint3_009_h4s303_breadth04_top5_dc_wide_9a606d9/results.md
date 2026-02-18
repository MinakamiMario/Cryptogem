# Sprint 3 — sprint3_009_h4s303_breadth04_top5_dc_wide

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_wide
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 823 |
| Win Rate | 34.8% |
| P&L | $-1,564.04 |
| PF | 0.77 |
| Max DD | 89.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 160 | $-1,112.26 | 30 |
| DC TARGET | 617 | $+1,672.53 | 253 |
| RSI RECOVERY | 18 | $-239.59 | 3 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-1.52 | 0 |
| FIXED STOP | 26 | $-1,883.21 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.77 (below 1.05)
- [FAIL] G2:MAX_DD: DD 89.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.5% trades, 1.6% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 299tr PF=0.74 [FAIL] | W2: 285tr PF=0.66 [FAIL] | W3: 237tr PF=1.06 [PASS]
- [OK] S1:TRADE_FREQ: 823 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.90 (negative or zero)
