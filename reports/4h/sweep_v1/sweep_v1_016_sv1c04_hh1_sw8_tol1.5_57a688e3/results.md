# Sweep v1 -- sweep_v1_016_sv1c04_hh1_sw8_tol1.5

- **Hypothesis**: TrendPullback HH1 Swing8 Tol1.5 (SV1-C04)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5477, entries=18283/18283
- **Research grade**: WEAK_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 239 |
| Win Rate | 53.1% |
| P&L | $-926.90 |
| PF | 0.95 |
| Max DD | 63.9% |
| EV/trade | $-3.88 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 17 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 16 | $+295.24 | 14 |
| DC TARGET | 17 | $+869.70 | 14 |
| RSI RECOVERY | 130 | $+3,070.06 | 98 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-4.94 | 0 |
| FIXED STOP | 30 | $-2,635.59 | 0 |
| TIME MAX | 43 | $-1,858.47 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.95 (below 1.05)
- [FAIL] G2:MAX_DD: DD 63.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.8% trades, 6.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 82tr PF=0.86 [FAIL] | W2: 79tr PF=1.64 [PASS] | W3: 77tr PF=0.67 [FAIL]
- [OK] S1:TRADE_FREQ: 239 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.88 (negative or zero)

## Research Notes
- WEAK LEAD: PF=0.95, needs improvement (A share=100%, stopout=13%)
- Best exit: RSI RECOVERY ($3070, 130 trades, 75% WR)
- Worst exit: FIXED STOP ($-2636, 30 trades)
- Breakeven fee: 16.8 bps per side
- WARNING: unprofitable at Kraken fees (26 bps)
- LOW STOPOUT: 13% -- entries have good geometric placement
