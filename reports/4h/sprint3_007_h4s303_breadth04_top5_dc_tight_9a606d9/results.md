# Sprint 3 — sprint3_007_h4s303_breadth04_top5_dc_tight

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_tight
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 824 |
| Win Rate | 33.9% |
| P&L | $-1,597.58 |
| PF | 0.78 |
| Max DD | 88.4% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 141 | $-559.20 | 28 |
| DC TARGET | 593 | $+2,383.47 | 248 |
| RSI RECOVERY | 14 | $-139.64 | 3 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-1.40 | 0 |
| FIXED STOP | 74 | $-3,280.81 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.78 (below 1.05)
- [FAIL] G2:MAX_DD: DD 88.4% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.5% trades, 2.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 300tr PF=0.79 [FAIL] | W2: 285tr PF=0.54 [FAIL] | W3: 237tr PF=1.01 [FAIL]
- [OK] S1:TRADE_FREQ: 824 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.94 (negative or zero)
