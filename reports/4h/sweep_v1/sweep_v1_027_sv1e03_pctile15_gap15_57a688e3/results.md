# Sweep v1 -- sweep_v1_027_sv1e03_pctile15_gap15

- **Hypothesis**: CrossRSI Pctile15 Gap15 (SV1-E03)
- **Family**: CrossRSIExtreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6548, entries=12128/12128
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 202 |
| Win Rate | 41.6% |
| P&L | $-1,589.69 |
| PF | 0.62 |
| Max DD | 81.5% |
| EV/trade | $-7.87 |
| Class A share | 100% |
| Stopout ratio | 19% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+29.42 | 2 |
| DC TARGET | 22 | $+799.77 | 21 |
| RSI RECOVERY | 75 | $+1,298.46 | 59 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-1.92 | 1 |
| FIXED STOP | 39 | $-2,161.48 | 0 |
| TIME MAX | 59 | $-1,332.66 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.62 (below 1.05)
- [FAIL] G2:MAX_DD: DD 81.5% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.8% trades, 15.1% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 70tr PF=0.50 [FAIL] | W2: 64tr PF=0.80 [FAIL] | W3: 66tr PF=0.79 [FAIL]
- [OK] S1:TRADE_FREQ: 202 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.87 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.62 < 0.90
- Best exit: RSI RECOVERY ($1298, 75 trades, 79% WR)
- Worst exit: FIXED STOP ($-2161, 39 trades)
- LOW STOPOUT: 19% -- entries have good geometric placement
