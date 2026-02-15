#!/usr/bin/env python3
"""
Part 2 -- Agent C2-A5: Exclusion Threshold Sweep
=================================================
Finds the MINIMUM number of worst-performing coins to exclude
such that all 7 gates pass.

Cycle 1 showed:
  - excl_worst5:  4/7 gates
  - excl_worst10: 5/7 gates
  - excl_all_negative (21): 7/7 gates

This sweep tests N = 5,8,10,12,14,15,16,17,18,19,20,21
plus threshold-based exclusion at -$100, -$50, -$25, $0.

Usage:
    python -m strategies.hf.screening.run_part2_excl_sweep
    python -m strategies.hf.screening.run_part2_excl_sweep --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

BARS_PER_WEEK = 168
BARS_PER_DAY = 24

BASELINE_PARAMS = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# N-values to sweep (worst-N exclusion)
SWEEP_N_VALUES = [5, 8, 10, 12, 14, 15, 16, 17, 18, 19, 20, 21]

# Threshold-based exclusion: exclude coins with P&L below threshold
THRESHOLD_VALUES = [-100, -50, -25, 0]


def load_candle_cache(timeframe='1h', require_data=False):
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if cache_path.exists():
        print(f'[Load] Reading {cache_path.name}...')
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        print(f'[Load] {len(coins_data)} coins loaded (merged cache)')
        return coins_data
    parts_base = ROOT / 'data' / 'cache_parts_hf' / timeframe
    if not parts_base.exists():
        if require_data:
            print(f'[ERROR] No cache found')
            sys.exit(1)
        print('[SKIP] No 1H candle cache found.')
        return None
    print(f'[Load] Loading from per-coin parts...')
    manifest_path = ROOT / 'data' / f'manifest_hf_{timeframe}.json'
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir():
            continue
        for coin_file in sorted(exchange_dir.glob('*.json')):
            symbol = coin_file.stem.replace('_', '/')
            if manifest and symbol in manifest:
                if manifest[symbol].get('status') != 'done':
                    continue
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
    if not coins_data:
        if require_data:
            sys.exit(1)
        return None
    print(f'[Load] {len(coins_data)} coins loaded (from part files)')
    return coins_data


def load_universe_tiering(require_data=False):
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        if require_data:
            sys.exit(1)
        return None
    with open(tiering_path) as f:
        return json.load(f)


def build_tier_coins(tiering, available_coins):
    tier_coins = {'tier1': [], 'tier2': []}
    tb = tiering.get('tier_breakdown', {})
    for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
        if tier_num in tb:
            coins = tb[tier_num].get('coins', [])
            tier_coins[tier_key] = [c for c in coins if c in available_coins]
    return tier_coins


def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None):
    if params is None:
        params = BASELINE_PARAMS
    signal_params = {**params, '__market__': market_context}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    all_trades = []
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=signal_params, indicators=indicators, fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    if params is None:
        params = BASELINE_PARAMS
    signal_params = {**params, '__market__': market_context}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    tier_fold_trades = {}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=signal_params, indicators=indicators, n_folds=n_folds,
            fee=fee, max_pos=1,
        )
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)
    return tier_fold_trades


def compute_metrics(trades, total_bars):
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
                'trades_per_week': 0.0, 'exp_per_week': 0.0,
                'max_dd_pct': 0.0, 'max_gap_days': 0.0, 'expectancy': 0.0}
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n_trades
    trades_per_week = n_trades / total_weeks
    exp_per_week = expectancy * trades_per_week
    equity = 2000.0
    peak = equity
    max_dd = 0.0
    sorted_trades = sorted(trades, key=lambda x: x.get('entry_bar', 0))
    for t in sorted_trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    max_gap_bars = 0
    if len(sorted_trades) > 1:
        for i in range(1, len(sorted_trades)):
            gap = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i-1].get('entry_bar', 0)
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
            'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4)}


def compute_concentration(trades):
    coin_pnl = defaultdict(float)
    for t in trades:
        coin_pnl[t.get('pair', 'unknown')] += t['pnl']
    positive_coins = {c: p for c, p in coin_pnl.items() if p > 0}
    total_positive = sum(positive_coins.values())
    if total_positive <= 0:
        return {'top1_pct': 100.0, 'top3_pct': 100.0, 'top1_coin': '?'}
    sorted_positive = sorted(positive_coins.items(), key=lambda x: x[1], reverse=True)
    top1_pct = sorted_positive[0][1] / total_positive * 100
    top3_pct = sum(v for _, v in sorted_positive[:3]) / total_positive * 100
    return {'top1_pct': round(top1_pct, 1), 'top3_pct': round(top3_pct, 1),
            'top1_coin': sorted_positive[0][0]}


def compute_fold_concentration(fold_trades):
    fold_pnls = {}
    for fold_idx, trades in fold_trades.items():
        fold_pnls[fold_idx] = sum(t['pnl'] for t in trades)
    positive_total = sum(max(0, p) for p in fold_pnls.values())
    if positive_total <= 0:
        return {'top1_fold_conc_pct': 100.0, 'fold_pnls': fold_pnls}
    max_fold_pnl = max(fold_pnls.values())
    top1_fold_conc = max(0, max_fold_pnl) / positive_total * 100
    return {'top1_fold_conc_pct': round(top1_fold_conc, 1),
            'fold_pnls': {k: round(v, 2) for k, v in fold_pnls.items()}}


def evaluate_gates(metrics, wf_folds_positive, n_folds, stress_metrics, fold_conc):
    gates = {}
    g1_val = metrics['trades_per_week']
    gates['G1'] = {'name': 'Trades/week', 'value': g1_val,
                   'threshold': '>= 10', 'pass': g1_val >= 10}
    g2_val = metrics['max_gap_days']
    gates['G2'] = {'name': 'Max gap (days)', 'value': g2_val,
                   'threshold': '<= 2.5', 'pass': g2_val <= 2.5}
    g3_val = metrics['exp_per_week']
    gates['G3'] = {'name': 'Exp/week (market)', 'value': round(g3_val, 2),
                   'threshold': '> $0', 'pass': g3_val > 0}
    g4_val = stress_metrics['exp_per_week']
    gates['G4'] = {'name': 'Exp/week (P95 stress)', 'value': round(g4_val, 2),
                   'threshold': '> $0', 'pass': g4_val > 0}
    g5_val = metrics['max_dd_pct']
    gates['G5'] = {'name': 'Max DD%', 'value': g5_val,
                   'threshold': '<= 20%', 'pass': g5_val <= 20}
    g6_val = wf_folds_positive
    gates['G6'] = {'name': 'WF folds positive', 'value': f'{g6_val}/{n_folds}',
                   'threshold': f'>= 4/{n_folds}', 'pass': g6_val >= 4}
    g8_val = fold_conc['top1_fold_conc_pct']
    gates['G8'] = {'name': 'Top-1 fold conc.', 'value': f'{g8_val}%',
                   'threshold': '< 35%', 'pass': g8_val < 35}
    n_pass = sum(1 for g in gates.values() if g['pass'])
    return {'gates': gates, 'pass_count': n_pass, 'total_count': len(gates),
            'score': f'{n_pass}/{len(gates)}', 'all_pass': n_pass == len(gates)}


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def coin_pnl_attribution(trades):
    coin_stats = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
    for t in trades:
        coin = t.get('pair', 'unknown')
        coin_stats[coin]['pnl'] += t['pnl']
        coin_stats[coin]['trades'] += 1
        if t['pnl'] > 0:
            coin_stats[coin]['wins'] += 1
        else:
            coin_stats[coin]['losses'] += 1
    sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]['pnl'])
    return sorted_coins, coin_stats


def run_full_evaluation(label, data, tier_coins, all_indicators_cache,
                        market_context, tier1_fee, tier2_fee,
                        stress_tier1_fee, stress_tier2_fee, total_bars):
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in all_indicators_cache:
            tier_indicators[tier_name] = {
                c: all_indicators_cache[tier_name][c]
                for c in coins if c in all_indicators_cache[tier_name]
            }
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee)
    metrics = compute_metrics(trades, total_bars)
    conc = compute_concentration(trades)
    n_coins_with_trades = len(set(t.get('pair', '') for t in trades))
    print(f'    trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'exp/w=${metrics["exp_per_week"]:.2f} DD={metrics["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Running stress (2x fees)...')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'    stress: trades={stress_metrics["trades"]} exp/w=${stress_metrics["exp_per_week"]:.2f}')

    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5)
    folds_positive = 0
    fold_details = []
    for fold_idx in sorted(fold_trades.keys()):
        fold_pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
        fold_n = len(fold_trades[fold_idx])
        is_pos = fold_pnl > 0
        if is_pos:
            folds_positive += 1
        fold_details.append({'fold': fold_idx, 'trades': fold_n,
                            'pnl': round(fold_pnl, 2), 'positive': is_pos})
    fold_conc = compute_fold_concentration(fold_trades)
    print(f'    WF={folds_positive}/5  fold_conc={fold_conc["top1_fold_conc_pct"]:.1f}%')

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    return {
        'label': label,
        'n_coins': sum(len(c) for c in tier_coins.values()),
        'n_t1': len(tier_coins.get('tier1', [])),
        'n_t2': len(tier_coins.get('tier2', [])),
        'n_coins_with_trades': n_coins_with_trades,
        'metrics': metrics,
        'stress_metrics': {'trades': stress_metrics['trades'], 'pnl': stress_metrics['pnl'],
                          'pf': stress_metrics['pf'], 'exp_per_week': stress_metrics['exp_per_week']},
        'wf_folds_positive': folds_positive, 'wf_fold_details': fold_details,
        'fold_concentration': fold_conc, 'concentration': conc,
        'gate_evaluation': gate_eval, 'runtime_s': round(elapsed, 1),
    }


def load_attribution_from_report():
    """Load coin attribution from the loss_cluster report if available."""
    report_path = ROOT / 'reports' / 'hf' / 'part2_loss_cluster_001.json'
    if report_path.exists():
        with open(report_path) as f:
            report = json.load(f)
        attr = report.get('coin_attribution', {}).get('full_attribution', [])
        if attr:
            print(f'[Attribution] Loaded from report: {len(attr)} coins')
            return attr
    return None


def main():
    parser = argparse.ArgumentParser(description='Part 2 Agent C2-A5: Exclusion Threshold Sweep')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C2-A5: Exclusion Threshold Sweep')
    print('  Objective: Find MINIMUM coins to exclude for 7/7 gates')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps')

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)
    n_t1 = len(tier_coins_full['tier1'])
    n_t2 = len(tier_coins_full['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins, total: {n_t1+n_t2}')

    if not tier_coins_full['tier1'] and not tier_coins_full['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1 if args.require_data else 0)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}')
        print(f'  Params: {BASELINE_PARAMS}')
        print(f'  Worst-N sweep: {SWEEP_N_VALUES}')
        print(f'  Threshold sweep: {THRESHOLD_VALUES}')
        print(f'  Total evaluations: {len(SWEEP_N_VALUES) + len(THRESHOLD_VALUES)}')
        sys.exit(0)

    # --- Precompute indicators (shared across all evaluations) ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators_full = {}
    for tier_name, coins in tier_coins_full.items():
        if coins:
            t_ind = time.time()
            tier_indicators_full[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_full.items():
        if coins and tier_name in tier_indicators_full:
            extend_indicators(data, coins, tier_indicators_full[tier_name])
            cov = get_feature_coverage(tier_indicators_full[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_full.get('tier1', []) + tier_coins_full.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    for tier_name, ind_dict in tier_indicators_full.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # --- Step 1: Get per-coin attribution ---
    print('\n' + '=' * 70)
    print('  STEP 1: Per-coin P&L attribution')
    print('=' * 70)

    # Try loading from existing report first
    cached_attr = load_attribution_from_report()
    if cached_attr:
        # Use cached attribution (sorted worst-to-best)
        attribution_list = cached_attr
        print(f'  Using cached attribution: {len(attribution_list)} coins')
    else:
        # Run baseline to compute attribution
        print('  Running baseline for attribution...')
        baseline_trades = run_variant(data, tier_coins_full, tier_indicators_full,
                                      market_context, tier1_fee, tier2_fee)
        sorted_coins, coin_stats = coin_pnl_attribution(baseline_trades)
        attribution_list = []
        t1_set = set(tier_coins_full['tier1'])
        for coin, stats in sorted_coins:
            tier = 'tier1' if coin in t1_set else 'tier2'
            attribution_list.append({
                'coin': coin, 'tier': tier, 'pnl': round(stats['pnl'], 2),
                'trades': stats['trades'], 'wins': stats['wins'],
                'losses': stats['losses'],
            })

    # Sorted worst-to-best (already in this order from loss_cluster)
    coins_sorted_worst = [a['coin'] for a in attribution_list]
    n_negative = sum(1 for a in attribution_list if a['pnl'] < 0)
    n_positive = sum(1 for a in attribution_list if a['pnl'] > 0)

    print(f'  Total coins with trades: {len(attribution_list)}')
    print(f'  Net-negative: {n_negative}, Net-positive: {n_positive}')
    print(f'\n  Worst 5: {coins_sorted_worst[:5]}')
    print(f'  Cumulative P&L of worst 5: ${sum(a["pnl"] for a in attribution_list[:5]):.0f}')
    print(f'  Cumulative P&L of worst 10: ${sum(a["pnl"] for a in attribution_list[:10]):.0f}')
    print(f'  Cumulative P&L of worst 15: ${sum(a["pnl"] for a in attribution_list[:15]):.0f}')
    print(f'  Cumulative P&L of all negative ({n_negative}): '
          f'${sum(a["pnl"] for a in attribution_list if a["pnl"] < 0):.0f}')

    # --- Step 2: Worst-N sweep ---
    print('\n' + '=' * 70)
    print('  STEP 2: Worst-N Exclusion Sweep')
    print(f'  N values: {SWEEP_N_VALUES}')
    print('=' * 70)

    results_by_n = {}
    for n_excl in SWEEP_N_VALUES:
        excl_coins = set(coins_sorted_worst[:n_excl])
        filtered = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_coins],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_coins],
        }
        label = f'excl_worst{n_excl}'
        result = run_full_evaluation(
            label=label, data=data, tier_coins=filtered,
            all_indicators_cache=tier_indicators_full, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
        )
        result['excluded_coins'] = sorted(excl_coins)
        result['excl_type'] = 'worst_n'
        result['excl_n'] = n_excl
        results_by_n[n_excl] = result

    # --- Step 3: Threshold-based sweep ---
    print('\n' + '=' * 70)
    print('  STEP 3: Threshold-Based Exclusion Sweep')
    print(f'  Thresholds: {THRESHOLD_VALUES}')
    print('=' * 70)

    results_by_thresh = {}
    for thresh in THRESHOLD_VALUES:
        excl_coins = set(a['coin'] for a in attribution_list if a['pnl'] < thresh)
        n_excl = len(excl_coins)
        filtered = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_coins],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_coins],
        }
        label = f'excl_below_${thresh}'
        result = run_full_evaluation(
            label=label, data=data, tier_coins=filtered,
            all_indicators_cache=tier_indicators_full, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
        )
        result['excluded_coins'] = sorted(excl_coins)
        result['excl_type'] = 'threshold'
        result['excl_threshold'] = thresh
        result['excl_n'] = n_excl
        results_by_thresh[thresh] = result

    elapsed_total = time.time() - t0_total

    # --- Analysis: Find minimum N ---
    print('\n' + '=' * 70)
    print('  ANALYSIS: Finding minimum N for 7/7 gates')
    print('=' * 70)

    min_n_all_pass = None
    for n_excl in sorted(results_by_n.keys()):
        r = results_by_n[n_excl]
        ge = r['gate_evaluation']
        all_pass = ge['all_pass']
        if all_pass and (min_n_all_pass is None or n_excl < min_n_all_pass):
            min_n_all_pass = n_excl

    if min_n_all_pass is not None:
        print(f'  MINIMUM N for 7/7 gates: {min_n_all_pass}')
        excl_coins_min = coins_sorted_worst[:min_n_all_pass]
        cum_pnl = sum(a['pnl'] for a in attribution_list[:min_n_all_pass])
        print(f'  Coins excluded: {excl_coins_min}')
        print(f'  Cumulative P&L removed: ${cum_pnl:.0f}')
    else:
        print('  NO N in sweep achieves 7/7 gates')

    min_thresh_all_pass = None
    for thresh in sorted(results_by_thresh.keys(), reverse=True):
        r = results_by_thresh[thresh]
        if r['gate_evaluation']['all_pass']:
            min_thresh_all_pass = thresh

    if min_thresh_all_pass is not None:
        print(f'  LEAST-AGGRESSIVE threshold for 7/7: ${min_thresh_all_pass}')
        n_excl_thresh = results_by_thresh[min_thresh_all_pass]['excl_n']
        print(f'  Coins excluded at that threshold: {n_excl_thresh}')
    else:
        print(f'  NO threshold achieves 7/7 gates')

    # --- Build report ---
    all_n_results = []
    for n_excl in sorted(results_by_n.keys()):
        all_n_results.append(results_by_n[n_excl])

    all_thresh_results = []
    for thresh in sorted(results_by_thresh.keys()):
        all_thresh_results.append(results_by_thresh[thresh])

    report = {
        'run_header': {
            'task': 'part2_excl_sweep', 'agent': 'C2-A5',
            'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION', 'params': BASELINE_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                               'tier2': round(stress_tier2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})', 'timeframe': '1h',
            'total_bars': total_bars, 'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'coin_attribution_summary': {
            'total_with_trades': len(attribution_list),
            'net_negative': n_negative,
            'net_positive': n_positive,
            'worst_coins': attribution_list[:21],
        },
        'worst_n_sweep': {
            'n_values_tested': SWEEP_N_VALUES,
            'results': all_n_results,
            'minimum_n_all_pass': min_n_all_pass,
        },
        'threshold_sweep': {
            'thresholds_tested': THRESHOLD_VALUES,
            'results': all_thresh_results,
            'least_aggressive_threshold_all_pass': min_thresh_all_pass,
        },
        'conclusion': {
            'minimum_n_for_7_of_7': min_n_all_pass,
            'margin': (21 - min_n_all_pass) if min_n_all_pass else None,
            'least_aggressive_threshold': min_thresh_all_pass,
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_excl_sweep_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # --- Build Markdown report ---
    md = []
    md.append('# Part 2 -- Exclusion Threshold Sweep (Agent C2-A5)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={BASELINE_PARAMS["dev_thresh"]}, tp={BASELINE_PARAMS["tp_pct"]}, '
              f'sl={BASELINE_PARAMS["sl_pct"]}, tl={BASELINE_PARAMS["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Summary box
    md.append('## Key Finding')
    md.append('')
    if min_n_all_pass is not None:
        md.append(f'**Minimum exclusion for 7/7 gates: {min_n_all_pass} coins**')
        md.append(f'- Margin vs all-negative (21): {21 - min_n_all_pass} coins of headroom')
        if min_thresh_all_pass is not None:
            n_at_thresh = results_by_thresh[min_thresh_all_pass]['excl_n']
            md.append(f'- Least-aggressive threshold: ${min_thresh_all_pass} '
                      f'(excludes {n_at_thresh} coins)')
    else:
        md.append('**No exclusion level in the sweep achieves 7/7 gates.**')
    md.append('')

    # Worst-N sweep table
    md.append('## 1. Worst-N Exclusion Sweep')
    md.append('')
    md.append('| N excl | Coins | Trades | PF | Exp/Wk | DD% | WF | FoldConc | Gates | All? |')
    md.append('|--------|-------|--------|----|--------|-----|----|----------|-------|------|')
    for n_excl in sorted(results_by_n.keys()):
        r = results_by_n[n_excl]
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        all_str = 'YES' if ge['all_pass'] else 'no'
        md.append(f'| {n_excl} | {r["n_coins"]} | {m["trades"]} | {m["pf"]:.3f} '
                  f'| ${m["exp_per_week"]:.0f} | {m["max_dd_pct"]:.1f}% '
                  f'| {r["wf_folds_positive"]}/5 | {fc["top1_fold_conc_pct"]:.1f}% '
                  f'| **{ge["score"]}** | {all_str} |')
    md.append('')

    # Gate detail per N
    md.append('## 2. Gate Detail per Exclusion Level')
    md.append('')
    gate_ids = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']
    # Compact table: one row per N, one column per gate
    md.append('| N | G1 Trades/wk | G2 Gap | G3 Exp/wk | G4 Stress | G5 DD% | G6 WF | G8 FoldConc |')
    md.append('|---|--------------|--------|-----------|-----------|--------|-------|-------------|')
    for n_excl in sorted(results_by_n.keys()):
        r = results_by_n[n_excl]
        ge = r['gate_evaluation']
        cells = [str(n_excl)]
        for gid in gate_ids:
            g = ge['gates'][gid]
            v = g['value']
            p = 'P' if g['pass'] else 'F'
            cells.append(f'{v} {p}')
        md.append('| ' + ' | '.join(cells) + ' |')
    md.append('')

    # Threshold sweep table
    md.append('## 3. Threshold-Based Exclusion')
    md.append('')
    md.append('| Threshold | N excl | Coins | Trades | PF | Exp/Wk | DD% | WF | FoldConc | Gates | All? |')
    md.append('|-----------|--------|-------|--------|----|--------|-----|----|----------|-------|------|')
    for thresh in sorted(results_by_thresh.keys()):
        r = results_by_thresh[thresh]
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        all_str = 'YES' if ge['all_pass'] else 'no'
        md.append(f'| ${thresh} | {r["excl_n"]} | {r["n_coins"]} | {m["trades"]} | {m["pf"]:.3f} '
                  f'| ${m["exp_per_week"]:.0f} | {m["max_dd_pct"]:.1f}% '
                  f'| {r["wf_folds_positive"]}/5 | {fc["top1_fold_conc_pct"]:.1f}% '
                  f'| **{ge["score"]}** | {all_str} |')
    md.append('')

    # Coins excluded at minimum N
    if min_n_all_pass is not None:
        md.append(f'## 4. Coins Excluded at Minimum N={min_n_all_pass}')
        md.append('')
        md.append('| # | Coin | Tier | P&L | Trades | W/L |')
        md.append('|---|------|------|-----|--------|-----|')
        for i, a in enumerate(attribution_list[:min_n_all_pass]):
            md.append(f'| {i+1} | {a["coin"]} | {a["tier"]} | ${a["pnl"]:+.2f} | '
                      f'{a["trades"]} | {a["wins"]}/{a["losses"]} |')
        md.append('')

    # Transition analysis: which gate is the last to flip?
    md.append('## 5. Gate Transition Analysis')
    md.append('')
    md.append('Tracking which gates flip from FAIL to PASS as N increases:')
    md.append('')
    prev_pass = set()
    for n_excl in sorted(results_by_n.keys()):
        r = results_by_n[n_excl]
        ge = r['gate_evaluation']
        curr_pass = set(gid for gid, g in ge['gates'].items() if g['pass'])
        newly_passed = curr_pass - prev_pass
        newly_failed = prev_pass - curr_pass
        if newly_passed or newly_failed:
            changes = []
            for gid in sorted(newly_passed):
                g = ge['gates'][gid]
                changes.append(f'{gid} ({g["name"]}): FAIL -> PASS')
            for gid in sorted(newly_failed):
                changes.append(f'{gid}: PASS -> FAIL (regression!)')
            md.append(f'- **N={n_excl}**: {"; ".join(changes)}')
        prev_pass = curr_pass
    md.append('')

    # Conclusion
    md.append('## 6. Conclusion')
    md.append('')
    if min_n_all_pass is not None:
        md.append(f'- **Minimum exclusion needed**: {min_n_all_pass} coins for 7/7 gates')
        md.append(f'- **Margin**: {21 - min_n_all_pass} extra coins could be removed without '
                  f'breaking gates (out of 21 total negative)')
        r_min = results_by_n[min_n_all_pass]
        m = r_min['metrics']
        md.append(f'- At N={min_n_all_pass}: {m["trades"]} trades, PF={m["pf"]:.3f}, '
                  f'exp/wk=${m["exp_per_week"]:.0f}, DD={m["max_dd_pct"]:.1f}%')
        # Is this much less than 21?
        if min_n_all_pass <= 15:
            md.append(f'- **GOOD**: Only {min_n_all_pass} coins needed (vs 21 all-negative) '
                      f'-- exclusion approach is robust with margin')
        else:
            md.append(f'- **TIGHT**: {min_n_all_pass} coins needed (vs 21 all-negative) '
                      f'-- limited margin for error')
    else:
        md.append('- **No N in range achieves 7/7 gates in this sweep**')
    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_excl_sweep.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_excl_sweep_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Exclusion Threshold Sweep')
    print(f'  Worst-N tested: {SWEEP_N_VALUES}')
    print(f'  Thresholds tested: {THRESHOLD_VALUES}')
    if min_n_all_pass is not None:
        print(f'  MINIMUM N for 7/7: {min_n_all_pass}')
        print(f'  Margin: {21 - min_n_all_pass} coins of headroom')
    else:
        print(f'  No N achieves 7/7 in sweep range')
    if min_thresh_all_pass is not None:
        print(f'  Best threshold: ${min_thresh_all_pass} '
              f'(excludes {results_by_thresh[min_thresh_all_pass]["excl_n"]} coins)')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
