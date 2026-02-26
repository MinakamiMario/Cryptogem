# Sweep v1 DD-Fix — A06 Drawdown Reduction

**Date**: 2026-02-26
**Git**: `57a688e`
**Config**: sweep_v1_006_sv1a06_rsi45_p8_atr2.0
**Original**: 347tr, PF=1.2413, DD=107.2%, P&L=$+4,473

## Methodology

Post-hoc equity simulation applying risk wrappers to existing trade lists.
Entry and exit logic are UNCHANGED. Only sizing and trade admission modified.

### Wrappers
1. **DD Throttle**: Scale position size by factor when DD > threshold
2. **Adaptive MaxPos**: Reduce max concurrent positions (calm/medium/stressed) by DD level

### Grid: 9 throttle x 3 maxpos = 27 combos

### Gates
- PF >= 1.15
- DD <= 25.0%
- Trades >= 200
- Boot P5 >= 0.85
- Boot %prof >= 80.0%
- Windows >= 2/3

## Phase 1: Quick Gate-Check (all combos)

| # | Label | Trades | PF | P&L | DD | DD_red | Quick |
|---|-------|-------:|---:|----:|---:|-------:|:-----:|
| 1 | 5%/0.30x+3/2/1 | 246 | 1.3174 | $+1,532 | 28.2% | +73.6% | FAIL |
| 2 | 5%/0.30x+2/1/1 | 222 | 1.7410 | $+2,483 | 14.9% | +86.1% | PASS |
| 3 | 5%/0.30x+3/2/0 | 4 | 0.0319 | $-391 | 20.0% | +81.3% | FAIL |
| 4 | 5%/0.25x+3/2/1 | 280 | 1.3103 | $+1,413 | 25.0% | +76.6% | FAIL |
| 5 | 5%/0.25x+2/1/1 | 224 | 1.7355 | $+2,145 | 14.6% | +86.4% | PASS |
| 6 | 5%/0.25x+3/2/0 | 8 | 0.1097 | $-415 | 21.2% | +80.2% | FAIL |
| 7 | 5%/0.22x+3/2/1 | 275 | 1.3275 | $+1,267 | 23.9% | +77.7% | PASS |
| 8 | 5%/0.22x+2/1/1 | 218 | 1.8035 | $+1,911 | 15.9% | +85.1% | PASS |
| 9 | 5%/0.22x+3/2/0 | 8 | 0.1041 | $-401 | 20.5% | +80.9% | FAIL |
| 10 | 5%/0.20x+3/2/1 | 269 | 1.6113 | $+2,285 | 23.1% | +78.4% | PASS |
| 11 | 5%/0.20x+2/1/1 | 226 | 2.1031 | $+2,825 | 13.7% | +87.2% | PASS |
| 12 | 5%/0.20x+3/2/0 | 8 | 0.1000 | $-391 | 20.0% | +81.3% | FAIL |
| 13 | 8%/0.30x+3/2/1 | 243 | 1.2920 | $+1,567 | 28.2% | +73.6% | FAIL |
| 14 | 8%/0.30x+2/1/1 | 222 | 1.7538 | $+2,712 | 14.9% | +86.1% | PASS |
| 15 | 8%/0.30x+3/2/0 | 4 | 0.0319 | $-391 | 20.0% | +81.3% | FAIL |
| 16 | 8%/0.25x+3/2/1 | 278 | 1.5313 | $+2,716 | 25.0% | +76.6% | FAIL |
| 17 | 8%/0.25x+2/1/1 | 226 | 2.0714 | $+3,468 | 12.3% | +88.5% | PASS |
| 18 | 8%/0.25x+3/2/0 | 8 | 0.1097 | $-415 | 21.2% | +80.2% | FAIL |
| 19 | 8%/0.22x+3/2/1 | 273 | 1.5722 | $+2,685 | 23.9% | +77.7% | PASS |
| 20 | 8%/0.22x+2/1/1 | 213 | 2.0410 | $+3,113 | 15.9% | +85.1% | PASS |
| 21 | 8%/0.22x+3/2/0 | 8 | 0.1041 | $-401 | 20.5% | +80.9% | FAIL |
| 22 | 10%/0.30x+3/2/1 | 246 | 1.5173 | $+2,892 | 28.2% | +73.6% | FAIL |
| 23 | 10%/0.30x+2/1/1 | 222 | 2.0509 | $+3,930 | 14.9% | +86.1% | PASS |
| 24 | 10%/0.30x+3/2/0 | 4 | 0.0319 | $-391 | 20.0% | +81.3% | FAIL |
| 25 | 10%/0.25x+3/2/1 | 276 | 1.5314 | $+2,862 | 25.0% | +76.6% | FAIL |
| 26 | 10%/0.25x+2/1/1 | 224 | 2.0941 | $+3,641 | 13.2% | +87.7% | PASS |
| 27 | 10%/0.25x+3/2/0 | 8 | 0.1097 | $-415 | 21.2% | +80.2% | FAIL |

## Phase 2: Full Truth-Pass

### 5%/0.30x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 222 |
| PF | 1.7410 |
| P&L | $+2,483 |
| DD | 14.9% |
| DD reduction | +86.1% |
| PF change | +40.3% |
| Windows | 2/3 |
| Boot P5 | 1.18 |
| Boot %prof | 98.6% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.741 | PASS |
| DD <= 25.0% | 14.91 | PASS |
| Boot P5 >= 0.85 | 1.1809 | PASS |
| Boot %prof >= 80.0% | 98.6 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 222 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 147 | $+3,984 | 72.1% |
| DC TARGET | A | 18 | $+1,169 | 94.4% |
| BB TARGET | A | 12 | $+434 | 91.7% |
| END | B | 3 | $-7 | 0.0% |
| TIME MAX | B | 26 | $-1,394 | 3.8% |
| FIXED STOP | B | 16 | $-1,703 | 0.0% |

---

### 5%/0.25x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 224 |
| PF | 1.7355 |
| P&L | $+2,145 |
| DD | 14.6% |
| DD reduction | +86.4% |
| PF change | +39.8% |
| Windows | 2/3 |
| Boot P5 | 1.13 |
| Boot %prof | 98.0% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.7355 | PASS |
| DD <= 25.0% | 14.61 | PASS |
| Boot P5 >= 0.85 | 1.1278 | PASS |
| Boot %prof >= 80.0% | 98.0 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 224 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 149 | $+3,403 | 72.5% |
| DC TARGET | A | 18 | $+1,087 | 94.4% |
| BB TARGET | A | 12 | $+362 | 91.7% |
| END | B | 3 | $-6 | 0.0% |
| TIME MAX | B | 26 | $-1,231 | 3.8% |
| FIXED STOP | B | 16 | $-1,471 | 0.0% |

---

### 5%/0.22x+3/2/1

| Metric | Value |
|--------|------:|
| Trades | 275 |
| PF | 1.3275 |
| P&L | $+1,267 |
| DD | 23.9% |
| DD reduction | +77.7% |
| PF change | +6.9% |
| Windows | 2/3 |
| Boot P5 | 0.93 |
| Boot %prof | 90.5% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.3275 | PASS |
| DD <= 25.0% | 23.88 | PASS |
| Boot P5 >= 0.85 | 0.9296 | PASS |
| Boot %prof >= 80.0% | 90.5 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 275 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 177 | $+3,457 | 75.1% |
| DC TARGET | A | 24 | $+1,151 | 87.5% |
| BB TARGET | A | 13 | $+304 | 84.6% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 30 | $-1,008 | 3.3% |
| FIXED STOP | B | 28 | $-2,632 | 0.0% |

---

### 5%/0.22x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 218 |
| PF | 1.8035 |
| P&L | $+1,911 |
| DD | 15.9% |
| DD reduction | +85.1% |
| PF change | +45.3% |
| Windows | 1/3 |
| Boot P5 | 1.11 |
| Boot %prof | 97.8% |
| Truth-Pass | CONDITIONAL (1/2) |
| Gates | 5/6 gates |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.8035 | PASS |
| DD <= 25.0% | 15.93 | PASS |
| Boot P5 >= 0.85 | 1.1101 | PASS |
| Boot %prof >= 80.0% | 97.8 | PASS |
| Win >= 2/3 | 1 | FAIL |
| Trades >= 200 | 218 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 147 | $+2,810 | 71.4% |
| DC TARGET | A | 16 | $+971 | 93.8% |
| BB TARGET | A | 11 | $+297 | 90.9% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 27 | $-967 | 3.7% |
| FIXED STOP | B | 14 | $-1,195 | 0.0% |

---

### 5%/0.20x+3/2/1

| Metric | Value |
|--------|------:|
| Trades | 269 |
| PF | 1.6113 |
| P&L | $+2,285 |
| DD | 23.1% |
| DD reduction | +78.4% |
| PF change | +29.8% |
| Windows | 2/3 |
| Boot P5 | 0.90 |
| Boot %prof | 89.9% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.6113 | PASS |
| DD <= 25.0% | 23.11 | PASS |
| Boot P5 >= 0.85 | 0.8987 | PASS |
| Boot %prof >= 80.0% | 89.9 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 269 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 172 | $+4,388 | 75.0% |
| DC TARGET | A | 24 | $+1,123 | 87.5% |
| BB TARGET | A | 14 | $+293 | 85.7% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 27 | $-976 | 3.7% |
| FIXED STOP | B | 29 | $-2,539 | 0.0% |

---

### 5%/0.20x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 226 |
| PF | 2.1031 |
| P&L | $+2,825 |
| DD | 13.7% |
| DD reduction | +87.2% |
| PF change | +69.4% |
| Windows | 1/3 |
| Boot P5 | 1.10 |
| Boot %prof | 97.3% |
| Truth-Pass | CONDITIONAL (1/2) |
| Gates | 5/6 gates |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 2.1031 | PASS |
| DD <= 25.0% | 13.7 | PASS |
| Boot P5 >= 0.85 | 1.0983 | PASS |
| Boot %prof >= 80.0% | 97.3 | PASS |
| Win >= 2/3 | 1 | FAIL |
| Trades >= 200 | 226 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 146 | $+3,928 | 72.6% |
| DC TARGET | A | 18 | $+989 | 88.9% |
| BB TARGET | A | 12 | $+275 | 83.3% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 26 | $-814 | 3.8% |
| FIXED STOP | B | 21 | $-1,548 | 0.0% |

---

### 8%/0.30x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 222 |
| PF | 1.7538 |
| P&L | $+2,712 |
| DD | 14.9% |
| DD reduction | +86.1% |
| PF change | +41.3% |
| Windows | 2/3 |
| Boot P5 | 1.19 |
| Boot %prof | 99.2% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.7538 | PASS |
| DD <= 25.0% | 14.91 | PASS |
| Boot P5 >= 0.85 | 1.1921 | PASS |
| Boot %prof >= 80.0% | 99.2 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 222 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 147 | $+4,150 | 72.1% |
| DC TARGET | A | 18 | $+1,247 | 94.4% |
| BB TARGET | A | 12 | $+635 | 91.7% |
| END | B | 3 | $-7 | 0.0% |
| TIME MAX | B | 26 | $-1,394 | 3.8% |
| FIXED STOP | B | 16 | $-1,920 | 0.0% |

---

### 8%/0.25x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 226 |
| PF | 2.0714 |
| P&L | $+3,468 |
| DD | 12.3% |
| DD reduction | +88.5% |
| PF change | +66.9% |
| Windows | 2/3 |
| Boot P5 | 1.16 |
| Boot %prof | 98.1% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 2.0714 | PASS |
| DD <= 25.0% | 12.32 | PASS |
| Boot P5 >= 0.85 | 1.1599 | PASS |
| Boot %prof >= 80.0% | 98.1 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 226 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 152 | $+4,924 | 72.4% |
| DC TARGET | A | 18 | $+1,185 | 94.4% |
| BB TARGET | A | 12 | $+362 | 91.7% |
| END | B | 3 | $-6 | 0.0% |
| TIME MAX | B | 26 | $-1,371 | 3.8% |
| FIXED STOP | B | 15 | $-1,626 | 0.0% |

---

### 8%/0.22x+3/2/1

| Metric | Value |
|--------|------:|
| Trades | 273 |
| PF | 1.5722 |
| P&L | $+2,685 |
| DD | 23.9% |
| DD reduction | +77.7% |
| PF change | +26.7% |
| Windows | 2/3 |
| Boot P5 | 0.95 |
| Boot %prof | 92.3% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 1.5722 | PASS |
| DD <= 25.0% | 23.88 | PASS |
| Boot P5 >= 0.85 | 0.9519 | PASS |
| Boot %prof >= 80.0% | 92.3 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 273 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 176 | $+5,319 | 75.0% |
| DC TARGET | A | 24 | $+1,460 | 87.5% |
| BB TARGET | A | 12 | $+353 | 83.3% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 30 | $-1,568 | 3.3% |
| FIXED STOP | B | 28 | $-2,873 | 0.0% |

---

### 8%/0.22x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 213 |
| PF | 2.0410 |
| P&L | $+3,113 |
| DD | 15.9% |
| DD reduction | +85.1% |
| PF change | +64.4% |
| Windows | 1/3 |
| Boot P5 | 1.11 |
| Boot %prof | 98.0% |
| Truth-Pass | CONDITIONAL (1/2) |
| Gates | 5/6 gates |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 2.041 | PASS |
| DD <= 25.0% | 15.93 | PASS |
| Boot P5 >= 0.85 | 1.1136 | PASS |
| Boot %prof >= 80.0% | 98.0 | PASS |
| Win >= 2/3 | 1 | FAIL |
| Trades >= 200 | 213 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 143 | $+4,524 | 71.3% |
| DC TARGET | A | 16 | $+1,072 | 93.8% |
| BB TARGET | A | 11 | $+297 | 90.9% |
| END | B | 3 | $-5 | 0.0% |
| TIME MAX | B | 26 | $-1,339 | 0.0% |
| FIXED STOP | B | 14 | $-1,437 | 0.0% |

---

### 10%/0.30x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 222 |
| PF | 2.0509 |
| P&L | $+3,930 |
| DD | 14.9% |
| DD reduction | +86.1% |
| PF change | +65.2% |
| Windows | 2/3 |
| Boot P5 | 1.24 |
| Boot %prof | 99.5% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 2.0509 | PASS |
| DD <= 25.0% | 14.91 | PASS |
| Boot P5 >= 0.85 | 1.2417 | PASS |
| Boot %prof >= 80.0% | 99.5 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 222 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 147 | $+5,436 | 72.1% |
| DC TARGET | A | 18 | $+1,309 | 94.4% |
| BB TARGET | A | 12 | $+635 | 91.7% |
| END | B | 3 | $-7 | 0.0% |
| TIME MAX | B | 26 | $-1,524 | 3.8% |
| FIXED STOP | B | 16 | $-1,920 | 0.0% |

---

### 10%/0.25x+2/1/1

| Metric | Value |
|--------|------:|
| Trades | 224 |
| PF | 2.0941 |
| P&L | $+3,641 |
| DD | 13.2% |
| DD reduction | +87.7% |
| PF change | +68.7% |
| Windows | 2/3 |
| Boot P5 | 1.20 |
| Boot %prof | 98.8% |
| Truth-Pass | VERIFIED (2/2) |
| Gates | 6/6 gates -- GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.15 | 2.0941 | PASS |
| DD <= 25.0% | 13.21 | PASS |
| Boot P5 >= 0.85 | 1.2034 | PASS |
| Boot %prof >= 80.0% | 98.8 | PASS |
| Win >= 2/3 | 2 | PASS |
| Trades >= 200 | 224 | PASS |

**Exit Attribution:**
| Reason | Class | Count | P&L | WR |
|--------|:-----:|------:|----:|---:|
| RSI RECOVERY | A | 149 | $+4,906 | 72.5% |
| DC TARGET | A | 18 | $+1,238 | 94.4% |
| BB TARGET | A | 12 | $+577 | 91.7% |
| END | B | 3 | $-6 | 0.0% |
| TIME MAX | B | 26 | $-1,371 | 3.8% |
| FIXED STOP | B | 16 | $-1,703 | 0.0% |

---

## Conclusion

**WINNER: 10%/0.25x+2/1/1** -- 224 trades, PF=2.0941, DD=13.2%, DD reduction +87.7%, 6/6 gates

Original A06: PF=1.2413, DD=107.2%
Wrapped:      PF=2.0941, DD=13.2%
