# Sweep v1 -- sweep_v1_011_sv1b05_dclow_rsi45_vol1.0_sw0.3

- **Hypothesis**: WickSweep DClow RSI45 Vol1.0 Sweep0.3 (SV1-B05)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6976, entries=7376/7376
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 245 |
| Win Rate | 54.7% |
| P&L | $-920.58 |
| PF | 0.82 |
| Max DD | 61.2% |
| EV/trade | $-3.76 |
| Class A share | 100% |
| Stopout ratio | 16% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 7 | $+780.41 | 7 |
| DC TARGET | 38 | $+1,027.17 | 33 |
| RSI RECOVERY | 112 | $+2,122.47 | 93 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-28.75 | 0 |
| FIXED STOP | 40 | $-3,321.83 | 0 |
| TIME MAX | 45 | $-1,500.05 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.82 (below 1.05)
- [FAIL] G2:MAX_DD: DD 61.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.3% trades, 3.8% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 83tr PF=0.86 [FAIL] | W2: 72tr PF=0.67 [FAIL] | W3: 88tr PF=0.86 [FAIL]
- [OK] S1:TRADE_FREQ: 245 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.76 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.82 < 0.90
- Best exit: RSI RECOVERY ($2122, 112 trades, 83% WR)
- Worst exit: FIXED STOP ($-3322, 40 trades)
- LOW STOPOUT: 16% -- entries have good geometric placement
