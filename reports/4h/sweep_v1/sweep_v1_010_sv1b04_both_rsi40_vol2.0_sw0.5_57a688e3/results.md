# Sweep v1 -- sweep_v1_010_sv1b04_both_rsi40_vol2.0_sw0.5

- **Hypothesis**: WickSweep Both RSI40 Vol2.0 Sweep0.5 (SV1-B04)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Compat score**: avg=0.611, entries=600/600
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 210 |
| Win Rate | 48.6% |
| P&L | $-1,217.13 |
| PF | 0.59 |
| Max DD | 61.0% |
| EV/trade | $-5.80 |
| Class A share | 100% |
| Stopout ratio | 10% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 7 | $+55.16 | 5 |
| DC TARGET | 33 | $+330.25 | 25 |
| RSI RECOVERY | 116 | $+1,138.03 | 72 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-50.73 | 0 |
| FIXED STOP | 20 | $-1,363.77 | 0 |
| TIME MAX | 31 | $-1,326.07 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.59 (below 1.05)
- [FAIL] G2:MAX_DD: DD 61.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.3% trades, 6.9% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 64tr PF=0.60 [FAIL] | W2: 75tr PF=0.83 [FAIL] | W3: 70tr PF=0.43 [FAIL]
- [OK] S1:TRADE_FREQ: 210 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.80 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.59 < 0.90
- Best exit: RSI RECOVERY ($1138, 116 trades, 62% WR)
- Worst exit: FIXED STOP ($-1364, 20 trades)
- LOW STOPOUT: 10% -- entries have good geometric placement
