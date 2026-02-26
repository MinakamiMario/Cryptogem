# Sweep v1 -- sweep_v1_008_sv1b02_dclow_rsi35_vol2.0_sw0.5

- **Hypothesis**: WickSweep DClow RSI35 Vol2.0 Sweep0.5 (SV1-B02)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.7422, entries=944/944
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 185 |
| Win Rate | 50.3% |
| P&L | $-1,040.19 |
| PF | 0.69 |
| Max DD | 53.0% |
| EV/trade | $-5.62 |
| Class A share | 100% |
| Stopout ratio | 15% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 8 | $+116.66 | 6 |
| DC TARGET | 35 | $+455.57 | 28 |
| RSI RECOVERY | 81 | $+1,535.35 | 58 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-41.29 | 0 |
| FIXED STOP | 27 | $-2,014.47 | 0 |
| TIME MAX | 32 | $-1,092.01 | 1 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.69 (below 1.05)
- [FAIL] G2:MAX_DD: DD 53.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 15.1% trades, 8.7% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 62tr PF=0.66 [FAIL] | W2: 58tr PF=0.79 [FAIL] | W3: 64tr PF=0.67 [FAIL]
- [OK] S1:TRADE_FREQ: 185 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.62 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.69 < 0.90
- Best exit: RSI RECOVERY ($1535, 81 trades, 72% WR)
- Worst exit: FIXED STOP ($-2014, 27 trades)
- LOW STOPOUT: 15% -- entries have good geometric placement
