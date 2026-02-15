# Part 2 Backlog — Priority Queue

> Last updated: Cycle 1 complete (2026-02-16)

## P0 — Critical (blocks GO decision)
| # | Card | Owner | Status |
|---|------|-------|--------|
| P0-1 | G7 robustness test on 295-coin universe (excl_all_negative) | — | 🔴 Cycle 2 |
| P0-2 | Run tp10_sl4_tl8 on 295-coin universe — full 8-gate test | — | 🔴 Cycle 2 |
| P0-3 | OOS validation: is excl_all_negative forward-looking bias? | — | 🔴 Cycle 2 |
| P0-4 | Run tp10_sl4_tl8 + excl_all_negative combo — full gate test | — | 🔴 Cycle 2 |
| P0-5 | Sweep exclusion thresholds: excl_worst15/worst18 to find minimum exclusion | — | 🔴 Cycle 2 |

## P1 — Important (improves confidence)
| # | Card | Owner | Status |
|---|------|-------|--------|
| P1-1 | Per-fold coin attribution on 295-coin leader | — | ⏳ Cycle 2/3 |
| P1-2 | Stress 2x on 295-coin + tp10_sl4_tl8 | — | ⏳ Cycle 2 |
| P1-3 | Fold concentration deep-dive on 295-coin universe | — | ⏳ Cycle 2 |
| P1-4 | Multi-pos capacity (max_pos=2) on winning config | — | ⏳ Cycle 3 |

## P2 — Nice-to-have
| # | Card | Owner | Status |
|---|------|-------|--------|
| P2-1 | Time-of-day analysis on winning config | — | ⏳ |
| P2-2 | ADR HF-032 draft (Cycle 2 results) | — | ⏳ |
| P2-3 | Per-tier edge decomposition | — | ⏳ |

## Completed (Cycle 1)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-1~~ | Volume cutoff sweep | A1 | ❌ Dead end — edge in tail coins |
| ~~P0-2~~ | T1-only baseline | A2 | ❌ Too few trades (21), fails G1/G8 |
| ~~P0-3~~ | Loss-cluster exclusion | A3 | ⭐ **7/7 gates with excl_all_negative** |
| ~~P0-4~~ | Robustness on 316 | A4 | ✅ G7 PASS 9/12, sl=7 survives stress |
| ~~P0-5~~ | Stress model alternatives | A5 | ✅ Breakeven at 1.71x, T2 is drag |
| ~~P1-1~~ | Param combos on 135 | A6 | ✅ tp10_sl4_tl8 fixes G8 (fold_conc=25.8%) |
