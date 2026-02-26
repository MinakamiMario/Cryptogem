# Sweep v1 -- sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh

- **Hypothesis**: SwingFractal RSI40 Pivot8 ATR1.0 VolHigh (SV1-A05)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5998, entries=4926/4926
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 313 |
| Win Rate | 53.4% |
| P&L | $+2,847.68 |
| PF | 1.24 |
| Max DD | 41.9% |
| EV/trade | $+9.10 |
| Class A share | 100% |
| Stopout ratio | 14% |
| Breakeven fee | 50 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 19 | $+1,857.97 | 16 |
| DC TARGET | 33 | $+2,324.80 | 31 |
| RSI RECOVERY | 175 | $+9,813.68 | 120 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-14.43 | 0 |
| FIXED STOP | 43 | $-7,942.14 | 0 |
| TIME MAX | 41 | $-3,192.20 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (2/4 hard gates)

- [PASS] G1:PF: PF 1.24 (PASS)
- [FAIL] G2:MAX_DD: DD 41.9% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 12.5% trades, 10.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 109tr PF=0.90 [FAIL] | W2: 96tr PF=2.59 [PASS] | W3: 105tr PF=0.88 [FAIL]
- [OK] S1:TRADE_FREQ: 313 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $9.10 (positive)

## Research Notes
- STRONG LEAD: PF=1.24, Class A share=100%, stopout ratio=14%
- Best exit: RSI RECOVERY ($9814, 175 trades, 69% WR)
- Worst exit: FIXED STOP ($-7942, 43 trades)
- Breakeven fee: 50.0 bps per side
- LOW STOPOUT: 14% -- entries have good geometric placement
