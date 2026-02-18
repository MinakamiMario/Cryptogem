# Sprint 3 — sprint3_011_h4s303_breadth03_top10_dc_medium

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_medium
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 1294 |
| Win Rate | 33.5% |
| P&L | $-1,951.83 |
| PF | 0.65 |
| Max DD | 98.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 214 | $-804.73 | 46 |
| DC TARGET | 970 | $+1,240.44 | 385 |
| RSI RECOVERY | 45 | $-368.23 | 2 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-0.17 | 0 |
| FIXED STOP | 62 | $-2,008.06 | 0 |
| TIME MAX | 1 | $-11.08 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.7% trades, 2.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 439tr PF=0.64 [FAIL] | W2: 466tr PF=0.80 [FAIL] | W3: 387tr PF=0.60 [FAIL]
- [OK] S1:TRADE_FREQ: 1294 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.51 (negative or zero)
