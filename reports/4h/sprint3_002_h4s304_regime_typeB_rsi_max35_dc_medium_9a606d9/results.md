# Sprint 3 — sprint3_002_h4s304_regime_typeB_rsi_max35_dc_medium

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
| Trades | 242 |
| Win Rate | 50.4% |
| P&L | $-684.61 |
| PF | 0.81 |
| Max DD | 56.3% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 31 | $+383.44 | 24 |
| DC TARGET | 24 | $+472.33 | 18 |
| RSI RECOVERY | 125 | $+1,622.89 | 80 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-48.46 | 0 |
| FIXED STOP | 30 | $-2,088.97 | 0 |
| TIME MAX | 30 | $-1,025.84 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.81 (below 1.05)
- [FAIL] G2:MAX_DD: DD 56.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.9% trades, 9.2% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 71tr PF=0.48 [FAIL] | W2: 82tr PF=0.95 [FAIL] | W3: 88tr PF=1.17 [PASS]
- [OK] S1:TRADE_FREQ: 242 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.83 (negative or zero)
