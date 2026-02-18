# MEXC DD Micro-Sweep — Report

**Date**: 2026-02-18
**Git**: `9a606d9`
**ADR**: 4H-014 addendum
**Fixed**: adaptive_maxpos 3/2/1

## Phase 1: Quick Gate-Check

| # | Label | Trades | PF | P&L | DD | Quick |
|---|-------|-------:|---:|----:|---:|:-----:|
| 1 | 5%/0.25x (baseline) | 301 | 1.4796 | $+3,671 | 20.3% | ❌ |
| 2 | 5%/0.22x | 297 | 1.4523 | $+3,073 | 19.4% | ✅ |
| 3 | 5%/0.20x | 296 | 1.4257 | $+2,749 | 18.7% | ✅ |
| 4 | 6%/0.25x | 279 | 1.3809 | $+2,874 | 20.7% | ❌ |
| 5 | 6%/0.22x | 287 | 1.4860 | $+3,437 | 22.3% | ❌ |
| 6 | 7%/0.25x | 280 | 1.3990 | $+3,121 | 20.7% | ❌ |

## Phase 2: Full Truth-Pass

### 5%/0.22x

| Metric | Value |
|--------|------:|
| Trades | 297 |
| PF | 1.4523 |
| P&L | $+3,073 |
| DD | 19.4% |
| Windows | 4/5 |
| Boot P5 | 1.02 |
| Boot %prof | 96.0% |
| Truth-Pass | VERIFIED (3/3) |
| Gates | ✅ 7/7 GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.3 | 1.4523 | ✅ |
| DD <= 20.0% | 19.36 | ✅ |
| Boot P5 >= 0.85 | 1.0178 | ✅ |
| Boot %prof >= 80.0% | 96.0 | ✅ |
| Win >= 4/5 | 4 | ✅ |
| Trades >= 250 | 297 | ✅ |
| Determinism | PASS | ✅ |

---

### 5%/0.20x

| Metric | Value |
|--------|------:|
| Trades | 296 |
| PF | 1.4257 |
| P&L | $+2,749 |
| DD | 18.7% |
| Windows | 4/5 |
| Boot P5 | 0.99 |
| Boot %prof | 94.2% |
| Truth-Pass | VERIFIED (3/3) |
| Gates | ✅ 7/7 GO |

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.3 | 1.4257 | ✅ |
| DD <= 20.0% | 18.73 | ✅ |
| Boot P5 >= 0.85 | 0.9895 | ✅ |
| Boot %prof >= 80.0% | 94.2 | ✅ |
| Win >= 4/5 | 4 | ✅ |
| Trades >= 250 | 296 | ✅ |
| Determinism | PASS | ✅ |

---

## Conclusion

**WINNER: 5%/0.22x** — 297 trades, PF=1.4523, DD=19.4%, 7/7 gates ✅

This config is ready for **GO — PAPERTRADE**.
