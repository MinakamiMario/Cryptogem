# Sprint 3 — sprint3_006_h4s304_regime_typeA_rsi_max40_dc_wide

- **Hypothesis**: RSI + Regime Filter (DC Exits) (H4S3-04)
- **Category**: mean_reversion
- **Exit template**: dc_wide
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 235 |
| Win Rate | 44.7% |
| P&L | $-1,288.46 |
| PF | 0.63 |
| Max DD | 65.1% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 15 | $+299.89 | 10 |
| DC TARGET | 26 | $+536.12 | 20 |
| RSI RECOVERY | 157 | $+193.34 | 75 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-51.13 | 0 |
| FIXED STOP | 15 | $-1,384.48 | 0 |
| TIME MAX | 19 | $-882.20 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.63 (below 1.05)
- [FAIL] G2:MAX_DD: DD 65.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.2% trades, 18.4% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 77tr PF=0.61 [FAIL] | W2: 86tr PF=0.98 [FAIL] | W3: 71tr PF=0.38 [FAIL]
- [OK] S1:TRADE_FREQ: 235 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.48 (negative or zero)
