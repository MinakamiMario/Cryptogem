# Sweep v1 -- sweep_v1_014_sv1c02_hh2_sw5_tol1.5

- **Hypothesis**: TrendPullback HH2 Swing5 Tol1.5 (SV1-C02)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Compat score**: avg=0.5847, entries=2296/2296
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 183 |
| Win Rate | 55.2% |
| P&L | $-757.06 |
| PF | 0.73 |
| Max DD | 59.0% |
| EV/trade | $-4.14 |
| Class A share | 100% |
| Stopout ratio | 14% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 8 | $+152.41 | 8 |
| DC TARGET | 13 | $+393.72 | 12 |
| RSI RECOVERY | 106 | $+1,371.67 | 80 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $+3.37 | 1 |
| FIXED STOP | 25 | $-1,763.60 | 0 |
| TIME MAX | 29 | $-914.63 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.73 (below 1.05)
- [FAIL] G2:MAX_DD: DD 59.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.8% trades, 18.0% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 63tr PF=0.45 [FAIL] | W2: 65tr PF=0.99 [FAIL] | W3: 54tr PF=1.57 [PASS]
- [OK] S1:TRADE_FREQ: 183 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.14 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.73 < 0.90
- Best exit: RSI RECOVERY ($1372, 106 trades, 76% WR)
- Worst exit: FIXED STOP ($-1764, 25 trades)
- LOW STOPOUT: 14% -- entries have good geometric placement
