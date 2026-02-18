# MEXC Portability Report v2 — Config 041

**Date**: 2026-02-18
**Git**: `9a606d9`
**Dataset**: `ohlcv_4h_mexc_spot_usdt_v2` (439 coins)
**Universe**: `mexc_4h_v2_439`
**Config**: sprint4_041 (Vol Capitulation 3x BBlow RSI40, DC hybrid_notrl)

## Results Summary

| Metric | MEXC 10bps | MEXC 26bps | Kraken 26bps (ref) |
|--------|-----------|-----------|-------------------|
| Trades | 199 | 199 | 216 |
| PF | 0.97 | 0.91 | 1.41 |
| P&L | $-147 | $-501 | $+3,350 |
| WR | 53.3% | 50.8% | 54.6% |
| DD | 47.7% | 50.7% | 36.4% |
| EV/trade | $-0.74 | $-2.52 | $15.51 |
| Trades/day | 1.78 | 1.78 | 1.93 |
| Coins | 439 | 439 | 487 |

Full range (MEXC 10bps, 467d): PF=1.25, 636 trades, DD=92.2%

## V1 vs V2 Comparison

| Metric | V1 (145 coins) | V2 (439 coins) | Delta |
|--------|:-:|:-:|:-:|
| PF | 1.17 | 0.97 | -0.19 |
| Trades | 101 | 199 | +98 |
| DD | 51.5% | 47.7% | -3.8pp |
| Trades/day | 0.90 | 1.78 | +0.88 |

## Window Split (MEXC 10bps)

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| Early | 68 | 0.86 | $-288 |
| Mid | 64 | 1.67 | $+924 |
| Late | 67 | 0.67 | $-783 |

**1/3 profitable FAIL**

## Exit Attribution (MEXC 10bps)

| Exit | Class | Count | P&L | WR |
|------|-------|------:|----:|---:|
| RSI RECOVERY | A | 73 | $+3,494 | 84% |
| DC TARGET | A | 39 | $+1,549 | 92% |
| BB TARGET | A | 8 | $+373 | 100% |
| END | B | 3 | $-31 | 0% |
| TIME MAX | B | 36 | $-1,373 | 3% |
| FIXED STOP | B | 40 | $-4,158 | 0% |

## Bootstrap (MEXC 10bps)

- Resamples: 1000
- Median PF: 0.97
- P5 PF: 0.69
- P95 PF: 1.36
- % Profitable: 43.1%
- **FAIL**

## Fee Isolation

- PF diff (10bps vs 26bps): +0.0679
- P&L diff: $+354
- DD diff: -3.02pp
