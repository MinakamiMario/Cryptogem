# Sweep v1 -- sweep_v1_024_sv1d06_pctile30_sq3_volhigh

- **Hypothesis**: ATRExhaust Pctile30 Squeeze3 VolHigh (SV1-D06)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5289, entries=2472/2472
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 248 |
| Win Rate | 54.0% |
| P&L | $-1,655.64 |
| PF | 0.70 |
| Max DD | 84.3% |
| EV/trade | $-6.68 |
| Class A share | 100% |
| Stopout ratio | 13% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 11 | $+113.49 | 11 |
| DC TARGET | 39 | $+446.97 | 31 |
| RSI RECOVERY | 123 | $+1,405.92 | 91 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-2.83 | 1 |
| FIXED STOP | 32 | $-1,898.74 | 0 |
| TIME MAX | 40 | $-1,029.54 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.70 (below 1.05)
- [FAIL] G2:MAX_DD: DD 84.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.7% trades, 7.6% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 88tr PF=0.54 [FAIL] | W2: 80tr PF=1.09 [PASS] | W3: 79tr PF=0.58 [FAIL]
- [OK] S1:TRADE_FREQ: 248 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-6.68 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.70 < 0.90
- Best exit: RSI RECOVERY ($1406, 123 trades, 74% WR)
- Worst exit: FIXED STOP ($-1899, 32 trades)
- LOW STOPOUT: 13% -- entries have good geometric placement
