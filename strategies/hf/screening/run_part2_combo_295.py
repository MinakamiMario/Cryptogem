#!/usr/bin/env python3
"""
Part 2 -- Agent C2-A4: Combined tp10_sl4_tl8 + excl_all_negative (295 coins)
=============================================================================
Tests the COMBINED best findings from Cycle 1:
  - A3: excl_all_negative (295 coins) passes 7/7 gates with v5 params
  - A6: tp10_sl4_tl8 fixes fold concentration (25.8% on 135 coins)
  - Combined: tp10_sl4_tl8 on 295-coin universe

Also runs v5 params on same 295 coins for head-to-head comparison.

Usage:
    python -m strategies.hf.screening.run_part2_combo_295
    python -m strategies.hf.screening.run_part2_combo_295 --dry-run
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

# The 21 net-negative coins from A3 loss cluster analysis
EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# Two configs to compare head-to-head on 295 coins
COMBO_PARAMS = {
    'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 4, 'time_limit': 8,
}
V5_PARAMS = {
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
        params = COMBO_PARAMS
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
        params = COMBO_PARAMS
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


def run_full_evaluation(label, data, tier_coins, tier_indicators_cache,
                        market_context, tier1_fee, tier2_fee,
                        stress_tier1_fee, stress_tier2_fee, total_bars,
                        params=None):
    """Run baseline + stress + WF + gate evaluation for a given param set."""
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in tier_indicators_cache:
            tier_indicators[tier_name] = {
                c: tier_indicators_cache[tier_name][c]
                for c in coins if c in tier_indicators_cache[tier_name]
            }
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, params=params)
    metrics = compute_metrics(trades, total_bars)
    conc = compute_concentration(trades)
    n_coins_with_trades = len(set(t.get('pair', '') for t in trades))
    print(f'    trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'exp/w=${metrics["exp_per_week"]:.2f} DD={metrics["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Running stress (2x fees)...')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee, params=params)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'    stress: trades={stress_metrics["trades"]} exp/w=${stress_metrics["exp_per_week"]:.2f}')

    print(f'  [{label}] Running walk-forward 5-fold...')
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
    fold_conc = compute_fold_concentration(fold_trades)
    print(f'    WF={folds_positive}/5  fold_conc={fold_conc["top1_fold_conc_pct"]:.1f}%')

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    # Per-coin attribution
    sorted_coins_attr, coin_stats = coin_pnl_attribution(trades)

    return {
        'label': label,
        'params': params,
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
        'coin_attribution': {
            'worst_5': [{'coin': c, 'pnl': round(s['pnl'], 2), 'trades': s['trades'],
                        'wins': s['wins'], 'losses': s['losses']}
                       for c, s in sorted_coins_attr[:5]],
            'best_5': [{'coin': c, 'pnl': round(s['pnl'], 2), 'trades': s['trades'],
                       'wins': s['wins'], 'losses': s['losses']}
                      for c, s in sorted_coins_attr[-5:]],
            'n_positive': sum(1 for _, s in sorted_coins_attr if s['pnl'] > 0),
            'n_negative': sum(1 for _, s in sorted_coins_attr if s['pnl'] < 0),
            'n_zero': sum(1 for _, s in sorted_coins_attr if s['pnl'] == 0),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C2-A4: Combined tp10_sl4_tl8 + excl_all_negative (295 coins)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C2-A4: Combined Config Test')
    print('  tp10_sl4_tl8 on 295-coin universe (excl 21 net-negative)')
    print('  + HEAD-TO-HEAD vs v5 params on same 295 coins')
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
    n_t1_full = len(tier_coins_full['tier1'])
    n_t2_full = len(tier_coins_full['tier2'])
    print(f'[Universe] Full: T1={n_t1_full}, T2={n_t2_full}, total={n_t1_full+n_t2_full}')

    # Build 295-coin universe (exclude 21 net-negative)
    tier_coins_295 = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }
    n_t1 = len(tier_coins_295['tier1'])
    n_t2 = len(tier_coins_295['tier2'])
    n_excluded = (n_t1_full - n_t1) + (n_t2_full - n_t2)
    print(f'[Universe] 295-coin: T1={n_t1}, T2={n_t2}, total={n_t1+n_t2} (excluded {n_excluded})')

    if not tier_coins_295['tier1'] and not tier_coins_295['tier2']:
        print('[ERROR] No coins after exclusion.')
        sys.exit(1)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2} (295 coins)')
        print(f'  Combo params: {COMBO_PARAMS}')
        print(f'  V5 params:    {V5_PARAMS}')
        print(f'  Excluded: {sorted(EXCLUDED_COINS)}')
        print(f'  Tests: baseline, stress 2x, walk-forward 5-fold')
        sys.exit(0)

    # Precompute indicators (shared between both param sets)
    print('[Indicators] Precomputing base indicators for 295-coin universe...')
    tier_indicators = {}
    for tier_name, coins in tier_coins_295.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_295.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_295.get('tier1', []) + tier_coins_295.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicators
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins_295)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ===== RUN 1: COMBO params (tp10_sl4_tl8) on 295 coins =====
    print('\n' + '=' * 70)
    print('  RUN 1: COMBO (tp10_sl4_tl8) on 295 coins')
    print(f'  Params: {COMBO_PARAMS}')
    print('=' * 70)
    combo_result = run_full_evaluation(
        label='combo_tp10_sl4_tl8_295',
        data=data, tier_coins=tier_coins_295,
        tier_indicators_cache=tier_indicators, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars, params=COMBO_PARAMS,
    )

    # ===== RUN 2: V5 params on 295 coins (head-to-head) =====
    print('\n' + '=' * 70)
    print('  RUN 2: V5 baseline (tp8_sl5_tl10) on 295 coins')
    print(f'  Params: {V5_PARAMS}')
    print('=' * 70)
    v5_result = run_full_evaluation(
        label='v5_tp8_sl5_tl10_295',
        data=data, tier_coins=tier_coins_295,
        tier_indicators_cache=tier_indicators, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars, params=V5_PARAMS,
    )

    elapsed_total = time.time() - t0_total

    # ===== HEAD-TO-HEAD COMPARISON =====
    print('\n' + '=' * 70)
    print('  HEAD-TO-HEAD COMPARISON (295 coins)')
    print('=' * 70)
    for label, r in [('COMBO (tp10_sl4_tl8)', combo_result), ('V5 (tp8_sl5_tl10)', v5_result)]:
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        sm = r['stress_metrics']
        print(f'\n  {label}:')
        print(f'    Trades={m["trades"]}  PF={m["pf"]:.3f}  WR={m["wr"]:.1f}%  P&L=${m["pnl"]:.0f}')
        print(f'    Exp/wk=${m["exp_per_week"]:.2f}  DD={m["max_dd_pct"]:.1f}%  Gap={m["max_gap_days"]:.2f}d')
        print(f'    Stress: exp/wk=${sm["exp_per_week"]:.2f}  PF={sm["pf"]:.3f}')
        print(f'    WF={r["wf_folds_positive"]}/5  Fold conc={fc["top1_fold_conc_pct"]:.1f}%')
        print(f'    Gates: {ge["score"]}  all_pass={ge["all_pass"]}')

    # ===== BUILD REPORT =====
    report = {
        'run_header': {
            'task': 'part2_combo_295', 'agent': 'C2-A4',
            'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'combo_params': COMBO_PARAMS, 'v5_params': V5_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                               'tier2': round(stress_tier2_fee * 10000, 1)},
            'universe_full': f'T1({n_t1_full})+T2({n_t2_full})',
            'universe_295': f'T1({n_t1})+T2({n_t2})',
            'excluded_coins': sorted(EXCLUDED_COINS),
            'n_excluded': n_excluded,
            'timeframe': '1h', 'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'combo_result': combo_result,
        'v5_result': v5_result,
        'head_to_head': {
            'combo_gates': combo_result['gate_evaluation']['score'],
            'v5_gates': v5_result['gate_evaluation']['score'],
            'combo_all_pass': combo_result['gate_evaluation']['all_pass'],
            'v5_all_pass': v5_result['gate_evaluation']['all_pass'],
            'combo_pnl': combo_result['metrics']['pnl'],
            'v5_pnl': v5_result['metrics']['pnl'],
            'combo_exp_per_week': combo_result['metrics']['exp_per_week'],
            'v5_exp_per_week': v5_result['metrics']['exp_per_week'],
            'combo_fold_conc': combo_result['fold_concentration']['top1_fold_conc_pct'],
            'v5_fold_conc': v5_result['fold_concentration']['top1_fold_conc_pct'],
            'combo_dd': combo_result['metrics']['max_dd_pct'],
            'v5_dd': v5_result['metrics']['max_dd_pct'],
            'winner': 'combo' if combo_result['gate_evaluation']['pass_count'] >
                      v5_result['gate_evaluation']['pass_count'] else
                      ('v5' if v5_result['gate_evaluation']['pass_count'] >
                       combo_result['gate_evaluation']['pass_count'] else 'tie'),
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_combo_295_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ===== BUILD MARKDOWN =====
    md = []
    md.append('# Part 2 -- Combined Config Test: tp10_sl4_tl8 on 295 coins (Agent C2-A4)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: 295 coins (316 minus 21 net-negative)')
    md.append(f'**Tier split**: T1={n_t1}, T2={n_t2}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    md.append('## 1. Head-to-Head Comparison')
    md.append('')
    md.append('| Metric | COMBO (tp10/sl4/tl8) | V5 (tp8/sl5/tl10) | Better |')
    md.append('|--------|---------------------|-------------------|--------|')

    c_m = combo_result['metrics']
    v_m = v5_result['metrics']
    c_sm = combo_result['stress_metrics']
    v_sm = v5_result['stress_metrics']
    c_ge = combo_result['gate_evaluation']
    v_ge = v5_result['gate_evaluation']
    c_fc = combo_result['fold_concentration']['top1_fold_conc_pct']
    v_fc = v5_result['fold_concentration']['top1_fold_conc_pct']

    def better(a, b, higher_is_better=True):
        if higher_is_better:
            return 'COMBO' if a > b else ('V5' if b > a else 'TIE')
        else:
            return 'COMBO' if a < b else ('V5' if b < a else 'TIE')

    md.append(f'| Trades | {c_m["trades"]} | {v_m["trades"]} | {better(c_m["trades"], v_m["trades"])} |')
    md.append(f'| P&L | ${c_m["pnl"]:.0f} | ${v_m["pnl"]:.0f} | {better(c_m["pnl"], v_m["pnl"])} |')
    md.append(f'| PF | {c_m["pf"]:.3f} | {v_m["pf"]:.3f} | {better(c_m["pf"], v_m["pf"])} |')
    md.append(f'| WR | {c_m["wr"]:.1f}% | {v_m["wr"]:.1f}% | {better(c_m["wr"], v_m["wr"])} |')
    md.append(f'| Exp/wk | ${c_m["exp_per_week"]:.2f} | ${v_m["exp_per_week"]:.2f} | '
              f'{better(c_m["exp_per_week"], v_m["exp_per_week"])} |')
    md.append(f'| Max DD | {c_m["max_dd_pct"]:.1f}% | {v_m["max_dd_pct"]:.1f}% | '
              f'{better(c_m["max_dd_pct"], v_m["max_dd_pct"], False)} |')
    md.append(f'| Max Gap | {c_m["max_gap_days"]:.2f}d | {v_m["max_gap_days"]:.2f}d | '
              f'{better(c_m["max_gap_days"], v_m["max_gap_days"], False)} |')
    md.append(f'| Stress Exp/wk | ${c_sm["exp_per_week"]:.2f} | ${v_sm["exp_per_week"]:.2f} | '
              f'{better(c_sm["exp_per_week"], v_sm["exp_per_week"])} |')
    md.append(f'| WF folds+ | {combo_result["wf_folds_positive"]}/5 | '
              f'{v5_result["wf_folds_positive"]}/5 | '
              f'{better(combo_result["wf_folds_positive"], v5_result["wf_folds_positive"])} |')
    md.append(f'| Fold conc | {c_fc:.1f}% | {v_fc:.1f}% | {better(c_fc, v_fc, False)} |')
    md.append(f'| **Gates** | **{c_ge["score"]}** | **{v_ge["score"]}** | '
              f'**{better(c_ge["pass_count"], v_ge["pass_count"])}** |')
    md.append('')

    # Gate detail for each
    for label, r in [('COMBO (tp10/sl4/tl8)', combo_result), ('V5 (tp8/sl5/tl10)', v5_result)]:
        ge = r['gate_evaluation']
        md.append(f'## 2. Gate Detail: {label}')
        md.append('')
        md.append(f'**Params**: {r["params"]}')
        md.append(f'**Coins**: {r["n_coins"]} (T1={r["n_t1"]}, T2={r["n_t2"]})')
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
        md.append(f'**Coin concentration**: top1={r["concentration"]["top1_pct"]:.1f}% '
                  f'({r["concentration"]["top1_coin"]}), top3={r["concentration"]["top3_pct"]:.1f}%')
        md.append('')

    # Per-coin attribution for combo
    md.append('## 3. Per-Coin Attribution (COMBO config)')
    md.append('')
    ca = combo_result['coin_attribution']
    md.append(f'- Coins with trades: {combo_result["n_coins_with_trades"]}')
    md.append(f'- Net-positive: {ca["n_positive"]}')
    md.append(f'- Net-negative: {ca["n_negative"]}')
    md.append('')
    md.append('### Worst 5 Coins')
    md.append('')
    md.append('| Coin | P&L | Trades | W/L |')
    md.append('|------|-----|--------|-----|')
    for c in ca['worst_5']:
        md.append(f'| {c["coin"]} | ${c["pnl"]:+.2f} | {c["trades"]} | {c["wins"]}/{c["losses"]} |')
    md.append('')
    md.append('### Best 5 Coins')
    md.append('')
    md.append('| Coin | P&L | Trades | W/L |')
    md.append('|------|-----|--------|-----|')
    for c in ca['best_5']:
        md.append(f'| {c["coin"]} | ${c["pnl"]:+.2f} | {c["trades"]} | {c["wins"]}/{c["losses"]} |')
    md.append('')

    # Conclusions
    md.append('## 4. Conclusions')
    md.append('')
    h2h = report['head_to_head']
    if h2h['combo_all_pass']:
        md.append('**COMBO passes ALL 7 gates.**')
    else:
        combo_fails = [gid for gid, g in c_ge['gates'].items() if not g['pass']]
        md.append(f'**COMBO fails gates: {", ".join(combo_fails)}**')
    if h2h['v5_all_pass']:
        md.append('**V5 passes ALL 7 gates.**')
    else:
        v5_fails = [gid for gid, g in v_ge['gates'].items() if not g['pass']]
        md.append(f'**V5 fails gates: {", ".join(v5_fails)}**')
    md.append('')
    md.append(f'- Winner by gate count: **{h2h["winner"].upper()}**')
    md.append(f'- Fold concentration: COMBO={h2h["combo_fold_conc"]:.1f}% vs V5={h2h["v5_fold_conc"]:.1f}%')
    md.append(f'- Max DD: COMBO={h2h["combo_dd"]:.1f}% vs V5={h2h["v5_dd"]:.1f}%')
    md.append(f'- P&L: COMBO=${h2h["combo_pnl"]:.0f} vs V5=${h2h["v5_pnl"]:.0f}')
    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_combo_295.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_combo_295_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Combined Config Test')
    print(f'  COMBO (tp10_sl4_tl8): {c_ge["score"]} gates | '
          f'P&L=${c_m["pnl"]:.0f} | fold_conc={c_fc:.1f}%')
    print(f'  V5 (tp8_sl5_tl10):    {v_ge["score"]} gates | '
          f'P&L=${v_m["pnl"]:.0f} | fold_conc={v_fc:.1f}%')
    print(f'  Winner: {h2h["winner"].upper()}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
