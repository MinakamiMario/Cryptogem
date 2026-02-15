#!/usr/bin/env python3
"""
Part 2 -- Agent C2-A6: Deep Stress Analysis on 295 Coins with tp10_sl4_tl8
===========================================================================
Tests the combined configuration (tp10_sl4_tl8 + excl_all_negative on 295 coins)
under multiple fee stress levels and performs per-fold coin attribution.

Part A: Fee ladder (1.0x through 2.5x) + binary search for exact breakeven
Part B: Per-fold coin attribution (5-fold WF with per-coin P&L per fold)

Compares with v5 baseline params on the same 295-coin universe.

Usage:
    python -m strategies.hf.screening.run_part2_stress_295
    python -m strategies.hf.screening.run_part2_stress_295 --dry-run
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

BASE_T1 = get_harness_fee('mexc_market', 'tier1')
BASE_T2 = get_harness_fee('mexc_market', 'tier2')

# tp10_sl4_tl8 — leading candidate from A6 param grid
TP10_PARAMS = {
    'dev_thresh': 2.0,
    'tp_pct': 10,
    'sl_pct': 4,
    'time_limit': 8,
}

# v5 baseline for comparison
V5_PARAMS = {
    'dev_thresh': 2.0,
    'tp_pct': 8,
    'sl_pct': 5,
    'time_limit': 10,
}

# 21 net-negative coins identified by A3 loss cluster analysis
EXCLUDED_COINS = [
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
]

FEE_MULTIPLIERS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]


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
            print('[ERROR] No cache found')
            sys.exit(1)
        print('[SKIP] No 1H candle cache found.')
        return None
    print('[Load] Loading from per-coin parts...')
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


def apply_exclusion(tier_coins, excluded):
    excl_set = set(excluded)
    return {
        'tier1': [c for c in tier_coins['tier1'] if c not in excl_set],
        'tier2': [c for c in tier_coins['tier2'] if c not in excl_set],
    }


def run_with_fees(data, tier_coins, tier_indicators, market_context,
                  t1_fee, t2_fee, params):
    enriched_params = {**params, '__market__': market_context}
    all_trades = []
    tier_fees = {'tier1': t1_fee, 'tier2': t2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, t1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched_params, indicators=indicators, fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           t1_fee, t2_fee, n_folds=5, params=None):
    enriched_params = {**params, '__market__': market_context}
    tier_fees = {'tier1': t1_fee, 'tier2': t2_fee}
    tier_fold_trades = {}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, t1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched_params, indicators=indicators, n_folds=n_folds,
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
                'max_dd_pct': 0.0, 'expectancy': 0.0, 'fee_drag_pct': 0.0}
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
    # Drawdown
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
    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        fee = t.get('_fee_per_side', 0.00125)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * fee + (size + gross) * fee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag_pct = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
    return {
        'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
        'expectancy': round(expectancy, 4), 'fee_drag_pct': round(fee_drag_pct, 2),
    }


def tier_pnl_breakdown(trades):
    t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
    t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
    t1_pnl = sum(t['pnl'] for t in t1_trades)
    t2_pnl = sum(t['pnl'] for t in t2_trades)
    return {
        'tier1': {'trades': len(t1_trades), 'pnl': round(t1_pnl, 2)},
        'tier2': {'trades': len(t2_trades), 'pnl': round(t2_pnl, 2)},
    }


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def find_breakeven_multiplier(data, tier_coins, tier_indicators, market_context,
                              total_bars, params, lo=1.0, hi=3.0,
                              tol_dollars=0.01, max_iter=20):
    """Binary search for breakeven fee multiplier. Tolerance: $0.01/week."""
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    # Check bounds
    t1_lo, t2_lo = BASE_T1 * lo, BASE_T2 * lo
    trades_lo = run_with_fees(data, tier_coins, tier_indicators, market_context,
                              t1_lo, t2_lo, params)
    m_lo = compute_metrics(trades_lo, total_bars)
    if m_lo['exp_per_week'] <= 0:
        return lo, m_lo['exp_per_week'], 0

    t1_hi, t2_hi = BASE_T1 * hi, BASE_T2 * hi
    trades_hi = run_with_fees(data, tier_coins, tier_indicators, market_context,
                              t1_hi, t2_hi, params)
    m_hi = compute_metrics(trades_hi, total_bars)
    if m_hi['exp_per_week'] > 0:
        return hi, m_hi['exp_per_week'], 0

    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        mid = (lo + hi) / 2.0
        t1_mid, t2_mid = BASE_T1 * mid, BASE_T2 * mid
        trades_mid = run_with_fees(data, tier_coins, tier_indicators, market_context,
                                   t1_mid, t2_mid, params)
        m_mid = compute_metrics(trades_mid, total_bars)
        if abs(m_mid['exp_per_week']) < tol_dollars:
            return mid, m_mid['exp_per_week'], iterations
        if m_mid['exp_per_week'] > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0, 0.0, iterations


def per_fold_coin_attribution(fold_trades):
    """For each fold, compute per-coin P&L attribution."""
    fold_coin_data = {}
    all_coins_seen = set()
    for fold_idx in sorted(fold_trades.keys()):
        trades = fold_trades[fold_idx]
        coin_stats = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
        for t in trades:
            coin = t.get('pair', 'unknown')
            all_coins_seen.add(coin)
            coin_stats[coin]['pnl'] += t['pnl']
            coin_stats[coin]['trades'] += 1
            if t['pnl'] > 0:
                coin_stats[coin]['wins'] += 1
            else:
                coin_stats[coin]['losses'] += 1
        # Sort by P&L descending
        sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
        top5 = sorted_coins[:5]
        bottom5 = sorted_coins[-5:] if len(sorted_coins) >= 5 else sorted_coins
        fold_pnl = sum(t['pnl'] for t in trades)
        fold_coin_data[fold_idx] = {
            'fold_pnl': round(fold_pnl, 2),
            'n_trades': len(trades),
            'n_coins': len(coin_stats),
            'top5': [{'coin': c, 'pnl': round(s['pnl'], 2), 'trades': s['trades'],
                       'wr': round(s['wins'] / s['trades'] * 100, 1) if s['trades'] > 0 else 0}
                     for c, s in top5],
            'bottom5': [{'coin': c, 'pnl': round(s['pnl'], 2), 'trades': s['trades'],
                          'wr': round(s['wins'] / s['trades'] * 100, 1) if s['trades'] > 0 else 0}
                        for c, s in bottom5],
            'all_coins': {c: {'pnl': round(s['pnl'], 2), 'trades': s['trades'],
                              'wins': s['wins'], 'losses': s['losses']}
                          for c, s in sorted_coins},
        }

    # Cross-fold consistency: which coins are profitable in N folds?
    coin_fold_positive = defaultdict(int)
    coin_fold_count = defaultdict(int)
    coin_total_pnl = defaultdict(float)
    n_folds = len(fold_trades)
    for fold_idx, fdata in fold_coin_data.items():
        for coin, stats in fdata['all_coins'].items():
            coin_fold_count[coin] += 1
            coin_total_pnl[coin] += stats['pnl']
            if stats['pnl'] > 0:
                coin_fold_positive[coin] += 1

    consistency = []
    for coin in all_coins_seen:
        n_pos = coin_fold_positive.get(coin, 0)
        n_appear = coin_fold_count.get(coin, 0)
        total = coin_total_pnl.get(coin, 0.0)
        consistency.append({
            'coin': coin,
            'folds_appeared': n_appear,
            'folds_positive': n_pos,
            'total_pnl': round(total, 2),
            'consistency_pct': round(n_pos / n_appear * 100, 1) if n_appear > 0 else 0,
        })
    consistency.sort(key=lambda x: (-x['folds_positive'], -x['total_pnl']))

    # Categories
    always_profitable = [c for c in consistency if c['folds_positive'] == c['folds_appeared'] and c['folds_appeared'] >= 2]
    mostly_profitable = [c for c in consistency if c['folds_positive'] >= n_folds * 0.6 and c not in always_profitable]
    fold_specific = [c for c in consistency if c['folds_positive'] == 1]

    return {
        'per_fold': fold_coin_data,
        'consistency': consistency,
        'always_profitable': always_profitable,
        'mostly_profitable': mostly_profitable,
        'fold_specific': fold_specific,
        'n_folds': n_folds,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C2-A6: Deep Stress on 295 coins with tp10_sl4_tl8')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Part 2 -- Agent C2-A6: Deep Stress Analysis')
    print('  295 coins (excl_all_negative) + tp10_sl4_tl8 params')
    print(sep)
    print(f'Started: {datetime.now().isoformat(timespec="seconds")}')
    t0 = time.time()

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    print(f'[Costs] Base fees: T1={BASE_T1*10000:.1f}bps, T2={BASE_T2*10000:.1f}bps')
    print(f'[Params] tp10_sl4_tl8: {TP10_PARAMS}')
    print(f'[Params] v5 baseline:  {V5_PARAMS}')
    print(f'[Exclusion] {len(EXCLUDED_COINS)} net-negative coins')

    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)
    tier_coins_295 = apply_exclusion(tier_coins_full, EXCLUDED_COINS)

    n_t1 = len(tier_coins_295['tier1'])
    n_t2 = len(tier_coins_295['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] 295-coin: T1={n_t1}, T2={n_t2}, total={n_total}')

    if not tier_coins_295['tier1'] and not tier_coins_295['tier2']:
        print('[ERROR] No coins in T1 or T2 after exclusion.')
        sys.exit(1)

    if args.dry_run:
        print(f'\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  tp10 params: {TP10_PARAMS}')
        print(f'  v5 params:   {V5_PARAMS}')
        print(f'  Fee multipliers: {FEE_MULTIPLIERS}')
        print(f'  + Binary search for breakeven (tol=$0.01/wk, max 20 iters)')
        print(f'  + 5-fold WF with per-coin attribution')
        sys.exit(0)

    # Precompute indicators for the 295-coin universe
    print('[Indicators] Precomputing base indicators...')
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

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins_295)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # =========================================================================
    # PART A: Fee Ladder
    # =========================================================================
    print(f'\n{sep}')
    print('  PART A: Fee Ladder — tp10_sl4_tl8 vs v5 on 295 coins')
    print(sep)

    tp10_ladder = []
    v5_ladder = []

    for mult in FEE_MULTIPLIERS:
        t1_fee = BASE_T1 * mult
        t2_fee = BASE_T2 * mult

        # tp10_sl4_tl8
        t_start = time.time()
        trades_tp10 = run_with_fees(data, tier_coins_295, tier_indicators,
                                    market_context, t1_fee, t2_fee, TP10_PARAMS)
        m_tp10 = compute_metrics(trades_tp10, total_bars)
        tb_tp10 = tier_pnl_breakdown(trades_tp10)
        elapsed_tp10 = time.time() - t_start

        tp10_ladder.append({
            'multiplier': mult,
            't1_bps': round(t1_fee * 10000, 2),
            't2_bps': round(t2_fee * 10000, 2),
            'metrics': m_tp10,
            'tier_breakdown': tb_tp10,
            'runtime_s': round(elapsed_tp10, 1),
        })

        # v5 baseline
        t_start = time.time()
        trades_v5 = run_with_fees(data, tier_coins_295, tier_indicators,
                                  market_context, t1_fee, t2_fee, V5_PARAMS)
        m_v5 = compute_metrics(trades_v5, total_bars)
        tb_v5 = tier_pnl_breakdown(trades_v5)
        elapsed_v5 = time.time() - t_start

        v5_ladder.append({
            'multiplier': mult,
            't1_bps': round(t1_fee * 10000, 2),
            't2_bps': round(t2_fee * 10000, 2),
            'metrics': m_v5,
            'tier_breakdown': tb_v5,
            'runtime_s': round(elapsed_v5, 1),
        })

        g4_tp10 = 'PASS' if m_tp10['exp_per_week'] > 0 else 'FAIL'
        g4_v5 = 'PASS' if m_v5['exp_per_week'] > 0 else 'FAIL'
        print(f'  {mult:.2f}x | tp10: tr={m_tp10["trades"]:3d} PF={m_tp10["pf"]:.3f} '
              f'exp/w=${m_tp10["exp_per_week"]:.2f} DD={m_tp10["max_dd_pct"]:.1f}% G4={g4_tp10} '
              f'| v5: tr={m_v5["trades"]:3d} PF={m_v5["pf"]:.3f} '
              f'exp/w=${m_v5["exp_per_week"]:.2f} DD={m_v5["max_dd_pct"]:.1f}% G4={g4_v5}')

    # Binary search for breakeven — tp10
    print(f'\n{sep}')
    print('  Binary Search: Breakeven Multiplier (tp10_sl4_tl8)')
    print(sep)

    t_bs = time.time()
    be_tp10_mult, be_tp10_exp, be_tp10_iters = find_breakeven_multiplier(
        data, tier_coins_295, tier_indicators, market_context, total_bars,
        TP10_PARAMS, lo=1.0, hi=15.0, tol_dollars=0.01, max_iter=25,
    )
    elapsed_bs_tp10 = time.time() - t_bs
    print(f'  tp10 breakeven: {be_tp10_mult:.4f}x ({be_tp10_iters} iters, {elapsed_bs_tp10:.1f}s)')
    print(f'    At breakeven: T1={BASE_T1*be_tp10_mult*10000:.1f}bps, '
          f'T2={BASE_T2*be_tp10_mult*10000:.1f}bps, exp/w=${be_tp10_exp:.4f}')

    # Binary search for breakeven — v5 (for comparison)
    print(f'\n  Binary Search: Breakeven Multiplier (v5 baseline)')
    t_bs = time.time()
    be_v5_mult, be_v5_exp, be_v5_iters = find_breakeven_multiplier(
        data, tier_coins_295, tier_indicators, market_context, total_bars,
        V5_PARAMS, lo=1.0, hi=20.0, tol_dollars=0.01, max_iter=25,
    )
    elapsed_bs_v5 = time.time() - t_bs
    print(f'  v5 breakeven: {be_v5_mult:.4f}x ({be_v5_iters} iters, {elapsed_bs_v5:.1f}s)')
    print(f'    At breakeven: T1={BASE_T1*be_v5_mult*10000:.1f}bps, '
          f'T2={BASE_T2*be_v5_mult*10000:.1f}bps, exp/w=${be_v5_exp:.4f}')

    # =========================================================================
    # PART B: Per-Fold Coin Attribution (tp10_sl4_tl8)
    # =========================================================================
    print(f'\n{sep}')
    print('  PART B: Per-Fold Coin Attribution (tp10_sl4_tl8, 5-fold WF)')
    print(sep)

    t_wf = time.time()
    fold_trades = run_wf(data, tier_coins_295, tier_indicators, market_context,
                         BASE_T1, BASE_T2, n_folds=5, params=TP10_PARAMS)
    elapsed_wf = time.time() - t_wf
    print(f'  Walk-forward completed in {elapsed_wf:.1f}s')

    # Fold summary
    fold_pnls = {}
    folds_positive = 0
    for fold_idx in sorted(fold_trades.keys()):
        trades = fold_trades[fold_idx]
        fold_pnl = sum(t['pnl'] for t in trades)
        fold_pnls[fold_idx] = fold_pnl
        is_pos = fold_pnl > 0
        if is_pos:
            folds_positive += 1
        n_coins_in_fold = len(set(t.get('pair', '') for t in trades))
        print(f'  Fold {fold_idx}: {len(trades)} trades, {n_coins_in_fold} coins, '
              f'P&L=${fold_pnl:.2f} {"POS" if is_pos else "NEG"}')

    # Fold concentration
    positive_total = sum(max(0, p) for p in fold_pnls.values())
    if positive_total > 0:
        max_fold_pnl = max(fold_pnls.values())
        fold_conc = max(0, max_fold_pnl) / positive_total * 100
    else:
        fold_conc = 100.0
    print(f'  WF: {folds_positive}/5 positive, fold_conc={fold_conc:.1f}%')

    # Per-fold coin attribution
    attribution = per_fold_coin_attribution(fold_trades)

    print(f'\n  --- Cross-fold consistency ---')
    always = attribution['always_profitable']
    mostly = attribution['mostly_profitable']
    fold_spec = attribution['fold_specific']
    print(f'  Always profitable (all folds appeared): {len(always)} coins')
    for c in always[:10]:
        print(f'    {c["coin"]:15s} folds={c["folds_appeared"]} pos={c["folds_positive"]} '
              f'P&L=${c["total_pnl"]:+.2f}')
    print(f'  Mostly profitable (>=60% folds): {len(mostly)} coins')
    for c in mostly[:10]:
        print(f'    {c["coin"]:15s} folds={c["folds_appeared"]} pos={c["folds_positive"]} '
              f'P&L=${c["total_pnl"]:+.2f}')
    print(f'  Fold-specific (1 fold only): {len(fold_spec)} coins')

    print(f'\n  --- Top-5 coins per fold ---')
    for fold_idx in sorted(attribution['per_fold'].keys()):
        fdata = attribution['per_fold'][fold_idx]
        print(f'  Fold {fold_idx} (P&L=${fdata["fold_pnl"]:.2f}, {fdata["n_trades"]} trades):')
        for c in fdata['top5']:
            print(f'    {c["coin"]:15s} P&L=${c["pnl"]:+.2f} trades={c["trades"]} WR={c["wr"]:.0f}%')

    # Also run v5 WF for fold comparison
    print(f'\n  --- v5 baseline WF for comparison ---')
    t_wf_v5 = time.time()
    fold_trades_v5 = run_wf(data, tier_coins_295, tier_indicators, market_context,
                            BASE_T1, BASE_T2, n_folds=5, params=V5_PARAMS)
    elapsed_wf_v5 = time.time() - t_wf_v5
    v5_fold_pnls = {}
    v5_folds_positive = 0
    for fold_idx in sorted(fold_trades_v5.keys()):
        trades = fold_trades_v5[fold_idx]
        fold_pnl = sum(t['pnl'] for t in trades)
        v5_fold_pnls[fold_idx] = fold_pnl
        if fold_pnl > 0:
            v5_folds_positive += 1
        print(f'  v5 Fold {fold_idx}: {len(trades)} trades, P&L=${fold_pnl:.2f}')
    v5_pos_total = sum(max(0, p) for p in v5_fold_pnls.values())
    v5_fold_conc = (max(0, max(v5_fold_pnls.values())) / v5_pos_total * 100
                    if v5_pos_total > 0 else 100.0)
    print(f'  v5 WF: {v5_folds_positive}/5 positive, fold_conc={v5_fold_conc:.1f}%')

    elapsed_total = time.time() - t0

    # =========================================================================
    # Build JSON Report
    # =========================================================================
    dt_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Serialize fold attribution (convert defaultdicts to dicts)
    fold_attr_serializable = {}
    for fold_idx, fdata in attribution['per_fold'].items():
        fold_attr_serializable[str(fold_idx)] = {
            'fold_pnl': fdata['fold_pnl'],
            'n_trades': fdata['n_trades'],
            'n_coins': fdata['n_coins'],
            'top5': fdata['top5'],
            'bottom5': fdata['bottom5'],
        }

    report = {
        'run_header': {
            'task': 'part2_stress_295_deep',
            'agent': 'C2-A6',
            'date': dt_str,
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params_tp10': TP10_PARAMS,
            'params_v5': V5_PARAMS,
            'cost_model': 'costs_mexc_v2',
            'base_fees': {'tier1_bps': round(BASE_T1*10000, 1),
                         'tier2_bps': round(BASE_T2*10000, 1)},
            'universe': {'tier1_coins': n_t1, 'tier2_coins': n_t2,
                        'total_coins': n_total},
            'excluded_coins': EXCLUDED_COINS,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'fee_ladder': {
            'multipliers': FEE_MULTIPLIERS,
            'tp10_results': tp10_ladder,
            'v5_results': v5_ladder,
        },
        'breakeven': {
            'tp10': {
                'multiplier': round(be_tp10_mult, 4),
                't1_bps': round(BASE_T1 * be_tp10_mult * 10000, 2),
                't2_bps': round(BASE_T2 * be_tp10_mult * 10000, 2),
                'exp_per_week_at_be': round(be_tp10_exp, 4),
                'iterations': be_tp10_iters,
            },
            'v5': {
                'multiplier': round(be_v5_mult, 4),
                't1_bps': round(BASE_T1 * be_v5_mult * 10000, 2),
                't2_bps': round(BASE_T2 * be_v5_mult * 10000, 2),
                'exp_per_week_at_be': round(be_v5_exp, 4),
                'iterations': be_v5_iters,
            },
        },
        'walk_forward_tp10': {
            'folds_positive': folds_positive,
            'fold_pnls': {str(k): round(v, 2) for k, v in fold_pnls.items()},
            'fold_concentration_pct': round(fold_conc, 1),
        },
        'walk_forward_v5': {
            'folds_positive': v5_folds_positive,
            'fold_pnls': {str(k): round(v, 2) for k, v in v5_fold_pnls.items()},
            'fold_concentration_pct': round(v5_fold_conc, 1),
        },
        'per_fold_attribution': fold_attr_serializable,
        'cross_fold_consistency': {
            'always_profitable': attribution['always_profitable'],
            'mostly_profitable': attribution['mostly_profitable'],
            'fold_specific_count': len(attribution['fold_specific']),
            'full_consistency': attribution['consistency'],
        },
        'summary': {
            'tp10_breakeven_mult': round(be_tp10_mult, 4),
            'v5_breakeven_mult': round(be_v5_mult, 4),
            'tp10_survives_2x': be_tp10_mult >= 2.0,
            'v5_survives_2x': be_v5_mult >= 2.0,
            'tp10_wf_folds': f'{folds_positive}/5',
            'v5_wf_folds': f'{v5_folds_positive}/5',
            'tp10_fold_conc': round(fold_conc, 1),
            'v5_fold_conc': round(v5_fold_conc, 1),
            'always_profitable_coins': len(attribution['always_profitable']),
            'recommendation': '',  # filled below
        },
    }

    # Build recommendation
    rec_parts = []
    rec_parts.append(f'tp10_sl4_tl8 breakeven at {be_tp10_mult:.2f}x '
                     f'(v5 at {be_v5_mult:.2f}x on same 295 coins).')
    if be_tp10_mult >= 2.0:
        rec_parts.append('tp10 SURVIVES 2x uniform stress.')
    else:
        rec_parts.append(f'tp10 FAILS 2x stress (short by {2.0-be_tp10_mult:.2f}x).')
    rec_parts.append(f'WF: tp10 {folds_positive}/5 fold_conc={fold_conc:.1f}%, '
                     f'v5 {v5_folds_positive}/5 fold_conc={v5_fold_conc:.1f}%.')
    rec_parts.append(f'{len(always)} coins consistently profitable across all folds.')
    report['summary']['recommendation'] = ' '.join(rec_parts)

    json_path = ROOT / 'reports' / 'hf' / 'part2_stress_295_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # =========================================================================
    # Build Markdown Report
    # =========================================================================
    md = []
    md.append('# Part 2 -- Deep Stress Analysis: 295 Coins + tp10_sl4_tl8 (C2-A6)')
    md.append('')
    md.append(f'**Date**: {dt_str}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins '
              f'(excl {len(EXCLUDED_COINS)} net-negative)')
    md.append(f'**tp10 Params**: dev={TP10_PARAMS["dev_thresh"]}, tp={TP10_PARAMS["tp_pct"]}, '
              f'sl={TP10_PARAMS["sl_pct"]}, tl={TP10_PARAMS["time_limit"]}')
    md.append(f'**v5 Params**: dev={V5_PARAMS["dev_thresh"]}, tp={V5_PARAMS["tp_pct"]}, '
              f'sl={V5_PARAMS["sl_pct"]}, tl={V5_PARAMS["time_limit"]}')
    md.append(f'**Base Fees**: T1={BASE_T1*10000:.1f}bps, T2={BASE_T2*10000:.1f}bps')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Part A: Fee Ladder
    md.append('## Part A: Fee Ladder')
    md.append('')
    md.append('### tp10_sl4_tl8')
    md.append('')
    md.append('| Mult | T1 bps | T2 bps | Trades | PF | WR% | Exp/Wk | DD% | Fee Drag | T1 P&L | T2 P&L | G4 |')
    md.append('|------|--------|--------|--------|----|-----|--------|-----|----------|--------|--------|----|')
    for lr in tp10_ladder:
        m = lr['metrics']
        tb = lr['tier_breakdown']
        g4 = 'PASS' if m['exp_per_week'] > 0 else 'FAIL'
        md.append(f'| {lr["multiplier"]:.2f}x | {lr["t1_bps"]:.1f} | {lr["t2_bps"]:.1f} '
                  f'| {m["trades"]} | {m["pf"]:.3f} | {m["wr"]:.1f} | ${m["exp_per_week"]:.2f} '
                  f'| {m["max_dd_pct"]:.1f} | {m["fee_drag_pct"]:.1f}% '
                  f'| ${tb["tier1"]["pnl"]:.0f} | ${tb["tier2"]["pnl"]:.0f} | **{g4}** |')
    md.append('')

    md.append('### v5 baseline (same 295 coins)')
    md.append('')
    md.append('| Mult | Trades | PF | WR% | Exp/Wk | DD% | T1 P&L | T2 P&L | G4 |')
    md.append('|------|--------|----|-----|--------|-----|--------|--------|----|')
    for lr in v5_ladder:
        m = lr['metrics']
        tb = lr['tier_breakdown']
        g4 = 'PASS' if m['exp_per_week'] > 0 else 'FAIL'
        md.append(f'| {lr["multiplier"]:.2f}x | {m["trades"]} | {m["pf"]:.3f} | {m["wr"]:.1f} '
                  f'| ${m["exp_per_week"]:.2f} | {m["max_dd_pct"]:.1f} '
                  f'| ${tb["tier1"]["pnl"]:.0f} | ${tb["tier2"]["pnl"]:.0f} | **{g4}** |')
    md.append('')

    # Breakeven
    md.append('## Breakeven Analysis')
    md.append('')
    md.append(f'| Config | Breakeven Mult | T1 bps | T2 bps | Survives 2x? |')
    md.append(f'|--------|---------------|--------|--------|--------------|')
    be_tp10_ok = 'YES' if be_tp10_mult >= 2.0 else 'NO'
    be_v5_ok = 'YES' if be_v5_mult >= 2.0 else 'NO'
    md.append(f'| tp10_sl4_tl8 | **{be_tp10_mult:.3f}x** | {BASE_T1*be_tp10_mult*10000:.1f} '
              f'| {BASE_T2*be_tp10_mult*10000:.1f} | **{be_tp10_ok}** |')
    md.append(f'| v5 baseline | **{be_v5_mult:.3f}x** | {BASE_T1*be_v5_mult*10000:.1f} '
              f'| {BASE_T2*be_v5_mult*10000:.1f} | **{be_v5_ok}** |')
    md.append(f'| A5 ref (316 coins) | 1.71x | — | — | NO |')
    md.append('')

    # Part B: Walk-Forward
    md.append('## Part B: Walk-Forward Comparison')
    md.append('')
    md.append('| Fold | tp10 Trades | tp10 P&L | v5 Trades | v5 P&L |')
    md.append('|------|------------|----------|----------|--------|')
    for fold_idx in range(5):
        tp10_ft = fold_trades.get(fold_idx, [])
        v5_ft = fold_trades_v5.get(fold_idx, [])
        tp10_pnl = fold_pnls.get(fold_idx, 0)
        v5_pnl = v5_fold_pnls.get(fold_idx, 0)
        md.append(f'| {fold_idx} | {len(tp10_ft)} | ${tp10_pnl:.2f} '
                  f'| {len(v5_ft)} | ${v5_pnl:.2f} |')
    md.append(f'| **Total** | — | **{folds_positive}/5 pos** '
              f'| — | **{v5_folds_positive}/5 pos** |')
    md.append(f'| **Fold Conc** | — | **{fold_conc:.1f}%** '
              f'| — | **{v5_fold_conc:.1f}%** |')
    md.append('')

    # Per-fold top coins
    md.append('## Per-Fold Top-5 Coins (tp10_sl4_tl8)')
    md.append('')
    for fold_idx in sorted(attribution['per_fold'].keys()):
        fdata = attribution['per_fold'][fold_idx]
        md.append(f'### Fold {fold_idx} (P&L=${fdata["fold_pnl"]:.2f}, '
                  f'{fdata["n_trades"]} trades, {fdata["n_coins"]} coins)')
        md.append('')
        md.append('| Coin | P&L | Trades | WR% |')
        md.append('|------|-----|--------|-----|')
        for c in fdata['top5']:
            md.append(f'| {c["coin"]} | ${c["pnl"]:+.2f} | {c["trades"]} | {c["wr"]:.0f}% |')
        md.append('')

    # Cross-fold consistency
    md.append('## Cross-Fold Consistency')
    md.append('')
    md.append(f'- **Always profitable** (all folds appeared): {len(always)} coins')
    md.append(f'- **Mostly profitable** (>=60% folds): {len(mostly)} coins')
    md.append(f'- **Fold-specific** (1 fold only): {len(fold_spec)} coins')
    md.append('')
    if always:
        md.append('### Always-Profitable Coins')
        md.append('')
        md.append('| Coin | Folds | Pos Folds | Total P&L |')
        md.append('|------|-------|-----------|-----------|')
        for c in always:
            md.append(f'| {c["coin"]} | {c["folds_appeared"]} | {c["folds_positive"]} '
                      f'| ${c["total_pnl"]:+.2f} |')
        md.append('')

    # Key Findings
    md.append('## Key Findings')
    md.append('')
    md.append(f'1. **tp10 breakeven**: {be_tp10_mult:.3f}x '
              f'(v5: {be_v5_mult:.3f}x on same 295 coins, A5: 1.71x on 316 coins)')
    if be_tp10_mult < be_v5_mult:
        md.append(f'2. **v5 more stress-resilient**: v5 survives {be_v5_mult-be_tp10_mult:.2f}x more fee stress')
    else:
        md.append(f'2. **tp10 more stress-resilient**: tp10 survives {be_tp10_mult-be_v5_mult:.2f}x more fee stress')
    md.append(f'3. **Fold concentration**: tp10={fold_conc:.1f}% vs v5={v5_fold_conc:.1f}%')
    if fold_conc < v5_fold_conc:
        md.append(f'   - tp10 has better fold distribution (lower is better)')
    else:
        md.append(f'   - v5 has better fold distribution (lower is better)')
    md.append(f'4. **Walk-forward**: tp10={folds_positive}/5 vs v5={v5_folds_positive}/5')
    md.append(f'5. **Consistent coins**: {len(always)} always-profitable across all folds')
    md.append(f'6. **Fold-specific coins**: {len(fold_spec)} appear in only 1 fold (noise risk)')
    md.append('')

    md.append('## Recommendation')
    md.append('')
    md.append(report['summary']['recommendation'])
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_stress_295.py at {dt_str}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_stress_295_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{sep}')
    print(f'  COMPLETE: Deep Stress Analysis on 295 coins')
    print(f'  tp10 breakeven: {be_tp10_mult:.3f}x | v5 breakeven: {be_v5_mult:.3f}x')
    print(f'  tp10 WF: {folds_positive}/5 fold_conc={fold_conc:.1f}%')
    print(f'  v5 WF:   {v5_folds_positive}/5 fold_conc={v5_fold_conc:.1f}%')
    print(f'  Always-profitable coins: {len(always)}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
