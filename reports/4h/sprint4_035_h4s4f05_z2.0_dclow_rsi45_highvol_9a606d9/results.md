# Sprint 4 -- sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol

- **Hypothesis**: Z-Score -2.0 DClow RSI45 HighVol (H4S4-F05)
- **Family**: Z-Score Extreme
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.72, entries=8455/8455

## Results
| Metric | Value |
|--------|-------|
| Trades | 206 |
| Win Rate | 49.5% |
| P&L | $+810.21 |
| PF | 1.16 |
| Max DD | 53.2% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+82.52 | 4 |
| DC TARGET | 36 | $+1,220.75 | 32 |
| RSI RECOVERY | 75 | $+4,397.32 | 65 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-22.99 | 1 |
| FIXED STOP | 40 | $-3,661.33 | 0 |
| TIME MAX | 48 | $-1,206.06 | 0 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.16 (PASS)
- [FAIL] G2:MAX_DD: DD 53.2% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 16.0% trades, 9.9% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 74tr PF=0.54 [FAIL] | W2: 64tr PF=1.10 [PASS] | W3: 67tr PF=1.74 [PASS]
- [OK] S1:TRADE_FREQ: 206 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $3.93 (positive)
