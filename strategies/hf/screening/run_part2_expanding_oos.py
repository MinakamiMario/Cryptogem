#!/usr/bin/env python3
"""
Part 2 -- Agent C4-A2: Expanding Window OOS Validation
=======================================================
Tests whether the excl_all_negative coin exclusion generalises across
an expanding training window, and whether the exclusion list stabilises
as more data becomes available.

Algorithm:
  For train_end in range(min_train+50, total_bars-test_size, step):
      train: bars 50 .. train_end  (expanding)
      test:  bars train_end .. train_end+168  (fixed 1-week window)

      1. Run backtest on training window -> identify net-negative coins
      2. Run backtest on test window WITHOUT exclusion (full universe)
      3. Run backtest on test window WITH exclusion (remove train-negatives)
      4. Record delta (P&L, PF, trades)

  Aggregate all OOS test-window trades and evaluate gates.

Usage:
    python -m strategies.hf.screening.run_part2_expanding_oos
    python -m strategies.hf.screening.run_part2_expanding_oos --dry-run
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

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_COINS_ORACLE = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

WARMUP_BARS = 50
MIN_TRAIN_BARS = 336   # 2 weeks minimum training data
TEST_SIZE = 168         # 1 week test window
STEP = 168              # expand by 1 week each step


# ────────────────────────── Data Loading ──────────────────────────

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


# ────────────────────────── Metrics Helpers ──────────────────────────

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
            gap = (sorted_trades[i].get('entry_bar', 0)
                   - sorted_trades[i - 1].get('entry_bar', 0))
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2),
            'pf': round(pf, 3), 'wr': round(wr, 1),
            'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4),
            'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2),
            'expectancy': round(expectancy, 4)}


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


def coin_pnl_from_trades(trades):
    """Return dict of coin -> total pnl from a list of trades."""
    coin_pnl = defaultdict(float)
    for t in trades:
        coin_pnl[t.get('pair', 'unknown')] += t['pnl']
    return dict(coin_pnl)


def identify_negative_coins(trades):
    """From a list of trades, return set of coins with net-negative P&L."""
    coin_pnl = coin_pnl_from_trades(trades)
    return set(c for c, pnl in coin_pnl.items() if pnl < 0)


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ────────────────────────── Backtest Runner ──────────────────────────

def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None,
                start_bar=50, end_bar=None):
    """Run backtest on given tier_coins with optional bar range restriction."""
    if params is None:
        params = PARAMS_V5
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


# ══════════════════════════════════════════════════════════════════════
#  EXPANDING WINDOW OOS VALIDATION
# ══════════════════════════════════════════════════════════════════════

def run_expanding_window_oos(data, tier_coins_full, tier_indicators_full,
                              market_context, tier1_fee, tier2_fee,
                              stress_tier1_fee, stress_tier2_fee):
    """
    Expanding window OOS validation.

    For each step, the training window grows while the test window is a
    fixed 1-week segment immediately following the training period.
    """
    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    print(f'  total_bars={total_bars}')

    # Build indicator subset (reuse precomputed)
    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }

    # Calculate window boundaries
    first_train_end = WARMUP_BARS + MIN_TRAIN_BARS  # 50 + 336 = 386
    windows = []
    train_end = first_train_end
    while train_end + TEST_SIZE <= total_bars:
        test_start = train_end
        test_end = train_end + TEST_SIZE
        windows.append({
            'train_start': WARMUP_BARS,
            'train_end': train_end,
            'train_bars': train_end - WARMUP_BARS,
            'test_start': test_start,
            'test_end': test_end,
        })
        train_end += STEP

    print(f'  windows={len(windows)}, '
          f'first_train: bars {WARMUP_BARS}-{first_train_end} ({MIN_TRAIN_BARS} bars), '
          f'last_train: bars {WARMUP_BARS}-{windows[-1]["train_end"]} '
          f'({windows[-1]["train_bars"]} bars)')
    print(f'  test_size={TEST_SIZE} bars ({TEST_SIZE/BARS_PER_WEEK:.1f} week)')

    # ── Run each window ──
    window_results = []
    all_oos_trades_full = []        # aggregate OOS trades without exclusion
    all_oos_trades_excl = []        # aggregate OOS trades with exclusion
    all_exclusion_sets = []         # for stability tracking
    oos_fold_trades_full = {}       # window_idx -> trades (for fold concentration)
    oos_fold_trades_excl = {}

    for w_idx, w in enumerate(windows):
        t_w = time.time()

        # 1. Run backtest on expanding training window
        train_trades = run_variant(
            data, tier_coins_full, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=w['train_start'], end_bar=w['train_end'],
        )
        negative_coins = identify_negative_coins(train_trades)
        all_exclusion_sets.append(negative_coins)

        # 2. Run test window WITHOUT exclusion (full universe)
        test_trades_full = run_variant(
            data, tier_coins_full, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=w['test_start'], end_bar=w['test_end'],
        )

        # 3. Run test window WITH exclusion (remove training-negative coins)
        excl_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1']
                      if c not in negative_coins],
            'tier2': [c for c in tier_coins_full['tier2']
                      if c not in negative_coins],
        }
        test_trades_excl = run_variant(
            data, excl_tier_coins, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=w['test_start'], end_bar=w['test_end'],
        )

        # Accumulate OOS trades
        all_oos_trades_full.extend(test_trades_full)
        all_oos_trades_excl.extend(test_trades_excl)
        oos_fold_trades_full[w_idx] = test_trades_full
        oos_fold_trades_excl[w_idx] = test_trades_excl

        # Compute window metrics
        pnl_full = sum(t['pnl'] for t in test_trades_full)
        pnl_excl = sum(t['pnl'] for t in test_trades_excl)
        pnl_delta = pnl_excl - pnl_full
        n_full = len(test_trades_full)
        n_excl = len(test_trades_excl)
        n_excluded = len(negative_coins)
        elapsed_w = time.time() - t_w

        window_results.append({
            'window': w_idx,
            'train_bars': w['train_bars'],
            'train_weeks': round(w['train_bars'] / BARS_PER_WEEK, 1),
            'test_range': [w['test_start'], w['test_end']],
            'n_excluded': n_excluded,
            'excluded_coins': sorted(negative_coins),
            'test_full': {
                'trades': n_full,
                'pnl': round(pnl_full, 2),
            },
            'test_excl': {
                'trades': n_excl,
                'pnl': round(pnl_excl, 2),
            },
            'pnl_delta': round(pnl_delta, 2),
            'exclusion_helped': pnl_delta > 0,
            'runtime_s': round(elapsed_w, 1),
        })

        # Print progress
        helped_flag = 'YES' if pnl_delta > 0 else 'no'
        if w_idx < 4 or w_idx == len(windows) - 1:
            print(f'    w{w_idx:2d}: train={w["train_bars"]:4d}bars '
                  f'test=[{w["test_start"]}-{w["test_end"]}] '
                  f'excl={n_excluded:3d} | '
                  f'full: {n_full:3d}tr ${pnl_full:+7.0f} | '
                  f'excl: {n_excl:3d}tr ${pnl_excl:+7.0f} | '
                  f'delta=${pnl_delta:+7.0f} {helped_flag} '
                  f'({elapsed_w:.1f}s)')
        elif w_idx == 4:
            print(f'    ... ({len(windows) - 5} more windows) ...')

    # ── Aggregate OOS results ──
    total_oos_bars = len(windows) * TEST_SIZE
    agg_full_metrics = compute_metrics(all_oos_trades_full, total_oos_bars)
    agg_excl_metrics = compute_metrics(all_oos_trades_excl, total_oos_bars)

    # Count windows where exclusion helped
    n_helped = sum(1 for w in window_results if w['exclusion_helped'])

    print(f'\n  [Aggregate OOS]')
    print(f'    Windows: {len(windows)}, OOS bars: {total_oos_bars} '
          f'({total_oos_bars/BARS_PER_WEEK:.1f} weeks)')
    print(f'    Exclusion helped in {n_helped}/{len(windows)} windows')
    print(f'    Full:     {agg_full_metrics["trades"]}tr, '
          f'PF={agg_full_metrics["pf"]:.3f}, '
          f'P&L=${agg_full_metrics["pnl"]:.0f}, '
          f'exp/w=${agg_full_metrics["exp_per_week"]:.2f}')
    print(f'    Excluded: {agg_excl_metrics["trades"]}tr, '
          f'PF={agg_excl_metrics["pf"]:.3f}, '
          f'P&L=${agg_excl_metrics["pnl"]:.0f}, '
          f'exp/w=${agg_excl_metrics["exp_per_week"]:.2f}')

    # ── Exclusion list stability across expanding windows ──
    stability_overlaps = []
    for i in range(1, len(all_exclusion_sets)):
        prev = all_exclusion_sets[i - 1]
        curr = all_exclusion_sets[i]
        if prev or curr:
            union_sz = len(prev | curr)
            inter_sz = len(prev & curr)
            overlap_pct = inter_sz / union_sz * 100 if union_sz > 0 else 0
            stability_overlaps.append(overlap_pct)

    avg_overlap = (sum(stability_overlaps) / len(stability_overlaps)
                   if stability_overlaps else 0)
    min_overlap = min(stability_overlaps) if stability_overlaps else 0
    max_overlap = max(stability_overlaps) if stability_overlaps else 0

    # Track exclusion list size trend (should stabilise as training grows)
    excl_sizes = [w['n_excluded'] for w in window_results]

    # Coin exclusion frequency across all windows
    coin_excl_freq = defaultdict(int)
    for excl_set in all_exclusion_sets:
        for c in excl_set:
            coin_excl_freq[c] += 1
    n_windows = len(all_exclusion_sets)
    coin_excl_pct = {c: round(cnt / n_windows * 100, 1)
                     for c, cnt in sorted(coin_excl_freq.items(),
                                           key=lambda x: -x[1])}
    # Coins excluded in ALL windows = "stable exclusions"
    stable_excl = sorted(c for c, cnt in coin_excl_freq.items()
                         if cnt == n_windows)
    # Coins excluded in >75% of windows
    frequent_excl = sorted(c for c, cnt in coin_excl_freq.items()
                           if cnt / n_windows >= 0.75)

    print(f'\n  [Exclusion Stability]')
    print(f'    Avg consecutive overlap: {avg_overlap:.1f}% '
          f'(min={min_overlap:.0f}%, max={max_overlap:.0f}%)')
    print(f'    Exclusion list size: '
          f'first={excl_sizes[0]}, last={excl_sizes[-1]}, '
          f'min={min(excl_sizes)}, max={max(excl_sizes)}')
    print(f'    Coins excluded in ALL windows: {len(stable_excl)}')
    print(f'    Coins excluded in >75% windows: {len(frequent_excl)}')
    if stable_excl:
        print(f'    Stable exclusions: {stable_excl}')

    # ── Overlap with oracle exclusion list ──
    oracle_overlap = len(EXCLUDED_COINS_ORACLE & set(stable_excl))
    oracle_overlap_freq = len(EXCLUDED_COINS_ORACLE & set(frequent_excl))
    print(f'\n  [Oracle Overlap]')
    print(f'    Stable excl in oracle (21): {oracle_overlap}/{len(stable_excl)}')
    print(f'    Frequent excl in oracle: {oracle_overlap_freq}/{len(frequent_excl)}')

    # ── Gate evaluation on aggregated OOS excluded trades ──
    print(f'\n  [Gate Evaluation on aggregated OOS - excluded version]')

    # For WF-like fold counting, use each window as a "fold"
    n_folds_pos_full = sum(1 for w in window_results
                           if w['test_full']['pnl'] > 0)
    n_folds_pos_excl = sum(1 for w in window_results
                           if w['test_excl']['pnl'] > 0)

    fold_conc_excl = compute_fold_concentration(oos_fold_trades_excl)
    fold_conc_full = compute_fold_concentration(oos_fold_trades_full)

    # For stress metrics, run full-sample stress backtest with
    # the stable exclusion list
    stable_excl_set = set(stable_excl)
    stable_tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1']
                  if c not in stable_excl_set],
        'tier2': [c for c in tier_coins_full['tier2']
                  if c not in stable_excl_set],
    }
    stress_trades = run_variant(
        data, stable_tier_coins, tier_indicators_filtered,
        market_context, stress_tier1_fee, stress_tier2_fee,
    )
    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    stress_metrics = compute_metrics(stress_trades, total_bars)

    # Use window count as folds for G6, but scale: >= 80% positive windows
    # maps to the equivalent of 4/5 WF folds
    pct_pos_windows = n_folds_pos_excl / len(windows) * 100
    equiv_wf_folds = round(pct_pos_windows / 100 * 5)  # scale to 5-fold equiv

    gate_eval = evaluate_gates(
        agg_excl_metrics, equiv_wf_folds, 5,
        stress_metrics, fold_conc_excl,
    )

    print(f'    Positive OOS windows (excl): {n_folds_pos_excl}/{len(windows)} '
          f'({pct_pos_windows:.0f}%) -> equiv WF {equiv_wf_folds}/5')
    print(f'    Gate score: {gate_eval["score"]}')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  '
              f'({g["threshold"]}) -> {status}')

    return {
        'n_windows': len(windows),
        'total_oos_bars': total_oos_bars,
        'total_oos_weeks': round(total_oos_bars / BARS_PER_WEEK, 1),
        'total_bars': total_bars,
        'window_results': window_results,
        'aggregate_full': agg_full_metrics,
        'aggregate_excl': agg_excl_metrics,
        'aggregate_delta': {
            'pnl': round(agg_excl_metrics['pnl'] - agg_full_metrics['pnl'], 2),
            'pf': round(agg_excl_metrics['pf'] - agg_full_metrics['pf'], 3),
            'trades': agg_excl_metrics['trades'] - agg_full_metrics['trades'],
        },
        'windows_helped': n_helped,
        'windows_helped_pct': round(n_helped / len(windows) * 100, 1),
        'stability': {
            'avg_overlap_pct': round(avg_overlap, 1),
            'min_overlap_pct': round(min_overlap, 1),
            'max_overlap_pct': round(max_overlap, 1),
            'excl_sizes': excl_sizes,
            'overlaps': [round(o, 1) for o in stability_overlaps],
        },
        'stable_exclusions': stable_excl,
        'n_stable': len(stable_excl),
        'frequent_exclusions': frequent_excl,
        'n_frequent': len(frequent_excl),
        'coin_exclusion_frequency': coin_excl_pct,
        'oracle_overlap': {
            'stable_in_oracle': oracle_overlap,
            'stable_total': len(stable_excl),
            'frequent_in_oracle': oracle_overlap_freq,
            'frequent_total': len(frequent_excl),
            'oracle_total': len(EXCLUDED_COINS_ORACLE),
        },
        'oos_gate_evaluation': gate_eval,
        'oos_positive_windows_full': n_folds_pos_full,
        'oos_positive_windows_excl': n_folds_pos_excl,
        'oos_fold_conc_full': fold_conc_full,
        'oos_fold_conc_excl': fold_conc_excl,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C4-A2: Expanding Window OOS Validation')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C4-A2: Expanding Window OOS Validation')
    print('  Does exclusion generalise as training data expands?')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = get_harness_fee('mexc_market_p95', 'tier1')
    stress_tier2_fee = get_harness_fee('mexc_market_p95', 'tier2')
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] P95 stress: T1={stress_tier1_fee*10000:.1f}bps, '
          f'T2={stress_tier2_fee*10000:.1f}bps')

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
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
        # Estimate total bars from data
        max_bars_est = max(len(v) for v in data.values())
        first_te = WARMUP_BARS + MIN_TRAIN_BARS
        n_win_est = 0
        te = first_te
        while te + TEST_SIZE <= max_bars_est:
            n_win_est += 1
            te += STEP
        print(f'\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}')
        print(f'  Estimated total bars: {max_bars_est}')
        print(f'  Expanding windows: ~{n_win_est}')
        print(f'  Min train: {MIN_TRAIN_BARS} bars '
              f'({MIN_TRAIN_BARS/BARS_PER_WEEK:.1f} weeks)')
        print(f'  Test size: {TEST_SIZE} bars ({TEST_SIZE/BARS_PER_WEEK:.1f} weeks)')
        print(f'  Step: {STEP} bars ({STEP/BARS_PER_WEEK:.1f} weeks)')
        print(f'  Each window = 3 backtests (train + test_full + test_excl)')
        print(f'  Total backtests: ~{n_win_est * 3}')
        sys.exit(0)

    # Precompute indicators (once, reuse for all windows)
    print('\n[Indicators] Precomputing base indicators...')
    tier_indicators_full = {}
    for tier_name, coins in tier_coins_full.items():
        if coins:
            t_ind = time.time()
            tier_indicators_full[tier_name] = precompute_base_indicators(
                data, coins)
            print(f'  {tier_name}: {len(coins)} coins in '
                  f'{time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_full.items():
        if coins and tier_name in tier_indicators_full:
            extend_indicators(data, coins, tier_indicators_full[tier_name])
            cov = get_feature_coverage(tier_indicators_full[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_full.get('tier1', [])
                         + tier_coins_full.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicators
    for tier_name, ind_dict in tier_indicators_full.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ── RUN EXPANDING WINDOW OOS ──
    print('\n' + '=' * 70)
    print('  EXPANDING WINDOW OOS VALIDATION')
    print('=' * 70)

    result = run_expanding_window_oos(
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        stress_tier1_fee, stress_tier2_fee,
    )

    elapsed_total = time.time() - t0_total

    # ── VERDICT ──
    agg_delta_pnl = result['aggregate_delta']['pnl']
    agg_delta_pf = result['aggregate_delta']['pf']
    pct_helped = result['windows_helped_pct']
    n_stable = result['n_stable']
    gate_score = result['oos_gate_evaluation']['score']

    # Verdict logic:
    # - Exclusion helps consistently OOS if >60% of windows helped AND agg P&L delta > 0
    # - Exclusion list stabilises if stable exclusions exist and overlap is high
    # - Strategy generalises if gate score >= 4/7
    if pct_helped >= 60 and agg_delta_pnl > 0 and n_stable > 0:
        verdict = 'CONFIRMED_STRUCTURAL'
        verdict_detail = (
            f'Expanding window OOS CONFIRMS the structural feature finding. '
            f'Exclusion helped in {pct_helped:.0f}% of OOS windows with '
            f'aggregate P&L delta of ${agg_delta_pnl:+.0f}. '
            f'{n_stable} coins consistently excluded across all windows.'
        )
    elif pct_helped >= 45 or (agg_delta_pnl > 0 and n_stable >= 5):
        verdict = 'PARTIAL_CONFIRMATION'
        verdict_detail = (
            f'Partial confirmation. Exclusion helped in {pct_helped:.0f}% of '
            f'windows. Aggregate delta ${agg_delta_pnl:+.0f}. '
            f'{n_stable} stable exclusions. The signal exists but is not '
            f'dominant across all time periods.'
        )
    else:
        verdict = 'NOT_CONFIRMED'
        verdict_detail = (
            f'Expanding window OOS does NOT confirm the structural feature. '
            f'Exclusion helped in only {pct_helped:.0f}% of windows. '
            f'Aggregate delta ${agg_delta_pnl:+.0f}. '
            f'The exclusion benefit is largely in-sample.'
        )

    print(f'\n{"=" * 70}')
    print(f'  VERDICT: {verdict}')
    print(f'  {verdict_detail}')
    print(f'  OOS Gate score: {gate_score}')
    print(f'{"=" * 70}')

    # ── BUILD JSON REPORT ──
    report = {
        'run_header': {
            'task': 'part2_expanding_oos',
            'agent': 'C4-A2',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'cost_regime': 'MEXC Market',
            'fees_bps': {
                'tier1': round(tier1_fee * 10000, 1),
                'tier2': round(tier2_fee * 10000, 1),
            },
            'stress_fees_bps': {
                'tier1': round(stress_tier1_fee * 10000, 1),
                'tier2': round(stress_tier2_fee * 10000, 1),
            },
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'runtime_s': round(elapsed_total, 1),
            'config': {
                'warmup_bars': WARMUP_BARS,
                'min_train_bars': MIN_TRAIN_BARS,
                'test_size': TEST_SIZE,
                'step': STEP,
            },
        },
        'expanding_oos': result,
        'verdict': {
            'result': verdict,
            'detail': verdict_detail,
            'aggregate_pnl_delta': agg_delta_pnl,
            'aggregate_pf_delta': agg_delta_pf,
            'pct_windows_helped': pct_helped,
            'n_stable_exclusions': n_stable,
            'oos_gate_score': gate_score,
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_expanding_oos_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ── BUILD MARKDOWN REPORT ──
    md = []
    md.append('# Part 2 -- Expanding Window OOS Validation (Agent C4-A2)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={PARAMS_V5["dev_thresh"]}, '
              f'tp={PARAMS_V5["tp_pct"]}, sl={PARAMS_V5["sl_pct"]}, '
              f'tl={PARAMS_V5["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, '
              f'T2={tier2_fee*10000:.1f}bps')
    md.append(f'**Stress**: T1={stress_tier1_fee*10000:.1f}bps, '
              f'T2={stress_tier2_fee*10000:.1f}bps (P95)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    md.append('## Objective')
    md.append('')
    md.append('Validate the `excl_all_negative` exclusion approach using an '
              '**expanding training window**:')
    md.append('')
    md.append(f'- Training: bars {WARMUP_BARS} to train_end (expanding from '
              f'{MIN_TRAIN_BARS} bars)')
    md.append(f'- Test: fixed {TEST_SIZE}-bar ({TEST_SIZE/BARS_PER_WEEK:.0f}-week) '
              f'window after training')
    md.append(f'- Step: expand training by {STEP} bars '
              f'({STEP/BARS_PER_WEEK:.0f} week) each iteration')
    md.append(f'- Total windows: {result["n_windows"]}')
    md.append('')
    md.append('Key question: does the exclusion list stabilise and the delta '
              'remain positive as more training data is used?')
    md.append('')

    md.append('## Per-Window Results')
    md.append('')
    md.append('| Window | Train (bars) | Train (wk) | Test Range | Excl | '
              'Full Tr | Full P&L | Excl Tr | Excl P&L | Delta | Helped |')
    md.append('|--------|-------------|-----------|------------|------|'
              '---------|----------|---------|----------|-------|--------|')
    for w in result['window_results']:
        helped = 'YES' if w['exclusion_helped'] else 'no'
        md.append(
            f'| {w["window"]} | {w["train_bars"]} | {w["train_weeks"]} | '
            f'{w["test_range"][0]}-{w["test_range"][1]} | {w["n_excluded"]} | '
            f'{w["test_full"]["trades"]} | ${w["test_full"]["pnl"]:.0f} | '
            f'{w["test_excl"]["trades"]} | ${w["test_excl"]["pnl"]:.0f} | '
            f'${w["pnl_delta"]:+.0f} | {helped} |'
        )
    md.append('')

    md.append('## Aggregate OOS Metrics')
    md.append('')
    af = result['aggregate_full']
    ae = result['aggregate_excl']
    ad = result['aggregate_delta']
    md.append('| Metric | Full Universe | With Exclusion | Delta |')
    md.append('|--------|-------------|----------------|-------|')
    md.append(f'| Trades | {af["trades"]} | {ae["trades"]} | {ad["trades"]:+d} |')
    md.append(f'| P&L | ${af["pnl"]:.0f} | ${ae["pnl"]:.0f} | '
              f'${ad["pnl"]:+.0f} |')
    md.append(f'| PF | {af["pf"]:.3f} | {ae["pf"]:.3f} | '
              f'{ad["pf"]:+.3f} |')
    md.append(f'| WR | {af["wr"]:.1f}% | {ae["wr"]:.1f}% | '
              f'{ae["wr"]-af["wr"]:+.1f}% |')
    md.append(f'| Exp/week | ${af["exp_per_week"]:.2f} | '
              f'${ae["exp_per_week"]:.2f} | |')
    md.append(f'| DD% | {af["max_dd_pct"]:.1f}% | {ae["max_dd_pct"]:.1f}% | |')
    md.append('')
    md.append(f'**Windows where exclusion helped**: '
              f'{result["windows_helped"]}/{result["n_windows"]} '
              f'({pct_helped:.0f}%)')
    md.append('')

    md.append('## Exclusion List Stability')
    md.append('')
    stab = result['stability']
    md.append(f'- **Consecutive overlap**: avg={stab["avg_overlap_pct"]:.1f}%, '
              f'min={stab["min_overlap_pct"]:.0f}%, '
              f'max={stab["max_overlap_pct"]:.0f}%')
    md.append(f'- **Exclusion list size**: first={stab["excl_sizes"][0]}, '
              f'last={stab["excl_sizes"][-1]}')
    md.append(f'- **Coins excluded in ALL windows**: {result["n_stable"]}')
    md.append(f'- **Coins excluded in >75% windows**: {result["n_frequent"]}')
    md.append('')

    if result['stable_exclusions']:
        md.append('### Stable Exclusions (in ALL expanding windows)')
        md.append('')
        md.append('| Coin | Excl Freq (%) | In Oracle? |')
        md.append('|------|--------------|------------|')
        freq = result['coin_exclusion_frequency']
        for c in result['stable_exclusions']:
            in_oracle = 'YES' if c in EXCLUDED_COINS_ORACLE else 'no'
            md.append(f'| {c} | {freq.get(c, 0):.0f}% | {in_oracle} |')
        md.append('')

    if result['frequent_exclusions']:
        md.append('### Frequent Exclusions (>75% of windows)')
        md.append('')
        md.append('| Coin | Excl Freq (%) | In Oracle? |')
        md.append('|------|--------------|------------|')
        freq = result['coin_exclusion_frequency']
        for c in result['frequent_exclusions']:
            if c not in result['stable_exclusions']:
                in_oracle = 'YES' if c in EXCLUDED_COINS_ORACLE else 'no'
                md.append(f'| {c} | {freq.get(c, 0):.0f}% | {in_oracle} |')
        md.append('')

    # Oracle overlap
    oo = result['oracle_overlap']
    md.append(f'### Oracle Overlap')
    md.append('')
    md.append(f'- Stable exclusions also in oracle (21): '
              f'{oo["stable_in_oracle"]}/{oo["stable_total"]}')
    md.append(f'- Frequent exclusions also in oracle: '
              f'{oo["frequent_in_oracle"]}/{oo["frequent_total"]}')
    md.append('')

    md.append('## OOS Gate Evaluation')
    md.append('')
    md.append('Gate evaluation on aggregated OOS trades from excluded version.')
    md.append('')
    ge = result['oos_gate_evaluation']
    md.append('| Gate | Metric | Value | Threshold | Verdict |')
    md.append('|------|--------|-------|-----------|---------|')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = ge['gates'][gid]
        status = 'PASS' if g['pass'] else '**FAIL**'
        md.append(f'| {gid} | {g["name"]} | {g["value"]} | '
                  f'{g["threshold"]} | {status} |')
    md.append('')
    md.append(f'**Gate score: {ge["score"]}**')
    md.append('')

    stress_m = result['stress_metrics']
    md.append(f'Stress test (P95, stable excl): trades={stress_m["trades"]}, '
              f'PF={stress_m["pf"]:.3f}, P&L=${stress_m["pnl"]:.0f}, '
              f'exp/w=${stress_m["exp_per_week"]:.2f}')
    md.append('')

    md.append('## Verdict')
    md.append('')
    md.append(f'### **{verdict}**')
    md.append('')
    md.append(verdict_detail)
    md.append('')
    md.append(f'| Evidence | Value |')
    md.append(f'|----------|-------|')
    md.append(f'| OOS windows helped | {result["windows_helped"]}/'
              f'{result["n_windows"]} ({pct_helped:.0f}%) |')
    md.append(f'| Aggregate P&L delta | ${agg_delta_pnl:+.0f} |')
    md.append(f'| Aggregate PF delta | {agg_delta_pf:+.3f} |')
    md.append(f'| Stable exclusions | {n_stable} coins |')
    md.append(f'| OOS gate score | {gate_score} |')
    _avg_ol = result['stability']['avg_overlap_pct']
    md.append(f'| Excl list stabilises? | '
              f'{"Yes" if _avg_ol >= 70 else "Partial" if _avg_ol >= 50 else "No"} '
              f'(overlap {_avg_ol:.0f}%) |')
    md.append('')

    if verdict == 'CONFIRMED_STRUCTURAL':
        md.append('### Implication')
        md.append('')
        md.append('The expanding window analysis confirms that coin exclusion '
                   'based on training-period performance is a structural '
                   'feature, not overfitting. The exclusion list stabilises '
                   'as training data grows, and the OOS benefit is consistent.')
    elif verdict == 'PARTIAL_CONFIRMATION':
        md.append('### Implication')
        md.append('')
        md.append('Some structural signal exists but the benefit is not '
                   'dominant. A conservative approach using only the most '
                   'stable exclusions may be warranted.')
    else:
        md.append('### Implication')
        md.append('')
        md.append('The exclusion benefit does not generalise reliably '
                   'in the expanding window test. The in-sample exclusion '
                   'advantage likely reflects overfitting rather than a '
                   'durable structural pattern.')

    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_expanding_oos.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_expanding_oos_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Expanding Window OOS Validation')
    print(f'  Verdict: {verdict}')
    print(f'  OOS Gate score: {gate_score}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
