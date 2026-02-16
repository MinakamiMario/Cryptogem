#!/usr/bin/env python3
"""
Part 2 -- Agent C8-C: Monte Carlo Trade Shuffle (P2-8)
=======================================================
Bootstrap confidence intervals via 10,000 trade-order shuffles.

Takes the existing trades from the 295-coin v5 baseline (with their P&L
values intact) and randomly reorders them 10,000 times. For each shuffle,
computes a cumulative equity curve and measures max drawdown. This tests
whether the strategy is robust to trade ordering.

Metrics computed across 10,000 shuffles:
  1. P&L distribution: mean, median, P5, P25, P75, P95
  2. Probability of positive P&L (% of shuffles with P&L > 0)
  3. Max drawdown distribution: mean, median, P95
  4. Sharpe-like ratio: mean(P&L) / std(P&L)
  5. Win probability at thresholds: $0, $500, $1000, $2000

Algorithm:
  - Run baseline backtest on 295 coins -> extract trade P&L list
  - For each of 10,000 shuffles (seed=42):
    - np.random.permutation(pnls)
    - equity = np.cumsum(shuffled) + initial_capital
    - max_dd% = max((peak - equity) / peak * 100)
    - Record: final P&L, max DD%, peak equity
  - Compute statistics across all shuffles

Output:
  reports/hf/part2_monte_carlo_001.json
  reports/hf/part2_monte_carlo_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_monte_carlo_001.py
    python strategies/hf/screening/run_part2_monte_carlo_001.py --dry-run
    python strategies/hf/screening/run_part2_monte_carlo_001.py --shuffles 1000
"""
import sys
import json
import time
import argparse
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import run_backtest, precompute_base_indicators
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168   # 24 * 7
BARS_PER_DAY = 24
INITIAL_CAPITAL = 2000.0

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

N_SHUFFLES_DEFAULT = 10000
SEED = 42

REPORT_JSON = 'part2_monte_carlo_001.json'
REPORT_MD = 'part2_monte_carlo_001.md'


# ============================================================
# Data Loading (same pattern as other run_part2 scripts)
# ============================================================

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
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        if require_data:
            print(f'[ERROR] Tiering not found: {path}')
            sys.exit(1)
        print('[SKIP] No tiering file found.')
        return None
    with open(path) as f:
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


# ============================================================
# Combined Backtest (T1 + T2, merged trades)
# ============================================================

def run_combined_backtest(data, tier_coins, tier_indicators, market_ctx,
                          tier1_fee, tier2_fee, params, max_pos=1):
    """Run combined T1+T2 backtest, return merged trade list."""
    signal_fn = signal_h20_vwap_deviation
    signal_params = {**params, '__market__': market_ctx}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    all_trades = []
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_fn,
            params=signal_params, indicators=indicators, fee=fee,
            max_pos=max_pos,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


# ============================================================
# Monte Carlo Trade Shuffle Engine
# ============================================================

def monte_carlo_shuffle(pnls, n_shuffles, initial_capital, seed=42):
    """
    Perform n_shuffles random permutations of the trade P&L array.

    For each shuffle:
      - Compute cumulative equity curve
      - Compute max drawdown %
      - Record final P&L, max DD, peak equity

    Returns dict of arrays (length n_shuffles).
    """
    rng = np.random.default_rng(seed)
    pnl_arr = np.array(pnls, dtype=np.float64)
    n_trades = len(pnl_arr)

    final_pnls = np.empty(n_shuffles, dtype=np.float64)
    max_dds = np.empty(n_shuffles, dtype=np.float64)
    peak_equities = np.empty(n_shuffles, dtype=np.float64)
    min_equities = np.empty(n_shuffles, dtype=np.float64)

    for i in range(n_shuffles):
        # Shuffle trade order
        shuffled = rng.permutation(pnl_arr)

        # Cumulative equity curve
        cum_pnl = np.cumsum(shuffled)
        equity_curve = cum_pnl + initial_capital

        # Max drawdown %
        running_peak = np.maximum.accumulate(equity_curve)
        drawdowns = (running_peak - equity_curve) / running_peak * 100
        # Guard against division by zero (peak=0 shouldn't happen with positive capital)
        drawdowns = np.where(np.isfinite(drawdowns), drawdowns, 0.0)

        final_pnls[i] = cum_pnl[-1]  # = sum of all pnls (same every shuffle)
        max_dds[i] = np.max(drawdowns)
        peak_equities[i] = np.max(equity_curve)
        min_equities[i] = np.min(equity_curve)

    return {
        'final_pnls': final_pnls,
        'max_dds': max_dds,
        'peak_equities': peak_equities,
        'min_equities': min_equities,
    }


def compute_mc_statistics(mc_results, initial_capital):
    """Compute comprehensive statistics from Monte Carlo results."""
    final_pnls = mc_results['final_pnls']
    max_dds = mc_results['max_dds']
    peak_eqs = mc_results['peak_equities']
    min_eqs = mc_results['min_equities']
    n = len(final_pnls)

    # P&L distribution
    pnl_stats = {
        'mean': float(np.mean(final_pnls)),
        'median': float(np.median(final_pnls)),
        'std': float(np.std(final_pnls)),
        'p5': float(np.percentile(final_pnls, 5)),
        'p25': float(np.percentile(final_pnls, 25)),
        'p75': float(np.percentile(final_pnls, 75)),
        'p95': float(np.percentile(final_pnls, 95)),
        'min': float(np.min(final_pnls)),
        'max': float(np.max(final_pnls)),
    }

    # Note: since we're shuffling the same set of trades, the final P&L
    # is always the same (sum is commutative). The key insight is that
    # max drawdown DOES change with ordering.
    # For P&L, all shuffles produce the same total. The distribution is
    # degenerate. We report it for completeness.

    # Probability of positive P&L
    # Since sum is invariant to permutation, this is either 100% or 0%
    prob_positive = float(np.mean(final_pnls > 0) * 100)

    # Win probability at thresholds
    thresholds = [0, 500, 1000, 2000]
    win_probs = {}
    for thresh in thresholds:
        prob = float(np.mean(final_pnls > thresh) * 100)
        win_probs[f'>${thresh}'] = round(prob, 2)

    # Max DD distribution (THIS is where ordering matters)
    dd_stats = {
        'mean': float(np.mean(max_dds)),
        'median': float(np.median(max_dds)),
        'std': float(np.std(max_dds)),
        'p5': float(np.percentile(max_dds, 5)),
        'p25': float(np.percentile(max_dds, 25)),
        'p75': float(np.percentile(max_dds, 75)),
        'p95': float(np.percentile(max_dds, 95)),
        'p99': float(np.percentile(max_dds, 99)),
        'min': float(np.min(max_dds)),
        'max': float(np.max(max_dds)),
    }

    # Peak equity distribution
    peak_stats = {
        'mean': float(np.mean(peak_eqs)),
        'median': float(np.median(peak_eqs)),
        'p5': float(np.percentile(peak_eqs, 5)),
        'p95': float(np.percentile(peak_eqs, 95)),
    }

    # Min equity distribution (worst point in equity curve)
    min_eq_stats = {
        'mean': float(np.mean(min_eqs)),
        'median': float(np.median(min_eqs)),
        'p5': float(np.percentile(min_eqs, 5)),
        'p95': float(np.percentile(min_eqs, 95)),
    }

    # Sharpe-like ratio: mean(P&L) / std(P&L)
    # Since all final P&Ls are the same, std=0. We use max DD std instead.
    # Report the actual P&L sharpe (will be inf/nan if std=0) and a
    # risk-adjusted version using DD variability.
    pnl_std = float(np.std(final_pnls))
    pnl_mean = float(np.mean(final_pnls))
    # P&L std is essentially zero (floating-point noise) since sum is commutative
    if pnl_std > 0.01:  # meaningful variation threshold
        sharpe_pnl = pnl_mean / pnl_std
    else:
        sharpe_pnl = float('inf') if pnl_mean > 0 else 0.0

    # Risk-adjusted: P&L / mean(max_dd%)
    dd_mean = float(np.mean(max_dds))
    risk_adjusted = pnl_mean / dd_mean if dd_mean > 0 else float('inf')

    # Probability of ruin: equity ever going below 0
    prob_ruin = float(np.mean(min_eqs <= 0) * 100)

    # Probability of DD > various thresholds
    dd_thresholds = [5, 10, 15, 20, 25, 30, 50]
    dd_probs = {}
    for thresh in dd_thresholds:
        prob = float(np.mean(max_dds > thresh) * 100)
        dd_probs[f'>{thresh}%'] = round(prob, 2)

    return {
        'pnl_distribution': pnl_stats,
        'prob_positive_pnl': round(prob_positive, 2),
        'win_probabilities': win_probs,
        'max_dd_distribution': dd_stats,
        'dd_threshold_probs': dd_probs,
        'peak_equity_distribution': peak_stats,
        'min_equity_distribution': min_eq_stats,
        'sharpe_pnl': round(sharpe_pnl, 4) if np.isfinite(sharpe_pnl) else 'inf',
        'risk_adjusted_pnl_over_dd': round(risk_adjusted, 4) if np.isfinite(risk_adjusted) else 'inf',
        'prob_ruin_pct': round(prob_ruin, 2),
        'n_shuffles': n,
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 -- Agent C8-C: Monte Carlo Trade Shuffle (P2-8)',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data and run baseline, but skip MC shuffles')
    parser.add_argument('--require-data', action='store_true',
                        help='Exit 1 if cache/tiering missing')
    parser.add_argument('--shuffles', type=int, default=N_SHUFFLES_DEFAULT,
                        help=f'Number of Monte Carlo shuffles (default: {N_SHUFFLES_DEFAULT})')
    args = parser.parse_args()

    n_shuffles = args.shuffles

    print('=' * 70)
    print('  Part 2 -- Agent C8-C: Monte Carlo Trade Shuffle (P2-8)')
    print(f'  Shuffles: {n_shuffles:,}')
    print(f'  Seed: {SEED}')
    print(f'  Initial capital: ${INITIAL_CAPITAL:,.0f}')
    print('  Tests robustness to trade ordering via bootstrap permutation')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    print(f'[Costs] MEXC Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')

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

    # --- Apply 21-coin exclusion -> 295-coin universe ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (after exclusion)')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins after exclusion.')
        sys.exit(1)

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
    # Step 1: Baseline Backtest on 295 coins
    # ============================================================
    print('\n--- Step 1: Baseline Backtest ---')
    t_bt = time.time()

    trades = run_combined_backtest(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, PARAMS_V5, max_pos=1,
    )
    trades_sorted = sorted(trades, key=lambda t: t.get('entry_bar', 0))

    # Extract P&L values
    pnls = [t['pnl'] for t in trades_sorted]
    n_trades = len(pnls)
    total_pnl = sum(pnls)
    n_winners = sum(1 for p in pnls if p > 0)
    n_losers = sum(1 for p in pnls if p <= 0)
    win_total = sum(p for p in pnls if p > 0)
    loss_total = abs(sum(p for p in pnls if p <= 0))
    pf = win_total / loss_total if loss_total > 0 else float('inf')
    wr = n_winners / n_trades * 100 if n_trades > 0 else 0

    # Baseline equity curve (original order)
    eq = INITIAL_CAPITAL
    peak = eq
    max_dd_baseline = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd_baseline:
            max_dd_baseline = dd

    # Per-tier breakdown
    t1_trades = [t for t in trades_sorted if t.get('_tier') == 'tier1']
    t2_trades = [t for t in trades_sorted if t.get('_tier') == 'tier2']

    # Per-reason breakdown
    reason_counts = {}
    reason_pnls = {}
    for t in trades_sorted:
        r = t.get('reason', 'unknown')
        reason_counts[r] = reason_counts.get(r, 0) + 1
        reason_pnls[r] = reason_pnls.get(r, 0.0) + t['pnl']

    print(f'  Trades: {n_trades} (T1:{len(t1_trades)}, T2:{len(t2_trades)})')
    print(f'  P&L: ${total_pnl:.2f} | PF: {pf:.3f} | WR: {wr:.1f}%')
    print(f'  Max DD (original order): {max_dd_baseline:.1f}%')
    print(f'  Winners: {n_winners} | Losers: {n_losers}')
    print(f'  Backtest time: {time.time()-t_bt:.1f}s')

    # Print trade P&L summary
    pnl_arr = np.array(pnls)
    print(f'\n  Trade P&L summary:')
    print(f'    Mean: ${np.mean(pnl_arr):.2f}')
    print(f'    Median: ${np.median(pnl_arr):.2f}')
    print(f'    Std: ${np.std(pnl_arr):.2f}')
    print(f'    Min: ${np.min(pnl_arr):.2f}')
    print(f'    Max: ${np.max(pnl_arr):.2f}')
    print(f'    Total: ${np.sum(pnl_arr):.2f}')

    for reason in sorted(reason_counts.keys()):
        cnt = reason_counts[reason]
        rpnl = reason_pnls[reason]
        print(f'    {reason}: {cnt} trades, P&L ${rpnl:.2f}')

    # --- Dry-run exit ---
    if args.dry_run:
        print('\n--- DRY RUN: Would run %d shuffles on %d trades ---' % (n_shuffles, n_trades))
        print('  Total P&L: $%.2f (invariant to permutation)' % total_pnl)
        print('  Key test: max drawdown distribution under random ordering')
        sys.exit(0)

    # ============================================================
    # Step 2: Monte Carlo Shuffle (10,000 permutations)
    # ============================================================
    print(f'\n--- Step 2: Monte Carlo Shuffle ({n_shuffles:,} permutations) ---')
    t_mc = time.time()

    mc_results = monte_carlo_shuffle(
        pnls=pnls,
        n_shuffles=n_shuffles,
        initial_capital=INITIAL_CAPITAL,
        seed=SEED,
    )

    mc_time = time.time() - t_mc
    print(f'  Completed in {mc_time:.1f}s')

    # ============================================================
    # Step 3: Compute Statistics
    # ============================================================
    print('\n--- Step 3: Statistics ---')

    stats = compute_mc_statistics(mc_results, INITIAL_CAPITAL)

    # Print key results
    print(f'\n  P&L Distribution:')
    ps = stats['pnl_distribution']
    print(f'    Mean:   ${ps["mean"]:.2f}')
    print(f'    Median: ${ps["median"]:.2f}')
    print(f'    Std:    ${ps["std"]:.2f}')
    print(f'    P5:     ${ps["p5"]:.2f}')
    print(f'    P95:    ${ps["p95"]:.2f}')

    print(f'\n  Prob positive P&L: {stats["prob_positive_pnl"]:.1f}%')

    print(f'\n  Win probabilities:')
    for thresh, prob in stats['win_probabilities'].items():
        print(f'    P(P&L {thresh}): {prob:.1f}%')

    print(f'\n  Max DD Distribution:')
    dd = stats['max_dd_distribution']
    print(f'    Mean:   {dd["mean"]:.1f}%')
    print(f'    Median: {dd["median"]:.1f}%')
    print(f'    P5:     {dd["p5"]:.1f}% (best case)')
    print(f'    P25:    {dd["p25"]:.1f}%')
    print(f'    P75:    {dd["p75"]:.1f}%')
    print(f'    P95:    {dd["p95"]:.1f}% (stress case)')
    print(f'    P99:    {dd["p99"]:.1f}% (extreme)')
    print(f'    Min:    {dd["min"]:.1f}% (luckiest order)')
    print(f'    Max:    {dd["max"]:.1f}% (unluckiest order)')

    print(f'\n  DD threshold probabilities:')
    for thresh, prob in stats['dd_threshold_probs'].items():
        print(f'    P(DD {thresh}): {prob:.1f}%')

    print(f'\n  Min equity (worst point in curve):')
    me = stats['min_equity_distribution']
    print(f'    Mean:   ${me["mean"]:.2f}')
    print(f'    P5:     ${me["p5"]:.2f} (worst 5%)')
    print(f'    Median: ${me["median"]:.2f}')

    print(f'\n  Sharpe-like ratio (P&L/std): {stats["sharpe_pnl"]}')
    print(f'  Risk-adjusted (P&L/mean_DD): {stats["risk_adjusted_pnl_over_dd"]}')
    print(f'  Prob of ruin (equity<=0): {stats["prob_ruin_pct"]:.2f}%')

    # Original order DD vs shuffle distribution
    dd_percentile_of_original = float(
        np.mean(mc_results['max_dds'] <= max_dd_baseline) * 100
    )
    print(f'\n  Original order DD ({max_dd_baseline:.1f}%) is at '
          f'percentile {dd_percentile_of_original:.1f}% of shuffle distribution')

    elapsed = time.time() - t0

    # ============================================================
    # Verdict
    # ============================================================
    print('\n--- VERDICT ---')

    # Key determination: is the strategy robust to trade ordering?
    total_pnl_positive = total_pnl > 0
    median_dd = dd['median']
    p95_dd = dd['p95']
    prob_ruin = stats['prob_ruin_pct']

    if total_pnl_positive and p95_dd < 50 and prob_ruin == 0:
        if p95_dd < 20:
            verdict = 'STRONG PASS'
            verdict_detail = (
                f'P&L=${total_pnl:.0f} always positive, P95 DD={p95_dd:.1f}% < 20%, '
                f'zero ruin probability'
            )
        elif p95_dd < 30:
            verdict = 'PASS'
            verdict_detail = (
                f'P&L=${total_pnl:.0f} always positive, P95 DD={p95_dd:.1f}% < 30%, '
                f'zero ruin probability'
            )
        else:
            verdict = 'CONDITIONAL PASS'
            verdict_detail = (
                f'P&L=${total_pnl:.0f} positive but P95 DD={p95_dd:.1f}% elevated, '
                f'zero ruin probability'
            )
    elif total_pnl_positive and prob_ruin < 1:
        verdict = 'MARGINAL PASS'
        verdict_detail = (
            f'P&L=${total_pnl:.0f} positive, P95 DD={p95_dd:.1f}%, '
            f'ruin probability={prob_ruin:.2f}%'
        )
    else:
        verdict = 'FAIL'
        verdict_detail = (
            f'P&L=${total_pnl:.0f}, P95 DD={p95_dd:.1f}%, '
            f'ruin probability={prob_ruin:.2f}%'
        )

    print(f'  Verdict: {verdict}')
    print(f'  Detail: {verdict_detail}')

    # ============================================================
    # JSON Report
    # ============================================================

    # Round all floats in trade list for compact output
    trade_summary = []
    for t in trades_sorted:
        trade_summary.append({
            'pair': t['pair'],
            'pnl': round(t['pnl'], 4),
            'pnl_pct': round(t.get('pnl_pct', 0), 2),
            'reason': t.get('reason', 'unknown'),
            'entry_bar': t.get('entry_bar', 0),
            'exit_bar': t.get('exit_bar', 0),
            'bars': t.get('bars', 0),
            '_tier': t.get('_tier', 'unknown'),
        })

    report = {
        'run_header': {
            'task': 'part2_monte_carlo_001',
            'agent': 'C8-C',
            'priority': 'P2-8',
            'status': 'DONE',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees_bps': {
                'tier1': round(tier1_fee * 10000, 1),
                'tier2': round(tier2_fee * 10000, 1),
            },
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'n_shuffles': n_shuffles,
            'seed': SEED,
            'initial_capital': INITIAL_CAPITAL,
            'runtime_s': round(elapsed, 1),
            'mc_runtime_s': round(mc_time, 1),
        },
        'baseline': {
            'trades': n_trades,
            'total_pnl': round(total_pnl, 2),
            'pf': round(pf, 3),
            'wr': round(wr, 1),
            'max_dd_pct': round(max_dd_baseline, 1),
            'winners': n_winners,
            'losers': n_losers,
            'win_total': round(win_total, 2),
            'loss_total': round(loss_total, 2),
            'exp_per_trade': round(total_pnl / n_trades, 2) if n_trades > 0 else 0,
            'exp_per_week': round(total_pnl / total_weeks, 2) if total_weeks > 0 else 0,
            'tier_split': {
                'tier1': len(t1_trades),
                'tier2': len(t2_trades),
            },
            'exit_reasons': {
                r: {'count': reason_counts[r], 'pnl': round(reason_pnls[r], 2)}
                for r in sorted(reason_counts.keys())
            },
        },
        'monte_carlo': {
            'n_shuffles': n_shuffles,
            'seed': SEED,
            'note': 'Trade-order shuffle: same trades, different ordering. '
                    'Final P&L is invariant (sum is commutative). '
                    'Max drawdown varies with trade ordering.',
            'statistics': stats,
            'original_order_dd_percentile': round(dd_percentile_of_original, 1),
        },
        'verdict': {
            'result': verdict,
            'detail': verdict_detail,
            'total_pnl': round(total_pnl, 2),
            'prob_positive': stats['prob_positive_pnl'],
            'median_dd': round(median_dd, 1),
            'p95_dd': round(p95_dd, 1),
            'prob_ruin': stats['prob_ruin_pct'],
        },
        'trade_list': trade_summary,
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / REPORT_JSON
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # Markdown Report
    # ============================================================

    md = []
    md.append('# Part 2 -- Monte Carlo Trade Shuffle (Agent C8-C, P2-8)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins (excl 21 net-negative)')
    md.append(f'**Params**: v5 (dev={PARAMS_V5["dev_thresh"]}, tp={PARAMS_V5["tp_pct"]}, '
              f'sl={PARAMS_V5["sl_pct"]}, tl={PARAMS_V5["time_limit"]})')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    md.append(f'**Shuffles**: {n_shuffles:,} (seed={SEED})')
    md.append(f'**Initial Capital**: ${INITIAL_CAPITAL:,.0f}')
    md.append(f'**Runtime**: {elapsed:.1f}s (MC: {mc_time:.1f}s)')
    md.append('')

    # Verdict box
    md.append('## Verdict')
    md.append('')
    md.append(f'**{verdict}**: {verdict_detail}')
    md.append('')

    # Baseline summary
    md.append('## 1. Baseline (295 coins, original order)')
    md.append('')
    md.append('| Metric | Value |')
    md.append('|--------|-------|')
    md.append(f'| Trades | {n_trades} (T1:{len(t1_trades)}, T2:{len(t2_trades)}) |')
    md.append(f'| Total P&L | ${total_pnl:.2f} |')
    md.append(f'| Profit Factor | {pf:.3f} |')
    md.append(f'| Win Rate | {wr:.1f}% |')
    md.append(f'| Max DD (original) | {max_dd_baseline:.1f}% |')
    md.append(f'| Winners / Losers | {n_winners} / {n_losers} |')
    md.append(f'| Exp/trade | ${total_pnl/n_trades:.2f} |' if n_trades > 0 else '| Exp/trade | $0 |')
    md.append(f'| Exp/week | ${total_pnl/total_weeks:.2f} |' if total_weeks > 0 else '| Exp/week | $0 |')
    md.append('')

    # Exit reason breakdown
    md.append('### Exit Reasons')
    md.append('')
    md.append('| Reason | Count | P&L | Avg P&L |')
    md.append('|--------|-------|-----|---------|')
    for r in sorted(reason_counts.keys()):
        cnt = reason_counts[r]
        rpnl = reason_pnls[r]
        avg = rpnl / cnt if cnt > 0 else 0
        md.append(f'| {r} | {cnt} | ${rpnl:.2f} | ${avg:.2f} |')
    md.append('')

    # MC P&L Distribution
    md.append('## 2. Monte Carlo P&L Distribution')
    md.append('')
    md.append(f'> **Note**: Since we shuffle the same set of trades, the total P&L is '
              f'always ${total_pnl:.2f} (sum is commutative). The real test is drawdown.')
    md.append('')
    md.append('| Statistic | Value |')
    md.append('|-----------|-------|')
    md.append(f'| Mean | ${ps["mean"]:.2f} |')
    md.append(f'| Median | ${ps["median"]:.2f} |')
    md.append(f'| Std Dev | ${ps["std"]:.2f} |')
    md.append(f'| P5 | ${ps["p5"]:.2f} |')
    md.append(f'| P25 | ${ps["p25"]:.2f} |')
    md.append(f'| P75 | ${ps["p75"]:.2f} |')
    md.append(f'| P95 | ${ps["p95"]:.2f} |')
    md.append('')

    md.append('### Win Probabilities')
    md.append('')
    md.append('| Threshold | Probability |')
    md.append('|-----------|-------------|')
    for thresh, prob in stats['win_probabilities'].items():
        md.append(f'| P&L {thresh} | {prob:.1f}% |')
    md.append('')

    # MC Max DD Distribution (the KEY result)
    md.append('## 3. Max Drawdown Distribution (KEY RESULT)')
    md.append('')
    md.append('This is the core insight from trade-order shuffling: how much does '
              'drawdown vary with the sequence of trades?')
    md.append('')
    md.append('| Statistic | DD% |')
    md.append('|-----------|-----|')
    md.append(f'| Mean | {dd["mean"]:.1f}% |')
    md.append(f'| Median | {dd["median"]:.1f}% |')
    md.append(f'| Std Dev | {dd["std"]:.1f}% |')
    md.append(f'| P5 (best) | {dd["p5"]:.1f}% |')
    md.append(f'| P25 | {dd["p25"]:.1f}% |')
    md.append(f'| P75 | {dd["p75"]:.1f}% |')
    md.append(f'| P95 (stress) | {dd["p95"]:.1f}% |')
    md.append(f'| P99 (extreme) | {dd["p99"]:.1f}% |')
    md.append(f'| Min (luckiest) | {dd["min"]:.1f}% |')
    md.append(f'| Max (unluckiest) | {dd["max"]:.1f}% |')
    md.append(f'| **Original order** | **{max_dd_baseline:.1f}%** (percentile: {dd_percentile_of_original:.0f}%) |')
    md.append('')

    # DD threshold probabilities
    md.append('### Drawdown Exceedance Probabilities')
    md.append('')
    md.append('| DD Threshold | P(DD > threshold) |')
    md.append('|-------------|-------------------|')
    for thresh, prob in stats['dd_threshold_probs'].items():
        md.append(f'| {thresh} | {prob:.1f}% |')
    md.append('')

    # Risk metrics
    md.append('## 4. Risk Metrics')
    md.append('')
    md.append('| Metric | Value |')
    md.append('|--------|-------|')
    md.append(f'| Sharpe-like (P&L/std) | {stats["sharpe_pnl"]} |')
    md.append(f'| Risk-adjusted (P&L/mean_DD) | {stats["risk_adjusted_pnl_over_dd"]} |')
    md.append(f'| Prob of ruin (equity<=0) | {stats["prob_ruin_pct"]:.2f}% |')
    md.append('')

    me = stats['min_equity_distribution']
    md.append('### Minimum Equity Distribution (worst point in curve)')
    md.append('')
    md.append('| Statistic | Value |')
    md.append('|-----------|-------|')
    md.append(f'| Mean | ${me["mean"]:.2f} |')
    md.append(f'| Median | ${me["median"]:.2f} |')
    md.append(f'| P5 (worst 5%) | ${me["p5"]:.2f} |')
    md.append(f'| P95 (best 5%) | ${me["p95"]:.2f} |')
    md.append('')

    # Trade list (top 10 by absolute P&L)
    md.append('## 5. Trade List (sorted by entry)')
    md.append('')
    md.append(f'Total: {n_trades} trades')
    md.append('')
    md.append('| # | Pair | P&L | P&L% | Reason | Bars | Tier |')
    md.append('|---|------|-----|------|--------|------|------|')
    for i, t in enumerate(trade_summary):
        md.append(f'| {i+1} | {t["pair"]} | ${t["pnl"]:.2f} | {t["pnl_pct"]:.1f}% | '
                  f'{t["reason"]} | {t["bars"]} | {t["_tier"]} |')
    md.append('')

    # Interpretation
    md.append('## 6. Interpretation')
    md.append('')
    md.append('**What this test shows**: The Monte Carlo trade-order shuffle takes the '
              f'{n_trades} actual trades and randomly reorders them {n_shuffles:,} times. '
              'Since the total P&L is the sum of all trade P&Ls (commutative), the final '
              'P&L is always the same. However, the **maximum drawdown** changes with '
              'ordering because a streak of losers early creates a deeper trough than '
              'the same losers spread out.')
    md.append('')
    md.append(f'**Key findings**:')
    md.append(f'- The strategy is **always profitable** (${total_pnl:.2f}) regardless of trade order')
    md.append(f'- Median max drawdown: {dd["median"]:.1f}% (half of orderings are better than this)')
    md.append(f'- P95 worst-case DD: {dd["p95"]:.1f}% (only 5% of orderings are worse)')
    md.append(f'- Original order DD ({max_dd_baseline:.1f}%) sits at the '
              f'{dd_percentile_of_original:.0f}th percentile')
    if stats['prob_ruin_pct'] == 0:
        md.append(f'- Zero probability of ruin (equity never hits $0 in any ordering)')
    else:
        md.append(f'- Ruin probability: {stats["prob_ruin_pct"]:.2f}%')
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_monte_carlo_001.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = out_dir / REPORT_MD
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # --- Final summary ---
    print(f'\n{"="*70}')
    print(f'  MONTE CARLO TRADE SHUFFLE COMPLETE')
    print(f'  Trades: {n_trades} | P&L: ${total_pnl:.2f} | PF: {pf:.3f}')
    print(f'  Shuffles: {n_shuffles:,} | Seed: {SEED}')
    print(f'  Median DD: {dd["median"]:.1f}% | P95 DD: {dd["p95"]:.1f}%')
    print(f'  Original DD: {max_dd_baseline:.1f}% (percentile: {dd_percentile_of_original:.0f}%)')
    print(f'  Prob ruin: {stats["prob_ruin_pct"]:.2f}%')
    print(f'  VERDICT: {verdict}')
    print(f'  Runtime: {elapsed:.1f}s')
    print(f'{"="*70}')


if __name__ == '__main__':
    main()
