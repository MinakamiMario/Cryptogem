#!/usr/bin/env python3
"""
Part 2 -- Agent C3-A2: Rolling Lookback Exclusion Simulation
=============================================================
Production-ready mechanism for coin exclusion without forward-looking bias.

Instead of using full-sample knowledge to identify bad coins, this script
simulates the actual production workflow:
  - Divide data into weekly segments
  - For each segment, look back N bars to identify net-negative coins
  - Exclude those coins from the CURRENT segment only
  - Aggregate all segment results into a full P&L series

Tests lookback windows of 168 (1 week), 336 (2 weeks), 504 (3 weeks) bars,
with exclusion thresholds: all-negative, worst-12.

Usage:
    python -m strategies.hf.screening.run_part2_rolling_exclusion
    python -m strategies.hf.screening.run_part2_rolling_exclusion --dry-run
    python -m strategies.hf.screening.run_part2_rolling_exclusion --require-data
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

GATE_THRESHOLDS = {
    'G1_trades_per_week': 10,
    'G2_max_gap_days': 2.5,
    'G3_exp_per_week_market': 0,
    'G4_exp_per_week_stress': 0,
    'G5_max_dd_pct': 20,
    'G6_wf_folds_positive': 4,
    'G8_top1_fold_conc_pct': 35,
}

# Lookback windows to test (in bars)
LOOKBACK_WINDOWS = [168, 336, 504]  # 1wk, 2wk, 3wk
SEGMENT_SIZE = 168  # 1 week per forward segment
WARMUP_BARS = 50    # standard indicator warmup


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
            gap = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i - 1].get('entry_bar', 0)
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
            'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4)}


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


def identify_worst_n_coins(trades, n):
    """From a list of trades, return set of N worst coins by P&L."""
    coin_pnl = coin_pnl_from_trades(trades)
    sorted_coins = sorted(coin_pnl.items(), key=lambda x: x[1])
    # Only exclude coins that are actually negative
    worst = []
    for coin, pnl in sorted_coins[:n]:
        if pnl < 0:
            worst.append(coin)
    return set(worst)


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ────────────────────────── Backtest Runners ──────────────────────────

def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None,
                start_bar=50, end_bar=None):
    """Run backtest on given tier_coins with optional bar range restriction."""
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


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    """Walk-forward across tiers, merging fold results."""
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


# ══════════════════════════════════════════════════════════════════════
#  ROLLING LOOKBACK EXCLUSION SIMULATION
# ══════════════════════════════════════════════════════════════════════

def run_rolling_simulation(data, tier_coins_full, tier_indicators_full,
                           market_context, tier1_fee, tier2_fee,
                           lookback_bars, segment_size, exclusion_mode,
                           label=''):
    """
    Rolling lookback exclusion simulation.

    For each forward segment [seg_start, seg_end]:
      1. Lookback window: [seg_start - lookback_bars, seg_start]
      2. Run backtest on lookback to identify negative/worst-N coins
      3. Exclude those coins from the current segment
      4. Run backtest on current segment with exclusion applied
      5. Record trades

    Args:
        lookback_bars: how many bars to look back from segment start
        segment_size: forward segment size (bars)
        exclusion_mode: 'all_negative' or 'worst_12'
        label: descriptive label for this variant
    """
    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)

    # Build indicator subset (reuse precomputed)
    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }

    # The first segment starts where we have enough lookback data
    # We need at least WARMUP_BARS + lookback_bars before first segment
    first_seg_start = max(WARMUP_BARS, WARMUP_BARS + lookback_bars)
    # If lookback requires more bars than we have warmup, adjust
    if first_seg_start > total_bars:
        print(f'    [WARN] Not enough data for lookback={lookback_bars}')
        return None

    # Build segment boundaries
    segments = []
    seg_start = first_seg_start
    while seg_start < total_bars:
        seg_end = min(seg_start + segment_size, total_bars)
        lb_start = max(WARMUP_BARS, seg_start - lookback_bars)
        lb_end = seg_start
        segments.append({
            'seg_start': seg_start,
            'seg_end': seg_end,
            'lb_start': lb_start,
            'lb_end': lb_end,
        })
        seg_start = seg_end

    print(f'  [{label}] {len(segments)} segments, '
          f'lookback={lookback_bars}bars ({lookback_bars/BARS_PER_WEEK:.1f}wk), '
          f'segment={segment_size}bars ({segment_size/BARS_PER_WEEK:.1f}wk), '
          f'excl={exclusion_mode}')

    all_segment_trades = []
    segment_details = []
    all_exclusion_sets = []  # for stability analysis

    for seg_idx, seg in enumerate(segments):
        # STEP 1: Run lookback window to identify bad coins
        lb_trades = run_variant(
            data, tier_coins_full, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=seg['lb_start'], end_bar=seg['lb_end'],
        )

        # STEP 2: Identify coins to exclude based on lookback
        if exclusion_mode == 'all_negative':
            excl_coins = identify_negative_coins(lb_trades)
        elif exclusion_mode == 'worst_12':
            excl_coins = identify_worst_n_coins(lb_trades, 12)
        else:
            excl_coins = set()

        all_exclusion_sets.append(excl_coins)

        # STEP 3: Build filtered coin list for this segment
        seg_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_coins],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_coins],
        }

        # STEP 4: Run backtest on current segment with exclusion
        seg_trades = run_variant(
            data, seg_tier_coins, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=seg['seg_start'], end_bar=seg['seg_end'],
        )

        # Tag trades with segment info
        for t in seg_trades:
            t['_segment'] = seg_idx

        all_segment_trades.extend(seg_trades)

        seg_pnl = sum(t['pnl'] for t in seg_trades)
        lb_n_trades = len(lb_trades)

        segment_details.append({
            'segment': seg_idx,
            'seg_bars': [seg['seg_start'], seg['seg_end']],
            'lb_bars': [seg['lb_start'], seg['lb_end']],
            'lb_trades': lb_n_trades,
            'excluded_coins': sorted(excl_coins),
            'n_excluded': len(excl_coins),
            'n_coins_active': sum(len(c) for c in seg_tier_coins.values()),
            'seg_trades': len(seg_trades),
            'seg_pnl': round(seg_pnl, 2),
        })

        if seg_idx < 4 or seg_idx == len(segments) - 1:
            print(f'    seg {seg_idx}: bars {seg["seg_start"]}-{seg["seg_end"]} | '
                  f'lb_trades={lb_n_trades} | excl={len(excl_coins)} | '
                  f'seg_trades={len(seg_trades)} | pnl=${seg_pnl:+.0f}')
        elif seg_idx == 4:
            print(f'    ... ({len(segments) - 5} more segments) ...')

    # Compute rolling metrics over the full aggregated period
    total_forward_bars = sum(s['seg_end'] - s['seg_start'] for s in segments)
    rolling_metrics = compute_metrics(all_segment_trades, total_forward_bars)

    # Exclusion list stability: how much overlap between consecutive segments?
    stability_overlaps = []
    for i in range(1, len(all_exclusion_sets)):
        prev = all_exclusion_sets[i - 1]
        curr = all_exclusion_sets[i]
        if prev or curr:
            union_size = len(prev | curr)
            inter_size = len(prev & curr)
            overlap_pct = inter_size / union_size * 100 if union_size > 0 else 0
            stability_overlaps.append(overlap_pct)

    avg_overlap = sum(stability_overlaps) / len(stability_overlaps) if stability_overlaps else 0
    min_overlap = min(stability_overlaps) if stability_overlaps else 0
    max_overlap = max(stability_overlaps) if stability_overlaps else 0

    # Coin exclusion frequency: how often is each coin excluded?
    coin_excl_freq = defaultdict(int)
    for excl_set in all_exclusion_sets:
        for c in excl_set:
            coin_excl_freq[c] += 1
    total_segments = len(all_exclusion_sets)
    coin_excl_pct = {c: round(cnt / total_segments * 100, 1)
                     for c, cnt in sorted(coin_excl_freq.items(), key=lambda x: -x[1])}

    # Coins excluded in >50% of segments = "persistently bad"
    persistent_excl = [c for c, cnt in coin_excl_freq.items()
                       if cnt / total_segments >= 0.5]

    print(f'    TOTAL: {rolling_metrics["trades"]} trades, PF={rolling_metrics["pf"]:.3f}, '
          f'P&L=${rolling_metrics["pnl"]:.0f}, exp/w=${rolling_metrics["exp_per_week"]:.2f}')
    print(f'    Stability: avg_overlap={avg_overlap:.1f}%, '
          f'min={min_overlap:.0f}%, max={max_overlap:.0f}%')
    print(f'    Persistent excludes (>50%): {len(persistent_excl)} coins')

    return {
        'label': label,
        'lookback_bars': lookback_bars,
        'lookback_weeks': round(lookback_bars / BARS_PER_WEEK, 1),
        'segment_size': segment_size,
        'exclusion_mode': exclusion_mode,
        'n_segments': len(segments),
        'total_forward_bars': total_forward_bars,
        'metrics': rolling_metrics,
        'segment_details': segment_details,
        'stability': {
            'avg_overlap_pct': round(avg_overlap, 1),
            'min_overlap_pct': round(min_overlap, 1),
            'max_overlap_pct': round(max_overlap, 1),
            'consecutive_overlaps': [round(o, 1) for o in stability_overlaps],
        },
        'coin_exclusion_frequency': coin_excl_pct,
        'persistent_excludes': sorted(persistent_excl),
        'n_persistent': len(persistent_excl),
    }


def run_no_exclusion_baseline(data, tier_coins_full, tier_indicators_full,
                               market_context, tier1_fee, tier2_fee,
                               first_seg_start, total_bars, segment_size):
    """Run baseline (no exclusion) over the same forward segments for fair comparison."""
    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }

    all_trades = []
    seg_start = first_seg_start
    while seg_start < total_bars:
        seg_end = min(seg_start + segment_size, total_bars)
        trades = run_variant(
            data, tier_coins_full, tier_indicators_filtered,
            market_context, tier1_fee, tier2_fee,
            start_bar=seg_start, end_bar=seg_end,
        )
        all_trades.extend(trades)
        seg_start = seg_end

    total_forward_bars = total_bars - first_seg_start
    metrics = compute_metrics(all_trades, total_forward_bars)
    return all_trades, metrics


# ══════════════════════════════════════════════════════════════════════
#  FULL EVALUATION (GATE ASSESSMENT)
# ══════════════════════════════════════════════════════════════════════

def run_full_evaluation_for_rolling(label, data, tier_coins, tier_indicators_full,
                                     market_context, tier1_fee, tier2_fee,
                                     stress_tier1_fee, stress_tier2_fee, total_bars):
    """Full gate evaluation for the full-sample exclusion reference."""
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in tier_indicators_full:
            tier_indicators[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee)
    metrics = compute_metrics(trades, total_bars)
    print(f'    trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'exp/w=${metrics["exp_per_week"]:.2f} DD={metrics["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Running stress (2x fees)...')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    stress_metrics = compute_metrics(stress_trades, total_bars)

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
    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    return {
        'label': label,
        'metrics': metrics,
        'stress_metrics': {'pnl': stress_metrics['pnl'], 'pf': stress_metrics['pf'],
                          'exp_per_week': stress_metrics['exp_per_week']},
        'wf_folds_positive': folds_positive, 'wf_fold_details': fold_details,
        'fold_concentration': fold_conc, 'gate_evaluation': gate_eval,
        'runtime_s': round(elapsed, 1),
    }


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C3-A2: Rolling Lookback Exclusion Simulation')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C3-A2: Rolling Lookback Exclusion Simulation')
    print('  Production mechanism: lookback N bars -> exclude bad coins -> trade')
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
        print(f'  Lookback windows: {LOOKBACK_WINDOWS} bars')
        print(f'  Segment size: {SEGMENT_SIZE} bars')
        print(f'  Exclusion modes: all_negative, worst_12')
        total_variants = len(LOOKBACK_WINDOWS) * 2  # 2 exclusion modes
        print(f'  Total variants: {total_variants}')
        sys.exit(0)

    # Precompute indicators (once, reuse for all methods)
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

    # ══════════════════════════════════════════════════════════════
    # STEP 1: Reference baselines (full-sample, no exclusion)
    # ══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 1: Reference baselines')
    print('=' * 70)

    # (a) No exclusion - full sample
    print('\n  [baseline_no_excl] Full universe, no exclusion...')
    baseline_trades = run_variant(data, tier_coins_full, tier_indicators_full,
                                   market_context, tier1_fee, tier2_fee)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'    trades={baseline_metrics["trades"]} PF={baseline_metrics["pf"]:.3f} '
          f'P&L=${baseline_metrics["pnl"]:.0f} exp/w=${baseline_metrics["exp_per_week"]:.2f}')

    # (b) Full-sample excl_all_negative (oracle, forward-looking)
    neg_coins_full = identify_negative_coins(baseline_trades)
    oracle_tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in neg_coins_full],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in neg_coins_full],
    }
    print(f'\n  [oracle_excl_all_neg] Full-sample exclusion ({len(neg_coins_full)} coins)...')
    oracle_result = run_full_evaluation_for_rolling(
        'oracle_excl_all_neg', data, oracle_tier_coins, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        stress_tier1_fee, stress_tier2_fee, total_bars,
    )

    # ══════════════════════════════════════════════════════════════
    # STEP 2: Rolling lookback simulations
    # ══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 2: Rolling lookback simulations')
    print('=' * 70)

    rolling_results = []
    exclusion_modes = ['all_negative', 'worst_12']

    for lookback in LOOKBACK_WINDOWS:
        for excl_mode in exclusion_modes:
            label = f'rolling_lb{lookback}_seg{SEGMENT_SIZE}_{excl_mode}'
            print(f'\n--- {label} ---')
            result = run_rolling_simulation(
                data, tier_coins_full, tier_indicators_full,
                market_context, tier1_fee, tier2_fee,
                lookback_bars=lookback,
                segment_size=SEGMENT_SIZE,
                exclusion_mode=excl_mode,
                label=label,
            )
            if result is not None:
                rolling_results.append(result)

    # Also run no-exclusion baseline over the same forward segments as the
    # largest lookback window (for fair comparison)
    max_lookback = max(LOOKBACK_WINDOWS)
    first_seg_start = max(WARMUP_BARS, WARMUP_BARS + max_lookback)
    print(f'\n--- baseline_no_excl (same segments as lb={max_lookback}) ---')
    no_excl_trades, no_excl_metrics = run_no_exclusion_baseline(
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        first_seg_start=first_seg_start,
        total_bars=total_bars,
        segment_size=SEGMENT_SIZE,
    )
    print(f'    TOTAL: {no_excl_metrics["trades"]} trades, PF={no_excl_metrics["pf"]:.3f}, '
          f'P&L=${no_excl_metrics["pnl"]:.0f}, exp/w=${no_excl_metrics["exp_per_week"]:.2f}')

    # Also run per-lookback-window no-exclusion for each unique first_seg_start
    no_excl_baselines = {}
    for lookback in LOOKBACK_WINDOWS:
        fs = max(WARMUP_BARS, WARMUP_BARS + lookback)
        if fs not in no_excl_baselines:
            _, nm = run_no_exclusion_baseline(
                data, tier_coins_full, tier_indicators_full,
                market_context, tier1_fee, tier2_fee,
                first_seg_start=fs, total_bars=total_bars,
                segment_size=SEGMENT_SIZE,
            )
            no_excl_baselines[fs] = nm

    # ══════════════════════════════════════════════════════════════
    # STEP 3: Compare rolling vs oracle vs no-exclusion
    # ══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 3: Comparison')
    print('=' * 70)

    print(f'\n  {"Variant":<45s} | {"Trades":>6s} | {"PF":>6s} | {"P&L":>8s} | '
          f'{"Exp/Wk":>8s} | {"DD%":>5s} | {"Overlap":>7s} | {"Persist":>7s}')
    print(f'  {"-"*45}-+-{"-"*6}-+-{"-"*6}-+-{"-"*8}-+-{"-"*8}-+-{"-"*5}-+-{"-"*7}-+-{"-"*7}')

    # Full-sample baseline
    print(f'  {"baseline_316_full_sample":<45s} | '
          f'{baseline_metrics["trades"]:>6d} | {baseline_metrics["pf"]:>6.3f} | '
          f'${baseline_metrics["pnl"]:>+7.0f} | ${baseline_metrics["exp_per_week"]:>7.2f} | '
          f'{baseline_metrics["max_dd_pct"]:>4.1f}% | {"N/A":>7s} | {"N/A":>7s}')

    # Oracle
    om = oracle_result['metrics']
    print(f'  {"oracle_excl_all_neg (forward-looking)":<45s} | '
          f'{om["trades"]:>6d} | {om["pf"]:>6.3f} | '
          f'${om["pnl"]:>+7.0f} | ${om["exp_per_week"]:>7.2f} | '
          f'{om["max_dd_pct"]:>4.1f}% | {"N/A":>7s} | {"N/A":>7s}')

    # Rolling variants
    for r in rolling_results:
        m = r['metrics']
        stab = r['stability']
        print(f'  {r["label"]:<45s} | '
              f'{m["trades"]:>6d} | {m["pf"]:>6.3f} | '
              f'${m["pnl"]:>+7.0f} | ${m["exp_per_week"]:>7.2f} | '
              f'{m["max_dd_pct"]:>4.1f}% | {stab["avg_overlap_pct"]:>5.1f}% | '
              f'{r["n_persistent"]:>7d}')

    # ══════════════════════════════════════════════════════════════
    # STEP 4: Gate evaluation for best rolling variant
    # ══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 4: Gate evaluation for best rolling variant')
    print('=' * 70)

    # Pick best rolling by PF (among profitable ones)
    profitable_rolling = [r for r in rolling_results if r['metrics']['pnl'] > 0]
    if profitable_rolling:
        best_rolling = max(profitable_rolling, key=lambda r: r['metrics']['pf'])
    elif rolling_results:
        best_rolling = max(rolling_results, key=lambda r: r['metrics']['pnl'])
    else:
        best_rolling = None

    best_gate_eval = None
    if best_rolling:
        # For gate evaluation, use the persistent excludes from best rolling
        persistent_coins = set(best_rolling['persistent_excludes'])
        print(f'\n  Best rolling: {best_rolling["label"]}')
        print(f'  Using {len(persistent_coins)} persistently excluded coins for gate eval')
        if persistent_coins:
            print(f'  Persistent excludes: {sorted(persistent_coins)}')

        persist_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in persistent_coins],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in persistent_coins],
        }
        best_gate_eval = run_full_evaluation_for_rolling(
            f'rolling_persistent_excl ({len(persistent_coins)} coins)',
            data, persist_tier_coins, tier_indicators_full,
            market_context, tier1_fee, tier2_fee,
            stress_tier1_fee, stress_tier2_fee, total_bars,
        )

    elapsed_total = time.time() - t0_total

    # ══════════════════════════════════════════════════════════════
    # BUILD REPORTS
    # ══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 5: Building reports')
    print('=' * 70)

    # Determine overall verdict
    if best_rolling and best_rolling['metrics']['pnl'] > 0:
        oracle_pnl = oracle_result['metrics']['pnl']
        rolling_pnl = best_rolling['metrics']['pnl']
        retention_pct = rolling_pnl / oracle_pnl * 100 if oracle_pnl > 0 else 0
        if retention_pct >= 60:
            verdict = 'ROLLING_VIABLE'
            verdict_detail = (f'Rolling lookback retains {retention_pct:.0f}% of oracle P&L. '
                              f'Production mechanism is viable.')
        elif retention_pct >= 30:
            verdict = 'ROLLING_PARTIAL'
            verdict_detail = (f'Rolling lookback retains {retention_pct:.0f}% of oracle P&L. '
                              f'Some benefit, but the gap to oracle is significant.')
        else:
            verdict = 'ROLLING_MARGINAL'
            verdict_detail = (f'Rolling lookback retains only {retention_pct:.0f}% of oracle P&L. '
                              f'Most exclusion benefit requires forward-looking knowledge.')
    else:
        retention_pct = 0
        verdict = 'ROLLING_NOT_PROFITABLE'
        verdict_detail = 'Rolling lookback exclusion does not produce positive P&L.'

    report = {
        'run_header': {
            'task': 'part2_rolling_exclusion',
            'agent': 'C3-A2',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': BASELINE_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                               'tier2': round(stress_tier2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
            'lookback_windows_tested': LOOKBACK_WINDOWS,
            'segment_size': SEGMENT_SIZE,
            'exclusion_modes': exclusion_modes,
        },
        'reference_baselines': {
            'no_exclusion': {
                'metrics': baseline_metrics,
                'n_coins': n_t1 + n_t2,
            },
            'oracle_excl_all_neg': {
                'n_excluded': len(neg_coins_full),
                'excluded_coins': sorted(neg_coins_full),
                'metrics': oracle_result['metrics'],
                'gate_evaluation': oracle_result['gate_evaluation'],
            },
        },
        'rolling_results': rolling_results,
        'best_rolling': {
            'label': best_rolling['label'] if best_rolling else None,
            'metrics': best_rolling['metrics'] if best_rolling else None,
            'persistent_excludes': best_rolling['persistent_excludes'] if best_rolling else [],
            'n_persistent': best_rolling['n_persistent'] if best_rolling else 0,
            'stability': best_rolling['stability'] if best_rolling else None,
            'coin_exclusion_frequency': best_rolling['coin_exclusion_frequency'] if best_rolling else {},
        },
        'gate_evaluation_persistent': best_gate_eval if best_gate_eval else None,
        'verdict': {
            'result': verdict,
            'detail': verdict_detail,
            'oracle_pnl': oracle_result['metrics']['pnl'],
            'best_rolling_pnl': best_rolling['metrics']['pnl'] if best_rolling else 0,
            'retention_pct': round(retention_pct, 1),
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_rolling_exclusion_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'[Report] JSON: {json_path}')

    # ── BUILD MARKDOWN REPORT ──
    md = []
    md.append('# Part 2 -- Rolling Lookback Exclusion Simulation (Agent C3-A2)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={BASELINE_PARAMS["dev_thresh"]}, tp={BASELINE_PARAMS["tp_pct"]}, '
              f'sl={BASELINE_PARAMS["sl_pct"]}, tl={BASELINE_PARAMS["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    md.append('## Objective')
    md.append('')
    md.append('The `excl_all_negative` approach uses full in-sample knowledge (oracle) to exclude ')
    md.append('21 net-negative coins, achieving 7/7 gates. In production, we cannot see the future. ')
    md.append('This test simulates a **rolling lookback window** mechanism:')
    md.append('')
    md.append('1. For each weekly segment, look back N bars')
    md.append('2. Run backtest on lookback window, identify net-negative coins')
    md.append('3. Exclude those coins from the current segment')
    md.append('4. Aggregate all segment results')
    md.append('')
    md.append(f'**Lookback windows tested**: {", ".join(f"{lb} bars ({lb/BARS_PER_WEEK:.0f}wk)" for lb in LOOKBACK_WINDOWS)}')
    md.append(f'**Segment size**: {SEGMENT_SIZE} bars ({SEGMENT_SIZE/BARS_PER_WEEK:.0f} week)')
    md.append(f'**Exclusion modes**: all_negative, worst-12')
    md.append('')

    md.append('## 1. Reference Baselines')
    md.append('')
    md.append('| Variant | Trades | PF | P&L | Exp/Wk | DD% | Gates |')
    md.append('|---------|--------|----|-----|--------|-----|-------|')
    bm = baseline_metrics
    md.append(f'| No exclusion (316 coins) | {bm["trades"]} | {bm["pf"]:.3f} | '
              f'${bm["pnl"]:.0f} | ${bm["exp_per_week"]:.2f} | {bm["max_dd_pct"]:.1f}% | '
              f'{oracle_result.get("gate_evaluation", {}).get("score", "?")} (oracle) |')
    om = oracle_result['metrics']
    og = oracle_result['gate_evaluation']
    md.append(f'| Oracle excl_all_neg ({len(neg_coins_full)} excl) | {om["trades"]} | {om["pf"]:.3f} | '
              f'${om["pnl"]:.0f} | ${om["exp_per_week"]:.2f} | {om["max_dd_pct"]:.1f}% | '
              f'{og["score"]} |')
    md.append('')

    md.append('## 2. Rolling Lookback Results')
    md.append('')
    md.append('| Variant | Lookback | Excl Mode | Segs | Trades | PF | P&L | Exp/Wk | DD% | Overlap% | Persist |')
    md.append('|---------|----------|-----------|------|--------|----|-----|--------|-----|----------|---------|')
    for r in rolling_results:
        m = r['metrics']
        s = r['stability']
        md.append(f'| {r["label"]} | {r["lookback_weeks"]}wk | {r["exclusion_mode"]} | '
                  f'{r["n_segments"]} | {m["trades"]} | {m["pf"]:.3f} | ${m["pnl"]:.0f} | '
                  f'${m["exp_per_week"]:.2f} | {m["max_dd_pct"]:.1f}% | {s["avg_overlap_pct"]:.0f}% | '
                  f'{r["n_persistent"]} |')
    md.append('')

    # Delta vs no-exclusion
    md.append('### Rolling vs No-Exclusion Delta')
    md.append('')
    md.append('| Variant | Rolling P&L | No-Excl P&L | Delta | PF Gain |')
    md.append('|---------|------------|-------------|-------|---------|')
    for r in rolling_results:
        m = r['metrics']
        # Find matching no-excl baseline
        fs = max(WARMUP_BARS, WARMUP_BARS + r['lookback_bars'])
        no_excl_m = no_excl_baselines.get(fs, no_excl_metrics)
        pnl_delta = m['pnl'] - no_excl_m['pnl']
        pf_delta = m['pf'] - no_excl_m['pf']
        md.append(f'| {r["label"]} | ${m["pnl"]:.0f} | ${no_excl_m["pnl"]:.0f} | '
                  f'${pnl_delta:+.0f} | {pf_delta:+.3f} |')
    md.append('')

    md.append('## 3. Exclusion List Stability')
    md.append('')
    md.append('How stable is the exclusion list between consecutive weekly segments?')
    md.append('High overlap = consistent signal. Low overlap = noisy/unstable.')
    md.append('')
    for r in rolling_results:
        s = r['stability']
        md.append(f'**{r["label"]}**: avg overlap={s["avg_overlap_pct"]:.1f}%, '
                  f'min={s["min_overlap_pct"]:.0f}%, max={s["max_overlap_pct"]:.0f}%')
        md.append('')

    md.append('### Persistent Excludes (excluded in >50% of segments)')
    md.append('')
    if best_rolling and best_rolling['persistent_excludes']:
        md.append(f'**Best variant ({best_rolling["label"]})**: '
                  f'{len(best_rolling["persistent_excludes"])} coins')
        md.append('')
        md.append('| Coin | Exclusion Freq (%) |')
        md.append('|------|--------------------|')
        freq = best_rolling['coin_exclusion_frequency']
        for coin in best_rolling['persistent_excludes']:
            md.append(f'| {coin} | {freq.get(coin, 0):.0f}% |')
        md.append('')
    else:
        md.append('No persistent excludes found.')
        md.append('')

    # Gate evaluation for persistent excludes
    if best_gate_eval:
        md.append('## 4. Gate Evaluation (Persistent Excludes)')
        md.append('')
        md.append(f'Using the {best_rolling["n_persistent"]} persistently excluded coins from '
                  f'the best rolling variant as a **static exclusion list**.')
        md.append('')
        ge = best_gate_eval['gate_evaluation']
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')
        md.append(f'**Gate score: {ge["score"]}**')
        md.append('')
        bm2 = best_gate_eval['metrics']
        md.append(f'Metrics: trades={bm2["trades"]}, PF={bm2["pf"]:.3f}, '
                  f'P&L=${bm2["pnl"]:.0f}, exp/wk=${bm2["exp_per_week"]:.2f}, '
                  f'DD={bm2["max_dd_pct"]:.1f}%')
        md.append('')

    md.append('## 5. Verdict')
    md.append('')
    md.append(f'### **{verdict}**')
    md.append('')
    md.append(f'{verdict_detail}')
    md.append('')
    md.append(f'- Oracle (full-sample) P&L: ${oracle_result["metrics"]["pnl"]:.0f}')
    if best_rolling:
        md.append(f'- Best rolling P&L: ${best_rolling["metrics"]["pnl"]:.0f}')
    md.append(f'- Retention: {retention_pct:.0f}%')
    md.append(f'- Baseline (no excl) P&L: ${baseline_metrics["pnl"]:.0f}')
    md.append('')

    md.append('### Production Recommendation')
    md.append('')
    if verdict in ('ROLLING_VIABLE', 'ROLLING_PARTIAL') and best_rolling:
        md.append(f'Use rolling lookback with **{best_rolling["lookback_bars"]} bars '
                  f'({best_rolling["lookback_weeks"]} weeks)**, exclusion mode '
                  f'**{best_rolling["exclusion_mode"]}**.')
        md.append('')
        md.append('Implementation:')
        md.append(f'1. Every {SEGMENT_SIZE/BARS_PER_DAY:.0f} days (1 segment), '
                  f'look back {best_rolling["lookback_bars"]/BARS_PER_DAY:.0f} days')
        md.append('2. Run backtest on lookback window, identify net-negative coins')
        md.append('3. Exclude those coins from the next trading segment')
        md.append('4. Re-evaluate exclusion list at next segment boundary')
        if best_rolling['persistent_excludes']:
            md.append('')
            md.append(f'Alternatively, use the **static persistent exclusion list** '
                      f'({best_rolling["n_persistent"]} coins) as a simpler baseline, '
                      f'and add rolling refinement on top.')
    elif verdict == 'ROLLING_MARGINAL':
        md.append('Rolling exclusion provides marginal benefit. Consider:')
        md.append('- Using only the persistent excludes as a static list')
        md.append('- Exploring other exclusion criteria (e.g., volume-based, volatility-based)')
        md.append('- Accepting the baseline performance without exclusion')
    else:
        md.append('Rolling exclusion is not profitable. The in-sample exclusion benefit ')
        md.append('appears to be largely forward-looking bias. Proceed without coin exclusion ')
        md.append('or investigate alternative filtering approaches.')

    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_rolling_exclusion.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_rolling_exclusion_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Rolling Lookback Exclusion Simulation')
    print(f'  Verdict: {verdict}')
    print(f'  Oracle P&L: ${oracle_result["metrics"]["pnl"]:.0f}')
    if best_rolling:
        print(f'  Best rolling: {best_rolling["label"]} -> P&L=${best_rolling["metrics"]["pnl"]:.0f}')
    print(f'  Retention: {retention_pct:.0f}%')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
