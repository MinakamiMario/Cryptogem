# MEXC v2 Top-200 Experiments — Config 041

**Date**: 2026-02-18
**Git**: `9a606d9`
**Dataset**: `ohlcv_4h_mexc_spot_usdt_v2`
**Universe**: Top 200 by median volume, ≥2160 bars (200 coins)
**Fair slicing**: end_bar=721
**Fee**: MEXC 10bps

## Comparison Matrix

| Config | vol | rsi | Trades | PF | P&L | WR | DD | EV/t | Win/3 | Boot%Prof |
|--------|----:|----:|-------:|---:|----:|---:|---:|-----:|------:|----------:|
| Baseline 041 on top-200 | 3.0 | 40 | 140 | 1.08 | $+299 | 55.7% | 37.5% | $2.14 | 1/3 | 61.8% |
| Stricter vol (3.5x) on top-200 | 3.5 | 40 | 124 | 1.15 | $+647 | 53.2% | 32.8% | $5.22 | 1/3 | 70.7% |
| Stricter vol (4.0x) on top-200 | 4.0 | 40 | 109 | 1.19 | $+726 | 52.3% | 34.6% | $6.66 | 1/3 | 72.2% |
| Strict vol (3.5x) + RSI 35 on top-200 | 3.5 | 35 | 113 | 1.18 | $+727 | 52.2% | 31.3% | $6.44 | 1/3 | 70.7% |
| **Kraken ref (487 coins)** | 3.0 | 40 | 216 | 1.41 | $+3,350 | 54.6% | 36.4% | $15.51 | — | — |
| **MEXC v2 full (439 coins)** | 3.0 | 40 | 199 | 0.97 | $-147 | 53.3% | 47.7% | $-0.74 | 1/3 | 43.1% |

## Baseline 041 on top-200

### Exit Attribution

| Exit | Class | Count | P&L | WR |
|------|-------|------:|----:|---:|
| RSI RECOVERY | A | 47 | $+2,311 | 83% |
| DC TARGET | A | 41 | $+1,822 | 93% |
| BB TARGET | A | 1 | $+21 | 100% |
| TIME MAX | B | 21 | $-880 | 0% |
| FIXED STOP | B | 30 | $-2,976 | 0% |

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| Early | 50 | 0.68 | $-463 |
| Mid | 46 | 1.81 | $+971 |
| Late | 44 | 0.84 | $-210 |

**1/3 FAIL**

### Bootstrap

- P5 PF: 0.72
- Median PF: 1.08
- % Profitable: 61.8%
- **FAIL**

## Stricter vol (3.5x) on top-200

### Exit Attribution

| Exit | Class | Count | P&L | WR |
|------|-------|------:|----:|---:|
| RSI RECOVERY | A | 41 | $+2,693 | 80% |
| DC TARGET | A | 36 | $+2,039 | 89% |
| BB TARGET | A | 1 | $+27 | 100% |
| TIME MAX | B | 20 | $-813 | 0% |
| FIXED STOP | B | 26 | $-3,300 | 0% |

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| Early | 46 | 0.95 | $-73 |
| Mid | 40 | 2.23 | $+1,427 |
| Late | 38 | 0.60 | $-707 |

**1/3 FAIL**

### Bootstrap

- P5 PF: 0.76
- Median PF: 1.15
- % Profitable: 70.7%
- **FAIL**

## Stricter vol (4.0x) on top-200

### Exit Attribution

| Exit | Class | Count | P&L | WR |
|------|-------|------:|----:|---:|
| RSI RECOVERY | A | 35 | $+2,623 | 83% |
| DC TARGET | A | 31 | $+1,866 | 87% |
| BB TARGET | A | 1 | $+28 | 100% |
| TIME MAX | B | 19 | $-746 | 0% |
| FIXED STOP | B | 23 | $-3,045 | 0% |

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| Early | 40 | 0.96 | $-43 |
| Mid | 36 | 2.46 | $+1,526 |
| Late | 33 | 0.55 | $-757 |

**1/3 FAIL**

### Bootstrap

- P5 PF: 0.75
- Median PF: 1.18
- % Profitable: 72.2%
- **FAIL**

## Strict vol (3.5x) + RSI 35 on top-200

### Exit Attribution

| Exit | Class | Count | P&L | WR |
|------|-------|------:|----:|---:|
| RSI RECOVERY | A | 35 | $+2,566 | 80% |
| DC TARGET | A | 36 | $+1,991 | 86% |
| TIME MAX | B | 19 | $-786 | 0% |
| FIXED STOP | B | 23 | $-3,043 | 0% |

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| Early | 43 | 0.97 | $-35 |
| Mid | 39 | 2.24 | $+1,490 |
| Late | 31 | 0.55 | $-727 |

**1/3 FAIL**

### Bootstrap

- P5 PF: 0.72
- Median PF: 1.17
- % Profitable: 70.7%
- **FAIL**
