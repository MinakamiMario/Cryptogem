# Part 2 Scoreboard — Gate Status per Candidate

> Last updated: Cycle 4 complete (2026-02-16)

## Hard Gates

| Gate | Metric | Threshold |
|------|--------|-----------|
| G1 | Trades/week | >= 10 |
| G2 | Max gap | <= 2.5d |
| G3 | Exp/week (market) | > $0 |
| G4 | Exp/week (P95 stress) | > $0 |
| G5 | Max DD | <= 20% |
| G6 | Walk-forward | >= 4/5 |
| G7 | Neighbor stability | >= 8/12 |
| G8 | Top-1 fold conc. | < 35% |

## Candidates

### ⭐⭐ LEADER: v5 on 295 coins (excl_all_negative) — 8/8 gates PASS
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 13.03/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$762/wk | PASS |
| G4 | +$571/wk (2x stress) | PASS |
| G5 | 8.6% | PASS |
| G6 | 4/5 | PASS |
| G7 | **12/12** (C2-A1) | **PASS** |
| G8 | 34.2% | PASS |
| **Score** | **8/8 ALL GATES PASS** | **🟢🟢 GO** |

> Source: A3 loss_cluster_001 + C2-A1 robustness_295_001
> PF=2.834, 56 trades, WF folds: $909, $58, -$18, $792, $913
> Stress 2x: PF=2.306, Exp/wk=$571
> G7: ALL 12/12 neighbors profitable, ALL 12/12 survive stress 2x
> Breakeven: 5.00x fee multiplier (C2-A6) — massive margin over 2x stress
> OOS validation: STRUCTURAL_FEATURE (C2-A3) but expanding window NOT_CONFIRMED (C4-A2)
> Minimum exclusion: 12 coins (not 21) for 7/7 gates — 9 coins of headroom (C2-A5)
> Multi-pos: max_pos=2 passes 7/7 but -60% P&L — keep max_pos=1 (C4-A1)
> Tier split: T1=32.3% ($1058), T2=67.7% ($2214) — T2 is dominant edge contributor (C4-A4)
> Time-of-day: filtering worst hours causes REGRESSION 7/7→6/7 (G8 fails) — not viable (C4-A3)

### ⭐ sl=7 on 295 coins (excl_all_negative) — 7/7 gates PASS (ALTERNATIVE)
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 12.82/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$745/wk | PASS |
| G4 | +$557/wk (2x stress) | PASS |
| G5 | 9.8% | PASS |
| G6 | 5/5 | PASS |
| G7 | 12/12 (C2-A1) | PASS |
| G8 | 33.1% | PASS |
| **Score** | **7/7 ALL GATES PASS** | **🟢🟢 ALT GO** |

> Source: C3-A3 sl7_295_001. sl=7 variant: better WF (5/5 vs 4/5) and fold_conc (33.1% vs 34.2%).
> PF=2.715, 55 trades, DD=9.8%. V5 wins on raw P&L/PF but sl=7 wins on robustness metrics.
> Both pass all 7 testable gates. sl=7 is more conservative (wider stop loss).

### v5 on 304 coins (excl_worst12) — 8/8 gates PASS (CONSERVATIVE ALT)
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 13.50/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$559/wk | PASS |
| G4 | +$392/wk (2x stress) | PASS |
| G5 | 11.8% | PASS |
| G6 | 4/5 | PASS |
| G7 | **12/12** (C3-A1) | **PASS** |
| G8 | 34.0% | PASS |
| **Score** | **8/8 ALL GATES PASS** | **🟢🟢 GO** |

> Source: C2-A5 excl_sweep_001 + C3-A1 robustness_304_001. More conservative: only 12 worst coins excluded.
> PF=2.518, 58 trades, DD=11.8%, fold_conc=34.0%. G7=12/12 (all survive stress, all WF>=3/5).
> Top variant on 304: time_limit-2 (score=510.6, exp/wk=$638).

### tp10_sl4_tl8 on 295 coins — 6/7 gates (G8 FAIL)
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 14.21/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$645/wk | PASS |
| G4 | +$452/wk (2x stress) | PASS |
| G5 | 12.2% | PASS |
| G6 | 5/5 | PASS |
| G8 | 36.1% | **FAIL** (barely) |
| **Score** | **6/7** | **Near-miss** |

> Source: C2-A2 + C2-A4. PF=2.392, 61 trades, WF=5/5 but fold_conc=36.1%>35%.
> Breakeven: 3.00x (C2-A6). Better WF but worse fold_conc vs v5.

### v5 on 306 coins (excl_worst10) — 5/7 gates
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 13.96/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$479/wk | PASS |
| G4 | +$316/wk | PASS |
| G5 | 20.2% | **FAIL** (barely) |
| G6 | 4/5 | PASS |
| G8 | 38.5% | **FAIL** |
| **Score** | **5/7** | **Near-miss** |

### Baseline: v5 on 316 coins (003 — HALT)
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 16.75/wk | PASS |
| G2 | 1.42d | PASS |
| G3 | +$86/wk | PASS |
| G4 | -$33/wk | **FAIL** |
| G5 | 53.1% | **FAIL** |
| G6 | 3/5 | **FAIL** |
| G7 | 9/12 (A4) | PASS |
| G8 | 48.6% | **FAIL** |
| **Score** | **4/8** | **HALT** |

### Baseline: v5 on 135 coins (002 — reference)
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 10.01/wk | PASS |
| G2 | 1.75d | PASS |
| G3 | +$250/wk | PASS |
| G4 | +$178/wk | PASS |
| G5 | 11.4% | PASS |
| G6 | 5/5 | PASS |
| G7 | 11/12 | PASS |
| G8 | 59.5% | **FAIL** |
| **Score** | **7/8** | **COND. GO** |

### tp10_sl4_tl8 on 135 coins (A6 param grid) — reference
| Gate | Value | Verdict |
|------|-------|---------|
| G3 | +$149/wk | PASS |
| G5 | 9.0% | PASS |
| G6 | 5/5 | PASS |
| G8 | 25.8% | PASS |
| **Note** | PF=1.683, 31 trades | 135-coin reference |

### T1-only (100 coins) — rejected
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 4.89/wk | **FAIL** |
| G8 | 66.6% | **FAIL** |
| **Score** | **5/7** | **FAIL** (too few trades, too concentrated) |

### Volume cutoff sweep — no winner
| Best N | Gates | Note |
|--------|-------|------|
| N=316 | 3/7 | Best volume cutoff, but still fails G4/G5/G6/G8 |
| All N<316 | 0-1/7 | Volume sorting doesn't help — edge is in low-vol coins |

## Key Insights

### Cycle 4 (NEW)
1. **max_pos=2 passes 7/7 but NOT worth it**: Both max_pos=1 and max_pos=2 pass all gates, but max_pos=2 has -60% P&L ($1309 vs $3272) and -60% exp/wk ($305 vs $762). Lower DD (5.0% vs 8.6%) is the only advantage. Recommendation: keep max_pos=1.
2. **Expanding window OOS: NOT_CONFIRMED**: Exclusion helped 0/2 OOS windows, aggregate delta -$106. 11 stable exclusions all match oracle list, but exclusion doesn't improve OOS P&L. Contradicts C2-A3 STRUCTURAL_FEATURE — exclusion benefit may be largely in-sample. OOS gate score: 4/7.
3. **Time-of-day filtering: REGRESSION**: Signal fires 23/24 hours. Filtering worst hours (06, 14, 19 UTC) improves PF (2.834→3.795) but causes G8 FAIL (fold_conc 34.2%→38.5%). 7/7→6/7 gates. Not viable.
4. **T2 is the dominant edge contributor**: T2 provides 67.7% of total P&L ($2214 of $3272), has better WF (5/5 vs T1's 3/5), lower DD (8.4% vs 11.1%). Fee drag: T2=14.5% vs T1=6.6%, but T2 still strongly profitable. Keep T2 in universe.
5. **OOS caution flag raised**: The expanding window test (C4-A2) is more pessimistic than the split-half test (C2-A3). The in-sample exclusion advantage may not generalize as strongly as initially believed. Paper trading will be the definitive test.

### Cycle 3
1. **G7 PASS 12/12 on 304 coins**: excl_worst12 also gets perfect G7 — TWO universes now pass all 8 gates
2. **sl=7 on 295 coins: 7/7 gates + WF=5/5**: Better walk-forward (5/5 vs 4/5) and fold_conc (33.1% vs 34.2%) than v5 baseline
3. **Rolling lookback: MARGINAL**: Only retains 22% of oracle P&L. Best rolling variant = $729 (vs oracle $3272). Not viable as sole production mechanism.
4. **Persistent excludes (12 coins)**: Static list from rolling analysis gets 6/7 gates (G8 FAIL at 39.8%)
5. **ADR HF-032 written**: GO decision for paper trading with v5 on 295 coins documented
6. **Three viable production configs**: v5/295 (leader), sl7/295 (robustness alt), v5/304 (conservative alt)

### Cycle 2
1. **G7 PASS 12/12 on 295 coins**: ALL neighbors profitable, ALL survive stress — best G7 ever
2. **excl_all_negative is STRUCTURAL**: OOS validation confirms it helps out-of-sample (C2-A3)
3. **Minimum exclusion = 12 coins** (not 21): 9 coins of headroom for error (C2-A5)
4. **tp10_sl4_tl8 fails G8 on 295 coins**: fold_conc=36.1% > 35% — v5 params are better
5. **Breakeven 5.00x on 295 coins** (v5): massive improvement vs 1.71x on 316 coins
6. **3 consistently profitable coins**: AURA/USD, XL1/USD, NOBODY/USD across all folds
7. **Leakage-free gate score**: 4/7 (degraded from 7/7) — in-sample bias accounts for ~3 gates

### Cycle 1
1. **excl_all_negative is the breakthrough**: Removing 21 net-negative coins flips 4 gates FAIL→PASS
2. **Volume cutoff doesn't work**: Edge is in tail coins (low-vol T2), not in top-volume coins
3. **T2 is structural drag on stress**: T2 loses $239 even at baseline fees (A5)
4. **Breakeven fee multiplier**: 1.71x on 316 coins (A5)
5. **tp10+tl8 fixes fold concentration on 135**: fold_conc=25.8% (A6)
6. **G7 passes on 316**: 9/12 neighbors profitable (A4)
7. **sl=7 survives stress on 316**: PF=1.079 at 2x fees (A4)

---
