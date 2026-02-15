#!/usr/bin/env python3
"""
Debug probe: Waarom zijn alle Scout Phase 2 outputs identiek (score 71.8)?

Hypotheses:
  H1: cfg_hash excludes velden → cache hit → zelfde result
  H2: exit_type=tp_sl ignoreert trail-params (atr_mult, be_trigger, max_stop_pct, time_max_bars) → zelfde backtest
  H3: evaluate() cacht iets
  H4: scoring saturatie

Test: 3 extreme probes + audit record per trade.
"""
import json, sys, os, hashlib
from copy import deepcopy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_team_v3 import (
    run_backtest, precompute_all, evaluate, cfg_hash, check_entry_at_bar,
    CACHE_FILE, START_BAR, INITIAL_CAPITAL, Blackboard,
)

# Load data
with open(CACHE_FILE) as f:
    data = json.load(f)
coins = sorted([k for k in data if not k.startswith('_')])
# Use full 526-coin dataset (same as champion)
indicators = precompute_all(data, coins)
bb = Blackboard()

# Champion config
CHAMP = {
    'rsi_max': 45, 'vol_spike_mult': 3.0, 'vol_confirm': True,
    'exit_type': 'tp_sl', 'tp_pct': 15, 'sl_pct': 15, 'tm_bars': 15, 'max_pos': 1,
}

# ===== TEST 1: Hash uniqueness =====
print("=" * 80)
print("TEST 1: Hash uniqueness")
print("=" * 80)
configs = [
    ('Champion',               {**CHAMP}),
    ('rsi_max=25',             {**CHAMP, 'rsi_max': 25}),
    ('rsi_max=70',             {**CHAMP, 'rsi_max': 70}),
    ('tp5_sl20',               {**CHAMP, 'tp_pct': 5, 'sl_pct': 20}),
    ('tp25_sl10',              {**CHAMP, 'tp_pct': 25, 'sl_pct': 10}),
    ('tm3',                    {**CHAMP, 'tm_bars': 3}),
    ('tm50',                   {**CHAMP, 'tm_bars': 50}),
    # Scout Phase 2 variaties (exact wat identiek scoorde)
    ('vol_spike=3_tm=6',       {**CHAMP, 'vol_spike_mult': 3.0, 'time_max_bars': 6}),
    ('vol_spike=3_atr=1.5',    {**CHAMP, 'vol_spike_mult': 3.0, 'atr_mult': 1.5}),
    ('vol_spike=3_be=1.5',     {**CHAMP, 'vol_spike_mult': 3.0, 'be_trigger': 1.5}),
    ('vol_spike=3_ms=8',       {**CHAMP, 'vol_spike_mult': 3.0, 'max_stop_pct': 8.0}),
    ('rsi45_rr42',             {**CHAMP, 'rsi_max': 45, 'rsi_rec_target': 42}),
]

hashes = {}
for name, cfg in configs:
    h = cfg_hash(cfg)
    hashes[name] = h
    print(f"  {name:30s} hash={h}  cfg_keys={sorted(cfg.keys())}")

unique_h = len(set(hashes.values()))
print(f"\n  Unique hashes: {unique_h}/{len(hashes)}  → {'OK' if unique_h == len(hashes) else 'DUPLICATE!'}")

# ===== TEST 2: Backtest output per config =====
print("\n" + "=" * 80)
print("TEST 2: Backtest output per config (trade count, P&L, WR, exit reasons)")
print("=" * 80)

# Track which configs produce identical results
results = {}
for name, cfg in configs:
    bt = run_backtest(indicators, coins, cfg)
    # Exit reason breakdown
    reasons = {}
    for t in bt['trade_list']:
        r = t['reason']
        reasons[r] = reasons.get(r, 0) + 1
    reason_str = ' | '.join(f"{r}:{n}" for r, n in sorted(reasons.items()))
    results[name] = {
        'trades': bt['trades'], 'pnl': round(bt['pnl'], 2),
        'wr': round(bt['wr'], 1), 'dd': round(bt['dd'], 1),
        'final_eq': round(bt['final_equity'], 2),
        'reasons': reasons,
    }
    print(f"  {name:30s} Tr={bt['trades']:3d} P&L=${bt['pnl']:+8,.0f} "
          f"WR={bt['wr']:5.1f}% DD={bt['dd']:5.1f}% | {reason_str}")

# Check: zijn er identieke results?
print("\n  IDENTITY CHECK:")
champ_key = (results['Champion']['trades'], results['Champion']['pnl'])
identical_to_champ = [n for n, r in results.items()
                      if (r['trades'], r['pnl']) == champ_key and n != 'Champion']
if identical_to_champ:
    print(f"  ⚠️  IDENTIEK AAN CHAMPION: {identical_to_champ}")
else:
    print(f"  ✅ Alle configs produceren verschillende resultaten")

# ===== TEST 3: Root cause — welke params worden GENEGEERD bij tp_sl? =====
print("\n" + "=" * 80)
print("TEST 3: Parameter sensitivity proof (welke params worden genegeerd bij tp_sl?)")
print("=" * 80)

# Deze params zitten in trail/hybrid_notrl maar NIET in tp_sl exit logic
trail_only_params = {
    'atr_mult': [1.5, 2.0, 3.0],
    'be_trigger': [1.5, 2.0, 4.0],
    'max_stop_pct': [8.0, 12.0, 20.0],
    'time_max_bars': [4, 10, 20],  # NB: tp_sl gebruikt 'tm_bars', niet 'time_max_bars'!
    'rsi_recovery': [True, False],
    'rsi_rec_target': [40, 45, 50],
    'breakeven': [True, False],
}

print(f"\n  Champion cfg: {json.dumps(CHAMP, sort_keys=True)}")
print(f"\n  tp_sl exit code leest: tp_pct, sl_pct, tm_bars")
print(f"  NIET gelezen: atr_mult, be_trigger, max_stop_pct, time_max_bars, rsi_recovery, rsi_rec_target, breakeven")
print(f"\n  Bewijs — varieer elke trail-only param, check of output verandert:")

champ_bt = run_backtest(indicators, coins, CHAMP)
champ_sig = (champ_bt['trades'], round(champ_bt['pnl'], 2))

for param, values in trail_only_params.items():
    for val in values:
        cfg = deepcopy(CHAMP)
        cfg[param] = val
        bt = run_backtest(indicators, coins, cfg)
        sig = (bt['trades'], round(bt['pnl'], 2))
        match = "IDENTICAL ⚠️" if sig == champ_sig else "DIFFERENT ✅"
        print(f"    {param:20s} = {str(val):8s} → Tr={bt['trades']:3d} P&L=${bt['pnl']:+8,.0f} {match}")

# ===== TEST 4: Scoring check =====
print("\n" + "=" * 80)
print("TEST 4: Scoring per config (check saturatie/clipping)")
print("=" * 80)

for name, cfg in configs[:7]:  # extremes only
    entry = evaluate(indicators, coins, cfg, name, bb)
    if entry:
        print(f"  {name:30s} score={entry['score']:.1f} | "
              f"Tr={entry['backtest']['trades']} P&L=${entry['backtest']['pnl']:+,.0f} "
              f"MC_med=${entry['mc_block']['median_eq']:,.0f}")
    else:
        print(f"  {name:30s} KILLED (gates failed)")

# ===== CONCLUSIE =====
print("\n" + "=" * 80)
print("CONCLUSIE")
print("=" * 80)
print("""
ROOT CAUSE HYPOTHESE:
  Champion is exit_type='tp_sl'. De tp_sl exit logic leest ALLEEN:
    tp_pct, sl_pct, tm_bars

  De Scout Phase 2 grid varieert vanuit bb.get_best_cfg() (= champion cfg):
    vol_spike_mult, rsi_max, rsi_rec_target, time_max_bars,
    atr_mult, be_trigger, max_stop_pct

  PROBLEEM: 'time_max_bars' ≠ 'tm_bars'!
  - tp_sl exit code leest cfg.get('tm_bars', 15) op line 307
  - Scout Phase 1+2 grid zet cfg['time_max_bars'] = val
  - trail exit code leest cfg.get('time_max_bars', 10) op line 320
  - Dus: bij tp_sl wordt time_max_bars COMPLEET GENEGEERD

  EN: atr_mult, be_trigger, max_stop_pct, rsi_recovery, rsi_rec_target
  worden alleen gelezen in trail/hybrid_notrl exit branches.
  Bij tp_sl: deze params bestaan wel in de cfg dict, geven een andere hash,
  maar produceren een IDENTIEKE backtest.

  Resultaat: alle Scout 2-param variaties met trail-only params × anything
  geven exact dezelfde trades/P&L/score als champion.
  Score 71.8 is niet gesatureerd — het is letterlijk dezelfde backtest 100x herhaald.
""")
