#!/usr/bin/env python3
"""
Part 2 -- Agent C5-A2: sl=7 on 304-coin universe (excl_worst12)
================================================================
Tests sl=7 variant (dev_thresh=2.0, tp_pct=8, sl_pct=7, time_limit=10)
on the 304-coin universe (316 minus 12 worst coins by net P&L).

4-way comparison:
  A) sl=7 on 304 coins (NEW — this is the main test)
  B) sl=7 on 295 coins (reference from C3-A3)
  C) v5 (sl=5) on 304 coins (reference from C3-A1)
  D) v5 (sl=5) on 295 coins (leader)

Full gate test per config: baseline, stress 2x, walk-forward 5-fold,
fold concentration, gate evaluation (G1-G6, G8), coin P&L attribution.

Question: Does sl7 + 304 coins pass all gates? Could it be the
optimal conservative config (fewer exclusions than 295, better
robustness than sl=5)?

Output:
  reports/hf/part2_sl7_304_001.json
  reports/hf/part2_sl7_304_001.md

Usage:
    python -m strategies.hf.screening.run_part2_sl7_304
"""
import sys
import json
import time
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

# sl=7 variant (G7 robustness winner on 295 coins)
PARAMS_SL7 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10,
}

# v5 baseline (sl=5)
PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# 12 worst coins (excl_worst12) — same as robustness_304
EXCL_WORST12 = {
    'ALKIMI/USD', 'ANIME/USD', 'DBR/USD', 'ESX/USD', 'HOUSE/USD',
    'KET/USD', 'LMWR/USD', 'MXC/USD', 'ODOS/USD', 'PERP/USD',
    'TANSSI/USD', 'TITCOIN/USD',
}

# 21 net-negative coins (excl_all_negative) — same as sl7_295
EXCL_ALL_NEGATIVE = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
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


def load_candle_cache(timeframe='1h'):
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
        return None
    print(f'[Load] {len(coins_data)} coins loaded (from part files)')
    return coins_data


def load_universe_tiering():
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
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


def apply_exclusion(tier_coins_full, excluded_coins):
    """Apply exclusion set and return new tier_coins dict."""
    return {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in excluded_coins],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in excluded_coins],
    }


def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params):
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


def run_full_test(label, params, data, tier_coins, tier_indicators, market_context,
                  tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee, total_bars):
    """Run full 7-gate test (G1-G6, G8). Returns dict with all results."""
    n_t1 = len(tier_coins.get('tier1', []))
    n_t2 = len(tier_coins.get('tier2', []))
    print(f'\n{"=" * 70}')
    print(f'  {label}: Baseline backtest')
    print(f'  Params: dev={params["dev_thresh"]}, tp={params["tp_pct"]}, '
          f'sl={params["sl_pct"]}, tl={params["time_limit"]}')
    print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_t1+n_t2}')
    print(f'{"=" * 70}')

    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, params=params)
    metrics = compute_metrics(trades, total_bars)
    conc = compute_concentration(trades)
    n_coins_with_trades = len(set(t.get('pair', '') for t in trades))
    print(f'  Baseline: {metrics["trades"]} trades, PF={metrics["pf"]:.3f}, '
          f'P&L=${metrics["pnl"]:.0f}, WR={metrics["wr"]:.1f}%')
    print(f'  exp/wk=${metrics["exp_per_week"]:.2f}, DD={metrics["max_dd_pct"]:.1f}%, '
          f'gap={metrics["max_gap_days"]:.2f}d')
    print(f'  Coins with trades: {n_coins_with_trades}')
    print(f'  Concentration: top1={conc["top1_pct"]:.1f}% ({conc["top1_coin"]}), '
          f'top3={conc["top3_pct"]:.1f}%')

    sorted_coins, coin_stats = coin_pnl_attribution(trades)
    n_negative = sum(1 for _, s in sorted_coins if s['pnl'] < 0)
    n_positive = sum(1 for _, s in sorted_coins if s['pnl'] > 0)
    n_zero = sum(1 for _, s in sorted_coins if s['pnl'] == 0)
    print(f'  Per-coin: negative={n_negative}, positive={n_positive}, zero={n_zero}')

    # Stress test
    print(f'\n  --- Stress test (2x fees) ---')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee, params=params)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'  Stress: {stress_metrics["trades"]} trades, PF={stress_metrics["pf"]:.3f}, '
          f'P&L=${stress_metrics["pnl"]:.0f}, exp/wk=${stress_metrics["exp_per_week"]:.2f}')

    # Walk-Forward 5-fold
    print(f'\n  --- Walk-Forward 5-fold ---')
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5, params=params)
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
        status = 'POS' if is_pos else 'NEG'
        print(f'  Fold {fold_idx}: {fold_n} trades, P&L=${fold_pnl:.2f} [{status}]')
    fold_conc = compute_fold_concentration(fold_trades)
    print(f'  WF: {folds_positive}/5 positive, fold_conc={fold_conc["top1_fold_conc_pct"]:.1f}%')

    # Gate evaluation
    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    print(f'\n  --- Gate Evaluation ---')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'  {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')
    print(f'  VERDICT: {gate_eval["score"]}  '
          f'{"ALL PASS" if gate_eval["all_pass"] else "NOT ALL PASS"}')

    return {
        'metrics': metrics,
        'stress_metrics': stress_metrics,
        'folds_positive': folds_positive,
        'fold_details': fold_details,
        'fold_conc': fold_conc,
        'gate_eval': gate_eval,
        'trades': trades,
        'conc': conc,
        'sorted_coins': sorted_coins,
        'coin_stats': coin_stats,
        'n_coins_with_trades': n_coins_with_trades,
        'n_negative': n_negative,
        'n_positive': n_positive,
        'n_zero': n_zero,
    }


def build_config_result_dict(label, params, results, tier_coins, runtime):
    """Build JSON-serializable result dict for one config."""
    t1_set = set(tier_coins.get('tier1', []))
    sorted_coins = results['sorted_coins']
    attr_list = []
    for coin, stats in sorted_coins:
        tier = 'tier1' if coin in t1_set else 'tier2'
        attr_list.append({
            'coin': coin, 'tier': tier, 'pnl': round(stats['pnl'], 2),
            'trades': stats['trades'], 'wins': stats['wins'],
            'losses': stats['losses'],
        })
    n_t1 = len(tier_coins.get('tier1', []))
    n_t2 = len(tier_coins.get('tier2', []))
    return {
        'label': label,
        'params': params,
        'universe': f'T1={n_t1}, T2={n_t2}, total={n_t1+n_t2}',
        'baseline': {
            'metrics': results['metrics'],
            'concentration': results['conc'],
            'n_coins_with_trades': results['n_coins_with_trades'],
        },
        'stress_2x': {
            'trades': results['stress_metrics']['trades'],
            'pnl': results['stress_metrics']['pnl'],
            'pf': results['stress_metrics']['pf'],
            'exp_per_week': results['stress_metrics']['exp_per_week'],
        },
        'walk_forward': {
            'n_folds': 5,
            'folds_positive': results['folds_positive'],
            'fold_details': results['fold_details'],
            'fold_concentration': results['fold_conc'],
        },
        'gate_evaluation': results['gate_eval'],
        'coin_attribution': {
            'coins_with_trades': results['n_coins_with_trades'],
            'coins_net_negative': results['n_negative'],
            'coins_net_positive': results['n_positive'],
            'coins_breakeven': results['n_zero'],
            'worst_5': attr_list[:5],
            'best_5': attr_list[-5:],
        },
        'runtime_s': round(runtime, 1),
    }


def main():
    print('=' * 70)
    print('  Part 2 -- Agent C5-A2: sl=7 on 304-coin universe (excl_worst12)')
    print('  4-way comparison: sl7/304, sl7/295, v5/304, v5/295')
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

    # Load data
    data = load_candle_cache('1h')
    if data is None:
        print('[ERROR] No candle data found.')
        sys.exit(1)
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    if tiering is None:
        print('[ERROR] No universe tiering found.')
        sys.exit(1)
    tier_coins_full = build_tier_coins(tiering, available_coins)
    n_t1_full = len(tier_coins_full['tier1'])
    n_t2_full = len(tier_coins_full['tier2'])
    print(f'[Universe] Full: T1={n_t1_full}, T2={n_t2_full}, total={n_t1_full+n_t2_full}')

    # Build 2 universe variants
    tier_coins_304 = apply_exclusion(tier_coins_full, EXCL_WORST12)
    tier_coins_295 = apply_exclusion(tier_coins_full, EXCL_ALL_NEGATIVE)

    n304 = len(tier_coins_304['tier1']) + len(tier_coins_304['tier2'])
    n295 = len(tier_coins_295['tier1']) + len(tier_coins_295['tier2'])
    print(f'[Universe] 304-coin (excl_worst12): T1={len(tier_coins_304["tier1"])}, '
          f'T2={len(tier_coins_304["tier2"])}, total={n304}')
    print(f'[Universe] 295-coin (excl_all_neg): T1={len(tier_coins_295["tier1"])}, '
          f'T2={len(tier_coins_295["tier2"])}, total={n295}')

    # Precompute indicators for the LARGER universe (304 coins — superset of 295)
    # The 295-coin universe is a strict subset, so we can reuse the same indicators.
    print('[Indicators] Precomputing base indicators (304-coin superset)...')
    tier_indicators_304 = {}
    for tier_name, coins in tier_coins_304.items():
        if coins:
            t_ind = time.time()
            tier_indicators_304[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_304.items():
        if coins and tier_name in tier_indicators_304:
            extend_indicators(data, coins, tier_indicators_304[tier_name])
            cov = get_feature_coverage(tier_indicators_304[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # For 295-coin runs, create a filtered view of the same indicators
    tier_indicators_295 = {}
    for tier_name in ('tier1', 'tier2'):
        coins_295 = set(tier_coins_295.get(tier_name, []))
        if tier_name in tier_indicators_304:
            tier_indicators_295[tier_name] = {
                c: ind for c, ind in tier_indicators_304[tier_name].items()
                if c in coins_295
            }

    print('[Market Context] Precomputing...')
    # Use all 304 coins + BTC for market context (superset)
    all_coins = list(set(tier_coins_304.get('tier1', []) + tier_coins_304.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicators
    for tier_name, ind_dict in tier_indicators_304.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_304, tier_coins_304)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # =================================================================
    # CONFIG A: sl=7 on 304 coins (NEW — the main test)
    # =================================================================
    t0_a = time.time()
    results_a = run_full_test(
        'CONFIG A: sl=7 / 304 coins', PARAMS_SL7,
        data, tier_coins_304, tier_indicators_304, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee, total_bars,
    )
    runtime_a = time.time() - t0_a

    # =================================================================
    # CONFIG B: sl=7 on 295 coins (reference from C3-A3)
    # =================================================================
    t0_b = time.time()
    results_b = run_full_test(
        'CONFIG B: sl=7 / 295 coins', PARAMS_SL7,
        data, tier_coins_295, tier_indicators_295, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee, total_bars,
    )
    runtime_b = time.time() - t0_b

    # =================================================================
    # CONFIG C: v5 (sl=5) on 304 coins (reference from C3-A1)
    # =================================================================
    t0_c = time.time()
    results_c = run_full_test(
        'CONFIG C: v5 (sl=5) / 304 coins', PARAMS_V5,
        data, tier_coins_304, tier_indicators_304, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee, total_bars,
    )
    runtime_c = time.time() - t0_c

    # =================================================================
    # CONFIG D: v5 (sl=5) on 295 coins (leader)
    # =================================================================
    t0_d = time.time()
    results_d = run_full_test(
        'CONFIG D: v5 (sl=5) / 295 coins', PARAMS_V5,
        data, tier_coins_295, tier_indicators_295, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee, total_bars,
    )
    runtime_d = time.time() - t0_d

    elapsed_total = time.time() - t0_total

    # =================================================================
    # 4-WAY COMPARISON TABLE
    # =================================================================
    configs = [
        ('A: sl7/304', results_a),
        ('B: sl7/295', results_b),
        ('C: v5/304', results_c),
        ('D: v5/295', results_d),
    ]

    print('\n' + '=' * 90)
    print('  4-WAY COMPARISON TABLE')
    print('=' * 90)
    hdr = f'  {"Metric":<22s}'
    for label, _ in configs:
        hdr += f' {label:>14s}'
    print(hdr)
    print(f'  {"-"*22}' + f' {"-"*14}' * 4)

    # Trades
    row = f'  {"Trades":<22s}'
    for _, r in configs:
        row += f' {r["metrics"]["trades"]:>14d}'
    print(row)

    # P&L
    row = f'  {"P&L":<22s}'
    for _, r in configs:
        row += f' {"$"+str(r["metrics"]["pnl"]):>14s}'
    print(row)

    # PF
    row = f'  {"PF":<22s}'
    for _, r in configs:
        row += f' {r["metrics"]["pf"]:>14.3f}'
    print(row)

    # WR
    row = f'  {"WR%":<22s}'
    for _, r in configs:
        row += f' {str(r["metrics"]["wr"])+"%":>14s}'
    print(row)

    # Exp/wk
    row = f'  {"Exp/wk":<22s}'
    for _, r in configs:
        row += f' {"$"+str(round(r["metrics"]["exp_per_week"],2)):>14s}'
    print(row)

    # DD
    row = f'  {"DD%":<22s}'
    for _, r in configs:
        row += f' {str(r["metrics"]["max_dd_pct"])+"%":>14s}'
    print(row)

    # Stress
    row = f'  {"Stress PF":<22s}'
    for _, r in configs:
        row += f' {r["stress_metrics"]["pf"]:>14.3f}'
    print(row)

    row = f'  {"Stress Exp/wk":<22s}'
    for _, r in configs:
        row += f' {"$"+str(round(r["stress_metrics"]["exp_per_week"],2)):>14s}'
    print(row)

    # WF
    row = f'  {"WF folds":<22s}'
    for _, r in configs:
        row += f' {str(r["folds_positive"])+"/5":>14s}'
    print(row)

    # Fold conc
    row = f'  {"Fold conc":<22s}'
    for _, r in configs:
        row += f' {str(r["fold_conc"]["top1_fold_conc_pct"])+"%":>14s}'
    print(row)

    # Gates
    row = f'  {"Gates":<22s}'
    for _, r in configs:
        row += f' {r["gate_eval"]["score"]:>14s}'
    print(row)

    # Determine best config
    best_idx = 0
    best_score = 0
    for i, (label, r) in enumerate(configs):
        score = 0
        # Gates all pass: +10
        if r['gate_eval']['all_pass']:
            score += 10
        # WF folds: +folds
        score += r['folds_positive']
        # PF bonus
        score += r['metrics']['pf']
        # Lower DD: +1 if < 15
        if r['metrics']['max_dd_pct'] < 15:
            score += 1
        # Fold conc < 35: +1
        if r['fold_conc']['top1_fold_conc_pct'] < 35:
            score += 1
        if score > best_score:
            best_score = score
            best_idx = i

    print(f'\n  BEST CONFIG: {configs[best_idx][0]} (composite={best_score:.1f})')

    # =================================================================
    # BUILD JSON REPORT
    # =================================================================
    report = {
        'run_header': {
            'task': 'part2_sl7_304',
            'agent': 'C5-A2',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'question': 'Does sl=7 + 304 coins (excl_worst12) pass all gates?',
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1),
                         'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                                'tier2': round(stress_tier2_fee * 10000, 1)},
            'universes': {
                '304_coin': {
                    'description': 'excl_worst12',
                    'T1': len(tier_coins_304['tier1']),
                    'T2': len(tier_coins_304['tier2']),
                    'total': n304,
                    'excluded': sorted(EXCL_WORST12),
                },
                '295_coin': {
                    'description': 'excl_all_negative',
                    'T1': len(tier_coins_295['tier1']),
                    'T2': len(tier_coins_295['tier2']),
                    'total': n295,
                    'excluded': sorted(EXCL_ALL_NEGATIVE),
                },
            },
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'config_a_sl7_304': build_config_result_dict(
            'sl7/304', PARAMS_SL7, results_a, tier_coins_304, runtime_a),
        'config_b_sl7_295': build_config_result_dict(
            'sl7/295', PARAMS_SL7, results_b, tier_coins_295, runtime_b),
        'config_c_v5_304': build_config_result_dict(
            'v5/304', PARAMS_V5, results_c, tier_coins_304, runtime_c),
        'config_d_v5_295': build_config_result_dict(
            'v5/295', PARAMS_V5, results_d, tier_coins_295, runtime_d),
        'comparison': {
            'best_config': configs[best_idx][0],
            'matrix': {},
        },
    }

    # Build comparison matrix
    for label, r in configs:
        report['comparison']['matrix'][label] = {
            'trades': r['metrics']['trades'],
            'pnl': r['metrics']['pnl'],
            'pf': r['metrics']['pf'],
            'wr': r['metrics']['wr'],
            'exp_per_week': round(r['metrics']['exp_per_week'], 2),
            'max_dd_pct': r['metrics']['max_dd_pct'],
            'stress_pf': r['stress_metrics']['pf'],
            'stress_exp_per_week': round(r['stress_metrics']['exp_per_week'], 2),
            'wf_folds': r['folds_positive'],
            'fold_conc_pct': r['fold_conc']['top1_fold_conc_pct'],
            'gates': r['gate_eval']['score'],
            'all_pass': r['gate_eval']['all_pass'],
        }

    json_path = ROOT / 'reports' / 'hf' / 'part2_sl7_304_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # =================================================================
    # BUILD MARKDOWN REPORT
    # =================================================================
    md = []
    md.append('# Part 2 -- sl=7 on 304-coin Universe (Agent C5-A2)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Agent**: C5-A2')
    md.append(f'**Question**: Does sl=7 + 304 coins (excl_worst12) pass all gates?')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    md.append('## Universes')
    md.append('')
    md.append(f'- **304 coins**: T1={len(tier_coins_304["tier1"])}, '
              f'T2={len(tier_coins_304["tier2"])} (excl 12 worst by P&L)')
    md.append(f'- **295 coins**: T1={len(tier_coins_295["tier1"])}, '
              f'T2={len(tier_coins_295["tier2"])} (excl 21 all net-negative)')
    md.append(f'- **Difference**: 9 extra coins in 304 that are in excl_all_neg but not excl_worst12')
    md.append('')

    # 4-way comparison table
    md.append('## 4-Way Comparison')
    md.append('')
    md.append('| Metric | A: sl7/304 | B: sl7/295 | C: v5/304 | D: v5/295 |')
    md.append('|--------|------------|------------|-----------|-----------|')

    def fmt_val(r, key, prefix='', suffix='', decimals=None):
        val = r['metrics'].get(key, r.get(key, 0))
        if decimals is not None:
            return f'{prefix}{val:.{decimals}f}{suffix}'
        return f'{prefix}{val}{suffix}'

    ra, rb, rc, rd = results_a, results_b, results_c, results_d

    md.append(f'| Trades | {ra["metrics"]["trades"]} | {rb["metrics"]["trades"]} | '
              f'{rc["metrics"]["trades"]} | {rd["metrics"]["trades"]} |')
    md.append(f'| P&L | ${ra["metrics"]["pnl"]:.2f} | ${rb["metrics"]["pnl"]:.2f} | '
              f'${rc["metrics"]["pnl"]:.2f} | ${rd["metrics"]["pnl"]:.2f} |')
    md.append(f'| PF | {ra["metrics"]["pf"]:.3f} | {rb["metrics"]["pf"]:.3f} | '
              f'{rc["metrics"]["pf"]:.3f} | {rd["metrics"]["pf"]:.3f} |')
    md.append(f'| WR% | {ra["metrics"]["wr"]:.1f}% | {rb["metrics"]["wr"]:.1f}% | '
              f'{rc["metrics"]["wr"]:.1f}% | {rd["metrics"]["wr"]:.1f}% |')
    md.append(f'| Exp/wk | ${ra["metrics"]["exp_per_week"]:.2f} | ${rb["metrics"]["exp_per_week"]:.2f} | '
              f'${rc["metrics"]["exp_per_week"]:.2f} | ${rd["metrics"]["exp_per_week"]:.2f} |')
    md.append(f'| DD% | {ra["metrics"]["max_dd_pct"]:.1f}% | {rb["metrics"]["max_dd_pct"]:.1f}% | '
              f'{rc["metrics"]["max_dd_pct"]:.1f}% | {rd["metrics"]["max_dd_pct"]:.1f}% |')
    md.append(f'| Max Gap (days) | {ra["metrics"]["max_gap_days"]:.2f} | {rb["metrics"]["max_gap_days"]:.2f} | '
              f'{rc["metrics"]["max_gap_days"]:.2f} | {rd["metrics"]["max_gap_days"]:.2f} |')
    md.append(f'| Stress PF | {ra["stress_metrics"]["pf"]:.3f} | {rb["stress_metrics"]["pf"]:.3f} | '
              f'{rc["stress_metrics"]["pf"]:.3f} | {rd["stress_metrics"]["pf"]:.3f} |')
    md.append(f'| Stress Exp/wk | ${ra["stress_metrics"]["exp_per_week"]:.2f} | '
              f'${rb["stress_metrics"]["exp_per_week"]:.2f} | '
              f'${rc["stress_metrics"]["exp_per_week"]:.2f} | '
              f'${rd["stress_metrics"]["exp_per_week"]:.2f} |')
    md.append(f'| WF folds | {ra["folds_positive"]}/5 | {rb["folds_positive"]}/5 | '
              f'{rc["folds_positive"]}/5 | {rd["folds_positive"]}/5 |')
    md.append(f'| Fold conc | {ra["fold_conc"]["top1_fold_conc_pct"]:.1f}% | '
              f'{rb["fold_conc"]["top1_fold_conc_pct"]:.1f}% | '
              f'{rc["fold_conc"]["top1_fold_conc_pct"]:.1f}% | '
              f'{rd["fold_conc"]["top1_fold_conc_pct"]:.1f}% |')
    md.append(f'| **Gates** | **{ra["gate_eval"]["score"]}** | **{rb["gate_eval"]["score"]}** | '
              f'**{rc["gate_eval"]["score"]}** | **{rd["gate_eval"]["score"]}** |')
    md.append('')

    # Per-config detailed gate tables
    for label, r, tc, params in [
        ('A: sl=7 / 304 coins (NEW)', results_a, tier_coins_304, PARAMS_SL7),
        ('B: sl=7 / 295 coins (ref C3-A3)', results_b, tier_coins_295, PARAMS_SL7),
        ('C: v5 (sl=5) / 304 coins (ref C3-A1)', results_c, tier_coins_304, PARAMS_V5),
        ('D: v5 (sl=5) / 295 coins (leader)', results_d, tier_coins_295, PARAMS_V5),
    ]:
        md.append(f'## Config {label}')
        md.append('')
        n_t1 = len(tc.get('tier1', []))
        n_t2 = len(tc.get('tier2', []))
        md.append(f'**Params**: dev={params["dev_thresh"]}, tp={params["tp_pct"]}, '
                  f'sl={params["sl_pct"]}, tl={params["time_limit"]}')
        md.append(f'**Universe**: T1={n_t1}, T2={n_t2}, total={n_t1+n_t2}')
        md.append('')

        md.append('### Gate Evaluation')
        md.append('')
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = r['gate_eval']['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')
        md.append(f'**Overall**: {r["gate_eval"]["score"]} gates pass '
                  f'{"-- ALL PASS" if r["gate_eval"]["all_pass"] else ""}')
        md.append('')

        # Walk-forward detail
        md.append('### Walk-Forward Detail')
        md.append('')
        md.append('| Fold | Trades | P&L | Positive |')
        md.append('|------|--------|-----|----------|')
        for fd in r['fold_details']:
            pos_str = 'YES' if fd['positive'] else 'NO'
            md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.2f} | {pos_str} |')
        md.append('')

        # Top/worst 5 coins
        t1_set = set(tc.get('tier1', []))
        md.append('### Top 5 Coins (by P&L)')
        md.append('')
        md.append('| # | Coin | Tier | P&L | Trades | W/L |')
        md.append('|---|------|------|-----|--------|-----|')
        for i, (coin, stats) in enumerate(reversed(r['sorted_coins'][-5:])):
            tier = 'T1' if coin in t1_set else 'T2'
            md.append(f'| {i+1} | {coin} | {tier} | ${stats["pnl"]:+.2f} | '
                      f'{stats["trades"]} | {stats["wins"]}/{stats["losses"]} |')
        md.append('')

        md.append('### Worst 5 Coins (by P&L)')
        md.append('')
        md.append('| # | Coin | Tier | P&L | Trades | W/L |')
        md.append('|---|------|------|-----|--------|-----|')
        for i, (coin, stats) in enumerate(r['sorted_coins'][:5]):
            tier = 'T1' if coin in t1_set else 'T2'
            md.append(f'| {i+1} | {coin} | {tier} | ${stats["pnl"]:+.2f} | '
                      f'{stats["trades"]} | {stats["wins"]}/{stats["losses"]} |')
        md.append('')

    # Verdict section
    md.append('## Verdict')
    md.append('')

    a_pass = results_a['gate_eval']['all_pass']
    b_pass = results_b['gate_eval']['all_pass']

    if a_pass:
        md.append('**sl=7 / 304 coins: ALL GATES PASS.**')
        md.append('')
        md.append('This confirms that sl=7 is viable on the 304-coin universe (excl_worst12). ')
        md.append('Key findings:')
        md.append('')
        # Compare sl7/304 vs v5/304
        pf_delta = results_a['metrics']['pf'] - results_c['metrics']['pf']
        wr_delta = results_a['metrics']['wr'] - results_c['metrics']['wr']
        wf_delta = results_a['folds_positive'] - results_c['folds_positive']
        fc_delta = results_a['fold_conc']['top1_fold_conc_pct'] - results_c['fold_conc']['top1_fold_conc_pct']
        md.append(f'- **PF delta (sl7 vs v5, 304 coins)**: {pf_delta:+.3f}')
        md.append(f'- **WR delta**: {wr_delta:+.1f}%')
        md.append(f'- **WF delta**: {wf_delta:+d} folds')
        md.append(f'- **Fold conc delta**: {fc_delta:+.1f}%')
        md.append('')
        # Compare sl7/304 vs sl7/295
        pf_delta2 = results_a['metrics']['pf'] - results_b['metrics']['pf']
        exp_delta = results_a['metrics']['exp_per_week'] - results_b['metrics']['exp_per_week']
        md.append(f'- **sl7/304 vs sl7/295 PF**: {pf_delta2:+.3f}')
        md.append(f'- **sl7/304 vs sl7/295 Exp/wk**: ${exp_delta:+.2f}')
    else:
        md.append('**sl=7 / 304 coins: NOT ALL GATES PASS.**')
        md.append('')
        failed_gates = [gid for gid, g in results_a['gate_eval']['gates'].items()
                        if not g['pass']]
        md.append(f'Failed gates: {", ".join(failed_gates)}')
        md.append('')
        md.append('The 304-coin universe may include too many problematic coins for sl=7. ')
        md.append('The 295-coin universe remains the better choice.')

    md.append('')
    md.append(f'**Best config**: {configs[best_idx][0]}')
    md.append('')

    # Recommendation
    md.append('## Recommendation')
    md.append('')
    if a_pass and b_pass:
        md.append('Both sl=7/304 and sl=7/295 pass all gates. The 304-coin config is ')
        md.append('preferable if it has similar or better robustness, since it uses a ')
        md.append('less aggressive exclusion list (12 vs 21 coins).')
        md.append('')
        md.append('Compare fold concentration and WF folds to determine the more robust option.')
    elif a_pass:
        md.append('sl=7/304 passes all gates. Consider this as the production candidate ')
        md.append('since it requires fewer exclusions.')
    else:
        md.append('Stick with sl=7/295 (or v5/295) as the production candidate. ')
        md.append('The 304-coin universe does not pass all gates with sl=7.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_sl7_304.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_sl7_304_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: 4-way comparison (sl7 x v5) x (304 x 295)')
    for label, r in configs:
        m = r['metrics']
        ge = r['gate_eval']
        fc = r['fold_conc']
        print(f'  {label}: Trades={m["trades"]}, PF={m["pf"]:.3f}, '
              f'P&L=${m["pnl"]:.0f}, WF={r["folds_positive"]}/5, '
              f'FC={fc["top1_fold_conc_pct"]:.1f}%, Gates={ge["score"]}')
    print(f'  BEST: {configs[best_idx][0]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
