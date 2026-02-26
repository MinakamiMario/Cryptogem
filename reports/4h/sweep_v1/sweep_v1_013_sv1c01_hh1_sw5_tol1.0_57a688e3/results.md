# Sweep v1 -- sweep_v1_013_sv1c01_hh1_sw5_tol1.0

- **Hypothesis**: TrendPullback HH1 Swing5 Tol1.0 (SV1-C01)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5852, entries=10747/10747
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 238 |
| Win Rate | 53.4% |
| P&L | $-1,465.88 |
| PF | 0.87 |
| Max DD | 79.0% |
| EV/trade | $-6.16 |
| Class A share | 100% |
| Stopout ratio | 17% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 15 | $+768.94 | 13 |
| DC TARGET | 14 | $+712.16 | 13 |
| RSI RECOVERY | 127 | $+2,446.32 | 99 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+2.71 | 2 |
| FIXED STOP | 40 | $-3,131.30 | 0 |
| TIME MAX | 39 | $-1,447.55 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.87 (below 1.05)
- [FAIL] G2:MAX_DD: DD 79.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.8% trades, 29.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 78tr PF=0.84 [FAIL] | W2: 82tr PF=0.75 [FAIL] | W3: 77tr PF=1.12 [PASS]
- [OK] S1:TRADE_FREQ: 238 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.16 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.87 < 0.90
- Best exit: RSI RECOVERY ($2446, 127 trades, 78% WR)
- Worst exit: FIXED STOP ($-3131, 40 trades)
- LOW STOPOUT: 17% -- entries have good geometric placement
