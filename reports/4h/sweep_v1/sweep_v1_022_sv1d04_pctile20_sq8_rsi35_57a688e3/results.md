# Sweep v1 -- sweep_v1_022_sv1d04_pctile20_sq8_rsi35

- **Hypothesis**: ATRExhaust Pctile20 Squeeze8 RSI35 (SV1-D04)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5415, entries=1455/1455
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 197 |
| Win Rate | 47.2% |
| P&L | $-1,657.33 |
| PF | 0.52 |
| Max DD | 84.8% |
| EV/trade | $-8.41 |
| Class A share | 100% |
| Stopout ratio | 15% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 8 | $+74.77 | 8 |
| DC TARGET | 31 | $+154.76 | 21 |
| RSI RECOVERY | 80 | $+1,052.07 | 61 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+3.90 | 2 |
| FIXED STOP | 29 | $-1,499.78 | 0 |
| TIME MAX | 46 | $-1,087.38 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.52 (below 1.05)
- [FAIL] G2:MAX_DD: DD 84.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 15.2% trades, 2.4% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 65tr PF=0.43 [FAIL] | W2: 66tr PF=0.78 [FAIL] | W3: 65tr PF=0.42 [FAIL]
- [OK] S1:TRADE_FREQ: 197 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-8.41 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.52 < 0.90
- Best exit: RSI RECOVERY ($1052, 80 trades, 76% WR)
- Worst exit: FIXED STOP ($-1500, 29 trades)
- LOW STOPOUT: 15% -- entries have good geometric placement
