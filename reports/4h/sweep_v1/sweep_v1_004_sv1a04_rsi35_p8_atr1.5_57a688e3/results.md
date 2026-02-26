# Sweep v1 -- sweep_v1_004_sv1a04_rsi35_p8_atr1.5

- **Hypothesis**: SwingFractal RSI35 Pivot8 ATR1.5 (SV1-A04)
- **Family**: SwingFractalBounce
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6014, entries=7178/7178
- **Research grade**: STRONG_LEAD

## Results
| Metric | Value |
|--------|-------|
| Trades | 286 |
| Win Rate | 55.9% |
| P&L | $-685.19 |
| PF | 1.01 |
| Max DD | 68.7% |
| EV/trade | $-2.40 |
| Class A share | 100% |
| Stopout ratio | 12% |
| Breakeven fee | 28 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 11 | $+491.52 | 10 |
| DC TARGET | 32 | $+934.86 | 25 |
| RSI RECOVERY | 156 | $+4,688.24 | 121 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-8.85 | 0 |
| FIXED STOP | 35 | $-3,910.10 | 0 |
| TIME MAX | 50 | $-2,117.43 | 4 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 1.01 (below 1.05)
- [FAIL] G2:MAX_DD: DD 68.7% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.9% trades, 5.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 93tr PF=1.08 [PASS] | W2: 97tr PF=1.03 [FAIL] | W3: 95tr PF=0.90 [FAIL]
- [OK] S1:TRADE_FREQ: 286 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-2.40 (negative or zero)

## Research Notes
- STRONG LEAD: PF=1.01, Class A share=100%, stopout ratio=12%
- Best exit: RSI RECOVERY ($4688, 156 trades, 78% WR)
- Worst exit: FIXED STOP ($-3910, 35 trades)
- Breakeven fee: 27.9 bps per side
- TIGHT: barely profitable at Kraken fees, consider MEXC (10 bps)
- LOW STOPOUT: 12% -- entries have good geometric placement
