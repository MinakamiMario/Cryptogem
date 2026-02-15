#!/usr/bin/env python3
"""
Part 2 -- Agent C4-A3: Time-of-Day Analysis
============================================
Analyzes whether certain hours of the day produce better/worse signal
performance for the v5 H20 VWAP_DEVIATION strategy.

Approach:
  1. Run full v5 backtest on 295-coin universe (excl_all_negative)
  2. Map each trade to its entry hour (0-23 UTC) via candle timestamp
  3. Compute per-hour metrics: trade count, win rate, avg P&L, total P&L, PF
  4. Identify consistently negative hours
  5. Test "filtered hours" variant that post-filters worst hours
  6. Run gate evaluation on both full and filtered variants

Output:
  reports/hf/part2_time_of_day_001.json
  reports/hf/part2_time_of_day_001.md

Usage:
    python -m strategies.hf.screening.run_part2_time_of_day
    python -m strategies.hf.screening.run_part2_time_of_day --dry-run
    python -m strategies.hf.screening.run_part2_time_of_day --require-data
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BARS_PER_WEEK = 168
BARS_PER_DAY = 24

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}


# ---------------------------------------------------------------------------
# Data loading (reuse patterns from loss_cluster script)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Backtest helpers
# ---------------------------------------------------------------------------
def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None):
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
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    if params is None:
        params = PARAMS_V5
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
    # Max gap
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


# ---------------------------------------------------------------------------
# Time-of-day analysis
# ---------------------------------------------------------------------------
def extract_entry_hour(trade, data):
    """Extract the UTC hour of a trade's entry from candle timestamp."""
    pair = trade.get('pair', '')
    entry_bar = trade.get('entry_bar', 0)
    candles = data.get(pair, [])
    if entry_bar < len(candles):
        candle = candles[entry_bar]
        ts = candle.get('time', 0)
        if ts > 0:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.hour
    return None


def compute_hourly_stats(trades, data):
    """Group trades by entry hour and compute per-hour metrics."""
    hourly = defaultdict(list)
    for t in trades:
        hour = extract_entry_hour(t, data)
        if hour is not None:
            hourly[hour].append(t)

    stats = {}
    for hour in range(24):
        hour_trades = hourly.get(hour, [])
        n = len(hour_trades)
        if n == 0:
            stats[hour] = {
                'hour': hour, 'trades': 0, 'wins': 0, 'wr': 0.0,
                'avg_pnl': 0.0, 'total_pnl': 0.0, 'pf': 0.0,
                'avg_pnl_pct': 0.0,
            }
            continue
        wins = sum(1 for t in hour_trades if t['pnl'] > 0)
        total_pnl = sum(t['pnl'] for t in hour_trades)
        tw = sum(t['pnl'] for t in hour_trades if t['pnl'] > 0)
        tl = abs(sum(t['pnl'] for t in hour_trades if t['pnl'] <= 0))
        pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
        avg_pnl_pct = sum(t.get('pnl_pct', 0) for t in hour_trades) / n

        stats[hour] = {
            'hour': hour,
            'trades': n,
            'wins': wins,
            'wr': round(wins / n * 100, 1),
            'avg_pnl': round(total_pnl / n, 2),
            'total_pnl': round(total_pnl, 2),
            'pf': round(pf, 3) if pf != float('inf') else 999.0,
            'avg_pnl_pct': round(avg_pnl_pct, 2),
        }
    return stats


def identify_worst_hours(hourly_stats, min_trades=2):
    """Identify hours with consistently negative P&L (>= min_trades)."""
    worst = []
    for hour, s in hourly_stats.items():
        if s['trades'] >= min_trades and s['total_pnl'] < 0:
            worst.append(hour)
    return sorted(worst)


def filter_trades_by_hours(trades, excluded_hours, data):
    """Remove trades whose entry hour is in excluded_hours."""
    kept = []
    removed = []
    for t in trades:
        hour = extract_entry_hour(t, data)
        if hour is not None and hour in excluded_hours:
            removed.append(t)
        else:
            kept.append(t)
    return kept, removed


# ---------------------------------------------------------------------------
# Full evaluation helper
# ---------------------------------------------------------------------------
def run_full_gate_eval(label, trades, data, tier_coins, tier_indicators,
                       market_context, tier1_fee, tier2_fee,
                       stress_tier1_fee, stress_tier2_fee, total_bars,
                       excluded_hours=None):
    """Run metrics + stress + WF + gates for a set of trades.

    For the filtered variant, we use post-filtering on the WF fold trades too.
    """
    metrics = compute_metrics(trades, total_bars)

    # Stress test
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    if excluded_hours:
        stress_trades, _ = filter_trades_by_hours(stress_trades, excluded_hours, data)
    stress_metrics = compute_metrics(stress_trades, total_bars)

    # Walk-forward
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5)
    folds_positive = 0
    fold_details = []
    for fold_idx in sorted(fold_trades.keys()):
        ft = fold_trades[fold_idx]
        if excluded_hours:
            ft, _ = filter_trades_by_hours(ft, excluded_hours, data)
        fold_pnl = sum(t['pnl'] for t in ft)
        fold_n = len(ft)
        is_pos = fold_pnl > 0
        if is_pos:
            folds_positive += 1
        fold_details.append({'fold': fold_idx, 'trades': fold_n,
                            'pnl': round(fold_pnl, 2), 'positive': is_pos})
    fold_conc = compute_fold_concentration(
        {fd['fold']: [{'pnl': fd['pnl']}] for fd in fold_details}
    )
    # Recompute fold_conc properly from actual fold P&Ls
    fold_pnls_dict = {}
    for fd in fold_details:
        fold_pnls_dict[fd['fold']] = fd['pnl']
    positive_total = sum(max(0, p) for p in fold_pnls_dict.values())
    if positive_total > 0:
        max_fold_pnl = max(fold_pnls_dict.values())
        top1_fold_conc = max(0, max_fold_pnl) / positive_total * 100
    else:
        top1_fold_conc = 100.0
    fold_conc = {
        'top1_fold_conc_pct': round(top1_fold_conc, 1),
        'fold_pnls': {k: round(v, 2) for k, v in fold_pnls_dict.items()},
    }

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)

    return {
        'label': label,
        'metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'gate_evaluation': gate_eval,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C4-A3: Time-of-Day Analysis',
    )
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Time-of-Day Analysis (Agent C4-A3)')
    print('  Objective: Find hour-of-day patterns in v5 signal performance')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps')

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # --- Apply exclusion (295-coin universe) ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1={n_t1}, T2={n_t2}, total={n_total} (excl {len(EXCLUDED_COINS)} coins)')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins available.')
        sys.exit(1 if args.require_data else 0)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  Params: {PARAMS_V5}')
        print(f'  Will analyze 24 hours (0-23 UTC)')
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # --- Market context ---
    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ============================================================
    # STEP 1: Full baseline backtest
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 1: Full v5 baseline backtest on 295 coins')
    print('=' * 70)

    baseline_trades = run_variant(data, tier_coins, tier_indicators,
                                   market_context, tier1_fee, tier2_fee)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'  Baseline: {baseline_metrics["trades"]} trades, '
          f'PF={baseline_metrics["pf"]:.3f}, P&L=${baseline_metrics["pnl"]:.2f}, '
          f'exp/w=${baseline_metrics["exp_per_week"]:.2f}')

    # ============================================================
    # STEP 2: Per-hour analysis
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 2: Per-hour breakdown (0-23 UTC)')
    print('=' * 70)

    hourly_stats = compute_hourly_stats(baseline_trades, data)

    # Print per-hour table
    print(f'\n  {"Hour":>4s} {"Trades":>6s} {"Wins":>5s} {"WR%":>6s} '
          f'{"AvgP&L":>8s} {"TotP&L":>9s} {"PF":>7s} {"AvgPct":>7s}')
    print(f'  {"----":>4s} {"------":>6s} {"-----":>5s} {"------":>6s} '
          f'{"--------":>8s} {"---------":>9s} {"-------":>7s} {"-------":>7s}')
    for hour in range(24):
        s = hourly_stats[hour]
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        print(f'  {hour:4d} {s["trades"]:6d} {s["wins"]:5d} {s["wr"]:5.1f}% '
              f'{s["avg_pnl"]:+8.2f} {s["total_pnl"]:+9.2f} {pf_str:>7s} '
              f'{s["avg_pnl_pct"]:+6.2f}%')

    # Summary stats
    total_mapped = sum(s['trades'] for s in hourly_stats.values())
    unmapped = len(baseline_trades) - total_mapped
    print(f'\n  Mapped: {total_mapped} trades, Unmapped: {unmapped}')

    # ============================================================
    # STEP 3: Identify worst hours
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 3: Identify worst hours')
    print('=' * 70)

    worst_hours = identify_worst_hours(hourly_stats, min_trades=2)
    print(f'  Hours with negative total P&L (>= 2 trades): {worst_hours}')

    # Also identify hours with WR < 40% and >= 3 trades
    low_wr_hours = [h for h in range(24)
                    if hourly_stats[h]['trades'] >= 3 and hourly_stats[h]['wr'] < 40]
    print(f'  Hours with WR < 40% (>= 3 trades): {low_wr_hours}')

    # Calculate impact of worst hours
    worst_pnl = sum(hourly_stats[h]['total_pnl'] for h in worst_hours)
    worst_trades = sum(hourly_stats[h]['trades'] for h in worst_hours)
    print(f'  Worst hours total: {worst_trades} trades, ${worst_pnl:+.2f} P&L')

    # ============================================================
    # STEP 4: Gate evaluation -- baseline (full)
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 4: Gate evaluation -- full v5 baseline')
    print('=' * 70)

    full_eval = run_full_gate_eval(
        label='v5_full',
        trades=baseline_trades,
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars,
    )
    full_ge = full_eval['gate_evaluation']
    print(f'  Gates: {full_ge["score"]}')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = full_ge['gates'][gid]
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'    {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    # ============================================================
    # STEP 5: Gate evaluation -- filtered (exclude worst hours)
    # ============================================================
    filtered_eval = None
    if worst_hours:
        print('\n' + '=' * 70)
        print(f'  STEP 5: Gate evaluation -- filtered (exclude hours {worst_hours})')
        print('=' * 70)

        filtered_trades, removed_trades = filter_trades_by_hours(
            baseline_trades, set(worst_hours), data)
        print(f'  Kept: {len(filtered_trades)} trades, Removed: {len(removed_trades)} trades')

        filtered_eval = run_full_gate_eval(
            label=f'v5_excl_h{",".join(str(h) for h in worst_hours)}',
            trades=filtered_trades,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
            excluded_hours=set(worst_hours),
        )
        filt_ge = filtered_eval['gate_evaluation']
        print(f'  Gates: {filt_ge["score"]}')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = filt_ge['gates'][gid]
            status = 'PASS' if g['pass'] else 'FAIL'
            print(f'    {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')
    else:
        print('\n  No hours with negative P&L (>= 2 trades) found. Skipping filtered variant.')

    elapsed_total = time.time() - t0_total

    # ============================================================
    # Build JSON report
    # ============================================================
    hourly_list = [hourly_stats[h] for h in range(24)]
    best_hours = sorted(
        [s for s in hourly_list if s['trades'] >= 2],
        key=lambda x: x['total_pnl'], reverse=True
    )[:5]
    worst_hours_detail = sorted(
        [s for s in hourly_list if s['trades'] >= 2],
        key=lambda x: x['total_pnl']
    )[:5]

    report = {
        'run_header': {
            'task': 'part2_time_of_day',
            'agent': 'C4-A3',
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
            'universe_total': n_total,
            'excluded_coins': sorted(EXCLUDED_COINS),
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'baseline_metrics': baseline_metrics,
        'hourly_breakdown': hourly_list,
        'best_hours': best_hours,
        'worst_hours': worst_hours_detail,
        'negative_hours': worst_hours,
        'full_evaluation': full_eval,
        'filtered_evaluation': filtered_eval,
        'verdict': {},
    }

    # Build verdict
    if filtered_eval:
        full_gates = full_eval['gate_evaluation']['pass_count']
        filt_gates = filtered_eval['gate_evaluation']['pass_count']
        full_exp = full_eval['metrics']['exp_per_week']
        filt_exp = filtered_eval['metrics']['exp_per_week']
        full_trades_n = full_eval['metrics']['trades']
        filt_trades_n = filtered_eval['metrics']['trades']

        if filt_gates > full_gates:
            verdict_text = (f'IMPROVEMENT: Filtering hours {worst_hours} improves gate '
                          f'score from {full_gates}/7 to {filt_gates}/7.')
        elif filt_gates == full_gates and filt_exp > full_exp:
            verdict_text = (f'MARGINAL: Same gate score ({full_gates}/7), but exp/wk '
                          f'improves ${full_exp:.2f} -> ${filt_exp:.2f}.')
        elif filt_gates < full_gates:
            verdict_text = (f'REGRESSION: Filtering hours {worst_hours} reduces gate '
                          f'score from {full_gates}/7 to {filt_gates}/7.')
        else:
            verdict_text = (f'NO CHANGE: Filtering hours {worst_hours} has no meaningful impact. '
                          f'Gates {full_gates}/7, exp/wk ${full_exp:.2f} -> ${filt_exp:.2f}.')

        report['verdict'] = {
            'text': verdict_text,
            'filtering_worth_it': filt_gates > full_gates or (filt_gates == full_gates and filt_exp > full_exp * 1.05),
            'full_gates': full_gates,
            'filtered_gates': filt_gates,
            'full_exp_per_week': full_exp,
            'filtered_exp_per_week': filt_exp,
            'trades_removed': full_trades_n - filt_trades_n,
            'pnl_removed': round(sum(hourly_stats[h]['total_pnl'] for h in worst_hours), 2),
        }
    else:
        report['verdict'] = {
            'text': 'No consistently negative hours identified. Time-of-day filtering not applicable.',
            'filtering_worth_it': False,
        }

    json_path = ROOT / 'reports' / 'hf' / 'part2_time_of_day_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # Markdown report
    # ============================================================
    md = []
    md.append('# Part 2 -- Time-of-Day Analysis (Agent C4-A3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins (295-coin universe)')
    md.append(f'**Params**: dev={PARAMS_V5["dev_thresh"]}, tp={PARAMS_V5["tp_pct"]}, '
              f'sl={PARAMS_V5["sl_pct"]}, tl={PARAMS_V5["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Baseline summary
    md.append('## 1. Baseline Summary')
    md.append('')
    md.append(f'- Trades: {baseline_metrics["trades"]}')
    md.append(f'- P&L: ${baseline_metrics["pnl"]:.2f}')
    md.append(f'- PF: {baseline_metrics["pf"]:.3f}')
    md.append(f'- WR: {baseline_metrics["wr"]:.1f}%')
    md.append(f'- Exp/week: ${baseline_metrics["exp_per_week"]:.2f}')
    md.append('')

    # Per-hour breakdown
    md.append('## 2. Per-Hour Breakdown (UTC)')
    md.append('')
    md.append('| Hour | Trades | Wins | WR% | Avg P&L | Total P&L | PF | Avg P&L% |')
    md.append('|------|--------|------|-----|---------|-----------|-----|----------|')
    for hour in range(24):
        s = hourly_stats[hour]
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        marker = ' **' if s['total_pnl'] < 0 and s['trades'] >= 2 else ''
        md.append(f'| {hour:02d}:00 | {s["trades"]} | {s["wins"]} | {s["wr"]:.1f}% '
                  f'| ${s["avg_pnl"]:+.2f} | ${s["total_pnl"]:+.2f}{marker} '
                  f'| {pf_str} | {s["avg_pnl_pct"]:+.2f}% |')
    md.append('')
    md.append('*Rows marked with ** have negative total P&L with >= 2 trades.*')
    md.append('')

    # Distribution summary
    active_hours = [h for h in range(24) if hourly_stats[h]['trades'] > 0]
    inactive_hours = [h for h in range(24) if hourly_stats[h]['trades'] == 0]
    md.append('## 3. Distribution Summary')
    md.append('')
    md.append(f'- Active hours (>= 1 trade): {len(active_hours)} ({", ".join(f"{h:02d}" for h in active_hours)})')
    if inactive_hours:
        md.append(f'- Inactive hours (0 trades): {len(inactive_hours)} ({", ".join(f"{h:02d}" for h in inactive_hours)})')
    md.append(f'- Total trades mapped to hours: {total_mapped}/{len(baseline_trades)}')
    md.append('')

    # Best/worst hours
    md.append('## 4. Best and Worst Hours')
    md.append('')
    md.append('### Top 5 Best Hours (by total P&L)')
    md.append('')
    md.append('| Hour | Trades | WR% | Total P&L | PF |')
    md.append('|------|--------|-----|-----------|-----|')
    for s in best_hours:
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        md.append(f'| {s["hour"]:02d}:00 | {s["trades"]} | {s["wr"]:.1f}% '
                  f'| ${s["total_pnl"]:+.2f} | {pf_str} |')
    md.append('')

    md.append('### Top 5 Worst Hours (by total P&L)')
    md.append('')
    md.append('| Hour | Trades | WR% | Total P&L | PF |')
    md.append('|------|--------|-----|-----------|-----|')
    for s in worst_hours_detail:
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        md.append(f'| {s["hour"]:02d}:00 | {s["trades"]} | {s["wr"]:.1f}% '
                  f'| ${s["total_pnl"]:+.2f} | {pf_str} |')
    md.append('')

    # Negative hours identified
    md.append('## 5. Negative Hours Analysis')
    md.append('')
    if worst_hours:
        md.append(f'**Hours with negative total P&L (>= 2 trades)**: {", ".join(f"{h:02d}:00" for h in worst_hours)}')
        md.append(f'- Combined trades: {worst_trades}')
        md.append(f'- Combined P&L: ${worst_pnl:+.2f}')
        md.append('')
    else:
        md.append('No hours with consistently negative P&L (>= 2 trades) found.')
        md.append('')

    if low_wr_hours:
        md.append(f'**Hours with WR < 40% (>= 3 trades)**: {", ".join(f"{h:02d}:00" for h in low_wr_hours)}')
        md.append('')

    # Gate comparison
    md.append('## 6. Gate Comparison')
    md.append('')
    md.append('### Full Baseline')
    md.append('')
    md.append('| Gate | Metric | Value | Threshold | Verdict |')
    md.append('|------|--------|-------|-----------|---------|')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = full_ge['gates'][gid]
        status = 'PASS' if g['pass'] else '**FAIL**'
        md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
    md.append('')
    fm = full_eval['metrics']
    md.append(f'**Metrics**: {fm["trades"]} trades, PF={fm["pf"]:.3f}, '
              f'exp/wk=${fm["exp_per_week"]:.2f}, DD={fm["max_dd_pct"]:.1f}%')
    md.append(f'**Stress**: PF={full_eval["stress_metrics"]["pf"]:.3f}, '
              f'exp/wk=${full_eval["stress_metrics"]["exp_per_week"]:.2f}')
    md.append(f'**Walk-Forward**: {full_eval["wf_folds_positive"]}/5 folds positive')
    md.append('')

    if filtered_eval:
        md.append(f'### Filtered (exclude hours {worst_hours})')
        md.append('')
        filt_ge = filtered_eval['gate_evaluation']
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = filt_ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')
        fm2 = filtered_eval['metrics']
        md.append(f'**Metrics**: {fm2["trades"]} trades, PF={fm2["pf"]:.3f}, '
                  f'exp/wk=${fm2["exp_per_week"]:.2f}, DD={fm2["max_dd_pct"]:.1f}%')
        md.append(f'**Stress**: PF={filtered_eval["stress_metrics"]["pf"]:.3f}, '
                  f'exp/wk=${filtered_eval["stress_metrics"]["exp_per_week"]:.2f}')
        md.append(f'**Walk-Forward**: {filtered_eval["wf_folds_positive"]}/5 folds positive')
        md.append('')

        # Delta table
        md.append('### Comparison: Full vs Filtered')
        md.append('')
        md.append('| Metric | Full | Filtered | Delta |')
        md.append('|--------|------|----------|-------|')
        md.append(f'| Trades | {fm["trades"]} | {fm2["trades"]} | {fm2["trades"] - fm["trades"]:+d} |')
        md.append(f'| PF | {fm["pf"]:.3f} | {fm2["pf"]:.3f} | {fm2["pf"] - fm["pf"]:+.3f} |')
        md.append(f'| WR% | {fm["wr"]:.1f} | {fm2["wr"]:.1f} | {fm2["wr"] - fm["wr"]:+.1f} |')
        md.append(f'| Exp/wk | ${fm["exp_per_week"]:.2f} | ${fm2["exp_per_week"]:.2f} '
                  f'| ${fm2["exp_per_week"] - fm["exp_per_week"]:+.2f} |')
        md.append(f'| DD% | {fm["max_dd_pct"]:.1f} | {fm2["max_dd_pct"]:.1f} '
                  f'| {fm2["max_dd_pct"] - fm["max_dd_pct"]:+.1f} |')
        md.append(f'| Gates | {full_ge["score"]} | {filt_ge["score"]} '
                  f'| {filt_ge["pass_count"] - full_ge["pass_count"]:+d} |')
        md.append(f'| WF folds | {full_eval["wf_folds_positive"]}/5 '
                  f'| {filtered_eval["wf_folds_positive"]}/5 '
                  f'| {filtered_eval["wf_folds_positive"] - full_eval["wf_folds_positive"]:+d} |')
        md.append('')

    # Verdict
    md.append('## 7. Verdict')
    md.append('')
    md.append(f'**{report["verdict"]["text"]}**')
    md.append('')
    if report['verdict'].get('filtering_worth_it'):
        md.append('Recommendation: Time-of-day filtering IMPROVES the strategy. '
                  'Consider adding an hour filter to the signal.')
    else:
        md.append('Recommendation: Time-of-day filtering is NOT worth the added complexity. '
                  'The signal performs broadly across hours without significant negative clusters.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_time_of_day.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_time_of_day_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Time-of-Day Analysis')
    print(f'  Baseline: {baseline_metrics["trades"]} trades, PF={baseline_metrics["pf"]:.3f}')
    print(f'  Active hours: {len(active_hours)}/24')
    print(f'  Negative hours: {worst_hours if worst_hours else "none"}')
    print(f'  Full gates: {full_ge["score"]}')
    if filtered_eval:
        filt_ge = filtered_eval['gate_evaluation']
        print(f'  Filtered gates: {filt_ge["score"]}')
    print(f'  Verdict: {report["verdict"]["text"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
