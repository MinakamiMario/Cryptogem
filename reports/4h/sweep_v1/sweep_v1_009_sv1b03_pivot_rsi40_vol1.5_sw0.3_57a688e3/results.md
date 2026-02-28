# Sweep v1 -- sweep_v1_009_sv1b03_pivot_rsi40_vol1.5_sw0.3

- **Hypothesis**: WickSweep Pivot RSI40 Vol1.5 Sweep0.3 (SV1-B03)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.6326, entries=4047/4047
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 277 |
| Win Rate | 55.2% |
| P&L | $-992.30 |
| PF | 0.78 |
| Max DD | 58.0% |
| EV/trade | $-3.58 |
| Class A share | 100% |
| Stopout ratio | 15% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 11 | $+267.05 | 8 |
| DC TARGET | 57 | $+1,120.18 | 46 |
| RSI RECOVERY | 127 | $+1,801.01 | 97 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-12.68 | 1 |
| FIXED STOP | 41 | $-3,140.67 | 0 |
| TIME MAX | 39 | $-1,027.19 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.78 (below 1.05)
- [FAIL] G2:MAX_DD: DD 58.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.0% trades, 3.0% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 100tr PF=0.80 [FAIL] | W2: 82tr PF=0.60 [FAIL] | W3: 94tr PF=0.92 [FAIL]
- [OK] S1:TRADE_FREQ: 277 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-3.58 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.78 < 0.90
- Best exit: RSI RECOVERY ($1801, 127 trades, 76% WR)
- Worst exit: FIXED STOP ($-3141, 41 trades)
- LOW STOPOUT: 15% -- entries have good geometric placement
