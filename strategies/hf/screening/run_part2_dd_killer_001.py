#!/usr/bin/env python3
"""
Part 2 DD Killer: Drawdown Reduction Experiments (P0-4)
========================================================
Tests four approaches to reduce max drawdown on the 295-coin universe
while preserving trades/week >= 10:

  1. SL/TP retune grid (7 combos)
  2. Cooldown after loss sweep (5 levels)
  3. Volatility filter (ATR ratio threshold, 4 levels)
  4. Combined best-of-each

Gate evaluation per variant (STRICT):
  G1: trades/week >= 10
  G2: max gap <= 2.5 days
  G3: exp/week > $0
  G4: exp/week > $0 (stress 2x)
  G5: max DD <= 20%
  G6: WF >= 4/5
  G8: fold_conc < 35%

Output:
  reports/hf/part2_dd_killer_001.json
  reports/hf/part2_dd_killer_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_dd_killer_001.py
    python strategies/hf/screening/run_part2_dd_killer_001.py --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from copy import deepcopy

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
PARAMS_V5 = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# --- Experiment grids ---

# 1. SL/TP retune
SLTP_GRID = [
    {'label': 'baseline (sl5/tp8)',    'sl_pct': 5, 'tp_pct': 8},
    {'label': 'sl3/tp6 (tight)',       'sl_pct': 3, 'tp_pct': 6},
    {'label': 'sl3/tp8',              'sl_pct': 3, 'tp_pct': 8},
    {'label': 'sl4/tp8',              'sl_pct': 4, 'tp_pct': 8},
    {'label': 'sl5/tp6 (tight tp)',   'sl_pct': 5, 'tp_pct': 6},
    {'label': 'sl5/tp10 (wide tp)',   'sl_pct': 5, 'tp_pct': 10},
    {'label': 'sl7/tp8',              'sl_pct': 7, 'tp_pct': 8},
    {'label': 'sl7/tp10',             'sl_pct': 7, 'tp_pct': 10},
]

# 2. Cooldown sweep
COOLDOWN_GRID = [
    {'label': 'cd0/cas0 (no cooldown)', 'cooldown_bars': 0,  'cooldown_after_stop': 0},
    {'label': 'cd4/cas8 (baseline)',     'cooldown_bars': 4,  'cooldown_after_stop': 8},
    {'label': 'cd4/cas12',               'cooldown_bars': 4,  'cooldown_after_stop': 12},
    {'label': 'cd8/cas12',               'cooldown_bars': 8,  'cooldown_after_stop': 12},
    {'label': 'cd8/cas24 (1 day)',       'cooldown_bars': 8,  'cooldown_after_stop': 24},
    {'label': 'cd12/cas24',              'cooldown_bars': 12, 'cooldown_after_stop': 24},
]

# 3. Volatility filter thresholds
VOL_FILTER_GRID = [
    {'label': 'no vol filter',  'atr_threshold': None},
    {'label': 'atr_ratio<1.5',  'atr_threshold': 1.5},
    {'label': 'atr_ratio<2.0',  'atr_threshold': 2.0},
    {'label': 'atr_ratio<2.5',  'atr_threshold': 2.5},
    {'label': 'atr_ratio<3.0',  'atr_threshold': 3.0},
]


# ============================================================
# Volatility-filtered signal wrapper
# ============================================================

def make_vol_filtered_signal(base_signal_fn, atr_threshold):
    """Wrap a signal function to skip entries when ATR ratio is too high."""
    if atr_threshold is None:
        return base_signal_fn

    def filtered_signal(candles, bar, ind, params):
        # Check ATR ratio from extended indicators (precomputed)
        atr_ratio_list = ind.get('atr_ratio')
        if atr_ratio_list is not None and bar < len(atr_ratio_list):
            ratio = atr_ratio_list[bar]
            if ratio is not None and ratio > atr_threshold:
                return None  # Skip: too volatile
        else:
            # Fallback: compute from raw ATR
            atr_list = ind.get('atr', [])
            if bar >= 50 and bar < len(atr_list) and atr_list[bar] is not None:
                atr_window = []
                for j in range(max(0, bar - 49), bar + 1):
                    if j < len(atr_list) and atr_list[j] is not None:
                        atr_window.append(atr_list[j])
                if atr_window:
                    avg_atr = sum(atr_window) / len(atr_window)
                    if avg_atr > 0 and atr_list[bar] / avg_atr > atr_threshold:
                        return None

        return base_signal_fn(candles, bar, ind, params)

    return filtered_signal


# ============================================================
# Per-tier combined backtest runner
# ============================================================

def run_combined(data, tier_coins, tier_indicators, market_context,
                 tier1_fee, tier2_fee, params,
                 signal_fn=None,
                 cooldown_bars=4, cooldown_after_stop=8):
    """Run H20 across both tiers, return combined trade list."""
    if signal_fn is None:
        signal_fn = signal_h20_vwap_deviation

    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_context}

    all_trades = []
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_fn,
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
                              signal_fn=None,
                              cooldown_bars=4, cooldown_after_stop=8,
                              n_folds=5):
    """Walk-forward across both tiers; returns {fold_idx: [trades]}."""
    if signal_fn is None:
        signal_fn = signal_h20_vwap_deviation

    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_context}

    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    tier_fold_trades = {}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_fn,
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
# Max gap between trades (in days)
# ============================================================

def compute_max_gap_days(trades):
    """Compute max gap between consecutive trade entries, in days."""
    if len(trades) < 2:
        return 0.0
    entry_bars = sorted(t.get('entry_bar', 0) for t in trades)
    max_gap = 0
    for i in range(1, len(entry_bars)):
        gap = entry_bars[i] - entry_bars[i - 1]
        if gap > max_gap:
            max_gap = gap
    return max_gap / BARS_PER_DAY


# ============================================================
# Fold concentration (top-1 fold share of total P&L)
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
# Gate evaluation (STRICT)
# ============================================================

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days, top1_fold_conc):
    """Evaluate strict gates. Returns dict of gate results."""
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
                     total_bars, params,
                     signal_fn=None,
                     cooldown_bars=4, cooldown_after_stop=8):
    """Run baseline + stress + WF and evaluate all gates. Returns result dict."""
    t0 = time.time()

    # 1. Baseline
    trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, params,
        signal_fn=signal_fn,
        cooldown_bars=cooldown_bars,
        cooldown_after_stop=cooldown_after_stop,
    )
    metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)
    max_gap = compute_max_gap_days(trades)

    # 2. Stress 2x
    stress_trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        stress_t1_fee, stress_t2_fee, params,
        signal_fn=signal_fn,
        cooldown_bars=cooldown_bars,
        cooldown_after_stop=cooldown_after_stop,
    )
    stress_metrics = compute_metrics(stress_trades, initial_capital=2000.0, total_bars=total_bars)

    # 3. Walk-forward 5-fold
    fold_trades = run_walk_forward_combined(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, params,
        signal_fn=signal_fn,
        cooldown_bars=cooldown_bars,
        cooldown_after_stop=cooldown_after_stop,
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

    # 4. Gates
    gates, all_pass = evaluate_gates(
        metrics, stress_metrics, folds_positive, max_gap, fold_conc,
    )

    elapsed = time.time() - t0

    # Count tier split
    t1_trades = sum(1 for t in trades if t.get('_tier') == 'tier1')
    t2_trades = sum(1 for t in trades if t.get('_tier') == 'tier2')

    gates_passed = sum(1 for g in gates.values() if g['pass'])
    gates_total = len(gates)

    result = {
        'label': label,
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
    print('  %-28s trades=%3d PF=%.3f exp/w=$%.2f DD=%.1f%% WF=%d/5 gap=%.1f fc=%.2f [%s] (%.1fs)' % (
        label, metrics['trades'], metrics['pf'], metrics['exp_per_week'],
        metrics['dd'], folds_positive, max_gap, fold_conc, pass_str, elapsed))

    return result


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 DD Killer: Drawdown Reduction Experiments',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data, print grids, skip backtests')
    args = parser.parse_args()

    print('=' * 74)
    print('  Part 2 DD Killer: Drawdown Reduction Experiments (P0-4)')
    print('  Universe: 295-coin (excl 21 net-negative)')
    print('  Signal: H20 VWAP_DEVIATION v5')
    print('  Cost: MEXC Market (costs_mexc_v2)')
    print('=' * 74)
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
        print('SL/TP grid: %d variants' % len(SLTP_GRID))
        for v in SLTP_GRID:
            print('  %s' % v['label'])
        print('Cooldown grid: %d variants' % len(COOLDOWN_GRID))
        for v in COOLDOWN_GRID:
            print('  %s' % v['label'])
        print('Vol filter grid: %d variants' % len(VOL_FILTER_GRID))
        for v in VOL_FILTER_GRID:
            print('  %s' % v['label'])
        print('+ Combined best variant')
        total_variants = len(SLTP_GRID) + len(COOLDOWN_GRID) + len(VOL_FILTER_GRID) + 1
        print('Total: %d variants x 3 passes each' % total_variants)
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

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('[Data] total_bars=%d total_weeks=%.1f' % (total_bars, total_weeks))

    all_results = {}

    # ================================================================
    # EXPERIMENT 1: SL/TP Retune
    # ================================================================
    print('\n' + '=' * 74)
    print('  EXPERIMENT 1: SL/TP Retune Grid (%d variants)' % len(SLTP_GRID))
    print('=' * 74)

    sltp_results = []
    for variant in SLTP_GRID:
        params = {
            'dev_thresh': PARAMS_V5['dev_thresh'],
            'tp_pct': variant['tp_pct'],
            'sl_pct': variant['sl_pct'],
            'time_limit': PARAMS_V5['time_limit'],
        }
        result = evaluate_variant(
            label=variant['label'],
            data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
            total_bars=total_bars, params=params,
        )
        result['params'] = params
        sltp_results.append(result)

    all_results['sltp'] = sltp_results

    # Find best SL/TP by: passes most gates, then lowest DD, then highest exp/week
    best_sltp = sorted(sltp_results,
                       key=lambda r: (r['gates_passed'], -r['baseline_metrics']['dd'],
                                      r['baseline_metrics']['exp_per_week']),
                       reverse=True)[0]
    print('\n  Best SL/TP: %s (gates=%d/%d DD=%.1f%%)' % (
        best_sltp['label'], best_sltp['gates_passed'],
        best_sltp['gates_total'], best_sltp['baseline_metrics']['dd']))

    # ================================================================
    # EXPERIMENT 2: Cooldown After Loss
    # ================================================================
    print('\n' + '=' * 74)
    print('  EXPERIMENT 2: Cooldown After Loss (%d variants)' % len(COOLDOWN_GRID))
    print('=' * 74)

    cooldown_results = []
    for variant in COOLDOWN_GRID:
        result = evaluate_variant(
            label=variant['label'],
            data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
            total_bars=total_bars,
            params=PARAMS_V5,
            cooldown_bars=variant['cooldown_bars'],
            cooldown_after_stop=variant['cooldown_after_stop'],
        )
        result['cooldown_bars'] = variant['cooldown_bars']
        result['cooldown_after_stop'] = variant['cooldown_after_stop']
        cooldown_results.append(result)

    all_results['cooldown'] = cooldown_results

    best_cd = sorted(cooldown_results,
                     key=lambda r: (r['gates_passed'], -r['baseline_metrics']['dd'],
                                    r['baseline_metrics']['exp_per_week']),
                     reverse=True)[0]
    print('\n  Best Cooldown: %s (gates=%d/%d DD=%.1f%%)' % (
        best_cd['label'], best_cd['gates_passed'],
        best_cd['gates_total'], best_cd['baseline_metrics']['dd']))

    # ================================================================
    # EXPERIMENT 3: Volatility Filter
    # ================================================================
    print('\n' + '=' * 74)
    print('  EXPERIMENT 3: Volatility Filter (%d variants)' % len(VOL_FILTER_GRID))
    print('=' * 74)

    vol_results = []
    for variant in VOL_FILTER_GRID:
        sig_fn = make_vol_filtered_signal(
            signal_h20_vwap_deviation, variant['atr_threshold'],
        )
        result = evaluate_variant(
            label=variant['label'],
            data=data, tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
            total_bars=total_bars,
            params=PARAMS_V5,
            signal_fn=sig_fn,
        )
        result['atr_threshold'] = variant['atr_threshold']
        vol_results.append(result)

    all_results['vol_filter'] = vol_results

    best_vol = sorted(vol_results,
                      key=lambda r: (r['gates_passed'], -r['baseline_metrics']['dd'],
                                     r['baseline_metrics']['exp_per_week']),
                      reverse=True)[0]
    print('\n  Best Vol Filter: %s (gates=%d/%d DD=%.1f%%)' % (
        best_vol['label'], best_vol['gates_passed'],
        best_vol['gates_total'], best_vol['baseline_metrics']['dd']))

    # ================================================================
    # EXPERIMENT 4: Combined Best
    # ================================================================
    print('\n' + '=' * 74)
    print('  EXPERIMENT 4: Combined Best')
    print('=' * 74)

    # Extract best settings
    best_sl = best_sltp['params']['sl_pct'] if best_sltp['params'] else PARAMS_V5['sl_pct']
    best_tp = best_sltp['params']['tp_pct'] if best_sltp['params'] else PARAMS_V5['tp_pct']
    best_cd_bars = best_cd.get('cooldown_bars', 4)
    best_cas_bars = best_cd.get('cooldown_after_stop', 8)
    best_atr_thresh = best_vol.get('atr_threshold', None)

    combo_label = 'COMBO: sl%d/tp%d cd%d/cas%d atr<%s' % (
        best_sl, best_tp, best_cd_bars, best_cas_bars,
        str(best_atr_thresh) if best_atr_thresh else 'off')

    combo_params = {
        'dev_thresh': PARAMS_V5['dev_thresh'],
        'tp_pct': best_tp,
        'sl_pct': best_sl,
        'time_limit': PARAMS_V5['time_limit'],
    }

    combo_sig_fn = make_vol_filtered_signal(
        signal_h20_vwap_deviation, best_atr_thresh,
    )

    combo_result = evaluate_variant(
        label=combo_label,
        data=data, tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
        total_bars=total_bars,
        params=combo_params,
        signal_fn=combo_sig_fn,
        cooldown_bars=best_cd_bars,
        cooldown_after_stop=best_cas_bars,
    )
    combo_result['params'] = combo_params
    combo_result['cooldown_bars'] = best_cd_bars
    combo_result['cooldown_after_stop'] = best_cas_bars
    combo_result['atr_threshold'] = best_atr_thresh

    all_results['combined'] = combo_result

    # Also run a "max DD reduction" combo with tightest settings
    print('\n  --- Max DD Reduction Combo ---')
    max_dd_label = 'MAX_DD_KILL: sl3/tp6 cd12/cas24 atr<1.5'
    max_dd_params = {
        'dev_thresh': PARAMS_V5['dev_thresh'],
        'tp_pct': 6, 'sl_pct': 3, 'time_limit': PARAMS_V5['time_limit'],
    }
    max_dd_sig = make_vol_filtered_signal(signal_h20_vwap_deviation, 1.5)
    max_dd_result = evaluate_variant(
        label=max_dd_label,
        data=data, tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_t1_fee=stress_t1_fee, stress_t2_fee=stress_t2_fee,
        total_bars=total_bars,
        params=max_dd_params,
        signal_fn=max_dd_sig,
        cooldown_bars=12,
        cooldown_after_stop=24,
    )
    max_dd_result['params'] = max_dd_params
    max_dd_result['cooldown_bars'] = 12
    max_dd_result['cooldown_after_stop'] = 24
    max_dd_result['atr_threshold'] = 1.5

    all_results['max_dd_kill'] = max_dd_result

    elapsed_total = time.time() - t_global

    # ================================================================
    # Build Summary: All Variants Comparison
    # ================================================================
    print('\n' + '=' * 74)
    print('  SUMMARY: All Variants')
    print('=' * 74)

    summary_rows = []
    for section, results in [
        ('SL/TP', sltp_results),
        ('Cooldown', cooldown_results),
        ('VolFilter', vol_results),
    ]:
        for r in results:
            summary_rows.append({
                'section': section,
                'label': r['label'],
                'trades': r['baseline_metrics']['trades'],
                'pf': r['baseline_metrics']['pf'],
                'pnl': r['baseline_metrics']['pnl'],
                'exp_wk': r['baseline_metrics']['exp_per_week'],
                'dd': r['baseline_metrics']['dd'],
                'wf': r['wf_folds_positive'],
                'fold_conc': r['fold_concentration'],
                'max_gap': r['max_gap_days'],
                'gates_passed': r['gates_passed'],
                'gates_total': r['gates_total'],
                'all_pass': r['all_gates_pass'],
            })

    for tag, r in [('Combined', combo_result), ('MaxDDKill', max_dd_result)]:
        summary_rows.append({
            'section': tag,
            'label': r['label'],
            'trades': r['baseline_metrics']['trades'],
            'pf': r['baseline_metrics']['pf'],
            'pnl': r['baseline_metrics']['pnl'],
            'exp_wk': r['baseline_metrics']['exp_per_week'],
            'dd': r['baseline_metrics']['dd'],
            'wf': r['wf_folds_positive'],
            'fold_conc': r['fold_concentration'],
            'max_gap': r['max_gap_days'],
            'gates_passed': r['gates_passed'],
            'gates_total': r['gates_total'],
            'all_pass': r['all_gates_pass'],
        })

    # Print summary table
    print('  %-10s %-28s %4s %6s %7s %7s %5s %3s %5s %5s %s' % (
        'Section', 'Label', 'Tr', 'PF', 'P&L', 'Exp/Wk', 'DD%', 'WF', 'FC', 'Gap', 'Gates'))
    print('  ' + '-' * 110)
    for row in summary_rows:
        pass_str = 'ALL' if row['all_pass'] else '%d/%d' % (row['gates_passed'], row['gates_total'])
        print('  %-10s %-28s %4d %6.3f %7.0f %7.2f %5.1f %d/5 %5.2f %5.1f %s' % (
            row['section'], row['label'],
            row['trades'], row['pf'], row['pnl'], row['exp_wk'],
            row['dd'], row['wf'], row['fold_conc'], row['max_gap'], pass_str))

    # Count all-pass variants
    n_all_pass = sum(1 for r in summary_rows if r['all_pass'])
    print('\n  Variants passing ALL gates: %d/%d' % (n_all_pass, len(summary_rows)))
    print('  Total runtime: %.1fs' % elapsed_total)

    # ================================================================
    # JSON Report
    # ================================================================
    report = {
        'run_header': {
            'task': 'part2_dd_killer',
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
        'experiments': {
            'sltp_retune': {
                'description': 'SL/TP parameter retune grid',
                'n_variants': len(SLTP_GRID),
                'results': sltp_results,
                'best': best_sltp['label'],
            },
            'cooldown': {
                'description': 'Cooldown after loss sweep',
                'n_variants': len(COOLDOWN_GRID),
                'results': cooldown_results,
                'best': best_cd['label'],
            },
            'vol_filter': {
                'description': 'Volatility filter (ATR ratio threshold)',
                'n_variants': len(VOL_FILTER_GRID),
                'results': vol_results,
                'best': best_vol['label'],
            },
            'combined': {
                'description': 'Best cooldown + best SL/TP + best vol filter',
                'result': combo_result,
            },
            'max_dd_kill': {
                'description': 'Maximum DD reduction (tightest everything)',
                'result': max_dd_result,
            },
        },
        'summary': {
            'all_variants': summary_rows,
            'n_all_pass': n_all_pass,
            'n_total_variants': len(summary_rows),
            'best_overall': None,
        },
    }

    # Pick best overall (all gates pass, then lowest DD, then highest exp/wk)
    passing = [r for r in summary_rows if r['all_pass']]
    if passing:
        best_overall = sorted(passing, key=lambda r: (-r['exp_wk'], r['dd']))[0]
        report['summary']['best_overall'] = best_overall['label']
    else:
        # No all-pass; pick highest gates_passed then lowest DD
        best_overall = sorted(summary_rows,
                              key=lambda r: (r['gates_passed'], -r['dd'], r['exp_wk']),
                              reverse=True)[0]
        report['summary']['best_overall'] = best_overall['label'] + ' (partial)'

    json_path = ROOT / 'reports' / 'hf' / 'part2_dd_killer_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ================================================================
    # Markdown Report
    # ================================================================
    md = []
    md.append('# Part 2 DD Killer: Drawdown Reduction Experiments')
    md.append('')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Commit**: %s' % commit)
    md.append('**Universe**: T1(%d) + T2(%d) = %d coins (excl %d net-negative)' % (
        n_t1, n_t2, n_total, n_excl))
    md.append('**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
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

    # Summary table
    md.append('## Summary: All Variants')
    md.append('')
    md.append('| Section | Label | Trades | PF | P&L | Exp/Wk | DD%% | WF | FC | Gap | Gates |')
    md.append('|---------|-------|--------|----|------|--------|------|----|----|-----|-------|')
    for row in summary_rows:
        pass_str = '**ALL**' if row['all_pass'] else '%d/%d' % (row['gates_passed'], row['gates_total'])
        md.append('| %s | %s | %d | %.3f | $%.0f | $%.2f | %.1f | %d/5 | %.2f | %.1f | %s |' % (
            row['section'], row['label'],
            row['trades'], row['pf'], row['pnl'], row['exp_wk'],
            row['dd'], row['wf'], row['fold_conc'], row['max_gap'], pass_str))
    md.append('')

    md.append('**Variants passing ALL gates**: %d/%d' % (n_all_pass, len(summary_rows)))
    if report['summary']['best_overall']:
        md.append('**Best overall**: %s' % report['summary']['best_overall'])
    md.append('')

    # --- Experiment 1: SL/TP ---
    md.append('## Experiment 1: SL/TP Retune')
    md.append('')
    md.append('Baseline SL/TP = sl5/tp8. Testing tighter stops, tighter/wider targets.')
    md.append('')
    md.append('| Label | SL | TP | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |')
    md.append('|-------|----|----|--------|----|--------|------|----|----|----|----|----|----|----|-----|')
    for r in sltp_results:
        p = r.get('params', {})
        g = r['gates']
        def _pf(gate_key):
            return 'P' if g[gate_key]['pass'] else 'F'
        md.append('| %s | %s | %s | %d | %.3f | $%.2f | %.1f | %d/5 | %s | %s | %s | %s | %s | %s | %s |' % (
            r['label'], p.get('sl_pct', '?'), p.get('tp_pct', '?'),
            r['baseline_metrics']['trades'], r['baseline_metrics']['pf'],
            r['baseline_metrics']['exp_per_week'], r['baseline_metrics']['dd'],
            r['wf_folds_positive'],
            _pf('G1'), _pf('G2'), _pf('G3'), _pf('G4'), _pf('G5'), _pf('G6'), _pf('G8')))
    md.append('')
    md.append('**Best SL/TP**: %s' % best_sltp['label'])
    md.append('')

    # --- Experiment 2: Cooldown ---
    md.append('## Experiment 2: Cooldown After Loss')
    md.append('')
    md.append('Testing longer cooldown periods after stops to reduce revenge trading.')
    md.append('')
    md.append('| Label | CD | CAS | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |')
    md.append('|-------|----|-----|--------|----|--------|------|----|----|----|----|----|----|----|-----|')
    for r in cooldown_results:
        g = r['gates']
        def _pf(gate_key):
            return 'P' if g[gate_key]['pass'] else 'F'
        md.append('| %s | %s | %s | %d | %.3f | $%.2f | %.1f | %d/5 | %s | %s | %s | %s | %s | %s | %s |' % (
            r['label'], r.get('cooldown_bars', '?'), r.get('cooldown_after_stop', '?'),
            r['baseline_metrics']['trades'], r['baseline_metrics']['pf'],
            r['baseline_metrics']['exp_per_week'], r['baseline_metrics']['dd'],
            r['wf_folds_positive'],
            _pf('G1'), _pf('G2'), _pf('G3'), _pf('G4'), _pf('G5'), _pf('G6'), _pf('G8')))
    md.append('')
    md.append('**Best Cooldown**: %s' % best_cd['label'])
    md.append('')

    # --- Experiment 3: Volatility Filter ---
    md.append('## Experiment 3: Volatility Filter')
    md.append('')
    md.append('Skip entries when ATR_ratio (current ATR / SMA of ATR) exceeds threshold.')
    md.append('')
    md.append('| Label | Threshold | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |')
    md.append('|-------|-----------|--------|----|--------|------|----|----|----|----|----|----|----|-----|')
    for r in vol_results:
        g = r['gates']
        def _pf(gate_key):
            return 'P' if g[gate_key]['pass'] else 'F'
        thresh_str = str(r.get('atr_threshold', 'off'))
        md.append('| %s | %s | %d | %.3f | $%.2f | %.1f | %d/5 | %s | %s | %s | %s | %s | %s | %s |' % (
            r['label'], thresh_str,
            r['baseline_metrics']['trades'], r['baseline_metrics']['pf'],
            r['baseline_metrics']['exp_per_week'], r['baseline_metrics']['dd'],
            r['wf_folds_positive'],
            _pf('G1'), _pf('G2'), _pf('G3'), _pf('G4'), _pf('G5'), _pf('G6'), _pf('G8')))
    md.append('')
    md.append('**Best Vol Filter**: %s' % best_vol['label'])
    md.append('')

    # --- Experiment 4: Combined ---
    md.append('## Experiment 4: Combined Best')
    md.append('')
    md.append('Combines best individual findings:')
    md.append('- SL/TP: %s' % best_sltp['label'])
    md.append('- Cooldown: %s' % best_cd['label'])
    md.append('- Vol filter: %s' % best_vol['label'])
    md.append('')

    for tag, r in [('Combined', combo_result), ('Max DD Kill', max_dd_result)]:
        g = r['gates']
        pass_str = 'ALL PASS' if r['all_gates_pass'] else '%d/%d' % (r['gates_passed'], r['gates_total'])
        md.append('### %s: %s' % (tag, r['label']))
        md.append('')
        md.append('| Metric | Value |')
        md.append('|--------|-------|')
        md.append('| Trades | %d |' % r['baseline_metrics']['trades'])
        md.append('| PF | %.3f |' % r['baseline_metrics']['pf'])
        md.append('| P&L | $%.0f |' % r['baseline_metrics']['pnl'])
        md.append('| Exp/Week | $%.2f |' % r['baseline_metrics']['exp_per_week'])
        md.append('| DD%% | %.1f%% |' % r['baseline_metrics']['dd'])
        md.append('| WF | %d/5 |' % r['wf_folds_positive'])
        md.append('| Fold Conc | %.2f |' % r['fold_concentration'])
        md.append('| Max Gap | %.1f days |' % r['max_gap_days'])
        md.append('| Stress PF | %.3f |' % r['stress_metrics']['pf'])
        md.append('| Stress Exp/Wk | $%.2f |' % r['stress_metrics']['exp_per_week'])
        md.append('| **Gates** | **%s** |' % pass_str)
        md.append('')

        # Gate detail
        md.append('| Gate | Value | Threshold | Pass |')
        md.append('|------|-------|-----------|------|')
        for gk in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            gv = g[gk]
            pf_str = 'PASS' if gv['pass'] else 'FAIL'
            md.append('| %s | %s | %s | %s |' % (gk, gv['value'], gv['threshold'], pf_str))
        md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    if n_all_pass > 0:
        md.append('**%d variant(s) pass ALL strict gates.**' % n_all_pass)
        md.append('')
        md.append('Best overall: **%s**' % report['summary']['best_overall'])
    else:
        md.append('**No variant passes ALL strict gates.**')
        md.append('')
        md.append('Closest: **%s** (%d/%d gates)' % (
            report['summary']['best_overall'],
            max(r['gates_passed'] for r in summary_rows),
            summary_rows[0]['gates_total'] if summary_rows else 7))
    md.append('')

    # Key findings
    md.append('### Key Findings')
    md.append('')

    # SL/TP effect on DD
    baseline_dd = sltp_results[0]['baseline_metrics']['dd']
    for r in sltp_results[1:]:
        delta_dd = r['baseline_metrics']['dd'] - baseline_dd
        if abs(delta_dd) > 0.5:
            direction = 'reduces' if delta_dd < 0 else 'increases'
            md.append('- **%s** %s DD by %.1f%% (%.1f%% -> %.1f%%)' % (
                r['label'], direction, abs(delta_dd), baseline_dd, r['baseline_metrics']['dd']))

    # Cooldown effect
    base_cd_dd = cooldown_results[1]['baseline_metrics']['dd']  # cd4/cas8 baseline
    for r in cooldown_results[2:]:
        delta_dd = r['baseline_metrics']['dd'] - base_cd_dd
        delta_trades = r['baseline_metrics']['trades'] - cooldown_results[1]['baseline_metrics']['trades']
        if abs(delta_dd) > 0.5 or abs(delta_trades) > 2:
            md.append('- **%s**: DD %.1f%% (%+.1f%%), trades %d (%+d)' % (
                r['label'], r['baseline_metrics']['dd'], delta_dd,
                r['baseline_metrics']['trades'], delta_trades))

    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_dd_killer_001.py at %s*' % (
        datetime.now().strftime('%Y-%m-%d %H:%M')))

    md_path = ROOT / 'reports' / 'hf' / 'part2_dd_killer_001.md'
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    # Final summary
    print('\n' + '=' * 74)
    print('  DD KILLER COMPLETE')
    print('  Variants tested: %d' % len(summary_rows))
    print('  ALL gates pass: %d/%d' % (n_all_pass, len(summary_rows)))
    print('  Best overall: %s' % report['summary']['best_overall'])
    print('  Runtime: %.1fs' % elapsed_total)
    print('=' * 74)


if __name__ == '__main__':
    main()
