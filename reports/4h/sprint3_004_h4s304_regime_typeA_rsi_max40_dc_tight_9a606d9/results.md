# Sprint 3 — sprint3_004_h4s304_regime_typeA_rsi_max40_dc_tight

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
| Trades | 290 |
| Win Rate | 42.1% |
| P&L | $-1,315.98 |
| PF | 0.67 |
| Max DD | 67.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 26 | $+487.22 | 18 |
| DC TARGET | 35 | $+707.76 | 27 |
| RSI RECOVERY | 105 | $+1,156.61 | 68 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-1.72 | 0 |
| FIXED STOP | 40 | $-2,187.94 | 0 |
| TIME MAX | 82 | $-1,477.90 | 9 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.67 (below 1.05)
- [FAIL] G2:MAX_DD: DD 67.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.7% trades, 13.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 96tr PF=0.62 [FAIL] | W2: 110tr PF=1.01 [FAIL] | W3: 82tr PF=0.42 [FAIL]
- [OK] S1:TRADE_FREQ: 290 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.54 (negative or zero)
