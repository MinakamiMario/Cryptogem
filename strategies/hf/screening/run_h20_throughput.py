#!/usr/bin/env python3
"""
H20 VWAP_DEVIATION Throughput Analysis (Part 2)
================================================
Analyzes trade flow, capacity, and consistency for v5 baseline.

Key questions answered:
  - How many trades per week does the strategy generate?
  - Are trades evenly distributed or bunched?
  - What is the longest drought between trades?
  - How does max_pos=2/3 change capacity?
  - How much capital utilization does the strategy achieve?

Usage:
    python -m strategies.hf.screening.run_h20_throughput          # Full run
    python -m strategies.hf.screening.run_h20_throughput --dry-run # Preview only
    python -m strategies.hf.screening.run_h20_throughput --require-data  # CI mode
"""
import sys
import json
import math
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter

# Ensure project root on path
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168   # 24 * 7
BARS_PER_DAY = 24

# MEXC Market fees (per-side) -- fallback if v2 cost model unavailable
MEXC_MARKET_T1 = 0.0005   # 5 bps
MEXC_MARKET_T2 = 0.0020   # 20 bps

# Try v2 cost model for canonical fees
try:
    from strategies.hf.screening.costs_mexc_v2 import get_harness_fee
    MEXC_MARKET_T1 = get_harness_fee('mexc_market', 'tier1')
    MEXC_MARKET_T2 = get_harness_fee('mexc_market', 'tier2')
except ImportError:
    pass  # use hardcoded fallback above

# v5 baseline parameters
BASELINE_PARAMS = {
    'dev_thresh': 2.0,
    'tp_pct': 8,
    'sl_pct': 5,
    'time_limit': 10,
}

MAX_POS_VALUES = [1, 2, 3]


# ============================================================
# Data Loading (self-contained, from robustness runner pattern)
# ============================================================

def load_candle_cache(timeframe='1h', require_data=False):
    """Load candle cache: try merged file first, fall back to per-coin parts."""
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if cache_path.exists():
        print(f'[Load] Reading {cache_path.name}...')
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        print(f'[Load] {len(coins_data)} coins loaded (merged cache)')
        return coins_data

    # Fall back to per-coin part files
    parts_base = ROOT / 'data' / 'cache_parts_hf' / timeframe
    if not parts_base.exists():
        if require_data:
            print(f'[ERROR] No cache found: neither {cache_path} nor {parts_base}')
            sys.exit(1)
        print('[SKIP] No 1H candle cache found. Run data fetch first.')
        return None

    print(f'[Load] Merged cache not found, loading from per-coin parts...')
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
            print('[ERROR] No coins loaded from part files.')
            sys.exit(1)
        print('[SKIP] No coins loaded from part files. Run data fetch first.')
        return None

    print(f'[Load] {len(coins_data)} coins loaded (from part files)')
    return coins_data


def load_universe_tiering():
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        print(f'[ERROR] Tiering not found: {tiering_path}')
        sys.exit(1)
    with open(tiering_path) as f:
        return json.load(f)


def build_tier_coins(tiering, available_coins):
    tier_coins = {'tier1': [], 'tier2': []}
    tb = tiering.get('tier_breakdown', {})
    if tb:
        for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
            if tier_num in tb:
                coins = tb[tier_num].get('coins', [])
                tier_coins[tier_key] = [c for c in coins if c in available_coins]
        if tier_coins['tier1'] or tier_coins['tier2']:
            return tier_coins

    tiers = tiering.get('tiers', {})
    for tier_key_name in ['tier_1', 'Tier 1 (Liquid)', 'tier1', '1']:
        if tier_key_name in tiers:
            coins = tiers[tier_key_name].get('coins', [])
            tier_coins['tier1'] = [c for c in coins if c in available_coins]
            break
    for tier_key_name in ['tier_2', 'Tier 2 (Mid)', 'tier2', '2']:
        if tier_key_name in tiers:
            coins = tiers[tier_key_name].get('coins', [])
            tier_coins['tier2'] = [c for c in coins if c in available_coins]
            break
    return tier_coins


def estimate_total_bars(tier_indicators, tier_coins):
    """Estimate total bars from indicator data."""
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            ind = indicators.get(coin, {})
            n = ind.get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ============================================================
# Throughput Analysis
# ============================================================

def analyze_throughput(trades, total_bars):
    """Compute throughput metrics from trade list.

    Returns dict with trade flow, gap analysis, and consistency metrics.
    """
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0

    if n_trades == 0:
        return {
            'trades_total': 0, 'trades_per_week': 0.0,
            'trades_t1': 0, 'trades_t2': 0,
            'max_gap_bars': total_bars, 'max_gap_days': total_bars / BARS_PER_DAY,
            'median_gap_bars': 0, 'mean_gap_bars': 0,
            'rolling_4w_mean': 0.0, 'rolling_4w_std': 0.0, 'rolling_4w_cv': 0.0,
            'utilization_pct': 0.0, 'total_weeks': round(total_weeks, 2),
        }

    # --- Tier breakdown ---
    trades_t1 = sum(1 for t in trades if t.get('_tier') == 'tier1')
    trades_t2 = sum(1 for t in trades if t.get('_tier') == 'tier2')

    # --- Gap analysis (entry_bar sorted) ---
    entry_bars = sorted(t['entry_bar'] for t in trades)
    gaps = [entry_bars[i + 1] - entry_bars[i] for i in range(len(entry_bars) - 1)]

    if gaps:
        max_gap = max(gaps)
        median_gap = sorted(gaps)[len(gaps) // 2]
        mean_gap = sum(gaps) / len(gaps)
    else:
        max_gap = 0
        median_gap = 0
        mean_gap = 0

    # --- Rolling 4-week trade counts ---
    window_bars = 4 * BARS_PER_WEEK  # 672 bars
    n_windows = max(1, (total_bars - window_bars) // BARS_PER_WEEK + 1)
    rolling_counts = []
    for w in range(n_windows):
        w_start = w * BARS_PER_WEEK
        w_end = w_start + window_bars
        count = sum(1 for eb in entry_bars if w_start <= eb < w_end)
        rolling_counts.append(count)

    r_mean = sum(rolling_counts) / len(rolling_counts) if rolling_counts else 0.0
    r_var = sum((c - r_mean) ** 2 for c in rolling_counts) / len(rolling_counts) if rolling_counts else 0.0
    r_std = math.sqrt(r_var)
    r_cv = r_std / r_mean if r_mean > 0 else 0.0

    # --- Utilization: fraction of bars with an open position ---
    bars_with_position = set()
    for t in trades:
        for b in range(t['entry_bar'], t.get('exit_bar', t['entry_bar'] + 1)):
            bars_with_position.add(b)
    utilization = len(bars_with_position) / total_bars * 100 if total_bars > 0 else 0.0

    return {
        'trades_total': n_trades,
        'trades_per_week': round(n_trades / total_weeks, 2),
        'trades_t1': trades_t1,
        'trades_t2': trades_t2,
        'max_gap_bars': max_gap,
        'max_gap_days': round(max_gap / BARS_PER_DAY, 2),
        'median_gap_bars': median_gap,
        'mean_gap_bars': round(mean_gap, 1),
        'rolling_4w_mean': round(r_mean, 2),
        'rolling_4w_std': round(r_std, 2),
        'rolling_4w_cv': round(r_cv, 3),
        'utilization_pct': round(utilization, 2),
        'total_weeks': round(total_weeks, 2),
    }


def analyze_trade_clustering(trades, total_bars):
    """Analyze trade clustering: which bars/weeks have the most entries."""
    if not trades:
        return {'weekly_distribution': [], 'busiest_week': None, 'empty_weeks': 0}

    entry_bars = [t['entry_bar'] for t in trades]
    total_weeks = max(1, total_bars // BARS_PER_WEEK)

    # Trades per week bucket
    week_counts = Counter()
    for eb in entry_bars:
        week_idx = eb // BARS_PER_WEEK
        week_counts[week_idx] += 1

    weekly_dist = [week_counts.get(w, 0) for w in range(total_weeks)]
    empty_weeks = sum(1 for c in weekly_dist if c == 0)
    busiest_week = max(weekly_dist) if weekly_dist else 0

    return {
        'weekly_distribution': weekly_dist,
        'busiest_week_trades': busiest_week,
        'empty_weeks': empty_weeks,
        'total_weeks_in_data': total_weeks,
        'weeks_with_trades': total_weeks - empty_weeks,
        'pct_weeks_active': round((total_weeks - empty_weeks) / total_weeks * 100, 1)
            if total_weeks > 0 else 0.0,
    }


def analyze_time_of_week(trades, data):
    """Analyze which hours/days see the most signals (if timestamps available)."""
    if not trades:
        return {'available': False}

    # Try to extract hour-of-week from first trade's candle data
    sample_pair = trades[0].get('pair', '')
    candles = data.get(sample_pair, [])
    has_timestamps = (
        candles and len(candles) > 0
        and isinstance(candles[0], (list, dict))
    )

    # Attempt to get bar timestamps
    hour_counts = Counter()
    dow_counts = Counter()
    mapped = 0

    for t in trades:
        pair = t.get('pair', '')
        bar_idx = t.get('entry_bar', 0)
        pair_candles = data.get(pair, [])
        if bar_idx < len(pair_candles):
            candle = pair_candles[bar_idx]
            ts = None
            if isinstance(candle, dict):
                ts = candle.get('time') or candle.get('timestamp') or candle.get('t')
            elif isinstance(candle, (list, tuple)) and len(candle) > 0:
                ts = candle[0]
            if ts is not None:
                try:
                    dt = datetime.utcfromtimestamp(float(ts))
                    hour_counts[dt.hour] += 1
                    dow_counts[dt.strftime('%A')] += 1
                    mapped += 1
                except (ValueError, TypeError, OSError):
                    pass

    if mapped == 0:
        return {'available': False, 'reason': 'No parseable timestamps in candle data'}

    return {
        'available': True,
        'mapped_trades': mapped,
        'hour_distribution': dict(sorted(hour_counts.items())),
        'day_of_week_distribution': dict(dow_counts.most_common()),
        'peak_hour': hour_counts.most_common(1)[0] if hour_counts else None,
        'peak_day': dow_counts.most_common(1)[0] if dow_counts else None,
    }


# ============================================================
# Capacity Analysis (multi max_pos)
# ============================================================

def run_h20_variant(params, data, tier_coins, tier_indicators,
                    market_context, tier1_fee, tier2_fee, max_pos=1):
    """Run one H20 variant across both tiers, return combined trade list."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}
    signal_fn = signal_h20_vwap_deviation

    all_trades = []
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=enriched_params,
            indicators=indicators,
            fee=fee,
            max_pos=max_pos,
        )

        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    return all_trades


def compute_basic_metrics(trades, total_bars):
    """Compute PnL, PF, WR from trade list."""
    n = len(trades)
    if n == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0}
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    wr = len(wins) / n * 100

    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    exp_per_week = (total_pnl / n) * (n / total_weeks) if n > 0 else 0.0

    return {
        'trades': n,
        'pnl': round(total_pnl, 2),
        'pf': round(pf, 3),
        'wr': round(wr, 1),
        'exp_per_week': round(exp_per_week, 2),
    }


def analyze_capacity(data, tier_coins, tier_indicators, market_context,
                     tier1_fee, tier2_fee, total_bars):
    """Run backtest at different max_pos values to measure capacity."""
    results = {}
    for mp in MAX_POS_VALUES:
        trades = run_h20_variant(
            params=BASELINE_PARAMS,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee,
            tier2_fee=tier2_fee,
            max_pos=mp,
        )
        metrics = compute_basic_metrics(trades, total_bars)
        throughput = analyze_throughput(trades, total_bars)

        results[f'max_pos_{mp}'] = {
            **metrics,
            'utilization_pct': throughput['utilization_pct'],
            'trades_per_week': throughput['trades_per_week'],
        }

    # Compute missed signals (delta between max_pos levels)
    if 'max_pos_1' in results and 'max_pos_2' in results:
        results['missed_at_mp1_vs_mp2'] = (
            results['max_pos_2']['trades'] - results['max_pos_1']['trades']
        )
    if 'max_pos_2' in results and 'max_pos_3' in results:
        results['missed_at_mp2_vs_mp3'] = (
            results['max_pos_3']['trades'] - results['max_pos_2']['trades']
        )

    return results


# ============================================================
# Report Generation
# ============================================================

def build_json_report(throughput, clustering, capacity, time_dist,
                      total_bars, total_weeks, n_t1, n_t2, commit, elapsed):
    """Build the full JSON report dict."""
    return {
        'run_header': {
            'task': 'h20_throughput_analysis',
            'status': 'DONE',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(MEXC_MARKET_T1 * 10000, 1),
                         'tier2': round(MEXC_MARKET_T2 * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runner': 'strategies/hf/screening/run_h20_throughput.py',
            'command': 'python -m strategies.hf.screening.run_h20_throughput',
            'runtime_s': round(elapsed, 1),
        },
        'throughput': throughput,
        'clustering': {k: v for k, v in clustering.items()
                       if k != 'weekly_distribution'},
        'weekly_trade_counts': clustering.get('weekly_distribution', []),
        'capacity': capacity,
        'time_of_week': time_dist,
    }


def build_md_report(throughput, clustering, capacity, time_dist,
                    total_bars, total_weeks, n_t1, n_t2, commit, elapsed):
    """Build Markdown report string."""
    md = []
    md.append('# H20 VWAP_DEVIATION Throughput Analysis')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2})')
    md.append(f'**Timeframe**: 1H ({total_bars} bars, {total_weeks:.1f} weeks)')
    md.append(f'**Cost Regime**: MEXC Market '
              f'(T1={MEXC_MARKET_T1*10000:.0f}bps, T2={MEXC_MARKET_T2*10000:.0f}bps)')
    md.append(f'**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # --- Trade flow ---
    md.append('## Trade Flow')
    md.append('')
    md.append(f'| Metric | Value |')
    md.append(f'|--------|-------|')
    md.append(f'| Total trades | {throughput["trades_total"]} |')
    md.append(f'| Trades/week | {throughput["trades_per_week"]} |')
    md.append(f'| T1 trades | {throughput["trades_t1"]} |')
    md.append(f'| T2 trades | {throughput["trades_t2"]} |')
    md.append(f'| Utilization | {throughput["utilization_pct"]}% |')
    md.append('')

    # --- Gap analysis ---
    md.append('## Gap Analysis')
    md.append('')
    md.append(f'| Metric | Value |')
    md.append(f'|--------|-------|')
    md.append(f'| Max gap (bars) | {throughput["max_gap_bars"]} |')
    md.append(f'| Max gap (days) | {throughput["max_gap_days"]} |')
    md.append(f'| Median gap (bars) | {throughput["median_gap_bars"]} |')
    md.append(f'| Mean gap (bars) | {throughput["mean_gap_bars"]} |')
    md.append('')

    # --- Consistency ---
    md.append('## Rolling 4-Week Consistency')
    md.append('')
    md.append(f'| Metric | Value |')
    md.append(f'|--------|-------|')
    md.append(f'| Mean trades/4wk | {throughput["rolling_4w_mean"]} |')
    md.append(f'| Std trades/4wk | {throughput["rolling_4w_std"]} |')
    md.append(f'| CV (std/mean) | {throughput["rolling_4w_cv"]} |')
    cv = throughput["rolling_4w_cv"]
    verdict = "CONSISTENT" if cv < 0.5 else ("MODERATE" if cv < 1.0 else "ERRATIC")
    md.append(f'| Verdict | {verdict} (<0.5=consistent, <1.0=moderate) |')
    md.append('')

    # --- Clustering ---
    md.append('## Trade Clustering')
    md.append('')
    md.append(f'| Metric | Value |')
    md.append(f'|--------|-------|')
    md.append(f'| Weeks with trades | '
              f'{clustering["weeks_with_trades"]}/{clustering["total_weeks_in_data"]} |')
    md.append(f'| Empty weeks | {clustering["empty_weeks"]} |')
    md.append(f'| % weeks active | {clustering["pct_weeks_active"]}% |')
    md.append(f'| Busiest week | {clustering["busiest_week_trades"]} trades |')
    md.append('')

    # --- Capacity ---
    md.append('## Capacity Analysis (max_pos comparison)')
    md.append('')
    md.append('| max_pos | Trades | PnL | PF | WR% | Exp/Wk | Util% |')
    md.append('|---------|--------|-----|----|-----|--------|-------|')
    for mp in MAX_POS_VALUES:
        key = f'max_pos_{mp}'
        if key in capacity:
            c = capacity[key]
            md.append(f'| {mp} | {c["trades"]} | ${c["pnl"]:.0f} '
                      f'| {c["pf"]:.3f} | {c["wr"]:.1f} '
                      f'| ${c["exp_per_week"]:.2f} | {c["utilization_pct"]:.1f} |')
    md.append('')

    missed_1v2 = capacity.get('missed_at_mp1_vs_mp2', 0)
    missed_2v3 = capacity.get('missed_at_mp2_vs_mp3', 0)
    md.append(f'- Signals missed at max_pos=1 (vs 2): **{missed_1v2}**')
    md.append(f'- Signals missed at max_pos=2 (vs 3): **{missed_2v3}**')
    md.append('')

    # --- Time distribution ---
    md.append('## Time-of-Week Distribution')
    md.append('')
    if time_dist.get('available'):
        peak_hour = time_dist.get('peak_hour')
        peak_day = time_dist.get('peak_day')
        md.append(f'- Mapped trades: {time_dist["mapped_trades"]}')
        if peak_hour:
            md.append(f'- Peak hour: {peak_hour[0]:02d}:00 UTC ({peak_hour[1]} trades)')
        if peak_day:
            md.append(f'- Peak day: {peak_day[0]} ({peak_day[1]} trades)')
        md.append('')
        if 'hour_distribution' in time_dist:
            md.append('**Hourly distribution:**')
            md.append('')
            md.append('| Hour | Trades |')
            md.append('|------|--------|')
            for h, c in sorted(time_dist['hour_distribution'].items()):
                md.append(f'| {int(h):02d}:00 | {c} |')
            md.append('')
    else:
        reason = time_dist.get('reason', 'No timestamps available')
        md.append(f'*{reason}*')
        md.append('')

    # --- Footer ---
    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_h20_throughput.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='H20 VWAP_DEVIATION Throughput Analysis')
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data, print stats, skip backtest')
    parser.add_argument('--require-data', action='store_true',
                        help='Exit with code 1 if cache missing (CI mode)')
    args = parser.parse_args()

    print('=' * 70)
    print('  H20 VWAP_DEVIATION Throughput Analysis')
    print('  Cost Regime: MEXC Market '
          f'(T1={MEXC_MARKET_T1*10000:.0f}bps, T2={MEXC_MARKET_T2*10000:.0f}bps)')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Git commit ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)

    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    tier_coins = build_tier_coins(tiering, available_coins)

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    # --- Precompute base indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    # --- Extend indicators (H20 needs VWAP) ---
    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # --- Precompute market context ---
    print('[Market Context] Precomputing...')
    all_coins = list(set(
        c for coins in tier_coins.values() for c in coins
    ))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into each coin's indicators dict
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    if args.dry_run:
        print('\n[DRY RUN] Data loaded successfully. Skipping backtest.')
        print(f'  T1 coins: {n_t1}, T2 coins: {n_t2}')
        print(f'  Total bars: {total_bars}, Total weeks: {total_weeks:.1f}')
        print(f'  MEXC T1 fee: {MEXC_MARKET_T1*10000:.1f}bps, '
              f'T2 fee: {MEXC_MARKET_T2*10000:.1f}bps')
        sys.exit(0)

    # ==========================================================
    # 1. Baseline throughput (max_pos=1)
    # ==========================================================

    print('\n--- Baseline Throughput (max_pos=1) ---')
    baseline_trades = run_h20_variant(
        params=BASELINE_PARAMS,
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=MEXC_MARKET_T1,
        tier2_fee=MEXC_MARKET_T2,
        max_pos=1,
    )

    throughput = analyze_throughput(baseline_trades, total_bars)
    clustering = analyze_trade_clustering(baseline_trades, total_bars)

    print(f'  Trades: {throughput["trades_total"]}')
    print(f'  Trades/week: {throughput["trades_per_week"]}')
    print(f'  T1: {throughput["trades_t1"]}, T2: {throughput["trades_t2"]}')
    print(f'  Max gap: {throughput["max_gap_bars"]} bars '
          f'({throughput["max_gap_days"]} days)')
    print(f'  Rolling 4wk CV: {throughput["rolling_4w_cv"]} '
          f'(mean={throughput["rolling_4w_mean"]}, std={throughput["rolling_4w_std"]})')
    print(f'  Utilization: {throughput["utilization_pct"]}%')
    print(f'  Active weeks: {clustering["weeks_with_trades"]}'
          f'/{clustering["total_weeks_in_data"]} '
          f'({clustering["pct_weeks_active"]}%)')

    # ==========================================================
    # 2. Capacity analysis (max_pos=1,2,3)
    # ==========================================================

    print('\n--- Capacity Analysis (max_pos=1/2/3) ---')
    capacity = analyze_capacity(
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=MEXC_MARKET_T1,
        tier2_fee=MEXC_MARKET_T2,
        total_bars=total_bars,
    )

    for mp in MAX_POS_VALUES:
        key = f'max_pos_{mp}'
        if key in capacity:
            c = capacity[key]
            print(f'  max_pos={mp}: {c["trades"]} trades, '
                  f'PF={c["pf"]:.3f}, ${c["pnl"]:.0f}, '
                  f'util={c["utilization_pct"]:.1f}%')

    missed_1v2 = capacity.get('missed_at_mp1_vs_mp2', 0)
    missed_2v3 = capacity.get('missed_at_mp2_vs_mp3', 0)
    print(f'  Missed at mp=1 vs 2: {missed_1v2}')
    print(f'  Missed at mp=2 vs 3: {missed_2v3}')

    # ==========================================================
    # 3. Time-of-week distribution
    # ==========================================================

    print('\n--- Time-of-Week Distribution ---')
    time_dist = analyze_time_of_week(baseline_trades, data)
    if time_dist.get('available'):
        peak_hour = time_dist.get('peak_hour')
        peak_day = time_dist.get('peak_day')
        if peak_hour:
            print(f'  Peak hour: {peak_hour[0]:02d}:00 UTC ({peak_hour[1]} trades)')
        if peak_day:
            print(f'  Peak day: {peak_day[0]} ({peak_day[1]} trades)')
    else:
        print(f'  {time_dist.get("reason", "No timestamps available")}')

    elapsed = time.time() - t0

    # ==========================================================
    # Write Reports
    # ==========================================================

    json_report = build_json_report(
        throughput, clustering, capacity, time_dist,
        total_bars, total_weeks, n_t1, n_t2, commit, elapsed,
    )

    json_path = ROOT / 'reports' / 'hf' / 'h20_throughput_002.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(json_report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md_text = build_md_report(
        throughput, clustering, capacity, time_dist,
        total_bars, total_weeks, n_t1, n_t2, commit, elapsed,
    )

    md_path = ROOT / 'reports' / 'hf' / 'h20_throughput_002.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    # --- Summary ---
    print(f'\n{"=" * 70}')
    print(f'  THROUGHPUT ANALYSIS COMPLETE')
    print(f'  Trades: {throughput["trades_total"]} '
          f'({throughput["trades_per_week"]}/week)')
    print(f'  Max gap: {throughput["max_gap_days"]} days')
    cv = throughput["rolling_4w_cv"]
    verdict = "CONSISTENT" if cv < 0.5 else ("MODERATE" if cv < 1.0 else "ERRATIC")
    print(f'  Consistency: CV={cv:.3f} ({verdict})')
    print(f'  Capacity headroom (mp1->2): +{missed_1v2} trades')
    print(f'  Runtime: {elapsed:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
