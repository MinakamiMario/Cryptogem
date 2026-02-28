# Sweep v1 -- sweep_v1_021_sv1d03_pctile40_sq3_expand

- **Hypothesis**: ATRExhaust Pctile40 Squeeze3 Expand (SV1-D03)
- **Family**: ATRExhaustion
- **Category**: mean_reversion
- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526 (487 coins)
- **Elapsed**: 0.1s
- **Compat score**: avg=0.5215, entries=3298/3298
- **Research grade**: NEGATIVE

## Results
| Metric | Value |
|--------|-------|
| Trades | 243 |
| Win Rate | 53.5% |
| P&L | $-1,289.71 |
| PF | 0.72 |
| Max DD | 79.8% |
| EV/trade | $-5.31 |
| Class A share | 100% |
| Stopout ratio | 14% |
| Breakeven fee | 0 bps |

## Exit Classes
### Class A (smart)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| BB TARGET | 12 | $+188.82 | 12 |
| DC TARGET | 39 | $+595.79 | 30 |
| RSI RECOVERY | 111 | $+1,660.58 | 88 |

### Class B (mechanical)
| Reason | Count | P&L | Wins |
|--------|-------|-----|------|
| END | 3 | $-39.46 | 0 |
| FIXED STOP | 33 | $-2,130.94 | 0 |
| TIME MAX | 45 | $-1,292.24 | 0 |

## Gates (Sweep v1 -- PF > 1.05)
**Verdict: NO-GO** (1/4 hard gates)

- [FAIL] G1:PF: PF 0.72 (below 1.05)
- [FAIL] G2:MAX_DD: DD 79.8% (exceeds 25.0%)
- [PASS] G3:TOP10_CONC: Top10: 13.2% trades, 10.5% P&L (PASS)
- [FAIL] G4:WINDOW_SPLIT: W1: 85tr PF=0.57 [FAIL] | W2: 76tr PF=0.83 [FAIL] | W3: 81tr PF=0.94 [FAIL]
- [OK] S1:TRADE_FREQ: 243 trades (meets target)
- [LOW] S2:EV_TRADE: EV/trade $-5.31 (negative or zero)

## Research Notes
- NEGATIVE: PF=0.72 < 0.90
- Best exit: RSI RECOVERY ($1661, 111 trades, 79% WR)
- Worst exit: FIXED STOP ($-2131, 33 trades)
- LOW STOPOUT: 14% -- entries have good geometric placement
