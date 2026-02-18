# Sprint 3 — sprint3_018_h4s302_bbw80_dec2_dc_wide

- **Hypothesis**: Volatility Exhaustion Fade (DC Exits) (H4S3-02)
- **Category**: mean_reversion
- **Exit template**: dc_wide
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.3s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 378 |
| Win Rate | 42.9% |
| P&L | $-1,473.57 |
| PF | 0.68 |
| Max DD | 76.6% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 28 | $+222.04 | 15 |
| DC TARGET | 55 | $+365.90 | 29 |
| RSI RECOVERY | 260 | $+285.22 | 118 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-5.19 | 0 |
| FIXED STOP | 15 | $-1,201.10 | 0 |
| TIME MAX | 17 | $-737.99 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.68 (below 1.05)
- [FAIL] G2:MAX_DD: DD 76.6% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 26.5% trades, 9.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 121tr PF=0.69 [FAIL] | W2: 112tr PF=0.58 [FAIL] | W3: 144tr PF=0.78 [FAIL]
- [OK] S1:TRADE_FREQ: 378 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.90 (negative or zero)
