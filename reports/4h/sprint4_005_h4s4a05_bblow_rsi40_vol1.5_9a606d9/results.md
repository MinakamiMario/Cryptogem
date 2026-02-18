# Sprint 4 -- sprint4_005_h4s4a05_bblow_rsi40_vol1.5

- **Hypothesis**: DC-Lite BBlow RSI40 VolSpike1.5 (H4S4-A05)
- **Family**: DC-Lite
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7085, entries=725/725

## Results
| Metric | Value |
|--------|-------|
| Trades | 155 |
| Win Rate | 50.3% |
| P&L | $+257.40 |
| PF | 1.07 |
| Max DD | 46.8% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 5 | $+519.92 | 4 |
| DC TARGET | 27 | $+1,217.66 | 27 |
| RSI RECOVERY | 60 | $+2,193.68 | 45 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+13.55 | 1 |
| FIXED STOP | 35 | $-2,878.99 | 0 |
| TIME MAX | 27 | $-808.42 | 1 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.07 (PASS)
- [FAIL] G2:MAX_DD: DD 46.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.5% trades, 9.7% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 50tr PF=0.71 [FAIL] | W2: 50tr PF=0.72 [FAIL] | W3: 53tr PF=1.54 [PASS]
- [OK] S1:TRADE_FREQ: 155 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $1.66 (positive)
