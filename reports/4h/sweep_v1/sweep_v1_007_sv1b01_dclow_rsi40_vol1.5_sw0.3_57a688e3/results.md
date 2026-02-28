# Sweep v1 -- sweep_v1_007_sv1b01_dclow_rsi40_vol1.5_sw0.3

- **Hypothesis**: WickSweep DClow RSI40 Vol1.5 Sweep0.3 (SV1-B01)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.7294, entries=5180/5180
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 231 |
| Win Rate | 54.5% |
| P&L | $-803.31 |
| PF | 0.86 |
| Max DD | 63.3% |
| EV/trade | $-3.48 |
| Class A share | 100% |
| Stopout ratio | 16% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 6 | $+493.51 | 6 |
| DC TARGET | 44 | $+1,066.76 | 38 |
| RSI RECOVERY | 92 | $+3,125.24 | 79 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-13.85 | 1 |
| FIXED STOP | 38 | $-3,871.25 | 0 |
| TIME MAX | 48 | $-1,603.71 | 2 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.86 (below 1.05)
- [FAIL] G2:MAX_DD: DD 63.3% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.7% trades, 3.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 85tr PF=0.94 [FAIL] | W2: 67tr PF=0.86 [FAIL] | W3: 78tr PF=0.72 [FAIL]
- [OK] S1:TRADE_FREQ: 231 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.48 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.86 < 0.90
- Best exit: RSI RECOVERY ($3125, 92 trades, 86% WR)
- Worst exit: FIXED STOP ($-3871, 38 trades)
- LOW STOPOUT: 16% -- entries have good geometric placement
