# Sprint 3 — sprint3_005_h4s304_regime_typeA_rsi_max40_dc_medium

- **Hypothesis**: RSI + Regime Filter (DC Exits) (H4S3-04)
- **Category**: mean_reversion
- **Exit template**: dc_medium
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 254 |
| Win Rate | 45.3% |
| P&L | $-1,294.49 |
| PF | 0.63 |
| Max DD | 66.6% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 19 | $+360.04 | 14 |
| DC TARGET | 35 | $+586.51 | 25 |
| RSI RECOVERY | 129 | $+781.76 | 76 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-10.95 | 0 |
| FIXED STOP | 33 | $-2,146.34 | 0 |
| TIME MAX | 35 | $-865.50 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.63 (below 1.05)
- [FAIL] G2:MAX_DD: DD 66.6% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.8% trades, 15.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 87tr PF=0.55 [FAIL] | W2: 91tr PF=0.94 [FAIL] | W3: 74tr PF=0.45 [FAIL]
- [OK] S1:TRADE_FREQ: 254 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.10 (negative or zero)
