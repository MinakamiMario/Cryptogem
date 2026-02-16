#!/usr/bin/env python3
"""
Part 2 Baseline Gate Evaluation: 316-coin vs 295-coin (STRICT)
===============================================================
Agent C7-F Integrator script.

Runs the v5 baseline (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)
on BOTH the full 316-coin and 295-coin universes with STRICT gate thresholds.

For each universe:
  1. Full backtest (baseline fees)
  2. Stress 2x backtest
  3. Walk-forward 5-fold
  4. ALL gate metrics evaluated

Gates (STRICT):
  G1: trades_per_week >= 10
  G2: max_gap_days <= 2.5
  G3: exp_per_week > $0 (baseline)
  G4: exp_per_week > $0 (stress 2x)
  G5: max_dd <= 20%
  G6: walk-forward >= 4/5 positive folds
  G8: top1 fold concentration < 35%

Output:
  reports/hf/part2_baseline_316_001.json
  reports/hf/part2_baseline_316_001.md

Usage:
    python strategies/hf/screening/run_part2_baseline_316_001.py
"""
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import precompute_base_indicators
from strategies.hf.screening.run_h20_robustness import (
    BARS_PER_WEEK,
    load_candle_cache,
    load_universe_tiering,
    build_tier_coins,
    run_h20_variant,
    run_h20_walk_forward,
    compute_metrics,
    estimate_total_bars,
)
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee, stress_multiplier

REPORT_JSON = 'part2_baseline_316_001.json'
REPORT_MD   = 'part2_baseline_316_001.md'

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
    'label': 'v5 baseline',
}

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}


# -----------------------------------------------------------------------
# Max gap computation
# -----------------------------------------------------------------------
def compute_max_gap_days(trades, total_bars):
    """Compute max gap between consecutive trade entries in days (1H bars)."""
    if len(trades) < 2:
        return total_bars / 24.0 if total_bars > 0 else 999.0
    sorted_trades = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    max_gap_bars = 0
    for i in range(1, len(sorted_trades)):
        gap = sorted_trades[i]['entry_bar'] - sorted_trades[i - 1]['entry_bar']
        if gap > max_gap_bars:
            max_gap_bars = gap
    # Also check gap from start to first trade and last trade to end
    first_gap = sorted_trades[0]['entry_bar'] - 50  # start_bar = 50
    last_gap = total_bars - sorted_trades[-1].get('exit_bar', sorted_trades[-1]['entry_bar'])
    max_gap_bars = max(max_gap_bars, first_gap, last_gap)
    return max_gap_bars / 24.0  # convert 1H bars to days


# -----------------------------------------------------------------------
# Fold concentration
# -----------------------------------------------------------------------
def compute_fold_concentration(fold_details):
    """Compute top-1 fold profit concentration.

    = max(fold_pnl) / sum(positive_fold_pnls)
    Only considers positive folds. Returns 1.0 if only 1 positive fold.
    """
    positive_folds = [f for f in fold_details if f['pnl'] > 0]
    if not positive_folds:
        return 1.0
    total_positive = sum(f['pnl'] for f in positive_folds)
    if total_positive <= 0:
        return 1.0
    max_fold_pnl = max(f['pnl'] for f in positive_folds)
    return max_fold_pnl / total_positive


# -----------------------------------------------------------------------
# Gate evaluation (STRICT)
# -----------------------------------------------------------------------
def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days,
                   top1_fold_conc, n_folds=5):
    """Evaluate all gates with STRICT thresholds."""
    gates = {}
    gates['G1'] = {
        'name': 'Throughput',
        'value': round(metrics['trades_per_week'], 2),
        'threshold': '>= 10/wk',
        'pass': metrics['trades_per_week'] >= 10,
    }
    gates['G2'] = {
        'name': 'Max Gap',
        'value': round(max_gap_days, 2),
        'threshold': '<= 2.5d',
        'pass': max_gap_days <= 2.5,
    }
    gates['G3'] = {
        'name': 'Edge (baseline)',
        'value': round(metrics['exp_per_week'], 2),
        'threshold': '> $0',
        'pass': metrics['exp_per_week'] > 0,
    }
    gates['G4'] = {
        'name': 'Edge (stress 2x)',
        'value': round(stress_metrics['exp_per_week'], 2),
        'threshold': '> $0',
        'pass': stress_metrics['exp_per_week'] > 0,
    }
    gates['G5'] = {
        'name': 'Max Drawdown',
        'value': round(metrics['dd'], 1),
        'threshold': '<= 20%',
        'pass': metrics['dd'] <= 20,
    }
    gates['G6'] = {
        'name': 'Walk-Forward',
        'value': '%d/%d' % (wf_folds_positive, n_folds),
        'threshold': '>= 4/5',
        'pass': wf_folds_positive >= 4,
    }
    gates['G8'] = {
        'name': 'Fold Concentration',
        'value': round(top1_fold_conc * 100, 1),
        'threshold': '< 35%',
        'pass': top1_fold_conc < 0.35,
    }
    n_pass = sum(1 for g in gates.values() if g['pass'])
    return gates, n_pass


# -----------------------------------------------------------------------
# Per-coin P&L analysis
# -----------------------------------------------------------------------
def per_coin_pnl(trades):
    """Group trades by coin pair, compute per-coin stats."""
    coin_stats = {}
    for t in trades:
        pair = t['pair']
        if pair not in coin_stats:
            coin_stats[pair] = {'trades': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0}
        coin_stats[pair]['trades'] += 1
        coin_stats[pair]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            coin_stats[pair]['wins'] += 1
        else:
            coin_stats[pair]['losses'] += 1
    # Sort by pnl ascending (worst first)
    sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]['pnl'])
    return sorted_coins


# -----------------------------------------------------------------------
# Run evaluation for one universe
# -----------------------------------------------------------------------
def run_evaluation(label, params, data, tier_coins, tier_indicators,
                   market_context, tier1_fee, tier2_fee, stress_t1_fee,
                   stress_t2_fee, total_bars):
    """Run full evaluation pipeline for one universe configuration."""
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('\n--- Evaluating: %s ---' % label)
    n_coins = sum(len(c) for c in tier_coins.values())
    print('  Universe: %d coins' % n_coins)

    # Pass 1: Baseline backtest
    t0 = time.time()
    trades = run_h20_variant(
        params=params, data=data, tier_coins=tier_coins,
        tier_indicators=tier_indicators, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
    )
    metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)
    t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
    t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
    print('  Baseline: %d trades (T1:%d T2:%d) PF=%.3f WR=%.1f%% exp/w=$%.2f DD=%.1f%% (%.1fs)' % (
        metrics['trades'], len(t1_trades), len(t2_trades),
        metrics['pf'], metrics['wr'], metrics['exp_per_week'],
        metrics['dd'], time.time() - t0))

    # Pass 2: Stress 2x
    t0 = time.time()
    stress_trades = run_h20_variant(
        params=params, data=data, tier_coins=tier_coins,
        tier_indicators=tier_indicators, market_context=market_context,
        tier1_fee=stress_t1_fee, tier2_fee=stress_t2_fee,
    )
    stress_metrics = compute_metrics(
        stress_trades, initial_capital=2000.0, total_bars=total_bars,
    )
    print('  Stress 2x: PF=%.3f exp/w=$%.2f DD=%.1f%% (%.1fs)' % (
        stress_metrics['pf'], stress_metrics['exp_per_week'],
        stress_metrics['dd'], time.time() - t0))

    # Pass 3: Walk-forward 5-fold
    t0 = time.time()
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
        # Per-coin breakdown for this fold
        fold_coin_pnl = {}
        for t in fold_trades[fold_idx]:
            pair = t['pair']
            fold_coin_pnl[pair] = fold_coin_pnl.get(pair, 0.0) + t['pnl']
        # Top contributor in this fold
        top_coin = max(fold_coin_pnl.items(), key=lambda x: abs(x[1])) if fold_coin_pnl else ('N/A', 0)
        fold_details.append({
            'fold': fold_idx,
            'trades': fold_n,
            'pnl': round(fold_pnl, 2),
            'positive': is_positive,
            'top_coin': top_coin[0],
            'top_coin_pnl': round(top_coin[1], 2),
        })
    print('  Walk-Forward: %d/5 positive (%.1fs)' % (folds_positive, time.time() - t0))
    for fd in fold_details:
        mark = '+' if fd['positive'] else '-'
        print('    F%d: %s$%.0f (%d trades, top: %s $%.0f)' % (
            fd['fold'], mark, abs(fd['pnl']), fd['trades'],
            fd['top_coin'], fd['top_coin_pnl']))

    # Compute gate inputs
    max_gap_days = compute_max_gap_days(trades, total_bars)
    top1_fold_conc = compute_fold_concentration(fold_details)

    # Gate evaluation
    gates, n_pass = evaluate_gates(
        metrics, stress_metrics, folds_positive, max_gap_days,
        top1_fold_conc,
    )
    print('  Gates: %d/7 PASS' % n_pass)
    for gid, g in sorted(gates.items()):
        status = 'PASS' if g['pass'] else 'FAIL'
        print('    %s %-20s %s %s  [%s]' % (gid, g['name'], g['value'], g['threshold'], status))

    # Per-coin analysis
    coin_breakdown = per_coin_pnl(trades)
    worst_10 = coin_breakdown[:10]
    best_10 = coin_breakdown[-10:]
    best_10.reverse()

    # Worst trades
    worst_trades = sorted(trades, key=lambda t: t['pnl'])[:10]

    # Exit reason breakdown
    exit_reasons = Counter(t['reason'] for t in trades)
    exit_pnl = {}
    for t in trades:
        r = t['reason']
        if r not in exit_pnl:
            exit_pnl[r] = {'count': 0, 'pnl': 0.0, 'wins': 0}
        exit_pnl[r]['count'] += 1
        exit_pnl[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            exit_pnl[r]['wins'] += 1

    return {
        'label': label,
        'n_coins': n_coins,
        'tier_split': {
            'tier1': len(tier_coins.get('tier1', [])),
            'tier2': len(tier_coins.get('tier2', [])),
        },
        'baseline_metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'wr': stress_metrics['wr'],
            'dd': stress_metrics['dd'],
            'exp_per_week': stress_metrics['exp_per_week'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'top1_fold_conc': round(top1_fold_conc, 4),
        'max_gap_days': round(max_gap_days, 2),
        'gates': gates,
        'gates_pass': n_pass,
        'gates_total': 7,
        'tier_trade_split': {
            'tier1_trades': len(t1_trades),
            'tier2_trades': len(t2_trades),
        },
        'worst_coins': [
            {'pair': pair, **stats} for pair, stats in worst_10
        ],
        'best_coins': [
            {'pair': pair, **stats} for pair, stats in best_10
        ],
        'worst_trades': [
            {
                'pair': t['pair'], 'pnl': round(t['pnl'], 2),
                'pnl_pct': round(t['pnl_pct'], 2), 'reason': t['reason'],
                'bars': t['bars'], 'entry_bar': t['entry_bar'],
                'tier': t.get('_tier', 'unknown'),
            }
            for t in worst_trades
        ],
        'exit_breakdown': {
            r: {
                'count': v['count'],
                'pnl': round(v['pnl'], 2),
                'wr': round(v['wins'] / v['count'] * 100, 1) if v['count'] > 0 else 0,
            }
            for r, v in sorted(exit_pnl.items(), key=lambda x: x[1]['pnl'])
        },
    }


# -----------------------------------------------------------------------
# Gap analysis
# -----------------------------------------------------------------------
def compute_gap_analysis(result_316, result_295):
    """For each failing gate on 316, compute what needs to change."""
    gaps = []
    gates_316 = result_316['gates']
    gates_295 = result_295['gates']

    for gid in sorted(gates_316.keys()):
        g316 = gates_316[gid]
        g295 = gates_295.get(gid, {})
        if g316['pass']:
            continue  # only analyze failing gates

        gap_entry = {
            'gate': gid,
            'name': g316['name'],
            'value_316': g316['value'],
            'value_295': g295.get('value', 'N/A'),
            'threshold': g316['threshold'],
            'status_295': 'PASS' if g295.get('pass', False) else 'FAIL',
            'analysis': '',
            'suggestions': [],
        }

        if gid == 'G4':
            # Stress exp/week needs to be > $0
            v316 = result_316['stress_metrics']['exp_per_week']
            v295 = result_295['stress_metrics']['exp_per_week']
            gap_entry['analysis'] = (
                '316-coin stress exp/wk = $%.2f (need > $0). '
                '295-coin = $%.2f. The 21 excluded T2 coins with high fees '
                'drag edge below zero under 2x stress.' % (v316, v295)
            )
            gap_entry['suggestions'] = [
                'Reduce T2 exposure (fee drag dominates under stress)',
                'Tighten SL to reduce loss magnitude per trade',
                'Raise dev_thresh to filter weak signals (fewer but cleaner trades)',
                'Consider T2 fee rebate or maker-order strategy',
            ]
        elif gid == 'G5':
            dd316 = result_316['baseline_metrics']['dd']
            dd295 = result_295['baseline_metrics']['dd']
            reduction_needed = dd316 - 20.0
            gap_entry['analysis'] = (
                '316-coin DD = %.1f%% (need <= 20%%). Need %.1f%% DD reduction. '
                '295-coin DD = %.1f%%.' % (dd316, reduction_needed, dd295)
            )
            gap_entry['suggestions'] = [
                'Reduce position size (currently 100% of capital)',
                'Tighten stop loss (sl_pct from 5% to 3-4%)',
                'Add max_pos > 1 for diversification',
                'Time-based risk reduction (shorter time_limit)',
            ]
        elif gid == 'G6':
            wf316 = result_316['wf_folds_positive']
            wf295 = result_295['wf_folds_positive']
            # Identify which folds fail
            failing_folds = []
            for fd in result_316['wf_fold_details']:
                if not fd['positive']:
                    failing_folds.append(fd)
            gap_entry['analysis'] = (
                '316-coin WF = %d/5 (need >= 4/5). '
                '295-coin WF = %d/5. Failing folds: %s' % (
                    wf316, wf295,
                    ', '.join('F%d ($%.0f, %d trades, top: %s)' % (
                        f['fold'], f['pnl'], f['trades'], f.get('top_coin', 'N/A'))
                        for f in failing_folds)
                )
            )
            gap_entry['suggestions'] = [
                'Investigate failing fold periods for regime shifts',
                'Test adaptive parameters per market regime',
                'Check if excluded coins drive fold losses',
                'Consider 3/5 threshold for GO with caveats',
            ]
        elif gid == 'G8':
            conc316 = result_316['top1_fold_conc']
            conc295 = result_295['top1_fold_conc']
            gap_entry['analysis'] = (
                '316-coin fold_conc = %.1f%% (need < 35%%). '
                '295-coin fold_conc = %.1f%%.' % (conc316 * 100, conc295 * 100)
            )
            gap_entry['suggestions'] = [
                'More uniform edge across folds needed',
                'Check if one fold has an outlier coin',
                'Diversify signal sources across time periods',
            ]
        elif gid == 'G1':
            gap_entry['analysis'] = (
                'Trades/week = %.1f (need >= 10). '
                'Consider lowering dev_thresh to increase signal frequency.' % (
                    result_316['baseline_metrics']['trades_per_week'])
            )
            gap_entry['suggestions'] = [
                'Lower dev_thresh (1.8 generates more signals)',
                'Reduce cooldown periods',
                'Add complementary signals',
            ]
        elif gid == 'G2':
            gap_entry['analysis'] = (
                'Max gap = %.1f days (need <= 2.5d). '
                'Long dry spell without trades.' % result_316['max_gap_days']
            )
            gap_entry['suggestions'] = [
                'Lower signal threshold for more frequent entries',
                'Add alternative signal triggers during gaps',
            ]
        else:
            gap_entry['analysis'] = 'Gate %s fails. Review threshold and metric.' % gid

        gaps.append(gap_entry)

    return gaps


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    print('=' * 72)
    print('  Part 2 Baseline Gate Evaluation: 316 vs 295 (STRICT)')
    print('  Agent C7-F Integrator')
    print('=' * 72)
    print('Started: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    t_start = time.time()

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Fees ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_regime = stress_multiplier('mexc_market', 2.0)
    stress_t1_fee = stress_regime['tier1']['total_per_side_bps'] / 10000.0
    stress_t2_fee = stress_regime['tier2']['total_per_side_bps'] / 10000.0
    print('[Costs] Baseline: T1=%.1fbps T2=%.1fbps' % (tier1_fee * 10000, tier2_fee * 10000))
    print('[Costs] Stress 2x: T1=%.1fbps T2=%.1fbps' % (stress_t1_fee * 10000, stress_t2_fee * 10000))

    # --- Load data ---
    data = load_candle_cache('1h', require_data=True)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=True)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    n_t1_full = len(tier_coins_full['tier1'])
    n_t2_full = len(tier_coins_full['tier2'])
    n_total_full = n_t1_full + n_t2_full
    print('[Universe] Full: T1=%d T2=%d Total=%d' % (n_t1_full, n_t2_full, n_total_full))

    # 295-coin universe (exclude 21)
    tier_coins_295 = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1_295 = len(tier_coins_295['tier1'])
    n_t2_295 = len(tier_coins_295['tier2'])
    n_total_295 = n_t1_295 + n_t2_295
    actual_excluded = n_total_full - n_total_295
    print('[Universe] 295: T1=%d T2=%d Total=%d (excluded %d)' % (
        n_t1_295, n_t2_295, n_total_295, actual_excluded))

    # --- Precompute indicators (full universe, then subset) ---
    print('[Indicators] Precomputing base indicators (full)...')
    tier_indicators_full = {}
    for tier_name, coins in tier_coins_full.items():
        if coins:
            t_ind = time.time()
            tier_indicators_full[tier_name] = precompute_base_indicators(data, coins)
            print('  %s: %d coins in %.1fs' % (tier_name, len(coins), time.time() - t_ind))

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_full.items():
        if coins and tier_name in tier_indicators_full:
            extend_indicators(data, coins, tier_indicators_full[tier_name])
            cov = get_feature_coverage(tier_indicators_full[tier_name], coins)
            print('  %s: VWAP %.0f%% (%d/%d)' % (
                tier_name, cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

    # Market context (use all coins including BTC)
    print('[Market Context] Precomputing...')
    all_coins = list(set(
        tier_coins_full.get('tier1', []) + tier_coins_full.get('tier2', [])
    ))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators_full.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('[Data] total_bars=%d, total_weeks=%.1f' % (total_bars, total_weeks))

    # Build 295-coin indicator subset (reuse precomputed, just subset the dicts)
    tier_indicators_295 = {}
    for tier_name in ('tier1', 'tier2'):
        full_ind = tier_indicators_full.get(tier_name, {})
        coins_295 = set(tier_coins_295.get(tier_name, []))
        tier_indicators_295[tier_name] = {
            c: ind for c, ind in full_ind.items() if c in coins_295
        }

    # Enrich params with market context
    enriched_params = {k: v for k, v in PARAMS_V5.items()}
    enriched_params['__market__'] = market_context

    # ================================================================
    # Run evaluations
    # ================================================================
    result_316 = run_evaluation(
        label='Full 316-coin universe',
        params=PARAMS_V5,
        data=data,
        tier_coins=tier_coins_full,
        tier_indicators=tier_indicators_full,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
        total_bars=total_bars,
    )

    result_295 = run_evaluation(
        label='295-coin universe (excl 21)',
        params=PARAMS_V5,
        data=data,
        tier_coins=tier_coins_295,
        tier_indicators=tier_indicators_295,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
        total_bars=total_bars,
    )

    # ================================================================
    # Gap Analysis
    # ================================================================
    print('\n--- Gap Analysis: 316 -> Passing ---')
    gap_analysis = compute_gap_analysis(result_316, result_295)
    if not gap_analysis:
        print('  All gates pass on 316 coins!')
    else:
        for gap in gap_analysis:
            print('  %s %s: %s' % (gap['gate'], gap['name'], gap['analysis'][:100]))

    elapsed = time.time() - t_start

    # ================================================================
    # Build JSON report
    # ================================================================
    report = {
        'run_header': {
            'task': 'part2_baseline_316_gate_evaluation',
            'agent': 'C7-F Integrator',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': {k: v for k, v in PARAMS_V5.items() if k != 'label'},
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
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'universes': {
            '316': {
                'tier1': n_t1_full, 'tier2': n_t2_full, 'total': n_total_full,
            },
            '295': {
                'tier1': n_t1_295, 'tier2': n_t2_295, 'total': n_total_295,
                'excluded': actual_excluded,
                'excluded_coins': sorted(list(EXCLUDED_21)),
            },
        },
        'result_316': result_316,
        'result_295': result_295,
        'gap_analysis': gap_analysis,
        'verdict': {
            '316_gates_pass': result_316['gates_pass'],
            '316_gates_total': result_316['gates_total'],
            '295_gates_pass': result_295['gates_pass'],
            '295_gates_total': result_295['gates_total'],
            '316_verdict': 'GO' if result_316['gates_pass'] >= 6 else (
                'CONDITIONAL' if result_316['gates_pass'] >= 4 else 'NO-GO'),
            '295_verdict': 'GO' if result_295['gates_pass'] >= 6 else (
                'CONDITIONAL' if result_295['gates_pass'] >= 4 else 'NO-GO'),
            'failing_gates_316': [
                gid for gid, g in result_316['gates'].items() if not g['pass']
            ],
            'failing_gates_295': [
                gid for gid, g in result_295['gates'].items() if not g['pass']
            ],
        },
    }

    json_path = ROOT / 'reports' / 'hf' / REPORT_JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ================================================================
    # Build Markdown report
    # ================================================================
    md = []
    md.append('# Part 2 Baseline Gate Evaluation: 316 vs 295 (STRICT)')
    md.append('')
    md.append('**Agent**: C7-F Integrator')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Commit**: %s' % commit)
    md.append('**Params**: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10')
    md.append('**Fees**: T1=%.1fbps, T2=%.1fbps (stress 2x: T1=%.1fbps, T2=%.1fbps)' % (
        tier1_fee * 10000, tier2_fee * 10000,
        stress_t1_fee * 10000, stress_t2_fee * 10000))
    md.append('**Runtime**: %.1fs' % elapsed)
    md.append('')

    # Verdict box
    md.append('## Verdict')
    md.append('')
    v316 = report['verdict']['316_verdict']
    v295 = report['verdict']['295_verdict']
    md.append('| Universe | Gates Pass | Verdict | Failing |')
    md.append('|----------|-----------|---------|---------|')
    md.append('| **316 coins** | %d/%d | **%s** | %s |' % (
        result_316['gates_pass'], result_316['gates_total'], v316,
        ', '.join(report['verdict']['failing_gates_316']) or 'None'))
    md.append('| **295 coins** | %d/%d | **%s** | %s |' % (
        result_295['gates_pass'], result_295['gates_total'], v295,
        ', '.join(report['verdict']['failing_gates_295']) or 'None'))
    md.append('')

    # Gate comparison table
    md.append('## Gate Comparison')
    md.append('')
    md.append('| Gate | Name | Threshold | 316 Value | 316 | 295 Value | 295 |')
    md.append('|------|------|-----------|-----------|-----|-----------|-----|')
    for gid in sorted(result_316['gates'].keys()):
        g316 = result_316['gates'][gid]
        g295 = result_295['gates'].get(gid, {})
        s316 = 'PASS' if g316['pass'] else '**FAIL**'
        s295 = 'PASS' if g295.get('pass', False) else '**FAIL**'
        md.append('| %s | %s | %s | %s | %s | %s | %s |' % (
            gid, g316['name'], g316['threshold'],
            g316['value'], s316, g295.get('value', 'N/A'), s295))
    md.append('')

    # Metrics comparison
    md.append('## Metrics Comparison')
    md.append('')
    md.append('| Metric | 316 coins | 295 coins | Delta |')
    md.append('|--------|-----------|-----------|-------|')
    m316 = result_316['baseline_metrics']
    m295 = result_295['baseline_metrics']
    for key in ['trades', 'pnl', 'pf', 'wr', 'dd', 'trades_per_week', 'exp_per_week', 'fee_drag_pct']:
        v316 = m316[key]
        v295 = m295[key]
        if isinstance(v316, float):
            delta = v295 - v316
            if key in ('dd', 'fee_drag_pct'):
                # Lower is better for DD and fee drag
                sign = '+' if delta <= 0 else ''
            else:
                sign = '+' if delta >= 0 else ''
            md.append('| %s | %.2f | %.2f | %s%.2f |' % (key, v316, v295, sign, delta))
        else:
            md.append('| %s | %s | %s | %s |' % (key, v316, v295, v295 - v316))
    md.append('')

    # Stress comparison
    md.append('## Stress Test (2x fees)')
    md.append('')
    md.append('| Metric | 316 coins | 295 coins |')
    md.append('|--------|-----------|-----------|')
    s316 = result_316['stress_metrics']
    s295 = result_295['stress_metrics']
    for key in ['trades', 'pnl', 'pf', 'wr', 'dd', 'exp_per_week']:
        md.append('| %s | %s | %s |' % (key, s316[key], s295[key]))
    md.append('')

    # Walk-forward detail
    md.append('## Walk-Forward Detail (5-fold)')
    md.append('')
    md.append('### 316 coins')
    md.append('')
    md.append('| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |')
    md.append('|------|--------|-----|--------|----------|-------------|')
    for fd in result_316['wf_fold_details']:
        status = 'PASS' if fd['positive'] else '**FAIL**'
        md.append('| F%d | %d | $%.0f | %s | %s | $%.0f |' % (
            fd['fold'], fd['trades'], fd['pnl'], status,
            fd.get('top_coin', 'N/A'), fd.get('top_coin_pnl', 0)))
    md.append('')

    md.append('### 295 coins')
    md.append('')
    md.append('| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |')
    md.append('|------|--------|-----|--------|----------|-------------|')
    for fd in result_295['wf_fold_details']:
        status = 'PASS' if fd['positive'] else '**FAIL**'
        md.append('| F%d | %d | $%.0f | %s | %s | $%.0f |' % (
            fd['fold'], fd['trades'], fd['pnl'], status,
            fd.get('top_coin', 'N/A'), fd.get('top_coin_pnl', 0)))
    md.append('')

    # Gap analysis
    md.append('## Gap Analysis: 316 -> Passing')
    md.append('')
    if not gap_analysis:
        md.append('All gates pass on 316 coins.')
    else:
        for gap in gap_analysis:
            md.append('### %s: %s' % (gap['gate'], gap['name']))
            md.append('')
            md.append('- **316 value**: %s' % gap['value_316'])
            md.append('- **295 value**: %s (status: %s)' % (
                gap['value_295'], gap['status_295']))
            md.append('- **Threshold**: %s' % gap['threshold'])
            md.append('- **Analysis**: %s' % gap['analysis'])
            md.append('- **Suggestions**:')
            for s in gap['suggestions']:
                md.append('  - %s' % s)
            md.append('')

    # Worst coins on 316
    md.append('## Worst Coins (316 universe)')
    md.append('')
    md.append('| Coin | Trades | P&L | Wins | Losses |')
    md.append('|------|--------|-----|------|--------|')
    for c in result_316['worst_coins']:
        md.append('| %s | %d | $%.2f | %d | %d |' % (
            c['pair'], c['trades'], c['pnl'], c['wins'], c['losses']))
    md.append('')

    # Best coins on 316
    md.append('## Best Coins (316 universe)')
    md.append('')
    md.append('| Coin | Trades | P&L | Wins | Losses |')
    md.append('|------|--------|-----|------|--------|')
    for c in result_316['best_coins']:
        md.append('| %s | %d | $%.2f | %d | %d |' % (
            c['pair'], c['trades'], c['pnl'], c['wins'], c['losses']))
    md.append('')

    # Worst trades
    md.append('## Worst Trades (316 universe)')
    md.append('')
    md.append('| Coin | P&L | P&L% | Reason | Bars | Entry Bar | Tier |')
    md.append('|------|-----|------|--------|------|-----------|------|')
    for t in result_316['worst_trades']:
        md.append('| %s | $%.2f | %.1f%% | %s | %d | %d | %s |' % (
            t['pair'], t['pnl'], t['pnl_pct'], t['reason'],
            t['bars'], t['entry_bar'], t['tier']))
    md.append('')

    # Exit breakdown
    md.append('## Exit Reason Breakdown')
    md.append('')
    md.append('### 316 coins')
    md.append('')
    md.append('| Reason | Count | P&L | WR% |')
    md.append('|--------|-------|-----|-----|')
    for r, v in result_316['exit_breakdown'].items():
        md.append('| %s | %d | $%.2f | %.1f%% |' % (r, v['count'], v['pnl'], v['wr']))
    md.append('')

    md.append('### 295 coins')
    md.append('')
    md.append('| Reason | Count | P&L | WR% |')
    md.append('|--------|-------|-----|-----|')
    for r, v in result_295['exit_breakdown'].items():
        md.append('| %s | %d | $%.2f | %.1f%% |' % (r, v['count'], v['pnl'], v['wr']))
    md.append('')

    # Best-next-test suggestions
    md.append('## Best-Next-Test Suggestions')
    md.append('')
    if gap_analysis:
        md.append('Based on failing gates on 316:')
        md.append('')
        # Prioritize suggestions
        all_suggestions = []
        for gap in gap_analysis:
            for s in gap['suggestions']:
                all_suggestions.append('- [%s] %s' % (gap['gate'], s))
        for s in all_suggestions:
            md.append(s)
    else:
        md.append('All gates pass. Ready for paper trading validation.')
    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_baseline_316_001.py')
    md.append('at %s*' % datetime.now().strftime('%Y-%m-%d %H:%M'))

    md_path = ROOT / 'reports' / 'hf' / REPORT_MD
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    # Final summary
    print('\n' + '=' * 72)
    print('  COMPLETE')
    print('  316 coins: %d/%d gates PASS -> %s' % (
        result_316['gates_pass'], result_316['gates_total'],
        report['verdict']['316_verdict']))
    print('  295 coins: %d/%d gates PASS -> %s' % (
        result_295['gates_pass'], result_295['gates_total'],
        report['verdict']['295_verdict']))
    if gap_analysis:
        print('  Failing gates on 316: %s' % ', '.join(
            g['gate'] for g in gap_analysis))
    print('  Runtime: %.1fs' % elapsed)
    print('=' * 72)


if __name__ == '__main__':
    main()
