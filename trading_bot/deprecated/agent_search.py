#!/usr/bin/env python3
"""
MULTI-AGENT SEARCH ENGINE — 4 parallelle zoekstrategieën
=========================================================
Elke agent zoekt in een ANDERE richting vanuit het beste bekende punt.

Agent 1: GRID SEARCH — Alle 2-param combinaties systematisch doorrekenen
Agent 2: WIDE EXPLORER — Grote sprongen, 3-4 params tegelijk, nieuwe exit types
Agent 3: FINE TUNER — Fijne stappen rondom de top-5, continue waarden
Agent 4: WALK-FORWARD VALIDATOR — Top configs testen op out-of-sample periodes

Gebruik:
    python agent_search.py --agent 1    # Grid search
    python agent_search.py --agent 2    # Wide explorer
    python agent_search.py --agent 3    # Fine tuner
    python agent_search.py --agent 4    # Walk-forward validator
"""
import sys
import json
import time
import random
import itertools
from pathlib import Path
from copy import deepcopy

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from overnight_optimizer import (
    precompute_all, run_backtest_realistic, monte_carlo,
    evaluate_config, print_result, hill_climb,
    INITIAL_CAPITAL, PARAM_SPACE, START_BAR
)

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'

# Huidige beste config (uit sweep: score 96.7)
BEST_KNOWN = {
    'exit_type': 'trail',
    'rsi_max': 42, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 2.0,
    'time_max_bars': 6,
    'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 12.0,
    'max_pos': 2,
}

# Alternatieven: max_pos=1 geeft +$5,787 P&L maar lagere score
BEST_SINGLE = {
    'exit_type': 'trail',
    'rsi_max': 42, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 2.0,
    'time_max_bars': 6,
    'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 12.0,
    'max_pos': 1,
}


def load_data():
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins", flush=True)
    indicators = precompute_all(data, coins)
    return indicators, coins


def save_results(agent_id, results, best):
    report = {
        'agent': agent_id,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'configs_evaluated': len(results),
        'best': best,
        'top20': sorted(results, key=lambda x: x['score'], reverse=True)[:20],
    }
    f = BASE_DIR / f'agent_{agent_id}_results.json'
    with open(f, 'w') as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nReport: {f}", flush=True)


# ============================================================
# AGENT 1: GRID SEARCH — Alle 2-param combinaties
# ============================================================
def agent_grid_search(indicators, coins):
    """
    Systematisch ALLE combinaties van 2 parameters doorrekenen.
    Dit vindt interacties die single-param sweep mist.
    Bv: rsi_max=35 + vol_spike=4.0 samen beter dan elk apart.
    """
    print("=" * 80, flush=True)
    print("AGENT 1: GRID SEARCH — 2-parameter combinaties", flush=True)
    print("=" * 80, flush=True)

    # Relevante params voor trail exit type
    trail_params = {
        'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
        'rsi_max': [30, 35, 38, 40, 42, 45],
        'rsi_rec_target': [40, 42, 45, 47, 50],
        'time_max_bars': [4, 6, 8, 10, 12],
        'atr_mult': [1.5, 2.0, 2.5, 3.0],
        'be_trigger': [1.5, 2.0, 2.5, 3.0, 4.0],
        'max_stop_pct': [8.0, 10.0, 12.0, 15.0, 20.0],
    }

    param_names = list(trail_params.keys())
    results = []
    best_score = 0
    best_result = None
    total = 0

    # Alle paren van parameters
    for p1, p2 in itertools.combinations(param_names, 2):
        values1 = trail_params[p1]
        values2 = trail_params[p2]
        combos = list(itertools.product(values1, values2))
        print(f"\n  Grid: {p1} x {p2} ({len(combos)} combos)", flush=True)

        pair_best = 0
        for v1, v2 in combos:
            cfg = deepcopy(BEST_KNOWN)
            cfg[p1] = v1
            cfg[p2] = v2

            r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                              label=f"grid-{p1}={v1}-{p2}={v2}")
            results.append(r)
            total += 1

            if r['score'] > best_score:
                best_score = r['score']
                best_result = r
                print_result(r, prefix="    🏆 ")
                pair_best = r['score']

        if pair_best > 0:
            print(f"    Beste voor {p1}x{p2}: {pair_best:.1f}", flush=True)

    # Ook grid voor max_pos x andere params
    for p in ['vol_spike_mult', 'rsi_max', 'time_max_bars', 'be_trigger']:
        print(f"\n  Grid: max_pos x {p}", flush=True)
        for mp in [1, 2]:
            for v in trail_params[p]:
                cfg = deepcopy(BEST_KNOWN)
                cfg['max_pos'] = mp
                cfg[p] = v
                r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                                  label=f"grid-mp={mp}-{p}={v}")
                results.append(r)
                total += 1
                if r['score'] > best_score:
                    best_score = r['score']
                    best_result = r
                    print_result(r, prefix="    🏆 ")

    print(f"\n  Grid search klaar: {total} configs, beste score: {best_score:.1f}", flush=True)
    return results, best_result


# ============================================================
# AGENT 2: WIDE EXPLORER — Grote sprongen, nieuwe territory
# ============================================================
def agent_wide_explorer(indicators, coins):
    """
    Verken radicaal andere configs:
    - 3-4 params tegelijk veranderen
    - Andere exit types (tp_sl, hybrid_notrl)
    - Extreme parameterwaarden
    - Compleet willekeurige configs
    """
    print("=" * 80, flush=True)
    print("AGENT 2: WIDE EXPLORER — Radicale verkenning", flush=True)
    print("=" * 80, flush=True)

    results = []
    best_score = 0
    best_result = None

    # === Deel 1: Hybrid NoTrail varianten ===
    print("\n  --- Hybrid NoTrail varianten ---", flush=True)
    hybrid_combos = list(itertools.product(
        [2.0, 3.0, 4.0],           # vol_spike_mult
        [35, 40, 42, 45],           # rsi_max
        [6, 10, 15, 20],            # time_max_bars
        [10.0, 15.0, 20.0, 25.0],   # max_stop_pct
        [True, False],              # rsi_recovery
        [1, 2],                     # max_pos
    ))
    random.shuffle(hybrid_combos)

    for i, (vs, rm, tm, ms, rr, mp) in enumerate(hybrid_combos[:200]):
        cfg = {
            'exit_type': 'hybrid_notrl',
            'rsi_max': rm, 'vol_spike_mult': vs, 'vol_confirm': True,
            'time_max_bars': tm, 'max_stop_pct': ms,
            'rsi_recovery': rr, 'rsi_rec_target': 45,
            'max_pos': mp,
        }
        r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                          label=f"hybrid-vs{vs}-rm{rm}-tm{tm}-ms{ms}-rr{rr}-mp{mp}")
        results.append(r)
        if r['score'] > best_score:
            best_score = r['score']
            best_result = r
            print_result(r, prefix="    🏆 ")
        if (i+1) % 50 == 0:
            print(f"    ... {i+1}/200 hybrid, beste: {best_score:.1f}", flush=True)

    # === Deel 2: TP/SL varianten met ALLE exit params ===
    print("\n  --- TP/SL varianten ---", flush=True)
    tpsl_combos = list(itertools.product(
        [2.0, 3.0, 4.0],           # vol_spike_mult
        [35, 40, 42],               # rsi_max
        [3.0, 5.0, 7.0, 10.0, 15.0],  # tp_pct
        [5.0, 8.0, 10.0, 15.0, 20.0], # sl_pct
        [8, 12, 15, 20, 999],       # tm_bars
        [1, 2],                     # max_pos
    ))
    random.shuffle(tpsl_combos)

    for i, (vs, rm, tp, sl, tm, mp) in enumerate(tpsl_combos[:300]):
        cfg = {
            'exit_type': 'tp_sl',
            'rsi_max': rm, 'vol_spike_mult': vs, 'vol_confirm': True,
            'tp_pct': tp, 'sl_pct': sl, 'tm_bars': tm,
            'max_pos': mp,
        }
        r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                          label=f"tpsl-tp{tp}-sl{sl}-tm{tm}-vs{vs}-rm{rm}-mp{mp}")
        results.append(r)
        if r['score'] > best_score:
            best_score = r['score']
            best_result = r
            print_result(r, prefix="    🏆 ")
        if (i+1) % 50 == 0:
            print(f"    ... {i+1}/300 tpsl, beste: {best_score:.1f}", flush=True)

    # === Deel 3: Trail met extreme waarden ===
    print("\n  --- Trail extreme varianten ---", flush=True)
    extreme_combos = list(itertools.product(
        [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0],  # vol_spike breder
        [25, 30, 35, 40, 45, 50],    # rsi_max breder
        [3, 4, 5, 6, 8, 10, 15, 20, 30], # time_max breder
        [1.0, 1.5, 2.0, 3.0, 4.0],  # atr_mult
        [1, 2],                       # max_pos
    ))
    random.shuffle(extreme_combos)

    for i, (vs, rm, tm, am, mp) in enumerate(extreme_combos[:400]):
        cfg = deepcopy(BEST_KNOWN)
        cfg['vol_spike_mult'] = vs
        cfg['rsi_max'] = rm
        cfg['time_max_bars'] = tm
        cfg['atr_mult'] = am
        cfg['max_pos'] = mp
        r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                          label=f"extreme-vs{vs}-rm{rm}-tm{tm}-am{am}-mp{mp}")
        results.append(r)
        if r['score'] > best_score:
            best_score = r['score']
            best_result = r
            print_result(r, prefix="    🏆 ")
        if (i+1) % 50 == 0:
            print(f"    ... {i+1}/400 extreme, beste: {best_score:.1f}", flush=True)

    print(f"\n  Wide explorer klaar: {len(results)} configs, beste: {best_score:.1f}", flush=True)
    return results, best_result


# ============================================================
# AGENT 3: FINE TUNER — Fijne stappen rondom de top
# ============================================================
def agent_fine_tuner(indicators, coins):
    """
    Fijne granulariteit rondom de beste configs.
    Continue waarden ipv discrete stappen.
    """
    print("=" * 80, flush=True)
    print("AGENT 3: FINE TUNER — Fijne optimalisatie", flush=True)
    print("=" * 80, flush=True)

    results = []
    best_score = 0
    best_result = None

    # Fijne param space rondom BEST_KNOWN
    fine_params = {
        'vol_spike_mult': [2.5, 2.7, 2.8, 3.0, 3.2, 3.3, 3.5, 3.7, 4.0],
        'rsi_max': [38, 39, 40, 41, 42, 43, 44, 45],
        'rsi_rec_target': [40, 41, 42, 43, 44, 45, 46, 47],
        'time_max_bars': [4, 5, 6, 7, 8, 9, 10],
        'atr_mult': [1.5, 1.7, 1.8, 2.0, 2.2, 2.3, 2.5],
        'be_trigger': [1.0, 1.5, 1.7, 2.0, 2.2, 2.5, 3.0],
        'max_stop_pct': [8.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    }

    # Fijne sweeps per parameter
    for param, values in fine_params.items():
        print(f"\n  Fine sweep: {param} ({len(values)} values)", flush=True)
        for val in values:
            for mp in [1, 2]:
                cfg = deepcopy(BEST_KNOWN)
                cfg[param] = val
                cfg['max_pos'] = mp
                r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                                  label=f"fine-{param}={val}-mp{mp}")
                results.append(r)
                if r['score'] > best_score:
                    best_score = r['score']
                    best_result = r
                    print_result(r, prefix="    🏆 ")

    # Multi-param fine tuning: top combos
    print("\n  --- Multi-param fine tuning ---", flush=True)
    key_params = ['vol_spike_mult', 'rsi_max', 'time_max_bars', 'be_trigger']
    fine_values = {
        'vol_spike_mult': [2.8, 3.0, 3.2, 3.5],
        'rsi_max': [40, 42, 44],
        'time_max_bars': [5, 6, 7, 8],
        'be_trigger': [1.5, 2.0, 2.5],
    }
    combos = list(itertools.product(
        fine_values['vol_spike_mult'],
        fine_values['rsi_max'],
        fine_values['time_max_bars'],
        fine_values['be_trigger'],
    ))

    for i, (vs, rm, tm, be) in enumerate(combos):
        for mp in [1, 2]:
            cfg = deepcopy(BEST_KNOWN)
            cfg['vol_spike_mult'] = vs
            cfg['rsi_max'] = rm
            cfg['time_max_bars'] = tm
            cfg['be_trigger'] = be
            cfg['max_pos'] = mp
            r = evaluate_config(indicators, coins, cfg, n_sims=5000,
                              label=f"multi-vs{vs}-rm{rm}-tm{tm}-be{be}-mp{mp}")
            results.append(r)
            if r['score'] > best_score:
                best_score = r['score']
                best_result = r
                print_result(r, prefix="    🏆 ")
        if (i+1) % 30 == 0:
            print(f"    ... {i+1}/{len(combos)} multi-combos, beste: {best_score:.1f}", flush=True)

    # Hill climb vanuit de fine-tuned best
    if best_result:
        print("\n  Hill climbing vanuit fine-tuned best...", flush=True)
        best_cfg, best_score, _ = hill_climb(
            indicators, coins, deepcopy(best_result['cfg']),
            best_score, best_result['label'], results,
            n_sims=5000, max_rounds=5)

    print(f"\n  Fine tuner klaar: {len(results)} configs, beste: {best_score:.1f}", flush=True)
    return results, best_result


# ============================================================
# AGENT 4: WALK-FORWARD VALIDATOR — Out-of-sample testing
# ============================================================
def agent_walk_forward(indicators, coins):
    """
    Walk-forward validatie: train op eerste deel, test op tweede.
    Dit is de ECHTE test of een config robuust is.
    5-fold time-series splits.
    """
    print("=" * 80, flush=True)
    print("AGENT 4: WALK-FORWARD VALIDATOR", flush=True)
    print("=" * 80, flush=True)

    results = []

    # Bepaal max bars
    max_bars = max(indicators[p]['n'] for p in coins if p in indicators)
    usable = max_bars - START_BAR

    # 5-fold walk-forward: 60% train, 40% test
    n_folds = 5
    fold_size = usable // n_folds
    print(f"  Max bars: {max_bars}, usable: {usable}, fold size: {fold_size}", flush=True)

    # Configs om te testen (alle bekende goede + varianten)
    test_configs = [
        ('BEST_mp2', BEST_KNOWN),
        ('BEST_mp1', BEST_SINGLE),
        ('V5+VolSpk3_orig', {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 3.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 1,
        }),
        ('HYBRID_NoTrail', {
            'exit_type': 'hybrid_notrl', 'rsi_max': 40,
            'vol_spike_mult': 2.0, 'vol_confirm': True,
            'time_max_bars': 15, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 20.0, 'max_pos': 1,
        }),
        ('V5_baseline', {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 2.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 1,
        }),
        # Varianten van best
        ('BEST_vs3.5', {**BEST_KNOWN, 'vol_spike_mult': 3.5}),
        ('BEST_vs4.0', {**BEST_KNOWN, 'vol_spike_mult': 4.0}),
        ('BEST_rm40', {**BEST_KNOWN, 'rsi_max': 40}),
        ('BEST_tm8', {**BEST_KNOWN, 'time_max_bars': 8}),
        ('BEST_tm10', {**BEST_KNOWN, 'time_max_bars': 10}),
        ('BEST_be3', {**BEST_KNOWN, 'be_trigger': 3.0}),
        ('BEST_mp1_vs3.5', {**BEST_SINGLE, 'vol_spike_mult': 3.5}),
        ('BEST_mp1_tm8', {**BEST_SINGLE, 'time_max_bars': 8}),
    ]

    # Walk-forward per config
    for config_name, cfg in test_configs:
        print(f"\n  === {config_name} ===", flush=True)
        fold_results = []
        train_wins = 0
        test_wins = 0

        for fold in range(n_folds):
            # Train: fold 0..fold, Test: fold+1
            train_end = START_BAR + (fold + 1) * fold_size
            test_start = train_end
            test_end = min(test_start + fold_size, max_bars)

            if test_end <= test_start + 10:
                continue

            # Train backtest
            bt_train = run_backtest_realistic(indicators, coins, cfg,
                                             start_bar=START_BAR, end_bar=train_end)
            # Test backtest
            bt_test = run_backtest_realistic(indicators, coins, cfg,
                                            start_bar=test_start, end_bar=test_end)

            train_pnl = bt_train['pnl']
            test_pnl = bt_test['pnl']
            train_ok = train_pnl > 0
            test_ok = test_pnl > 0
            if train_ok:
                train_wins += 1
            if test_ok:
                test_wins += 1

            marker = "✅" if test_ok else "❌"
            print(f"    Fold {fold+1}: Train[{START_BAR}-{train_end}] "
                  f"P&L=${train_pnl:+.0f} ({bt_train['trades']}tr) | "
                  f"Test[{test_start}-{test_end}] "
                  f"P&L=${test_pnl:+.0f} ({bt_test['trades']}tr) {marker}",
                  flush=True)

            fold_results.append({
                'fold': fold + 1,
                'train_pnl': train_pnl, 'train_trades': bt_train['trades'],
                'test_pnl': test_pnl, 'test_trades': bt_test['trades'],
                'train_ok': train_ok, 'test_ok': test_ok,
            })

        # Full backtest + Monte Carlo
        r = evaluate_config(indicators, coins, cfg, n_sims=10000, label=config_name)
        r['walk_forward'] = {
            'folds': fold_results,
            'test_wins': test_wins,
            'total_folds': len(fold_results),
            'wf_ratio': f"{test_wins}/{len(fold_results)}",
        }
        results.append(r)

        print(f"    WF: {test_wins}/{len(fold_results)} folds winstgevend | "
              f"Full: {r['backtest']['trades']}tr P&L=${r['backtest']['pnl']:+.0f} "
              f"MC:{r['monte_carlo']['win_pct']:.0f}%", flush=True)

    # Ranking op WF + MC combined
    print(f"\n{'=' * 80}", flush=True)
    print("WALK-FORWARD RANKING", flush=True)
    print(f"{'=' * 80}", flush=True)

    results.sort(key=lambda x: (
        x['walk_forward']['test_wins'],
        x['score']
    ), reverse=True)

    print(f"\n{'Rk':<4} {'Config':<25} {'WF':>5} {'Score':>6} {'MC%':>6} "
          f"{'Tr':>4} {'P&L':>10} {'DD%':>6}", flush=True)
    print(f"{'─' * 75}", flush=True)

    for i, r in enumerate(results):
        wf = r['walk_forward']
        bt = r['backtest']
        mc = r['monte_carlo']
        star = " ⭐" if i == 0 else ""
        print(f"  #{i+1:<2} {r['label']:<25} {wf['wf_ratio']:>5} "
              f"{r['score']:>5.1f} {mc['win_pct']:>5.0f}% "
              f"{bt['trades']:>4} ${bt['pnl']:>+8.0f} "
              f"{bt['dd']:>5.1f}%{star}", flush=True)

    best_result = results[0] if results else None
    return results, best_result


# ============================================================
# MAIN
# ============================================================
def main():
    agent_id = 1
    for arg in sys.argv:
        if arg.startswith('--agent'):
            if '=' in arg:
                agent_id = int(arg.split('=')[1])
            elif sys.argv.index(arg) + 1 < len(sys.argv):
                agent_id = int(sys.argv[sys.argv.index(arg) + 1])

    print(f"{'=' * 80}", flush=True)
    print(f"AGENT {agent_id} gestart — {time.strftime('%H:%M:%S')}", flush=True)
    print(f"{'=' * 80}", flush=True)

    t0 = time.time()
    indicators, coins = load_data()

    agents = {
        1: ("GRID SEARCH", agent_grid_search),
        2: ("WIDE EXPLORER", agent_wide_explorer),
        3: ("FINE TUNER", agent_fine_tuner),
        4: ("WALK-FORWARD VALIDATOR", agent_walk_forward),
    }

    name, func = agents[agent_id]
    print(f"\nStrategie: {name}", flush=True)

    results, best = func(indicators, coins)

    elapsed = time.time() - t0
    print(f"\n{'=' * 80}", flush=True)
    print(f"AGENT {agent_id} ({name}) KLAAR — {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)
    print(f"Configs geëvalueerd: {len(results)}", flush=True)

    if best:
        print(f"\n🏆 BESTE:", flush=True)
        print_result(best, prefix="  ")
        print(f"  Config: {best['cfg']}", flush=True)

    save_results(agent_id, results, best)


if __name__ == '__main__':
    main()
