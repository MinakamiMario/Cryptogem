# Sweep v1 -- sweep_v1_003_sv1a03_rsi45_p5_atr2.0

- **Hypothesis**: SwingFractal RSI45 Pivot5 ATR2.0 (SV1-A03)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5061, entries=23624/23624
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 308 |
| Win Rate | 56.8% |
| P&L | $-171.42 |
| PF | 1.06 |
| Max DD | 55.3% |
| EV/trade | $-0.56 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 36 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 13 | $+471.02 | 12 |
| DC TARGET | 24 | $+1,035.70 | 20 |
| RSI RECOVERY | 189 | $+6,574.36 | 141 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-138.18 | 1 |
| FIXED STOP | 40 | $-5,115.88 | 0 |
| TIME MAX | 39 | $-2,308.06 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [PASS] G1:PF: PF 1.06 (PASS)
- [FAIL] G2:MAX_DD: DD 55.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.0% trades, 5.4% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 103tr PF=0.86 [FAIL] | W2: 99tr PF=2.67 [PASS] | W3: 105tr PF=0.58 [FAIL]
- [OK] S1:TRADE_FREQ: 308 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-0.56 (negative or zero)

## Research Notes
- STRONG LEAD: PF=1.06, Class A share=100%, stopout ratio=13%
- Best exit: RSI RECOVERY ($6574, 189 trades, 75% WR)
- Worst exit: FIXED STOP ($-5116, 40 trades)
- Breakeven fee: 36.3 bps per side
- LOW STOPOUT: 13% -- entries have good geometric placement
