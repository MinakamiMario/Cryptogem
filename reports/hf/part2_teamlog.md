# Part 2 Team Log — 48h Iteration Loop

> Started: 2026-02-16
> Branch: hf-part2
> Objective: Find universe + H20 variant that passes all 8 hard gates

---

## Cycle 1

### Assignments
| Agent | Task | Status |
|-------|------|--------|
| A1 (Universe Slicer) | Volume-cutoff sweep: top-N coins by volume | ✅ DONE |
| A2 (T1-Only) | Run v5 on T1 (100 coins) only | ✅ DONE |
| A3 (Loss Cluster) | Identify worst-performing coins, test exclusion | ✅ DONE |
| A4 (Robustness) | 12-variant neighborhood sweep on 316 coins | ✅ DONE |
| A5 (Stress Modeler) | Alternative stress models on 316 coins | ✅ DONE |
| A6 (Param Explorer) | 48-combo param grid on 135 coins | ✅ DONE |

### Agent Log Entries

#### A1 — Volume Cutoff Sweep
- **Report**: `part2_volume_cutoff_sweep_001.json` + `.md`
- **Attempt**: Sorted 316 coins by median hourly dollar volume, tested N=50,75,100,135,150,175,200,250,316
- **Metrics**: N=316 best at 3/7 gates; all smaller N <= 1/7 gates
- **Learnings**: Edge is NOT in high-volume coins. Top-50 by volume = 0 trades. Signal fires on tail coins. Volume cutoff approach is a dead end.
- **Next move**: → Abandon volume cutoff. Focus on coin exclusion (A3's approach).

#### A2 — T1-Only Test
- **Report**: `part2_t1_only_001.json` + `.md`
- **Attempt**: v5 (tp=8) and tp=10 on T1 only (100 coins, 12.5bps fee)
- **Metrics**: 21 trades, PF=1.875, WR=66.7%, Exp/wk=$142, DD=24%, WF=3/5, fold_conc=66.6%
- **Learnings**: Only 15 coins produce trades on T1, only 21 trades total (4.89/wk). XL1/USD dominates (48% of P&L). Fails G1 (<10/wk) and G8 (>35% fold conc). Too few trades for robust strategy.
- **Next move**: → T1-only rejected. Need broader universe. Combine with A3's exclusion approach.

#### A3 — Loss Cluster Analysis ⭐ BREAKTHROUGH
- **Report**: `part2_loss_cluster_001.json` + `.md`
- **Attempt**: Per-coin PnL attribution on 316 coins, test 5 exclusion strategies
- **Metrics**:
  - baseline_316: 3/7 gates
  - excl_worst5: 4/7 (G4 flips PASS)
  - excl_worst10: 5/7 (G6 flips PASS)
  - excl_all_negative: **7/7 gates** (G4, G5, G6, G8 all flip PASS)
  - excl_1trade_losers: 4/7
- **Learnings**: 21 coins are net-negative (total -$2097). Removing them → PF=2.834, DD=8.6%, WF=4/5, fold_conc=34.2%. This is the first candidate to pass all testable gates. Critical caveat: this uses in-sample knowledge of which coins lose.
- **Next move**: → LEADER CANDIDATE. Needs G7 robustness test + out-of-sample validation.

#### A4 — Robustness 316
- **Report**: `part2_robustness_316_001.json` + `.md`
- **Attempt**: 12-variant neighborhood sweep (dev_thresh, tp, sl, tl) on full 316 coins
- **Metrics**: G7 PASS: 9/12 variants PF>1.0. sl=7 best (score 115.8, PF=1.285). 5 variants survive stress 2x.
- **Learnings**: WF stuck at 3/5 across ALL variants on 316 coins — structural, not parameter-driven. sl=7 (wider SL) is most stress-resilient. dev_thresh most sensitive (2.2+ goes negative).
- **Next move**: → G7 PASS confirmed on 316. Test G7 on excl_all_negative universe.

#### A5 — Stress Model Analysis
- **Report**: `part2_stress_models_001.json` + `.md`
- **Attempt**: 6 named scenarios + 16-step fee ladder + breakeven binary search on 316 coins
- **Metrics**: Breakeven at 1.705x uniform multiplier. Only 2/6 named scenarios pass G4. T2 loses $239 at baseline fees (51 trades).
- **Learnings**: T2 is structurally unprofitable. Even "friendliest" tiered stress (T1=1.5x, T2=2x) fails. No stress model redesign saves the full 316-coin universe. Solution must come from universe reduction.
- **Next move**: → Stress model analysis complete. Confirms A3's exclusion approach is the right direction.

#### A6 — Param Grid 135
- **Report**: `part2_param_grid_135_001.json` + `.md`
- **Attempt**: 48-combo grid (tp=[6,8,10,12] × sl=[3,4,5,7] × tl=[6,8,10]) on 135 coins
- **Metrics**: 4 configs pass G8 (fold_conc < 35%) + exp>0 + WF>=4/5. Best: tp10_sl4_tl8 (PF=1.683, fold_conc=25.8%, WF=5/5, DD=9.0%, score=148.6)
- **Learnings**: tp=10 + tl=8 breaks fold concentration by shifting dominant fold from F3 to F2. Fold 3 dominates in 94% of configs — structural market effect. The tp10+tl8 combo is the fix.
- **Next move**: → Test tp10_sl4_tl8 on excl_all_negative universe (295 coins).

### Cycle 1 Synthesis

**The winning direction: excl_all_negative (295 coins) + param combo (tp10_sl4_tl8)**

A3 found that removing 21 net-negative coins passes 7/7 gates with v5 params.
A6 found that tp10+tl8 fixes fold concentration (25.8% vs 48.6%).
Combining both should yield an even stronger candidate.

**Key risk**: excl_all_negative uses in-sample coin selection. Out-of-sample validation needed.

---
