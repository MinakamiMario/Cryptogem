#!/usr/bin/env python3
"""
Regression tests voor parameter sensitivity fixes.

Test 1: tm_bars alias → time_max_bars werkt in alle exit branches
Test 2: elke grid-param bij zijn exit_type heeft meetbaar effect
Test 3: warn_unused_params detecteert dode params
Test 4: normalize_cfg migreert legacy keys correct
Test 5: used_keys_for returns correct key sets
Test 6: irrelevant params produce identical results at tp_sl
Test 7: Scout grid filtering unit test
Test 8: edge cases (normalize_cfg, used_keys_for, warn_unused_params)
Test 9: hybrid_notrl in used_keys_for
Test 10: save_champion writes canonical keys (normalize_cfg on legacy cfg)

Gebruik:
    python3 trading_bot/test_param_sensitivity.py
"""
import json, sys, os
from copy import deepcopy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_team_v3 import (
    run_backtest, precompute_all, normalize_cfg, warn_unused_params,
    used_keys_for, cfg_hash, PARAMS_BY_EXIT, CACHE_FILE, START_BAR,
)

# ======== Shared setup ========
print("Loading dataset...")
with open(CACHE_FILE) as f:
    data = json.load(f)
coins = sorted([k for k in data if not k.startswith('_')])
indicators = precompute_all(data, coins)
print(f"Loaded {len(coins)} coins\n")

passed = 0
failed = 0

def test(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}: {detail}")


# ======== TEST 1: tm_bars alias ========
print("=" * 70)
print("TEST 1: tm_bars alias → time_max_bars werkt in alle exit branches")
print("=" * 70)

for exit_type in ['tp_sl', 'trail', 'hybrid_notrl']:
    # Config met legacy tm_bars key
    cfg_legacy = {
        'exit_type': exit_type, 'rsi_max': 40, 'vol_spike_mult': 3.0,
        'vol_confirm': True, 'max_pos': 1,
        'tm_bars': 8,  # LEGACY key
    }
    # Config met canonical time_max_bars key
    cfg_canonical = {
        'exit_type': exit_type, 'rsi_max': 40, 'vol_spike_mult': 3.0,
        'vol_confirm': True, 'max_pos': 1,
        'time_max_bars': 8,  # CANONICAL key
    }
    # Extra exit-specific params
    if exit_type == 'tp_sl':
        for c in [cfg_legacy, cfg_canonical]:
            c.update({'tp_pct': 15, 'sl_pct': 15})
    elif exit_type == 'trail':
        for c in [cfg_legacy, cfg_canonical]:
            c.update({'atr_mult': 2.0, 'be_trigger': 3.0, 'max_stop_pct': 15.0,
                       'breakeven': True, 'rsi_recovery': True, 'rsi_rec_target': 45})
    elif exit_type == 'hybrid_notrl':
        for c in [cfg_legacy, cfg_canonical]:
            c.update({'max_stop_pct': 15.0, 'rsi_recovery': True, 'rsi_rec_target': 45})

    bt_legacy = run_backtest(indicators, coins, cfg_legacy)
    bt_canonical = run_backtest(indicators, coins, cfg_canonical)

    test(f"{exit_type}: tm_bars=8 == time_max_bars=8",
         bt_legacy['trades'] == bt_canonical['trades']
         and round(bt_legacy['pnl'], 2) == round(bt_canonical['pnl'], 2),
         f"legacy: {bt_legacy['trades']}tr ${bt_legacy['pnl']:+,.0f} vs "
         f"canonical: {bt_canonical['trades']}tr ${bt_canonical['pnl']:+,.0f}")

    # Verify different value actually changes result
    cfg_diff = deepcopy(cfg_canonical)
    cfg_diff['time_max_bars'] = 3  # very short → more TIME MAX exits
    bt_diff = run_backtest(indicators, coins, cfg_diff)

    test(f"{exit_type}: time_max_bars=3 ≠ time_max_bars=8",
         bt_diff['trades'] != bt_canonical['trades']
         or round(bt_diff['pnl'], 2) != round(bt_canonical['pnl'], 2),
         f"tm=3: {bt_diff['trades']}tr ${bt_diff['pnl']:+,.0f} vs "
         f"tm=8: {bt_canonical['trades']}tr ${bt_canonical['pnl']:+,.0f}")


# ======== TEST 2: Grid-param effect per exit_type ========
print("\n" + "=" * 70)
print("TEST 2: Elke grid-param heeft meetbaar effect bij zijn exit_type")
print("=" * 70)

# Base configs per exit_type
BASES = {
    'tp_sl': {
        'exit_type': 'tp_sl', 'rsi_max': 40, 'vol_spike_mult': 3.0,
        'vol_confirm': True, 'max_pos': 1,
        'tp_pct': 15, 'sl_pct': 15, 'time_max_bars': 15,
    },
    'trail': {
        'exit_type': 'trail', 'rsi_max': 40, 'vol_spike_mult': 3.0,
        'vol_confirm': True, 'max_pos': 1,
        'atr_mult': 2.0, 'be_trigger': 3.0, 'max_stop_pct': 15.0, 'time_max_bars': 10,
        'breakeven': True, 'rsi_recovery': True, 'rsi_rec_target': 45,
    },
    'hybrid_notrl': {
        'exit_type': 'hybrid_notrl', 'rsi_max': 40, 'vol_spike_mult': 3.0,
        'vol_confirm': True, 'max_pos': 1,
        'max_stop_pct': 15.0, 'time_max_bars': 15,
        'rsi_recovery': True, 'rsi_rec_target': 45,
    },
}

# Per grid-param: 2 extreme waarden die verschil MOETEN opleveren
EXTREMES = {
    'rsi_max':         (25, 70),
    'vol_spike_mult':  (1.5, 5.0),
    'tp_pct':          (3, 25),
    'sl_pct':          (5, 25),
    'time_max_bars':   (3, 50),
    'atr_mult':        (1.0, 4.0),
    'be_trigger':      (1.0, 5.0),
    'max_stop_pct':    (5.0, 30.0),
    'rsi_rec_target':  (30, 55),
}

for exit_type, spec in PARAMS_BY_EXIT.items():
    all_params = spec['entry'] + spec['exit']
    base = BASES[exit_type]
    bt_base = run_backtest(indicators, coins, base)
    base_sig = (bt_base['trades'], round(bt_base['pnl'], 2))

    for param in all_params:
        if param not in EXTREMES:
            continue
        lo, hi = EXTREMES[param]

        cfg_lo = deepcopy(base)
        cfg_lo[param] = lo
        bt_lo = run_backtest(indicators, coins, cfg_lo)
        sig_lo = (bt_lo['trades'], round(bt_lo['pnl'], 2))

        cfg_hi = deepcopy(base)
        cfg_hi[param] = hi
        bt_hi = run_backtest(indicators, coins, cfg_hi)
        sig_hi = (bt_hi['trades'], round(bt_hi['pnl'], 2))

        # Extreme values moeten van elkaar verschillen
        test(f"{exit_type}/{param}: {lo} ≠ {hi}",
             sig_lo != sig_hi,
             f"lo={sig_lo} hi={sig_hi} — NO EFFECT!")


# ======== TEST 3: warn_unused_params detecteert dode params ========
print("\n" + "=" * 70)
print("TEST 3: warn_unused_params detecteert dode params correct")
print("=" * 70)

# tp_sl cfg met trail-only params → should warn
cfg_bad = {
    'exit_type': 'tp_sl', 'rsi_max': 40, 'vol_spike_mult': 3.0,
    'tp_pct': 15, 'sl_pct': 15, 'time_max_bars': 15,
    'atr_mult': 2.0,       # ← dead in tp_sl
    'be_trigger': 3.0,     # ← dead in tp_sl
    'max_stop_pct': 15.0,  # ← dead in tp_sl
}
unused = warn_unused_params(cfg_bad, 'test3-bad')
test("tp_sl + trail-only params → warns about atr_mult, be_trigger, max_stop_pct",
     set(unused) >= {'atr_mult', 'be_trigger', 'max_stop_pct'},
     f"got unused={unused}")

# Clean tp_sl cfg → should NOT warn
cfg_clean = {
    'exit_type': 'tp_sl', 'rsi_max': 40, 'vol_spike_mult': 3.0,
    'tp_pct': 15, 'sl_pct': 15, 'time_max_bars': 15, 'max_pos': 1,
    'vol_confirm': True,
}
unused_clean = warn_unused_params(cfg_clean, 'test3-clean')
test("clean tp_sl cfg → no warnings",
     len(unused_clean) == 0,
     f"got unused={unused_clean}")

# trail cfg → should NOT warn about its own params
cfg_trail = {
    'exit_type': 'trail', 'rsi_max': 40, 'vol_spike_mult': 3.0,
    'atr_mult': 2.0, 'be_trigger': 3.0, 'max_stop_pct': 15.0,
    'time_max_bars': 10, 'rsi_rec_target': 45,
    'max_pos': 1, 'vol_confirm': True, 'rsi_recovery': True, 'breakeven': True,
}
unused_trail = warn_unused_params(cfg_trail, 'test3-trail')
test("trail cfg → no warnings",
     len(unused_trail) == 0,
     f"got unused={unused_trail}")


# ======== TEST 4: normalize_cfg ========
print("\n" + "=" * 70)
print("TEST 4: normalize_cfg migreert legacy keys correct")
print("=" * 70)

# Legacy tm_bars → time_max_bars
cfg1 = normalize_cfg({'exit_type': 'tp_sl', 'tm_bars': 15, 'tp_pct': 10})
test("tm_bars migrated to time_max_bars",
     'time_max_bars' in cfg1 and 'tm_bars' not in cfg1
     and cfg1['time_max_bars'] == 15,
     f"got {cfg1}")

# Both keys present → canonical wins, tm_bars removed
cfg2 = normalize_cfg({'exit_type': 'tp_sl', 'tm_bars': 10, 'time_max_bars': 15})
test("both keys → time_max_bars wins, tm_bars removed",
     cfg2['time_max_bars'] == 15 and 'tm_bars' not in cfg2,
     f"got {cfg2}")

# Already canonical → no change
cfg3 = normalize_cfg({'exit_type': 'trail', 'time_max_bars': 8})
test("canonical key unchanged",
     cfg3['time_max_bars'] == 8 and 'tm_bars' not in cfg3,
     f"got {cfg3}")

# Hash consistency: normalized tm_bars and time_max_bars → same hash
cfg_a = normalize_cfg({'exit_type': 'tp_sl', 'tm_bars': 15, 'tp_pct': 10, 'sl_pct': 15})
cfg_b = normalize_cfg({'exit_type': 'tp_sl', 'time_max_bars': 15, 'tp_pct': 10, 'sl_pct': 15})
test("normalized legacy and canonical → same hash",
     cfg_hash(cfg_a) == cfg_hash(cfg_b),
     f"hash_a={cfg_hash(cfg_a)} hash_b={cfg_hash(cfg_b)}")


# ======== TEST 5: used_keys_for correctness ========
print("\n" + "=" * 70)
print("TEST 5: used_keys_for returns correct key sets")
print("=" * 70)

tp_sl_keys = used_keys_for('tp_sl')
test("tp_sl includes tp_pct, sl_pct, time_max_bars",
     {'tp_pct', 'sl_pct', 'time_max_bars'}.issubset(tp_sl_keys),
     f"got {tp_sl_keys}")
test("tp_sl does NOT include atr_mult, be_trigger",
     'atr_mult' not in tp_sl_keys and 'be_trigger' not in tp_sl_keys,
     f"got {tp_sl_keys}")

trail_keys = used_keys_for('trail')
test("trail includes atr_mult, be_trigger, max_stop_pct, rsi_rec_target",
     {'atr_mult', 'be_trigger', 'max_stop_pct', 'rsi_rec_target'}.issubset(trail_keys),
     f"got {trail_keys}")
test("trail does NOT include tp_pct, sl_pct",
     'tp_pct' not in trail_keys and 'sl_pct' not in trail_keys,
     f"got {trail_keys}")


# ======== TEST 6: Irrelevant params produce identical results at tp_sl ========
print("\n" + "=" * 70)
print("TEST 6: Irrelevant trail-only params produce identical results at tp_sl")
print("=" * 70)

base_tp_sl = {
    'exit_type': 'tp_sl', 'rsi_max': 40, 'vol_spike_mult': 3.0,
    'vol_confirm': True, 'max_pos': 1,
    'tp_pct': 15, 'sl_pct': 15, 'time_max_bars': 15,
}
bt_base_tp = run_backtest(indicators, coins, base_tp_sl)
base_sig_tp = (bt_base_tp['trades'], round(bt_base_tp['pnl'], 2))

# Trail-only params: atr_mult, be_trigger, max_stop_pct, rsi_rec_target
# Varying these should produce IDENTICAL results for tp_sl
TRAIL_ONLY_EXTREMES = {
    'atr_mult':       (0.5, 10.0),
    'be_trigger':     (0.5, 10.0),
    'max_stop_pct':   (1.0, 50.0),
    'rsi_rec_target': (20, 70),
}

for param, (lo, hi) in TRAIL_ONLY_EXTREMES.items():
    cfg_lo = deepcopy(base_tp_sl)
    cfg_lo[param] = lo
    bt_lo = run_backtest(indicators, coins, cfg_lo)
    sig_lo = (bt_lo['trades'], round(bt_lo['pnl'], 2))

    cfg_hi = deepcopy(base_tp_sl)
    cfg_hi[param] = hi
    bt_hi = run_backtest(indicators, coins, cfg_hi)
    sig_hi = (bt_hi['trades'], round(bt_hi['pnl'], 2))

    test(f"tp_sl + {param}={lo} == base",
         sig_lo == base_sig_tp,
         f"lo={sig_lo} base={base_sig_tp}")
    test(f"tp_sl + {param}={hi} == base",
         sig_hi == base_sig_tp,
         f"hi={sig_hi} base={base_sig_tp}")


# ======== TEST 7: Scout grid filtering unit test ========
print("\n" + "=" * 70)
print("TEST 7: Scout grid filtering — PARAMS_BY_EXIT correctly filters grids")
print("=" * 70)

# Reconstruct ALL_PARAM_VALUES_QUICK (local to agent_scout, so inline here)
ALL_PARAM_VALUES_QUICK = {
    'vol_spike_mult': [2.5, 3.0, 4.0],
    'rsi_max':         [35, 40, 42, 45],
    'tp_pct':          [5, 7, 10, 15],
    'sl_pct':          [8, 10, 15, 20],
    'rsi_rec_target':  [42, 45, 47],
    'time_max_bars':   [5, 6, 8, 10, 15],
    'atr_mult':        [1.5, 2.0, 2.5],
    'be_trigger':      [1.5, 2.0, 3.0],
    'max_stop_pct':    [8.0, 12.0, 15.0],
}

for exit_type in ['tp_sl', 'trail', 'hybrid_notrl']:
    spec = PARAMS_BY_EXIT[exit_type]
    allowed_keys = set(spec['entry'] + spec['exit'])
    filtered_grid = {k: v for k, v in ALL_PARAM_VALUES_QUICK.items() if k in allowed_keys}

    if exit_type == 'tp_sl':
        test("tp_sl grid does NOT contain atr_mult",
             'atr_mult' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("tp_sl grid does NOT contain be_trigger",
             'be_trigger' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("tp_sl grid does NOT contain rsi_rec_target",
             'rsi_rec_target' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
    elif exit_type == 'trail':
        test("trail grid does NOT contain tp_pct",
             'tp_pct' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("trail grid does NOT contain sl_pct",
             'sl_pct' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
    elif exit_type == 'hybrid_notrl':
        test("hybrid_notrl grid does NOT contain atr_mult",
             'atr_mult' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("hybrid_notrl grid does NOT contain be_trigger",
             'be_trigger' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("hybrid_notrl grid does NOT contain tp_pct",
             'tp_pct' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")
        test("hybrid_notrl grid does NOT contain sl_pct",
             'sl_pct' not in filtered_grid,
             f"grid keys={sorted(filtered_grid.keys())}")


# ======== TEST 8: Edge cases ========
print("\n" + "=" * 70)
print("TEST 8: Edge cases (normalize_cfg, used_keys_for, warn_unused_params)")
print("=" * 70)

# normalize_cfg({}) returns {}
ec1 = normalize_cfg({})
test("normalize_cfg({}) returns {}",
     ec1 == {},
     f"got {ec1}")

# normalize_cfg with exit_type only, no time keys → no crash
ec2 = normalize_cfg({'exit_type': 'tp_sl'})
test("normalize_cfg({'exit_type': 'tp_sl'}) returns same (no crash)",
     ec2 == {'exit_type': 'tp_sl'},
     f"got {ec2}")

# used_keys_for('unknown_type') falls back to trail keys (not crash)
unk_keys = used_keys_for('unknown_type')
trail_ref = used_keys_for('trail')
test("used_keys_for('unknown_type') falls back to trail keys",
     unk_keys == trail_ref,
     f"unknown={unk_keys} trail={trail_ref}")

# warn_unused_params flags 'garbage' but not valid tp_sl keys
cfg_garbage = {
    'exit_type': 'tp_sl', 'garbage': 42, 'time_max_bars': 10,
    'tp_pct': 15, 'sl_pct': 15, 'rsi_max': 40, 'vol_spike_mult': 3.0,
}
unused_garbage = warn_unused_params(cfg_garbage, 'test8-garbage')
test("warn_unused_params flags 'garbage' key",
     'garbage' in unused_garbage,
     f"got unused={unused_garbage}")
test("warn_unused_params does NOT flag valid tp_sl keys",
     'tp_pct' not in unused_garbage and 'sl_pct' not in unused_garbage
     and 'time_max_bars' not in unused_garbage,
     f"got unused={unused_garbage}")


# ======== TEST 9: hybrid_notrl in used_keys_for ========
print("\n" + "=" * 70)
print("TEST 9: hybrid_notrl in used_keys_for — correct inclusions/exclusions")
print("=" * 70)

hn_keys = used_keys_for('hybrid_notrl')
test("hybrid_notrl includes time_max_bars",
     'time_max_bars' in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl includes max_stop_pct",
     'max_stop_pct' in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl includes rsi_rec_target",
     'rsi_rec_target' in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl does NOT include atr_mult",
     'atr_mult' not in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl does NOT include be_trigger",
     'be_trigger' not in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl does NOT include tp_pct",
     'tp_pct' not in hn_keys,
     f"got {hn_keys}")
test("hybrid_notrl does NOT include sl_pct",
     'sl_pct' not in hn_keys,
     f"got {hn_keys}")


# ======== TEST 10: save_champion writes canonical keys ========
print("\n" + "=" * 70)
print("TEST 10: normalize_cfg produces canonical keys (no legacy tm_bars)")
print("=" * 70)

# Simulate what save_champion does: normalize a legacy cfg
legacy_cfg = {
    'exit_type': 'trail', 'tm_bars': 10, 'atr_mult': 2.0,
    'be_trigger': 3.0, 'rsi_max': 42, 'vol_spike_mult': 3.0,
    'max_stop_pct': 12.0, 'rsi_rec_target': 45,
}
normalized = normalize_cfg(deepcopy(legacy_cfg))
test("normalized cfg contains 'time_max_bars'",
     'time_max_bars' in normalized,
     f"got keys={sorted(normalized.keys())}")
test("normalized cfg does NOT contain 'tm_bars'",
     'tm_bars' not in normalized,
     f"got keys={sorted(normalized.keys())}")
test("normalized time_max_bars has correct value (10)",
     normalized.get('time_max_bars') == 10,
     f"got time_max_bars={normalized.get('time_max_bars')}")


# ======== SUMMARY ========
print("\n" + "=" * 70)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)
