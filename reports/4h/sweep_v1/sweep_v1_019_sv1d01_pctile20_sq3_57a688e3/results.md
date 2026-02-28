# Sweep v1 -- sweep_v1_019_sv1d01_pctile20_sq3

- **Hypothesis**: ATRExhaust Pctile20 Squeeze3 (SV1-D01)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.4987, entries=4043/4043
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 253 |
| Win Rate | 50.2% |
| P&L | $-1,800.50 |
| PF | 0.56 |
| Max DD | 91.2% |
| EV/trade | $-7.12 |
| Class A share | 100% |
| Stopout ratio | 11% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 14 | $+81.21 | 11 |
| DC TARGET | 37 | $+270.09 | 28 |
| RSI RECOVERY | 117 | $+1,232.76 | 87 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-7.61 | 1 |
| FIXED STOP | 28 | $-1,718.18 | 0 |
| TIME MAX | 54 | $-1,225.06 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.56 (below 1.05)
- [FAIL] G2:MAX_DD: DD 91.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.2% trades, 10.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 90tr PF=0.56 [FAIL] | W2: 83tr PF=0.66 [FAIL] | W3: 79tr PF=0.39 [FAIL]
- [OK] S1:TRADE_FREQ: 253 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.12 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.56 < 0.90
- Best exit: RSI RECOVERY ($1233, 117 trades, 74% WR)
- Worst exit: FIXED STOP ($-1718, 28 trades)
- LOW STOPOUT: 11% -- entries have good geometric placement
