# Sweep v1 -- sweep_v1_029_sv1e05_pctile20_gap5_volhigh

- **Hypothesis**: CrossRSI Pctile20 Gap5 VolHigh (SV1-E05)
- **Family**: CrossRSIExtreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6809, entries=10952/10952
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 203 |
| Win Rate | 41.4% |
| P&L | $-1,612.92 |
| PF | 0.49 |
| Max DD | 80.8% |
| EV/trade | $-7.95 |
| Class A share | 100% |
| Stopout ratio | 21% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 6 | $+32.55 | 5 |
| DC TARGET | 16 | $+465.39 | 13 |
| RSI RECOVERY | 76 | $+957.52 | 63 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-13.11 | 1 |
| FIXED STOP | 43 | $-1,973.73 | 0 |
| TIME MAX | 59 | $-1,081.53 | 2 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.49 (below 1.05)
- [FAIL] G2:MAX_DD: DD 80.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 22.2% trades, 17.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 70tr PF=0.41 [FAIL] | W2: 66tr PF=0.57 [FAIL] | W3: 65tr PF=0.85 [FAIL]
- [OK] S1:TRADE_FREQ: 203 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.95 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.49 < 0.90
- Best exit: RSI RECOVERY ($958, 76 trades, 83% WR)
- Worst exit: FIXED STOP ($-1974, 43 trades)
