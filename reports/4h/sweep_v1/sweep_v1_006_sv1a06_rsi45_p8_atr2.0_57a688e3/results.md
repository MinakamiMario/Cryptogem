# Sweep v1 -- sweep_v1_006_sv1a06_rsi45_p8_atr2.0

- **Hypothesis**: SwingFractal RSI45 Pivot8 ATR2.0 (SV1-A06)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5106, entries=19669/19669
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 347 |
| Win Rate | 58.8% |
| P&L | $+3,425.19 |
| PF | 1.52 |
| Max DD | 63.1% |
| EV/trade | $+9.87 |
| Class A share | 100% |
| Stopout ratio | 10% |
| Breakeven fee | 50 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 20 | $+1,596.82 | 18 |
| DC TARGET | 26 | $+2,459.12 | 23 |
| RSI RECOVERY | 218 | $+12,759.71 | 162 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-21.94 | 0 |
| FIXED STOP | 36 | $-6,961.38 | 0 |
| TIME MAX | 44 | $-3,798.79 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.52 (PASS)
- [FAIL] G2:MAX_DD: DD 63.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.4% trades, 7.1% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 114tr PF=0.75 [FAIL] | W2: 117tr PF=4.34 [PASS] | W3: 114tr PF=1.13 [PASS]
- [OK] S1:TRADE_FREQ: 347 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $9.87 (positive)

## Research Notes
- STRONG LEAD: PF=1.52, Class A share=100%, stopout ratio=10%
- Best exit: RSI RECOVERY ($12760, 218 trades, 74% WR)
- Worst exit: FIXED STOP ($-6961, 36 trades)
- Breakeven fee: 50.0 bps per side
- LOW STOPOUT: 10% -- entries have good geometric placement
