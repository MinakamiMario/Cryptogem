#!/usr/bin/env python3
"""
Part 2 -- Agent C5-A4: Drawdown Duration Analysis
===================================================
Analyzes drawdown duration, consecutive losses, and inter-trade gaps
for the three production configs:

  1. v5 (sl=5) on 295 coins  -- leader
  2. sl=7 on 295 coins        -- robustness alternative
  3. v5 (sl=5) on 304 coins   -- conservative alternative

Metrics computed per config:
  A. Equity curve & drawdown series (peak-to-trough-to-recovery)
  B. Drawdown duration (trades and days)
  C. Consecutive loss analysis
  D. Inter-trade gap analysis
  E. Cross-config comparison table

Output:
  reports/hf/part2_dd_duration_001.json
  reports/hf/part2_dd_duration_001.md

Usage:
    python -m strategies.hf.screening.run_part2_dd_duration
    python -m strategies.hf.screening.run_part2_dd_duration --dry-run
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

# ---- Config definitions ----

# v5 baseline (leader)
PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# sl=7 variant (robustness alternative)
PARAMS_SL7 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10,
}

# 21 net-negative coins (excl_all_negative -> 295 coins)
EXCLUDED_ALL_NEGATIVE = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# 12 worst coins (excl_worst12 -> 304 coins)
EXCLUDED_WORST12 = {
    'ALKIMI/USD', 'ANIME/USD', 'DBR/USD', 'ESX/USD', 'HOUSE/USD',
    'KET/USD', 'LMWR/USD', 'MXC/USD', 'ODOS/USD', 'PERP/USD',
    'TANSSI/USD', 'TITCOIN/USD',
}


# ---- Data loading (same pattern as other part2 scripts) ----

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


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ---- Backtest runner ----

def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params, max_pos=1):
    """Run backtest across tiers, return merged trade list."""
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
            params=signal_params, indicators=indicators, fee=fee,
            max_pos=max_pos,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


# ---- Drawdown Duration Analysis ----

def analyze_drawdown_duration(trades, initial_equity=2000.0):
    """
    Compute detailed drawdown duration metrics from a trade list.

    Returns a dict with:
      - equity_curve: list of {trade_idx, entry_bar, exit_bar, pnl, equity, peak, dd_pct, underwater_trades, underwater_hours}
      - dd_episodes: list of peak-to-recovery episodes
      - duration_metrics: summary statistics
    """
    if not trades:
        return {
            'equity_curve': [],
            'dd_episodes': [],
            'duration_metrics': {
                'max_dd_duration_trades': 0,
                'max_dd_duration_hours': 0,
                'max_dd_duration_days': 0.0,
                'avg_dd_duration_trades': 0.0,
                'avg_dd_duration_days': 0.0,
                'n_dd_episodes': 0,
                'recovery_from_max_dd_trades': 0,
                'recovery_from_max_dd_days': 0.0,
                'max_dd_pct': 0.0,
                'max_dd_pct_trade_idx': 0,
            },
        }

    sorted_trades = sorted(trades, key=lambda x: x.get('entry_bar', 0))

    # Build equity curve
    equity = initial_equity
    peak = equity
    peak_trade_idx = -1  # index in sorted list where peak was set
    peak_bar = 0         # bar number where peak was set

    equity_curve = []
    for i, t in enumerate(sorted_trades):
        equity += t['pnl']
        if equity >= peak:
            peak = equity
            peak_trade_idx = i
            peak_bar = t.get('exit_bar', t.get('entry_bar', 0))
        dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
        # How many trades since last peak
        underwater_trades = i - peak_trade_idx if dd_pct > 0 else 0
        # How many hours since last peak exit bar
        current_bar = t.get('exit_bar', t.get('entry_bar', 0))
        underwater_hours = (current_bar - peak_bar) if dd_pct > 0 else 0

        equity_curve.append({
            'trade_idx': i,
            'pair': t.get('pair', ''),
            'entry_bar': t.get('entry_bar', 0),
            'exit_bar': t.get('exit_bar', 0),
            'pnl': round(t['pnl'], 2),
            'reason': t.get('reason', ''),
            'equity': round(equity, 2),
            'peak': round(peak, 2),
            'dd_pct': round(dd_pct, 2),
            'underwater_trades': underwater_trades,
            'underwater_hours': underwater_hours,
        })

    # Identify drawdown episodes (peak-to-recovery cycles)
    dd_episodes = []
    equity = initial_equity
    peak = equity
    peak_idx = -1
    peak_bar = 0
    in_drawdown = False
    episode_start_idx = None
    episode_start_bar = None
    episode_max_dd_pct = 0.0
    episode_max_dd_idx = None

    for i, t in enumerate(sorted_trades):
        equity += t['pnl']
        exit_bar = t.get('exit_bar', t.get('entry_bar', 0))

        if equity >= peak:
            # Recovery or new peak
            if in_drawdown:
                # Episode ends: recovered
                dd_episodes.append({
                    'start_trade_idx': episode_start_idx,
                    'end_trade_idx': i,
                    'start_bar': episode_start_bar,
                    'end_bar': exit_bar,
                    'duration_trades': i - episode_start_idx,
                    'duration_hours': exit_bar - episode_start_bar,
                    'duration_days': round((exit_bar - episode_start_bar) / BARS_PER_DAY, 2),
                    'max_dd_pct': round(episode_max_dd_pct, 2),
                    'max_dd_trade_idx': episode_max_dd_idx,
                    'recovered': True,
                })
                in_drawdown = False
            peak = equity
            peak_idx = i
            peak_bar = exit_bar
        else:
            dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if not in_drawdown:
                # New drawdown episode starts
                in_drawdown = True
                episode_start_idx = peak_idx + 1
                episode_start_bar = peak_bar
                episode_max_dd_pct = dd_pct
                episode_max_dd_idx = i
            if dd_pct > episode_max_dd_pct:
                episode_max_dd_pct = dd_pct
                episode_max_dd_idx = i

    # Handle open drawdown at end of data
    if in_drawdown:
        last_exit_bar = sorted_trades[-1].get('exit_bar', sorted_trades[-1].get('entry_bar', 0))
        dd_episodes.append({
            'start_trade_idx': episode_start_idx,
            'end_trade_idx': len(sorted_trades) - 1,
            'start_bar': episode_start_bar,
            'end_bar': last_exit_bar,
            'duration_trades': len(sorted_trades) - 1 - episode_start_idx + 1,
            'duration_hours': last_exit_bar - episode_start_bar,
            'duration_days': round((last_exit_bar - episode_start_bar) / BARS_PER_DAY, 2),
            'max_dd_pct': round(episode_max_dd_pct, 2),
            'max_dd_trade_idx': episode_max_dd_idx,
            'recovered': False,
        })

    # Summary metrics
    if dd_episodes:
        max_ep = max(dd_episodes, key=lambda e: e['duration_trades'])
        max_dd_ep = max(dd_episodes, key=lambda e: e['max_dd_pct'])
        avg_dur_trades = sum(e['duration_trades'] for e in dd_episodes) / len(dd_episodes)
        avg_dur_days = sum(e['duration_days'] for e in dd_episodes) / len(dd_episodes)

        # Recovery from max DD: find the episode containing max DD
        recovery_trades = 0
        recovery_days = 0.0
        if max_dd_ep['recovered']:
            recovery_trades = max_dd_ep['end_trade_idx'] - max_dd_ep['max_dd_trade_idx']
            recovery_hours = max_dd_ep['end_bar'] - equity_curve[max_dd_ep['max_dd_trade_idx']]['exit_bar']
            recovery_days = recovery_hours / BARS_PER_DAY
        else:
            recovery_trades = -1  # not recovered
            recovery_days = -1.0
    else:
        max_ep = {'duration_trades': 0, 'duration_hours': 0, 'duration_days': 0.0}
        max_dd_ep = {'max_dd_pct': 0.0, 'max_dd_trade_idx': 0}
        avg_dur_trades = 0.0
        avg_dur_days = 0.0
        recovery_trades = 0
        recovery_days = 0.0

    duration_metrics = {
        'max_dd_duration_trades': max_ep['duration_trades'],
        'max_dd_duration_hours': max_ep.get('duration_hours', 0),
        'max_dd_duration_days': round(max_ep['duration_days'], 2),
        'avg_dd_duration_trades': round(avg_dur_trades, 2),
        'avg_dd_duration_days': round(avg_dur_days, 2),
        'n_dd_episodes': len(dd_episodes),
        'n_recovered': sum(1 for e in dd_episodes if e['recovered']),
        'n_unrecovered': sum(1 for e in dd_episodes if not e['recovered']),
        'recovery_from_max_dd_trades': recovery_trades,
        'recovery_from_max_dd_days': round(recovery_days, 2),
        'max_dd_pct': round(max_dd_ep['max_dd_pct'], 2) if dd_episodes else 0.0,
        'max_dd_pct_trade_idx': max_dd_ep.get('max_dd_trade_idx', 0) if dd_episodes else 0,
        'longest_dd_episode_pct': round(max_ep.get('max_dd_pct', 0), 2) if dd_episodes else 0.0,
    }

    return {
        'equity_curve': equity_curve,
        'dd_episodes': dd_episodes,
        'duration_metrics': duration_metrics,
    }


def analyze_consecutive_losses(trades):
    """Analyze consecutive losing trade streaks."""
    if not trades:
        return {
            'max_consecutive_losses': 0,
            'avg_consecutive_losses': 0.0,
            'losing_streaks': [],
            'longest_streak_pnl': 0.0,
            'streak_distribution': {},
        }

    sorted_trades = sorted(trades, key=lambda x: x.get('entry_bar', 0))

    streaks = []
    current_streak = 0
    current_streak_pnl = 0.0
    current_streak_start = None

    for i, t in enumerate(sorted_trades):
        if t['pnl'] <= 0:
            if current_streak == 0:
                current_streak_start = i
            current_streak += 1
            current_streak_pnl += t['pnl']
        else:
            if current_streak > 0:
                streaks.append({
                    'length': current_streak,
                    'pnl': round(current_streak_pnl, 2),
                    'start_idx': current_streak_start,
                    'end_idx': i - 1,
                    'start_bar': sorted_trades[current_streak_start].get('entry_bar', 0),
                    'end_bar': sorted_trades[i - 1].get('exit_bar', 0),
                })
            current_streak = 0
            current_streak_pnl = 0.0

    # Handle trailing streak
    if current_streak > 0:
        streaks.append({
            'length': current_streak,
            'pnl': round(current_streak_pnl, 2),
            'start_idx': current_streak_start,
            'end_idx': len(sorted_trades) - 1,
            'start_bar': sorted_trades[current_streak_start].get('entry_bar', 0),
            'end_bar': sorted_trades[-1].get('exit_bar', 0),
        })

    max_consec = max((s['length'] for s in streaks), default=0)
    avg_consec = sum(s['length'] for s in streaks) / len(streaks) if streaks else 0.0
    longest_streak = max(streaks, key=lambda s: s['length']) if streaks else None
    longest_pnl = longest_streak['pnl'] if longest_streak else 0.0

    # Distribution
    dist = defaultdict(int)
    for s in streaks:
        dist[s['length']] += 1

    return {
        'max_consecutive_losses': max_consec,
        'avg_consecutive_losses': round(avg_consec, 2),
        'n_losing_streaks': len(streaks),
        'losing_streaks': streaks,
        'longest_streak_pnl': longest_pnl,
        'streak_distribution': dict(sorted(dist.items())),
    }


def analyze_inter_trade_gaps(trades, total_bars=721):
    """Analyze gaps between consecutive trades."""
    if len(trades) < 2:
        return {
            'max_gap_bars': 0,
            'max_gap_hours': 0,
            'max_gap_days': 0.0,
            'avg_gap_bars': 0.0,
            'avg_gap_hours': 0.0,
            'avg_gap_days': 0.0,
            'median_gap_bars': 0,
            'gap_details': [],
            'gap_distribution': {},
        }

    sorted_trades = sorted(trades, key=lambda x: x.get('entry_bar', 0))

    gaps = []
    for i in range(1, len(sorted_trades)):
        prev_entry = sorted_trades[i - 1].get('entry_bar', 0)
        curr_entry = sorted_trades[i].get('entry_bar', 0)
        gap_bars = curr_entry - prev_entry
        gaps.append({
            'from_trade_idx': i - 1,
            'to_trade_idx': i,
            'from_pair': sorted_trades[i - 1].get('pair', ''),
            'to_pair': sorted_trades[i].get('pair', ''),
            'from_entry_bar': prev_entry,
            'to_entry_bar': curr_entry,
            'gap_bars': gap_bars,
            'gap_hours': gap_bars,  # 1 bar = 1 hour
            'gap_days': round(gap_bars / BARS_PER_DAY, 2),
        })

    gap_bars_list = [g['gap_bars'] for g in gaps]
    gap_bars_list_sorted = sorted(gap_bars_list)
    n = len(gap_bars_list_sorted)
    median_gap = gap_bars_list_sorted[n // 2] if n > 0 else 0

    max_gap = max(gap_bars_list) if gap_bars_list else 0
    avg_gap = sum(gap_bars_list) / n if n > 0 else 0.0

    # Distribution buckets (in hours)
    buckets = {'0-6h': 0, '6-12h': 0, '12-24h': 0, '24-48h': 0, '48h+': 0}
    for g in gap_bars_list:
        if g <= 6:
            buckets['0-6h'] += 1
        elif g <= 12:
            buckets['6-12h'] += 1
        elif g <= 24:
            buckets['12-24h'] += 1
        elif g <= 48:
            buckets['24-48h'] += 1
        else:
            buckets['48h+'] += 1

    # Find largest gap and its location (fold approximation)
    max_gap_detail = max(gaps, key=lambda g: g['gap_bars']) if gaps else None
    if max_gap_detail:
        bar_mid = (max_gap_detail['from_entry_bar'] + max_gap_detail['to_entry_bar']) / 2
        fold_approx = int(bar_mid / (total_bars / 5)) if total_bars > 0 else 0
        max_gap_detail['approx_fold'] = min(fold_approx, 4)

    return {
        'max_gap_bars': max_gap,
        'max_gap_hours': max_gap,
        'max_gap_days': round(max_gap / BARS_PER_DAY, 2),
        'avg_gap_bars': round(avg_gap, 1),
        'avg_gap_hours': round(avg_gap, 1),
        'avg_gap_days': round(avg_gap / BARS_PER_DAY, 2),
        'median_gap_bars': median_gap,
        'median_gap_days': round(median_gap / BARS_PER_DAY, 2),
        'n_gaps': n,
        'gap_distribution': buckets,
        'max_gap_detail': {
            'from_pair': max_gap_detail['from_pair'],
            'to_pair': max_gap_detail['to_pair'],
            'from_bar': max_gap_detail['from_entry_bar'],
            'to_bar': max_gap_detail['to_entry_bar'],
            'gap_bars': max_gap_detail['gap_bars'],
            'gap_days': max_gap_detail['gap_days'],
            'approx_fold': max_gap_detail.get('approx_fold', 0),
        } if max_gap_detail else None,
        'top5_gaps': sorted(gaps, key=lambda g: g['gap_bars'], reverse=True)[:5],
    }


def compute_basic_metrics(trades, total_bars):
    """Compute basic backtest metrics for context."""
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
                'trades_per_week': 0.0, 'exp_per_week': 0.0, 'max_dd_pct': 0.0}
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
    return {
        'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 2), 'max_dd_pct': round(max_dd, 1),
    }


# ---- Full analysis per config ----

def run_config_analysis(label, data, tier_coins, tier_indicators,
                        market_context, tier1_fee, tier2_fee,
                        params, total_bars):
    """Run backtest and compute all drawdown/duration metrics for one config."""
    t0 = time.time()
    print(f'\n  [{label}] Running backtest...')
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, params=params, max_pos=1)
    basic = compute_basic_metrics(trades, total_bars)
    print(f'    trades={basic["trades"]} PF={basic["pf"]:.3f} '
          f'WR={basic["wr"]:.1f}% exp/w=${basic["exp_per_week"]:.2f} '
          f'DD={basic["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Analyzing drawdown duration...')
    dd_analysis = analyze_drawdown_duration(trades)

    print(f'  [{label}] Analyzing consecutive losses...')
    consec_analysis = analyze_consecutive_losses(trades)

    print(f'  [{label}] Analyzing inter-trade gaps...')
    gap_analysis = analyze_inter_trade_gaps(trades, total_bars)

    elapsed = time.time() - t0
    dm = dd_analysis['duration_metrics']
    print(f'    DD episodes: {dm["n_dd_episodes"]} '
          f'| Max duration: {dm["max_dd_duration_trades"]} trades '
          f'({dm["max_dd_duration_days"]:.1f}d) '
          f'| Max consec losses: {consec_analysis["max_consecutive_losses"]} '
          f'| Max gap: {gap_analysis["max_gap_days"]:.2f}d')
    print(f'    Done in {elapsed:.1f}s')

    return {
        'label': label,
        'params': params,
        'n_coins': sum(len(c) for c in tier_coins.values()),
        'basic_metrics': basic,
        'drawdown_duration': {
            'duration_metrics': dm,
            'dd_episodes': dd_analysis['dd_episodes'],
            'equity_curve_summary': {
                'n_points': len(dd_analysis['equity_curve']),
                'final_equity': dd_analysis['equity_curve'][-1]['equity'] if dd_analysis['equity_curve'] else 2000.0,
                'max_dd_pct': dm['max_dd_pct'],
                'min_equity': min((p['equity'] for p in dd_analysis['equity_curve']), default=2000.0),
                'max_equity': max((p['equity'] for p in dd_analysis['equity_curve']), default=2000.0),
            },
        },
        'consecutive_losses': {
            'max_consecutive_losses': consec_analysis['max_consecutive_losses'],
            'avg_consecutive_losses': consec_analysis['avg_consecutive_losses'],
            'n_losing_streaks': consec_analysis['n_losing_streaks'],
            'longest_streak_pnl': consec_analysis['longest_streak_pnl'],
            'streak_distribution': consec_analysis['streak_distribution'],
            'losing_streaks': consec_analysis['losing_streaks'],
        },
        'inter_trade_gaps': {
            'max_gap_bars': gap_analysis['max_gap_bars'],
            'max_gap_days': gap_analysis['max_gap_days'],
            'avg_gap_bars': gap_analysis['avg_gap_bars'],
            'avg_gap_days': gap_analysis['avg_gap_days'],
            'median_gap_bars': gap_analysis['median_gap_bars'],
            'median_gap_days': gap_analysis['median_gap_days'],
            'n_gaps': gap_analysis['n_gaps'],
            'gap_distribution': gap_analysis['gap_distribution'],
            'max_gap_detail': gap_analysis['max_gap_detail'],
            'top5_gaps': [
                {'from_pair': g['from_pair'], 'to_pair': g['to_pair'],
                 'gap_bars': g['gap_bars'], 'gap_days': g['gap_days']}
                for g in gap_analysis.get('top5_gaps', [])
            ],
        },
        'runtime_s': round(elapsed, 1),
    }


# ---- Markdown report generation ----

def build_md_report(results, commit, elapsed_total, tier1_fee, tier2_fee, total_bars):
    md = []
    md.append('# Part 2 -- Drawdown Duration Analysis (Agent C5-A4)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Data**: {total_bars} bars ({total_bars / BARS_PER_WEEK:.1f} weeks) of 1H candles')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps (MEXC market)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')
    md.append('## Question')
    md.append('')
    md.append('How long do drawdown periods last? What is the max time underwater?')
    md.append('How does this compare across the three production configs?')
    md.append('')

    # ---- Section 1: Cross-Config Comparison ----
    md.append('## 1. Cross-Config Comparison')
    md.append('')
    md.append('### 1a. Basic Metrics')
    md.append('')
    md.append('| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |')
    md.append('|--------|---------------|------------|---------------|')

    r = {res['label']: res for res in results}
    labels = ['v5_sl5_295', 'sl7_295', 'v5_sl5_304']
    for metric_name, key, fmt, higher_better in [
        ('Trades', 'trades', '{}', True),
        ('P&L', 'pnl', '${:.0f}', True),
        ('PF', 'pf', '{:.3f}', True),
        ('WR%', 'wr', '{:.1f}%', True),
        ('Trades/wk', 'trades_per_week', '{:.2f}', True),
        ('Exp/wk', 'exp_per_week', '${:.2f}', True),
        ('Max DD%', 'max_dd_pct', '{:.1f}%', False),
    ]:
        vals = [r[l]['basic_metrics'][key] for l in labels]
        cells = [fmt.format(v) for v in vals]
        # Bold the best
        if higher_better:
            best_idx = vals.index(max(vals))
        else:
            best_idx = vals.index(min(vals))
        cells[best_idx] = f'**{cells[best_idx]}**'
        md.append(f'| {metric_name} | {cells[0]} | {cells[1]} | {cells[2]} |')
    md.append('')

    md.append('### 1b. Drawdown Duration Comparison')
    md.append('')
    md.append('| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |')
    md.append('|--------|---------------|------------|---------------|')

    for metric_name, key, fmt, higher_better in [
        ('DD episodes', 'n_dd_episodes', '{}', False),
        ('Max DD duration (trades)', 'max_dd_duration_trades', '{}', False),
        ('Max DD duration (days)', 'max_dd_duration_days', '{:.2f}', False),
        ('Avg DD duration (trades)', 'avg_dd_duration_trades', '{:.2f}', False),
        ('Avg DD duration (days)', 'avg_dd_duration_days', '{:.2f}', False),
        ('Recovered episodes', 'n_recovered', '{}', True),
        ('Unrecovered episodes', 'n_unrecovered', '{}', False),
        ('Recovery from max DD (trades)', 'recovery_from_max_dd_trades', '{}', False),
        ('Recovery from max DD (days)', 'recovery_from_max_dd_days', '{:.2f}', False),
        ('Deepest DD%', 'max_dd_pct', '{:.2f}%', False),
        ('Longest episode DD%', 'longest_dd_episode_pct', '{:.2f}%', False),
    ]:
        vals = [r[l]['drawdown_duration']['duration_metrics'][key] for l in labels]
        cells = [fmt.format(v) for v in vals]
        # For "recovery" with -1 (not recovered), mark it
        for ci in range(len(cells)):
            if vals[ci] == -1:
                cells[ci] = 'N/R'
        # Bold the best (excluding -1 values)
        valid_vals = [(v, i) for i, v in enumerate(vals) if v >= 0]
        if valid_vals:
            if higher_better:
                best_idx = max(valid_vals, key=lambda x: x[0])[1]
            else:
                best_idx = min(valid_vals, key=lambda x: x[0])[1]
            cells[best_idx] = f'**{cells[best_idx]}**'
        md.append(f'| {metric_name} | {cells[0]} | {cells[1]} | {cells[2]} |')
    md.append('')

    md.append('### 1c. Consecutive Loss Comparison')
    md.append('')
    md.append('| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |')
    md.append('|--------|---------------|------------|---------------|')

    for metric_name, key, fmt, higher_better in [
        ('Max consec losses', 'max_consecutive_losses', '{}', False),
        ('Avg consec losses', 'avg_consecutive_losses', '{:.2f}', False),
        ('Losing streaks count', 'n_losing_streaks', '{}', False),
        ('Longest streak P&L', 'longest_streak_pnl', '${:.0f}', True),
    ]:
        vals = [r[l]['consecutive_losses'][key] for l in labels]
        cells = [fmt.format(v) for v in vals]
        if higher_better:
            best_idx = vals.index(max(vals))
        else:
            best_idx = vals.index(min(vals))
        cells[best_idx] = f'**{cells[best_idx]}**'
        md.append(f'| {metric_name} | {cells[0]} | {cells[1]} | {cells[2]} |')
    md.append('')

    md.append('### 1d. Inter-Trade Gap Comparison')
    md.append('')
    md.append('| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |')
    md.append('|--------|---------------|------------|---------------|')

    for metric_name, key, fmt, higher_better in [
        ('Max gap (days)', 'max_gap_days', '{:.2f}d', False),
        ('Avg gap (days)', 'avg_gap_days', '{:.2f}d', False),
        ('Median gap (days)', 'median_gap_days', '{:.2f}d', False),
        ('Max gap (bars/hours)', 'max_gap_bars', '{}h', False),
        ('Avg gap (bars/hours)', 'avg_gap_bars', '{:.1f}h', False),
    ]:
        vals = [r[l]['inter_trade_gaps'][key] for l in labels]
        cells = [fmt.format(v) for v in vals]
        if higher_better:
            best_idx = vals.index(max(vals))
        else:
            best_idx = vals.index(min(vals))
        cells[best_idx] = f'**{cells[best_idx]}**'
        md.append(f'| {metric_name} | {cells[0]} | {cells[1]} | {cells[2]} |')
    md.append('')

    # Gap distribution
    md.append('**Gap Distribution (entry-to-entry):**')
    md.append('')
    md.append('| Bucket | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |')
    md.append('|--------|---------------|------------|---------------|')
    for bucket in ['0-6h', '6-12h', '12-24h', '24-48h', '48h+']:
        vals = [r[l]['inter_trade_gaps']['gap_distribution'].get(bucket, 0) for l in labels]
        md.append(f'| {bucket} | {vals[0]} | {vals[1]} | {vals[2]} |')
    md.append('')

    # ---- Section 2: Per-Config Detail ----
    for res in results:
        label = res['label']
        dm = res['drawdown_duration']['duration_metrics']
        cl = res['consecutive_losses']
        ig = res['inter_trade_gaps']
        bm = res['basic_metrics']

        nice_label = {
            'v5_sl5_295': 'v5 (sl=5) on 295 coins -- LEADER',
            'sl7_295': 'sl=7 on 295 coins -- Robustness Alt',
            'v5_sl5_304': 'v5 (sl=5) on 304 coins -- Conservative Alt',
        }.get(label, label)

        md.append(f'## 2. Detail: {nice_label}')
        md.append('')
        md.append(f'**Params**: {res["params"]}')
        md.append(f'**Universe**: {res["n_coins"]} coins')
        md.append(f'**Trades**: {bm["trades"]} | PF={bm["pf"]:.3f} | '
                  f'WR={bm["wr"]:.1f}% | P&L=${bm["pnl"]:.0f}')
        md.append('')

        # DD episodes table
        episodes = res['drawdown_duration']['dd_episodes']
        if episodes:
            md.append(f'### Drawdown Episodes ({len(episodes)} total)')
            md.append('')
            md.append('| # | Start Bar | End Bar | Duration (trades) | Duration (days) | Max DD% | Recovered |')
            md.append('|---|-----------|---------|-------------------|-----------------|---------|-----------|')
            for ei, ep in enumerate(episodes):
                rec_str = 'YES' if ep['recovered'] else 'NO'
                md.append(f'| {ei+1} | {ep["start_bar"]} | {ep["end_bar"]} | '
                          f'{ep["duration_trades"]} | {ep["duration_days"]:.2f} | '
                          f'{ep["max_dd_pct"]:.2f}% | {rec_str} |')
            md.append('')

        # Consecutive losses
        md.append(f'### Consecutive Loss Streaks')
        md.append('')
        md.append(f'- Max consecutive losses: **{cl["max_consecutive_losses"]}**')
        md.append(f'- Avg consecutive losses: {cl["avg_consecutive_losses"]:.2f}')
        md.append(f'- Number of losing streaks: {cl["n_losing_streaks"]}')
        md.append(f'- Longest streak P&L impact: ${cl["longest_streak_pnl"]:.0f}')
        md.append('')

        # Streak distribution
        if cl['streak_distribution']:
            md.append('**Streak length distribution:**')
            md.append('')
            md.append('| Streak Length | Count |')
            md.append('|--------------|-------|')
            for length, count in sorted(cl['streak_distribution'].items()):
                md.append(f'| {length} | {count} |')
            md.append('')

        # Individual losing streaks
        if cl['losing_streaks']:
            md.append('**All losing streaks:**')
            md.append('')
            md.append('| # | Length | P&L | Start Bar | End Bar |')
            md.append('|---|--------|-----|-----------|---------|')
            for si, s in enumerate(sorted(cl['losing_streaks'], key=lambda x: x['length'], reverse=True)):
                md.append(f'| {si+1} | {s["length"]} | ${s["pnl"]:.0f} | {s["start_bar"]} | {s["end_bar"]} |')
            md.append('')

        # Inter-trade gaps: top 5
        md.append(f'### Top 5 Largest Inter-Trade Gaps')
        md.append('')
        if ig.get('top5_gaps'):
            md.append('| # | From | To | Gap (h) | Gap (d) |')
            md.append('|---|------|----|---------|---------|')
            for gi, g in enumerate(ig['top5_gaps'][:5]):
                md.append(f'| {gi+1} | {g["from_pair"]} | {g["to_pair"]} | '
                          f'{g["gap_bars"]}h | {g["gap_days"]:.2f}d |')
            md.append('')

        # Max gap detail
        mgd = ig.get('max_gap_detail')
        if mgd:
            md.append(f'**Largest gap**: {mgd["gap_bars"]}h ({mgd["gap_days"]:.2f}d) '
                      f'between {mgd["from_pair"]} and {mgd["to_pair"]}, '
                      f'bars {mgd["from_bar"]}-{mgd["to_bar"]} '
                      f'(approx fold {mgd["approx_fold"]})')
            md.append('')

    # ---- Section 3: Insights ----
    md.append('## 3. Key Insights')
    md.append('')

    # Auto-generate insights from data
    leader = r['v5_sl5_295']
    sl7 = r['sl7_295']
    c304 = r['v5_sl5_304']

    ldm = leader['drawdown_duration']['duration_metrics']
    sdm = sl7['drawdown_duration']['duration_metrics']
    cdm = c304['drawdown_duration']['duration_metrics']

    md.append('### Drawdown Duration')
    md.append('')
    md.append(f'1. **Max time underwater**: v5(295)={ldm["max_dd_duration_days"]:.1f}d, '
              f'sl7(295)={sdm["max_dd_duration_days"]:.1f}d, '
              f'v5(304)={cdm["max_dd_duration_days"]:.1f}d')
    md.append(f'2. **Average drawdown duration**: v5(295)={ldm["avg_dd_duration_days"]:.1f}d, '
              f'sl7(295)={sdm["avg_dd_duration_days"]:.1f}d, '
              f'v5(304)={cdm["avg_dd_duration_days"]:.1f}d')
    md.append(f'3. **DD episodes**: v5(295)={ldm["n_dd_episodes"]}, '
              f'sl7(295)={sdm["n_dd_episodes"]}, '
              f'v5(304)={cdm["n_dd_episodes"]}')

    # Which has most recoveries?
    rec_leader = ldm['n_recovered']
    rec_sl7 = sdm['n_recovered']
    rec_304 = cdm['n_recovered']
    md.append(f'4. **Recovered episodes**: v5(295)={rec_leader}/{ldm["n_dd_episodes"]}, '
              f'sl7(295)={rec_sl7}/{sdm["n_dd_episodes"]}, '
              f'v5(304)={rec_304}/{cdm["n_dd_episodes"]}')
    md.append('')

    md.append('### Consecutive Losses')
    md.append('')
    lcl = leader['consecutive_losses']
    scl = sl7['consecutive_losses']
    ccl = c304['consecutive_losses']
    md.append(f'5. **Max consecutive losses**: v5(295)={lcl["max_consecutive_losses"]}, '
              f'sl7(295)={scl["max_consecutive_losses"]}, '
              f'v5(304)={ccl["max_consecutive_losses"]}')
    md.append(f'6. **Longest losing streak P&L**: v5(295)=${lcl["longest_streak_pnl"]:.0f}, '
              f'sl7(295)=${scl["longest_streak_pnl"]:.0f}, '
              f'v5(304)=${ccl["longest_streak_pnl"]:.0f}')
    md.append('')

    md.append('### Inter-Trade Gaps')
    md.append('')
    lig = leader['inter_trade_gaps']
    sig = sl7['inter_trade_gaps']
    cig = c304['inter_trade_gaps']
    md.append(f'7. **Max gap**: v5(295)={lig["max_gap_days"]:.2f}d, '
              f'sl7(295)={sig["max_gap_days"]:.2f}d, '
              f'v5(304)={cig["max_gap_days"]:.2f}d')
    md.append(f'8. **Avg gap**: v5(295)={lig["avg_gap_days"]:.2f}d, '
              f'sl7(295)={sig["avg_gap_days"]:.2f}d, '
              f'v5(304)={cig["avg_gap_days"]:.2f}d')
    md.append('')

    # Overall assessment
    md.append('### Overall Assessment')
    md.append('')

    # Determine which config has best duration profile
    configs_by_max_dd_dur = sorted(
        [(ldm['max_dd_duration_days'], 'v5(295)'),
         (sdm['max_dd_duration_days'], 'sl7(295)'),
         (cdm['max_dd_duration_days'], 'v5(304)')],
        key=lambda x: x[0])
    best_dur = configs_by_max_dd_dur[0]
    worst_dur = configs_by_max_dd_dur[-1]

    md.append(f'- **Best max DD duration**: {best_dur[1]} at {best_dur[0]:.1f} days')
    md.append(f'- **Worst max DD duration**: {worst_dur[1]} at {worst_dur[0]:.1f} days')

    # Practical implications
    total_days = total_bars / BARS_PER_DAY
    pct_underwater = ldm['max_dd_duration_days'] / total_days * 100 if total_days > 0 else 0
    md.append(f'- **Total observation period**: {total_days:.1f} days')
    md.append(f'- **Leader max underwater**: {ldm["max_dd_duration_days"]:.1f}d '
              f'= {pct_underwater:.0f}% of observation period')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_dd_duration.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C5-A4: Drawdown Duration Analysis')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C5-A4: Drawdown Duration Analysis')
    print('  3 production configs: v5(295), sl7(295), v5(304)')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Params] v5: {PARAMS_V5}')
    print(f'[Params] sl7: {PARAMS_SL7}')

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
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_ALL_NEGATIVE],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_ALL_NEGATIVE],
    }
    n_295 = len(tier_coins_295['tier1']) + len(tier_coins_295['tier2'])
    print(f'[Universe] 295-coin: T1={len(tier_coins_295["tier1"])}, '
          f'T2={len(tier_coins_295["tier2"])}, total={n_295}')

    # Build 304-coin universe (exclude 12 worst)
    tier_coins_304 = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_WORST12],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_WORST12],
    }
    n_304 = len(tier_coins_304['tier1']) + len(tier_coins_304['tier2'])
    print(f'[Universe] 304-coin: T1={len(tier_coins_304["tier1"])}, '
          f'T2={len(tier_coins_304["tier2"])}, total={n_304}')

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Config 1: v5 sl=5 on {n_295} coins')
        print(f'  Config 2: sl=7 on {n_295} coins')
        print(f'  Config 3: v5 sl=5 on {n_304} coins')
        print(f'  Analysis: DD duration, consec losses, inter-trade gaps')
        sys.exit(0)

    # Precompute indicators for 295-coin universe
    print('\n[Indicators] Precomputing for 295-coin universe...')
    tier_indicators_295 = {}
    for tier_name, coins in tier_coins_295.items():
        if coins:
            t_ind = time.time()
            tier_indicators_295[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields (295)...')
    for tier_name, coins in tier_coins_295.items():
        if coins and tier_name in tier_indicators_295:
            extend_indicators(data, coins, tier_indicators_295[tier_name])
            cov = get_feature_coverage(tier_indicators_295[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # Precompute indicators for 304-coin universe (add extra 9 coins)
    extra_coins_304 = set()
    for tier_name in ['tier1', 'tier2']:
        for c in tier_coins_304[tier_name]:
            if c not in tier_coins_295.get(tier_name, []):
                extra_coins_304.add((tier_name, c))

    # Build 304 indicators by copying 295 and adding extra coins
    tier_indicators_304 = {}
    for tier_name in ['tier1', 'tier2']:
        if tier_name in tier_indicators_295:
            tier_indicators_304[tier_name] = dict(tier_indicators_295[tier_name])

    extra_by_tier = defaultdict(list)
    for tier_name, coin in extra_coins_304:
        extra_by_tier[tier_name].append(coin)

    if extra_by_tier:
        print(f'[Indicators] Precomputing {sum(len(v) for v in extra_by_tier.values())} extra coins for 304 universe...')
        for tier_name, coins in extra_by_tier.items():
            if coins:
                extra_ind = precompute_base_indicators(data, coins)
                extend_indicators(data, coins, extra_ind)
                if tier_name not in tier_indicators_304:
                    tier_indicators_304[tier_name] = {}
                tier_indicators_304[tier_name].update(extra_ind)

    # Market context (shared -- use 304 superset + BTC)
    print('[Market Context] Precomputing...')
    all_coins_304 = list(set(tier_coins_304.get('tier1', []) + tier_coins_304.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins_304:
            all_coins_304.append(btc)
    market_context = precompute_market_context(data, all_coins_304)
    print('  Done.')

    # Inject __coin__ into indicators
    for ind_dict in [tier_indicators_295, tier_indicators_304]:
        for tier_name, coin_inds in ind_dict.items():
            for coin in coin_inds:
                coin_inds[coin]['__coin__'] = coin

    total_bars_295 = estimate_total_bars(tier_indicators_295, tier_coins_295)
    total_bars_304 = estimate_total_bars(tier_indicators_304, tier_coins_304)
    total_bars = max(total_bars_295, total_bars_304)
    print(f'[Data] total_bars={total_bars} ({total_bars / BARS_PER_WEEK:.1f} weeks)')

    # ===== RUN CONFIG 1: v5 sl=5 on 295 coins (leader) =====
    print('\n' + '=' * 70)
    print('  CONFIG 1: v5 (sl=5) on 295 coins -- LEADER')
    print('=' * 70)
    result_v5_295 = run_config_analysis(
        label='v5_sl5_295', data=data, tier_coins=tier_coins_295,
        tier_indicators=tier_indicators_295, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        params=PARAMS_V5, total_bars=total_bars,
    )

    # ===== RUN CONFIG 2: sl=7 on 295 coins =====
    print('\n' + '=' * 70)
    print('  CONFIG 2: sl=7 on 295 coins -- ROBUSTNESS ALT')
    print('=' * 70)
    result_sl7_295 = run_config_analysis(
        label='sl7_295', data=data, tier_coins=tier_coins_295,
        tier_indicators=tier_indicators_295, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        params=PARAMS_SL7, total_bars=total_bars,
    )

    # ===== RUN CONFIG 3: v5 sl=5 on 304 coins =====
    print('\n' + '=' * 70)
    print('  CONFIG 3: v5 (sl=5) on 304 coins -- CONSERVATIVE ALT')
    print('=' * 70)
    result_v5_304 = run_config_analysis(
        label='v5_sl5_304', data=data, tier_coins=tier_coins_304,
        tier_indicators=tier_indicators_304, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        params=PARAMS_V5, total_bars=total_bars,
    )

    elapsed_total = time.time() - t0_total

    results = [result_v5_295, result_sl7_295, result_v5_304]

    # ===== SUMMARY =====
    print('\n' + '=' * 70)
    print('  CROSS-CONFIG SUMMARY')
    print('=' * 70)
    print(f'{"Config":<20} {"Trades":>6} {"PF":>6} {"DD%":>6} {"MaxDDdur":>10} {"MaxConsec":>9} {"MaxGap":>8}')
    print('-' * 70)
    for res in results:
        bm = res['basic_metrics']
        dm = res['drawdown_duration']['duration_metrics']
        cl = res['consecutive_losses']
        ig = res['inter_trade_gaps']
        print(f'{res["label"]:<20} {bm["trades"]:>6} {bm["pf"]:>6.3f} '
              f'{bm["max_dd_pct"]:>5.1f}% '
              f'{dm["max_dd_duration_days"]:>8.1f}d '
              f'{cl["max_consecutive_losses"]:>9} '
              f'{ig["max_gap_days"]:>6.2f}d')
    print(f'\nTotal runtime: {elapsed_total:.1f}s')

    # ===== SAVE JSON =====
    report = {
        'run_header': {
            'task': 'part2_dd_duration', 'agent': 'C5-A4',
            'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
            'configs_tested': 3,
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1),
                         'tier2': round(tier2_fee * 10000, 1)},
            'universes': {
                '295': f'T1({len(tier_coins_295["tier1"])})+T2({len(tier_coins_295["tier2"])})',
                '304': f'T1({len(tier_coins_304["tier1"])})+T2({len(tier_coins_304["tier2"])})',
            },
            'total_bars': total_bars,
            'total_weeks': round(total_bars / BARS_PER_WEEK, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'results': {res['label']: res for res in results},
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_dd_duration_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ===== SAVE MARKDOWN =====
    md_content = build_md_report(results, commit, elapsed_total,
                                  tier1_fee, tier2_fee, total_bars)
    md_path = ROOT / 'reports' / 'hf' / 'part2_dd_duration_001.md'
    md_path.write_text(md_content)
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Drawdown Duration Analysis')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
