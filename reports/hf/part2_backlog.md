# Part 2 Backlog — Priority Queue

> Last updated: Cycle 2 complete (2026-02-16)

## P0 — Critical (blocks GO decision)
| # | Card | Owner | Status |
|---|------|-------|--------|
| — | *All P0 items resolved* | — | ✅ |

**ALL 8 GATES PASS** on v5 + excl_all_negative (295 coins).

## P1 — Important (improves confidence)
| # | Card | Owner | Status |
|---|------|-------|--------|
| P1-1 | G7 robustness on excl_worst12 (304 coins) | — | ⏳ Cycle 3 |
| P1-2 | Rolling lookback window for coin exclusion (production mechanism) | — | ⏳ Cycle 3 |
| P1-3 | Multi-pos capacity (max_pos=2) on winning config | — | ⏳ Cycle 3 |
| P1-4 | Deeper OOS: 60/40 train/test split with rolling window | — | ⏳ Cycle 3 |

## P2 — Nice-to-have
| # | Card | Owner | Status |
|---|------|-------|--------|
| P2-1 | Time-of-day analysis on winning config | — | ⏳ |
| P2-2 | ADR HF-032 draft (Cycle 2 results → GO decision) | — | ⏳ |
| P2-3 | Per-tier edge decomposition on 295 coins | — | ⏳ |
| P2-4 | Explore sl=7 variant on 295 coins (top G7 scorer) | — | ⏳ |

## Completed (Cycle 1)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-1~~ | Volume cutoff sweep | A1 | ❌ Dead end — edge in tail coins |
| ~~P0-2~~ | T1-only baseline | A2 | ❌ Too few trades (21), fails G1/G8 |
| ~~P0-3~~ | Loss-cluster exclusion | A3 | ⭐ **7/7 gates with excl_all_negative** |
| ~~P0-4~~ | Robustness on 316 | A4 | ✅ G7 PASS 9/12, sl=7 survives stress |
| ~~P0-5~~ | Stress model alternatives | A5 | ✅ Breakeven at 1.71x, T2 is drag |
| ~~P1-1~~ | Param combos on 135 | A6 | ✅ tp10_sl4_tl8 fixes G8 (fold_conc=25.8%) |

## Completed (Cycle 2)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-1~~ | G7 robustness on 295 coins | C2-A1 | ⭐ **12/12 PASS — perfect score** |
| ~~P0-2~~ | tp10_sl4_tl8 on 295 coins | C2-A2 | ❌ G8 FAIL (fold_conc=36.1%) |
| ~~P0-3~~ | OOS validation | C2-A3 | ⚠️ STRUCTURAL_FEATURE (helps OOS, leakage-free 4/7) |
| ~~P0-4~~ | Combo test (tp10+excl) | C2-A4 | ❌ v5 beats tp10 on 295 coins |
| ~~P0-5~~ | Exclusion threshold sweep | C2-A5 | ⭐ **Min exclusion = 12 coins** (9 headroom) |
| ~~P1-2~~ | Stress 2x + attribution | C2-A6 | ⭐ **Breakeven 5.00x** (was 1.71x on 316) |
