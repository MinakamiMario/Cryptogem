# Sprint 3 — sprint3_012_h4s303_breadth03_top10_dc_wide

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_wide
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 1295 |
| Win Rate | 33.7% |
| P&L | $-1,952.73 |
| PF | 0.65 |
| Max DD | 98.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 228 | $-1,164.62 | 47 |
| DC TARGET | 989 | $+936.30 | 387 |
| RSI RECOVERY | 43 | $-340.17 | 2 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-0.16 | 0 |
| FIXED STOP | 32 | $-1,374.44 | 0 |
| TIME MAX | 1 | $-9.62 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.7% trades, 2.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 439tr PF=0.62 [FAIL] | W2: 464tr PF=0.88 [FAIL] | W3: 390tr PF=0.60 [FAIL]
- [OK] S1:TRADE_FREQ: 1295 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.51 (negative or zero)
