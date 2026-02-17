#!/usr/bin/env python3
"""
Part 2 -- Agent A3: Loss Cluster Analysis
==========================================
Identifies worst-performing coins on the 316-coin universe (T1+T2)
and tests whether excluding them fixes failing gates.

Usage:
    python -m strategies.hf.screening.run_part2_loss_cluster
    python -m strategies.hf.screening.run_part2_loss_cluster --dry-run
    python -m strategies.hf.screening.run_part2_loss_cluster --require-data
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from copy import deepcopy

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

GATE_THRESHOLDS = {
    'G1_trades_per_week': 10,
    'G2_max_gap_days': 2.5,
    'G3_exp_per_week_market': 0,
    'G4_exp_per_week_stress': 0,
    'G5_max_dd_pct': 20,
    'G6_wf_folds_positive': 4,
    'G8_top1_fold_conc_pct': 35,
}


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


def main():
    parser = argparse.ArgumentParser(description='Part 2 Agent A3: Loss Cluster Analysis')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent A3: Loss Cluster Analysis')
    print('  Objective: Find worst coins on 316 universe, test exclusion')
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
        print(f'  Exclusion strategies: top-5, top-10, all-negative, 1-trade-losers')
        sys.exit(0)

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

    # STEP 1: Full baseline + per-coin attribution
    print('\n' + '=' * 70)
    print('  STEP 1: Full baseline + per-coin attribution')
    print('=' * 70)
    baseline_trades = run_variant(data, tier_coins_full, tier_indicators_full,
                                  market_context, tier1_fee, tier2_fee)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'  Baseline: {baseline_metrics["trades"]} trades, PF={baseline_metrics["pf"]:.3f}, '
          f'P&L=${baseline_metrics["pnl"]:.0f}, exp/w=${baseline_metrics["exp_per_week"]:.2f}')

    sorted_coins, coin_stats = coin_pnl_attribution(baseline_trades)
    t1_set = set(tier_coins_full['tier1'])
    t2_set = set(tier_coins_full['tier2'])
    n_trading = len(sorted_coins)
    n_negative = sum(1 for _, s in sorted_coins if s['pnl'] < 0)
    n_positive = sum(1 for _, s in sorted_coins if s['pnl'] > 0)
    n_zero = sum(1 for _, s in sorted_coins if s['pnl'] == 0)

    print(f'\n  Coins with trades: {n_trading} / {n_t1+n_t2}')
    print(f'  Net-negative: {n_negative}, Net-positive: {n_positive}, Breakeven: {n_zero}')

    print(f'\n  --- Top-10 WORST coins ---')
    for i, (coin, stats) in enumerate(sorted_coins[:10]):
        tier = 'T1' if coin in t1_set else 'T2'
        print(f'    {i+1:2d}. {coin:12s} [{tier}]  P&L=${stats["pnl"]:+8.2f}  '
              f'trades={stats["trades"]}  W/L={stats["wins"]}/{stats["losses"]}')

    print(f'\n  --- Top-10 BEST coins ---')
    for i, (coin, stats) in enumerate(reversed(sorted_coins[-10:])):
        tier = 'T1' if coin in t1_set else 'T2'
        print(f'    {i+1:2d}. {coin:12s} [{tier}]  P&L=${stats["pnl"]:+8.2f}  '
              f'trades={stats["trades"]}  W/L={stats["wins"]}/{stats["losses"]}')

    single_trade_losers = [c for c, s in sorted_coins if s['trades'] == 1 and s['pnl'] < 0]
    print(f'\n  Single-trade losers: {len(single_trade_losers)} coins')

    # STEP 2: Build exclusion sets
    print('\n' + '=' * 70)
    print('  STEP 2: Exclusion strategies')
    print('=' * 70)
    worst_5 = set(c for c, _ in sorted_coins[:5])
    worst_10 = set(c for c, _ in sorted_coins[:10])
    all_negative = set(c for c, s in sorted_coins if s['pnl'] < 0)
    single_losers = set(single_trade_losers)

    exclusion_strategies = [
        ('baseline_316', set()),
        ('excl_worst5', worst_5),
        ('excl_worst10', worst_10),
        ('excl_all_negative', all_negative),
        ('excl_1trade_losers', single_losers),
    ]

    for name, excl_set in exclusion_strategies:
        if excl_set:
            excl_t1 = excl_set & t1_set
            excl_t2 = excl_set & t2_set
            print(f'  {name}: excluding {len(excl_set)} coins (T1: {len(excl_t1)}, T2: {len(excl_t2)})')
        else:
            print(f'  {name}: no exclusions (full universe)')

    # STEP 3: Run evaluations
    print('\n' + '=' * 70)
    print('  STEP 3: Running evaluations')
    print('=' * 70)
    results = []
    for name, excl_set in exclusion_strategies:
        filtered = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_set],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_set],
        }
        result = run_full_evaluation(
            label=name, data=data, tier_coins=filtered,
            all_indicators_cache=tier_indicators_full, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
        )
        result['excluded_coins'] = sorted(excl_set)
        results.append(result)

    elapsed_total = time.time() - t0_total

    # Build JSON report
    attribution_list = []
    for coin, stats in sorted_coins:
        tier = 'tier1' if coin in t1_set else 'tier2'
        attribution_list.append({'coin': coin, 'tier': tier, 'pnl': round(stats['pnl'], 2),
                                 'trades': stats['trades'], 'wins': stats['wins'],
                                 'losses': stats['losses']})

    best_result = max(results, key=lambda r: r['gate_evaluation']['pass_count'])
    baseline_ge = results[0]['gate_evaluation']

    report = {
        'run_header': {
            'task': 'part2_loss_cluster_analysis', 'agent': 'A3',
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
        'coin_attribution': {
            'total_coins_in_universe': n_t1 + n_t2, 'coins_with_trades': n_trading,
            'coins_net_negative': n_negative, 'coins_net_positive': n_positive,
            'coins_breakeven': n_zero, 'single_trade_losers': len(single_trade_losers),
            'worst_10': attribution_list[:10], 'best_10': attribution_list[-10:],
            'full_attribution': attribution_list,
        },
        'exclusion_results': results,
        'summary': {
            'best_exclusion': best_result['label'],
            'best_gate_score': best_result['gate_evaluation']['score'],
            'baseline_gate_score': baseline_ge['score'],
            'improvement': best_result['gate_evaluation']['pass_count'] - baseline_ge['pass_count'],
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_loss_cluster_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # Build Markdown report
    md = []
    md.append('# Part 2 -- Loss Cluster Analysis (Agent A3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={BASELINE_PARAMS["dev_thresh"]}, tp={BASELINE_PARAMS["tp_pct"]}, '
              f'sl={BASELINE_PARAMS["sl_pct"]}, tl={BASELINE_PARAMS["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')
    md.append('## 1. Per-Coin P&L Attribution')
    md.append('')
    md.append(f'- Coins in universe: {n_t1+n_t2}')
    md.append(f'- Coins with trades: {n_trading}')
    md.append(f'- Net-negative: {n_negative}')
    md.append(f'- Net-positive: {n_positive}')
    md.append(f'- Breakeven: {n_zero}')
    md.append(f'- Single-trade losers: {len(single_trade_losers)}')
    md.append('')
    md.append('### Top-10 Worst Coins')
    md.append('')
    md.append('| # | Coin | Tier | P&L | Trades | W/L |')
    md.append('|---|------|------|-----|--------|-----|')
    for i, (coin, stats) in enumerate(sorted_coins[:10]):
        tier = 'T1' if coin in t1_set else 'T2'
        md.append(f'| {i+1} | {coin} | {tier} | ${stats["pnl"]:+.2f} | '
                  f'{stats["trades"]} | {stats["wins"]}/{stats["losses"]} |')
    md.append('')
    md.append('### Top-10 Best Coins')
    md.append('')
    md.append('| # | Coin | Tier | P&L | Trades | W/L |')
    md.append('|---|------|------|-----|--------|-----|')
    for i, (coin, stats) in enumerate(reversed(sorted_coins[-10:])):
        tier = 'T1' if coin in t1_set else 'T2'
        md.append(f'| {i+1} | {coin} | {tier} | ${stats["pnl"]:+.2f} | '
                  f'{stats["trades"]} | {stats["wins"]}/{stats["losses"]} |')
    md.append('')
    md.append('## 2. Exclusion Strategies -- Gate Results')
    md.append('')
    md.append('| Strategy | Coins | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Score |')
    md.append('|----------|-------|--------|----|--------|-----|----|-----------|-------|')
    for r in results:
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        md.append(f'| {r["label"]} | {r["n_coins"]} | {m["trades"]} | {m["pf"]:.3f} '
                  f'| ${m["exp_per_week"]:.2f} | {m["max_dd_pct"]:.1f}% '
                  f'| {r["wf_folds_positive"]}/5 | {fc["top1_fold_conc_pct"]:.1f}% '
                  f'| **{ge["score"]}** |')
    md.append('')

    md.append('## 3. Gate Detail per Strategy')
    md.append('')
    for r in results:
        ge = r['gate_evaluation']
        md.append(f'### {r["label"]} ({r["n_coins"]} coins: T1={r["n_t1"]}, T2={r["n_t2"]})')
        md.append('')
        if r['excluded_coins']:
            md.append(f'**Excluded**: {", ".join(r["excluded_coins"])}')
            md.append('')
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')
        md.append('**Walk-Forward Folds:**')
        md.append('')
        md.append('| Fold | Trades | P&L | Positive |')
        md.append('|------|--------|-----|----------|')
        for fd in r.get('wf_fold_details', []):
            pos_str = 'YES' if fd['positive'] else 'NO'
            md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.0f} | {pos_str} |')
        md.append('')
        sm = r['stress_metrics']
        md.append(f'**Stress 2x**: trades={sm["trades"]}, PF={sm["pf"]:.3f}, '
                  f'exp/wk=${sm["exp_per_week"]:.2f}')
        md.append('')

    md.append('## 4. Conclusions')
    md.append('')
    best_non_baseline = max(results[1:], key=lambda r: r['gate_evaluation']['pass_count'])
    best_ne_ge = best_non_baseline['gate_evaluation']
    md.append(f'- **Baseline (316 coins)**: {baseline_ge["score"]} gates pass')
    md.append(f'- **Best exclusion**: {best_non_baseline["label"]} -> {best_ne_ge["score"]} gates pass')
    if best_ne_ge['pass_count'] > baseline_ge['pass_count']:
        delta = best_ne_ge['pass_count'] - baseline_ge['pass_count']
        md.append(f'- **Improvement**: +{delta} gates')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            bl = baseline_ge['gates'][gid]
            ex = best_ne_ge['gates'][gid]
            if not bl['pass'] and ex['pass']:
                md.append(f'  - {gid} ({ex["name"]}): FAIL -> PASS')
            elif bl['pass'] and not ex['pass']:
                md.append(f'  - {gid} ({ex["name"]}): PASS -> FAIL (regression!)')
    elif best_ne_ge['pass_count'] == baseline_ge['pass_count']:
        md.append('- **No improvement**: Exclusion does not change gate pass count')
    else:
        md.append('- **Regression**: Exclusion reduces gate pass count')
    md.append('')

    md.append('## 5. Actionable Finding')
    md.append('')
    total_neg_pnl = sum(s['pnl'] for _, s in sorted_coins if s['pnl'] < 0)
    total_pos_pnl = sum(s['pnl'] for _, s in sorted_coins if s['pnl'] > 0)
    md.append(f'- Total negative coin P&L: ${total_neg_pnl:+.2f} across {n_negative} coins')
    md.append(f'- Total positive coin P&L: ${total_pos_pnl:+.2f} across {n_positive} coins')
    md.append(f'- Net: ${total_neg_pnl + total_pos_pnl:+.2f}')
    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_loss_cluster.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_loss_cluster_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Loss Cluster Analysis')
    print(f'  Coins with trades: {n_trading}/{n_t1+n_t2}')
    print(f'  Net-negative coins: {n_negative}')
    print(f'  Baseline gates: {baseline_ge["score"]}')
    print(f'  Best exclusion: {best_non_baseline["label"]} -> {best_ne_ge["score"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
