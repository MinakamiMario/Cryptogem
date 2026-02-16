# Part 2 Backlog — Priority Queue

> Last updated: Cycle 6 complete — ALL ITEMS RESOLVED (2026-02-16)

## P0 — Critical (blocks GO decision)
| # | Card | Owner | Status |
|---|------|-------|--------|
| — | *All P0 items resolved* | — | ✅ |

**ALL 8 GATES PASS** on v5 + excl_all_negative (295 coins).
**ADR HF-032 written** — GO decision documented.

## P1 — Important (improves confidence)
| # | Card | Owner | Status |
|---|------|-------|--------|
| — | *All P1 items resolved* | — | ✅ |

## P2 — Nice-to-have
| # | Card | Owner | Status |
|---|------|-------|--------|
| — | *All P2 items resolved* | — | ✅ |

**ALL 6 P2 items resolved. P2-5 (fee sensitivity) and P2-6 (T1 concentration) completed in Cycle 6.**

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

## Completed (Cycle 3)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P1-1~~ | G7 robustness on 304 coins | C3-A1 | ⭐ **12/12 PASS — perfect G7 on excl_worst12** |
| ~~P1-2~~ | Rolling lookback exclusion | C3-A2 | ⚠️ MARGINAL (22% of oracle P&L retained) |
| ~~P2-4~~ | sl=7 variant on 295 coins | C3-A3 | ⭐ **7/7 gates + WF=5/5 + fold_conc=33.1%** |
| ~~P2-2~~ | ADR HF-032 draft | C3-A4 | ✅ **GO decision documented** |

## Completed (Cycle 4)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P1-3~~ | Multi-pos capacity (max_pos=2) | C4-A1 | ✅ Both pass 7/7, but max_pos=2 has -60% P&L — keep max_pos=1 |
| ~~P1-4~~ | Expanding window OOS | C4-A2 | ⚠️ **NOT_CONFIRMED** — exclusion helped 0/2 windows, delta -$106 |
| ~~P1-5~~ | Time-of-day analysis | C4-A3 | ❌ REGRESSION — filtering breaks G8 (fold_conc 38.5%) |
| ~~P1-6~~ | Per-tier edge decomposition | C4-A4 | ⭐ **T2 validated — 67.7% of edge, WF=5/5, lower DD** |

## Completed (Cycle 5)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P2-1~~ | Hybrid exclusion (static+dynamic) | C5-A1 | ❌ **HYBRID_DEGRADES** — dynamic layer breaks G8 (35.3%), static-12 alone passes 7/7 |
| ~~P2-2~~ | sl=7 + excl_worst12 (304 coins) | C5-A2 | ⭐ **ALL 4 configs pass 7/7** — sl7/295 best by composite, sl7/304 viable but weakest |
| ~~P2-3~~ | BTC regime correlation | C5-A3 | ✅ **REGIME-ROBUST** — profitable in all regimes, filtering NOT recommended |
| ~~P2-4~~ | Max drawdown duration | C5-A4 | ⭐ **sl7/295 BEST** — 3.8d max underwater vs leader's 8.6d |

## Completed (Cycle 6)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P2-5~~ | T2 fee sensitivity ladder | C6-A2 | ⭐ **G3 breakeven 218bps (9.3x current)** — ALL 7 gates pass at every fee level 0-100bps |
| ~~P2-6~~ | T1 concentration risk study | C6-A1 | ✅ **MANAGEABLE** — HHI diversified, strategy survives without XL1/USD or all T1 |

---

**🏁 ALL P0/P1/P2 ITEMS RESOLVED — RESEARCH COMPLETE**

Final recommendation: Deploy paper trading with v5/295 (leader). Monitor sl7/295 as parallel alt.
See `part2_scoreboard.md` for full gate tables and `part2_teamlog.md` for 14-dimension risk coverage.
