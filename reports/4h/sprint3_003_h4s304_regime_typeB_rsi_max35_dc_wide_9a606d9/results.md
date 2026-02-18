# Sprint 3 — sprint3_003_h4s304_regime_typeB_rsi_max35_dc_wide

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
| Trades | 246 |
| Win Rate | 48.0% |
| P&L | $-643.92 |
| PF | 0.81 |
| Max DD | 62.9% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 20 | $+291.94 | 16 |
| DC TARGET | 20 | $+273.44 | 14 |
| RSI RECOVERY | 171 | $+868.74 | 88 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-49.83 | 0 |
| FIXED STOP | 17 | $-1,435.70 | 0 |
| TIME MAX | 16 | $-592.51 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.81 (below 1.05)
- [FAIL] G2:MAX_DD: DD 62.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.9% trades, 7.5% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 76tr PF=0.51 [FAIL] | W2: 83tr PF=0.76 [FAIL] | W3: 86tr PF=1.65 [PASS]
- [OK] S1:TRADE_FREQ: 246 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.62 (negative or zero)
