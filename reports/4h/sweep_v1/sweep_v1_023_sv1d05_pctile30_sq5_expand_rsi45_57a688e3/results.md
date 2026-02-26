# Sweep v1 -- sweep_v1_023_sv1d05_pctile30_sq5_expand_rsi45

- **Hypothesis**: ATRExhaust Pctile30 Squeeze5 Expand RSI45 (SV1-D05)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.4891, entries=3436/3436
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 261 |
| Win Rate | 55.9% |
| P&L | $-1,460.32 |
| PF | 0.78 |
| Max DD | 83.1% |
| EV/trade | $-5.60 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 18 | $+319.09 | 18 |
| DC TARGET | 43 | $+1,914.81 | 37 |
| RSI RECOVERY | 116 | $+1,494.32 | 91 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-24.24 | 0 |
| FIXED STOP | 35 | $-2,889.15 | 0 |
| TIME MAX | 46 | $-1,889.62 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.78 (below 1.05)
- [FAIL] G2:MAX_DD: DD 83.1% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 11.9% trades, 10.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 84tr PF=0.87 [FAIL] | W2: 89tr PF=0.79 [FAIL] | W3: 87tr PF=0.54 [FAIL]
- [OK] S1:TRADE_FREQ: 261 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.60 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.78 < 0.90
- Best exit: DC TARGET ($1915, 43 trades, 86% WR)
- Worst exit: FIXED STOP ($-2889, 35 trades)
- LOW STOPOUT: 13% -- entries have good geometric placement
