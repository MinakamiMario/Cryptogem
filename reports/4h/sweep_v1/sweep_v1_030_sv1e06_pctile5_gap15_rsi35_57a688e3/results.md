# Sweep v1 -- sweep_v1_030_sv1e06_pctile5_gap15_rsi35

- **Hypothesis**: CrossRSI Pctile5 Gap15 RSI35 (SV1-E06)
- **Family**: CrossRSIExtreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.7177, entries=4924/4924
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 205 |
| Win Rate | 42.9% |
| P&L | $-1,460.63 |
| PF | 0.69 |
| Max DD | 75.0% |
| EV/trade | $-7.13 |
| Class A share | 99% |
| Stopout ratio | 19% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+58.75 | 3 |
| DC TARGET | 24 | $+843.34 | 21 |
| RSI RECOVERY | 82 | $+1,587.85 | 61 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+15.77 | 2 |
| FIXED STOP | 38 | $-2,281.88 | 0 |
| TIME MAX | 54 | $-1,382.60 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.69 (below 1.05)
- [FAIL] G2:MAX_DD: DD 75.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 20.0% trades, 14.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 70tr PF=0.50 [FAIL] | W2: 67tr PF=1.21 [PASS] | W3: 67tr PF=0.73 [FAIL]
- [OK] S1:TRADE_FREQ: 205 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.13 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.69 < 0.90
- Best exit: RSI RECOVERY ($1588, 82 trades, 74% WR)
- Worst exit: FIXED STOP ($-2282, 38 trades)
- LOW STOPOUT: 19% -- entries have good geometric placement
