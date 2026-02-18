# Sprint 3 — sprint3_010_h4s303_breadth03_top10_dc_tight

- **Hypothesis**: Cross-Sectional Relative Strength (DC Exits) (H4S3-03)
- **Category**: momentum
- **Exit template**: dc_tight
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 1299 |
| Win Rate | 33.4% |
| P&L | $-1,953.56 |
| PF | 0.65 |
| Max DD | 98.3% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 206 | $-654.75 | 47 |
| DC TARGET | 952 | $+1,483.50 | 385 |
| RSI RECOVERY | 39 | $-310.11 | 2 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-0.16 | 0 |
| FIXED STOP | 100 | $-2,472.03 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.05)
- [FAIL] G2:MAX_DD: DD 98.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 9.6% trades, 2.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 440tr PF=0.64 [FAIL] | W2: 469tr PF=0.77 [FAIL] | W3: 388tr PF=0.61 [FAIL]
- [OK] S1:TRADE_FREQ: 1299 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.50 (negative or zero)
