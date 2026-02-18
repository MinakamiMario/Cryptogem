# Sprint 3 — sprint3_014_h4s302_bbw70_dec1_dc_medium

- **Hypothesis**: Volatility Exhaustion Fade (DC Exits) (H4S3-02)
- **Category**: mean_reversion
- **Exit template**: dc_medium
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 358 |
| Win Rate | 48.0% |
| P&L | $-547.32 |
| PF | 0.89 |
| Max DD | 52.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 35 | $+536.23 | 24 |
| DC TARGET | 59 | $+364.00 | 38 |
| RSI RECOVERY | 208 | $+1,959.12 | 109 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-35.22 | 0 |
| FIXED STOP | 20 | $-1,850.49 | 0 |
| TIME MAX | 33 | $-1,520.94 | 1 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.89 (below 1.05)
- [FAIL] G2:MAX_DD: DD 52.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 33.0% trades, 19.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 122tr PF=1.01 [FAIL] | W2: 112tr PF=0.60 [FAIL] | W3: 122tr PF=1.01 [FAIL]
- [OK] S1:TRADE_FREQ: 358 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.53 (negative or zero)
