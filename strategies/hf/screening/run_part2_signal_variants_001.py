#!/usr/bin/env python3
"""
C8-D: Signal Variant Exploration on 295 coins (P1-7)
=====================================================
Tests 10 variations of H20 VWAP_DEVIATION v5 signal parameters:

  Category 1 -- Asymmetric TP/SL ratios:
    tp10/sl3, tp10/sl4, tp12/sl5, tp6/sl3

  Category 2 -- Shorter time limits:
    tl6, tl8 (vs baseline tl=10)

  Category 3 -- Combined sl7 + different tp:
    sl7/tp6, sl7/tp10, sl7/tp12

Gate evaluation per variant (STRICT):
  G1: trades/week >= 10
  G2: max gap <= 2.5 days
  G3: exp/week > $0
  G4: exp/week > $0 (stress 2x)
  G5: max DD <= 20%
  G6: WF >= 4/5
  G8: fold_conc < 35%

Output:
  reports/hf/part2_signal_variants_001.json
  reports/hf/part2_signal_variants_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_signal_variants_001.py
    python strategies/hf/screening/run_part2_signal_variants_001.py --dry-run
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
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee, stress_multiplier
from strategies.hf.screening.run_h20_robustness import (
    load_candle_cache, load_universe_tiering, build_tier_coins,
    compute_metrics, estimate_total_bars, BARS_PER_WEEK,
)

# ============================================================
# Constants
# ============================================================

BARS_PER_DAY = 24

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# ============================================================
# Variant Matrix (10 variants including baseline)
# ============================================================

VARIANTS = [
    {'label': 'baseline_v5',  'params': {'dev_thresh': 2.0, 'tp_pct': 8,  'sl_pct': 5, 'time_limit': 10}},
    # Category 1: Asymmetric TP/SL ratios
    {'label': 'tp10_sl3',     'params': {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 3, 'time_limit': 10}},
    {'label': 'tp10_sl4',     'params': {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 4, 'time_limit': 10}},
    {'label': 'tp12_sl5',     'params': {'dev_thresh': 2.0, 'tp_pct': 12, 'sl_pct': 5, 'time_limit': 10}},
    {'label': 'tp6_sl3',      'params': {'dev_thresh': 2.0, 'tp_pct': 6,  'sl_pct': 3, 'time_limit': 10}},
    # Category 2: Shorter time limits
    {'label': 'tl6',          'params': {'dev_thresh': 2.0, 'tp_pct': 8,  'sl_pct': 5, 'time_limit': 6}},
    {'label': 'tl8',          'params': {'dev_thresh': 2.0, 'tp_pct': 8,  'sl_pct': 5, 'time_limit': 8}},
    # Category 3: sl7 + different tp
    {'label': 'sl7_tp6',      'params': {'dev_thresh': 2.0, 'tp_pct': 6,  'sl_pct': 7, 'time_limit': 10}},
    {'label': 'sl7_tp10',     'params': {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 7, 'time_limit': 10}},
    {'label': 'sl7_tp12',     'params': {'dev_thresh': 2.0, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 10}},
]


# ============================================================
# Max gap computation (MUST use exit_bar)
# ============================================================

def compute_max_gap(trades, total_bars):
    """Compute max gap between consecutive trades, using exit_bar for gap start."""
    if len(trades) < 2:
        return total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    mg = st[0].get('entry_bar', 50) - 50  # gap from start to first entry
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i - 1].get('exit_bar', 0)
        if g > mg:
            mg = g
    eg = total_bars - st[-1].get('exit_bar', 0)  # gap from last exit to end
    if eg > mg:
        mg = eg
    return mg / BARS_PER_DAY


# ============================================================
# Fold concentration (top-1 fold share of total positive P&L)
# ============================================================

def compute_fold_concentration(fold_trades):
    """Compute top-1 fold concentration (share of total positive P&L)."""
    fold_pnls = []
    for fold_idx in sorted(fold_trades.keys()):
        pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
        fold_pnls.append(pnl)

    total_positive = sum(max(0, p) for p in fold_pnls)
    if total_positive <= 0:
        return 1.0

    max_fold_pnl = max(fold_pnls)
    if max_fold_pnl <= 0:
        return 0.0

    return max_fold_pnl / total_positive


# ============================================================
# Per-tier combined backtest runner
# ============================================================

def run_combined(data, tier_coins, tier_indicators, market_context,
                 tier1_fee, tier2_fee, params,
                 cooldown_bars=4, cooldown_after_stop=8):
    """Run H20 across both tiers with separate fees, return combined trade list."""
    signal_params = {k: v for k, v in params.items() if k == 'label' or True}
    signal_params = {k: v for k, v in params.items()}
    enriched = {**signal_params, '__market__': market_context}

    all_trades = []
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data, coins=coins,
            signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=indicators, fee=fee,
            max_pos=1,
            cooldown_bars=cooldown_bars,
            cooldown_after_stop=cooldown_after_stop,
        )

        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    return all_trades


def run_walk_forward_combined(data, tier_coins, tier_indicators, market_context,
                              tier1_fee, tier2_fee, params,
                              cooldown_bars=4, cooldown_after_stop=8,
                              n_folds=5):
    """Walk-forward across both tiers; returns {fold_idx: [trades]}."""
    enriched = {**params, '__market__': market_context}

    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    tier_fold_trades = {}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        fold_results = walk_forward(
            data=data, coins=coins,
            signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=indicators,
            n_folds=n_folds, fee=fee, max_pos=1,
            cooldown_bars=cooldown_bars,
            cooldown_after_stop=cooldown_after_stop,
        )

        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)

    return tier_fold_trades


# ============================================================
# Gate evaluation (STRICT)
# ============================================================

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days, top1_fold_conc):
    """Evaluate strict gates. Returns dict of gate results + all_pass bool."""
    gates = {}
    gates['G1'] = {
        'metric': 'trades/week',
        'value': round(metrics['trades_per_week'], 2),
        'threshold': '>= 10',
        'pass': metrics['trades_per_week'] >= 10,
    }
    gates['G2'] = {
        'metric': 'max_gap_days',
        'value': round(max_gap_days, 2),
        'threshold': '<= 2.5',
        'pass': max_gap_days <= 2.5,
    }
    gates['G3'] = {
        'metric': 'exp/week',
        'value': round(metrics['exp_per_week'], 4),
        'threshold': '> $0',
        'pass': metrics['exp_per_week'] > 0,
    }
    gates['G4'] = {
        'metric': 'exp/week (stress 2x)',
        'value': round(stress_metrics['exp_per_week'], 4),
        'threshold': '> $0',
        'pass': stress_metrics['exp_per_week'] > 0,
    }
    gates['G5'] = {
        'metric': 'max DD%',
        'value': round(metrics['dd'], 2),
        'threshold': '<= 20%',
        'pass': metrics['dd'] <= 20,
    }
    gates['G6'] = {
        'metric': 'WF folds positive',
        'value': wf_folds_positive,
        'threshold': '>= 4/5',
        'pass': wf_folds_positive >= 4,
    }
    gates['G8'] = {
        'metric': 'fold_conc (top1)',
        'value': round(top1_fold_conc, 4),
        'threshold': '< 0.35',
        'pass': top1_fold_conc < 0.35,
    }

    all_pass = all(g['pass'] for g in gates.values())
    return gates, all_pass


# ============================================================
# Full evaluation pipeline for a single variant
# ============================================================

def evaluate_variant(label, data, tier_coins, tier_indicators, market_context,
                     tier1_fee, tier2_fee, stress_t1_fee, stress_t2_fee,
                     total_bars, params):
    """Run baseline + stress + WF and evaluate all gates. Returns result dict."""
    t0 = time.time()

    # 1. Baseline backtest
    trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, params,
    )
    metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)
    max_gap = compute_max_gap(trades, total_bars)

    # 2. Stress 2x backtest
    stress_trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        stress_t1_fee, stress_t2_fee, params,
    )
    stress_metrics = compute_metrics(stress_trades, initial_capital=2000.0, total_bars=total_bars)

    # 3. Walk-forward 5-fold
    fold_trades = run_walk_forward_combined(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, params,
        n_folds=5,
    )

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

    fold_conc = compute_fold_concentration(fold_trades)

    # 4. Gate evaluation
    gates, all_pass = evaluate_gates(
        metrics, stress_metrics, folds_positive, max_gap, fold_conc,
    )

    elapsed = time.time() - t0

    # Tier split stats
    t1_trades = sum(1 for t in trades if t.get('_tier') == 'tier1')
    t2_trades = sum(1 for t in trades if t.get('_tier') == 'tier2')
    gates_passed = sum(1 for g in gates.values() if g['pass'])
    gates_total = len(gates)

    result = {
        'label': label,
        'params': params,
        'baseline_metrics': metrics,
        'stress_metrics': {
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
            'trades': stress_metrics['trades'],
            'wr': stress_metrics['wr'],
            'dd': stress_metrics['dd'],
            'pnl': stress_metrics['pnl'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': round(fold_conc, 4),
        'max_gap_days': round(max_gap, 2),
        'gates': gates,
        'gates_passed': gates_passed,
        'gates_total': gates_total,
        'all_gates_pass': all_pass,
        'tier_split': {'tier1': t1_trades, 'tier2': t2_trades},
        'runtime_s': round(elapsed, 1),
    }

    # Print summary line
    pass_str = 'ALL PASS' if all_pass else '%d/%d' % (gates_passed, gates_total)
    print('  %-16s tp=%2d sl=%2d tl=%2d | tr=%3d PF=%.3f exp/w=$%.2f DD=%.1f%% WF=%d/5 gap=%.1f fc=%.2f [%s] (%.1fs)' % (
        label,
        params.get('tp_pct', 0), params.get('sl_pct', 0), params.get('time_limit', 0),
        metrics['trades'], metrics['pf'], metrics['exp_per_week'],
        metrics['dd'], folds_positive, max_gap, fold_conc, pass_str, elapsed))

    return result


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='C8-D: Signal Variant Exploration on 295 coins',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data, print variant grid, skip backtests')
    args = parser.parse_args()

    print('=' * 80)
    print('  C8-D: Signal Variant Exploration (P1-7)')
    print('  Universe: 295-coin (excl 21 net-negative)')
    print('  Signal: H20 VWAP_DEVIATION v5 -- 10 parameter variants')
    print('  Cost: MEXC Market (costs_mexc_v2)')
    print('=' * 80)
    print('Started: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    t_global = time.time()

    # --- Costs ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_regime = stress_multiplier('mexc_market', 2.0)
    stress_t1_fee = stress_regime['tier1']['total_per_side_bps'] / 10000.0
    stress_t2_fee = stress_regime['tier2']['total_per_side_bps'] / 10000.0
    print('[Costs] T1=%.1fbps T2=%.1fbps  Stress: T1=%.1fbps T2=%.1fbps' % (
        tier1_fee * 10000, tier2_fee * 10000,
        stress_t1_fee * 10000, stress_t2_fee * 10000))

    # --- Commit ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Data ---
    data = load_candle_cache('1h')
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # Apply 21-coin exclusion
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    n_excl = (len(tier_coins_full['tier1']) + len(tier_coins_full['tier2'])) - n_total
    print('[Universe] T1(%d)+T2(%d)=%d (excl %d)' % (n_t1, n_t2, n_total, n_excl))

    # --- Dry run ---
    if args.dry_run:
        print('\n--- DRY RUN ---')
        print('Variant grid: %d variants' % len(VARIANTS))
        for v in VARIANTS:
            p = v['params']
            print('  %-16s tp=%2d sl=%2d tl=%2d  R:R=%.1f:1' % (
                v['label'], p['tp_pct'], p['sl_pct'], p['time_limit'],
                p['tp_pct'] / p['sl_pct'] if p['sl_pct'] > 0 else 0))
        print('Each variant: 3 passes (baseline + stress + WF5)')
        print('Total: %d variants x 3 passes = %d backtests' % (
            len(VARIANTS), len(VARIANTS) * 3))
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print('  %s: %d coins in %.1fs' % (tier_name, len(coins), time.time() - t_ind))

    print('[Indicators] Extending with VWAP/ATR_ratio fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print('  %s: VWAP %.0f%% (%d/%d)' % (
                tier_name, cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicator dicts
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('[Data] total_bars=%d total_weeks=%.1f' % (total_bars, total_weeks))

    # ================================================================
    # Run all 10 variants
    # ================================================================
    print('\n' + '=' * 80)
    print('  SIGNAL VARIANT GRID (%d variants)' % len(VARIANTS))
    print('=' * 80)

    results = []
    for variant in VARIANTS:
        result = evaluate_variant(
            label=variant['label'],
            data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
            total_bars=total_bars,
            params=variant['params'],
        )
        results.append(result)

    elapsed_total = time.time() - t_global

    # ================================================================
    # Summary Analysis
    # ================================================================
    print('\n' + '=' * 80)
    print('  SUMMARY: All Signal Variants')
    print('=' * 80)

    # Header
    print('  %-16s %3s %3s %3s %5s %6s %7s %7s %5s %3s %5s %5s  %s' % (
        'Label', 'TP', 'SL', 'TL', 'R:R', 'PF', 'P&L', 'Exp/Wk', 'DD%', 'WF', 'FC', 'Gap', 'Gates'))
    print('  ' + '-' * 110)
    for r in results:
        p = r['params']
        rr = p['tp_pct'] / p['sl_pct'] if p['sl_pct'] > 0 else 0
        pass_str = 'ALL' if r['all_gates_pass'] else '%d/%d' % (r['gates_passed'], r['gates_total'])
        m = r['baseline_metrics']
        print('  %-16s %3d %3d %3d %5.1f %6.3f %7.0f %7.2f %5.1f %d/5 %5.2f %5.1f  %s' % (
            r['label'], p['tp_pct'], p['sl_pct'], p['time_limit'], rr,
            m['pf'], m['pnl'], m['exp_per_week'],
            m['dd'], r['wf_folds_positive'], r['fold_concentration'],
            r['max_gap_days'], pass_str))

    # Categorize results
    n_all_pass = sum(1 for r in results if r['all_gates_pass'])
    print('\n  Variants passing ALL gates: %d/%d' % (n_all_pass, len(results)))

    # Find best variant
    if n_all_pass > 0:
        passing = [r for r in results if r['all_gates_pass']]
        best = sorted(passing, key=lambda r: (-r['baseline_metrics']['exp_per_week'], r['baseline_metrics']['dd']))[0]
        print('  Best (all gates): %s -- exp/wk=$%.2f, DD=%.1f%%' % (
            best['label'], best['baseline_metrics']['exp_per_week'], best['baseline_metrics']['dd']))
    else:
        best = sorted(results, key=lambda r: (r['gates_passed'], r['baseline_metrics']['exp_per_week']),
                       reverse=True)[0]
        print('  Best (partial): %s -- %d/%d gates, exp/wk=$%.2f' % (
            best['label'], best['gates_passed'], best['gates_total'],
            best['baseline_metrics']['exp_per_week']))

    # Compare to baseline
    baseline_r = results[0]
    print('\n  --- Comparison vs Baseline (v5: tp=8, sl=5, tl=10) ---')
    for r in results[1:]:
        m = r['baseline_metrics']
        bm = baseline_r['baseline_metrics']
        delta_exp = m['exp_per_week'] - bm['exp_per_week']
        delta_dd = m['dd'] - bm['dd']
        delta_trades = m['trades'] - bm['trades']
        improved = delta_exp > 0 and delta_dd <= 0
        marker = ' <-- BETTER' if improved else ''
        gpass = 'ALL' if r['all_gates_pass'] else '%d/%d' % (r['gates_passed'], r['gates_total'])
        print('  %-16s exp/wk %+.2f  DD %+.1f%%  trades %+d  gates=%s%s' % (
            r['label'], delta_exp, delta_dd, delta_trades, gpass, marker))

    print('\n  Total runtime: %.1fs' % elapsed_total)

    # ================================================================
    # JSON Report
    # ================================================================
    report = {
        'run_header': {
            'task': 'part2_signal_variants',
            'agent': 'C8-D',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees': {
                'baseline': {
                    'tier1_bps': round(tier1_fee * 10000, 1),
                    'tier2_bps': round(tier2_fee * 10000, 1),
                },
                'stress_2x': {
                    'tier1_bps': round(stress_t1_fee * 10000, 1),
                    'tier2_bps': round(stress_t2_fee * 10000, 1),
                },
            },
            'universe': 'T1(%d)+T2(%d)=%d (excl %d)' % (n_t1, n_t2, n_total, n_excl),
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'gate_thresholds': {
            'G1': 'trades/week >= 10',
            'G2': 'max_gap <= 2.5 days',
            'G3': 'exp/week > $0',
            'G4': 'exp/week > $0 (stress 2x)',
            'G5': 'max DD <= 20%',
            'G6': 'WF >= 4/5',
            'G8': 'fold_conc < 0.35',
        },
        'variants': [
            {
                'label': v['label'],
                'params': v['params'],
                'rr_ratio': round(v['params']['tp_pct'] / v['params']['sl_pct'], 2) if v['params']['sl_pct'] > 0 else 0,
                'category': (
                    'baseline' if v['label'] == 'baseline_v5' else
                    'asymmetric_rr' if v['label'] in ('tp10_sl3', 'tp10_sl4', 'tp12_sl5', 'tp6_sl3') else
                    'time_limit' if v['label'] in ('tl6', 'tl8') else
                    'sl7_combos'
                ),
            }
            for v in VARIANTS
        ],
        'results': results,
        'summary': {
            'n_variants': len(results),
            'n_all_pass': n_all_pass,
            'best_overall': best['label'],
            'best_gates_passed': best['gates_passed'],
            'best_exp_per_week': best['baseline_metrics']['exp_per_week'],
            'baseline_exp_per_week': baseline_r['baseline_metrics']['exp_per_week'],
            'baseline_gates_passed': baseline_r['gates_passed'],
            'baseline_all_pass': baseline_r['all_gates_pass'],
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_signal_variants_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ================================================================
    # Markdown Report
    # ================================================================
    md = []
    md.append('# C8-D: Signal Variant Exploration (P1-7)')
    md.append('')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Agent**: C8-D')
    md.append('**Commit**: %s' % commit)
    md.append('**Universe**: T1(%d) + T2(%d) = %d coins (excl %d net-negative)' % (
        n_t1, n_t2, n_total, n_excl))
    md.append('**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0)')
    md.append('**Cost**: MEXC Market (T1=%.1fbps, T2=%.1fbps)' % (
        tier1_fee * 10000, tier2_fee * 10000))
    md.append('**Stress**: 2x (T1=%.1fbps, T2=%.1fbps)' % (
        stress_t1_fee * 10000, stress_t2_fee * 10000))
    md.append('**Runtime**: %.1fs' % elapsed_total)
    md.append('')

    # Gate thresholds
    md.append('## Gate Thresholds (STRICT)')
    md.append('')
    md.append('| Gate | Metric | Threshold |')
    md.append('|------|--------|-----------|')
    md.append('| G1 | trades/week | >= 10 |')
    md.append('| G2 | max gap | <= 2.5 days |')
    md.append('| G3 | exp/week | > $0 |')
    md.append('| G4 | exp/week (stress 2x) | > $0 |')
    md.append('| G5 | max DD | <= 20% |')
    md.append('| G6 | WF positive folds | >= 4/5 |')
    md.append('| G8 | fold concentration | < 35% |')
    md.append('')

    # R:R ratio analysis
    md.append('## Variant Matrix')
    md.append('')
    md.append('| Label | TP% | SL% | TL | R:R | Category |')
    md.append('|-------|-----|-----|----|-----|----------|')
    for v in VARIANTS:
        p = v['params']
        rr = p['tp_pct'] / p['sl_pct'] if p['sl_pct'] > 0 else 0
        cat = ('baseline' if v['label'] == 'baseline_v5' else
               'asymmetric R:R' if v['label'] in ('tp10_sl3', 'tp10_sl4', 'tp12_sl5', 'tp6_sl3') else
               'time limit' if v['label'] in ('tl6', 'tl8') else
               'sl7 combos')
        md.append('| %s | %d | %d | %d | %.1f:1 | %s |' % (
            v['label'], p['tp_pct'], p['sl_pct'], p['time_limit'], rr, cat))
    md.append('')

    # Full results table
    md.append('## Results: All Variants')
    md.append('')
    md.append('| Label | TP | SL | TL | R:R | Trades | PF | P&L | Exp/Wk | DD%% | WF | FC | Gap | Gates |')
    md.append('|-------|----|----|----|----|--------|----|-----|--------|------|----|----|-----|-------|')
    for r in results:
        p = r['params']
        rr = p['tp_pct'] / p['sl_pct'] if p['sl_pct'] > 0 else 0
        m = r['baseline_metrics']
        pass_str = '**ALL**' if r['all_gates_pass'] else '%d/%d' % (r['gates_passed'], r['gates_total'])
        md.append('| %s | %d | %d | %d | %.1f | %d | %.3f | $%.0f | $%.2f | %.1f | %d/5 | %.2f | %.1f | %s |' % (
            r['label'], p['tp_pct'], p['sl_pct'], p['time_limit'], rr,
            m['trades'], m['pf'], m['pnl'], m['exp_per_week'],
            m['dd'], r['wf_folds_positive'], r['fold_concentration'],
            r['max_gap_days'], pass_str))
    md.append('')

    # Gate detail per variant
    md.append('## Gate Detail Per Variant')
    md.append('')
    md.append('| Label | G1 | G2 | G3 | G4 | G5 | G6 | G8 | Total |')
    md.append('|-------|----|----|----|----|----|----|-----|-------|')
    for r in results:
        g = r['gates']
        def _pf(gk):
            return 'P' if g[gk]['pass'] else '**F**'
        total_str = '**ALL**' if r['all_gates_pass'] else '%d/7' % r['gates_passed']
        md.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            r['label'],
            _pf('G1'), _pf('G2'), _pf('G3'), _pf('G4'),
            _pf('G5'), _pf('G6'), _pf('G8'), total_str))
    md.append('')

    # Stress test comparison
    md.append('## Stress Test (2x fees)')
    md.append('')
    md.append('| Label | Baseline PF | Stress PF | Baseline Exp/Wk | Stress Exp/Wk | Survives? |')
    md.append('|-------|-------------|-----------|-----------------|---------------|-----------|')
    for r in results:
        survives = r['stress_metrics']['exp_per_week'] > 0
        md.append('| %s | %.3f | %.3f | $%.2f | $%.2f | %s |' % (
            r['label'], r['baseline_metrics']['pf'], r['stress_metrics']['pf'],
            r['baseline_metrics']['exp_per_week'], r['stress_metrics']['exp_per_week'],
            'YES' if survives else 'NO'))
    md.append('')

    # Walk-forward fold detail
    md.append('## Walk-Forward Fold Detail')
    md.append('')
    for r in results:
        md.append('### %s (WF=%d/5)' % (r['label'], r['wf_folds_positive']))
        md.append('')
        md.append('| Fold | Trades | P&L | Positive? |')
        md.append('|------|--------|-----|-----------|')
        for fd in r['wf_fold_details']:
            md.append('| %d | %d | $%.2f | %s |' % (
                fd['fold'], fd['trades'], fd['pnl'],
                'YES' if fd['positive'] else 'NO'))
        md.append('')

    # Delta vs baseline
    md.append('## Delta vs Baseline')
    md.append('')
    md.append('| Label | dExp/Wk | dDD%% | dTrades | dPF | Better? |')
    md.append('|-------|---------|-------|---------|-----|---------|')
    bm = baseline_r['baseline_metrics']
    for r in results[1:]:
        m = r['baseline_metrics']
        d_exp = m['exp_per_week'] - bm['exp_per_week']
        d_dd = m['dd'] - bm['dd']
        d_tr = m['trades'] - bm['trades']
        d_pf = m['pf'] - bm['pf']
        better = d_exp > 0 and d_dd <= 0
        md.append('| %s | %+.2f | %+.1f | %+d | %+.3f | %s |' % (
            r['label'], d_exp, d_dd, d_tr, d_pf,
            'YES' if better else 'no'))
    md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    if n_all_pass > 0:
        passing_labels = [r['label'] for r in results if r['all_gates_pass']]
        md.append('**%d variant(s) pass ALL 7 strict gates**: %s' % (
            n_all_pass, ', '.join(passing_labels)))
        md.append('')
        md.append('Best overall: **%s** (exp/wk=$%.2f, DD=%.1f%%)' % (
            best['label'], best['baseline_metrics']['exp_per_week'],
            best['baseline_metrics']['dd']))
        # Check if any beat baseline
        baseline_exp = baseline_r['baseline_metrics']['exp_per_week']
        beats_baseline = [r for r in results if r['all_gates_pass'] and
                          r['baseline_metrics']['exp_per_week'] > baseline_exp and
                          r['label'] != 'baseline_v5']
        if beats_baseline:
            md.append('')
            md.append('**Variants that BEAT baseline while passing all gates**:')
            for r in beats_baseline:
                md.append('- **%s**: exp/wk=$%.2f (+$%.2f), DD=%.1f%%' % (
                    r['label'], r['baseline_metrics']['exp_per_week'],
                    r['baseline_metrics']['exp_per_week'] - baseline_exp,
                    r['baseline_metrics']['dd']))
        else:
            md.append('')
            md.append('No variant beats the baseline exp/wk while passing all gates.')
    else:
        md.append('**No variant passes ALL 7 strict gates.**')
        md.append('')
        md.append('Closest: **%s** (%d/%d gates)' % (
            best['label'], best['gates_passed'], best['gates_total']))
    md.append('')

    # Key findings
    md.append('### Key Findings')
    md.append('')

    # Analyze R:R effect
    rr_results = [(r['params']['tp_pct'] / r['params']['sl_pct'] if r['params']['sl_pct'] > 0 else 0,
                    r['baseline_metrics']['exp_per_week'], r['baseline_metrics']['dd'], r['label'])
                   for r in results]
    rr_sorted = sorted(rr_results, key=lambda x: x[0])
    md.append('**R:R Ratio Analysis** (sorted by R:R):')
    for rr, exp, dd, lbl in rr_sorted:
        md.append('- R:R=%.1f (%s): exp/wk=$%.2f, DD=%.1f%%' % (rr, lbl, exp, dd))
    md.append('')

    # Time limit effect
    tl_results = [r for r in results if r['label'] in ('baseline_v5', 'tl6', 'tl8')]
    if tl_results:
        md.append('**Time Limit Effect**:')
        for r in tl_results:
            md.append('- tl=%d (%s): trades=%d, exp/wk=$%.2f, DD=%.1f%%' % (
                r['params']['time_limit'], r['label'],
                r['baseline_metrics']['trades'], r['baseline_metrics']['exp_per_week'],
                r['baseline_metrics']['dd']))
    md.append('')

    # sl7 family
    sl7_results = [r for r in results if r['label'].startswith('sl7_')]
    if sl7_results:
        md.append('**SL=7%% Family**:')
        for r in sl7_results:
            g_pass = 'ALL' if r['all_gates_pass'] else '%d/7' % r['gates_passed']
            md.append('- %s: trades=%d, exp/wk=$%.2f, DD=%.1f%%, gates=%s' % (
                r['label'], r['baseline_metrics']['trades'],
                r['baseline_metrics']['exp_per_week'],
                r['baseline_metrics']['dd'], g_pass))
    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_signal_variants_001.py at %s*' % (
        datetime.now().strftime('%Y-%m-%d %H:%M')))

    md_path = ROOT / 'reports' / 'hf' / 'part2_signal_variants_001.md'
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    # Final summary
    print('\n' + '=' * 80)
    print('  SIGNAL VARIANT EXPLORATION COMPLETE')
    print('  Variants tested: %d' % len(results))
    print('  ALL gates pass: %d/%d' % (n_all_pass, len(results)))
    print('  Best overall: %s' % best['label'])
    print('  Runtime: %.1fs' % elapsed_total)
    print('=' * 80)


if __name__ == '__main__':
    main()
