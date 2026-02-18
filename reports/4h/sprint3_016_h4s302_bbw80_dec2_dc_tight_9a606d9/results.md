# Sprint 3 — sprint3_016_h4s302_bbw80_dec2_dc_tight

- **Hypothesis**: Volatility Exhaustion Fade (DC Exits) (H4S3-02)
- **Category**: mean_reversion
- **Exit template**: dc_tight
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.3s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 449 |
| Win Rate | 45.2% |
| P&L | $-524.24 |
| PF | 0.93 |
| Max DD | 58.1% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 38 | $+687.60 | 25 |
| DC TARGET | 77 | $+1,326.23 | 50 |
| RSI RECOVERY | 220 | $+3,222.80 | 125 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-35.65 | 0 |
| FIXED STOP | 43 | $-3,751.52 | 0 |
| TIME MAX | 68 | $-1,973.70 | 3 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.93 (below 1.05)
- [FAIL] G2:MAX_DD: DD 58.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 26.7% trades, 11.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 149tr PF=0.98 [FAIL] | W2: 142tr PF=0.80 [FAIL] | W3: 156tr PF=0.94 [FAIL]
- [OK] S1:TRADE_FREQ: 449 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.17 (negative or zero)
