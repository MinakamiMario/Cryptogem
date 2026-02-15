#!/usr/bin/env python3
"""
Part 2 -- Agent C2-A3: Out-of-Sample Validation of excl_all_negative
=====================================================================
Tests whether the excl_all_negative coin exclusion approach contains
forward-looking bias or is a robust structural feature.

Three methods:
  1. Split-half temporal test: train exclusion on 1st half, apply to 2nd half
  2. Fold-based leakage-free: per-fold exclusion on training portion only
  3. Stability check: how many of the 21 excluded coins are negative across
     ALL three equal time periods?

Usage:
    python -m strategies.hf.screening.run_part2_oos_validation
    python -m strategies.hf.screening.run_part2_oos_validation --dry-run
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

# The 21 coins excluded by excl_all_negative from the loss cluster report
FULL_SAMPLE_EXCLUDED = [
    "AI3/USD", "ALKIMI/USD", "ANIME/USD", "CFG/USD", "DBR/USD",
    "ESX/USD", "GST/USD", "HOUSE/USD", "KET/USD", "LMWR/USD",
    "MXC/USD", "ODOS/USD", "PERP/USD", "PNUT/USD", "POLIS/USD",
    "RARI/USD", "SUKU/USD", "TANSSI/USD", "TITCOIN/USD", "TOSHI/USD",
    "WMTX/USD",
]


# ────────────────────────── Data Loading ──────────────────────────

def load_candle_cache(timeframe='1h', require_data=False):
    """Load candle data -- same as loss_cluster script."""
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


def run_full_evaluation(label, data, tier_coins, all_indicators_cache,
                        market_context, tier1_fee, tier2_fee,
                        stress_tier1_fee, stress_tier2_fee, total_bars):
    """Full gate evaluation -- same as loss_cluster script."""
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in all_indicators_cache:
            tier_indicators[tier_name] = {
                c: all_indicators_cache[tier_name][c]
                for c in coins if c in all_indicators_cache[tier_name]
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
    print(f'    stress: trades={stress_metrics["trades"]} exp/w=${stress_metrics["exp_per_week"]:.2f}')

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
    print(f'    WF={folds_positive}/5  fold_conc={fold_conc["top1_fold_conc_pct"]:.1f}%')

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    return {
        'label': label,
        'n_coins': sum(len(c) for c in tier_coins.values()),
        'n_t1': len(tier_coins.get('tier1', [])),
        'n_t2': len(tier_coins.get('tier2', [])),
        'metrics': metrics,
        'stress_metrics': {'trades': stress_metrics['trades'], 'pnl': stress_metrics['pnl'],
                          'pf': stress_metrics['pf'], 'exp_per_week': stress_metrics['exp_per_week']},
        'wf_folds_positive': folds_positive, 'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'gate_evaluation': gate_eval, 'runtime_s': round(elapsed, 1),
    }


# ══════════════════════════════════════════════════════════════════════
#  METHOD 1: Split-Half Temporal Test
# ══════════════════════════════════════════════════════════════════════

def method1_split_half(data, tier_coins_full, tier_indicators_full,
                       market_context, tier1_fee, tier2_fee,
                       stress_tier1_fee, stress_tier2_fee):
    """
    Split data into first-half and second-half by bar index.
    1) Run backtest on first half -> identify net-negative coins
    2) Run backtest on second half with full universe vs excluded universe
    3) Compare: does first-half exclusion help on second-half?
    """
    print('\n' + '=' * 70)
    print('  METHOD 1: Split-Half Temporal Test')
    print('  Train exclusion on 1st half, apply to 2nd half')
    print('=' * 70)

    # Find total bars (max across all coins)
    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    start_bar = 50  # standard warmup
    mid_bar = start_bar + (total_bars - start_bar) // 2
    half_bars = (total_bars - start_bar) // 2

    print(f'  total_bars={total_bars}, start_bar={start_bar}, mid_bar={mid_bar}')
    print(f'  1st half: bars {start_bar}-{mid_bar}  ({half_bars} bars, {half_bars/BARS_PER_WEEK:.1f} wks)')
    print(f'  2nd half: bars {mid_bar}-{total_bars}  ({total_bars-mid_bar} bars, '
          f'{(total_bars-mid_bar)/BARS_PER_WEEK:.1f} wks)')

    # ── FIRST HALF: identify negative coins ──
    print(f'\n  [1st half] Running backtest to identify losers...')
    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }
    signal_params = {**BASELINE_PARAMS, '__market__': market_context}

    h1_trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                            market_context, tier1_fee, tier2_fee,
                            start_bar=start_bar, end_bar=mid_bar)
    h1_metrics = compute_metrics(h1_trades, half_bars)
    h1_neg_coins = identify_negative_coins(h1_trades)
    h1_coin_pnl = coin_pnl_from_trades(h1_trades)

    print(f'    1st half: {h1_metrics["trades"]} trades, PF={h1_metrics["pf"]:.3f}, '
          f'P&L=${h1_metrics["pnl"]:.0f}')
    print(f'    Coins with trades: {len(h1_coin_pnl)}')
    print(f'    Net-negative on 1st half: {len(h1_neg_coins)} coins')
    if h1_neg_coins:
        print(f'    Exclusion list: {sorted(h1_neg_coins)}')

    # ── SECOND HALF: full universe vs first-half-excluded ──
    second_half_bars = total_bars - mid_bar
    print(f'\n  [2nd half - FULL] Running on all {sum(len(c) for c in tier_coins_full.values())} coins...')
    h2_full_trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                                 market_context, tier1_fee, tier2_fee,
                                 start_bar=mid_bar, end_bar=total_bars)
    h2_full_metrics = compute_metrics(h2_full_trades, second_half_bars)
    h2_full_stress_trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                                        market_context, stress_tier1_fee, stress_tier2_fee,
                                        start_bar=mid_bar, end_bar=total_bars)
    h2_full_stress_metrics = compute_metrics(h2_full_stress_trades, second_half_bars)

    print(f'    trades={h2_full_metrics["trades"]} PF={h2_full_metrics["pf"]:.3f} '
          f'exp/w=${h2_full_metrics["exp_per_week"]:.2f} DD={h2_full_metrics["max_dd_pct"]:.1f}%')

    # Build excluded tier_coins
    excl_tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in h1_neg_coins],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in h1_neg_coins],
    }
    n_excl = sum(len(c) for c in tier_coins_full.values()) - sum(len(c) for c in excl_tier_coins.values())
    print(f'\n  [2nd half - EXCLUDED] Removing {n_excl} coins identified on 1st half...')
    h2_excl_trades = run_variant(data, excl_tier_coins, tier_indicators_filtered,
                                  market_context, tier1_fee, tier2_fee,
                                  start_bar=mid_bar, end_bar=total_bars)
    h2_excl_metrics = compute_metrics(h2_excl_trades, second_half_bars)
    h2_excl_stress_trades = run_variant(data, excl_tier_coins, tier_indicators_filtered,
                                         market_context, stress_tier1_fee, stress_tier2_fee,
                                         start_bar=mid_bar, end_bar=total_bars)
    h2_excl_stress_metrics = compute_metrics(h2_excl_stress_trades, second_half_bars)

    print(f'    trades={h2_excl_metrics["trades"]} PF={h2_excl_metrics["pf"]:.3f} '
          f'exp/w=${h2_excl_metrics["exp_per_week"]:.2f} DD={h2_excl_metrics["max_dd_pct"]:.1f}%')

    # Check if excluded coins actually lost money on 2nd half too
    h2_coin_pnl = coin_pnl_from_trades(h2_full_trades)
    excl_lost_on_h2 = sum(1 for c in h1_neg_coins if h2_coin_pnl.get(c, 0) < 0)
    excl_won_on_h2 = sum(1 for c in h1_neg_coins if h2_coin_pnl.get(c, 0) > 0)
    excl_no_trades_h2 = sum(1 for c in h1_neg_coins if c not in h2_coin_pnl)
    excl_pnl_on_h2 = sum(h2_coin_pnl.get(c, 0) for c in h1_neg_coins)

    print(f'\n  [Excluded coins fate on 2nd half]')
    print(f'    Still negative: {excl_lost_on_h2}/{len(h1_neg_coins)}')
    print(f'    Turned positive: {excl_won_on_h2}/{len(h1_neg_coins)}')
    print(f'    No trades: {excl_no_trades_h2}/{len(h1_neg_coins)}')
    print(f'    Combined P&L of excluded coins on 2nd half: ${excl_pnl_on_h2:.2f}')

    # Does exclusion help? Compare key metrics
    pnl_delta = h2_excl_metrics['pnl'] - h2_full_metrics['pnl']
    pf_delta = h2_excl_metrics['pf'] - h2_full_metrics['pf']
    dd_delta = h2_excl_metrics['max_dd_pct'] - h2_full_metrics['max_dd_pct']
    helps = h2_excl_metrics['pnl'] > h2_full_metrics['pnl']

    print(f'\n  [Verdict] Exclusion {"HELPS" if helps else "DOES NOT HELP"} on 2nd half')
    print(f'    P&L delta: ${pnl_delta:+.2f}')
    print(f'    PF delta: {pf_delta:+.3f}')
    print(f'    DD delta: {dd_delta:+.1f}%')

    return {
        'method': 'split_half_temporal',
        'total_bars': total_bars,
        'mid_bar': mid_bar,
        'first_half': {
            'bar_range': [start_bar, mid_bar],
            'n_bars': half_bars,
            'metrics': h1_metrics,
            'negative_coins_found': len(h1_neg_coins),
            'negative_coins': sorted(h1_neg_coins),
            'coin_pnl': {c: round(p, 2) for c, p in sorted(h1_coin_pnl.items(), key=lambda x: x[1])},
        },
        'second_half_full': {
            'bar_range': [mid_bar, total_bars],
            'n_bars': second_half_bars,
            'n_coins': sum(len(c) for c in tier_coins_full.values()),
            'metrics': h2_full_metrics,
            'stress_metrics': {'pnl': h2_full_stress_metrics['pnl'],
                               'pf': h2_full_stress_metrics['pf'],
                               'exp_per_week': h2_full_stress_metrics['exp_per_week']},
        },
        'second_half_excluded': {
            'bar_range': [mid_bar, total_bars],
            'n_bars': second_half_bars,
            'n_coins': sum(len(c) for c in excl_tier_coins.values()),
            'n_excluded': n_excl,
            'metrics': h2_excl_metrics,
            'stress_metrics': {'pnl': h2_excl_stress_metrics['pnl'],
                               'pf': h2_excl_stress_metrics['pf'],
                               'exp_per_week': h2_excl_stress_metrics['exp_per_week']},
        },
        'excluded_coins_fate_on_h2': {
            'still_negative': excl_lost_on_h2,
            'turned_positive': excl_won_on_h2,
            'no_trades': excl_no_trades_h2,
            'combined_pnl': round(excl_pnl_on_h2, 2),
        },
        'comparison': {
            'pnl_delta': round(pnl_delta, 2),
            'pf_delta': round(pf_delta, 3),
            'dd_delta': round(dd_delta, 1),
            'exclusion_helps': helps,
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  METHOD 2: Fold-Based Leakage-Free Coin Exclusion
# ══════════════════════════════════════════════════════════════════════

def method2_fold_leakage_free(data, tier_coins_full, tier_indicators_full,
                               market_context, tier1_fee, tier2_fee,
                               stress_tier1_fee, stress_tier2_fee):
    """
    For each walk-forward fold:
    1) Use the TRAINING portion (all other folds) to identify negative coins
    2) Apply that exclusion to the TEST portion (this fold only)
    3) Report per-fold results -> overall gate assessment

    This is the proper no-leakage version: train exclusion list != test data.
    """
    print('\n' + '=' * 70)
    print('  METHOD 2: Fold-Based Leakage-Free Coin Exclusion')
    print('  Per-fold: train exclusion on other folds, apply to this fold')
    print('=' * 70)

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    start_bar = 50
    n_folds = 5
    embargo = 2
    total_range = total_bars - start_bar
    fold_size = total_range // n_folds

    print(f'  total_bars={total_bars}, fold_size={fold_size}, n_folds={n_folds}')

    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }

    # Compute fold boundaries (same as harness walk_forward)
    fold_bounds = []
    for fold_idx in range(n_folds):
        fold_start = start_bar + fold_idx * fold_size
        if fold_idx < n_folds - 1:
            fold_end = fold_start + fold_size - embargo
        else:
            fold_end = total_bars
        fold_bounds.append((fold_start, fold_end))
        print(f'    Fold {fold_idx}: bars {fold_start}-{fold_end} ({fold_end - fold_start} bars)')

    # For each fold: train on all OTHER folds, test on THIS fold
    fold_results = []
    total_test_trades_full = {}     # fold_idx -> trades (full universe)
    total_test_trades_excl = {}     # fold_idx -> trades (excluded)

    for test_fold in range(n_folds):
        test_start, test_end = fold_bounds[test_fold]
        test_bars = test_end - test_start
        print(f'\n  --- Fold {test_fold} (test: bars {test_start}-{test_end}) ---')

        # TRAINING: run backtest on all OTHER folds combined
        train_trades = []
        for train_fold in range(n_folds):
            if train_fold == test_fold:
                continue
            ts, te = fold_bounds[train_fold]
            trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                                 market_context, tier1_fee, tier2_fee,
                                 start_bar=ts, end_bar=te)
            train_trades.extend(trades)

        train_neg_coins = identify_negative_coins(train_trades)
        train_coin_pnl = coin_pnl_from_trades(train_trades)
        print(f'    Training: {len(train_trades)} trades across {len(train_coin_pnl)} coins')
        print(f'    Train-identified negative coins: {len(train_neg_coins)}')

        # TEST - FULL: run on all coins for this fold
        test_full_trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                                       market_context, tier1_fee, tier2_fee,
                                       start_bar=test_start, end_bar=test_end)
        test_full_metrics = compute_metrics(test_full_trades, test_bars)
        total_test_trades_full[test_fold] = test_full_trades

        # TEST - EXCLUDED: remove train-negative coins
        excl_tier_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in train_neg_coins],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in train_neg_coins],
        }
        test_excl_trades = run_variant(data, excl_tier_coins, tier_indicators_filtered,
                                        market_context, tier1_fee, tier2_fee,
                                        start_bar=test_start, end_bar=test_end)
        test_excl_metrics = compute_metrics(test_excl_trades, test_bars)
        total_test_trades_excl[test_fold] = test_excl_trades

        pnl_delta = test_excl_metrics['pnl'] - test_full_metrics['pnl']
        print(f'    Full:     {test_full_metrics["trades"]}tr, PF={test_full_metrics["pf"]:.3f}, '
              f'P&L=${test_full_metrics["pnl"]:.0f}')
        print(f'    Excluded: {test_excl_metrics["trades"]}tr, PF={test_excl_metrics["pf"]:.3f}, '
              f'P&L=${test_excl_metrics["pnl"]:.0f}  (delta=${pnl_delta:+.0f})')

        fold_results.append({
            'fold': test_fold,
            'test_bar_range': [test_start, test_end],
            'train_negative_coins': len(train_neg_coins),
            'train_negative_coins_list': sorted(train_neg_coins),
            'full': {'trades': test_full_metrics['trades'],
                     'pnl': test_full_metrics['pnl'],
                     'pf': test_full_metrics['pf']},
            'excluded': {'trades': test_excl_metrics['trades'],
                         'pnl': test_excl_metrics['pnl'],
                         'pf': test_excl_metrics['pf'],
                         'n_coins': sum(len(c) for c in excl_tier_coins.values())},
            'pnl_delta': round(pnl_delta, 2),
            'exclusion_helped': pnl_delta > 0,
        })

    # Aggregate: compute combined gate assessment for the excluded version
    # Combine all test-fold trades into a single set and fake 'fold_trades' dict
    all_excl_trades = []
    for trades in total_test_trades_excl.values():
        all_excl_trades.extend(trades)
    total_test_bars = total_bars - start_bar  # approximate
    combined_excl_metrics = compute_metrics(all_excl_trades, total_test_bars)

    # Fold-level P&L for gate assessment
    folds_positive_excl = sum(1 for f in fold_results if f['excluded']['pnl'] > 0)
    folds_positive_full = sum(1 for f in fold_results if f['full']['pnl'] > 0)
    fold_conc_excl = compute_fold_concentration(total_test_trades_excl)

    # Also run stress on full period for excluded version to get G4
    excl_all_neg_from_full = set()
    for f in fold_results:
        excl_all_neg_from_full.update(f['train_negative_coins_list'])
    # Use intersection of all train exclusion lists (coins negative in ALL training sets)
    coins_neg_in_all = None
    for f in fold_results:
        s = set(f['train_negative_coins_list'])
        if coins_neg_in_all is None:
            coins_neg_in_all = s
        else:
            coins_neg_in_all = coins_neg_in_all & s

    # Stress test using the union of all fold exclusions (conservative)
    union_excl_tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_all_neg_from_full],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_all_neg_from_full],
    }
    stress_trades = run_variant(data, union_excl_tier_coins, tier_indicators_filtered,
                                market_context, stress_tier1_fee, stress_tier2_fee)
    stress_metrics = compute_metrics(stress_trades, total_bars)

    gate_eval = evaluate_gates(combined_excl_metrics, folds_positive_excl, n_folds,
                               stress_metrics, fold_conc_excl)

    n_folds_helped = sum(1 for f in fold_results if f['exclusion_helped'])
    print(f'\n  [Summary]')
    print(f'    Folds where exclusion helped: {n_folds_helped}/{n_folds}')
    print(f'    Full-universe WF positive folds: {folds_positive_full}/{n_folds}')
    print(f'    Excluded-universe WF positive folds: {folds_positive_excl}/{n_folds}')
    print(f'    Coins negative in ALL training sets: {len(coins_neg_in_all or set())}')
    print(f'    Gate score (leakage-free): {gate_eval["score"]}')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    return {
        'method': 'fold_leakage_free',
        'n_folds': n_folds,
        'fold_results': fold_results,
        'aggregate': {
            'folds_exclusion_helped': n_folds_helped,
            'folds_positive_full': folds_positive_full,
            'folds_positive_excl': folds_positive_excl,
            'coins_negative_in_all_training_sets': sorted(coins_neg_in_all or set()),
            'n_coins_neg_all_training': len(coins_neg_in_all or set()),
            'union_excluded_coins': sorted(excl_all_neg_from_full),
            'n_union_excluded': len(excl_all_neg_from_full),
            'combined_excl_metrics': combined_excl_metrics,
            'stress_metrics': {'pnl': stress_metrics['pnl'], 'pf': stress_metrics['pf'],
                               'exp_per_week': stress_metrics['exp_per_week']},
            'fold_concentration': fold_conc_excl,
            'gate_evaluation': gate_eval,
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  METHOD 3: Stability Check (3-Period Consistency)
# ══════════════════════════════════════════════════════════════════════

def method3_stability(data, tier_coins_full, tier_indicators_full,
                      market_context, tier1_fee, tier2_fee):
    """
    Split into 3 equal time periods.
    Check how many of the 21 full-sample-excluded coins are net-negative
    in ALL 3, in 2/3, or in 1/3.
    High consistency = structural feature, not noise.
    """
    print('\n' + '=' * 70)
    print('  METHOD 3: Stability Check (3-Period Consistency)')
    print('  How many of the 21 excluded coins are consistently negative?')
    print('=' * 70)

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    start_bar = 50
    total_range = total_bars - start_bar
    period_size = total_range // 3

    tier_indicators_filtered = {}
    for tier_name, coins in tier_coins_full.items():
        if tier_name in tier_indicators_full:
            tier_indicators_filtered[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }

    periods = []
    for p in range(3):
        p_start = start_bar + p * period_size
        if p < 2:
            p_end = p_start + period_size
        else:
            p_end = total_bars
        periods.append((p_start, p_end))
        print(f'  Period {p+1}: bars {p_start}-{p_end} ({p_end - p_start} bars, '
              f'{(p_end - p_start)/BARS_PER_WEEK:.1f} wks)')

    # Run backtest on each period, track per-coin P&L
    period_coin_pnls = []  # list of dicts: coin -> pnl
    for p_idx, (p_start, p_end) in enumerate(periods):
        trades = run_variant(data, tier_coins_full, tier_indicators_filtered,
                             market_context, tier1_fee, tier2_fee,
                             start_bar=p_start, end_bar=p_end)
        coin_pnl = coin_pnl_from_trades(trades)
        period_coin_pnls.append(coin_pnl)
        n_trades = len(trades)
        total_pnl = sum(t['pnl'] for t in trades)
        n_neg = sum(1 for p in coin_pnl.values() if p < 0)
        print(f'  Period {p_idx+1}: {n_trades} trades, P&L=${total_pnl:.0f}, '
              f'{len(coin_pnl)} coins w/ trades, {n_neg} net-negative')

    # For each of the 21 excluded coins, check consistency
    excluded_set = set(FULL_SAMPLE_EXCLUDED)
    coin_period_status = {}  # coin -> [neg_in_p1, neg_in_p2, neg_in_p3]
    for coin in FULL_SAMPLE_EXCLUDED:
        statuses = []
        for p_idx in range(3):
            pnl = period_coin_pnls[p_idx].get(coin, 0)
            # 'no_trade' means no signal -- not negative, but not positive either
            if coin not in period_coin_pnls[p_idx]:
                statuses.append('no_trade')
            elif pnl < 0:
                statuses.append('negative')
            elif pnl > 0:
                statuses.append('positive')
            else:
                statuses.append('zero')
        coin_period_status[coin] = statuses

    # Count consistency levels
    neg_all_3 = []
    neg_2_of_3 = []
    neg_1_of_3 = []
    neg_0_of_3 = []

    for coin, statuses in coin_period_status.items():
        n_neg = statuses.count('negative')
        if n_neg >= 3:
            neg_all_3.append(coin)
        elif n_neg == 2:
            neg_2_of_3.append(coin)
        elif n_neg == 1:
            neg_1_of_3.append(coin)
        else:
            neg_0_of_3.append(coin)

    # Also count: negative OR no_trade (i.e., never profitable)
    never_profitable = []
    for coin, statuses in coin_period_status.items():
        if 'positive' not in statuses:
            never_profitable.append(coin)

    print(f'\n  [Consistency of 21 excluded coins across 3 periods]')
    print(f'    Negative in ALL 3 periods:  {len(neg_all_3)}/21')
    print(f'    Negative in 2/3 periods:    {len(neg_2_of_3)}/21')
    print(f'    Negative in 1/3 periods:    {len(neg_1_of_3)}/21')
    print(f'    Negative in 0/3 periods:    {len(neg_0_of_3)}/21')
    print(f'    Never profitable (neg or no trade in all): {len(never_profitable)}/21')

    # Detailed per-coin table
    print(f'\n  Per-coin detail:')
    print(f'    {"Coin":15s} | {"P1":>10s} | {"P2":>10s} | {"P3":>10s} | Consistency')
    print(f'    {"-"*15}-+-{"-"*10}-+-{"-"*10}-+-{"-"*10}-+-----------')
    for coin in sorted(FULL_SAMPLE_EXCLUDED):
        vals = []
        for p_idx in range(3):
            pnl = period_coin_pnls[p_idx].get(coin, None)
            if pnl is None:
                vals.append('  no_trade')
            else:
                vals.append(f'${pnl:>+9.2f}')
        statuses = coin_period_status[coin]
        n_neg = statuses.count('negative')
        cons = f'{n_neg}/3 neg'
        if coin in never_profitable:
            cons += ' [NEVER PROF]'
        print(f'    {coin:15s} | {vals[0]} | {vals[1]} | {vals[2]} | {cons}')

    stability_score = (len(neg_all_3) + len(neg_2_of_3)) / 21 * 100
    print(f'\n  Stability score: {stability_score:.0f}% '
          f'(coins negative in >=2/3 periods: {len(neg_all_3)+len(neg_2_of_3)}/21)')

    return {
        'method': 'stability_3period',
        'periods': [{'start': s, 'end': e, 'n_bars': e - s} for s, e in periods],
        'full_sample_excluded_coins': FULL_SAMPLE_EXCLUDED,
        'coin_period_detail': {
            coin: {
                'statuses': coin_period_status[coin],
                'pnls': [round(period_coin_pnls[p].get(coin, 0), 2) for p in range(3)],
                'n_negative_periods': coin_period_status[coin].count('negative'),
            }
            for coin in FULL_SAMPLE_EXCLUDED
        },
        'consistency': {
            'neg_all_3': sorted(neg_all_3),
            'neg_2_of_3': sorted(neg_2_of_3),
            'neg_1_of_3': sorted(neg_1_of_3),
            'neg_0_of_3': sorted(neg_0_of_3),
            'never_profitable': sorted(never_profitable),
        },
        'counts': {
            'neg_all_3': len(neg_all_3),
            'neg_2_of_3': len(neg_2_of_3),
            'neg_1_of_3': len(neg_1_of_3),
            'neg_0_of_3': len(neg_0_of_3),
            'never_profitable': len(never_profitable),
        },
        'stability_score_pct': round(stability_score, 1),
    }


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='OOS Validation: excl_all_negative bias test')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C2-A3: OOS Validation of excl_all_negative')
    print('  Question: Is coin exclusion forward-looking bias or structural?')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')

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
        print(f'  Full-sample excluded coins: {len(FULL_SAMPLE_EXCLUDED)}')
        print(f'  Methods: split_half, fold_leakage_free, stability_3period')
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

    # ── RUN ALL 3 METHODS ──
    m1_result = method1_split_half(
        data, tier_coins_full, tier_indicators_full, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee)

    m2_result = method2_fold_leakage_free(
        data, tier_coins_full, tier_indicators_full, market_context,
        tier1_fee, tier2_fee, stress_tier1_fee, stress_tier2_fee)

    m3_result = method3_stability(
        data, tier_coins_full, tier_indicators_full, market_context,
        tier1_fee, tier2_fee)

    elapsed_total = time.time() - t0_total

    # ── OVERALL VERDICT ──
    m1_helps = m1_result['comparison']['exclusion_helps']
    m2_folds_helped = m2_result['aggregate']['folds_exclusion_helped']
    m2_folds_total = m2_result['n_folds']
    m3_stable = m3_result['counts']['neg_all_3'] + m3_result['counts']['neg_2_of_3']
    m3_never_prof = m3_result['counts']['never_profitable']

    # Verdict logic
    evidence_for_structural = 0
    evidence_against = 0

    if m1_helps:
        evidence_for_structural += 1
    else:
        evidence_against += 1

    if m2_folds_helped >= 3:
        evidence_for_structural += 1
    elif m2_folds_helped >= 2:
        pass  # neutral
    else:
        evidence_against += 1

    if m3_stable >= 14:  # 2/3 of 21
        evidence_for_structural += 1
    elif m3_stable >= 10:
        pass  # neutral
    else:
        evidence_against += 1

    if evidence_for_structural >= 2:
        verdict = 'STRUCTURAL_FEATURE'
        verdict_detail = ('excl_all_negative is predominantly a STRUCTURAL feature, '
                          'not pure forward-looking bias. The exclusion helps OOS.')
    elif evidence_against >= 2:
        verdict = 'FORWARD_LOOKING_BIAS'
        verdict_detail = ('excl_all_negative is likely FORWARD-LOOKING BIAS. '
                          'The exclusion does NOT reliably help OOS.')
    else:
        verdict = 'MIXED_EVIDENCE'
        verdict_detail = ('Mixed evidence. Some structural signal exists but the '
                          'exclusion is not robustly forward-stable.')

    print('\n' + '=' * 70)
    print('  OVERALL VERDICT')
    print('=' * 70)
    print(f'  Method 1 (split-half): exclusion {"HELPS" if m1_helps else "DOES NOT HELP"}')
    print(f'  Method 2 (fold-based): {m2_folds_helped}/{m2_folds_total} folds helped')
    print(f'  Method 3 (stability):  {m3_stable}/21 coins neg in >=2/3 periods, '
          f'{m3_never_prof}/21 never profitable')
    print(f'  --> VERDICT: {verdict}')
    print(f'  {verdict_detail}')

    # Leakage-free gate score
    m2_gate = m2_result['aggregate']['gate_evaluation']
    print(f'\n  Leakage-free gate score: {m2_gate["score"]}')
    for gid, g in m2_gate['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'    {gid}: {g["name"]} = {g["value"]}  -> {status}')

    # ── BUILD JSON REPORT ──
    report = {
        'run_header': {
            'task': 'part2_oos_validation',
            'agent': 'C2-A3',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': BASELINE_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'runtime_s': round(elapsed_total, 1),
            'full_sample_excluded_coins': FULL_SAMPLE_EXCLUDED,
        },
        'method1_split_half': m1_result,
        'method2_fold_leakage_free': m2_result,
        'method3_stability': m3_result,
        'overall_verdict': {
            'verdict': verdict,
            'detail': verdict_detail,
            'evidence_for_structural': evidence_for_structural,
            'evidence_against': evidence_against,
            'method1_helps': m1_helps,
            'method2_folds_helped': f'{m2_folds_helped}/{m2_folds_total}',
            'method3_stable_coins': f'{m3_stable}/21',
            'method3_never_profitable': f'{m3_never_prof}/21',
            'leakage_free_gate_score': m2_gate['score'],
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_oos_validation_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ── BUILD MARKDOWN REPORT ──
    md = []
    md.append('# Part 2 -- OOS Validation: excl_all_negative Bias Test (Agent C2-A3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={BASELINE_PARAMS["dev_thresh"]}, tp={BASELINE_PARAMS["tp_pct"]}, '
              f'sl={BASELINE_PARAMS["sl_pct"]}, tl={BASELINE_PARAMS["time_limit"]}')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')
    md.append('## Question')
    md.append('')
    md.append('The `excl_all_negative` strategy removes 21 coins that are net-negative on the FULL ')
    md.append('in-sample period. This achieves 7/7 gates. But is this forward-looking bias?')
    md.append('In live trading, we cannot know which coins will be losers in advance.')
    md.append('')

    # Method 1
    md.append('## Method 1: Split-Half Temporal Test')
    md.append('')
    md.append('Train exclusion list on the 1st half of the data, apply to 2nd half only.')
    md.append('')
    m1h1 = m1_result['first_half']
    md.append(f'- **1st half**: bars {m1h1["bar_range"][0]}-{m1h1["bar_range"][1]} '
              f'({m1h1["n_bars"]} bars)')
    md.append(f'- **Negative coins found on 1st half**: {m1h1["negative_coins_found"]}')
    md.append('')
    md.append('### 2nd Half Comparison')
    md.append('')
    h2f = m1_result['second_half_full']['metrics']
    h2e = m1_result['second_half_excluded']['metrics']
    md.append('| Metric | Full Universe | 1st-Half-Excluded | Delta |')
    md.append('|--------|-------------|-------------------|-------|')
    md.append(f'| Trades | {h2f["trades"]} | {h2e["trades"]} | {h2e["trades"]-h2f["trades"]:+d} |')
    md.append(f'| P&L | ${h2f["pnl"]:.0f} | ${h2e["pnl"]:.0f} | ${m1_result["comparison"]["pnl_delta"]:+.0f} |')
    md.append(f'| PF | {h2f["pf"]:.3f} | {h2e["pf"]:.3f} | {m1_result["comparison"]["pf_delta"]:+.3f} |')
    md.append(f'| DD% | {h2f["max_dd_pct"]:.1f}% | {h2e["max_dd_pct"]:.1f}% | {m1_result["comparison"]["dd_delta"]:+.1f}% |')
    md.append(f'| Exp/wk | ${h2f["exp_per_week"]:.2f} | ${h2e["exp_per_week"]:.2f} | |')
    md.append('')
    fate = m1_result['excluded_coins_fate_on_h2']
    md.append(f'**Excluded coins on 2nd half**: {fate["still_negative"]} still neg, '
              f'{fate["turned_positive"]} turned positive, {fate["no_trades"]} no trades, '
              f'combined P&L=${fate["combined_pnl"]:.0f}')
    md.append('')
    md.append(f'**Verdict**: Exclusion **{"HELPS" if m1_helps else "DOES NOT HELP"}** on 2nd half '
              f'(P&L delta: ${m1_result["comparison"]["pnl_delta"]:+.0f})')
    md.append('')

    # Method 2
    md.append('## Method 2: Fold-Based Leakage-Free Exclusion')
    md.append('')
    md.append('For each WF fold: identify negative coins on training folds, exclude them on test fold.')
    md.append('')
    md.append('| Fold | Full Trades | Full P&L | Excl Trades | Excl P&L | Delta | Helped? |')
    md.append('|------|------------|----------|-------------|----------|-------|---------|')
    for f in m2_result['fold_results']:
        helped = 'YES' if f['exclusion_helped'] else 'NO'
        md.append(f'| {f["fold"]} | {f["full"]["trades"]} | ${f["full"]["pnl"]:.0f} '
                  f'| {f["excluded"]["trades"]} | ${f["excluded"]["pnl"]:.0f} '
                  f'| ${f["pnl_delta"]:+.0f} | {helped} |')
    md.append('')
    agg = m2_result['aggregate']
    md.append(f'- **Folds where exclusion helped**: {agg["folds_exclusion_helped"]}/{m2_result["n_folds"]}')
    md.append(f'- **Leakage-free WF positive folds**: {agg["folds_positive_excl"]}/{m2_result["n_folds"]}')
    md.append(f'- **Coins negative in ALL training sets**: {agg["n_coins_neg_all_training"]}')
    md.append('')
    md.append(f'### Leakage-Free Gate Assessment')
    md.append('')
    md.append('| Gate | Metric | Value | Threshold | Verdict |')
    md.append('|------|--------|-------|-----------|---------|')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = m2_gate['gates'][gid]
        status = 'PASS' if g['pass'] else '**FAIL**'
        md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
    md.append('')
    md.append(f'**Leakage-free gate score: {m2_gate["score"]}**')
    md.append('')

    # Method 3
    md.append('## Method 3: Stability Check (3-Period Consistency)')
    md.append('')
    md.append('Split into 3 equal periods, check how many of the 21 excluded coins are ')
    md.append('consistently negative.')
    md.append('')
    md.append(f'| Consistency | Count | Coins |')
    md.append(f'|------------|-------|-------|')
    m3c = m3_result['consistency']
    md.append(f'| Neg in ALL 3 periods | {m3_result["counts"]["neg_all_3"]}/21 '
              f'| {", ".join(m3c["neg_all_3"]) if m3c["neg_all_3"] else "-"} |')
    md.append(f'| Neg in 2/3 periods | {m3_result["counts"]["neg_2_of_3"]}/21 '
              f'| {", ".join(m3c["neg_2_of_3"]) if m3c["neg_2_of_3"] else "-"} |')
    md.append(f'| Neg in 1/3 periods | {m3_result["counts"]["neg_1_of_3"]}/21 '
              f'| {", ".join(m3c["neg_1_of_3"]) if m3c["neg_1_of_3"] else "-"} |')
    md.append(f'| Neg in 0/3 periods | {m3_result["counts"]["neg_0_of_3"]}/21 '
              f'| {", ".join(m3c["neg_0_of_3"]) if m3c["neg_0_of_3"] else "-"} |')
    md.append(f'| Never profitable | {m3_result["counts"]["never_profitable"]}/21 '
              f'| {", ".join(m3c["never_profitable"]) if m3c["never_profitable"] else "-"} |')
    md.append('')
    md.append(f'**Stability score**: {m3_result["stability_score_pct"]:.0f}% '
              f'(coins neg in >=2/3 periods)')
    md.append('')

    # Overall verdict
    md.append('## Overall Verdict')
    md.append('')
    md.append(f'| Method | Evidence |')
    md.append(f'|--------|----------|')
    md.append(f'| M1: Split-half | {"HELPS" if m1_helps else "NO HELP"} on 2nd half |')
    md.append(f'| M2: Fold-based | {m2_folds_helped}/{m2_folds_total} folds helped, '
              f'gate={m2_gate["score"]} |')
    md.append(f'| M3: Stability  | {m3_stable}/21 coins stable-negative, '
              f'{m3_never_prof}/21 never profitable |')
    md.append('')
    md.append(f'### **VERDICT: {verdict}**')
    md.append('')
    md.append(f'{verdict_detail}')
    md.append('')
    md.append(f'- Evidence for structural feature: {evidence_for_structural}')
    md.append(f'- Evidence against (forward bias): {evidence_against}')
    md.append('')

    if verdict == 'STRUCTURAL_FEATURE':
        md.append('### Implication')
        md.append('')
        md.append('The coin exclusion approach has out-of-sample support. In production, a ')
        md.append('rolling lookback window could be used to identify and exclude persistently ')
        md.append('negative coins without forward-looking bias.')
    elif verdict == 'FORWARD_LOOKING_BIAS':
        md.append('### Implication')
        md.append('')
        md.append('The 7/7 gate score from excl_all_negative is inflated by in-sample knowledge. ')
        md.append('The actual leakage-free gate score is more representative of live performance.')
    else:
        md.append('### Implication')
        md.append('')
        md.append('Some structural signal exists in coin exclusion, but it is not fully robust. ')
        md.append('A conservative approach would be to exclude only the most consistently ')
        md.append('negative coins (those negative across ALL time periods).')

    md.append('')
    md.append('---')
    md.append(f'*Generated by run_part2_oos_validation.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_oos_validation_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: OOS Validation of excl_all_negative')
    print(f'  Verdict: {verdict}')
    print(f'  Leakage-free gates: {m2_gate["score"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
