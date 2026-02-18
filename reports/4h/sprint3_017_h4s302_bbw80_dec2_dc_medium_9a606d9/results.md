# Sprint 3 — sprint3_017_h4s302_bbw80_dec2_dc_medium

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
| Trades | 390 |
| Win Rate | 48.7% |
| P&L | $-888.35 |
| PF | 0.95 |
| Max DD | 68.0% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 39 | $+761.27 | 27 |
| DC TARGET | 71 | $+923.43 | 46 |
| RSI RECOVERY | 219 | $+2,427.08 | 115 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-32.41 | 0 |
| FIXED STOP | 25 | $-2,751.45 | 0 |
| TIME MAX | 33 | $-1,613.81 | 2 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.95 (below 1.05)
- [FAIL] G2:MAX_DD: DD 68.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 29.2% trades, 14.5% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 130tr PF=1.21 [PASS] | W2: 122tr PF=0.64 [FAIL] | W3: 137tr PF=0.80 [FAIL]
- [OK] S1:TRADE_FREQ: 390 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.28 (negative or zero)
