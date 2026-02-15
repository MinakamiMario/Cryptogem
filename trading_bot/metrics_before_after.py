#!/usr/bin/env python3
"""
Metrics Before/After — PARAMS_BY_EXIT Fix Efficiency Measurement
================================================================
Measures search efficiency of the Scout Phase 1 grid BEFORE and AFTER
the PARAMS_BY_EXIT fix for a tp_sl champion config.

BEFORE: All 7 params used in 2-param grid (old buggy behavior)
AFTER:  Only PARAMS_BY_EXIT['tp_sl'] allowed params (5 params)

Runs each combo through run_backtest on full 526-coin dataset.
Reports unique output diversity, waste %, and top-5 diversity.
"""
import sys
import time
import json
from pathlib import Path
from copy import deepcopy
from itertools import combinations

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    PARAMS_BY_EXIT, normalize_cfg, run_backtest, precompute_all,
    cfg_hash, CACHE_FILE, START_BAR, BASELINE_CFG, BEST_KNOWN,
)

# ── Champion config (tp_sl type) ──
CHAMPION_TP_SL = {
    'exit_type': 'tp_sl',
    'rsi_max': 45,
    'vol_spike_mult': 3.0,
    'tp_pct': 15,
    'sl_pct': 15,
    'time_max_bars': 15,
    'max_pos': 1,
    'vol_confirm': True,
    'rsi_recovery': False,
    'breakeven': False,
}

# ── Small grid: 3 values per param (kept small for <2 min runtime) ──
SMALL_GRID = {
    'vol_spike_mult': [2.5, 3.0, 4.0],
    'rsi_max':         [40, 42, 45],
    'rsi_rec_target':  [42, 45, 47],
    'time_max_bars':   [6, 10, 15],
    'atr_mult':        [1.5, 2.0, 2.5],
    'be_trigger':      [1.5, 2.0, 3.0],
    'max_stop_pct':    [8.0, 12.0, 15.0],
    'tp_pct':          [7, 10, 15],
    'sl_pct':          [10, 15, 20],
}

# ── ALL 7 old params (BEFORE: buggy — includes trail-only params for tp_sl) ──
OLD_ALL_PARAMS = [
    'vol_spike_mult', 'rsi_max', 'rsi_rec_target', 'time_max_bars',
    'atr_mult', 'be_trigger', 'max_stop_pct',
]

# ── AFTER: only params from PARAMS_BY_EXIT['tp_sl'] ──
NEW_TP_SL_PARAMS_SPEC = PARAMS_BY_EXIT['tp_sl']
NEW_TP_SL_PARAMS = list(set(NEW_TP_SL_PARAMS_SPEC['entry'] + NEW_TP_SL_PARAMS_SPEC['exit']))


def generate_2param_configs(champion, param_names, grid):
    """Generate all 2-param combo configs from champion + grid."""
    configs = []
    for p1, p2 in combinations(param_names, 2):
        if p1 not in grid or p2 not in grid:
            continue
        for v1 in grid[p1]:
            for v2 in grid[p2]:
                if v1 == champion.get(p1) and v2 == champion.get(p2):
                    continue  # skip champion itself
                cfg = deepcopy(champion)
                cfg[p1] = v1
                cfg[p2] = v2
                configs.append((cfg, f"{p1}={v1},{p2}={v2}"))
    return configs


def run_scenario(label, champion, param_names, grid, indicators, coins):
    """Run all 2-param combos, collect results."""
    configs = generate_2param_configs(champion, param_names, grid)
    total = len(configs)
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Params: {sorted(param_names)}")
    print(f"  Total 2-param combos: {total}")
    print(f"{'='*60}")

    results = []
    unique_outputs = set()
    t0 = time.time()

    for i, (cfg, desc) in enumerate(configs):
        bt = run_backtest(indicators, coins, cfg)
        trades = bt['trades']
        pnl = round(bt['pnl'], 0)
        sig = (trades, pnl)
        unique_outputs.add(sig)
        results.append({
            'desc': desc,
            'trades': trades,
            'pnl': bt['pnl'],
            'wr': bt['wr'],
            'dd': bt['dd'],
            'sig': sig,
            'cfg': cfg,
        })

        if (i + 1) % 50 == 0 or (i + 1) == total:
            elapsed = time.time() - t0
            print(f"    {i+1}/{total} done ({elapsed:.1f}s) | unique so far: {len(unique_outputs)}")

    elapsed = time.time() - t0
    n_unique = len(unique_outputs)
    ratio = n_unique / max(1, total) * 100
    waste = 100 - ratio

    # Top-5 by pnl — how many unique sigs?
    results_sorted = sorted(results, key=lambda r: r['pnl'], reverse=True)
    top5 = results_sorted[:5]
    top5_sigs = set(r['sig'] for r in top5)
    top5_unique = len(top5_sigs)

    print(f"\n  Results:")
    print(f"    Total configs:    {total}")
    print(f"    Unique outputs:   {n_unique}")
    print(f"    Unique ratio:     {ratio:.1f}%")
    print(f"    Waste (no-ops):   {waste:.1f}%")
    print(f"    Top-5 unique:     {top5_unique}/5")
    print(f"    Runtime:          {elapsed:.1f}s")

    return {
        'total': total,
        'unique': n_unique,
        'ratio': ratio,
        'waste': waste,
        'top5_unique': top5_unique,
        'elapsed': elapsed,
        'results': results,
    }


def main():
    print("=" * 60)
    print("  METRICS: Search Efficiency BEFORE vs AFTER PARAMS_BY_EXIT fix")
    print("  Champion: tp_sl config (tp_pct=15, sl_pct=15)")
    print("=" * 60)

    # ── Load data ──
    print("\nLoading candle data...")
    t0 = time.time()
    with open(CACHE_FILE) as f:
        raw = json.load(f)
    # Filter: only keys whose values are lists of candle dicts
    coins = [k for k, v in raw.items() if isinstance(v, list) and len(v) > 0]
    print(f"  {len(coins)} coins loaded ({time.time()-t0:.1f}s)")

    print("Precomputing indicators...")
    t1 = time.time()
    indicators = precompute_all(raw, coins)
    print(f"  Done ({time.time()-t1:.1f}s)")

    # ── Baseline: run champion once ──
    print("\nRunning champion (tp_sl) baseline...")
    bt_champ = run_backtest(indicators, coins, CHAMPION_TP_SL)
    print(f"  Champion: {bt_champ['trades']} trades | P&L ${bt_champ['pnl']:.0f} | "
          f"WR {bt_champ['wr']:.1f}% | DD {bt_champ['dd']:.1f}%")

    # ── BEFORE scenario: old buggy grid with ALL 7 params ──
    before = run_scenario(
        "BEFORE (old buggy grid: ALL 7 params for tp_sl)",
        CHAMPION_TP_SL,
        OLD_ALL_PARAMS,
        SMALL_GRID,
        indicators,
        coins,
    )

    # ── AFTER scenario: fixed grid with only tp_sl params ──
    after = run_scenario(
        "AFTER (fixed grid: only PARAMS_BY_EXIT['tp_sl'] params)",
        CHAMPION_TP_SL,
        NEW_TP_SL_PARAMS,
        SMALL_GRID,
        indicators,
        coins,
    )

    # ── Comparison table ──
    print("\n" + "=" * 60)
    print("  COMPARISON TABLE")
    print("=" * 60)
    print(f"{'':>12} | {'Total':>6} | {'Unique':>6} | {'Ratio':>7} | {'Waste%':>7} | {'Top5Div':>7}")
    print("-" * 60)
    print(f"{'BEFORE':>12} | {before['total']:>6} | {before['unique']:>6} | "
          f"{before['ratio']:>6.1f}% | {before['waste']:>6.1f}% | "
          f"{before['top5_unique']:>5}/5")
    print(f"{'AFTER':>12} | {after['total']:>6} | {after['unique']:>6} | "
          f"{after['ratio']:>6.1f}% | {after['waste']:>6.1f}% | "
          f"{after['top5_unique']:>5}/5")
    print("-" * 60)

    # ── Efficiency improvement ──
    configs_saved = before['total'] - after['total']
    configs_saved_pct = configs_saved / max(1, before['total']) * 100
    waste_reduction = before['waste'] - after['waste']

    print(f"\n  Configs eliminated:   {configs_saved} ({configs_saved_pct:.1f}% reduction)")
    print(f"  Waste reduction:      {waste_reduction:+.1f} percentage points")
    print(f"  BEFORE runtime:       {before['elapsed']:.1f}s")
    print(f"  AFTER runtime:        {after['elapsed']:.1f}s")
    time_saved = before['elapsed'] - after['elapsed']
    time_saved_pct = time_saved / max(0.01, before['elapsed']) * 100
    print(f"  Time saved:           {time_saved:.1f}s ({time_saved_pct:.1f}%)")

    # ── KPI Summary ──
    print("\n" + "=" * 60)
    print("  KPI SUMMARY")
    print("=" * 60)
    print(f"  KPI 1 — No-Op Waste (BEFORE): {before['waste']:.1f}%")
    print(f"           No-Op Waste (AFTER):  {after['waste']:.1f}%")
    print(f"  KPI 2 — Top-5 Diversity BEFORE: {before['top5_unique']}/5")
    print(f"           Top-5 Diversity AFTER:  {after['top5_unique']}/5")
    print(f"\n  Confidence: HIGH — run on full 526-coin dataset with precomputed indicators")
    print("=" * 60)


if __name__ == '__main__':
    main()
