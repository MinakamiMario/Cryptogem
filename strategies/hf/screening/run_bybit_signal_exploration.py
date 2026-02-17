#!/usr/bin/env python3
"""
Bybit Signal Exploration Runner
=================================
Run any signal function through the 24-combo matrix on Bybit data.
Supports both single-signal runs and multi-signal bake-offs.

Reuses proven infrastructure from run_multi_exchange_validation.py:
- Same analyze_combination() flow (adapted for configurable signal_fn)
- Same 7 STRICT gates (G1-G6 + G8)
- Same fill model, same walk-forward 5-fold

Usage:
    # Step 2: Normalized VWAP z-score on Bybit
    python -m strategies.hf.screening.run_bybit_signal_exploration --signal H20Z --config zscore_v5

    # Step 3: Multi-signal bake-off
    python -m strategies.hf.screening.run_bybit_signal_exploration --bakeoff

    # Single signal from bake-off list
    python -m strategies.hf.screening.run_bybit_signal_exploration --signal H16 --config disp_tight
"""
import sys
import json
import time
import argparse
import subprocess
import copy
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators,
)
from strategies.hf.screening.hypotheses_s5 import (
    signal_h20_vwap_deviation,
    signal_h20z_vwap_deviation_zscore,
    signal_h16_displacement_bar,
    signal_h17_wick_rejection,
    signal_h18_vol_expansion,
    signal_h19_gap_proxy,
)
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import (
    register_regime, COST_REGIMES,
)
from strategies.hf.screening.fill_model_v3 import full_fill_model_v3
from strategies.hf.screening.exchange_config import get_exchange, FeeSnapshot
from strategies.hf.screening.run_multi_exchange_validation import (
    load_candle_cache_exchange, load_universe_tiering_exchange,
    build_tier_coins, compute_metrics, compute_max_gap,
    compute_fold_concentration, evaluate_gates_strict,
    tier_pnl_breakdown, build_size_specific_regime,
    get_half_spread_for_fill, compute_stress_fees,
    BARS_PER_WEEK, BARS_PER_DAY,
)


# ============================================================
# Signal + Config definitions
# ============================================================

SIGNAL_REGISTRY = {
    'H20':  {'fn': signal_h20_vwap_deviation, 'name': 'VWAP_DEVIATION (raw)'},
    'H20Z': {'fn': signal_h20z_vwap_deviation_zscore, 'name': 'VWAP_DEVIATION_ZSCORE'},
    'H16':  {'fn': signal_h16_displacement_bar, 'name': 'DISPLACEMENT_BAR'},
    'H17':  {'fn': signal_h17_wick_rejection, 'name': 'WICK_REJECTION'},
    'H18':  {'fn': signal_h18_vol_expansion, 'name': 'VOL_EXPANSION'},
    'H19':  {'fn': signal_h19_gap_proxy, 'name': 'GAP_PROXY'},
}

# Config presets per signal
SIGNAL_CONFIGS = {
    'H20Z': {
        'zscore_v5':  {'zscore_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
        'zscore_sl7': {'zscore_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10},
    },
    'H16': {
        'disp_tight': {'disp_thresh': 2.0, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 12},
        'disp_wide':  {'disp_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 12},
    },
    'H17': {
        'wick_tight': {'wick_pct': 0.6, 'vol_mult': 1.5, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
        'wick_wide':  {'wick_pct': 0.7, 'vol_mult': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 10},
    },
    'H18': {
        'volexp_3':   {'compress_bars': 3, 'expansion_thresh': 1.5, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
        'volexp_5':   {'compress_bars': 5, 'expansion_thresh': 1.5, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 15},
    },
    'H19': {
        'gap_tight':  {'gap_thresh': 0.01, 'tp_pct': 4, 'sl_pct': 3, 'time_limit': 8},
        'gap_wide':   {'gap_thresh': 0.015, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 8},
    },
}

REGIMES_TO_TEST = [
    'measured_ob_maker_p50', 'measured_ob_maker_p90',
    'measured_ob_taker_p50', 'measured_ob_taker_p90',
]

SIZES = [200, 500, 2000]


# ============================================================
# Backtest runners (signal_fn as parameter)
# ============================================================

def run_combined_signal(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                        market_ctx, t1_fee, t2_fee, params, signal_fn,
                        initial_capital=2000.0):
    """Run backtests for T1 and T2 with configurable signal function."""
    enriched = {**params, '__market__': market_ctx}
    all_trades = []

    if t1_coins:
        bt_t1 = run_backtest(
            data=data, coins=t1_coins, signal_fn=signal_fn,
            params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t1.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = t1_fee
        all_trades.extend(bt_t1.trade_list)

    if t2_coins:
        bt_t2 = run_backtest(
            data=data, coins=t2_coins, signal_fn=signal_fn,
            params=enriched, indicators=t2_indicators, fee=t2_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t2.trade_list:
            t['_tier'] = 'tier2'
            t['_fee_per_side'] = t2_fee
        all_trades.extend(bt_t2.trade_list)

    return all_trades


def run_combined_wf_signal(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                           market_ctx, t1_fee, t2_fee, params, signal_fn,
                           n_folds=5, initial_capital=2000.0):
    """Run walk-forward with configurable signal function."""
    enriched = {**params, '__market__': market_ctx}
    fold_trades = {}

    if t1_coins:
        t1_results = walk_forward(
            data=data, coins=t1_coins, signal_fn=signal_fn,
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
            data=data, coins=t2_coins, signal_fn=signal_fn,
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
# Analyze one combination (signal-parametric)
# ============================================================

def analyze_combination_signal(
    config_name, config_params, regime_name, regime, size,
    data, t1_coins, t2_coins, t1_indicators, t2_indicators,
    market_ctx, total_bars, distributions, signal_fn,
    skip_fill_model=False,
):
    """Run full analysis for one config x regime x size with any signal_fn."""
    t_start = time.time()
    exec_mode = regime.get('execution_mode', '')
    t1_fee = regime['tier1']['total_per_side_bps'] / 10000.0
    t2_fee = regime['tier2']['total_per_side_bps'] / 10000.0

    label = f'{config_name}/{regime_name}/${size}'
    print(f'  [{label}] fees T1={regime["tier1"]["total_per_side_bps"]}bps '
          f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # Baseline backtest
    trades = run_combined_signal(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, signal_fn,
        initial_capital=size,
    )
    pre_fill_count = len(trades)
    pre_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    # Fill model (same logic as original runner)
    fill_result = None
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)
        t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
        t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
        surviving = []
        fill_summary = {'total': len(trades), 'filled': 0, 'missed': 0, 'fill_rate': 0.0}

        if t1_trades and hs_t1 > 0:
            fm = full_fill_model_v3(t1_trades, data, half_spread_bps=hs_t1)
            surviving.extend(fm['trades'])
            fill_summary['filled'] += fm['fill_summary']['filled']
            fill_summary['missed'] += fm['fill_summary']['missed']
        elif t1_trades:
            surviving.extend(t1_trades)
            fill_summary['filled'] += len(t1_trades)

        if t2_trades and hs_t2 > 0:
            fm = full_fill_model_v3(t2_trades, data, half_spread_bps=hs_t2)
            surviving.extend(fm['trades'])
            fill_summary['filled'] += fm['fill_summary']['filled']
            fill_summary['missed'] += fm['fill_summary']['missed']
        elif t2_trades:
            surviving.extend(t2_trades)
            fill_summary['filled'] += len(t2_trades)

        total_fm = fill_summary['filled'] + fill_summary['missed']
        fill_summary['fill_rate'] = fill_summary['filled'] / total_fm if total_fm > 0 else 0.0
        trades = surviving
        fill_result = fill_summary
    elif not skip_fill_model and 'taker' in exec_mode:
        fill_result = {'total': len(trades), 'filled': len(trades), 'missed': 0,
                       'fill_rate': 1.0, 'note': 'taker: market orders'}

    post_fill_count = len(trades)
    post_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    m = compute_metrics(trades, total_bars, initial_capital=size)
    tb = tier_pnl_breakdown(trades)

    if len(trades) >= 2:
        max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    else:
        max_gap_days = total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
        max_gap_bars = total_bars

    print(f'    Baseline: {pre_fill_count}->{post_fill_count}tr '
          f'PF={m["pf"]:.3f} Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    # Stress 2x
    stress_fees = compute_stress_fees(regime, 2.0)
    stress_trades = run_combined_signal(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, stress_fees['tier1_fee'], stress_fees['tier2_fee'],
        config_params, signal_fn, initial_capital=size,
    )
    # Apply fill model to stress trades
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)
        st1 = [t for t in stress_trades if t.get('_tier') == 'tier1']
        st2 = [t for t in stress_trades if t.get('_tier') == 'tier2']
        ss = []
        if st1 and hs_t1 > 0:
            fm = full_fill_model_v3(st1, data, half_spread_bps=hs_t1)
            ss.extend(fm['trades'])
        elif st1:
            ss.extend(st1)
        if st2 and hs_t2 > 0:
            fm = full_fill_model_v3(st2, data, half_spread_bps=hs_t2)
            ss.extend(fm['trades'])
        elif st2:
            ss.extend(st2)
        stress_trades = ss

    sm = compute_metrics(stress_trades, total_bars, initial_capital=size)
    print(f'    Stress: {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.2f}')

    # Walk-Forward 5-fold
    print(f'  [{label}] Walk-forward 5-fold...')
    fold_trades = run_combined_wf_signal(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, signal_fn,
        n_folds=5, initial_capital=size,
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
            fs = []
            if ft1 and hs_t1 > 0:
                fm = full_fill_model_v3(ft1, data, half_spread_bps=hs_t1, seed=42 + fi)
                fs.extend(fm['trades'])
            elif ft1:
                fs.extend(ft1)
            if ft2 and hs_t2 > 0:
                fm = full_fill_model_v3(ft2, data, half_spread_bps=hs_t2, seed=42 + fi)
                fs.extend(fm['trades'])
            elif ft2:
                fs.extend(ft2)
            fold_tr = fs

        fpnl = sum(t['pnl'] for t in fold_tr)
        fn = len(fold_tr)
        pos = fpnl > 0
        if pos:
            wf_folds_positive += 1
        fold_pnls.append(fpnl)
        fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos})

    top1_fold_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    print(f'    WF: {wf_folds_positive}/5 positive, conc={top1_fold_conc:.3f}')

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
        },
        'pre_fill': {'trades': pre_fill_count, 'pnl': round(pre_fill_pnl, 2)},
        'post_fill': {'trades': post_fill_count, 'pnl': round(post_fill_pnl, 2)},
        'fill_model': fill_result,
        'metrics': {
            'total_trades': m['trades'],
            'profit_factor': m['pf'],
            'win_rate': m['wr'],
            'pnl': m['pnl'],
            'exp_per_week': m['exp_per_week'],
            'max_dd_pct': m['dd'],
            'trades_per_week': m['trades_per_week'],
        },
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
# Report builders
# ============================================================

def build_md_exploration(report, elapsed):
    """Build markdown report for signal exploration."""
    md = []
    hdr = report['header']
    md.append(f'# Bybit Signal Exploration: {hdr["signal_name"]}')
    md.append('')
    md.append(f'**Date**: {hdr["date"]}')
    md.append(f'**Commit**: {hdr["commit"]}')
    md.append(f'**Signal**: {hdr["signal_id"]} — {hdr["signal_name"]}')
    md.append(f'**Exchange**: Bybit (maker={hdr["fee_snapshot"]["maker_fee_bps"]}bps, '
              f'taker={hdr["fee_snapshot"]["taker_fee_bps"]}bps)')
    md.append(f'**Universe**: T1({hdr["n_t1"]}) + T2({hdr["n_t2"]}) = {hdr["n_total"]} coins')
    md.append(f'**Data**: {hdr["total_bars"]} bars ({hdr["total_weeks"]:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # Scoreboard
    md.append('## Scoreboard')
    md.append('')
    md.append('| Config | Regime | Size | Pre | Post | PF | Exp/Wk | DD% | WF | Gates |')
    md.append('|--------|--------|------|-----|------|----|----|-----|----|----|')

    for r in report['combinations']:
        m = r['metrics']
        wf = r.get('walk_forward', {})
        pre = r.get('pre_fill', {})
        gc = r.get('gates_passed', 0)
        gt = r.get('gates_total', 7)
        ap = r.get('all_gates_pass', False)
        gs = f'**{gc}/{gt}**' if ap else f'{gc}/{gt}'
        md.append(
            f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
            f'| {pre.get("trades", 0)} | {m["total_trades"]} '
            f'| {m["profit_factor"]:.3f} | ${m["exp_per_week"]:.2f} '
            f'| {m["max_dd_pct"]:.1f} | {wf.get("folds_positive", 0)}/5 | {gs} |'
        )
    md.append('')

    # Summary
    passing = [r for r in report['combinations'] if r.get('all_gates_pass')]
    md.append('## Summary')
    md.append('')
    md.append(f'- **Passing ALL gates**: {len(passing)}/{len(report["combinations"])}')
    if passing:
        for r in passing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}')
    md.append('')

    # Failed gates breakdown
    if not passing:
        md.append('### Failure Analysis')
        md.append('')
        gate_fail_counts = {}
        for r in report['combinations']:
            for g in r.get('failed_gates', []):
                gate_fail_counts[g] = gate_fail_counts.get(g, 0) + 1
        for g, cnt in sorted(gate_fail_counts.items(), key=lambda x: -x[1]):
            md.append(f'- {g}: fails in {cnt}/{len(report["combinations"])} combos')
        md.append('')

    md.append('---')
    md.append(f'*Generated by run_bybit_signal_exploration.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


def build_bakeoff_md(all_signal_results, elapsed):
    """Build markdown for multi-signal bake-off comparison."""
    md = []
    md.append('# Bybit Signal Bake-Off Scoreboard')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Exchange**: Bybit')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # Overview table: best combo per signal
    md.append('## Best Combo per Signal (maker_p50 / $200)')
    md.append('')
    md.append('| Signal | Config | Trades | PF | Exp/Wk | DD% | WF | Gates |')
    md.append('|--------|--------|--------|----|--------|-----|----|----|')

    for sig_id, result in sorted(all_signal_results.items()):
        # Find maker_p50 $200 combo (most relevant)
        best = None
        for r in result.get('combinations', []):
            if 'maker_p50' in r.get('regime', '') and r.get('size') == 200:
                if best is None or r['metrics']['profit_factor'] > best['metrics']['profit_factor']:
                    best = r
        if best is None and result.get('combinations'):
            best = max(result['combinations'], key=lambda x: x['metrics'].get('profit_factor', 0))
        if best:
            m = best['metrics']
            wf = best.get('walk_forward', {})
            gc = best.get('gates_passed', 0)
            gt = best.get('gates_total', 7)
            ap = best.get('all_gates_pass', False)
            gs = f'**{gc}/{gt}**' if ap else f'{gc}/{gt}'
            md.append(
                f'| {sig_id} | {best["config"]} | {m["total_trades"]} '
                f'| {m["profit_factor"]:.3f} | ${m["exp_per_week"]:.2f} '
                f'| {m["max_dd_pct"]:.1f} | {wf.get("folds_positive", 0)}/5 | {gs} |'
            )
    md.append('')

    # Full scoreboard per signal
    for sig_id, result in sorted(all_signal_results.items()):
        md.append(f'## {sig_id}: {SIGNAL_REGISTRY.get(sig_id, {}).get("name", sig_id)}')
        md.append('')
        passing = [r for r in result.get('combinations', []) if r.get('all_gates_pass')]
        md.append(f'Passing: {len(passing)}/{len(result.get("combinations", []))}')
        md.append('')

        md.append('| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |')
        md.append('|--------|--------|------|--------|----|--------|-----|----|----|')
        for r in result.get('combinations', []):
            m = r['metrics']
            wf = r.get('walk_forward', {})
            gc = r.get('gates_passed', 0)
            gt = r.get('gates_total', 7)
            ap = r.get('all_gates_pass', False)
            gs = f'**{gc}/{gt}**' if ap else f'{gc}/{gt}'
            md.append(
                f'| {r["config"]} | {r["regime"][:22]} | ${r["size"]} '
                f'| {m["total_trades"]} | {m["profit_factor"]:.3f} '
                f'| ${m["exp_per_week"]:.2f} | {m["max_dd_pct"]:.1f} '
                f'| {wf.get("folds_positive", 0)}/5 | {gs} |'
            )
        md.append('')

    md.append('---')
    md.append(f'*Generated by run_bybit_signal_exploration.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


# ============================================================
# Data loading (shared infrastructure)
# ============================================================

def load_bybit_infra():
    """Load all Bybit data: candles, tiering, OB costs, indicators."""
    exchange_id = 'bybit'
    exchange_cfg = get_exchange(exchange_id)
    fee_snap = FeeSnapshot(
        exchange_id='bybit',
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        region='EU',
        account_tier='regular',
        source='signal exploration run',
    )

    # Load OB regimes
    ob_report_path = ROOT / 'reports' / 'hf' / 'bybit_orderbook_costs_001.json'
    with open(ob_report_path) as f:
        ob_report = json.load(f)
    measured_regimes = ob_report.get('regimes', {})
    distributions = ob_report.get('distributions', {})
    for name, regime in measured_regimes.items():
        if name in REGIMES_TO_TEST:
            if name not in COST_REGIMES:
                register_regime(name, regime)
            print(f'  Regime: {name} -> '
                  f'T1={regime["tier1"]["total_per_side_bps"]}bps '
                  f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # Load candle data
    data = load_candle_cache_exchange(exchange_id, require_data=True)
    available_coins = set(data.keys())

    tiering = load_universe_tiering_exchange(exchange_id, require_data=True)
    tier_coins = build_tier_coins(tiering, available_coins)

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_t1 + n_t2} coins')

    # Precompute indicators
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP + z-score fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # Market context
    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    # Estimate total bars
    total_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > total_bars:
                total_bars = n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # Z-score sanity check: coverage, boundedness, warmup, NaN-free
    n_zscore_avail = 0
    zscore_all_vals = []
    zscore_warmup_bars = []
    for tier_name, ind_dict in tier_indicators.items():
        for coin, ind in ind_dict.items():
            zs = ind.get('vwap_dev_zscore', [])
            valid = [z for z in zs if z is not None]
            if valid:
                n_zscore_avail += 1
                zscore_all_vals.extend(valid)
                # Find first non-None index (warmup period)
                for i, z in enumerate(zs):
                    if z is not None:
                        zscore_warmup_bars.append(i)
                        break

    n_total_coins = n_t1 + n_t2
    print(f'[Z-Score] Coins with z-score data: {n_zscore_avail}/{n_total_coins}')

    if zscore_all_vals:
        import math
        has_nan = any(math.isnan(z) for z in zscore_all_vals)
        has_inf = any(math.isinf(z) for z in zscore_all_vals)
        zmin = min(zscore_all_vals)
        zmax = max(zscore_all_vals)
        zmean = sum(zscore_all_vals) / len(zscore_all_vals)
        # p90 of absolute z-scores
        abs_zs = sorted(abs(z) for z in zscore_all_vals)
        zp90 = abs_zs[int(len(abs_zs) * 0.9)]
        zp99 = abs_zs[int(len(abs_zs) * 0.99)]
        median_warmup = sorted(zscore_warmup_bars)[len(zscore_warmup_bars) // 2] if zscore_warmup_bars else 0
        n_above_2 = sum(1 for z in zscore_all_vals if z >= 2.0)
        n_above_1_5 = sum(1 for z in zscore_all_vals if z >= 1.5)

        print(f'  NaN={has_nan} Inf={has_inf} range=[{zmin:.2f}, {zmax:.2f}] '
              f'mean={zmean:.3f} |z|p90={zp90:.2f} |z|p99={zp99:.2f}')
        print(f'  Warmup: median={median_warmup} bars (first valid z-score)')
        print(f'  Triggers: z>=2.0: {n_above_2} bars | z>=1.5: {n_above_1_5} bars '
              f'(across {n_zscore_avail} coins, {len(zscore_all_vals)} total bars)')

        if has_nan or has_inf:
            print(f'  [WARN] NaN/Inf detected in z-scores — investigate!')
        if zp99 > 10:
            print(f'  [WARN] Extreme z-scores detected (p99={zp99:.1f}) — check for thin data')
    else:
        print(f'  [WARN] No z-score data computed — HLC3 VWAP may be missing')

    return {
        'data': data,
        'tier_coins': tier_coins,
        'tier_indicators': tier_indicators,
        'market_context': market_context,
        'measured_regimes': measured_regimes,
        'distributions': distributions,
        'total_bars': total_bars,
        'total_weeks': total_weeks,
        'fee_snap': fee_snap,
        'n_t1': n_t1,
        'n_t2': n_t2,
    }


# ============================================================
# Run one signal through the matrix
# ============================================================

def run_signal_matrix(signal_id, configs, infra, skip_fill_model=False):
    """Run all configs x regimes x sizes for one signal."""
    sig_info = SIGNAL_REGISTRY[signal_id]
    signal_fn = sig_info['fn']

    data = infra['data']
    t1_coins = infra['tier_coins']['tier1']
    t2_coins = infra['tier_coins']['tier2']
    t1_indicators = infra['tier_indicators'].get('tier1', {})
    t2_indicators = infra['tier_indicators'].get('tier2', {})
    market_ctx = infra['market_context']
    total_bars = infra['total_bars']
    distributions = infra['distributions']
    measured_regimes = infra['measured_regimes']

    all_results = []
    combo_idx = 0
    total_combos = len(configs) * len(REGIMES_TO_TEST) * len(SIZES)

    for config_name, config_params in configs.items():
        for regime_name in REGIMES_TO_TEST:
            base_regime = measured_regimes[regime_name]

            for size in SIZES:
                combo_idx += 1
                print(f'\n--- [{signal_id}] Combo {combo_idx}/{total_combos}: '
                      f'{config_name}/{regime_name}/${size} ---')

                if distributions is not None:
                    regime = build_size_specific_regime(base_regime, distributions, size)
                else:
                    regime = base_regime

                result = analyze_combination_signal(
                    config_name=config_name,
                    config_params=config_params,
                    regime_name=regime_name,
                    regime=regime,
                    size=size,
                    data=data,
                    t1_coins=t1_coins,
                    t2_coins=t2_coins,
                    t1_indicators=t1_indicators,
                    t2_indicators=t2_indicators,
                    market_ctx=market_ctx,
                    total_bars=total_bars,
                    distributions=distributions,
                    signal_fn=signal_fn,
                    skip_fill_model=skip_fill_model,
                )
                all_results.append(result)

    return all_results


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Bybit Signal Exploration: run any signal through 24-combo matrix',
    )
    parser.add_argument('--signal', type=str, default='H20Z',
                        choices=list(SIGNAL_REGISTRY.keys()),
                        help='Signal ID to test (default: H20Z)')
    parser.add_argument('--config', type=str, default=None,
                        help='Specific config name (default: all configs for signal)')
    parser.add_argument('--bakeoff', action='store_true',
                        help='Run multi-signal bake-off (H16, H17, H18, H19, H20Z)')
    parser.add_argument('--skip-fill-model', action='store_true',
                        help='Skip fill model for faster iteration')
    parser.add_argument('--output-label', type=str, default='001',
                        help='Output file label (default: 001)')

    args = parser.parse_args()

    sep = '=' * 70

    # Git commit
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    t0 = time.time()

    # Load all Bybit infrastructure (once for all signals)
    print(sep)
    print('  Loading Bybit infrastructure...')
    print(sep)
    infra = load_bybit_infra()

    if args.bakeoff:
        # Multi-signal bake-off
        bakeoff_signals = ['H20Z', 'H16', 'H17', 'H18', 'H19']
        print(f'\n{sep}')
        print(f'  BAKE-OFF: Testing {len(bakeoff_signals)} signals')
        print(sep)

        all_signal_results = {}

        for sig_id in bakeoff_signals:
            print(f'\n{"="*50}')
            print(f'  Signal: {sig_id} — {SIGNAL_REGISTRY[sig_id]["name"]}')
            print(f'{"="*50}')

            configs = SIGNAL_CONFIGS.get(sig_id, {})
            if not configs:
                print(f'  [WARN] No configs defined for {sig_id}, skipping')
                continue

            results = run_signal_matrix(sig_id, configs, infra,
                                        skip_fill_model=args.skip_fill_model)

            all_signal_results[sig_id] = {
                'signal_id': sig_id,
                'signal_name': SIGNAL_REGISTRY[sig_id]['name'],
                'combinations': results,
            }

        elapsed = time.time() - t0

        # Save bake-off report
        report = {
            'header': {
                'task': 'bybit_signal_bakeoff',
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'commit': commit,
                'exchange': 'bybit',
                'fee_snapshot': {
                    'maker_fee_bps': infra['fee_snap'].maker_fee_bps,
                    'taker_fee_bps': infra['fee_snap'].taker_fee_bps,
                },
                'signals_tested': bakeoff_signals,
                'n_t1': infra['n_t1'],
                'n_t2': infra['n_t2'],
                'n_total': infra['n_t1'] + infra['n_t2'],
                'total_bars': infra['total_bars'],
                'total_weeks': infra['total_weeks'],
                'runtime_s': round(elapsed, 1),
            },
            'signal_results': all_signal_results,
        }

        out_dir = ROOT / 'reports' / 'hf'
        json_path = out_dir / f'bybit_signal_bakeoff_{args.output_label}.json'
        json_path.write_text(json.dumps(report, indent=2, default=str))
        print(f'\n[Report] JSON: {json_path}')

        md_text = build_bakeoff_md(all_signal_results, elapsed)
        md_path = out_dir / f'bybit_signal_bakeoff_{args.output_label}.md'
        md_path.write_text(md_text)
        print(f'[Report] MD:   {md_path}')

        # Final scoreboard
        print(f'\n{sep}')
        print(f'  BAKE-OFF COMPLETE ({elapsed:.1f}s)')
        print(sep)
        for sig_id, result in all_signal_results.items():
            combos = result.get('combinations', [])
            passing = [r for r in combos if r.get('all_gates_pass')]
            best = max(combos, key=lambda x: x['metrics'].get('profit_factor', 0)) if combos else None
            bpf = best['metrics']['profit_factor'] if best else 0
            btrades = best['metrics']['total_trades'] if best else 0
            print(f'  {sig_id:5s} {SIGNAL_REGISTRY[sig_id]["name"]:30s} '
                  f'Pass={len(passing)}/{len(combos)} '
                  f'Best: {btrades}tr PF={bpf:.3f}')

    else:
        # Single signal run
        signal_id = args.signal
        sig_info = SIGNAL_REGISTRY[signal_id]

        print(f'\n{sep}')
        print(f'  Signal: {signal_id} — {sig_info["name"]}')
        print(sep)

        # Determine configs
        all_configs = SIGNAL_CONFIGS.get(signal_id, {})
        if args.config:
            if args.config in all_configs:
                configs = {args.config: all_configs[args.config]}
            else:
                print(f'[ERROR] Config {args.config} not found for {signal_id}')
                print(f'  Available: {list(all_configs.keys())}')
                sys.exit(1)
        else:
            configs = all_configs

        if not configs:
            print(f'[ERROR] No configs defined for signal {signal_id}')
            sys.exit(1)

        results = run_signal_matrix(signal_id, configs, infra,
                                    skip_fill_model=args.skip_fill_model)

        elapsed = time.time() - t0

        # Save report
        report = {
            'header': {
                'signal_id': signal_id,
                'signal_name': sig_info['name'],
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'commit': commit,
                'exchange': 'bybit',
                'fee_snapshot': {
                    'exchange_id': 'bybit',
                    'maker_fee_bps': infra['fee_snap'].maker_fee_bps,
                    'taker_fee_bps': infra['fee_snap'].taker_fee_bps,
                    'region': infra['fee_snap'].region,
                    'account_tier': infra['fee_snap'].account_tier,
                    'source': infra['fee_snap'].source,
                },
                'configs': {k: v for k, v in configs.items()},
                'regimes_tested': REGIMES_TO_TEST,
                'sizes': SIZES,
                'n_t1': infra['n_t1'],
                'n_t2': infra['n_t2'],
                'n_total': infra['n_t1'] + infra['n_t2'],
                'coin_universe': 'full_bybit',
                'total_bars': infra['total_bars'],
                'total_weeks': infra['total_weeks'],
                'zscore_params': {
                    'lookback_window': 50,
                    'min_history': 20,
                    'normalization': 'rolling z-score of (vwap - close) / atr',
                    'vwap_source': 'HLC3 proxy (H+L+C)/3',
                },
                'runtime_s': round(elapsed, 1),
            },
            'combinations': results,
        }

        out_dir = ROOT / 'reports' / 'hf'
        json_path = out_dir / f'part2_bybit_{signal_id.lower()}_{args.output_label}.json'
        json_path.write_text(json.dumps(report, indent=2, default=str))
        print(f'\n[Report] JSON: {json_path}')

        md_text = build_md_exploration(report, elapsed)
        md_path = out_dir / f'part2_bybit_{signal_id.lower()}_{args.output_label}.md'
        md_path.write_text(md_text)
        print(f'[Report] MD:   {md_path}')

        # Final summary
        print(f'\n{sep}')
        print(f'  {signal_id} ON BYBIT COMPLETE ({elapsed:.1f}s)')
        print(sep)
        for r in results:
            m = r['metrics']
            gc = r.get('gates_passed', 0)
            gt = r.get('gates_total', 7)
            ap = r.get('all_gates_pass', False)
            status = 'ALL PASS' if ap else f'FAIL ({", ".join(r.get("failed_gates", []))})'
            print(f'  {r["config"]:12s} {r["regime"]:28s} ${r["size"]:>5} '
                  f'{m["total_trades"]:>4}tr PF={m["profit_factor"]:.3f} '
                  f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["max_dd_pct"]:.1f}% '
                  f'Gates={gc}/{gt} {status}')

        passing = [r for r in results if r.get('all_gates_pass')]
        print(f'\n  Passing: {len(passing)}/{len(results)}')


if __name__ == '__main__':
    main()
