# Sweep v1 -- sweep_v1_017_sv1c05_hh2_sw8_tol1.0_rsi35

- **Hypothesis**: TrendPullback HH2 Swing8 Tol1.0 RSI35 (SV1-C05)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Compat score**: avg=0.6422, entries=1047/1047
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 123 |
| Win Rate | 51.2% |
| P&L | $-1,087.34 |
| PF | 0.75 |
| Max DD | 55.4% |
| EV/trade | $-8.84 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+258.25 | 4 |
| DC TARGET | 8 | $+158.44 | 8 |
| RSI RECOVERY | 68 | $+1,221.30 | 50 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| FIXED STOP | 16 | $-1,389.29 | 0 |
| TIME MAX | 27 | $-856.63 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.75 (below 1.05)
- [FAIL] G2:MAX_DD: DD 55.4% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 23.6% trades, 2.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 35tr PF=0.57 [FAIL] | W2: 39tr PF=1.40 [PASS] | W3: 48tr PF=0.72 [FAIL]
- [OK] S1:TRADE_FREQ: 123 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-8.84 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.75 < 0.90
- Best exit: RSI RECOVERY ($1221, 68 trades, 74% WR)
- Worst exit: FIXED STOP ($-1389, 16 trades)
- LOW STOPOUT: 13% -- entries have good geometric placement
