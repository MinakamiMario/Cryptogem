#!/usr/bin/env python3
"""
Part 2 -- Agent P0-A: Data / Selection Audit
=============================================
Comprehensive audit of the 316-coin universe, the EXCLUDED_21 exclusion,
and potential biases in the data assembly process.

Sections:
  1. Data Provenance: coin count, bar count, date range
  2. Survivorship Scan: zero-vol tails, short bar counts
  3. EXCLUDED_21 Circularity Proof: re-derive from full-sample backtest
  4. Random-21 Placebo Test (100x): compare EXCLUDED_21 vs random exclusion
  5. Cross-Validation Exclusion (5-fold, embargo=10): train/test lift
  6. Universe-as-of Analysis: point-in-time drift
  7. Leakage Scorecard: summary

Output:
  reports/hf/part2_data_assembly_audit.json
  reports/hf/part2_data_assembly_audit.md

Usage:
    python strategies/hf/screening/run_part2_data_assembly_audit.py
    python strategies/hf/screening/run_part2_data_assembly_audit.py --dry-run
"""
import sys
import json
import time
import random
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
from strategies.hf.screening.universe_as_of import (
    get_universe_at_bar, compare_with_static_universe,
    get_universe_timeline, survivorship_scan,
)


BARS_PER_WEEK = 168
BARS_PER_DAY = 24
WARMUP_BARS = 50

BASELINE_PARAMS = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

N_PLACEBO = 100
N_CV_FOLDS = 5
CV_EMBARGO = 10


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
    if len(sorted_trades) >= 2:
        mg = sorted_trades[0].get('entry_bar', WARMUP_BARS) - WARMUP_BARS
        for i in range(1, len(sorted_trades)):
            g = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i - 1].get('exit_bar', 0)
            if g > mg:
                mg = g
        eg = total_bars - sorted_trades[-1].get('exit_bar', 0)
        if eg > mg:
            mg = eg
        max_gap_bars = mg
    elif len(sorted_trades) == 1:
        max_gap_bars = total_bars
    else:
        max_gap_bars = total_bars
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {
        'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
        'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4),
    }


def coin_pnl_from_trades(trades):
    coin_pnl = defaultdict(float)
    for t in trades:
        coin_pnl[t.get('pair', 'unknown')] += t['pnl']
    return dict(coin_pnl)


def identify_negative_coins(trades):
    coin_pnl = coin_pnl_from_trades(trades)
    return set(c for c, pnl in coin_pnl.items() if pnl < 0)


def evaluate_gates(metrics):
    gates = {}
    gates['G1'] = {'pass': metrics['trades_per_week'] >= 10}
    gates['G2'] = {'pass': metrics['max_gap_days'] <= 2.5}
    gates['G3'] = {'pass': metrics['exp_per_week'] > 0}
    gates['G5'] = {'pass': metrics['max_dd_pct'] <= 20}
    n_pass = sum(1 for g in gates.values() if g['pass'])
    return gates, n_pass, len(gates)


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None,
                start_bar=50, end_bar=None):
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
            start_bar=start_bar, end_bar=end_bar,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def section_data_provenance(data, tier_coins):
    print('\n' + '=' * 70)
    print('  SECTION 1: Data Provenance')
    print('=' * 70)
    total_coins = sum(1 for k in data if not k.startswith('_'))
    bar_counts = []
    first_timestamps = []
    last_timestamps = []
    for coin, candles in data.items():
        if coin.startswith('_'):
            continue
        bar_counts.append(len(candles))
        if candles:
            ts0 = candles[0].get('timestamp', candles[0].get('t', None))
            ts1 = candles[-1].get('timestamp', candles[-1].get('t', None))
            if ts0:
                first_timestamps.append(ts0)
            if ts1:
                last_timestamps.append(ts1)
    n_t1 = len(tier_coins.get('tier1', []))
    n_t2 = len(tier_coins.get('tier2', []))
    min_bars = min(bar_counts) if bar_counts else 0
    max_bars = max(bar_counts) if bar_counts else 0
    avg_bars = sum(bar_counts) / len(bar_counts) if bar_counts else 0
    median_bars = sorted(bar_counts)[len(bar_counts) // 2] if bar_counts else 0
    earliest = min(first_timestamps) if first_timestamps else None
    latest = max(last_timestamps) if last_timestamps else None
    result = {
        'total_coins_in_cache': total_coins,
        'tier1_coins': n_t1, 'tier2_coins': n_t2,
        'tiered_total': n_t1 + n_t2,
        'bar_count_stats': {'min': min_bars, 'max': max_bars, 'avg': round(avg_bars, 1), 'median': median_bars},
        'date_range': {'earliest_timestamp': earliest, 'latest_timestamp': latest},
        'excluded_21_count': len(EXCLUDED_21),
        'post_exclusion_count': n_t1 + n_t2 - len(
            set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])) & EXCLUDED_21),
    }
    print(f'  Coins in cache: {total_coins}')
    print(f'  Tiered universe: T1={n_t1} + T2={n_t2} = {n_t1+n_t2}')
    print(f'  Bar counts: min={min_bars}, max={max_bars}, avg={avg_bars:.0f}, median={median_bars}')
    print(f'  Earliest timestamp: {earliest}')
    print(f'  Latest timestamp: {latest}')
    return result


def section_survivorship(data):
    print('\n' + '=' * 70)
    print('  SECTION 2: Survivorship Scan')
    print('=' * 70)
    scan = survivorship_scan(data, min_bars=200, max_zero_vol_tail=48)
    print(f'  Short-lived (<200 bars): {scan["n_short"]} coins')
    print(f'  Zero-vol tail (>=48 bars): {scan["n_zero_vol"]} coins')
    print(f'  Healthy: {scan["n_healthy"]} coins')
    if scan['short_lived']:
        print(f'  Top short-lived:')
        for item in scan['short_lived'][:10]:
            print(f'    {item["coin"]}: {item["bars"]} bars')
    if scan['zero_vol_tail']:
        print(f'  Top zero-vol tail:')
        for item in scan['zero_vol_tail'][:10]:
            print(f'    {item["coin"]}: {item["zero_vol_tail"]} trailing zero-vol bars (of {item["bars"]})')
    return scan


def section_circularity_proof(data, tier_coins_full, tier_indicators_full,
                               market_context, tier1_fee, tier2_fee, total_bars):
    print('\n' + '=' * 70)
    print('  SECTION 3: EXCLUDED_21 Circularity Proof')
    print('=' * 70)
    print('  Running full 316-coin backtest...')
    trades_316 = run_variant(data, tier_coins_full, tier_indicators_full,
                              market_context, tier1_fee, tier2_fee)
    metrics_316 = compute_metrics(trades_316, total_bars)
    print(f'    316-coin: {metrics_316["trades"]} trades, PF={metrics_316["pf"]:.3f}, P&L=${metrics_316["pnl"]:.0f}')
    coin_pnl = coin_pnl_from_trades(trades_316)
    coins_with_trades = set(coin_pnl.keys())
    neg_coins = set(c for c, pnl in coin_pnl.items() if pnl < 0)
    overlap = neg_coins & EXCLUDED_21
    only_in_derived = neg_coins - EXCLUDED_21
    only_in_hardcoded = EXCLUDED_21 - neg_coins
    jaccard = len(overlap) / len(neg_coins | EXCLUDED_21) if (neg_coins | EXCLUDED_21) else 0
    excl_with_trades = EXCLUDED_21 & coins_with_trades
    excl_no_trades = EXCLUDED_21 - coins_with_trades
    excl_pnl = sum(coin_pnl.get(c, 0) for c in EXCLUDED_21)
    is_circular = len(overlap) == len(EXCLUDED_21 & coins_with_trades)
    print(f'  Coins with trades: {len(coins_with_trades)}')
    print(f'  Net-negative coins (derived): {len(neg_coins)}')
    print(f'  Overlap: {len(overlap)} ({jaccard:.1%} Jaccard)')
    print(f'  Only in derived: {sorted(only_in_derived)}')
    print(f'  Only in EXCLUDED_21: {sorted(only_in_hardcoded)}')
    print(f'  EXCLUDED_21 total PnL: ${excl_pnl:.2f}')
    print(f'  Circular? {"YES" if is_circular else "NO"}')
    result = {
        'metrics_316': metrics_316,
        'coins_with_trades': len(coins_with_trades),
        'net_negative_derived': sorted(neg_coins),
        'n_negative_derived': len(neg_coins),
        'excluded_21_hardcoded': sorted(EXCLUDED_21),
        'overlap': sorted(overlap), 'n_overlap': len(overlap),
        'jaccard': round(jaccard, 4),
        'only_in_derived': sorted(only_in_derived),
        'only_in_hardcoded': sorted(only_in_hardcoded),
        'excl_with_trades': sorted(excl_with_trades),
        'excl_no_trades': sorted(excl_no_trades),
        'excl_total_pnl': round(excl_pnl, 2),
        'is_circular': is_circular,
        'coin_pnl_excluded': {c: round(coin_pnl.get(c, 0), 2) for c in sorted(EXCLUDED_21)},
    }
    return result, trades_316, coin_pnl


def section_placebo_test(data, tier_coins_full, tier_indicators_full,
                          market_context, tier1_fee, tier2_fee, total_bars,
                          coins_with_trades, trades_316, metrics_316):
    print('\n' + '=' * 70)
    print(f'  SECTION 4: Random-21 Placebo Test ({N_PLACEBO}x)')
    print('=' * 70)
    trade_coins = sorted(coins_with_trades)
    print(f'  Pool of coins with trades: {len(trade_coins)}')
    excl_tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    trades_excl = run_variant(data, excl_tier_coins, tier_indicators_full,
                               market_context, tier1_fee, tier2_fee)
    metrics_excl = compute_metrics(trades_excl, total_bars)
    excl_pnl = metrics_excl['pnl']
    excl_pf = metrics_excl['pf']
    print(f'  EXCLUDED_21 result: PnL=${excl_pnl:.0f}, PF={excl_pf:.3f}')
    random.seed(42)
    placebo_pnls = []
    placebo_pfs = []
    for i in range(N_PLACEBO):
        rand_excl = set(random.sample(trade_coins, min(21, len(trade_coins))))
        rand_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in rand_excl],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in rand_excl],
        }
        rand_trades = run_variant(data, rand_tier_coins, tier_indicators_full,
                                   market_context, tier1_fee, tier2_fee)
        rand_metrics = compute_metrics(rand_trades, total_bars)
        placebo_pnls.append(rand_metrics['pnl'])
        placebo_pfs.append(rand_metrics['pf'])
        if (i + 1) % 25 == 0:
            print(f'    Placebo {i+1}/{N_PLACEBO}: median PnL=${sorted(placebo_pnls)[len(placebo_pnls)//2]:.0f}')
    placebo_pnls_sorted = sorted(placebo_pnls)
    median_pnl = placebo_pnls_sorted[len(placebo_pnls_sorted) // 2]
    mean_pnl = sum(placebo_pnls) / len(placebo_pnls)
    p5_pnl = placebo_pnls_sorted[int(0.05 * len(placebo_pnls_sorted))]
    p95_pnl = placebo_pnls_sorted[int(0.95 * len(placebo_pnls_sorted))]
    n_better = sum(1 for p in placebo_pnls if p >= excl_pnl)
    pct_better = n_better / len(placebo_pnls) * 100
    baseline_pnl = metrics_316['pnl']
    excl_lift = excl_pnl - baseline_pnl
    median_lift = median_pnl - baseline_pnl
    print(f'\n  Results:')
    print(f'    EXCLUDED_21 PnL: ${excl_pnl:.0f} (lift: ${excl_lift:+.0f} vs baseline)')
    print(f'    Placebo median: ${median_pnl:.0f} (lift: ${median_lift:+.0f})')
    print(f'    Placebo P5-P95: ${p5_pnl:.0f} to ${p95_pnl:.0f}')
    print(f'    Placebo runs >= EXCLUDED_21: {n_better}/{N_PLACEBO} ({pct_better:.1f}%)')
    result = {
        'pool_size': len(trade_coins), 'n_excluded': 21, 'n_placebo_runs': N_PLACEBO,
        'excluded_21_result': {
            'pnl': excl_pnl, 'pf': excl_pf,
            'trades': metrics_excl['trades'],
            'lift_vs_baseline': round(excl_lift, 2),
        },
        'placebo_stats': {
            'mean_pnl': round(mean_pnl, 2), 'median_pnl': round(median_pnl, 2),
            'p5_pnl': round(p5_pnl, 2), 'p95_pnl': round(p95_pnl, 2),
            'min_pnl': round(min(placebo_pnls), 2), 'max_pnl': round(max(placebo_pnls), 2),
            'std_pnl': round((sum((p - mean_pnl)**2 for p in placebo_pnls) / len(placebo_pnls))**0.5, 2),
            'median_lift': round(median_lift, 2),
        },
        'n_placebo_beat_excluded': n_better,
        'pct_placebo_beat_excluded': round(pct_better, 1),
        'percentile_of_excluded': round(100 - pct_better, 1),
        'baseline_pnl': round(baseline_pnl, 2),
    }
    return result


def section_cv_exclusion(data, tier_coins_full, tier_indicators_full,
                          market_context, tier1_fee, tier2_fee, total_bars):
    print('\n' + '=' * 70)
    print(f'  SECTION 5: Cross-Validation Exclusion ({N_CV_FOLDS}-fold, embargo={CV_EMBARGO})')
    print('=' * 70)
    usable_bars = total_bars - WARMUP_BARS
    fold_size = usable_bars // N_CV_FOLDS
    folds = []
    for i in range(N_CV_FOLDS):
        fold_start = WARMUP_BARS + i * fold_size
        fold_end = fold_start + fold_size if i < N_CV_FOLDS - 1 else total_bars
        folds.append((fold_start, fold_end))
    print(f'  Total bars: {total_bars}, usable: {usable_bars}, fold_size: {fold_size}')
    for i, (s, e) in enumerate(folds):
        print(f'    Fold {i}: bars {s}-{e} ({e-s} bars)')
    cv_results = []
    all_excluded_sets = []
    for test_fold_idx in range(N_CV_FOLDS):
        test_start, test_end = folds[test_fold_idx]
        print(f'\n  --- Test fold {test_fold_idx} (bars {test_start}-{test_end}) ---')
        train_trades = []
        for fold_idx in range(N_CV_FOLDS):
            if fold_idx == test_fold_idx:
                continue
            fs, fe = folds[fold_idx]
            if fold_idx == test_fold_idx - 1:
                fe = max(fs, fe - CV_EMBARGO)
            elif fold_idx == test_fold_idx + 1:
                fs = min(fe, fs + CV_EMBARGO)
            if fe <= fs:
                continue
            fold_trades = run_variant(
                data, tier_coins_full, tier_indicators_full,
                market_context, tier1_fee, tier2_fee,
                start_bar=fs, end_bar=fe,
            )
            train_trades.extend(fold_trades)
        train_neg = identify_negative_coins(train_trades)
        all_excluded_sets.append(train_neg)
        print(f'    Train: {len(train_trades)} trades, {len(train_neg)} net-negative coins')
        excl_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in train_neg],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in train_neg],
        }
        test_excl_trades = run_variant(
            data, excl_tier_coins, tier_indicators_full,
            market_context, tier1_fee, tier2_fee,
            start_bar=test_start, end_bar=test_end,
        )
        test_excl_pnl = sum(t['pnl'] for t in test_excl_trades)
        test_no_excl_trades = run_variant(
            data, tier_coins_full, tier_indicators_full,
            market_context, tier1_fee, tier2_fee,
            start_bar=test_start, end_bar=test_end,
        )
        test_no_excl_pnl = sum(t['pnl'] for t in test_no_excl_trades)
        lift = test_excl_pnl - test_no_excl_pnl
        print(f'    Test WITH exclusion: {len(test_excl_trades)} trades, PnL=${test_excl_pnl:.2f}')
        print(f'    Test NO exclusion:   {len(test_no_excl_trades)} trades, PnL=${test_no_excl_pnl:.2f}')
        print(f'    Lift: ${lift:+.2f}')
        cv_results.append({
            'fold': test_fold_idx,
            'test_bars': [test_start, test_end],
            'train_trades': len(train_trades),
            'n_excluded': len(train_neg),
            'excluded_coins': sorted(train_neg),
            'test_with_excl': {'trades': len(test_excl_trades), 'pnl': round(test_excl_pnl, 2)},
            'test_no_excl': {'trades': len(test_no_excl_trades), 'pnl': round(test_no_excl_pnl, 2)},
            'lift': round(lift, 2),
        })
    total_lift = sum(r['lift'] for r in cv_results)
    avg_lift = total_lift / len(cv_results)
    folds_positive_lift = sum(1 for r in cv_results if r['lift'] > 0)
    jaccard_pairs = []
    for i in range(len(all_excluded_sets)):
        for j in range(i + 1, len(all_excluded_sets)):
            si, sj = all_excluded_sets[i], all_excluded_sets[j]
            union = si | sj
            inter = si & sj
            jac = len(inter) / len(union) if union else 0
            jaccard_pairs.append(jac)
    avg_jaccard = sum(jaccard_pairs) / len(jaccard_pairs) if jaccard_pairs else 0
    min_jaccard = min(jaccard_pairs) if jaccard_pairs else 0
    max_jaccard = max(jaccard_pairs) if jaccard_pairs else 0
    coin_freq = defaultdict(int)
    for excl_set in all_excluded_sets:
        for c in excl_set:
            coin_freq[c] += 1
    stable_coins = sorted(c for c, cnt in coin_freq.items() if cnt == N_CV_FOLDS)
    print(f'\n  CV Summary:')
    print(f'    Total lift: ${total_lift:+.2f}')
    print(f'    Avg lift per fold: ${avg_lift:+.2f}')
    print(f'    Folds with positive lift: {folds_positive_lift}/{N_CV_FOLDS}')
    print(f'    Jaccard stability: avg={avg_jaccard:.3f}, min={min_jaccard:.3f}, max={max_jaccard:.3f}')
    print(f'    Coins excluded in all {N_CV_FOLDS} folds: {len(stable_coins)} -> {stable_coins}')
    return {
        'n_folds': N_CV_FOLDS, 'embargo_bars': CV_EMBARGO,
        'fold_results': cv_results,
        'summary': {
            'total_lift': round(total_lift, 2), 'avg_lift': round(avg_lift, 2),
            'folds_positive_lift': folds_positive_lift,
            'jaccard_stability': {'avg': round(avg_jaccard, 4), 'min': round(min_jaccard, 4), 'max': round(max_jaccard, 4)},
            'stable_coins_all_folds': stable_coins, 'n_stable': len(stable_coins),
            'coin_frequency': {c: cnt for c, cnt in sorted(coin_freq.items(), key=lambda x: -x[1])},
        },
    }


def section_universe_as_of(data, tier_coins_full, total_bars):
    print('\n' + '=' * 70)
    print('  SECTION 6: Universe-as-of Analysis')
    print('=' * 70)
    timeline = get_universe_timeline(data, step=BARS_PER_WEEK, warmup=WARMUP_BARS)
    print(f'  Timeline snapshots: {len(timeline)}')
    if timeline:
        print(f'    First: bar={timeline[0]["bar"]}, available={timeline[0]["n_available"]}')
        print(f'    Last:  bar={timeline[-1]["bar"]}, available={timeline[-1]["n_available"]}')
        min_avail = min(s['n_available'] for s in timeline)
        max_avail = max(s['n_available'] for s in timeline)
        print(f'    Range: {min_avail} - {max_avail} available coins')
    static_coins = set(tier_coins_full['tier1'] + tier_coins_full['tier2']) - EXCLUDED_21
    comparisons = []
    check_bars = [WARMUP_BARS, total_bars // 4, total_bars // 2, 3 * total_bars // 4, total_bars - 1]
    for bar in check_bars:
        if bar < WARMUP_BARS or bar >= total_bars:
            continue
        comp = compare_with_static_universe(data, static_coins, bar)
        comparisons.append(comp)
        print(f'    Bar {bar}: Jaccard={comp["jaccard"]:.4f}, available={comp["n_available"]}, '
              f'static={comp["n_static"]}, intersection={comp["n_intersection"]}')
    return {
        'timeline': timeline, 'n_snapshots': len(timeline),
        'min_available': min(s['n_available'] for s in timeline) if timeline else 0,
        'max_available': max(s['n_available'] for s in timeline) if timeline else 0,
        'static_comparisons': comparisons,
        'static_universe_size': len(static_coins),
    }


def build_leakage_scorecard(provenance, survivorship, circularity, placebo, cv, universe):
    items = []
    items.append({'check': 'Data completeness',
        'result': f'{provenance["total_coins_in_cache"]} coins, {provenance["bar_count_stats"]["max"]} max bars',
        'risk': 'LOW', 'detail': 'Full universe loaded'})
    n_short = survivorship['n_short']
    n_zvol = survivorship['n_zero_vol']
    risk = 'LOW' if (n_short + n_zvol) < 10 else ('MEDIUM' if (n_short + n_zvol) < 30 else 'HIGH')
    items.append({'check': 'Survivorship bias',
        'result': f'{n_short} short-lived, {n_zvol} zero-vol tail', 'risk': risk,
        'detail': 'Coins with <200 bars or >=48 trailing zero-vol bars'})
    items.append({'check': 'EXCLUDED_21 circularity',
        'result': f'{"100% in-sample" if circularity["is_circular"] else "PARTIAL"} (Jaccard={circularity["jaccard"]:.2f})',
        'risk': 'HIGH', 'detail': f'{circularity["n_overlap"]}/{len(EXCLUDED_21)} overlap'})
    pct_better = placebo['pct_placebo_beat_excluded']
    placebo_risk = 'HIGH' if pct_better > 40 else ('MEDIUM' if pct_better > 15 else 'LOW')
    items.append({'check': 'Random-21 placebo test',
        'result': f'{pct_better}% random >= EXCLUDED_21', 'risk': placebo_risk,
        'detail': f'P{placebo["percentile_of_excluded"]:.0f}'})
    cv_lift = cv['summary']['avg_lift']
    folds_pos = cv['summary']['folds_positive_lift']
    cv_risk = 'LOW' if (folds_pos >= 4 and cv_lift > 0) else ('MEDIUM' if (folds_pos >= 3 and cv_lift > 0) else 'HIGH')
    items.append({'check': 'CV exclusion lift',
        'result': f'Avg lift: ${cv_lift:+.2f}, {folds_pos}/{N_CV_FOLDS} folds positive',
        'risk': cv_risk, 'detail': f'Jaccard stability: {cv["summary"]["jaccard_stability"]["avg"]:.3f}'})
    if universe['n_snapshots'] > 0:
        drift = universe['max_available'] - universe['min_available']
        drift_pct = drift / universe['max_available'] * 100 if universe['max_available'] > 0 else 0
        drift_risk = 'LOW' if drift_pct < 5 else ('MEDIUM' if drift_pct < 15 else 'HIGH')
    else:
        drift_pct = 0
        drift_risk = 'UNKNOWN'
    items.append({'check': 'Universe drift',
        'result': f'{universe["min_available"]}-{universe["max_available"]} coins ({drift_pct:.1f}% range)',
        'risk': drift_risk, 'detail': f'{universe["n_snapshots"]} weekly snapshots'})
    risk_scores = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'UNKNOWN': 2}
    avg_risk = sum(risk_scores.get(i['risk'], 2) for i in items) / len(items)
    overall = 'HIGH' if avg_risk >= 2.5 else ('MEDIUM' if avg_risk >= 1.5 else 'LOW')
    return {'items': items, 'overall_risk': overall, 'avg_risk_score': round(avg_risk, 2)}


def build_md_report(report, commit, elapsed):
    md = []
    md.append('# Part 2 -- Data / Selection Audit (Agent P0-A)')
    md.append('')
    rh = report['run_header']
    md.append(f'**Datum**: {rh["date"]}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: {rh["universe"]}')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')
    md.append('## Doel')
    md.append('')
    md.append('Kwantificeer de werkelijke waarde van de EXCLUDED_21 coin exclusion ')
    md.append('en bewijs eventuele biases in de data-assemblage. De exclusion is ')
    md.append('100% in-sample (circulair) en werd NIET bevestigd door expanding-window OOS.')
    md.append('')
    prov = report['data_provenance']
    md.append('## 1. Data Provenance')
    md.append('')
    md.append('| Item | Waarde |')
    md.append('|------|--------|')
    md.append(f'| Coins in cache | {prov["total_coins_in_cache"]} |')
    md.append(f'| T1 coins | {prov["tier1_coins"]} |')
    md.append(f'| T2 coins | {prov["tier2_coins"]} |')
    md.append(f'| Totaal tiered | {prov["tiered_total"]} |')
    md.append(f'| Bars (min/max/avg) | {prov["bar_count_stats"]["min"]} / {prov["bar_count_stats"]["max"]} / {prov["bar_count_stats"]["avg"]} |')
    md.append(f'| Datumbereik | {prov["date_range"]["earliest_timestamp"]} tot {prov["date_range"]["latest_timestamp"]} |')
    md.append(f'| EXCLUDED_21 | {prov["excluded_21_count"]} coins |')
    md.append('')
    surv = report['survivorship']
    md.append('## 2. Survivorship Scan')
    md.append('')
    md.append('| Categorie | Aantal |')
    md.append('|-----------|--------|')
    md.append(f'| Short-lived (<200 bars) | {surv["n_short"]} |')
    md.append(f'| Zero-vol tail (>=48 bars) | {surv["n_zero_vol"]} |')
    md.append(f'| Gezond | {surv["n_healthy"]} |')
    md.append('')
    if surv.get('short_lived'):
        md.append('**Short-lived coins** (eerste 10):')
        md.append('')
        md.append('| Coin | Bars |')
        md.append('|------|------|')
        for item in surv['short_lived'][:10]:
            md.append(f'| {item["coin"]} | {item["bars"]} |')
        md.append('')
    if surv.get('zero_vol_tail'):
        md.append('**Zero-vol tail coins** (eerste 10):')
        md.append('')
        md.append('| Coin | Trailing zero-vol | Totaal bars |')
        md.append('|------|-------------------|-------------|')
        for item in surv['zero_vol_tail'][:10]:
            md.append(f'| {item["coin"]} | {item["zero_vol_tail"]} | {item["bars"]} |')
        md.append('')
    circ = report['circularity_proof']
    md.append('## 3. EXCLUDED_21 Circulariteit')
    md.append('')
    md.append(f'Full-sample 316-coin backtest: **{circ["metrics_316"]["trades"]} trades**, PF={circ["metrics_316"]["pf"]:.3f}, P&L=${circ["metrics_316"]["pnl"]:.0f}')
    md.append('')
    md.append('| Item | Waarde |')
    md.append('|------|--------|')
    md.append(f'| Coins met trades | {circ["coins_with_trades"]} |')
    md.append(f'| Netto-negatieve coins (afgeleid) | {circ["n_negative_derived"]} |')
    md.append(f'| Overlap met EXCLUDED_21 | {circ["n_overlap"]} ({circ["jaccard"]:.1%} Jaccard) |')
    md.append(f'| Alleen in afgeleid | {", ".join(circ["only_in_derived"]) if circ["only_in_derived"] else "geen"} |')
    md.append(f'| Alleen in EXCLUDED_21 | {", ".join(circ["only_in_hardcoded"]) if circ["only_in_hardcoded"] else "geen"} |')
    md.append(f'| EXCLUDED_21 totaal PnL | ${circ["excl_total_pnl"]:.2f} |')
    md.append(f'| **Circulair?** | **{"JA" if circ["is_circular"] else "NEE"}** |')
    md.append('')
    if circ.get('coin_pnl_excluded'):
        md.append('**PnL per EXCLUDED_21 coin**:')
        md.append('')
        md.append('| Coin | PnL |')
        md.append('|------|-----|')
        for coin, pnl in sorted(circ['coin_pnl_excluded'].items(), key=lambda x: x[1]):
            md.append(f'| {coin} | ${pnl:.2f} |')
        md.append('')
    plac = report['placebo_test']
    md.append('## 4. Random-21 Placebo Test')
    md.append('')
    md.append(f'**Pool**: {plac["pool_size"]} coins met trades, {plac["n_placebo_runs"]} random-21 trekkingen')
    md.append('')
    md.append('| Metric | EXCLUDED_21 | Placebo mediaan | Placebo P5-P95 |')
    md.append('|--------|-------------|-----------------|----------------|')
    md.append(f'| PnL | ${plac["excluded_21_result"]["pnl"]:.0f} | ${plac["placebo_stats"]["median_pnl"]:.0f} | ${plac["placebo_stats"]["p5_pnl"]:.0f} tot ${plac["placebo_stats"]["p95_pnl"]:.0f} |')
    md.append(f'| Lift vs baseline | ${plac["excluded_21_result"]["lift_vs_baseline"]:+.0f} | ${plac["placebo_stats"]["median_lift"]:+.0f} | - |')
    md.append('')
    md.append(f'**Placebo runs >= EXCLUDED_21**: {plac["n_placebo_beat_excluded"]}/{plac["n_placebo_runs"]} ({plac["pct_placebo_beat_excluded"]}%)')
    md.append(f'**EXCLUDED_21 percentiel**: P{plac["percentile_of_excluded"]:.0f}')
    md.append('')
    if plac['pct_placebo_beat_excluded'] > 30:
        md.append('> **Conclusie**: EXCLUDED_21 is NIET significant beter dan willekeurige exclusion.')
    elif plac['pct_placebo_beat_excluded'] > 10:
        md.append('> **Conclusie**: EXCLUDED_21 presteert beter dan mediaan maar niet significant uniek.')
    else:
        md.append('> **Conclusie**: EXCLUDED_21 presteert significant beter dan random exclusion.')
    md.append('')
    cv = report['cv_exclusion']
    md.append('## 5. Cross-Validation Exclusion')
    md.append('')
    md.append(f'**Methode**: {cv["n_folds"]}-fold CV, embargo={cv["embargo_bars"]} bars')
    md.append('')
    md.append('| Fold | Train trades | N excluded | Test+excl PnL | Test-excl PnL | Lift |')
    md.append('|------|-------------|------------|---------------|---------------|------|')
    for fr in cv['fold_results']:
        md.append(f'| {fr["fold"]} | {fr["train_trades"]} | {fr["n_excluded"]} | ${fr["test_with_excl"]["pnl"]:.0f} | ${fr["test_no_excl"]["pnl"]:.0f} | ${fr["lift"]:+.0f} |')
    md.append('')
    summ = cv['summary']
    md.append(f'**Totale CV lift**: ${summ["total_lift"]:+.2f}')
    md.append(f'**Gemiddelde lift per fold**: ${summ["avg_lift"]:+.2f}')
    md.append(f'**Folds met positieve lift**: {summ["folds_positive_lift"]}/{cv["n_folds"]}')
    md.append(f'**Jaccard stabiliteit**: avg={summ["jaccard_stability"]["avg"]:.3f}, min={summ["jaccard_stability"]["min"]:.3f}, max={summ["jaccard_stability"]["max"]:.3f}')
    md.append(f'**Coins in alle folds excluded**: {summ["n_stable"]} coins')
    if summ['stable_coins_all_folds']:
        md.append(f'  {", ".join(summ["stable_coins_all_folds"])}')
    md.append('')
    univ = report['universe_as_of']
    md.append('## 6. Universe-as-of Analyse')
    md.append('')
    md.append(f'**Snapshots**: {univ["n_snapshots"]} wekelijkse punten')
    md.append(f'**Bereik**: {univ["min_available"]} - {univ["max_available"]} beschikbare coins')
    md.append('')
    if univ.get('static_comparisons'):
        md.append('| Bar | Jaccard vs 295 | Beschikbaar | Alleen dynamic | Alleen static |')
        md.append('|-----|---------------|-------------|----------------|---------------|')
        for comp in univ['static_comparisons']:
            md.append(f'| {comp["bar"]} | {comp["jaccard"]:.4f} | {comp["n_available"]} | {len(comp["only_in_available"])} | {len(comp["only_in_static"])} |')
        md.append('')
    sc = report['leakage_scorecard']
    md.append('## 7. Leakage Scorecard')
    md.append('')
    md.append('| Check | Resultaat | Risico |')
    md.append('|-------|-----------|--------|')
    for item in sc['items']:
        risk_label = f'**{item["risk"]}**' if item['risk'] == 'HIGH' else item['risk']
        md.append(f'| {item["check"]} | {item["result"]} | {risk_label} |')
    md.append('')
    md.append(f'**Totaal risico**: **{sc["overall_risk"]}** (score {sc["avg_risk_score"]:.2f}/3.0)')
    md.append('')
    md.append('## Verdict')
    md.append('')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append('')
    md.append('---')
    md.append(f'*Gegenereerd door run_part2_data_assembly_audit.py op {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


def main():
    parser = argparse.ArgumentParser(description='Part 2 -- Agent P0-A: Data / Selection Audit')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()
    print('=' * 70)
    print('  Part 2 -- Agent P0-A: Data / Selection Audit')
    print('  EXCLUDED_21 circulariteit, placebo test, CV exclusion, universe drift')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT)).decode().strip()
    except Exception:
        commit = 'unknown'
    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        print('[SKIP] No data available.')
        sys.exit(0)
    available_coins = set(data.keys())
    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        print('[SKIP] No tiering available.')
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
        print(f'  Would run: provenance, survivorship, circularity, placebo ({N_PLACEBO}x), CV ({N_CV_FOLDS}-fold), universe-as-of')
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
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% ({cov["vwap_available"]}/{cov["total_coins"]})')
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

    provenance = section_data_provenance(data, tier_coins_full)
    survivorship_result = section_survivorship(data)
    circularity, trades_316, coin_pnl_316 = section_circularity_proof(
        data, tier_coins_full, tier_indicators_full, market_context, tier1_fee, tier2_fee, total_bars)
    metrics_316 = circularity['metrics_316']
    coins_with_trades = set(coin_pnl_316.keys())
    placebo = section_placebo_test(
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee, total_bars,
        coins_with_trades, trades_316, metrics_316)
    cv_result = section_cv_exclusion(
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee, total_bars)
    universe_result = section_universe_as_of(data, tier_coins_full, total_bars)

    print('\n' + '=' * 70)
    print('  SECTION 7: Leakage Scorecard')
    print('=' * 70)
    scorecard = build_leakage_scorecard(provenance, survivorship_result, circularity, placebo, cv_result, universe_result)
    for item in scorecard['items']:
        print(f'  [{item["risk"]:6s}] {item["check"]}: {item["result"]}')
    print(f'\n  Overall risk: {scorecard["overall_risk"]} (score {scorecard["avg_risk_score"]:.2f}/3.0)')

    elapsed_total = time.time() - t0_total

    verdict_lines = []
    verdict_lines.append('### Samenvatting')
    verdict_lines.append('')
    if circularity['is_circular']:
        verdict_lines.append('1. **EXCLUDED_21 is 100% circulair**: De exclusion list is afgeleid van full-sample backtest resultaten. Dit is forward-looking bias.')
    else:
        verdict_lines.append('1. **EXCLUDED_21 is GEDEELTELIJK circulair**: Niet alle coins overlappen.')
    pct_beat = placebo['pct_placebo_beat_excluded']
    if pct_beat > 30:
        verdict_lines.append(f'2. **Placebo test: NIET significant** ({pct_beat:.0f}% random runs >= EXCLUDED_21). Willekeurige exclusion bereikt vergelijkbare resultaten.')
    elif pct_beat > 10:
        verdict_lines.append(f'2. **Placebo test: MARGINAAL** ({pct_beat:.0f}% random runs >= EXCLUDED_21).')
    else:
        verdict_lines.append(f'2. **Placebo test: SIGNIFICANT** (slechts {pct_beat:.0f}% random runs >= EXCLUDED_21).')
    cv_lift = cv_result['summary']['avg_lift']
    folds_pos = cv_result['summary']['folds_positive_lift']
    if cv_lift > 0 and folds_pos >= 3:
        verdict_lines.append(f'3. **CV exclusion: POSITIEF** (avg lift ${cv_lift:+.2f}, {folds_pos}/{N_CV_FOLDS} folds positief). Exclusion heeft enige OOS waarde.')
    elif cv_lift > 0:
        verdict_lines.append(f'3. **CV exclusion: ZWAK POSITIEF** (avg lift ${cv_lift:+.2f}, maar slechts {folds_pos}/{N_CV_FOLDS} folds positief).')
    else:
        verdict_lines.append(f'3. **CV exclusion: NEGATIEF** (avg lift ${cv_lift:+.2f}). Exclusion voegt OOS geen waarde toe.')
    if universe_result['n_snapshots'] > 0:
        drift = universe_result['max_available'] - universe_result['min_available']
        drift_pct = drift / universe_result['max_available'] * 100 if universe_result['max_available'] > 0 else 0
        verdict_lines.append(f'4. **Universe drift: {drift_pct:.1f}%** ({universe_result["min_available"]}-{universe_result["max_available"]} coins over {universe_result["n_snapshots"]} weken).')
    else:
        verdict_lines.append('4. **Universe drift: onbekend** (geen snapshots)')
    verdict_lines.append('')
    verdict_lines.append('### Aanbeveling')
    verdict_lines.append('')
    if scorecard['overall_risk'] == 'HIGH':
        verdict_lines.append(f'**HOOG RISICO**: De EXCLUDED_21 exclusion is circulair en heeft beperkte OOS waarde. Overweeg om ZONDER exclusion te werken, of gebruik alleen de {cv_result["summary"]["n_stable"]} coins die in alle CV-folds excluded worden.')
    elif scorecard['overall_risk'] == 'MEDIUM':
        verdict_lines.append('**GEMIDDELD RISICO**: De exclusion heeft enige OOS onderbouwing maar is niet volledig robuust. Gebruik rolling lookback exclusion in productie.')
    else:
        verdict_lines.append('**LAAG RISICO**: De data-assemblage en exclusion zijn goed onderbouwd.')

    print('\n' + '=' * 70)
    print('  Building reports...')
    print('=' * 70)
    report = {
        'run_header': {
            'task': 'part2_data_assembly_audit', 'agent': 'P0-A',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'), 'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION', 'params': BASELINE_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})', 'timeframe': '1h',
            'total_bars': total_bars, 'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'data_provenance': provenance,
        'survivorship': {
            'n_short': survivorship_result['n_short'], 'n_zero_vol': survivorship_result['n_zero_vol'],
            'n_healthy': survivorship_result['n_healthy'],
            'short_lived': survivorship_result['short_lived'][:20],
            'zero_vol_tail': survivorship_result['zero_vol_tail'][:20],
        },
        'circularity_proof': circularity,
        'placebo_test': placebo,
        'cv_exclusion': cv_result,
        'universe_as_of': {
            'n_snapshots': universe_result['n_snapshots'],
            'min_available': universe_result['min_available'],
            'max_available': universe_result['max_available'],
            'static_universe_size': universe_result['static_universe_size'],
            'static_comparisons': universe_result['static_comparisons'],
            'timeline_summary': {
                'first': universe_result['timeline'][0] if universe_result['timeline'] else None,
                'last': universe_result['timeline'][-1] if universe_result['timeline'] else None,
                'n_points': len(universe_result['timeline']),
            },
        },
        'leakage_scorecard': scorecard,
        'verdict_lines': verdict_lines,
    }
    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / 'part2_data_assembly_audit.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'[Report] JSON: {json_path}')
    md_text = build_md_report(report, commit, elapsed_total)
    md_path = out_dir / 'part2_data_assembly_audit.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Data / Selection Audit')
    print(f'  Overall leakage risk: {scorecard["overall_risk"]}')
    print(f'  Circulair: {"JA" if circularity["is_circular"] else "NEE"}')
    print(f'  Placebo: {placebo["pct_placebo_beat_excluded"]}% random >= EXCLUDED_21')
    print(f'  CV lift: ${cv_result["summary"]["avg_lift"]:+.2f} ({cv_result["summary"]["folds_positive_lift"]}/{N_CV_FOLDS} positief)')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
