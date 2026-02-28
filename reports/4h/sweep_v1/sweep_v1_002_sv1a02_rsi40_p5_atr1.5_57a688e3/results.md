# Sweep v1 -- sweep_v1_002_sv1a02_rsi40_p5_atr1.5

- **Hypothesis**: SwingFractal RSI40 Pivot5 ATR1.5 (SV1-A02)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5564, entries=14458/14458
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 306 |
| Win Rate | 57.8% |
| P&L | $+744.52 |
| PF | 1.35 |
| Max DD | 56.8% |
| EV/trade | $+2.43 |
| Class A share | 100% |
| Stopout ratio | 11% |
| Breakeven fee | 50 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 13 | $+873.37 | 13 |
| DC TARGET | 22 | $+732.49 | 17 |
| RSI RECOVERY | 197 | $+8,927.41 | 147 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-116.68 | 0 |
| FIXED STOP | 34 | $-4,623.17 | 0 |
| TIME MAX | 38 | $-2,851.31 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [PASS] G1:PF: PF 1.35 (PASS)
- [FAIL] G2:MAX_DD: DD 56.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.1% trades, 5.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 103tr PF=0.88 [FAIL] | W2: 100tr PF=3.08 [PASS] | W3: 102tr PF=0.96 [FAIL]
- [OK] S1:TRADE_FREQ: 306 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $2.43 (positive)

## Research Notes
- STRONG LEAD: PF=1.35, Class A share=100%, stopout ratio=11%
- Best exit: RSI RECOVERY ($8927, 197 trades, 75% WR)
- Worst exit: FIXED STOP ($-4623, 34 trades)
- Breakeven fee: 50.0 bps per side
- LOW STOPOUT: 11% -- entries have good geometric placement
