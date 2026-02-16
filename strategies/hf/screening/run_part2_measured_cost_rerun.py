#!/usr/bin/env python3
"""
Part 2: Measured Orderbook Cost Rerun (P0-3)
=============================================
Test the H20 VWAP_DEVIATION signal under measured orderbook cost regimes.

Matrix:
  2 configs (v5 baseline, sl7 variant)
  x 4 regimes (measured maker/taker at P50/P90)
  x 3 trade sizes ($200, $500, $2000)
  = 24 backtests

Each combination:
  - Bar-structure fill model (fill_model_v3)
  - Stress testing 2x fees
  - Walk-forward 5-fold (with fill model per fold)
  - 7 STRICT gate evaluation

Output:
  reports/hf/part2_measured_cost_rerun_001.json
  reports/hf/part2_measured_cost_rerun_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_measured_cost_rerun.py
    python strategies/hf/screening/run_part2_measured_cost_rerun.py --dry-run
    python strategies/hf/screening/run_part2_measured_cost_rerun.py --config v5
    python strategies/hf/screening/run_part2_measured_cost_rerun.py --skip-fill-model
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

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
    register_regime, get_harness_fee, COST_REGIMES,
)
from strategies.hf.screening.fill_model_v3 import full_fill_model_v3
from strategies.hf.screening.orderbook_analysis import (
    load_snapshots, compute_distributions, build_measured_regimes,
)

# Import reusable functions from the existing runner
from strategies.hf.screening.run_part2_exec_realism_002 import (
    load_candle_cache, load_universe_tiering, build_tier_coins,
    compute_metrics, compute_max_gap, compute_fold_concentration,
    evaluate_gates_strict, tier_pnl_breakdown,
    BARS_PER_WEEK, BARS_PER_DAY, EXCLUDED_COINS,
)

# ============================================================
# Config matrix
# ============================================================

CONFIGS = {
    'v5': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
    'sl7': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10},
}

REGIMES_TO_TEST = [
    'measured_ob_maker_p50', 'measured_ob_maker_p90',
    'measured_ob_taker_p50', 'measured_ob_taker_p90',
]

SIZES = [200, 500, 2000]


# ============================================================
# Size-specific regime adjustment
# ============================================================

def build_size_specific_regime(base_regime, distributions, size):
    """Adjust taker regime slippage based on trade size.

    For maker regimes: slippage is adverse selection (spread-based), not size-dependent.
    For taker regimes: replace slippage_200_bps with the appropriate size bucket.

    Parameters
    ----------
    base_regime : dict from build_measured_regimes()
    distributions : dict from compute_distributions()
    size : int, one of 200, 500, 2000

    Returns
    -------
    dict : adjusted regime (new dict, does not mutate base_regime)
    """
    import copy
    regime = copy.deepcopy(base_regime)
    exec_mode = regime.get('execution_mode', '')

    # Maker regimes: adverse selection is spread-based, not size-dependent
    if 'maker' in exec_mode:
        return regime

    # Taker regimes: adjust slippage per size
    size_key = f'slippage_{size}_bps'
    pct_label = regime.get('percentile', 'p50')

    for tier_key in ('tier1', 'tier2'):
        tier_dist = distributions.get(tier_key, {})
        slip_dist = tier_dist.get(size_key, {})
        new_slip = slip_dist.get(pct_label, 0.0)

        tier = regime[tier_key]
        old_slip = tier.get('slippage_bps', 0.0)
        tier['slippage_bps'] = round(new_slip, 1)

        # Recompute total
        total = (
            tier.get('exchange_fee_bps', 0.0)
            + tier.get('spread_bps', 0.0)
            + tier['slippage_bps']
            + tier.get('adverse_selection_bps', 0.0)
        )
        tier['total_per_side_bps'] = round(total, 1)

    regime['description'] += f' (size=${size})'
    return regime


def get_half_spread_for_fill(distributions, tier_key, exec_mode):
    """Determine half_spread_bps for the fill model.

    Maker mode: use measured P50 spread / 2 as half-spread.
      (Limit at bid, price needs to drop half-spread to fill.)
    Taker mode: 0 (market order, always fills -> skip fill model).

    Parameters
    ----------
    distributions : dict from compute_distributions()
    tier_key : 'tier1' or 'tier2'
    exec_mode : 'maker_limit' or 'taker_market'

    Returns
    -------
    float : half_spread_bps, or 0.0 for taker
    """
    if 'taker' in exec_mode:
        return 0.0  # Market order: always fills

    tier_dist = distributions.get(tier_key, {})
    spread_dist = tier_dist.get('spread_bps', {})
    spread_p50 = spread_dist.get('p50', 0.0)
    return spread_p50 / 2.0


# ============================================================
# Backtest runners (with initial_capital / size support)
# ============================================================

def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                 market_ctx, t1_fee, t2_fee, params, initial_capital=2000.0):
    """Run backtests for T1 and T2 separately, merge trade lists."""
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
    """Run walk-forward for T1 and T2 separately, merge fold trades."""
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
# Stress fee helper
# ============================================================

def compute_stress_fees(regime_info, multiplier=2.0):
    """Compute stress fees by multiplying a regime's per-side fees."""
    t1_total = regime_info.get('tier1', {}).get('total_per_side_bps', 0.0)
    t2_total = regime_info.get('tier2', {}).get('total_per_side_bps', 0.0)
    return {
        'tier1_fee': t1_total * multiplier / 10000.0,
        'tier2_fee': t2_total * multiplier / 10000.0,
        'tier1_bps': round(t1_total * multiplier, 1),
        'tier2_bps': round(t2_total * multiplier, 1),
    }


# ============================================================
# Single combination analysis
# ============================================================

def analyze_combination(
    config_name, config_params, regime_name, regime, size,
    data, t1_coins, t2_coins, t1_indicators, t2_indicators,
    market_ctx, total_bars, distributions, skip_fill_model=False,
):
    """Run full analysis for one config x regime x size combination."""
    t_start = time.time()
    exec_mode = regime.get('execution_mode', '')

    # --- Per-tier fees ---
    t1_fee = regime['tier1']['total_per_side_bps'] / 10000.0
    t2_fee = regime['tier2']['total_per_side_bps'] / 10000.0

    label = f'{config_name}/{regime_name}/${size}'
    print(f'  [{label}] fees T1={regime["tier1"]["total_per_side_bps"]}bps '
          f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # --- Baseline backtest ---
    print(f'  [{label}] Running baseline backtest...')
    trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, initial_capital=size,
    )
    pre_fill_count = len(trades)
    pre_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    # --- Fill model ---
    fill_result = None
    if not skip_fill_model and 'maker' in exec_mode:
        # Maker mode: apply bar-structure fill model
        # Use the larger half-spread for fill model (T2 is wider)
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)

        # Apply fill model per tier
        t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
        t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
        surviving = []

        fill_summary_combined = {
            'total': len(trades), 'filled': 0, 'missed': 0,
            'fill_rate': 0.0, 'tier_detail': {},
        }

        if t1_trades and hs_t1 > 0:
            fm_t1 = full_fill_model_v3(
                t1_trades, data, half_spread_bps=hs_t1,
            )
            surviving.extend(fm_t1['trades'])
            fill_summary_combined['tier_detail']['tier1'] = fm_t1['fill_summary']
            fill_summary_combined['filled'] += fm_t1['fill_summary']['filled']
            fill_summary_combined['missed'] += fm_t1['fill_summary']['missed']
        elif t1_trades:
            surviving.extend(t1_trades)
            fill_summary_combined['filled'] += len(t1_trades)

        if t2_trades and hs_t2 > 0:
            fm_t2 = full_fill_model_v3(
                t2_trades, data, half_spread_bps=hs_t2,
            )
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
        # Taker mode: market orders always fill, no fill model needed
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

    # --- Stress 2x ---
    stress_fees = compute_stress_fees(regime, 2.0)
    print(f'  [{label}] Running stress 2x backtest '
          f'(T1={stress_fees["tier1_bps"]}bps, T2={stress_fees["tier2_bps"]}bps)...')
    stress_trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, stress_fees['tier1_fee'], stress_fees['tier2_fee'],
        config_params, initial_capital=size,
    )

    # Apply fill model to stress trades too
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

    # --- Walk-Forward 5-fold ---
    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_combined_wf(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, n_folds=5,
        initial_capital=size,
    )

    # Apply fill model per fold for maker regimes
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

    # --- Gate evaluation ---
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
        'pre_fill': {
            'trades': pre_fill_count,
            'pnl': round(pre_fill_pnl, 2),
        },
        'post_fill': {
            'trades': post_fill_count,
            'pnl': round(post_fill_pnl, 2),
        },
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
# Markdown report
# ============================================================

def build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks):
    md = []
    md.append('# Part 2: Measured Orderbook Cost Rerun (P0-3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5/sl7 variants')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append(f'**Matrix**: {report["run_header"]["matrix_description"]}')
    md.append('')

    # Objective
    md.append('## Objective')
    md.append('')
    md.append('Test strategy resilience under measured orderbook cost regimes with:')
    md.append('- **Configs**: v5 baseline (sl=5) and sl7 variant (sl=7)')
    md.append('- **Regimes**: Measured maker/taker costs at P50 and P90 from live orderbook data')
    md.append('- **Sizes**: $200, $500, $2000 per trade (size-dependent slippage for taker)')
    md.append('- **Fill model**: Bar-structure fill probability for maker limit orders')
    md.append('')
    md.append('STRICT gate thresholds: G1>=10 trades/wk, G2<=2.5d gap, G3/G4>$0 exp/wk,')
    md.append('G5<=20% DD, G6>=4/5 WF folds, G8<35% fold concentration.')
    md.append('')

    # Summary scoreboard
    md.append('## Summary Scoreboard')
    md.append('')
    md.append('| Config | Regime | Size | T1 bps | T2 bps | Pre-Fill | Post-Fill | PF | Exp/Wk | DD% | WF | Gates |')
    md.append('|--------|--------|------|--------|--------|----------|-----------|----|----|-----|----|----|')

    for r in report['combinations']:
        m = r['baseline']
        wf = r.get('walk_forward', {})
        wf_str = f'{wf.get("folds_positive", 0)}/5'

        fees = r.get('fees', {})
        t1b = fees.get('tier1_bps', '-')
        t2b = fees.get('tier2_bps', '-')

        pre = r.get('pre_fill', {})
        post = r.get('post_fill', {})

        gate_info = r.get('gates_passed', '-')
        gate_total = r.get('gates_total', '-')
        if r.get('all_gates_pass'):
            gate_str = f'**{gate_info}/{gate_total}**'
        else:
            gate_str = f'{gate_info}/{gate_total}'

        md.append(
            f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
            f'| {t1b} | {t2b} | {pre.get("trades", 0)} | {post.get("trades", 0)} '
            f'| {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} '
            f'| {m["dd"]:.1f} | {wf_str} | {gate_str} |'
        )
    md.append('')

    # Pass/fail summary
    passing = [r for r in report['combinations'] if r.get('all_gates_pass')]
    failing = [r for r in report['combinations'] if not r.get('all_gates_pass')]

    md.append('## Gate Results Summary')
    md.append('')
    md.append(f'- **Passing ALL gates**: {len(passing)}/{len(report["combinations"])}')
    if passing:
        md.append('')
        for r in passing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}')
    md.append('')
    if failing:
        md.append(f'- **Failing**: {len(failing)}/{len(report["combinations"])}')
        md.append('')
        for r in failing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                      f'fails {", ".join(r.get("failed_gates", []))}')
        md.append('')

    # Fill model impact (maker regimes only)
    maker_results = [r for r in report['combinations'] if 'maker' in r.get('execution_mode', '')]
    if maker_results:
        md.append('## Fill Model Impact (Maker Regimes)')
        md.append('')
        md.append('| Config | Regime | Size | Pre-Fill Trades | Post-Fill Trades | Fill Rate | Pre PnL | Post PnL |')
        md.append('|--------|--------|------|-----------------|------------------|-----------|---------|----------|')

        for r in maker_results:
            pre = r.get('pre_fill', {})
            post = r.get('post_fill', {})
            fm = r.get('fill_model', {})
            fr = fm.get('fill_rate', 1.0) if fm else 1.0
            md.append(
                f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
                f'| {pre.get("trades", 0)} | {post.get("trades", 0)} '
                f'| {fr:.1%} | ${pre.get("pnl", 0):.0f} | ${post.get("pnl", 0):.0f} |'
            )
        md.append('')

    # Per-combination detail sections
    for r in report['combinations']:
        md.append(f'### {r["config"]} / {r["regime"]} / ${r["size"]}')
        md.append('')
        md.append(f'- **Execution mode**: {r.get("execution_mode", "?")}')
        md.append(f'- **Fees**: T1={r["fees"]["tier1_bps"]}bps, T2={r["fees"]["tier2_bps"]}bps per side')

        m = r['baseline']
        md.append(f'- **Baseline**: {m["trades"]}tr, PF={m["pf"]:.3f}, WR={m["wr"]:.1f}%, '
                  f'P&L=${m["pnl"]:.0f}, Exp/Wk=${m["exp_per_week"]:.2f}, DD={m["dd"]:.1f}%')

        pre = r.get('pre_fill', {})
        post = r.get('post_fill', {})
        if pre.get('trades', 0) != post.get('trades', 0):
            md.append(f'- **Fill model**: {pre["trades"]} -> {post["trades"]} trades '
                      f'(PnL ${pre["pnl"]:.0f} -> ${post["pnl"]:.0f})')

        gap = r.get('max_gap', {})
        md.append(f'- **Max Gap**: {gap.get("days", "?")}d ({gap.get("bars", "?")} bars)')

        s = r.get('stress_2x', {})
        md.append(f'- **Stress 2x**: {s.get("trades", "?")}tr, PF={s.get("pf", 0):.3f}, '
                  f'Exp/Wk=${s.get("exp_per_week", 0):.2f}')

        wf = r.get('walk_forward', {})
        md.append(f'- **Walk-Forward**: {wf.get("folds_positive", 0)}/5 folds positive, '
                  f'top1 conc={wf.get("top1_fold_conc", 0):.3f}')
        md.append('')

        # Gate table
        md.append('| Gate | Value | Threshold | Verdict |')
        md.append('|------|-------|-----------|---------|')
        for gname, ginfo in r['gates'].items():
            val = ginfo['value']
            thr = ginfo['threshold']
            p = ginfo['pass']
            verdict = 'PASS' if p else '**FAIL**'
            md.append(f'| {gname} | {val} | {thr} | {verdict} |')
        md.append('')

        # Fold details
        fold_details = wf.get('fold_details', [])
        if fold_details:
            md.append('| Fold | Trades | P&L | Positive? |')
            md.append('|------|--------|-----|-----------|')
            for fd in fold_details:
                md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.0f} | '
                          f'{"Yes" if fd["positive"] else "No"} |')
            md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_measured_cost_rerun.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2: Measured Orderbook Cost Rerun (P0-3)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    parser.add_argument('--config', choices=['v5', 'sl7', 'both'], default='both',
                        help='Config to test (default: both)')
    parser.add_argument('--skip-fill-model', action='store_true',
                        help='Skip fill model for faster iteration')
    parser.add_argument('--measured-report', type=str,
                        default=str(ROOT / 'reports' / 'hf' / 'mexc_orderbook_costs_001.json'),
                        help='Path to measured orderbook report JSON (alternative to raw snapshots)')
    parser.add_argument('--orderbook-input', type=str,
                        default=str(ROOT / 'data' / 'orderbook_snapshots' / 'mexc_orderbook_001.jsonl'),
                        help='Path to raw orderbook JSONL snapshots')
    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Part 2: Measured Orderbook Cost Rerun (P0-3)')
    print('  H20 VWAP_DEVIATION v5/sl7 | Measured OB Regimes | STRICT Gates')
    print(sep)
    t0 = time.time()

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Select configs ---
    if args.config == 'both':
        configs_to_test = CONFIGS
    else:
        configs_to_test = {args.config: CONFIGS[args.config]}

    # --- Load orderbook data and build measured regimes ---
    print('[Orderbook] Loading measured cost data...')
    distributions = None

    # Try loading from the pre-computed report first
    measured_report_path = Path(args.measured_report)
    if measured_report_path.exists():
        print(f'  Loading from report: {measured_report_path}')
        with open(measured_report_path) as f:
            ob_report = json.load(f)
        distributions = ob_report.get('distributions', {})
        measured_regimes = ob_report.get('regimes', {})
        print(f'  Found {len(measured_regimes)} regimes from report')
    else:
        # Fall back to raw JSONL
        ob_input = Path(args.orderbook_input)
        if not ob_input.exists():
            print(f'[ERROR] No orderbook data found at {ob_input} or {measured_report_path}')
            print('  Run orderbook_analysis.py first, or provide --measured-report / --orderbook-input')
            sys.exit(1)
        print(f'  Loading raw snapshots from: {ob_input}')
        snapshots = load_snapshots(str(ob_input))
        distributions = compute_distributions(snapshots)
        measured_regimes = build_measured_regimes(distributions)

    # Register measured regimes
    for name, regime in measured_regimes.items():
        if name in REGIMES_TO_TEST:
            register_regime(name, regime)
            print(f'  Registered: {name} -> '
                  f'T1={regime["tier1"]["total_per_side_bps"]}bps '
                  f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # Verify all required regimes exist
    missing = [r for r in REGIMES_TO_TEST if r not in COST_REGIMES]
    if missing:
        print(f'[ERROR] Missing regimes: {missing}')
        print(f'  Available: {list(COST_REGIMES.keys())}')
        sys.exit(1)

    # --- Load candle data ---
    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # Apply exclusion
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (after exclusion)')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    n_configs = len(configs_to_test)
    n_regimes = len(REGIMES_TO_TEST)
    n_sizes = len(SIZES)
    n_combos = n_configs * n_regimes * n_sizes

    if args.dry_run:
        print(f'\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  Configs: {list(configs_to_test.keys())}')
        print(f'  Regimes: {REGIMES_TO_TEST}')
        print(f'  Sizes: {SIZES}')
        print(f'  Total combinations: {n_combos}')
        print(f'  Each: baseline + stress 2x + WF 5-fold + fill model + gates')
        print(f'  Skip fill model: {args.skip_fill_model}')
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

    t1_indicators = tier_indicators.get('tier1', {})
    t2_indicators = tier_indicators.get('tier2', {})
    t1_coins = tier_coins['tier1']
    t2_coins = tier_coins['tier2']

    # ============================================================
    # Run all combinations
    # ============================================================
    all_results = []
    combo_idx = 0

    for config_name, config_params in configs_to_test.items():
        for regime_name in REGIMES_TO_TEST:
            base_regime = measured_regimes[regime_name]

            for size in SIZES:
                combo_idx += 1
                print(f'\n{sep}')
                print(f'  COMBINATION {combo_idx}/{n_combos}: '
                      f'{config_name} / {regime_name} / ${size}')
                print(sep)

                # Build size-specific regime (adjusts taker slippage for size)
                if distributions is not None:
                    regime = build_size_specific_regime(
                        base_regime, distributions, size,
                    )
                else:
                    regime = base_regime

                result = analyze_combination(
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
                    market_ctx=market_context,
                    total_bars=total_bars,
                    distributions=distributions,
                    skip_fill_model=args.skip_fill_model,
                )
                all_results.append(result)

    elapsed = time.time() - t0

    # ============================================================
    # Verdict
    # ============================================================
    verdict_lines = []
    passing = [r for r in all_results if r.get('all_gates_pass')]
    failing = [r for r in all_results if not r.get('all_gates_pass')]

    verdict_lines.append(
        f'**Combinations passing ALL STRICT gates**: {len(passing)}/{len(all_results)}'
    )
    verdict_lines.append('')

    if passing:
        verdict_lines.append('**Passing combinations**:')
        for r in passing:
            m = r['baseline']
            verdict_lines.append(
                f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                f'{m["trades"]}tr PF={m["pf"]:.3f} Exp/wk=${m["exp_per_week"]:.2f}'
            )
        verdict_lines.append('')

    if failing:
        verdict_lines.append('**Failing combinations**:')
        for r in failing:
            verdict_lines.append(
                f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                f'fails {", ".join(r.get("failed_gates", []))}'
            )
        verdict_lines.append('')

    # Size sensitivity
    verdict_lines.append('**Size sensitivity** (v5 config, same regime):')
    for regime_name in REGIMES_TO_TEST:
        size_results = [r for r in all_results
                        if r['config'] == 'v5' and r['regime'] == regime_name]
        if size_results:
            verdict_lines.append(f'  {regime_name}:')
            for r in sorted(size_results, key=lambda x: x['size']):
                m = r['baseline']
                verdict_lines.append(
                    f'    ${r["size"]}: {m["trades"]}tr PF={m["pf"]:.3f} '
                    f'Exp/wk=${m["exp_per_week"]:.2f} '
                    f'{"PASS" if r["all_gates_pass"] else "FAIL"}'
                )
    verdict_lines.append('')

    # Maker vs taker comparison
    verdict_lines.append('**Maker vs Taker** (v5 config, $200 size):')
    for pct in ('p50', 'p90'):
        maker = next((r for r in all_results
                      if r['config'] == 'v5' and r['size'] == 200
                      and f'maker_{pct}' in r['regime']), None)
        taker = next((r for r in all_results
                      if r['config'] == 'v5' and r['size'] == 200
                      and f'taker_{pct}' in r['regime']), None)
        if maker and taker:
            mm = maker['baseline']
            tm = taker['baseline']
            verdict_lines.append(
                f'  {pct}: maker {mm["trades"]}tr Exp/wk=${mm["exp_per_week"]:.2f} '
                f'vs taker {tm["trades"]}tr Exp/wk=${tm["exp_per_week"]:.2f}'
            )
    verdict_lines.append('')

    # Overall
    if len(passing) == len(all_results):
        verdict_lines.append(
            '**CONCLUSION**: Strategy passes ALL STRICT gates under ALL measured cost regimes '
            'and trade sizes. Orderbook-measured costs are NOT a concern.'
        )
    elif len(passing) > len(all_results) * 0.5:
        verdict_lines.append(
            f'**CONCLUSION**: Strategy passes STRICT gates in {len(passing)}/{len(all_results)} '
            f'combinations. Some regimes/sizes erode edge. Review failing combinations.'
        )
    else:
        verdict_lines.append(
            f'**CONCLUSION**: Strategy fails STRICT gates in majority of combinations '
            f'({len(failing)}/{len(all_results)}). Measured costs may be too high for STRICT thresholds.'
        )

    # ============================================================
    # JSON Report
    # ============================================================
    report = {
        'run_header': {
            'task': 'part2_measured_cost_rerun_001',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'configs': {k: v for k, v in configs_to_test.items()},
            'regimes_tested': REGIMES_TO_TEST,
            'sizes': SIZES,
            'matrix_description': (
                f'{n_configs} configs x {n_regimes} regimes x {n_sizes} sizes '
                f'= {n_combos} combinations'
            ),
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
            'fill_model': 'fill_model_v3 (bar-structure, maker regimes only)',
            'skip_fill_model': args.skip_fill_model,
            'strict_gates': {
                'G1': '>=10 trades/week',
                'G2': '<=2.5 days max gap',
                'G3': '>$0 exp/week (market)',
                'G4': '>$0 exp/week (stress 2x)',
                'G5': '<=20% max DD',
                'G6': '>=4/5 WF folds positive',
                'G8': '<35% top-1 fold concentration',
            },
        },
        'measured_regimes': {
            name: {
                'description': regime.get('description', ''),
                'execution_mode': regime.get('execution_mode', ''),
                'tier1_total_bps': regime.get('tier1', {}).get('total_per_side_bps', 0),
                'tier2_total_bps': regime.get('tier2', {}).get('total_per_side_bps', 0),
            }
            for name, regime in measured_regimes.items()
            if name in REGIMES_TO_TEST
        },
        'combinations': all_results,
        'verdict_lines': verdict_lines,
        'summary': {
            'passing': len(passing),
            'failing': len(failing),
            'total': len(all_results),
            'passing_combos': [
                f'{r["config"]}/{r["regime"]}/${r["size"]}' for r in passing
            ],
        },
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / 'part2_measured_cost_rerun_001.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md_text = build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks)
    md_path = out_dir / 'part2_measured_cost_rerun_001.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{sep}')
    print('  MEASURED COST RERUN COMPLETE')
    print(sep)

    for r in all_results:
        m = r['baseline']
        g = r.get('gates_passed', '?')
        gt = r.get('gates_total', '?')
        ap = r.get('all_gates_pass', False)
        pre = r.get('pre_fill', {}).get('trades', '?')
        post = m['trades']
        status = 'ALL PASS' if ap else f'FAIL ({", ".join(r.get("failed_gates", []))})'
        print(f'  {r["config"]:4s} {r["regime"]:28s} ${r["size"]:>5}  '
              f'{pre}->{post}tr  PF={m["pf"]:.3f}  '
              f'Exp/wk=${m["exp_per_week"]:.2f}  DD={m["dd"]:.1f}%  '
              f'Gates={g}/{gt} {status}')

    print(f'\n  Passing: {len(passing)}/{len(all_results)}')
    print(f'  Runtime: {elapsed:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
