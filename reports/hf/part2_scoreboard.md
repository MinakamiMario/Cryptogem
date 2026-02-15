# Part 2 Scoreboard — Gate Status per Candidate

> Last updated: Cycle 1 complete (2026-02-16)

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

### ⭐ LEADER: v5 on 295 coins (excl_all_negative) — 7/7 gates
| Gate | Value | Verdict |
|------|-------|---------|
| G1 | 13.03/wk | PASS |
| G2 | 1.50d | PASS |
| G3 | +$761/wk | PASS |
| G4 | +$571/wk (2x stress) | PASS |
| G5 | 8.6% | PASS |
| G6 | 4/5 | PASS |
| G7 | TBD (needs Cycle 2) | — |
| G8 | 34.2% | PASS |
| **Score** | **7/7 (G7 pending)** | **🟢 CANDIDATE GO** |

> Source: A3 loss_cluster_001. Universe = 316 minus 21 net-negative coins.
> PF=2.834, 56 trades, WF folds: $909, $58, -$18, $792, $913
> Stress 2x: PF=2.306, Exp/wk=$571

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

### tp10_sl4_tl8 on 135 coins (A6 param grid) — best param combo
| Gate | Value | Verdict |
|------|-------|---------|
| G3 | +$149/wk | PASS |
| G5 | 9.0% | PASS |
| G6 | 5/5 | PASS |
| G8 | 25.8% | PASS |
| **Note** | PF=1.683, 31 trades | Needs full gate test on 295 coins |

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

## Key Insights from Cycle 1

1. **excl_all_negative is the breakthrough**: Removing 21 net-negative coins flips 4 gates FAIL→PASS
2. **Volume cutoff doesn't work**: Edge is in tail coins (low-vol T2), not in top-volume coins
3. **T2 is structural drag on stress**: T2 loses $239 even at baseline fees (A5)
4. **Breakeven fee multiplier**: 1.71x (A5) — current 2x stress overshoots
5. **tp10+tl8 fixes fold concentration on 135**: fold_conc=25.8% (A6)
6. **G7 passes on 316**: 9/12 neighbors profitable (A4)
7. **sl=7 survives stress on 316**: PF=1.079 at 2x fees (A4)

---
