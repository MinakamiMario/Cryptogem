# Part 2 Backlog — Priority Queue

> Last updated: **CLOSED** (2026-02-17)
>
> **SCOPE RESET**: User directive — paper trading is NOT the next step.
> New P0 items target: universe policy, concentration control, execution realism, drawdown control, loser diagnostics.
> Previous Cycles 1-6 results remain valid as reference.

## P0 — Critical (blocks GO decision)
| # | Card | Owner | Status |
|---|------|-------|--------|
| — | *(all P0 resolved)* | — | — |

## P1 — Important (improves confidence)
| # | Card | Owner | Status |
|---|------|-------|--------|
| P1-9 | Fresh data validation: re-run on newest candle data if available (check for regime shift) | — | WONTFIX (project closed) |

## P2 — Nice-to-have
| # | Card | Owner | Status |
|---|------|-------|--------|
| P2-7 | Hybrid maker strategy: limit-order entry for T2 coins to reduce taker costs | — | WONTFIX (project closed) |

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

## Completed (Cycle 7 — SCOPE RESET)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-1~~ | Universe policy sweep (14 variants, STRICT) | C7-A | ⭐ **CONFIRMS** — only excl_neg21 (295) + excl_worst12 (304) pass 7/7 |
| ~~P0-2~~ | Concentration control (17 variants) | C7-D | ❌ **NO IMPROVEMENT** — baseline passes G8, all controls hurt |
| ~~P0-3~~ | Execution realism (5 regimes) | C7-B | ⚠️ **RESILIENT** — degrades gracefully. G2 discrepancy found (2.75d vs 1.5d) |
| ~~P0-4~~ | DD killer (21 variants) | C7-C | ✅ **BASELINE OPTIMAL** — tighter stops increase DD, cooldown has no effect |
| ~~P0-5~~ | Losers cluster diagnostics (full 316 attribution) | C7-E | ✅ **EXCLUDED_21 CONFIRMED** — 0 new candidates, all 21 validated |
| ~~INT~~ | Baseline 316 vs 295 (STRICT) | C7-F | ✅ **CONFIRMS** — 316=3/7 NO-GO, 295=7/7 GO |

---

## Completed (Cycle 8 — G2 bug fix + continued investigation)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-6~~ | G2 gap computation discrepancy | HEAD | ✅ **BUG FOUND**: exec_realism + concentration scripts used entry_bar instead of exit_bar. Correct G2=1.5d (PASS). |

---

## Completed (Cycle 8 — Confidence Battery)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P1-7~~ | Signal variants exploration (10 variants) | C8-D | ✅ **BASELINE OPTIMAL** — 2/10 pass all gates, none beats baseline exp/wk |
| ~~P1-8~~ | Dev threshold sensitivity sweep | C8-A | ⭐ **dev=2.0 CONFIRMED** — only value passing 7/7, sharp optimum |
| ~~P2-8~~ | Monte Carlo trade shuffle (10K bootstraps) | C8-C | ⭐ **100% WIN** — zero ruin, P95 DD=22.7%, DD budget ~25% |
| ~~INT~~ | Exec realism v002 (G2 bugfix rerun) | C8-B | ⭐ **4/5 REGIMES PASS** — G2 fixed, only P90 fails (WF=3/5) |
| ~~INT~~ | Coin stability / edge persistence | C8-E | ⚠️ **WEAK PERSISTENCE** — 1 stable winner, 51% one-shot profit |

---

## Completed (Cycle 9 — P0 Validation)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-A~~ | Universe/selection audit (data assembly) | P0-A | ✅ **MEDIUM RISK** — Exclusion is circular but specific. CV lift positive but modest ($+16.34). |
| ~~P0-B~~ | Execution cost measurement (MEXC) | P0-B | ⚠️ **CANDLE PROXY INVALID** — Measures bar range not spread. Breakeven 6.5x v2. Real spread unknown. |
| ~~P0-C~~ | Decision/ADR writer | P0-C | ✅ ADR-HF-033 written. GO maintained with caveats. |

---

## Completed (Cycle 10 — Measured Orderbook Validation)
| # | Card | Owner | Result |
|---|------|-------|--------|
| ~~P0-D1~~ | MEXC orderbook data collection (19.5K snapshots) | Collector | ✅ 42 coins, 10s interval, 0% crossed books, 39/42 coins present |
| ~~P0-D2~~ | Data quality validation (3 subagents) | A/B/C | ✅ Sanity PASS, Slippage 0.00bps delta, Anti-double-count 12/12 |
| ~~P0-D3~~ | 24-combo measured cost rerun (7 STRICT gates) | D | ⭐ **14/24 PASS — all 12 maker combos 7/7** |
| ~~P0-D4~~ | ADR-HF-034 decision record | HEAD | ✅ CONDITIONAL GO MAINTAINED (maker execution) |

---

**✅ MEXC VALIDATION COMPLETE** — All P0 items resolved. Next: multi-exchange exploration.

**✅ RESEARCH COMPLETE** — All critical and important items resolved. 2 nice-to-have items remain (P1-9, P2-7) for future work.

**🔒 PROJECT CLOSED** (2026-02-17) — MEXC validated; Bybit portability disproven.
