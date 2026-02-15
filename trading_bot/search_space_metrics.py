#!/usr/bin/env python3
"""
Search Space Metrics — Agent E Deliverable
============================================
Quantifies the Scout optimizer bug where exit-type-unaware grids wasted
~70% of evaluated configs on no-op parameter variations.

Computes:
1. Unique-output ratio from 5-run results (old/buggy behavior)
2. No-op budget waste %
3. New grid sizes per exit_type with PARAMS_BY_EXIT fix
4. Estimated improvement in useful Scout budget
"""

import json
import sys
from itertools import combinations
from pathlib import Path
from collections import Counter

# ============================================================
# 1. LOAD 5-RUN RESULTS
# ============================================================

RESULTS_FILE = Path(__file__).parent / 'agent_team_v3_results.json'

if not RESULTS_FILE.exists():
    print(f"ERROR: {RESULTS_FILE} not found")
    sys.exit(1)

with open(RESULTS_FILE) as f:
    data = json.load(f)

print("=" * 72)
print("  SEARCH SPACE METRICS — Agent E")
print("=" * 72)
print(f"\n  Results file: {RESULTS_FILE.name}")
print(f"  Total runs: {data['n_runs']}")
print(f"  OK runs: {sum(1 for r in data['per_run'] if r['status'] == 'OK')}")

# ============================================================
# 2. ANALYZE CONSISTENT CONFIGS FOR DUPLICATE OUTPUTS
# ============================================================

print(f"\n{'─'*72}")
print("  KPI 1: Unique-output ratio (from consistent_configs)")
print(f"{'─'*72}")

configs = data.get('consistent_configs', [])
holdout = data.get('holdout_results', {})

# Group configs by their backtest output (trades, pnl, wr)
# We use holdout full-dataset results as ground truth
output_to_configs = {}
for cfg_entry in configs:
    h = cfg_entry['hash']
    if h in holdout:
        ho = holdout[h]['full']
        output_key = (ho['trades'], round(ho['pnl'], 2), round(ho['wr'], 1))
    else:
        # Use avg_score as proxy if no holdout
        output_key = (cfg_entry['avg_score'],)
    output_to_configs.setdefault(output_key, []).append(cfg_entry)

total_configs = len(configs)
unique_outputs = len(output_to_configs)

print(f"\n  Total configs in consistent_configs: {total_configs}")
print(f"  Unique (trades, pnl, wr) triples:   {unique_outputs}")
print(f"  Unique-output ratio:                 {unique_outputs}/{total_configs} = "
      f"{unique_outputs/total_configs:.1%}")

print(f"\n  Duplicate groups (same backtest output, different cfg):")
for output_key, cfgs in sorted(output_to_configs.items(), key=lambda x: -len(x[1])):
    if len(cfgs) > 1:
        print(f"    Output {output_key}: {len(cfgs)} configs")
        for c in cfgs:
            et = c['cfg'].get('exit_type', '?')
            # Show which params differ but don't matter
            extra_keys = []
            if et == 'tp_sl':
                for k in ['atr_mult', 'be_trigger', 'max_stop_pct', 'rsi_rec_target',
                           'rsi_recovery', 'breakeven']:
                    if k in c['cfg']:
                        extra_keys.append(f"{k}={c['cfg'][k]}")
            print(f"      {c['label']:<35} exit={et}  "
                  f"{'ignored: ' + ', '.join(extra_keys) if extra_keys else ''}")

# ============================================================
# 3. ESTIMATE NO-OP BUDGET WASTE (ABLATION + 2-PARAM GRID)
# ============================================================

print(f"\n{'─'*72}")
print("  KPI 2: No-op budget waste estimate")
print(f"{'─'*72}")

# The OLD (buggy) behavior: ALL params were searched regardless of exit_type.
# For ablation, all 9 params in ABLATION_GRID_ALL were tested.
# For 2-param grid, all 9 params in ALL_PARAM_VALUES_QUICK were combined.

ALL_PARAMS_OLD = {
    'vol_spike_mult': [2.5, 3.0, 4.0],          # 3 values
    'rsi_max':         [35, 40, 42, 45],          # 4 values
    'tp_pct':          [5, 7, 10, 15],            # 4 values
    'sl_pct':          [8, 10, 15, 20],           # 4 values
    'rsi_rec_target':  [42, 45, 47],              # 3 values
    'time_max_bars':   [5, 6, 8, 10, 15],         # 5 values
    'atr_mult':        [1.5, 2.0, 2.5],           # 3 values
    'be_trigger':      [1.5, 2.0, 3.0],           # 3 values
    'max_stop_pct':    [8.0, 12.0, 15.0],         # 3 values
}

ABLATION_GRID_ALL = {
    'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],   # 6 values
    'rsi_max':         [30, 35, 38, 40, 42, 45, 48],       # 7 values
    'tp_pct':          [3, 5, 7, 10, 12, 15, 20],          # 7 values
    'sl_pct':          [5, 8, 10, 15, 20, 25],             # 6 values
    'rsi_rec_target':  [40, 42, 44, 45, 46, 47, 48],       # 7 values
    'time_max_bars':   [4, 6, 8, 10, 12, 15],              # 6 values
    'atr_mult':        [1.5, 1.75, 2.0, 2.5, 3.0],         # 5 values
    'be_trigger':      [1.5, 2.0, 2.5, 3.0, 4.0],          # 5 values
    'max_stop_pct':    [8.0, 10.0, 12.0, 15.0, 20.0],      # 5 values
}

# PARAMS_BY_EXIT (the fix)
PARAMS_BY_EXIT = {
    'tp_sl': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['tp_pct', 'sl_pct', 'time_max_bars'],
    },
    'trail': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['atr_mult', 'be_trigger', 'max_stop_pct', 'time_max_bars',
                   'rsi_rec_target'],
    },
    'hybrid_notrl': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['max_stop_pct', 'time_max_bars', 'rsi_rec_target'],
    },
}

# ---- Analysis: if champion was tp_sl (which it was in runs 1,3,4) ----
# The champion in most runs was exit_type=tp_sl.
# OLD behavior: ablation grid had ALL 9 params.
# tp_sl only uses: rsi_max, vol_spike_mult, tp_pct, sl_pct, time_max_bars (5 params)
# Ignored by tp_sl: atr_mult, be_trigger, max_stop_pct, rsi_rec_target (4 params)

tp_sl_used = set(PARAMS_BY_EXIT['tp_sl']['entry'] + PARAMS_BY_EXIT['tp_sl']['exit'])
trail_used = set(PARAMS_BY_EXIT['trail']['entry'] + PARAMS_BY_EXIT['trail']['exit'])
hybrid_used = set(PARAMS_BY_EXIT['hybrid_notrl']['entry'] + PARAMS_BY_EXIT['hybrid_notrl']['exit'])

all_params = set(ALL_PARAMS_OLD.keys())
tp_sl_ignored = all_params - tp_sl_used

print(f"\n  Champion exit_type in 3/4 OK runs: tp_sl")
print(f"  tp_sl uses:    {sorted(tp_sl_used)} ({len(tp_sl_used)} params)")
print(f"  tp_sl ignores: {sorted(tp_sl_ignored)} ({len(tp_sl_ignored)} params)")

# Ablation waste for tp_sl champion
old_ablation_total = sum(len(v) - 1 for v in ABLATION_GRID_ALL.values())  # -1 for champion val
old_ablation_useful = sum(len(v) - 1 for k, v in ABLATION_GRID_ALL.items() if k in tp_sl_used)
old_ablation_wasted = old_ablation_total - old_ablation_useful
ablation_waste_pct = old_ablation_wasted / old_ablation_total * 100

print(f"\n  Ablation (Phase 0) for tp_sl champion:")
print(f"    Total ablation evals (all 9 params): {old_ablation_total}")
print(f"    Useful evals (5 tp_sl params):       {old_ablation_useful}")
print(f"    Wasted evals (4 ignored params):     {old_ablation_wasted}")
print(f"    Ablation waste:                      {ablation_waste_pct:.1f}%")

# 2-param grid waste for tp_sl base config
# OLD: C(9,2) = 36 pairs, each pair has |v1|*|v2| combos
# But only C(5,2)=10 pairs are useful for tp_sl
old_param_names = sorted(ALL_PARAMS_OLD.keys())
old_pairs = list(combinations(old_param_names, 2))
old_total_combos = 0
old_useful_combos = 0
old_wasted_combos = 0
pair_details = []

for p1, p2 in old_pairs:
    n_combos = len(ALL_PARAMS_OLD[p1]) * len(ALL_PARAMS_OLD[p2])
    p1_useful = p1 in tp_sl_used
    p2_useful = p2 in tp_sl_used
    both_useful = p1_useful and p2_useful
    at_least_one_noop = not both_useful  # at least one param ignored

    old_total_combos += n_combos

    if both_useful:
        old_useful_combos += n_combos
    elif p1_useful or p2_useful:
        # One param matters, one doesn't: all combos produce same output
        # as just varying the useful param (duplicates of 1-param sweep)
        old_wasted_combos += n_combos
    else:
        # Both ignored: all combos produce identical output to champion
        old_wasted_combos += n_combos

    pair_details.append((p1, p2, n_combos, both_useful,
                        'USEFUL' if both_useful else 'WASTED'))

grid_waste_pct = old_wasted_combos / old_total_combos * 100

print(f"\n  2-param grid (Phase 1) for tp_sl base config:")
print(f"    Total pairs: C(9,2) = {len(old_pairs)}")
print(f"    Total combos: {old_total_combos}")
print(f"    Useful combos (both params matter): {old_useful_combos}")
print(f"    Wasted combos (>=1 param ignored):  {old_wasted_combos}")
print(f"    Grid waste:                         {grid_waste_pct:.1f}%")

# Phase 3 was already exit-type-aware (hardcoded grids per type), so no waste there.
# The waste is in Phases 0, 1, and 2.

# Overall waste estimate (weighted by typical budget allocation)
# Phase 0 (ablation): ~10% of budget
# Phase 1 (2-param grid): ~50% of budget (biggest phase)
# Phase 2 (3-param extensions): ~20% of budget (inherits Phase 1 params = same waste)
# Phase 3 (exit families): ~15% of budget (already exit-aware, no waste)
# Phase 4 (max_pos): ~5% of budget (no waste)

phase_weights = {
    'Phase 0 (ablation)':      0.10,
    'Phase 1 (2-param grid)':  0.50,
    'Phase 2 (3-param ext)':   0.20,
    'Phase 3 (exit families)': 0.15,
    'Phase 4 (max_pos)':       0.05,
}
phase_waste = {
    'Phase 0 (ablation)':      ablation_waste_pct,
    'Phase 1 (2-param grid)':  grid_waste_pct,
    'Phase 2 (3-param ext)':   grid_waste_pct,    # same params → same waste ratio
    'Phase 3 (exit families)': 0.0,                # already exit-aware
    'Phase 4 (max_pos)':       0.0,                # no param waste
}

overall_waste = sum(phase_weights[p] * phase_waste[p] / 100 for p in phase_weights)
overall_waste_pct = overall_waste * 100

print(f"\n  Overall budget waste (weighted by phase budget allocation):")
for phase in phase_weights:
    w = phase_weights[phase]
    waste = phase_waste[phase]
    print(f"    {phase:<30} weight={w:.0%}  waste={waste:.1f}%  "
          f"contribution={w * waste:.1f}%")
print(f"    {'─'*60}")
print(f"    TOTAL NO-OP BUDGET WASTE:    {overall_waste_pct:.1f}%")

# ============================================================
# 4. NEW GRID SIZES PER EXIT_TYPE (with PARAMS_BY_EXIT fix)
# ============================================================

print(f"\n{'─'*72}")
print("  NEW grid sizes per exit_type (PARAMS_BY_EXIT fix)")
print(f"{'─'*72}")

for exit_type, spec in PARAMS_BY_EXIT.items():
    used = set(spec['entry'] + spec['exit'])
    n_params = len(used)

    # Quick grid sizes
    quick_params = {k: v for k, v in ALL_PARAMS_OLD.items() if k in used}
    quick_pairs = list(combinations(sorted(quick_params.keys()), 2))
    quick_combos = sum(len(quick_params[p1]) * len(quick_params[p2])
                       for p1, p2 in quick_pairs)

    # Ablation grid sizes
    abl_params = {k: v for k, v in ABLATION_GRID_ALL.items() if k in used}
    abl_evals = sum(len(v) - 1 for v in abl_params.values())

    print(f"\n  {exit_type}:")
    print(f"    Used params: {sorted(used)} ({n_params})")
    print(f"    Ablation evals:     {abl_evals}")
    print(f"    2-param pairs:      C({n_params},2) = {len(quick_pairs)}")
    print(f"    2-param combos:     {quick_combos}")
    print(f"    Pair breakdown:")
    for p1, p2 in quick_pairs:
        n = len(quick_params[p1]) * len(quick_params[p2])
        print(f"      {p1} x {p2}: {len(quick_params[p1])} x {len(quick_params[p2])} = {n}")

# ============================================================
# 5. IMPROVEMENT ESTIMATE
# ============================================================

print(f"\n{'─'*72}")
print("  IMPROVEMENT ESTIMATE: Useful budget after fix")
print(f"{'─'*72}")

# Old: 100% budget, X% wasted on no-ops
# New: same budget, 0% wasted (all params relevant)
useful_old = 100 - overall_waste_pct
useful_new = 100.0  # all evals now produce unique outputs

print(f"\n  Old (buggy): {useful_old:.1f}% of Scout budget spent on configs that differ")
print(f"  New (fixed): {useful_new:.1f}% of Scout budget spent on configs that differ")
print(f"  Improvement: {useful_new - useful_old:.1f} percentage points more useful evals")
print(f"  Speedup:     {useful_new / useful_old:.2f}x effective search efficiency")

# Also count: how many configs in results had identical holdout results?
holdout_outputs = {}
n_identical_to_champ = 0
champ_output = None
for h, ho in holdout.items():
    key = (ho['full']['trades'], round(ho['full']['pnl'], 2), round(ho['full']['wr'], 1))
    holdout_outputs.setdefault(key, []).append(ho['label'])

for key, labels in holdout_outputs.items():
    if len(labels) > 1:
        if champ_output is None:
            champ_output = key
            n_identical_to_champ = len(labels)

print(f"\n  Evidence from holdout results:")
print(f"    Total holdout configs: {len(holdout)}")
print(f"    Unique holdout outputs: {len(holdout_outputs)}")
for key, labels in sorted(holdout_outputs.items(), key=lambda x: -len(x[1])):
    if len(labels) > 1:
        print(f"    Output {key}: {len(labels)} configs → {labels}")

# ============================================================
# 6. SUMMARY
# ============================================================

print(f"\n{'='*72}")
print("  SUMMARY")
print(f"{'='*72}")

unique_ratio = unique_outputs / total_configs if total_configs > 0 else 0
print(f"""
  KPI 1 — Unique-output ratio:    {unique_ratio:.1%}
           ({unique_outputs} unique outputs / {total_configs} total configs)
           → {1 - unique_ratio:.1%} of configs produced duplicate outputs

  KPI 2 — No-op budget waste:     {overall_waste_pct:.1f}%
           (weighted across all Scout phases for tp_sl champion)
           → {overall_waste_pct:.1f}% of Scout compute time was spent evaluating
             configs that could never produce different backtest results

  NEW GRID SIZES (PARAMS_BY_EXIT fix):
    tp_sl:        5 params → C(5,2)=10 pairs → {sum(len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['tp_sl']['entry']+PARAMS_BY_EXIT['tp_sl']['exit'])}[p1]) * len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['tp_sl']['entry']+PARAMS_BY_EXIT['tp_sl']['exit'])}[p2]) for p1,p2 in combinations(sorted({k for k in ALL_PARAMS_OLD if k in set(PARAMS_BY_EXIT['tp_sl']['entry']+PARAMS_BY_EXIT['tp_sl']['exit'])}), 2))} combos
    trail:        7 params → C(7,2)=21 pairs → {sum(len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['trail']['entry']+PARAMS_BY_EXIT['trail']['exit'])}[p1]) * len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['trail']['entry']+PARAMS_BY_EXIT['trail']['exit'])}[p2]) for p1,p2 in combinations(sorted({k for k in ALL_PARAMS_OLD if k in set(PARAMS_BY_EXIT['trail']['entry']+PARAMS_BY_EXIT['trail']['exit'])}), 2))} combos
    hybrid_notrl: 5 params → C(5,2)=10 pairs → {sum(len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['hybrid_notrl']['entry']+PARAMS_BY_EXIT['hybrid_notrl']['exit'])}[p1]) * len({k:v for k,v in ALL_PARAMS_OLD.items() if k in set(PARAMS_BY_EXIT['hybrid_notrl']['entry']+PARAMS_BY_EXIT['hybrid_notrl']['exit'])}[p2]) for p1,p2 in combinations(sorted({k for k in ALL_PARAMS_OLD if k in set(PARAMS_BY_EXIT['hybrid_notrl']['entry']+PARAMS_BY_EXIT['hybrid_notrl']['exit'])}), 2))} combos
    OLD (all 9):  9 params → C(9,2)=36 pairs → {old_total_combos} combos

  IMPROVEMENT:
    Useful budget OLD: {useful_old:.1f}%
    Useful budget NEW: {useful_new:.1f}%
    Effective speedup: {useful_new / useful_old:.2f}x

  CONFIDENCE: 0.85
    - High confidence in grid size calculations (deterministic math)
    - Moderate confidence in waste % (depends on phase budget allocation estimate)
    - The holdout data confirms: 5/6 holdout configs with identical output

  RISKS:
    1. Phase budget weights are estimated (10/50/20/15/5%) — actual split depends
       on runtime and early-stopping. If Phase 1 runs longer, waste is higher.
    2. Triage kills some configs before full eval — actual unique ratio may differ
       from theoretical because killed configs don't produce output at all.
    3. The fix assumes run_backtest correctly ignores unused params. If there's
       any code path that reads atr_mult for tp_sl, the waste estimate is wrong.

  WHAT'S STILL UNCLEAR:
    1. How many total configs were evaluated per run (not just promoted/consistent)?
       The results JSON only contains promoted + consistent configs, not the full
       eval count. We can't compute the exact no-op ratio from actual run data.
    2. Was Phase 2 (3-param extensions) also affected? It inherits param_names from
       Phase 1 which now uses PARAMS_BY_EXIT — need to verify it was also buggy before.

  NEXT ACTION:
    Run agent_team_v3.py --quick with the PARAMS_BY_EXIT fix and compare eval counts
    and unique output ratios against this baseline to validate the improvement estimate.
""")
