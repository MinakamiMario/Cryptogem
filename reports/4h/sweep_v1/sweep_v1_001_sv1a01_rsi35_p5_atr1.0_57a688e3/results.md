# Sweep v1 -- sweep_v1_001_sv1a01_rsi35_p5_atr1.0

- **Hypothesis**: SwingFractal RSI35 Pivot5 ATR1.0 (SV1-A01)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6112, entries=7285/7285
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 284 |
| Win Rate | 56.3% |
| P&L | $-1,186.11 |
| PF | 0.83 |
| Max DD | 67.3% |
| EV/trade | $-4.18 |
| Class A share | 100% |
| Stopout ratio | 14% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 10 | $+260.95 | 9 |
| DC TARGET | 26 | $+388.32 | 22 |
| RSI RECOVERY | 165 | $+2,645.04 | 126 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-55.55 | 1 |
| FIXED STOP | 39 | $-3,005.04 | 0 |
| TIME MAX | 41 | $-992.54 | 2 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.83 (below 1.05)
- [FAIL] G2:MAX_DD: DD 67.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.0% trades, 3.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 98tr PF=0.69 [FAIL] | W2: 92tr PF=1.40 [PASS] | W3: 93tr PF=0.77 [FAIL]
- [OK] S1:TRADE_FREQ: 284 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-4.18 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.83 < 0.90
- Best exit: RSI RECOVERY ($2645, 165 trades, 76% WR)
- Worst exit: FIXED STOP ($-3005, 39 trades)
- LOW STOPOUT: 14% -- entries have good geometric placement
