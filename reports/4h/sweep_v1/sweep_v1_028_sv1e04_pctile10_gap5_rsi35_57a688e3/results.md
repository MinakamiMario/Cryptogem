# Sweep v1 -- sweep_v1_028_sv1e04_pctile10_gap5_rsi35

- **Hypothesis**: CrossRSI Pctile10 Gap5 RSI35 (SV1-E04)
- **Family**: CrossRSIExtreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6916, entries=10162/10162
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 202 |
| Win Rate | 42.1% |
| P&L | $-1,602.37 |
| PF | 0.61 |
| Max DD | 81.3% |
| EV/trade | $-7.93 |
| Class A share | 100% |
| Stopout ratio | 20% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+29.34 | 2 |
| DC TARGET | 23 | $+808.12 | 22 |
| RSI RECOVERY | 73 | $+1,289.95 | 58 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $+7.85 | 2 |
| FIXED STOP | 40 | $-2,183.27 | 0 |
| TIME MAX | 59 | $-1,333.09 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.61 (below 1.05)
- [FAIL] G2:MAX_DD: DD 81.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.8% trades, 15.2% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 70tr PF=0.50 [FAIL] | W2: 64tr PF=0.80 [FAIL] | W3: 67tr PF=0.77 [FAIL]
- [OK] S1:TRADE_FREQ: 202 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-7.93 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.61 < 0.90
- Best exit: RSI RECOVERY ($1290, 73 trades, 80% WR)
- Worst exit: FIXED STOP ($-2183, 40 trades)
- LOW STOPOUT: 20% -- entries have good geometric placement
