# Sweep v1 -- sweep_v1_018_sv1c06_hh1_sw5_tol2.0_rsi45

- **Hypothesis**: TrendPullback HH1 Swing5 Tol2.0 RSI45 (SV1-C06)
- **Family**: TrendPullback
- **Category**: trend_following
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.529, entries=18313/18313
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 259 |
| Win Rate | 59.1% |
| P&L | $-367.57 |
| PF | 1.09 |
| Max DD | 55.9% |
| EV/trade | $-1.42 |
| Class A share | 100% |
| Stopout ratio | 14% |
| Breakeven fee | 41 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 18 | $+1,176.12 | 17 |
| DC TARGET | 13 | $+1,122.36 | 12 |
| RSI RECOVERY | 149 | $+4,894.09 | 121 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+19.74 | 3 |
| FIXED STOP | 36 | $-4,512.71 | 0 |
| TIME MAX | 40 | $-2,097.10 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.09 (PASS)
- [FAIL] G2:MAX_DD: DD 55.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.1% trades, 15.5% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 85tr PF=1.03 [FAIL] | W2: 88tr PF=1.20 [PASS] | W3: 85tr PF=1.09 [PASS]
- [OK] S1:TRADE_FREQ: 259 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-1.42 (negative or zero)

## Research Notes
- STRONG LEAD: PF=1.09, Class A share=100%, stopout ratio=14%
- Best exit: RSI RECOVERY ($4894, 149 trades, 81% WR)
- Worst exit: FIXED STOP ($-4513, 36 trades)
- Breakeven fee: 41.2 bps per side
- LOW STOPOUT: 14% -- entries have good geometric placement
