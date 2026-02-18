# Sprint 4 -- sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5

- **Hypothesis**: DC-Lite DClow+BBlow RSI40 VolSpike1.5 (H4S4-A07)
- **Family**: DC-Lite
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.2s
- **Market context**: Yes (momentum rank + breadth)
- **Compat score**: avg=0.7385, entries=344/344

## Results
| Metric | Value |
|--------|-------|
| Trades | 101 |
| Win Rate | 54.5% |
| P&L | $+537.94 |
| PF | 1.25 |
| Max DD | 40.8% |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 4 | $+29.00 | 3 |
| DC TARGET | 12 | $+508.72 | 12 |
| RSI RECOVERY | 48 | $+2,028.27 | 38 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 1 | $+16.62 | 1 |
| FIXED STOP | 17 | $-1,485.57 | 0 |
| TIME MAX | 19 | $-559.11 | 1 |

## Gates (Stage 0 -- relaxed PF > 1.05)
**Verdict: NO-GO** (3/4 hard gates)

- [PASS] G1:PF: PF 1.25 (PASS)
- [FAIL] G2:MAX_DD: DD 40.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 14.9% trades, 3.7% P&L (PASS)
- [PASS] G4:WINDOW_SPLIT: W1: 36tr PF=0.47 [FAIL] | W2: 32tr PF=1.69 [PASS] | W3: 32tr PF=2.04 [PASS]
- [OK] S1:TRADE_FREQ: 101 trades (meets target)
- [OK] S2:EV_TRADE: EV/trade $5.33 (positive)
