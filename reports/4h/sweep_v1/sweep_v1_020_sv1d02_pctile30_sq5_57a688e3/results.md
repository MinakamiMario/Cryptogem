# Sweep v1 -- sweep_v1_020_sv1d02_pctile30_sq5

- **Hypothesis**: ATRExhaust Pctile30 Squeeze5 (SV1-D02)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.4982, entries=4095/4095
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 263 |
| Win Rate | 52.1% |
| P&L | $-1,743.54 |
| PF | 0.62 |
| Max DD | 88.2% |
| EV/trade | $-6.63 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 16 | $+152.66 | 13 |
| DC TARGET | 42 | $+418.33 | 34 |
| RSI RECOVERY | 119 | $+1,284.49 | 90 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-8.87 | 0 |
| FIXED STOP | 33 | $-1,936.46 | 0 |
| TIME MAX | 50 | $-1,139.04 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.62 (below 1.05)
- [FAIL] G2:MAX_DD: DD 88.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.3% trades, 16.7% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 90tr PF=0.53 [FAIL] | W2: 87tr PF=0.88 [FAIL] | W3: 85tr PF=0.52 [FAIL]
- [OK] S1:TRADE_FREQ: 263 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.63 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.62 < 0.90
- Best exit: RSI RECOVERY ($1284, 119 trades, 76% WR)
- Worst exit: FIXED STOP ($-1936, 33 trades)
- LOW STOPOUT: 13% -- entries have good geometric placement
