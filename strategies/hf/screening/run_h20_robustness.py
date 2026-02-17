#!/usr/bin/env python3
"""
H20 VWAP_DEVIATION Robustness Neighborhood Grid (Part 2)
=========================================================
Runs 12 variants around v5 baseline under MEXC Market costs.

v5 baseline: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10
Grid perturbs one parameter at a time from this baseline.

Metrics per variant:
  - Trades, PF, WR, Exp/Trade, Exp/Week, DD%, Fee Drag%
  - Walk-forward 5-fold (positive folds count)
  - Stress test at 2x fees (PF and exp/week)

Composite score:
  score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)

Usage:
    python -m strategies.hf.screening.run_h20_robustness              # Full run
    python -m strategies.hf.screening.run_h20_robustness --dry-run    # Preview grid only
    python -m strategies.hf.screening.run_h20_robustness --require-data  # CI mode (exit 1 on missing data)

Graceful handling:
    - Missing cache/tiering: prints [SKIP] and exits 0 (not error)
    - Use --require-data to restore exit-1 behavior for CI pipelines
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from copy import deepcopy

# Ensure project root on path
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

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168  # 24 * 7

# MEXC Market fees (per-side)
MEXC_MARKET_T1 = 0.0005   # 5 bps
MEXC_MARKET_T2 = 0.0020   # 20 bps

# Stress 2x fees (per-side)
STRESS_2X_T1 = 0.0010     # 10 bps
STRESS_2X_T2 = 0.0040     # 40 bps

# ============================================================
# Robustness Grid: 12 variants around v5 baseline
# ============================================================

ROBUSTNESS_GRID = [
    # Baseline (v5)
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
     'label': 'v5 baseline'},

    # dev_thresh perturbations
    {'dev_thresh': 1.8, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
     'label': 'dev_thresh -0.2'},
    {'dev_thresh': 2.2, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
     'label': 'dev_thresh +0.2'},
    {'dev_thresh': 2.5, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
     'label': 'dev_thresh +0.5'},

    # tp_pct perturbations
    {'dev_thresh': 2.0, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 10,
     'label': 'tp_pct -2'},
    {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 10,
     'label': 'tp_pct +2'},
    {'dev_thresh': 2.0, 'tp_pct': 12, 'sl_pct': 5, 'time_limit': 10,
     'label': 'tp_pct +4'},

    # sl_pct perturbations
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 3, 'time_limit': 10,
     'label': 'sl_pct -2'},
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10,
     'label': 'sl_pct +2'},

    # time_limit perturbations
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 8,
     'label': 'time_limit -2'},
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 12,
     'label': 'time_limit +2'},
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15,
     'label': 'time_limit +5'},
]

assert len(ROBUSTNESS_GRID) == 12, f'Expected 12 variants, got {len(ROBUSTNESS_GRID)}'


# ============================================================
# Data Loading (reuse from run_reality_check.py)
# ============================================================

def load_candle_cache(timeframe='1h', require_data=False):
    """Load candle cache: try merged file first, fall back to per-coin parts.

    Returns coins_data dict, or None if cache is missing and require_data=False.
    """
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
            # Convert filename back to symbol: BTC_USD.json -> BTC/USD
            symbol = coin_file.stem.replace('_', '/')
            # Check manifest status if available
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


def load_universe_tiering(require_data=False):
    """Load universe tiering. Returns dict or None if missing and not required."""
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        if require_data:
            print(f'[ERROR] Tiering not found: {tiering_path}')
            sys.exit(1)
        print('[SKIP] No tiering file found. Run universe tiering first.')
        return None
    with open(tiering_path) as f:
        tiering = json.load(f)
    return tiering


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


# ============================================================
# Backtest Runner (per variant, per tier)
# ============================================================

def run_h20_variant(params, data, tier_coins, tier_indicators,
                    market_context, tier1_fee, tier2_fee):
    """Run one H20 variant across both tiers, return combined trade list."""
    # Strip 'label' from params before passing to signal fn
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
            max_pos=1,
        )

        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    return all_trades


def run_h20_walk_forward(params, data, tier_coins, tier_indicators,
                         market_context, tier1_fee, tier2_fee, n_folds=5):
    """Run walk-forward for one H20 variant. Returns list of fold results."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}
    signal_fn = signal_h20_vwap_deviation

    # Collect fold results across tiers
    tier_fold_trades = {}  # fold_idx -> list of trades

    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        fold_results = walk_forward(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=enriched_params,
            indicators=indicators,
            n_folds=n_folds,
            fee=fee,
            max_pos=1,
        )

        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)

    return tier_fold_trades


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    """Compute standard metrics from a trade list."""
    n_trades = len(trades)
    if n_trades == 0:
        return {
            'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
            'dd': 0.0, 'expectancy': 0.0, 'trades_per_week': 0.0,
            'exp_per_week': 0.0, 'fee_drag_pct': 0.0,
        }

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n_trades

    # Trades per week
    total_weeks = total_bars / BARS_PER_WEEK if total_bars and total_bars > 0 else 1.0
    trades_per_week = n_trades / total_weeks
    exp_per_week = expectancy * trades_per_week

    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        fee = t.get('_fee_per_side', 0.0005)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * fee + (size + gross) * fee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag_pct = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0

    # Max drawdown
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get('entry_bar', 0)):
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        'trades': n_trades,
        'pnl': round(total_pnl, 2),
        'pf': round(pf, 3),
        'wr': round(wr, 2),
        'dd': round(max_dd, 2),
        'expectancy': round(expectancy, 4),
        'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4),
        'fee_drag_pct': round(fee_drag_pct, 2),
    }


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
# Composite Score
# ============================================================

def composite_score(exp_per_week, wf_folds_positive, trades, n_folds=5):
    """
    score = exp_per_week * (wf_folds_positive / n_folds) * min(1.0, trades / 50)
    """
    if exp_per_week <= 0:
        return 0.0
    wf_factor = wf_folds_positive / n_folds
    trade_factor = min(1.0, trades / 50)
    return exp_per_week * wf_factor * trade_factor


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='H20 VWAP_DEVIATION Robustness Neighborhood Grid',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data and print grid, but do not run backtests')
    parser.add_argument('--require-data', action='store_true',
                        help='Exit with code 1 if cache/tiering is missing (for CI)')
    args = parser.parse_args()

    print('=' * 70)
    print('  H20 VWAP_DEVIATION Robustness Neighborhood Grid')
    print('  Cost Regime: MEXC Market (T1=5bps, T2=20bps)')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Try to use v2 cost model ---
    try:
        from strategies.hf.screening.costs_mexc_v2 import get_harness_fee
        tier1_fee = get_harness_fee('mexc_market', 'tier1')
        tier2_fee = get_harness_fee('mexc_market', 'tier2')
        cost_source = 'costs_mexc_v2'
    except ImportError:
        tier1_fee = MEXC_MARKET_T1
        tier2_fee = MEXC_MARKET_T2
        cost_source = 'hardcoded'
    print(f'[Costs] Using {cost_source}: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')

    # --- Get commit hash ---
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

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins = build_tier_coins(tiering, available_coins)

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        if args.require_data:
            print('[ERROR] No coins in T1 or T2.')
            sys.exit(1)
        print('[SKIP] No coins in T1 or T2.')
        sys.exit(0)

    # --- Dry-run: print grid and exit ---
    if args.dry_run:
        print(f'\n--- DRY RUN: Grid Preview ({len(ROBUSTNESS_GRID)} variants) ---')
        print(f'{"#":>3s}  {"Label":20s}  dev   tp  sl  tl')
        print(f'{"---":>3s}  {"--------------------":20s}  ----  --  --  --')
        for i, v in enumerate(ROBUSTNESS_GRID):
            print(f'{i:3d}  {v["label"]:20s}  '
                  f'{v["dev_thresh"]:4.1f}  {v["tp_pct"]:2d}  '
                  f'{v["sl_pct"]:2d}  {v["time_limit"]:2d}')
        print(f'\n[Dry Run] Would run {len(ROBUSTNESS_GRID)} variants x 3 passes '
              f'(baseline + WF5 + stress2x)')
        print(f'[Dry Run] Universe: T1={n_t1}, T2={n_t2} coins')
        print(f'[Dry Run] Cost source: {cost_source}')
        sys.exit(0)

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
    all_coins = []
    for coins in tier_coins.values():
        all_coins.extend(coins)
    all_coins = list(set(all_coins))
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

    # ============================================================
    # Run backtests: MEXC Market baseline
    # ============================================================

    print(f'\n--- MEXC Market Baseline (T1={tier1_fee*10000:.0f}bps, '
          f'T2={tier2_fee*10000:.0f}bps) ---')

    variant_results = []

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_var = time.time()

        # Full backtest
        trades = run_h20_variant(
            params=params,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee,
            tier2_fee=tier2_fee,
        )

        metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)

        print(f'  [{var_idx:2d}] {params["label"]:20s} '
              f'trades={metrics["trades"]:3d} PF={metrics["pf"]:.3f} '
              f'WR={metrics["wr"]:.1f}% exp/w=${metrics["exp_per_week"]:.2f} '
              f'DD={metrics["dd"]:.1f}% fee_drag={metrics["fee_drag_pct"]:.1f}% '
              f'({time.time()-t_var:.1f}s)')

        variant_results.append({
            'variant_idx': var_idx,
            'label': params['label'],
            'params': {k: v for k, v in params.items() if k != 'label'},
            'baseline_metrics': metrics,
        })

    # ============================================================
    # Walk-Forward 5-fold per variant
    # ============================================================

    print('\n--- Walk-Forward 5-Fold ---')

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_wf = time.time()

        fold_trades = run_h20_walk_forward(
            params=params,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee,
            tier2_fee=tier2_fee,
            n_folds=5,
        )

        # Count positive folds
        folds_positive = 0
        fold_details = []
        for fold_idx in sorted(fold_trades.keys()):
            fold_pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
            fold_n = len(fold_trades[fold_idx])
            is_positive = fold_pnl > 0
            if is_positive:
                folds_positive += 1
            fold_details.append({
                'fold': fold_idx,
                'trades': fold_n,
                'pnl': round(fold_pnl, 2),
                'positive': is_positive,
            })

        variant_results[var_idx]['wf_folds_positive'] = folds_positive
        variant_results[var_idx]['wf_folds_total'] = 5
        variant_results[var_idx]['wf_fold_details'] = fold_details

        print(f'  [{var_idx:2d}] {params["label"]:20s} '
              f'WF={folds_positive}/5 ({time.time()-t_wf:.1f}s)')

    # ============================================================
    # Stress Test: 2x Fees
    # ============================================================

    print(f'\n--- Stress Test: 2x Fees (T1={STRESS_2X_T1*10000:.0f}bps, '
          f'T2={STRESS_2X_T2*10000:.0f}bps) ---')

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_stress = time.time()

        trades = run_h20_variant(
            params=params,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=STRESS_2X_T1,
            tier2_fee=STRESS_2X_T2,
        )

        stress_metrics = compute_metrics(
            trades, initial_capital=2000.0, total_bars=total_bars,
        )

        variant_results[var_idx]['stress_2x'] = {
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
            'trades': stress_metrics['trades'],
            'wr': stress_metrics['wr'],
            'dd': stress_metrics['dd'],
        }

        print(f'  [{var_idx:2d}] {params["label"]:20s} '
              f'PF={stress_metrics["pf"]:.3f} '
              f'exp/w=${stress_metrics["exp_per_week"]:.2f} '
              f'({time.time()-t_stress:.1f}s)')

    # ============================================================
    # Compute Composite Scores and Rank
    # ============================================================

    print('\n--- Composite Scoring ---')

    for vr in variant_results:
        m = vr['baseline_metrics']
        score = composite_score(
            exp_per_week=m['exp_per_week'],
            wf_folds_positive=vr['wf_folds_positive'],
            trades=m['trades'],
        )
        vr['composite_score'] = round(score, 4)

    # Sort by composite score descending
    ranked = sorted(variant_results, key=lambda x: x['composite_score'], reverse=True)

    for rank_idx, vr in enumerate(ranked):
        m = vr['baseline_metrics']
        print(f'  #{rank_idx+1:2d} [{vr["variant_idx"]:2d}] {vr["label"]:20s} '
              f'score={vr["composite_score"]:.4f} '
              f'exp/w=${m["exp_per_week"]:.2f} '
              f'WF={vr["wf_folds_positive"]}/5 '
              f'trades={m["trades"]}')

    elapsed = time.time() - t0

    # ============================================================
    # Build JSON Report
    # ============================================================

    report = {
        'run_header': {
            'task': 'h20_robustness_neighborhood',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'variants_tested': len(ROBUSTNESS_GRID),
            'cost_regime': 'MEXC Market',
            'fees': {
                'baseline': {'tier1_bps': 5, 'tier2_bps': 20},
                'stress_2x': {'tier1_bps': 10, 'tier2_bps': 40},
            },
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'scoring_formula': 'exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)',
        'variant_results': variant_results,
        'ranking': [
            {
                'rank': i + 1,
                'variant_idx': vr['variant_idx'],
                'label': vr['label'],
                'composite_score': vr['composite_score'],
            }
            for i, vr in enumerate(ranked)
        ],
        'top3': [
            {
                'rank': i + 1,
                'variant_idx': ranked[i]['variant_idx'],
                'label': ranked[i]['label'],
                'params': ranked[i]['params'],
                'composite_score': ranked[i]['composite_score'],
                'baseline_metrics': ranked[i]['baseline_metrics'],
                'wf_folds_positive': ranked[i]['wf_folds_positive'],
                'stress_2x': ranked[i]['stress_2x'],
            }
            for i in range(min(3, len(ranked)))
        ],
    }

    json_path = ROOT / 'reports' / 'hf' / 'h20_robustness_002.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # Build Markdown Report
    # ============================================================

    md = []
    md.append('# H20 VWAP_DEVIATION Robustness Neighborhood Grid')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2})')
    md.append(f'**Timeframe**: 1H')
    md.append(f'**Cost Regime**: MEXC Market (T1=5bps, T2=20bps)')
    md.append(f'**Stress**: 2x fees (T1=10bps, T2=40bps)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append(f'**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)')
    md.append('')

    md.append('## Grid Design')
    md.append('')
    md.append('12 variants perturbing one parameter at a time from v5 baseline.')
    md.append('')

    # Full results table
    md.append('## All Variants (MEXC Market)')
    md.append('')
    md.append('| # | Label | dev | tp | sl | tl | Trades | PF | WR% | Exp/Tr | Exp/Wk | DD% | Fee% | WF | Score |')
    md.append('|---|-------|-----|----|----|----|----|-----|------|--------|--------|------|------|-----|-------|')

    for vr in variant_results:
        m = vr['baseline_metrics']
        p = vr['params']
        md.append(
            f'| {vr["variant_idx"]} '
            f'| {vr["label"]} '
            f'| {p["dev_thresh"]} '
            f'| {p["tp_pct"]} '
            f'| {p["sl_pct"]} '
            f'| {p["time_limit"]} '
            f'| {m["trades"]} '
            f'| {m["pf"]:.3f} '
            f'| {m["wr"]:.1f} '
            f'| ${m["expectancy"]:.2f} '
            f'| ${m["exp_per_week"]:.2f} '
            f'| {m["dd"]:.1f} '
            f'| {m["fee_drag_pct"]:.1f} '
            f'| {vr["wf_folds_positive"]}/5 '
            f'| {vr["composite_score"]:.4f} |'
        )
    md.append('')

    # Stress test table
    md.append('## Stress Test (2x Fees)')
    md.append('')
    md.append('| # | Label | PF | Exp/Wk | Trades | WR% | DD% |')
    md.append('|---|-------|----|--------|--------|------|------|')

    for vr in variant_results:
        s = vr['stress_2x']
        md.append(
            f'| {vr["variant_idx"]} '
            f'| {vr["label"]} '
            f'| {s["pf"]:.3f} '
            f'| ${s["exp_per_week"]:.2f} '
            f'| {s["trades"]} '
            f'| {s["wr"]:.1f} '
            f'| {s["dd"]:.1f} |'
        )
    md.append('')

    # Walk-Forward detail
    md.append('## Walk-Forward Detail (5-Fold)')
    md.append('')
    md.append('| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |')
    md.append('|---|-------|--------|--------|--------|--------|--------|----------|')

    for vr in variant_results:
        fold_pnls = []
        for fd in vr.get('wf_fold_details', []):
            fold_pnls.append(f'${fd["pnl"]:.0f}')
        while len(fold_pnls) < 5:
            fold_pnls.append('-')
        md.append(
            f'| {vr["variant_idx"]} '
            f'| {vr["label"]} '
            f'| {fold_pnls[0]} '
            f'| {fold_pnls[1]} '
            f'| {fold_pnls[2]} '
            f'| {fold_pnls[3]} '
            f'| {fold_pnls[4]} '
            f'| {vr["wf_folds_positive"]}/5 |'
        )
    md.append('')

    # Top 3
    md.append('## Ranking (Composite Score)')
    md.append('')
    md.append('```')
    md.append('score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)')
    md.append('```')
    md.append('')

    for i, vr in enumerate(ranked[:3]):
        m = vr['baseline_metrics']
        s = vr['stress_2x']
        md.append(f'### #{i+1}: {vr["label"]} (variant {vr["variant_idx"]})')
        md.append('')
        md.append(f'- **Params**: dev_thresh={vr["params"]["dev_thresh"]}, '
                  f'tp_pct={vr["params"]["tp_pct"]}, '
                  f'sl_pct={vr["params"]["sl_pct"]}, '
                  f'time_limit={vr["params"]["time_limit"]}')
        md.append(f'- **Composite Score**: {vr["composite_score"]:.4f}')
        md.append(f'- **Baseline**: {m["trades"]} trades, PF={m["pf"]:.3f}, '
                  f'WR={m["wr"]:.1f}%, Exp/Wk=${m["exp_per_week"]:.2f}, '
                  f'DD={m["dd"]:.1f}%')
        md.append(f'- **Walk-Forward**: {vr["wf_folds_positive"]}/5 positive folds')
        md.append(f'- **Stress 2x**: PF={s["pf"]:.3f}, Exp/Wk=${s["exp_per_week"]:.2f}')
        md.append('')

    # Full ranking table
    md.append('### Full Ranking')
    md.append('')
    md.append('| Rank | # | Label | Score | Exp/Wk | WF | Trades |')
    md.append('|------|---|-------|-------|--------|----|--------|')

    for i, vr in enumerate(ranked):
        m = vr['baseline_metrics']
        md.append(
            f'| {i+1} '
            f'| {vr["variant_idx"]} '
            f'| {vr["label"]} '
            f'| {vr["composite_score"]:.4f} '
            f'| ${m["exp_per_week"]:.2f} '
            f'| {vr["wf_folds_positive"]}/5 '
            f'| {m["trades"]} |'
        )
    md.append('')

    # Sensitivity summary
    md.append('## Parameter Sensitivity Summary')
    md.append('')
    md.append('Comparing each perturbation to v5 baseline (variant 0):')
    md.append('')

    baseline_m = variant_results[0]['baseline_metrics']
    baseline_score = variant_results[0]['composite_score']

    md.append('| Param | Change | Trades | Exp/Wk | Score | Delta Score |')
    md.append('|-------|--------|--------|--------|-------|-------------|')

    for vr in variant_results:
        m = vr['baseline_metrics']
        delta = vr['composite_score'] - baseline_score
        sign = '+' if delta >= 0 else ''
        md.append(
            f'| {vr["label"]} '
            f'| vs baseline '
            f'| {m["trades"]} '
            f'| ${m["exp_per_week"]:.2f} '
            f'| {vr["composite_score"]:.4f} '
            f'| {sign}{delta:.4f} |'
        )
    md.append('')

    # Footer
    md.append('---')
    md.append(
        f'*Generated by strategies/hf/screening/run_h20_robustness.py '
        f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*'
    )

    md_path = ROOT / 'reports' / 'hf' / 'h20_robustness_002.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Print summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: {len(ROBUSTNESS_GRID)} variants tested')
    print(f'  Top-1: {ranked[0]["label"]} '
          f'(score={ranked[0]["composite_score"]:.4f})')
    if len(ranked) > 1:
        print(f'  Top-2: {ranked[1]["label"]} '
              f'(score={ranked[1]["composite_score"]:.4f})')
    if len(ranked) > 2:
        print(f'  Top-3: {ranked[2]["label"]} '
              f'(score={ranked[2]["composite_score"]:.4f})')
    print(f'  Runtime: {elapsed:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
