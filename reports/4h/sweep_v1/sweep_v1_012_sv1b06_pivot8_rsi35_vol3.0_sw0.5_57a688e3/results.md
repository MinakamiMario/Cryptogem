# Sweep v1 -- sweep_v1_012_sv1b06_pivot8_rsi35_vol3.0_sw0.5

- **Hypothesis**: WickSweep Pivot8 RSI35 Vol3.0 Sweep0.5 (SV1-B06)
- **Family**: WickSweepReclaim
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Compat score**: avg=0.6656, entries=171/171
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 118 |
| Win Rate | 48.3% |
| P&L | $-1,225.40 |
| PF | 0.45 |
| Max DD | 62.0% |
| EV/trade | $-10.38 |
| Class A share | 100% |
| Stopout ratio | 17% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+54.30 | 3 |
| DC TARGET | 20 | $+127.44 | 15 |
| RSI RECOVERY | 51 | $+735.48 | 39 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 2 | $-42.77 | 0 |
| FIXED STOP | 20 | $-1,438.56 | 0 |
| TIME MAX | 21 | $-661.30 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.45 (below 1.05)
- [FAIL] G2:MAX_DD: DD 62.0% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 17.8% trades, 26.3% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 40tr PF=0.32 [FAIL] | W2: 35tr PF=1.18 [PASS] | W3: 42tr PF=0.36 [FAIL]
- [OK] S1:TRADE_FREQ: 118 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-10.38 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.45 < 0.90
- Best exit: RSI RECOVERY ($735, 51 trades, 76% WR)
- Worst exit: FIXED STOP ($-1439, 20 trades)
- LOW STOPOUT: 17% -- entries have good geometric placement
