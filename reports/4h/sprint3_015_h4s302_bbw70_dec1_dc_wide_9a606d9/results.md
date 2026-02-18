# Sprint 3 — sprint3_015_h4s302_bbw70_dec1_dc_wide

- **Hypothesis**: Volatility Exhaustion Fade (DC Exits) (H4S3-02)
- **Category**: mean_reversion
- **Exit template**: dc_wide
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)

## Results
| Metric | Value |
|--------|-------|
| Trades | 379 |
| Win Rate | 45.4% |
| P&L | $-289.62 |
| PF | 0.95 |
| Max DD | 55.6% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 34 | $+658.88 | 25 |
| DC TARGET | 58 | $+781.36 | 35 |
| RSI RECOVERY | 260 | $+806.77 | 112 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-8.88 | 0 |
| FIXED STOP | 10 | $-1,543.81 | 0 |
| TIME MAX | 14 | $-983.95 | 0 |

## Gates (Stage 0 — relaxed PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.95 (below 1.05)
- [FAIL] G2:MAX_DD: DD 55.6% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 30.9% trades, 16.5% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 124tr PF=1.16 [PASS] | W2: 125tr PF=0.61 [FAIL] | W3: 128tr PF=0.96 [FAIL]
- [OK] S1:TRADE_FREQ: 379 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-0.76 (negative or zero)
