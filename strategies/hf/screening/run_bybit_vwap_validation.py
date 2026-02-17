#!/usr/bin/env python3
"""
Bybit Real VWAP Validation Runner
===================================
Runs H20 VWAP_DEVIATION (original, NOT z-score) on Bybit candle data with
REAL volume-weighted VWAP (from 1m aggregation) vs HLC3 proxy.

This is the definitive apples-to-apples comparison:
  - Same coins (MEXC ∩ Bybit intersection)
  - Same signal (H20 raw, dev_thresh=2.0)
  - Same VWAP definition (volume-weighted typical price)
  - Only difference: exchange microstructure

Runs the full 24-combo matrix (2 configs × 4 regimes × 3 sizes) and
produces a comparison report showing:
  - Trigger counts (real VWAP vs HLC3)
  - Trade counts (real VWAP vs HLC3)
  - Gate pass rates
  - VWAP divergence statistics

Usage:
    python -m strategies.hf.screening.run_bybit_vwap_validation
    python -m strategies.hf.screening.run_bybit_vwap_validation --config v5 --skip-fill-model
    python -m strategies.hf.screening.run_bybit_vwap_validation --dry-run
"""
import hashlib
import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

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
from strategies.hf.screening.costs_mexc_v2 import (
    register_regime, COST_REGIMES,
)
from strategies.hf.screening.fill_model_v3 import full_fill_model_v3
from strategies.hf.screening.orderbook_analysis import (
    load_snapshots, compute_distributions, build_measured_regimes,
)
from strategies.hf.screening.exchange_config import (
    add_exchange_args, build_fee_snapshot, get_exchange,
)

# ============================================================
# Constants (identical to run_multi_exchange_validation.py)
# ============================================================

BARS_PER_WEEK = 168
BARS_PER_DAY = 24

CONFIGS = {
    'v5': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
    'sl7': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10},
}

REGIMES_TO_TEST = [
    'measured_ob_maker_p50', 'measured_ob_maker_p90',
    'measured_ob_taker_p50', 'measured_ob_taker_p90',
]

SIZES = [200, 500, 2000]

# Minimum 1m bar coverage per coin to be included (90% of expected)
MIN_COVERAGE_PCT = 90.0


# ============================================================
# Guardrail helpers
# ============================================================

def compute_file_hash(filepath):
    """MD5 hash of a file for reproducibility."""
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def compute_time_window(data, coins):
    """Extract exact time window from candle data.

    Returns: {start_ts, end_ts, start_dt, end_dt, total_bars, total_hours}
    """
    min_ts = None
    max_ts = None
    max_bars = 0

    for coin in coins:
        candles = data.get(coin, [])
        if not candles:
            continue
        ts_key = 'timestamp' if 'timestamp' in candles[0] else 'time'
        first_ts = candles[0][ts_key]
        last_ts = candles[-1][ts_key]
        # Normalize to milliseconds
        if first_ts < 1e12:
            first_ts *= 1000
        if last_ts < 1e12:
            last_ts *= 1000
        if min_ts is None or first_ts < min_ts:
            min_ts = first_ts
        if max_ts is None or last_ts > max_ts:
            max_ts = last_ts
        if len(candles) > max_bars:
            max_bars = len(candles)

    if min_ts is None:
        return None

    start_dt = datetime.fromtimestamp(min_ts / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc)

    return {
        'start_ts': int(min_ts),
        'end_ts': int(max_ts),
        'start_dt': start_dt.strftime('%Y-%m-%d %H:%M UTC'),
        'end_dt': end_dt.strftime('%Y-%m-%d %H:%M UTC'),
        'total_bars': max_bars,
        'total_hours': round((max_ts - min_ts) / 3600_000, 1),
    }


def coverage_gate(data, coins):
    """Compute per-coin 1H bar coverage and apply exclusion threshold.

    Returns: (included_coins, excluded_coins, coverage_report)
    """
    # Find the max possible bars from the dataset
    all_bars = [len(data.get(c, [])) for c in coins if c in data]
    if not all_bars:
        return [], list(coins), []

    target_bars = max(all_bars)  # Best coverage coin sets the benchmark
    included = []
    excluded = []
    report = []

    for coin in coins:
        candles = data.get(coin, [])
        n_bars = len(candles)
        coverage_pct = (n_bars / target_bars * 100) if target_bars > 0 else 0.0

        # Check for real VWAP source
        n_real_vwap = 0
        if candles:
            n_real_vwap = sum(1 for c in candles
                              if c.get('_vwap_source') == 'real_1m')

        entry = {
            'coin': coin,
            'bars': n_bars,
            'target_bars': target_bars,
            'coverage_pct': round(coverage_pct, 1),
            'real_vwap_bars': n_real_vwap,
            'real_vwap_pct': round(n_real_vwap / n_bars * 100, 1) if n_bars > 0 else 0.0,
        }
        report.append(entry)

        if coverage_pct >= MIN_COVERAGE_PCT and n_real_vwap > 0:
            included.append(coin)
        else:
            excluded.append(coin)
            entry['excluded_reason'] = (
                'low_coverage' if coverage_pct < MIN_COVERAGE_PCT
                else 'no_real_vwap'
            )

    return included, excluded, report


def per_coin_trigger_breakdown(data, coins, indicators, params):
    """Per-coin trigger + trade diagnostic for top-N coins.

    Returns list of {coin, triggers_real_vwap, triggers_hlc3, bars, ...}
    """
    enriched = {**params, '__market__': {}}
    results = []

    for coin in coins:
        ind = indicators.get(coin, {})
        n = ind.get('n', 0)
        triggers = 0
        bars_above_2 = 0
        candidates_no_bounce = 0  # dev>=2.0 ignoring bounce filter
        max_dev = float('-inf')

        vwaps = ind.get('vwaps', [])
        atr_list = ind.get('atr', [])
        closes = ind.get('closes', [])

        for bar in range(1, n):
            # Count triggers (full signal including bounce)
            result = signal_h20_vwap_deviation(data[coin], bar, ind, enriched)
            if result is not None:
                triggers += 1

            # Count dev >= 2.0 (ignoring bounce filter) + track max_dev
            if (bar < len(vwaps) and vwaps[bar] is not None
                    and bar < len(atr_list) and atr_list[bar] is not None
                    and atr_list[bar] > 0 and closes[bar] > 0):
                dev = (vwaps[bar] - closes[bar]) / atr_list[bar]
                if dev > max_dev:
                    max_dev = dev
                if dev >= 2.0:
                    bars_above_2 += 1
                    # Check if bounce filter killed this candidate
                    prev_close = data[coin][bar - 1]['close'] if bar > 0 else 0
                    if closes[bar] > prev_close:
                        candidates_no_bounce += 0  # would have triggered
                    else:
                        candidates_no_bounce += 1  # bounce filter blocked it

        results.append({
            'coin': coin,
            'bars': n,
            'triggers': triggers,
            'bars_dev_above_2': bars_above_2,
            'blocked_by_bounce': candidates_no_bounce,
            'max_dev': round(max_dev, 4) if max_dev > float('-inf') else None,
        })

    return sorted(results, key=lambda x: -x['triggers'])


# ============================================================
# Reuse metric/gate functions from run_multi_exchange_validation
# ============================================================

from strategies.hf.screening.run_multi_exchange_validation import (
    compute_metrics, compute_max_gap, compute_fold_concentration,
    evaluate_gates_strict, tier_pnl_breakdown,
    build_size_specific_regime, get_half_spread_for_fill,
    compute_stress_fees,
    load_universe_tiering_exchange, build_tier_coins,
)


# ============================================================
# Signal trigger diagnostic
# ============================================================

def count_triggers(data, coins, indicators, params):
    """Count how many signal triggers H20 fires across all coins/bars.

    Returns: (total_triggers, coins_with_triggers, trigger_details)
    """
    total = 0
    coins_with = 0
    details = []

    enriched = {**params, '__market__': {}}  # Dummy market context for counting

    for coin in coins:
        ind = indicators.get(coin, {})
        n = ind.get('n', 0)
        coin_triggers = 0

        for bar in range(1, n):
            result = signal_h20_vwap_deviation(data[coin], bar, ind, enriched)
            if result is not None:
                coin_triggers += 1

        if coin_triggers > 0:
            coins_with += 1
            details.append({'coin': coin, 'triggers': coin_triggers})

        total += coin_triggers

    return total, coins_with, details


def count_vwap_availability(data, coins, indicators):
    """Count VWAP statistics across coins/bars.

    Returns dict with stats about VWAP deviation magnitudes.
    """
    deviations = []
    coins_with_vwap = 0
    bars_with_vwap = 0
    total_bars = 0

    for coin in coins:
        ind = indicators.get(coin, {})
        n = ind.get('n', 0)
        if not ind.get('has_vwap', False):
            continue

        coins_with_vwap += 1
        vwaps = ind.get('vwaps', [])
        atr_list = ind.get('atr', [])
        closes = ind.get('closes', [])

        for bar in range(n):
            total_bars += 1
            if (bar < len(vwaps) and vwaps[bar] is not None
                    and bar < len(atr_list) and atr_list[bar] is not None
                    and atr_list[bar] > 0 and closes[bar] > 0):
                bars_with_vwap += 1
                dev = (vwaps[bar] - closes[bar]) / atr_list[bar]
                deviations.append(dev)

    if not deviations:
        return {
            'coins_with_vwap': 0, 'bars_with_vwap': 0, 'total_bars': total_bars,
            'deviations': {},
        }

    deviations.sort()
    n = len(deviations)
    pos_devs = [d for d in deviations if d >= 2.0]
    return {
        'coins_with_vwap': coins_with_vwap,
        'bars_with_vwap': bars_with_vwap,
        'total_bars': total_bars,
        'deviations': {
            'count': n,
            'min': round(deviations[0], 4),
            'p25': round(deviations[n // 4], 4),
            'median': round(deviations[n // 2], 4),
            'p75': round(deviations[3 * n // 4], 4),
            'p90': round(deviations[int(n * 0.9)], 4),
            'p95': round(deviations[int(n * 0.95)], 4),
            'p99': round(deviations[int(n * 0.99)], 4),
            'max': round(deviations[-1], 4),
            'above_2': len(pos_devs),
            'above_2_pct': round(len(pos_devs) / n * 100, 3) if n > 0 else 0.0,
        },
    }


# ============================================================
# Backtest runners (accept signal_fn)
# ============================================================

def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                 market_ctx, t1_fee, t2_fee, params, initial_capital=2000.0):
    """Run backtests for T1 and T2 separately with H20 raw signal."""
    enriched = {**params, '__market__': market_ctx}
    all_trades = []

    if t1_coins:
        bt_t1 = run_backtest(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t1.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = t1_fee
        all_trades.extend(bt_t1.trade_list)

    if t2_coins:
        bt_t2 = run_backtest(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, fee=t2_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t2.trade_list:
            t['_tier'] = 'tier2'
            t['_fee_per_side'] = t2_fee
        all_trades.extend(bt_t2.trade_list)

    return all_trades


def run_combined_wf(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                    market_ctx, t1_fee, t2_fee, params, n_folds=5,
                    initial_capital=2000.0):
    """Run walk-forward with H20 raw signal."""
    enriched = {**params, '__market__': market_ctx}
    fold_trades = {}

    if t1_coins:
        t1_results = walk_forward(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, n_folds=n_folds,
            fee=t1_fee, max_pos=1, initial_capital=initial_capital,
        )
        for idx, fold_bt in enumerate(t1_results):
            if idx not in fold_trades:
                fold_trades[idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = 'tier1'
                t['_fee_per_side'] = t1_fee
            fold_trades[idx].extend(fold_bt.trade_list)

    if t2_coins:
        t2_results = walk_forward(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, n_folds=n_folds,
            fee=t2_fee, max_pos=1, initial_capital=initial_capital,
        )
        for idx, fold_bt in enumerate(t2_results):
            if idx not in fold_trades:
                fold_trades[idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = 'tier2'
                t['_fee_per_side'] = t2_fee
            fold_trades[idx].extend(fold_bt.trade_list)

    return fold_trades


# ============================================================
# analyze_combination (identical logic to parent, but local signal)
# ============================================================

def analyze_combination(
    config_name, config_params, regime_name, regime, size,
    data, t1_coins, t2_coins, t1_indicators, t2_indicators,
    market_ctx, total_bars, distributions, skip_fill_model=False,
):
    """Run full analysis for one config x regime x size combination."""
    t_start = time.time()
    exec_mode = regime.get('execution_mode', '')

    t1_fee = regime['tier1']['total_per_side_bps'] / 10000.0
    t2_fee = regime['tier2']['total_per_side_bps'] / 10000.0

    label = f'{config_name}/{regime_name}/${size}'
    print(f'  [{label}] fees T1={regime["tier1"]["total_per_side_bps"]}bps '
          f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # Baseline backtest
    print(f'  [{label}] Running baseline backtest...')
    trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, initial_capital=size,
    )
    pre_fill_count = len(trades)
    pre_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    # Fill model
    fill_result = None
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)

        t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
        t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
        surviving = []

        fill_summary_combined = {
            'total': len(trades), 'filled': 0, 'missed': 0,
            'fill_rate': 0.0, 'tier_detail': {},
        }

        if t1_trades and hs_t1 > 0:
            fm_t1 = full_fill_model_v3(t1_trades, data, half_spread_bps=hs_t1)
            surviving.extend(fm_t1['trades'])
            fill_summary_combined['tier_detail']['tier1'] = fm_t1['fill_summary']
            fill_summary_combined['filled'] += fm_t1['fill_summary']['filled']
            fill_summary_combined['missed'] += fm_t1['fill_summary']['missed']
        elif t1_trades:
            surviving.extend(t1_trades)
            fill_summary_combined['filled'] += len(t1_trades)

        if t2_trades and hs_t2 > 0:
            fm_t2 = full_fill_model_v3(t2_trades, data, half_spread_bps=hs_t2)
            surviving.extend(fm_t2['trades'])
            fill_summary_combined['tier_detail']['tier2'] = fm_t2['fill_summary']
            fill_summary_combined['filled'] += fm_t2['fill_summary']['filled']
            fill_summary_combined['missed'] += fm_t2['fill_summary']['missed']
        elif t2_trades:
            surviving.extend(t2_trades)
            fill_summary_combined['filled'] += len(t2_trades)

        total_fm = fill_summary_combined['filled'] + fill_summary_combined['missed']
        fill_summary_combined['fill_rate'] = (
            fill_summary_combined['filled'] / total_fm if total_fm > 0 else 0.0
        )
        trades = surviving
        fill_result = fill_summary_combined
    elif not skip_fill_model and 'taker' in exec_mode:
        fill_result = {
            'total': len(trades), 'filled': len(trades), 'missed': 0,
            'fill_rate': 1.0, 'note': 'taker mode: market orders always fill',
        }

    post_fill_count = len(trades)
    post_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    m = compute_metrics(trades, total_bars, initial_capital=size)
    tb = tier_pnl_breakdown(trades)

    if len(trades) >= 2:
        max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    else:
        max_gap_days = total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
        max_gap_bars = total_bars

    print(f'    Baseline: {pre_fill_count}tr -> {post_fill_count}tr (post-fill) '
          f'PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
          f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    # Stress 2x
    stress_fees = compute_stress_fees(regime, 2.0)
    print(f'  [{label}] Running stress 2x backtest '
          f'(T1={stress_fees["tier1_bps"]}bps, T2={stress_fees["tier2_bps"]}bps)...')
    stress_trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, stress_fees['tier1_fee'], stress_fees['tier2_fee'],
        config_params, initial_capital=size,
    )

    # Apply fill model to stress trades
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)
        st1 = [t for t in stress_trades if t.get('_tier') == 'tier1']
        st2 = [t for t in stress_trades if t.get('_tier') == 'tier2']
        stress_surviving = []
        if st1 and hs_t1 > 0:
            fm = full_fill_model_v3(st1, data, half_spread_bps=hs_t1)
            stress_surviving.extend(fm['trades'])
        elif st1:
            stress_surviving.extend(st1)
        if st2 and hs_t2 > 0:
            fm = full_fill_model_v3(st2, data, half_spread_bps=hs_t2)
            stress_surviving.extend(fm['trades'])
        elif st2:
            stress_surviving.extend(st2)
        stress_trades = stress_surviving

    sm = compute_metrics(stress_trades, total_bars, initial_capital=size)
    print(f'    Stress: {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.2f}')

    # Walk-Forward 5-fold
    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_combined_wf(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, n_folds=5,
        initial_capital=size,
    )

    # Apply fill model per fold
    wf_folds_positive = 0
    fold_pnls = []
    fold_details = []
    for fi in sorted(fold_trades.keys()):
        fold_tr = fold_trades[fi]

        if not skip_fill_model and 'maker' in exec_mode:
            hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
            hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)
            ft1 = [t for t in fold_tr if t.get('_tier') == 'tier1']
            ft2 = [t for t in fold_tr if t.get('_tier') == 'tier2']
            fold_surviving = []
            if ft1 and hs_t1 > 0:
                fm = full_fill_model_v3(ft1, data, half_spread_bps=hs_t1, seed=42 + fi)
                fold_surviving.extend(fm['trades'])
            elif ft1:
                fold_surviving.extend(ft1)
            if ft2 and hs_t2 > 0:
                fm = full_fill_model_v3(ft2, data, half_spread_bps=hs_t2, seed=42 + fi)
                fold_surviving.extend(fm['trades'])
            elif ft2:
                fold_surviving.extend(ft2)
            fold_tr = fold_surviving

        fpnl = sum(t['pnl'] for t in fold_tr)
        fn = len(fold_tr)
        pos = fpnl > 0
        if pos:
            wf_folds_positive += 1
        fold_pnls.append(fpnl)
        fold_details.append({
            'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos,
        })

    top1_fold_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    print(f'    WF: {wf_folds_positive}/5 folds positive, top1 conc={top1_fold_conc:.3f}')

    # Gate evaluation
    gates, all_pass, failed, passed = evaluate_gates_strict(
        m, sm, wf_folds_positive, max_gap_days, top1_fold_conc,
    )
    gate_count = sum(1 for g in gates.values() if g['pass'])
    total_gates = len(gates)

    elapsed = time.time() - t_start
    status = 'ALL PASS' if all_pass else f'FAIL: {", ".join(failed)}'
    print(f'    Gates: {gate_count}/{total_gates} {status} ({elapsed:.1f}s)')

    return {
        'config': config_name,
        'config_params': config_params,
        'regime': regime_name,
        'regime_description': regime.get('description', ''),
        'execution_mode': exec_mode,
        'size': size,
        'fees': {
            'tier1_bps': regime['tier1']['total_per_side_bps'],
            'tier2_bps': regime['tier2']['total_per_side_bps'],
            'tier1_fee': t1_fee,
            'tier2_fee': t2_fee,
        },
        'stress_fees': {
            'tier1_bps': stress_fees['tier1_bps'],
            'tier2_bps': stress_fees['tier2_bps'],
        },
        'pre_fill': {'trades': pre_fill_count, 'pnl': round(pre_fill_pnl, 2)},
        'post_fill': {'trades': post_fill_count, 'pnl': round(post_fill_pnl, 2)},
        'fill_model': fill_result,
        'baseline': m,
        'tier_breakdown': tb,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'stress_2x': {
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
        'walk_forward': {
            'folds_positive': wf_folds_positive,
            'fold_details': fold_details,
            'top1_fold_conc': round(top1_fold_conc, 4),
        },
        'gates': gates,
        'all_gates_pass': all_pass,
        'gates_passed': gate_count,
        'gates_total': total_gates,
        'failed_gates': failed,
        'passed_gates': passed,
        'runtime_s': round(elapsed, 1),
    }


# ============================================================
# Intersection coin loading
# ============================================================

def get_intersection_coins_tiered(real_vwap_cache, bybit_tiering):
    """Get intersection coins organized by tier."""
    # Coins that have real VWAP (patched)
    patched_coins = set()
    for coin, candles in real_vwap_cache.items():
        if coin.startswith('_'):
            continue
        if candles and any(c.get('_vwap_source') == 'real_1m' for c in candles[:5]):
            patched_coins.add(coin)

    # Build tier lists from Bybit tiering, filtered to patched coins
    tier_coins = build_tier_coins(bybit_tiering, patched_coins)

    # Also include coins that exist in cache but not in tiering
    tiered_set = set(tier_coins['tier1'] + tier_coins['tier2'])
    untiered = patched_coins - tiered_set
    if untiered:
        # Put untiered coins in tier2
        tier_coins['tier2'].extend(sorted(untiered))

    return tier_coins, patched_coins


# ============================================================
# Markdown report builder
# ============================================================

def build_diagnostics_md(report, commit):
    """Build diagnostics-only MD report (bybit_vwap1m_diagnostics_001.md)."""
    md = []
    g = report.get('guardrails', {})

    md.append('# Bybit VWAP 1m Diagnostics Report')
    md.append('')
    md.append(f'**Date**: {report.get("date", "?")}')
    md.append(f'**Commit**: {commit}')
    md.append('')

    # Guardrails section
    md.append('## Guardrails')
    md.append('')
    tw = g.get('time_window', {})
    md.append('### Time Window Lock')
    md.append(f'- start: {tw.get("start_dt", "?")} (ts={tw.get("start_ts", "?")})')
    md.append(f'- end: {tw.get("end_dt", "?")} (ts={tw.get("end_ts", "?")})')
    md.append(f'- bars: {tw.get("total_bars", "?")}')
    md.append(f'- hours: {tw.get("total_hours", "?")}')
    md.append('')

    md.append('### VWAP Definition')
    vdef = g.get('vwap_definition', {})
    for k, v in vdef.items():
        md.append(f'- **{k}**: `{v}`')
    md.append('')

    md.append('### OB Regimes Lock')
    md.append(f'- file: `{g.get("ob_file", "?")}`')
    md.append(f'- MD5: `{g.get("ob_file_hash", "?")}`')
    fee = g.get('fee_snapshot', {})
    md.append(f'- fees: maker={fee.get("maker_fee_bps", "?")}bps taker={fee.get("taker_fee_bps", "?")}bps')
    md.append('')

    md.append('### Coverage Gate')
    cg = g.get('coverage_gate', {})
    md.append(f'- threshold: ≥{cg.get("threshold_pct", "?")}%')
    md.append(f'- coins_requested: {cg.get("coins_requested", "?")}')
    md.append(f'- coins_included: {cg.get("coins_included", "?")}')
    md.append(f'- coins_excluded: {cg.get("coins_excluded", "?")}')
    md.append(f'- coins_full_721_bars: {cg.get("coins_full_721_bars", "?")}')
    excl = cg.get('excluded_coins', [])
    if excl:
        md.append('')
        md.append('**Excluded coins:**')
        md.append('| Coin | Bars | Coverage | Reason |')
        md.append('|------|------|----------|--------|')
        for e in excl:
            md.append(f'| {e["coin"]} | {e["bars"]} | {e["coverage_pct"]}% | {e["reason"]} |')
    md.append('')

    # VWAP diagnostic comparison
    diag = report.get('vwap_diagnostics', {})
    md.append('## VWAP Deviation Distribution')
    md.append('')

    for label, d in diag.items():
        devs = d.get('deviations', {})
        md.append(f'### {label}')
        md.append(f'- Coins with VWAP: {d.get("coins_with_vwap", 0)}')
        md.append(f'- Bars with VWAP: {d.get("bars_with_vwap", 0)}/{d.get("total_bars", 0)}')
        if devs:
            md.append(f'- min={devs.get("min")}, med={devs.get("median")}, '
                      f'p95={devs.get("p95")}, max={devs.get("max")}')
            md.append(f'- Deviations ≥ 2.0 ATR: {devs.get("above_2", 0)} '
                      f'({devs.get("above_2_pct", 0):.3f}%)')
        md.append('')

    # Trigger comparison
    tc = report.get('trigger_comparison', {})
    md.append('## Trigger Comparison')
    md.append('')
    md.append('| Metric | Real VWAP | HLC3 Proxy |')
    md.append('|--------|-----------|------------|')
    real = tc.get('real_vwap', {})
    hlc3 = tc.get('hlc3_proxy', {})
    md.append(f'| Total triggers | {real.get("total_triggers", 0)} '
              f'| {hlc3.get("total_triggers", 0)} |')
    md.append(f'| Coins with triggers | {real.get("coins_with_triggers", 0)} '
              f'| {hlc3.get("coins_with_triggers", 0)} |')
    md.append('')

    # Per-coin breakdown
    pcb = tc.get('per_coin_breakdown', {})
    if pcb:
        md.append('### Per-Coin Trigger Breakdown (top-20, real VWAP)')
        md.append('')
        md.append(f'- Total coins analyzed: {pcb.get("total_coins_analyzed", 0)}')
        md.append(f'- Coins with 0 triggers: {pcb.get("coins_zero_triggers", 0)}')
        md.append(f'- Coins with 0 dev≥2.0: {pcb.get("coins_zero_dev_above_2", 0)}')
        md.append('')
        cib = pcb.get('candidates_ignoring_bounce', {})
        if cib:
            md.append('**Candidates ignoring bounce filter:**')
            md.append(f'- Total bars with dev≥2.0: {cib.get("total_dev_above_2_bars", 0)}')
            md.append(f'- Blocked by bounce (close ≤ prev_close): {cib.get("blocked_by_bounce", 0)}')
            md.append(f'- Would trigger (dev≥2.0 + bounce): {cib.get("would_trigger", 0)}')
            md.append('')
        top20 = pcb.get('real_vwap_top20', [])
        if top20:
            md.append('| Coin | Triggers | Bars | Dev≥2.0 bars | Blocked by bounce |')
            md.append('|------|----------|------|--------------|-------------------|')
            for e in top20:
                md.append(f'| {e["coin"]} | {e["triggers"]} | {e["bars"]} '
                          f'| {e["bars_dev_above_2"]} | {e.get("blocked_by_bounce", 0)} |')
        md.append('')

        # Top-20 by max_dev (closest to triggering)
        top20_md = pcb.get('top20_by_max_dev', [])
        if top20_md:
            md.append('### Top-20 Coins by Max VWAP Deviation')
            md.append('')
            cs = pcb.get('candidate_summary', {})
            md.append(f'- Coins with max_dev ≥ 2.0: **{cs.get("max_dev_gte_2_0", 0)}**')
            md.append(f'- Coins with max_dev 1.5-2.0: {cs.get("max_dev_1_5_to_2_0", 0)}')
            md.append(f'- Coins with max_dev 1.0-1.5: {cs.get("max_dev_1_0_to_1_5", 0)}')
            md.append(f'- Coins with max_dev < 1.0: {cs.get("max_dev_lt_1_0", 0)}')
            md.append('')
            md.append('| Coin | Max Dev | Dev≥2.0 bars | Blocked | Triggers |')
            md.append('|------|---------|--------------|---------|----------|')
            for e in top20_md:
                md_val = e.get('max_dev') or 0
                md.append(f'| {e["coin"]} | {md_val:.4f} | {e["bars_dev_above_2"]} '
                          f'| {e.get("blocked_by_bounce", 0)} | {e["triggers"]} |')
        md.append('')

    md.append('---')
    md.append(f'*Generated by run_bybit_vwap_validation.py at {report.get("date", "?")}*')
    return '\n'.join(md)


def build_md(report, elapsed, commit):
    md = []
    rh = report['run_header']

    md.append('# Bybit Real VWAP Validation Report')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Test**: Apples-to-apples VWAP comparison (real 1m VWAP vs HLC3 proxy)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION raw (dev_thresh=2.0)')
    md.append(f'**Exchange**: Bybit SPOT (10/10 bps)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    md.append('## Objective')
    md.append('')
    md.append('Test whether Bybit H20 failure is caused by HLC3 proxy VWAP (vs real')
    md.append('volume-weighted VWAP). Downloaded 1m candles, computed real VWAP per')
    md.append('1H bar, then ran original H20 signal with same dev_thresh=2.0.')
    md.append('')

    # Guardrails section
    g = report.get('guardrails', {})
    md.append('## Guardrails')
    md.append('')
    tw = g.get('time_window', {})
    md.append(f'- **Time Window**: {tw.get("start_dt", "?")} → {tw.get("end_dt", "?")} '
              f'({tw.get("total_bars", "?")} bars, {tw.get("total_hours", "?")}h)')
    vdef = g.get('vwap_definition', {})
    md.append(f'- **VWAP**: `{vdef.get("formula", "?")}`')
    md.append(f'- **tp_1m**: `{vdef.get("typical_price", "?")}`')
    md.append(f'- **Missing minutes**: {vdef.get("missing_minutes", "?")}')
    md.append(f'- **OB file**: `{g.get("ob_file", "?")}` (MD5: `{g.get("ob_file_hash", "?")}`)')
    fee = g.get('fee_snapshot', {})
    md.append(f'- **Fees**: maker={fee.get("maker_fee_bps", "?")}bps '
              f'taker={fee.get("taker_fee_bps", "?")}bps')
    cg = g.get('coverage_gate', {})
    md.append(f'- **Coverage gate**: ≥{cg.get("threshold_pct", "?")}% → '
              f'{cg.get("coins_included", "?")}/{cg.get("coins_requested", "?")} included, '
              f'{cg.get("coins_excluded", "?")} excluded, '
              f'{cg.get("coins_full_721_bars", "?")} full 721-bar coins')
    md.append('')

    # VWAP diagnostic comparison
    diag = report.get('vwap_diagnostics', {})
    md.append('## VWAP Diagnostic')
    md.append('')

    for label, d in diag.items():
        devs = d.get('deviations', {})
        md.append(f'### {label}')
        md.append(f'- Coins with VWAP: {d.get("coins_with_vwap", 0)}')
        md.append(f'- Bars with VWAP: {d.get("bars_with_vwap", 0)}/{d.get("total_bars", 0)}')
        if devs:
            md.append(f'- Deviation stats: min={devs.get("min")}, med={devs.get("median")}, '
                      f'max={devs.get("max")}')
            md.append(f'- Deviations ≥ 2.0 ATR: {devs.get("above_2", 0)} '
                      f'({devs.get("above_2_pct", 0):.3f}%)')
        md.append('')

    # Trigger comparison
    tc = report.get('trigger_comparison', {})
    md.append('## Trigger Comparison')
    md.append('')
    md.append('| Metric | Real VWAP | HLC3 Proxy |')
    md.append('|--------|-----------|------------|')
    real = tc.get('real_vwap', {})
    hlc3 = tc.get('hlc3_proxy', {})
    md.append(f'| Total triggers | {real.get("total_triggers", 0)} '
              f'| {hlc3.get("total_triggers", 0)} |')
    md.append(f'| Coins with triggers | {real.get("coins_with_triggers", 0)} '
              f'| {hlc3.get("coins_with_triggers", 0)} |')
    md.append('')

    # Per-coin breakdown (top-10 in main report)
    pcb = tc.get('per_coin_breakdown', {})
    if pcb:
        cib = pcb.get('candidates_ignoring_bounce', {})
        if cib:
            md.append('### Candidates Ignoring Bounce Filter')
            md.append('')
            md.append(f'- Total bars with dev≥2.0: **{cib.get("total_dev_above_2_bars", 0)}**')
            md.append(f'- Blocked by bounce (close ≤ prev_close): **{cib.get("blocked_by_bounce", 0)}**')
            md.append(f'- Would trigger (dev≥2.0 + bounce): **{cib.get("would_trigger", 0)}**')
            md.append('')
        top20 = pcb.get('real_vwap_top20', [])
        if top20:
            md.append('### Top-10 Coins by Real VWAP Triggers')
            md.append('')
            md.append('| Coin | Triggers | Dev≥2.0 bars | Blocked by bounce |')
            md.append('|------|----------|--------------|-------------------|')
            for e in top20[:10]:
                md.append(f'| {e["coin"]} | {e["triggers"]} | {e["bars_dev_above_2"]} '
                          f'| {e.get("blocked_by_bounce", 0)} |')
            md.append('')
            md.append(f'*{pcb.get("coins_zero_triggers", 0)}/{pcb.get("total_coins_analyzed", 0)} '
                      f'coins have 0 triggers. '
                      f'Full breakdown in bybit_vwap1m_diagnostics report.*')

        # Top-20 by max_dev in main report (abbreviated)
        top20_md = pcb.get('top20_by_max_dev', [])
        cs = pcb.get('candidate_summary', {})
        if top20_md:
            md.append('')
            md.append('### Top-10 Coins by Max VWAP Deviation')
            md.append('')
            md.append(f'Coins ever exceeding dev≥2.0: **{cs.get("max_dev_gte_2_0", 0)}** | '
                      f'Near (1.5-2.0): {cs.get("max_dev_1_5_to_2_0", 0)} | '
                      f'Moderate (1.0-1.5): {cs.get("max_dev_1_0_to_1_5", 0)} | '
                      f'Far (<1.0): {cs.get("max_dev_lt_1_0", 0)}')
            md.append('')
            md.append('| Coin | Max Dev | Dev≥2.0 bars | Blocked | Triggers |')
            md.append('|------|---------|--------------|---------|----------|')
            for e in top20_md[:10]:
                md_val = e.get('max_dev') or 0
                md.append(f'| {e["coin"]} | {md_val:.4f} | {e["bars_dev_above_2"]} '
                          f'| {e.get("blocked_by_bounce", 0)} | {e["triggers"]} |')
            md.append('')

    # Summary scoreboard
    md.append('## 24-Combo Scoreboard (Real VWAP)')
    md.append('')
    md.append('| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |')
    md.append('|--------|--------|------|--------|----|----|-----|----|----|')

    for r in report.get('combinations', []):
        m = r['baseline']
        wf = r.get('walk_forward', {})
        wf_str = f'{wf.get("folds_positive", 0)}/5'
        gate_info = r.get('gates_passed', '-')
        gate_total = r.get('gates_total', '-')
        if r.get('all_gates_pass'):
            gate_str = f'**{gate_info}/{gate_total}**'
        else:
            gate_str = f'{gate_info}/{gate_total}'
        md.append(
            f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
            f'| {m["trades"]} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} '
            f'| {m["dd"]:.1f} | {wf_str} | {gate_str} |'
        )
    md.append('')

    # Gate summary
    passing = [r for r in report.get('combinations', []) if r.get('all_gates_pass')]
    failing = [r for r in report.get('combinations', []) if not r.get('all_gates_pass')]

    md.append('## Gate Results')
    md.append('')
    md.append(f'- **Passing ALL gates**: {len(passing)}/{len(report.get("combinations", []))}')
    if passing:
        for r in passing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}')
    md.append('')
    if failing:
        md.append(f'- **Failing**: {len(failing)}')
        for r in failing[:10]:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                      f'fails {", ".join(r.get("failed_gates", []))}')
    md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_bybit_vwap_validation.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Bybit Real VWAP Validation: H20 raw on 1m-aggregated VWAP',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--config', choices=['v5', 'sl7', 'both'], default='both',
                        help='Config to test (default: both)')
    parser.add_argument('--skip-fill-model', action='store_true',
                        help='Skip fill model for faster iteration')
    parser.add_argument('--output-label', type=str, default='001',
                        help='Output file label (default: 001)')

    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Bybit Real VWAP Validation')
    print('  H20 VWAP_DEVIATION raw | 1m-aggregated VWAP | vs HLC3 proxy')
    print('  Apples-to-apples comparison (same coins, same signal, real VWAP)')
    print(sep)
    t0 = time.time()

    # Commit hash
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # Select configs
    if args.config == 'both':
        configs_to_test = CONFIGS
    else:
        configs_to_test = {args.config: CONFIGS[args.config]}

    # --- Load real VWAP patched cache ---
    real_vwap_path = ROOT / 'data' / 'candle_cache_1h_bybit_real_vwap.json'
    if not real_vwap_path.exists():
        print(f'[ERROR] Patched cache not found: {real_vwap_path}')
        print(f'  Run: python -m strategies.hf.screening.vwap_1m_aggregator --mode intersection')
        sys.exit(1)

    print(f'[Load] Reading real VWAP patched cache...')
    with open(real_vwap_path) as f:
        real_vwap_data = json.load(f)
    all_coins_real = {k: v for k, v in real_vwap_data.items() if not k.startswith('_')}
    print(f'  {len(all_coins_real)} coins total in cache')

    # --- Also load original Bybit cache for comparison ---
    hlc3_path = ROOT / 'data' / 'candle_cache_1h_bybit.json'
    print(f'[Load] Reading original Bybit cache (HLC3 proxy)...')
    with open(hlc3_path) as f:
        hlc3_data = json.load(f)
    all_coins_hlc3 = {k: v for k, v in hlc3_data.items() if not k.startswith('_')}

    # ================================================================
    # GUARDRAIL A1: Time Window Lock
    # ================================================================
    print('\n[Guardrail] Time Window Lock')
    tw = compute_time_window(all_coins_real, list(all_coins_real.keys()))
    if tw:
        print(f'  start_ts = {tw["start_ts"]}  ({tw["start_dt"]})')
        print(f'  end_ts   = {tw["end_ts"]}  ({tw["end_dt"]})')
        print(f'  bars     = {tw["total_bars"]}')
        print(f'  hours    = {tw["total_hours"]}')
    else:
        print('  [ERROR] No time window data')
        sys.exit(1)

    # ================================================================
    # GUARDRAIL A2: VWAP Definition
    # ================================================================
    print('\n[Guardrail] VWAP Definition')
    vwap_def = {
        'formula': 'VWAP_1H = sum(tp_1m * vol_1m) / sum(vol_1m)',
        'typical_price': 'tp_1m = (high_1m + low_1m + close_1m) / 3  [HLC3 of 1m bar]',
        'aggregation': '60 x 1m bars per 1H bar',
        'missing_minutes': 'skip (hours with 0 volume fallback to HLC3 of 1H bar)',
        'source': 'Bybit SPOT via CCXT fetch_ohlcv(1m)',
    }
    for k, v in vwap_def.items():
        print(f'  {k}: {v}')

    # ================================================================
    # GUARDRAIL A4: OB Regimes (constant, hash-locked)
    # ================================================================
    exchange_cfg = get_exchange('bybit')
    exchange_id = exchange_cfg.id

    print(f'\n[Guardrail] OB Regimes Lock')
    ob_report_path = ROOT / 'reports' / 'hf' / f'{exchange_id}_orderbook_costs_{args.output_label}.json'
    ob_input_path = ROOT / 'data' / 'orderbook_snapshots' / f'{exchange_id}_orderbook_{args.output_label}.jsonl'

    ob_file_hash = None
    distributions = None
    if ob_report_path.exists():
        ob_file_hash = compute_file_hash(ob_report_path)
        print(f'  OB report: {ob_report_path.name}')
        print(f'  OB hash:   {ob_file_hash}')
        with open(ob_report_path) as f:
            ob_report = json.load(f)
        distributions = ob_report.get('distributions', {})
        measured_regimes = ob_report.get('regimes', {})
        print(f'  Regimes:   {len(measured_regimes)}')
    elif ob_input_path.exists():
        ob_file_hash = compute_file_hash(ob_input_path)
        print(f'  OB raw:  {ob_input_path.name}')
        print(f'  OB hash: {ob_file_hash}')
        from strategies.hf.screening.exchange_config import build_fee_snapshot as _bfs
        class _Args:
            exchange = 'bybit'
            maker_fee_bps = None
            taker_fee_bps = None
            fee_source = None
            region = None
            tier = None
        fee_snap = _bfs(_Args())
        snapshots = load_snapshots(str(ob_input_path))
        distributions = compute_distributions(snapshots)
        measured_regimes = build_measured_regimes(distributions, exchange=exchange_cfg, fee_snapshot=fee_snap)
        print(f'  Built {len(measured_regimes)} regimes from raw data')
    else:
        print(f'[ERROR] No orderbook data for {exchange_id}')
        sys.exit(1)

    # Fee snapshot
    fee_snapshot_data = {
        'exchange_id': exchange_id,
        'maker_fee_bps': exchange_cfg.maker_fee_bps,
        'taker_fee_bps': exchange_cfg.taker_fee_bps,
    }
    print(f'  Fees: maker={exchange_cfg.maker_fee_bps}bps taker={exchange_cfg.taker_fee_bps}bps')

    # Register regimes
    for name, regime in measured_regimes.items():
        if name in REGIMES_TO_TEST:
            register_regime(name, regime)
            print(f'  Registered: {name} -> '
                  f'T1={regime["tier1"]["total_per_side_bps"]}bps '
                  f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    missing = [r for r in REGIMES_TO_TEST if r not in COST_REGIMES]
    if missing:
        print(f'[ERROR] Missing regimes: {missing}')
        sys.exit(1)

    # --- Build intersection coin lists ---
    tiering = load_universe_tiering_exchange(exchange_id, require_data=True)
    tier_coins_raw, patched_coins = get_intersection_coins_tiered(real_vwap_data, tiering)

    # ================================================================
    # GUARDRAIL A3: Coverage Gate
    # ================================================================
    print('\n[Guardrail] Coverage Gate (threshold: >={}% bars + real VWAP)'.format(
        MIN_COVERAGE_PCT))

    all_patched_list = list(patched_coins)
    included_coins, excluded_coins, cov_report = coverage_gate(
        all_coins_real, all_patched_list)

    n_requested = len(all_patched_list)
    n_included = len(included_coins)
    n_excluded = len(excluded_coins)
    print(f'  coins_requested:  {n_requested}')
    print(f'  coins_included:   {n_included}')
    print(f'  coins_excluded:   {n_excluded}')

    # Count per coverage bucket
    full_721 = sum(1 for c in cov_report if c['bars'] >= 721)
    print(f'  coins_full_721_bars: {full_721}')

    if excluded_coins:
        print(f'  Excluded coins (low coverage / no real VWAP):')
        for entry in sorted(cov_report, key=lambda x: x['coverage_pct']):
            if entry['coin'] in excluded_coins:
                print(f'    {entry["coin"]:20s} bars={entry["bars"]} '
                      f'cov={entry["coverage_pct"]:.0f}% '
                      f'real_vwap={entry["real_vwap_pct"]:.0f}% '
                      f'reason={entry.get("excluded_reason", "?")}')

    # Re-filter tier_coins to only included coins
    included_set = set(included_coins)
    tier_coins = {
        'tier1': [c for c in tier_coins_raw['tier1'] if c in included_set],
        'tier2': [c for c in tier_coins_raw['tier2'] if c in included_set],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_patched = len(patched_coins)
    print(f'\n[Universe] After coverage gate: T1({n_t1}) + T2({n_t2}) = {n_t1 + n_t2} coins')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins pass coverage gate.')
        print('  Run the 1m aggregator first with enough coins.')
        sys.exit(1)

    n_combos = len(configs_to_test) * len(REGIMES_TO_TEST) * len(SIZES)

    if args.dry_run:
        print(f'\n--- DRY RUN ---')
        print(f'  Patched coins: {n_patched}')
        print(f'  Included (post-gate): {n_included}')
        print(f'  T1={n_t1}, T2={n_t2}')
        print(f'  Configs: {list(configs_to_test.keys())}')
        print(f'  Regimes: {REGIMES_TO_TEST}')
        print(f'  Sizes: {SIZES}')
        print(f'  Total combinations: {n_combos}')
        sys.exit(0)

    # --- Precompute indicators for REAL VWAP ---
    print('\n[Indicators] Precomputing for REAL VWAP cache...')
    real_tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            real_tier_indicators[tier_name] = precompute_base_indicators(
                all_coins_real, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields (real VWAP)...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in real_tier_indicators:
            extend_indicators(all_coins_real, coins, real_tier_indicators[tier_name])
            cov = get_feature_coverage(real_tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # --- Also precompute for HLC3 (comparison) ---
    # Only for coins that are also in the real VWAP set
    print('[Indicators] Precomputing for HLC3 proxy cache (comparison)...')
    hlc3_tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        hlc3_coins = [c for c in coins if c in all_coins_hlc3]
        if hlc3_coins:
            t_ind = time.time()
            hlc3_tier_indicators[tier_name] = precompute_base_indicators(
                all_coins_hlc3, hlc3_coins)
            print(f'  {tier_name}: {len(hlc3_coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields (HLC3 proxy)...')
    for tier_name, coins in tier_coins.items():
        hlc3_coins = [c for c in coins if c in all_coins_hlc3]
        if hlc3_coins and tier_name in hlc3_tier_indicators:
            extend_indicators(all_coins_hlc3, hlc3_coins, hlc3_tier_indicators[tier_name])
            cov = get_feature_coverage(hlc3_tier_indicators[tier_name], hlc3_coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}%')

    # --- VWAP diagnostics: compare deviation distributions ---
    print('\n[Diagnostics] Comparing VWAP deviation distributions...')
    all_real_coins = list(set(tier_coins['tier1'] + tier_coins['tier2']))
    all_real_indicators = {}
    for tier_name in ('tier1', 'tier2'):
        all_real_indicators.update(real_tier_indicators.get(tier_name, {}))

    all_hlc3_indicators = {}
    for tier_name in ('tier1', 'tier2'):
        all_hlc3_indicators.update(hlc3_tier_indicators.get(tier_name, {}))

    real_vwap_stats = count_vwap_availability(all_coins_real, all_real_coins, all_real_indicators)
    hlc3_vwap_stats = count_vwap_availability(all_coins_hlc3, all_real_coins, all_hlc3_indicators)

    print(f'  Real VWAP: {real_vwap_stats["coins_with_vwap"]} coins, '
          f'{real_vwap_stats["bars_with_vwap"]} bars')
    r_devs = real_vwap_stats.get('deviations', {})
    if r_devs:
        print(f'    Deviations: med={r_devs.get("median")}, p95={r_devs.get("p95")}, '
              f'max={r_devs.get("max")}')
        print(f'    Above 2.0: {r_devs.get("above_2", 0)} ({r_devs.get("above_2_pct", 0):.3f}%)')

    print(f'  HLC3 proxy: {hlc3_vwap_stats["coins_with_vwap"]} coins, '
          f'{hlc3_vwap_stats["bars_with_vwap"]} bars')
    h_devs = hlc3_vwap_stats.get('deviations', {})
    if h_devs:
        print(f'    Deviations: med={h_devs.get("median")}, p95={h_devs.get("p95")}, '
              f'max={h_devs.get("max")}')
        print(f'    Above 2.0: {h_devs.get("above_2", 0)} ({h_devs.get("above_2_pct", 0):.3f}%)')

    # --- Trigger count comparison ---
    print('\n[Triggers] Counting H20 triggers for real VWAP vs HLC3...')
    v5_params = CONFIGS['v5']

    real_triggers, real_coins_trig, real_details = count_triggers(
        all_coins_real, all_real_coins, all_real_indicators, v5_params)
    print(f'  Real VWAP: {real_triggers} triggers across {real_coins_trig} coins')

    hlc3_triggers, hlc3_coins_trig, hlc3_details = count_triggers(
        all_coins_hlc3, all_real_coins, all_hlc3_indicators, v5_params)
    print(f'  HLC3 proxy: {hlc3_triggers} triggers across {hlc3_coins_trig} coins')

    trigger_comparison = {
        'real_vwap': {
            'total_triggers': real_triggers,
            'coins_with_triggers': real_coins_trig,
            'top_coins': sorted(real_details, key=lambda x: -x['triggers'])[:20],
        },
        'hlc3_proxy': {
            'total_triggers': hlc3_triggers,
            'coins_with_triggers': hlc3_coins_trig,
            'top_coins': sorted(hlc3_details, key=lambda x: -x['triggers'])[:20],
        },
    }

    # --- Per-coin trigger breakdown (A5: top-20 + all coins) ---
    print('\n[Triggers] Per-coin breakdown (top-20 by real VWAP triggers)...')
    per_coin_real = per_coin_trigger_breakdown(
        all_coins_real, all_real_coins, all_real_indicators, v5_params)
    per_coin_hlc3 = per_coin_trigger_breakdown(
        all_coins_hlc3, all_real_coins, all_hlc3_indicators, v5_params)

    # Build lookup for HLC3
    hlc3_lookup = {r['coin']: r for r in per_coin_hlc3}

    print(f'  {"Coin":<15s} | {"Real":>5s} | {"HLC3":>5s} | {"Diff":>6s} | {"DevBars":>7s} | {"Blocked":>7s}')
    print(f'  {"-"*15} | {"-"*5} | {"-"*5} | {"-"*6} | {"-"*7} | {"-"*7}')
    for entry in per_coin_real[:20]:
        coin = entry['coin']
        real_t = entry['triggers']
        hlc3_t = hlc3_lookup.get(coin, {}).get('triggers', 0)
        diff = real_t - hlc3_t
        dev_bars = entry['bars_dev_above_2']
        blocked = entry['blocked_by_bounce']
        print(f'  {coin:<15s} | {real_t:>5d} | {hlc3_t:>5d} | {diff:>+6d} | {dev_bars:>7d} | {blocked:>7d}')

    # Aggregate: candidates ignoring bounce filter
    total_dev_bars = sum(e['bars_dev_above_2'] for e in per_coin_real)
    total_blocked = sum(e['blocked_by_bounce'] for e in per_coin_real)
    total_would_trigger = total_dev_bars - total_blocked
    print(f'\n  Candidates ignoring bounce filter:')
    print(f'    Total bars with dev>=2.0:     {total_dev_bars}')
    print(f'    Blocked by bounce filter:     {total_blocked}')
    print(f'    Would trigger (dev>=2.0 + bounce): {total_would_trigger}')

    # Coins with 0 triggers in real VWAP
    zero_trig_coins = [e for e in per_coin_real if e['triggers'] == 0]
    print(f'\n  Coins with 0 real-VWAP triggers: {len(zero_trig_coins)}/{len(per_coin_real)}')
    if zero_trig_coins:
        # Show reason: no dev>=2.0 bars
        no_dev = [e for e in zero_trig_coins if e['bars_dev_above_2'] == 0]
        has_dev_no_bounce = [e for e in zero_trig_coins
                            if e['bars_dev_above_2'] > 0 and e['blocked_by_bounce'] == e['bars_dev_above_2']]
        has_dev_with_bounce = [e for e in zero_trig_coins
                              if e['bars_dev_above_2'] > 0 and e['blocked_by_bounce'] < e['bars_dev_above_2']]
        print(f'    No dev>=2.0 bars at all: {len(no_dev)}')
        print(f'    Has dev>=2.0 but ALL blocked by bounce: {len(has_dev_no_bounce)}')
        print(f'    Has dev>=2.0 + bounce but still 0 triggers: {len(has_dev_with_bounce)}')

    # --- Top-20 coins by max_dev (closest to triggering) ---
    per_coin_by_maxdev = sorted(
        [e for e in per_coin_real if e.get('max_dev') is not None],
        key=lambda x: -(x['max_dev'] or 0),
    )
    coins_ever_above_2 = [e for e in per_coin_by_maxdev if e.get('max_dev', 0) >= 2.0]
    coins_above_1_5 = [e for e in per_coin_by_maxdev if 1.5 <= (e.get('max_dev') or 0) < 2.0]
    coins_above_1_0 = [e for e in per_coin_by_maxdev if 1.0 <= (e.get('max_dev') or 0) < 1.5]
    coins_below_1_0 = [e for e in per_coin_by_maxdev if (e.get('max_dev') or 0) < 1.0]

    print(f'\n  Top-20 coins by max VWAP deviation (closest to dev_thresh=2.0):')
    print(f'  {"Coin":<15s} | {"MaxDev":>8s} | {"Dev≥2.0":>7s} | {"Blocked":>7s} | {"Triggers":>8s}')
    print(f'  {"-"*15} | {"-"*8} | {"-"*7} | {"-"*7} | {"-"*8}')
    for entry in per_coin_by_maxdev[:20]:
        md = entry.get('max_dev') or 0
        print(f'  {entry["coin"]:<15s} | {md:>8.4f} | {entry["bars_dev_above_2"]:>7d} '
              f'| {entry["blocked_by_bounce"]:>7d} | {entry["triggers"]:>8d}')

    print(f'\n  Candidate coin summary:')
    print(f'    Coins with max_dev ≥ 2.0 (ever exceeded threshold): {len(coins_ever_above_2)}')
    print(f'    Coins with max_dev 1.5-2.0 (near threshold):       {len(coins_above_1_5)}')
    print(f'    Coins with max_dev 1.0-1.5 (moderate):             {len(coins_above_1_0)}')
    print(f'    Coins with max_dev < 1.0 (far from threshold):     {len(coins_below_1_0)}')

    trigger_comparison['per_coin_breakdown'] = {
        'real_vwap_top20': per_coin_real[:20],
        'top20_by_max_dev': per_coin_by_maxdev[:20],
        'total_coins_analyzed': len(per_coin_real),
        'coins_zero_triggers': len(zero_trig_coins),
        'coins_zero_dev_above_2': len([e for e in per_coin_real if e['bars_dev_above_2'] == 0]),
        'coins_ever_above_2': len(coins_ever_above_2),
        'candidate_summary': {
            'max_dev_gte_2_0': len(coins_ever_above_2),
            'max_dev_1_5_to_2_0': len(coins_above_1_5),
            'max_dev_1_0_to_1_5': len(coins_above_1_0),
            'max_dev_lt_1_0': len(coins_below_1_0),
        },
        'candidates_ignoring_bounce': {
            'total_dev_above_2_bars': total_dev_bars,
            'blocked_by_bounce': total_blocked,
            'would_trigger': total_would_trigger,
        },
    }

    # --- Market context ---
    print('[Market Context] Precomputing...')
    all_coins_list = list(set(tier_coins['tier1'] + tier_coins['tier2']))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in all_coins_real and btc not in all_coins_list:
            all_coins_list.append(btc)
    market_context = precompute_market_context(all_coins_real, all_coins_list)
    print('  Done.')

    # Inject __coin__
    for tier_name, ind_dict in real_tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    # Estimate total bars
    total_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = real_tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > total_bars:
                total_bars = n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    t1_indicators = real_tier_indicators.get('tier1', {})
    t2_indicators = real_tier_indicators.get('tier2', {})
    t1_coins = tier_coins['tier1']
    t2_coins = tier_coins['tier2']

    # ============================================================
    # Run all combinations
    # ============================================================

    print(f'\n[Run] Starting {n_combos} combinations...\n')
    results = []
    combo_idx = 0

    for config_name, config_params in configs_to_test.items():
        for regime_name in REGIMES_TO_TEST:
            regime_base = COST_REGIMES[regime_name]

            for size in SIZES:
                combo_idx += 1
                regime = build_size_specific_regime(regime_base, distributions or {}, size)
                print(f'\n--- Combo {combo_idx}/{n_combos} ---')

                result = analyze_combination(
                    config_name=config_name,
                    config_params=config_params,
                    regime_name=regime_name,
                    regime=regime,
                    size=size,
                    data=all_coins_real,
                    t1_coins=t1_coins,
                    t2_coins=t2_coins,
                    t1_indicators=t1_indicators,
                    t2_indicators=t2_indicators,
                    market_ctx=market_context,
                    total_bars=total_bars,
                    distributions=distributions or {},
                    skip_fill_model=args.skip_fill_model,
                )
                results.append(result)

    elapsed = time.time() - t0

    # ============================================================
    # Verdict
    # ============================================================

    passing = [r for r in results if r.get('all_gates_pass')]
    n_pass = len(passing)
    n_total = len(results)

    verdict_lines = []
    if n_pass > 0:
        verdict_lines.append(f'**{n_pass}/{n_total} combos PASS all 7 STRICT gates with real VWAP.**')
        verdict_lines.append('')
        verdict_lines.append('Real VWAP from 1m aggregation enables H20 signal on Bybit.')
        verdict_lines.append('Root cause confirmed: HLC3 proxy was the bottleneck.')
    elif real_triggers > hlc3_triggers * 2:
        verdict_lines.append(f'**0/{n_total} pass, BUT real VWAP generated '
                             f'{real_triggers} triggers vs {hlc3_triggers} (HLC3).**')
        verdict_lines.append('')
        verdict_lines.append('Real VWAP enables more triggers but trades are still unprofitable.')
        verdict_lines.append('Root cause: exchange microstructure (fills, adverse selection), NOT VWAP source.')
    else:
        verdict_lines.append(f'**0/{n_total} pass.** Real VWAP triggers={real_triggers}, '
                             f'HLC3 triggers={hlc3_triggers}.')
        verdict_lines.append('')
        if real_triggers <= hlc3_triggers:
            verdict_lines.append('Real VWAP does NOT increase trigger count — HLC3 was NOT the bottleneck.')
            verdict_lines.append('Root cause: exchange microstructure differences beyond VWAP.')
        else:
            verdict_lines.append('Marginal trigger increase insufficient for profitability.')

    for line in verdict_lines:
        print(line)

    # ============================================================
    # Build and save report
    # ============================================================

    report = {
        'task': 'bybit_h20_vwap1m_validation',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'commit': commit,
        'signal': 'H20 VWAP_DEVIATION raw (dev_thresh=2.0)',
        'exchange': 'bybit',
        # --- Guardrail metadata ---
        'guardrails': {
            'time_window': tw,
            'vwap_definition': vwap_def,
            'ob_file': str(ob_report_path.name) if ob_report_path.exists() else str(ob_input_path.name),
            'ob_file_hash': ob_file_hash,
            'fee_snapshot': fee_snapshot_data,
            'coverage_gate': {
                'threshold_pct': MIN_COVERAGE_PCT,
                'coins_requested': n_requested,
                'coins_included': n_included,
                'coins_excluded': n_excluded,
                'coins_full_721_bars': full_721,
                'excluded_coins': [
                    {
                        'coin': e['coin'],
                        'bars': e['bars'],
                        'coverage_pct': e['coverage_pct'],
                        'reason': e.get('excluded_reason', '?'),
                    }
                    for e in cov_report if e['coin'] in set(excluded_coins)
                ],
            },
        },
        'run_header': {
            'configs': list(configs_to_test.keys()),
            'regimes': REGIMES_TO_TEST,
            'sizes': SIZES,
            'n_combos': n_combos,
            'matrix_description': (
                f'{len(configs_to_test)} configs × {len(REGIMES_TO_TEST)} regimes '
                f'× {len(SIZES)} sizes = {n_combos} combos'
            ),
            'universe': {
                'patched_coins': n_patched,
                'coins_included': n_included,
                'tier1': n_t1,
                'tier2': n_t2,
            },
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
        },
        'vwap_diagnostics': {
            'real_vwap': real_vwap_stats,
            'hlc3_proxy': hlc3_vwap_stats,
        },
        'trigger_comparison': trigger_comparison,
        'combinations': results,
        'summary': {
            'total': n_total,
            'passing': n_pass,
            'failing': n_total - n_pass,
            'best_pf': round(max((r['baseline']['pf'] for r in results), default=0), 3),
            'best_trades': max((r['baseline']['trades'] for r in results), default=0),
            'max_gates_passed': max((r['gates_passed'] for r in results), default=0),
        },
        'verdict_lines': verdict_lines,
        'runtime_s': round(elapsed, 1),
    }

    # ============================================================
    # Save diagnostics report (separate)
    # ============================================================
    diag_report = {
        'task': 'bybit_vwap1m_diagnostics',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'commit': commit,
        'guardrails': report['guardrails'],
        'vwap_diagnostics': report['vwap_diagnostics'],
        'trigger_comparison': report['trigger_comparison'],
        'per_coin_coverage': cov_report,
    }

    diag_json_path = ROOT / 'reports' / 'hf' / f'bybit_vwap1m_diagnostics_{args.output_label}.json'
    diag_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(diag_json_path, 'w') as f:
        json.dump(diag_report, f, indent=2)
    print(f'\n[Report] Diagnostics JSON: {diag_json_path}')

    diag_md_content = build_diagnostics_md(diag_report, commit)
    diag_md_path = ROOT / 'reports' / 'hf' / f'bybit_vwap1m_diagnostics_{args.output_label}.md'
    with open(diag_md_path, 'w') as f:
        f.write(diag_md_content)
    print(f'[Report] Diagnostics MD: {diag_md_path}')

    # ============================================================
    # Save main backtest report
    # ============================================================
    json_path = ROOT / 'reports' / 'hf' / f'part2_bybit_h20_vwap1m_{args.output_label}.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f'[Report] Main JSON: {json_path}')

    md_content = build_md(report, elapsed, commit)
    md_path = ROOT / 'reports' / 'hf' / f'part2_bybit_h20_vwap1m_{args.output_label}.md'
    with open(md_path, 'w') as f:
        f.write(md_content)
    print(f'[Report] Main MD: {md_path}')

    print(f'\n{sep}')
    print(f'  VALIDATION COMPLETE ({elapsed:.1f}s)')
    print(f'  Result: {n_pass}/{n_total} combos pass')
    print(f'  Triggers: real={real_triggers} vs hlc3={hlc3_triggers}')
    print(sep)


if __name__ == '__main__':
    main()
