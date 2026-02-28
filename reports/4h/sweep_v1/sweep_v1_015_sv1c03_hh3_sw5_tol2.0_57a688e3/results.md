# Sweep v1 -- sweep_v1_015_sv1c03_hh3_sw5_tol2.0

- **Hypothesis**: TrendPullback HH3 Swing5 Tol2.0 (SV1-C03)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Compat score**: avg=0.6298, entries=408/408
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 61 |
| Win Rate | 55.7% |
| P&L | $-437.54 |
| PF | 0.65 |
| Max DD | 24.3% |
| EV/trade | $-7.17 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 3 | $+69.47 | 3 |
| DC TARGET | 6 | $+88.24 | 5 |
| RSI RECOVERY | 35 | $+569.66 | 26 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 8 | $-777.19 | 0 |
| TIME MAX | 9 | $-387.72 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [FAIL] G1:PF: PF 0.65 (below 1.05)
- [PASS] G2:MAX_DD: DD 24.3% (PASS)
- [PASS] G3:TOP10_CONC: Top10: 27.9% trades, 31.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 14tr PF=0.48 [FAIL] | W2: 19tr PF=1.91 [PASS] | W3: 27tr PF=0.41 [FAIL]
- [OK] S1:TRADE_FREQ: 61 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.17 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.65 < 0.90
- Best exit: RSI RECOVERY ($570, 35 trades, 74% WR)
- Worst exit: FIXED STOP ($-777, 8 trades)
- LOW STOPOUT: 13% -- entries have good geometric placement
