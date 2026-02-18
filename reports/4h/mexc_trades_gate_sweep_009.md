# MEXC Trades-Gate Sweep — Report

**Date**: 2026-02-18
**Git**: `9a606d9`
**ADR**: 4H-014
**Universe**: Top 200, >=2160 bars (200 coins)
**Fee**: MEXC 10bps | **Sizing**: Fixed $2,000/trade

## Purpose

ADR-4H-014: Hold trades ≥ 250 gate. Test adaptive_maxpos relaxations
to recover trades while keeping DD ≤ 20% and all other gates green.

## Scoreboard

| Variant | maxpos | Trades | PF | P&L | DD | Win | Boot P5 | Gates | Deploy |
|---------|:------:|-------:|---:|----:|---:|:---:|--------:|:-----:|:------:|
| baseline_2_1_1 | 2/1/1 | 238 | 1.56 | $+3,362 | 16.2% | 5/5 | 1.08 | 6/7 | ❌ |
| relaxed_A_2_2_1 | 2/2/1 | 260 | 1.51 | $+3,326 | 20.3% | 3/5 | 1.03 | 5/7 | ❌ |
| relaxed_B_3_2_1 | 3/2/1 | 301 | 1.48 | $+3,671 | 20.3% | 4/5 | 1.01 | 6/7 | ❌ |

## Baseline (2/1/1) — from report 008

**adaptive_maxpos**: 2/1/1

| Metric | Value |
|--------|------:|
| Trades | 238 |
| PF | 1.5556 |
| P&L | $+3,362 |
| DD | 16.2% |
| WR | 55.5% |
| EV/trade | $14.13 |
| Trades/day | 0.55 |

**Gates**:

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.3 | 1.5556 | ✅ |
| DD <= 20.0% | 16.16 | ✅ |
| Boot P5 PF >= 0.85 | 1.0831 | ✅ |
| Boot %prof >= 80.0% | 97.3 | ✅ |
| Window >= 4/5 | 5 | ✅ |
| Trades >= 250 | 238 | ❌ |
| Determinism | PASS | ✅ |

**Truth-Pass**: VERIFIED (3/3)
**Gates**: 6/7
**Deploy**: NO ❌

---

## Relaxed A (2/2/1) — allow 2 at DD 10-20%

**adaptive_maxpos**: 2/2/1

| Metric | Value |
|--------|------:|
| Trades | 260 |
| PF | 1.5110 |
| P&L | $+3,326 |
| DD | 20.3% |
| WR | 56.1% |
| EV/trade | $12.79 |
| Trades/day | 0.60 |

**Gates**:

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.3 | 1.511 | ✅ |
| DD <= 20.0% | 20.32 | ❌ |
| Boot P5 PF >= 0.85 | 1.0318 | ✅ |
| Boot %prof >= 80.0% | 96.2 | ✅ |
| Window >= 4/5 | 3 | ❌ |
| Trades >= 250 | 260 | ✅ |
| Determinism | PASS | ✅ |

**Truth-Pass**: CONDITIONAL (2/3)
**Gates**: 5/7
**Deploy**: NO ❌

---

## Relaxed B (3/2/1) — allow 3 when healthy

**adaptive_maxpos**: 3/2/1

| Metric | Value |
|--------|------:|
| Trades | 301 |
| PF | 1.4796 |
| P&L | $+3,671 |
| DD | 20.3% |
| WR | 54.5% |
| EV/trade | $12.20 |
| Trades/day | 0.69 |

**Gates**:

| Gate | Value | Status |
|------|------:|-------:|
| PF >= 1.3 | 1.4796 | ✅ |
| DD <= 20.0% | 20.32 | ❌ |
| Boot P5 PF >= 0.85 | 1.0089 | ✅ |
| Boot %prof >= 80.0% | 95.4 | ✅ |
| Window >= 4/5 | 4 | ✅ |
| Trades >= 250 | 301 | ✅ |
| Determinism | PASS | ✅ |

**Truth-Pass**: VERIFIED (3/3)
**Gates**: 6/7
**Deploy**: NO ❌

---

## Conclusion

**No variant passes all 7 gates.** Further investigation needed.
