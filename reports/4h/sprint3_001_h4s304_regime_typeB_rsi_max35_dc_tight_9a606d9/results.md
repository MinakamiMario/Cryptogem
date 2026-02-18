# Sprint 3 — sprint3_001_h4s304_regime_typeB_rsi_max35_dc_tight

- **Hypothesis**: RSI + Regime Filter (DC Exits) (H4S3-04)
- **Category**: mean_reversion
- **Exit template**: dc_tight
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 277 |
| Win Rate | 46.9% |
| P&L | $-806.61 |
| PF | 0.79 |
| Max DD | 63.7% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 23 | $+337.68 | 17 |
| DC TARGET | 25 | $+528.09 | 19 |
| RSI RECOVERY | 115 | $+1,725.10 | 81 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $-15.39 | 0 |
| FIXED STOP | 37 | $-2,093.97 | 0 |
| TIME MAX | 76 | $-1,288.13 | 13 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.79 (below 1.05)
- [FAIL] G2:MAX_DD: DD 63.7% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.2% trades, 2.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 86tr PF=0.59 [FAIL] | W2: 94tr PF=0.97 [FAIL] | W3: 95tr PF=1.03 [FAIL]
- [OK] S1:TRADE_FREQ: 277 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.91 (negative or zero)
