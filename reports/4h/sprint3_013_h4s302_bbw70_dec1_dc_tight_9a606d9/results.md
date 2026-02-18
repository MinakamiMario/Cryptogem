# Sprint 3 — sprint3_013_h4s302_bbw70_dec1_dc_tight

- **Hypothesis**: Volatility Exhaustion Fade (DC Exits) (H4S3-02)
- **Category**: mean_reversion
- **Exit template**: dc_tight
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 411 |
| Win Rate | 44.3% |
| P&L | $-1,249.74 |
| PF | 0.71 |
| Max DD | 67.4% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 36 | $+386.19 | 23 |
| DC TARGET | 71 | $+656.35 | 53 |
| RSI RECOVERY | 195 | $+1,266.08 | 104 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-18.19 | 0 |
| FIXED STOP | 41 | $-2,311.98 | 0 |
| TIME MAX | 65 | $-1,228.18 | 2 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.71 (below 1.05)
- [FAIL] G2:MAX_DD: DD 67.4% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 32.8% trades, 8.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 139tr PF=0.68 [FAIL] | W2: 129tr PF=0.62 [FAIL] | W3: 141tr PF=0.94 [FAIL]
- [OK] S1:TRADE_FREQ: 411 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.04 (negative or zero)
