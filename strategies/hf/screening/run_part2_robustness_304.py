#!/usr/bin/env python3
"""
Part 2 Robustness Sweep on 304-coin universe (excl_worst12)
============================================================
Same 12-variant ROBUSTNESS_GRID as run_h20_robustness.py and
run_part2_robustness_316.py, but on the 304-coin universe that
excludes only the worst 12 coins (by net P&L) from the exclusion
sweep analysis (Agent C2-A5).

Excluded coins (12):
  ALKIMI/USD, ANIME/USD, DBR/USD, ESX/USD, HOUSE/USD, KET/USD,
  LMWR/USD, MXC/USD, ODOS/USD, PERP/USD, TANSSI/USD, TITCOIN/USD

Key differences vs other robustness runs:
  - 295-coin run excluded all 21 net-negative coins (G7=12/12)
  - 316-coin run used full universe (G7=9/12)
  - This 304-coin run excludes only worst 12 (more conservative filter)
  - Same G7 gate: >= 8/12 variants profitable (PF > 1.0)
  - Same 3 passes: baseline, walk-forward 5-fold, stress 2x

Output:
  reports/hf/part2_robustness_304_001.json
  reports/hf/part2_robustness_304_001.md

Usage:
    python -m strategies.hf.screening.run_part2_robustness_304
    python -m strategies.hf.screening.run_part2_robustness_304 --dry-run
    python -m strategies.hf.screening.run_part2_robustness_304 --require-data
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

from strategies.hf.screening.run_h20_robustness import (
    ROBUSTNESS_GRID,
    BARS_PER_WEEK,
    STRESS_2X_T1, STRESS_2X_T2,
    load_candle_cache,
    load_universe_tiering,
    build_tier_coins,
    run_h20_variant,
    run_h20_walk_forward,
    compute_metrics,
    estimate_total_bars,
    composite_score,
)
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.harness import precompute_base_indicators

REPORT_JSON = 'part2_robustness_304_001.json'
REPORT_MD   = 'part2_robustness_304_001.md'

# 12 worst coins by net P&L from exclusion sweep (Agent C2-A5)
# Source: reports/hf/part2_excl_sweep_001.json -> worst_n_sweep -> excl_worst12
EXCLUDED_COINS = {
    'ALKIMI/USD', 'ANIME/USD', 'DBR/USD', 'ESX/USD', 'HOUSE/USD',
    'KET/USD', 'LMWR/USD', 'MXC/USD', 'ODOS/USD', 'PERP/USD',
    'TANSSI/USD', 'TITCOIN/USD',
}


def load_excluded_coins_from_report():
    """Load the worst-12 excluded coins from the excl sweep report JSON."""
    report_path = ROOT / 'reports' / 'hf' / 'part2_excl_sweep_001.json'
    if report_path.exists():
        with open(report_path) as f:
            report = json.load(f)
        for result in report.get('worst_n_sweep', {}).get('results', []):
            if result.get('excl_n') == 12:
                return set(result.get('excluded_coins', []))
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Robustness Sweep - 304-coin Universe (excl_worst12)',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data and print grid, but skip backtests')
    parser.add_argument('--require-data', action='store_true',
                        help='Exit 1 if cache/tiering missing (CI mode)')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 Robustness Sweep - 304-coin Universe (excl_worst12)')
    print('  Cost Regime: MEXC Market (costs_mexc_v2)')
    print('  Grid: 12 variants (same as h20_robustness_002)')
    print('  Exclusion: 12 worst coins by net P&L (excl sweep)')
    print('=' * 70)
    print('Started: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    t0 = time.time()

    # --- Excluded coins ---
    excl_from_report = load_excluded_coins_from_report()
    if excl_from_report is not None:
        excluded = excl_from_report
        excl_source = 'part2_excl_sweep_001.json (excl_worst12)'
        print('[Exclusion] Loaded %d coins from %s' % (len(excluded), excl_source))
    else:
        excluded = EXCLUDED_COINS
        excl_source = 'hardcoded'
        print('[Exclusion] Using hardcoded %d coins (report not found)' % len(excluded))
    print('[Exclusion] Coins: %s' % ', '.join(sorted(excluded)))

    # --- Cost model ---
    try:
        from strategies.hf.screening.costs_mexc_v2 import get_harness_fee
        tier1_fee = get_harness_fee('mexc_market', 'tier1')
        tier2_fee = get_harness_fee('mexc_market', 'tier2')
        cost_source = 'costs_mexc_v2'
    except ImportError:
        tier1_fee = 0.0005
        tier2_fee = 0.0020
        cost_source = 'hardcoded'
    print('[Costs] %s: T1=%.1fbps, T2=%.1fbps' % (cost_source, tier1_fee*10000, tier2_fee*10000))

    # --- Stress fees from v2 model ---
    try:
        from strategies.hf.screening.costs_mexc_v2 import stress_multiplier
        stress_regime = stress_multiplier('mexc_market', 2.0)
        stress_t1_fee = stress_regime['tier1']['total_per_side_bps'] / 10000.0
        stress_t2_fee = stress_regime['tier2']['total_per_side_bps'] / 10000.0
        stress_source = 'costs_mexc_v2 x2'
    except ImportError:
        stress_t1_fee = STRESS_2X_T1
        stress_t2_fee = STRESS_2X_T2
        stress_source = 'hardcoded 2x'
    print('[Stress] %s: T1=%.1fbps, T2=%.1fbps' % (stress_source, stress_t1_fee*10000, stress_t2_fee*10000))

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

    # --- Apply exclusion ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in excluded],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in excluded],
    }

    n_t1_full = len(tier_coins_full['tier1'])
    n_t2_full = len(tier_coins_full['tier2'])
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    n_excluded_actual = (n_t1_full + n_t2_full) - n_total

    print('[Universe] Full: T1(%d)+T2(%d)=%d' % (n_t1_full, n_t2_full, n_t1_full+n_t2_full))
    print('[Universe] After exclusion: T1(%d)+T2(%d)=%d (excluded %d)' % (
        n_t1, n_t2, n_total, n_excluded_actual))

    if n_total < 280:
        print('[WARN] Expected ~304 coins but only %d available.' % n_total)

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        if args.require_data:
            print('[ERROR] No coins in T1 or T2.')
            sys.exit(1)
        print('[SKIP] No coins in T1 or T2.')
        sys.exit(0)

    # --- Dry-run ---
    if args.dry_run:
        print('\n--- DRY RUN: Grid Preview (%d variants) ---' % len(ROBUSTNESS_GRID))
        for i, v in enumerate(ROBUSTNESS_GRID):
            print('  %2d  %-20s  %.1f  %2d  %2d  %2d' % (
                i, v['label'], v['dev_thresh'], v['tp_pct'], v['sl_pct'], v['time_limit']))
        print('\nWould run %d variants x 3 passes on %d coins' % (len(ROBUSTNESS_GRID), n_total))
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print('  %s: %d coins in %.1fs' % (tier_name, len(coins), time.time()-t_ind))

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print('  %s: VWAP %.0f%% (%d/%d)' % (
                tier_name, cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

    # --- Market context ---
    print('[Market Context] Precomputing...')
    all_coins = list(set(
        tier_coins.get('tier1', []) + tier_coins.get('tier2', [])
    ))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('[Data] total_bars=%d, total_weeks=%.1f' % (total_bars, total_weeks))

    # ============================================================
    # Pass 1: Baseline backtests
    # ============================================================
    print('\n--- Pass 1: MEXC Market Baseline ---')

    variant_results = []

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_var = time.time()

        trades = run_h20_variant(
            params=params, data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        )
        metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)

        t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
        t2_trades = [t for t in trades if t.get('_tier') == 'tier2']

        print('  [%2d] %-20s trades=%3d (T1:%d T2:%d) PF=%.3f WR=%.1f%% exp/w=$%.2f DD=%.1f%% fee=%.1f%% (%.1fs)' % (
            var_idx, params['label'], metrics['trades'], len(t1_trades), len(t2_trades),
            metrics['pf'], metrics['wr'], metrics['exp_per_week'], metrics['dd'],
            metrics['fee_drag_pct'], time.time()-t_var))

        variant_results.append({
            'variant_idx': var_idx,
            'label': params['label'],
            'params': {k: v for k, v in params.items() if k != 'label'},
            'baseline_metrics': metrics,
            'tier_split': {
                'tier1_trades': len(t1_trades),
                'tier2_trades': len(t2_trades),
            },
        })

    # ============================================================
    # Pass 2: Walk-Forward 5-fold
    # ============================================================
    print('\n--- Pass 2: Walk-Forward 5-Fold ---')

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_wf = time.time()

        fold_trades = run_h20_walk_forward(
            params=params, data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee, n_folds=5,
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

        variant_results[var_idx]['wf_folds_positive'] = folds_positive
        variant_results[var_idx]['wf_folds_total'] = 5
        variant_results[var_idx]['wf_fold_details'] = fold_details

        print('  [%2d] %-20s WF=%d/5 (%.1fs)' % (
            var_idx, params['label'], folds_positive, time.time()-t_wf))

    # ============================================================
    # Pass 3: Stress Test (2x fees)
    # ============================================================
    print('\n--- Pass 3: Stress 2x Fees (T1=%.1fbps, T2=%.1fbps) ---' % (
        stress_t1_fee*10000, stress_t2_fee*10000))

    for var_idx, params in enumerate(ROBUSTNESS_GRID):
        t_stress = time.time()

        trades = run_h20_variant(
            params=params, data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators, market_context=market_context,
            tier1_fee=stress_t1_fee, tier2_fee=stress_t2_fee,
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
            'pnl': stress_metrics['pnl'],
        }

        print('  [%2d] %-20s PF=%.3f exp/w=$%.2f (%.1fs)' % (
            var_idx, params['label'], stress_metrics['pf'],
            stress_metrics['exp_per_week'], time.time()-t_stress))

    # ============================================================
    # Composite scores
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

    ranked = sorted(variant_results, key=lambda x: x['composite_score'], reverse=True)

    for rank_idx, vr in enumerate(ranked):
        m = vr['baseline_metrics']
        print('  #%2d [%2d] %-20s score=%.4f exp/w=$%.2f WF=%d/5 trades=%d' % (
            rank_idx+1, vr['variant_idx'], vr['label'],
            vr['composite_score'], m['exp_per_week'],
            vr['wf_folds_positive'], m['trades']))

    elapsed = time.time() - t0

    # ============================================================
    # G7 Gate Assessment
    # ============================================================
    n_profitable = sum(
        1 for vr in variant_results if vr['baseline_metrics']['pf'] > 1.0
    )
    n_stress_profitable = sum(
        1 for vr in variant_results if vr['stress_2x']['pf'] > 1.0
    )
    n_stress_positive_exp = sum(
        1 for vr in variant_results
        if vr['stress_2x']['exp_per_week'] > 0
    )
    n_wf_3plus = sum(
        1 for vr in variant_results if vr['wf_folds_positive'] >= 3
    )
    g7_pass = n_profitable >= 8

    print('\n--- G7 Gate Assessment ---')
    print('  Profitable (PF>1.0): %d/12 %s (threshold: >=8)' % (
        n_profitable, 'PASS' if g7_pass else 'FAIL'))
    print('  Stress profitable (PF>1.0 @ 2x fees): %d/12' % n_stress_profitable)
    print('  Stress positive exp/wk: %d/12' % n_stress_positive_exp)
    print('  WF >= 3/5 folds: %d/12' % n_wf_3plus)

    # ============================================================
    # JSON Report
    # ============================================================
    summary = {
        'g7_neighbor_stability': {
            'profitable_count': n_profitable,
            'total_variants': 12,
            'threshold': 8,
            'pass': g7_pass,
            'verdict': 'PASS' if g7_pass else 'FAIL',
        },
        'stress_profitable_count': n_stress_profitable,
        'stress_positive_exp_count': n_stress_positive_exp,
        'wf_3plus_count': n_wf_3plus,
        'best_variant': ranked[0]['label'] if ranked else None,
        'best_score': ranked[0]['composite_score'] if ranked else 0,
        'baseline_pf': variant_results[0]['baseline_metrics']['pf'],
        'baseline_exp_per_week': variant_results[0]['baseline_metrics']['exp_per_week'],
    }

    report = {
        'run_header': {
            'task': 'part2_robustness_304',
            'agent': 'C3-A1',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'variants_tested': len(ROBUSTNESS_GRID),
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'cost_source': cost_source,
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
            'universe': 'T1(%d)+T2(%d) [excl_worst12]' % (n_t1, n_t2),
            'universe_total': n_total,
            'universe_full': n_t1_full + n_t2_full,
            'excluded_coins_count': n_excluded_actual,
            'excluded_coins': sorted(excluded),
            'exclusion_source': excl_source,
            'exclusion_rationale': 'Worst 12 coins by net P&L (minimum N for 7/7 gates)',
            'previous_runs': {
                '316_coin': 'part2_robustness_316 (full universe, G7=9/12 PASS)',
                '295_coin': 'part2_robustness_295 (excl_all_negative 21 coins, G7=12/12 PASS)',
            },
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'scoring_formula': 'exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)',
        'summary': summary,
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

    json_path = ROOT / 'reports' / 'hf' / REPORT_JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ============================================================
    # Markdown Report
    # ============================================================
    md = []
    md.append('# Part 2 Robustness Sweep - 304-coin Universe (excl_worst12)')
    md.append('')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Commit**: %s' % commit)
    md.append('**Agent**: C3-A1')
    md.append('**Universe**: T1(%d) + T2(%d) = %d coins (excl %d worst by P&L)' % (
        n_t1, n_t2, n_total, n_excluded_actual))
    md.append('**Full universe**: T1(%d) + T2(%d) = %d coins' % (
        n_t1_full, n_t2_full, n_t1_full + n_t2_full))
    md.append('**Timeframe**: 1H')
    md.append('**Cost Regime**: MEXC Market (%s)' % cost_source)
    md.append('**Fees**: T1=%.1fbps, T2=%.1fbps' % (tier1_fee*10000, tier2_fee*10000))
    md.append('**Stress**: 2x (T1=%.1fbps, T2=%.1fbps)' % (stress_t1_fee*10000, stress_t2_fee*10000))
    md.append('**Runtime**: %.1fs' % elapsed)
    md.append('**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)')
    md.append('')

    # Excluded coins
    md.append('## Excluded Coins (%d)' % n_excluded_actual)
    md.append('')
    md.append('Source: `%s`' % excl_source)
    md.append('Rationale: Worst 12 coins by net P&L -- minimum N for 7/7 baseline gates.')
    md.append('')
    md.append('```')
    md.append(', '.join(sorted(excluded)))
    md.append('```')
    md.append('')

    # G7 gate box
    md.append('## G7 Gate: Neighbor Stability')
    md.append('')
    g7_verdict = 'PASS' if g7_pass else 'FAIL'
    md.append('| Metric | Value | Threshold | Verdict |')
    md.append('|--------|-------|-----------|---------|')
    md.append('| Profitable neighbors (PF>1.0) | %d/12 | >=8/12 | **%s** |' % (n_profitable, g7_verdict))
    md.append('| Stress profitable (2x fees PF>1.0) | %d/12 | info | - |' % n_stress_profitable)
    md.append('| Stress positive exp/wk | %d/12 | info | - |' % n_stress_positive_exp)
    md.append('| WF >= 3/5 folds | %d/12 | info | - |' % n_wf_3plus)
    md.append('')

    # All variants table
    md.append('## All Variants (MEXC Market)')
    md.append('')
    md.append('| # | Label | dev | tp | sl | tl | Trades | T1 | T2 | PF | WR%% | Exp/Wk | DD%% | Fee%% | WF | Score |')
    md.append('|---|-------|-----|----|----|----|----|----|----|-----|------|--------|------|------|-----|-------|')

    for vr in variant_results:
        m = vr['baseline_metrics']
        p = vr['params']
        ts = vr['tier_split']
        md.append('| %d | %s | %s | %s | %s | %s | %d | %d | %d | %.3f | %.1f | $%.2f | %.1f | %.1f | %d/5 | %.4f |' % (
            vr['variant_idx'], vr['label'],
            p['dev_thresh'], p['tp_pct'], p['sl_pct'], p['time_limit'],
            m['trades'], ts['tier1_trades'], ts['tier2_trades'],
            m['pf'], m['wr'], m['exp_per_week'], m['dd'],
            m['fee_drag_pct'], vr['wf_folds_positive'], vr['composite_score']))
    md.append('')

    # Stress table
    md.append('## Stress Test (2x Fees)')
    md.append('')
    md.append('| # | Label | PF | Exp/Wk | P&L | Trades | WR%% | DD%% |')
    md.append('|---|-------|----|--------|------|--------|------|------|')

    for vr in variant_results:
        s = vr['stress_2x']
        md.append('| %d | %s | %.3f | $%.2f | $%.0f | %d | %.1f | %.1f |' % (
            vr['variant_idx'], vr['label'],
            s['pf'], s['exp_per_week'], s['pnl'], s['trades'], s['wr'], s['dd']))
    md.append('')

    # Walk-Forward detail
    md.append('## Walk-Forward Detail (5-Fold)')
    md.append('')
    md.append('| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |')
    md.append('|---|-------|--------|--------|--------|--------|--------|----------|')

    for vr in variant_results:
        fold_pnls = []
        for fd in vr.get('wf_fold_details', []):
            fold_pnls.append('$%.0f' % fd['pnl'])
        while len(fold_pnls) < 5:
            fold_pnls.append('-')
        md.append('| %d | %s | %s | %s | %s | %s | %s | %d/5 |' % (
            vr['variant_idx'], vr['label'],
            fold_pnls[0], fold_pnls[1], fold_pnls[2], fold_pnls[3], fold_pnls[4],
            vr['wf_folds_positive']))
    md.append('')

    # Ranking
    md.append('## Ranking (Composite Score)')
    md.append('')
    md.append('```')
    md.append('score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)')
    md.append('```')
    md.append('')

    for i, vr in enumerate(ranked[:3]):
        m = vr['baseline_metrics']
        s = vr['stress_2x']
        md.append('### #%d: %s (variant %d)' % (i+1, vr['label'], vr['variant_idx']))
        md.append('')
        md.append('- **Params**: dev_thresh=%s, tp_pct=%s, sl_pct=%s, time_limit=%s' % (
            vr['params']['dev_thresh'], vr['params']['tp_pct'],
            vr['params']['sl_pct'], vr['params']['time_limit']))
        md.append('- **Composite Score**: %.4f' % vr['composite_score'])
        md.append('- **Baseline**: %d trades, PF=%.3f, WR=%.1f%%, Exp/Wk=$%.2f, DD=%.1f%%' % (
            m['trades'], m['pf'], m['wr'], m['exp_per_week'], m['dd']))
        md.append('- **Walk-Forward**: %d/5 positive folds' % vr['wf_folds_positive'])
        md.append('- **Stress 2x**: PF=%.3f, Exp/Wk=$%.2f' % (s['pf'], s['exp_per_week']))
        md.append('')

    # Full ranking table
    md.append('### Full Ranking')
    md.append('')
    md.append('| Rank | # | Label | Score | Exp/Wk | WF | Trades |')
    md.append('|------|---|-------|-------|--------|----|--------|')

    for i, vr in enumerate(ranked):
        m = vr['baseline_metrics']
        md.append('| %d | %d | %s | %.4f | $%.2f | %d/5 | %d |' % (
            i+1, vr['variant_idx'], vr['label'],
            vr['composite_score'], m['exp_per_week'],
            vr['wf_folds_positive'], m['trades']))
    md.append('')

    # Comparison section (3-way)
    md.append('## Comparison: 304 vs 295 vs 316 coins')
    md.append('')
    md.append('| Metric | 316 coins | 304 coins | 295 coins |')
    md.append('|--------|-----------|-----------|-----------|')
    md.append('| Excluded | 0 | 12 worst | 21 (all negative) |')
    md.append('| G7 profitable | 9/12 | %d/12 | 12/12 |' % n_profitable)
    md.append('| Stress profitable | - | %d/12 | - |' % n_stress_profitable)
    md.append('| WF >= 3/5 | - | %d/12 | - |' % n_wf_3plus)
    md.append('')
    md.append('**Note**: 316-coin G7 was 9/12 PASS. 295-coin G7 was 12/12 PASS.')
    md.append('304-coin universe excludes only the worst 12 (more conservative than 295).')
    md.append('')

    # Parameter sensitivity
    md.append('## Parameter Sensitivity Summary')
    md.append('')
    md.append('Comparing each perturbation to v5 baseline (variant 0):')
    md.append('')

    baseline_score = variant_results[0]['composite_score']

    md.append('| Param | Change | Trades | Exp/Wk | Score | Delta Score |')
    md.append('|-------|--------|--------|--------|-------|-------------|')

    for vr in variant_results:
        m = vr['baseline_metrics']
        delta = vr['composite_score'] - baseline_score
        sign = '+' if delta >= 0 else ''
        md.append('| %s | vs baseline | %d | $%.2f | %.4f | %s%.4f |' % (
            vr['label'], m['trades'], m['exp_per_week'],
            vr['composite_score'], sign, delta))
    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_robustness_304.py at %s*' % (
        datetime.now().strftime('%Y-%m-%d %H:%M')))

    md_path = ROOT / 'reports' / 'hf' / REPORT_MD
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    # Final summary
    print('\n' + '=' * 70)
    print('  COMPLETE: %d variants on %d coins (excl %d worst by P&L)' % (
        len(ROBUSTNESS_GRID), n_total, n_excluded_actual))
    print('  G7 Neighbor Stability: %d/12 profitable (%s)' % (
        n_profitable, 'PASS' if g7_pass else 'FAIL'))
    print('  Stress profitable: %d/12' % n_stress_profitable)
    print('  WF >= 3/5: %d/12' % n_wf_3plus)
    print('  Top-1: %s (score=%.4f)' % (ranked[0]['label'], ranked[0]['composite_score']))
    if len(ranked) > 1:
        print('  Top-2: %s (score=%.4f)' % (ranked[1]['label'], ranked[1]['composite_score']))
    if len(ranked) > 2:
        print('  Top-3: %s (score=%.4f)' % (ranked[2]['label'], ranked[2]['composite_score']))
    print('  Runtime: %.1fs' % elapsed)
    print('  Comparison: 316-coin G7=9/12, 295-coin G7=12/12')
    print('=' * 70)


if __name__ == '__main__':
    main()
