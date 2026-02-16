#!/usr/bin/env python3
"""
C8-A: Dev Threshold Sensitivity Sweep on 295-coin universe
============================================================
Tests dev_thresh = [1.5, 1.8, 2.0, 2.2, 2.5, 3.0] with v5 params
(tp_pct=8, sl_pct=5, time_limit=10) on the 295-coin universe.

For each dev_thresh value:
  1. Full baseline backtest (MEXC market fees, T1+T2 separate)
  2. Stress 2x backtest
  3. Walk-forward 5-fold
  4. All 7 STRICT gates evaluated

STRICT Gate Thresholds:
  G1: trades/week >= 10
  G2: max gap <= 2.5d
  G3: exp/week > $0 (baseline)
  G4: exp/week > $0 (stress 2x)
  G5: DD <= 20%
  G6: WF >= 4/5
  G8: fold_conc < 35%

Output:
  reports/hf/part2_dev_thresh_sweep_001.json
  reports/hf/part2_dev_thresh_sweep_001.md

Usage:
    python strategies/hf/screening/run_part2_dev_thresh_sweep_001.py
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

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee, stress_multiplier

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------
BARS_PER_WEEK = 168   # 24 * 7
BARS_PER_DAY = 24

REPORT_JSON = 'part2_dev_thresh_sweep_001.json'
REPORT_MD   = 'part2_dev_thresh_sweep_001.md'

# Fees
T1_FEE = get_harness_fee('mexc_market', 'tier1')
T2_FEE = get_harness_fee('mexc_market', 'tier2')
_stress = stress_multiplier('mexc_market', 2.0)
T1_STRESS = _stress['tier1']['total_per_side_bps'] / 10000.0
T2_STRESS = _stress['tier2']['total_per_side_bps'] / 10000.0

# 21 excluded coins (loss cluster analysis)
EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# Sweep values
DEV_THRESH_VALUES = [1.5, 1.8, 2.0, 2.2, 2.5, 3.0]


# -----------------------------------------------------------------------
# Data loading (reuse patterns from existing scripts)
# -----------------------------------------------------------------------
def load_candle_cache():
    cache_path = ROOT / 'data' / 'candle_cache_1h.json'
    if cache_path.exists():
        print('[Load] Reading %s...' % cache_path.name)
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        print('[Load] %d coins loaded (merged cache)' % len(coins_data))
        return coins_data

    parts_base = ROOT / 'data' / 'cache_parts_hf' / '1h'
    if not parts_base.exists():
        print('[ERROR] No 1H candle cache found.')
        sys.exit(1)

    print('[Load] Merged cache not found, loading from per-coin parts...')
    manifest_path = ROOT / 'data' / 'manifest_hf_1h.json'
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
        print('[ERROR] No coins loaded from part files.')
        sys.exit(1)
    print('[Load] %d coins loaded (from part files)' % len(coins_data))
    return coins_data


def load_universe_tiering():
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        print('[ERROR] Tiering not found: %s' % tiering_path)
        sys.exit(1)
    with open(tiering_path) as f:
        return json.load(f)


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


# -----------------------------------------------------------------------
# Backtest runner (per-tier with different fees, then merge)
# -----------------------------------------------------------------------
def run_combined(data, tier_coins, tier_indicators, market_context,
                 signal_fn, params, fee_t1, fee_t2):
    """Run H20 across both tiers with separate fees, return merged trade list."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}

    all_trades = []
    tier_fees = {'tier1': fee_t1, 'tier2': fee_t2}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, fee_t1)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=enriched_params,
            indicators=indicators,
            fee=fee,
            max_pos=1,
            cooldown_bars=4,
            cooldown_after_stop=8,
        )

        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    return all_trades


def run_combined_wf(data, tier_coins, tier_indicators, market_context,
                    signal_fn, params, fee_t1, fee_t2, n_folds=5):
    """Run walk-forward across both tiers. Returns {fold_idx: [trades]}."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}

    tier_fold_trades = {}
    tier_fees = {'tier1': fee_t1, 'tier2': fee_t2}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, fee_t1)
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
            cooldown_bars=4,
            cooldown_after_stop=8,
        )

        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)

    return tier_fold_trades


# -----------------------------------------------------------------------
# Metrics computation
# -----------------------------------------------------------------------
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


# -----------------------------------------------------------------------
# Max gap computation (uses exit_bar for correct gap between trades)
# -----------------------------------------------------------------------
def compute_max_gap_days(trades, total_bars):
    """Compute max gap between consecutive trade entries/exits in days (1H bars)."""
    if len(trades) < 2:
        return total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    # Gap from start to first entry
    mg = st[0].get('entry_bar', 50) - 50
    # Gaps between consecutive trades (exit of prev to entry of next)
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i - 1].get('exit_bar', 0)
        if g > mg:
            mg = g
    # Gap from last exit to end
    eg = total_bars - st[-1].get('exit_bar', 0)
    if eg > mg:
        mg = eg
    return mg / BARS_PER_DAY


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
    """Evaluate all 7 STRICT gates."""
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
# Run one dev_thresh variant (full pipeline)
# -----------------------------------------------------------------------
def run_one_variant(dev_thresh, data, tier_coins, tier_indicators,
                    market_context, total_bars):
    """Run full evaluation for one dev_thresh value. Returns result dict."""
    params = {
        'dev_thresh': dev_thresh,
        'tp_pct': 8,
        'sl_pct': 5,
        'time_limit': 10,
        'label': 'dev=%.1f' % dev_thresh,
    }
    signal_fn = signal_h20_vwap_deviation
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0

    print('\n--- dev_thresh=%.1f ---' % dev_thresh)

    # Pass 1: Baseline
    t0 = time.time()
    trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        signal_fn, params, T1_FEE, T2_FEE,
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
    stress_trades = run_combined(
        data, tier_coins, tier_indicators, market_context,
        signal_fn, params, T1_STRESS, T2_STRESS,
    )
    stress_metrics = compute_metrics(
        stress_trades, initial_capital=2000.0, total_bars=total_bars,
    )
    print('  Stress 2x: PF=%.3f exp/w=$%.2f DD=%.1f%% (%.1fs)' % (
        stress_metrics['pf'], stress_metrics['exp_per_week'],
        stress_metrics['dd'], time.time() - t0))

    # Pass 3: Walk-forward 5-fold
    t0 = time.time()
    fold_trades = run_combined_wf(
        data, tier_coins, tier_indicators, market_context,
        signal_fn, params, T1_FEE, T2_FEE, n_folds=5,
    )
    folds_positive = 0
    fold_details = []
    for fold_idx in sorted(fold_trades.keys()):
        fold_pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
        fold_n = len(fold_trades[fold_idx])
        is_positive = fold_pnl > 0
        if is_positive:
            folds_positive += 1
        # Per-coin breakdown
        fold_coin_pnl = {}
        for t in fold_trades[fold_idx]:
            pair = t['pair']
            fold_coin_pnl[pair] = fold_coin_pnl.get(pair, 0.0) + t['pnl']
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

    # Exit reason breakdown
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
        'dev_thresh': dev_thresh,
        'label': params['label'],
        'params': {k: v for k, v in params.items() if k != 'label'},
        'baseline_metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'wr': stress_metrics['wr'],
            'dd': stress_metrics['dd'],
            'exp_per_week': stress_metrics['exp_per_week'],
        },
        'tier_trade_split': {
            'tier1_trades': len(t1_trades),
            'tier2_trades': len(t2_trades),
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'top1_fold_conc': round(top1_fold_conc, 4),
        'max_gap_days': round(max_gap_days, 2),
        'gates': gates,
        'gates_pass': n_pass,
        'gates_total': 7,
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
# Main
# -----------------------------------------------------------------------
def main():
    print('=' * 72)
    print('  C8-A: Dev Threshold Sensitivity Sweep (295 coins)')
    print('  dev_thresh = %s' % DEV_THRESH_VALUES)
    print('  Fixed: tp_pct=8, sl_pct=5, time_limit=10')
    print('=' * 72)
    print('Started: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    t_start = time.time()

    # Commit hash
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # Fees
    print('[Costs] Baseline: T1=%.1fbps T2=%.1fbps' % (T1_FEE * 10000, T2_FEE * 10000))
    print('[Costs] Stress 2x: T1=%.1fbps T2=%.1fbps' % (T1_STRESS * 10000, T2_STRESS * 10000))

    # Load data
    data = load_candle_cache()
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # Apply 295-coin exclusion
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    n_excluded = (len(tier_coins_full['tier1']) + len(tier_coins_full['tier2'])) - n_total
    print('[Universe] 295-coin: T1=%d T2=%d Total=%d (excluded %d)' % (
        n_t1, n_t2, n_total, n_excluded))

    # Precompute indicators
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print('  %s: %d coins in %.1fs' % (tier_name, len(coins), time.time() - t_ind))

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print('  %s: VWAP %.0f%% (%d/%d)' % (
                tier_name, cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

    # Market context
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
    print('[Data] total_bars=%d, total_weeks=%.1f' % (total_bars, total_weeks))

    # ================================================================
    # Run sweep
    # ================================================================
    results = []
    for dev_thresh in DEV_THRESH_VALUES:
        result = run_one_variant(
            dev_thresh, data, tier_coins, tier_indicators,
            market_context, total_bars,
        )
        results.append(result)

    elapsed = time.time() - t_start

    # ================================================================
    # Summary
    # ================================================================
    print('\n' + '=' * 72)
    print('  SWEEP SUMMARY')
    print('=' * 72)
    print('  %-8s %5s %6s %6s %8s %8s %6s %5s %5s %6s %s' % (
        'dev', 'Tr', 'PF', 'WR%', 'exp/wk', 'stress', 'DD%', 'WF', 'Gap', 'Conc%', 'Gates'))
    print('  ' + '-' * 80)
    for r in results:
        m = r['baseline_metrics']
        sm = r['stress_metrics']
        print('  %-8.1f %5d %6.3f %6.1f %8.2f %8.2f %6.1f %5s %5.1f %6.1f %d/7 %s' % (
            r['dev_thresh'], m['trades'], m['pf'], m['wr'],
            m['exp_per_week'], sm['exp_per_week'], m['dd'],
            r['gates']['G6']['value'], r['max_gap_days'],
            r['top1_fold_conc'] * 100, r['gates_pass'],
            ' '.join(gid for gid, g in sorted(r['gates'].items()) if not g['pass']) or 'ALL PASS',
        ))
    print('  Runtime: %.1fs' % elapsed)

    # ================================================================
    # Build JSON report
    # ================================================================
    report = {
        'run_header': {
            'task': 'part2_dev_thresh_sensitivity_sweep',
            'agent': 'C8-A',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'sweep_param': 'dev_thresh',
            'sweep_values': DEV_THRESH_VALUES,
            'fixed_params': {'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees': {
                'baseline': {
                    'tier1_bps': round(T1_FEE * 10000, 1),
                    'tier2_bps': round(T2_FEE * 10000, 1),
                },
                'stress_2x': {
                    'tier1_bps': round(T1_STRESS * 10000, 1),
                    'tier2_bps': round(T2_STRESS * 10000, 1),
                },
            },
            'universe': {
                'label': '295-coin (excl 21)',
                'tier1': n_t1,
                'tier2': n_t2,
                'total': n_total,
                'excluded': n_excluded,
                'excluded_coins': sorted(list(EXCLUDED_21)),
            },
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'gate_thresholds': {
            'G1': 'trades/week >= 10',
            'G2': 'max_gap <= 2.5d',
            'G3': 'exp/week > $0 (baseline)',
            'G4': 'exp/week > $0 (stress 2x)',
            'G5': 'DD <= 20%',
            'G6': 'WF >= 4/5',
            'G8': 'fold_conc < 35%',
        },
        'results': results,
        'sensitivity_analysis': {
            'optimal_dev_thresh': None,
            'monotonic_trades': True,
            'monotonic_edge': False,
            'observations': [],
        },
    }

    # Sensitivity analysis
    # Check monotonicity of trades (should decrease as dev_thresh increases)
    trades_seq = [r['baseline_metrics']['trades'] for r in results]
    for i in range(1, len(trades_seq)):
        if trades_seq[i] > trades_seq[i - 1]:
            report['sensitivity_analysis']['monotonic_trades'] = False
            break

    # Find which dev_thresh passes the most gates
    max_gates = max(r['gates_pass'] for r in results)
    best_dev = [r['dev_thresh'] for r in results if r['gates_pass'] == max_gates]
    # Among those with max gates, pick highest exp/week
    best_results = [r for r in results if r['gates_pass'] == max_gates]
    best_by_edge = max(best_results, key=lambda r: r['baseline_metrics']['exp_per_week'])
    report['sensitivity_analysis']['optimal_dev_thresh'] = best_by_edge['dev_thresh']
    report['sensitivity_analysis']['max_gates_pass'] = max_gates
    report['sensitivity_analysis']['best_candidates'] = best_dev

    # Observations
    obs = report['sensitivity_analysis']['observations']
    baseline_result = next(r for r in results if r['dev_thresh'] == 2.0)

    # Compare each to baseline
    for r in results:
        if r['dev_thresh'] == 2.0:
            obs.append('dev=2.0 (baseline): %d trades, %d/7 gates' % (
                r['baseline_metrics']['trades'], r['gates_pass']))
            continue
        delta_trades = r['baseline_metrics']['trades'] - baseline_result['baseline_metrics']['trades']
        delta_exp = r['baseline_metrics']['exp_per_week'] - baseline_result['baseline_metrics']['exp_per_week']
        delta_gates = r['gates_pass'] - baseline_result['gates_pass']
        obs.append('dev=%.1f vs 2.0: %+d trades, $%+.2f exp/wk, %+d gates (%d/7)' % (
            r['dev_thresh'], delta_trades, delta_exp, delta_gates, r['gates_pass']))

    json_path = ROOT / 'reports' / 'hf' / REPORT_JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ================================================================
    # Build Markdown report
    # ================================================================
    md = []
    md.append('# C8-A: Dev Threshold Sensitivity Sweep (295 coins)')
    md.append('')
    md.append('**Agent**: C8-A')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Commit**: %s' % commit)
    md.append('**Signal**: H20 VWAP_DEVIATION')
    md.append('**Sweep**: dev_thresh = %s' % DEV_THRESH_VALUES)
    md.append('**Fixed**: tp_pct=8, sl_pct=5, time_limit=10')
    md.append('**Universe**: 295 coins (T1=%d, T2=%d, excl %d)' % (n_t1, n_t2, n_excluded))
    md.append('**Fees**: T1=%.1fbps, T2=%.1fbps (stress 2x: T1=%.1fbps, T2=%.1fbps)' % (
        T1_FEE * 10000, T2_FEE * 10000, T1_STRESS * 10000, T2_STRESS * 10000))
    md.append('**Runtime**: %.1fs' % elapsed)
    md.append('')

    # Key finding
    md.append('## Key Finding')
    md.append('')
    md.append('**Optimal dev_thresh**: %.1f (passes %d/7 gates)' % (
        report['sensitivity_analysis']['optimal_dev_thresh'],
        report['sensitivity_analysis']['max_gates_pass']))
    md.append('')
    for o in report['sensitivity_analysis']['observations']:
        md.append('- %s' % o)
    md.append('')

    # Main comparison table
    md.append('## Sweep Results')
    md.append('')
    md.append('| dev | Trades | T1/T2 | PF | WR% | Exp/Wk | DD% | WF | Gap(d) | Conc% | Gates |')
    md.append('|-----|--------|-------|----|----|--------|-----|----|----|------|-------|')
    for r in results:
        m = r['baseline_metrics']
        is_baseline = ' *' if r['dev_thresh'] == 2.0 else ''
        md.append('| %.1f%s | %d | %d/%d | %.3f | %.1f | $%.2f | %.1f | %s | %.1f | %.1f | %d/7 |' % (
            r['dev_thresh'], is_baseline, m['trades'],
            r['tier_trade_split']['tier1_trades'], r['tier_trade_split']['tier2_trades'],
            m['pf'], m['wr'], m['exp_per_week'], m['dd'],
            r['gates']['G6']['value'], r['max_gap_days'],
            r['top1_fold_conc'] * 100, r['gates_pass']))
    md.append('')
    md.append('\\* = current baseline')
    md.append('')

    # Gate detail table
    md.append('## Gate Pass/Fail Matrix')
    md.append('')
    header = '| Gate | Threshold |'
    sep = '|------|-----------|'
    for dv in DEV_THRESH_VALUES:
        header += ' %.1f |' % dv
        sep += '-----|'
    md.append(header)
    md.append(sep)
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        row = '| %s | %s |' % (gid, results[0]['gates'][gid]['threshold'])
        for r in results:
            g = r['gates'][gid]
            if g['pass']:
                row += ' PASS |'
            else:
                row += ' **FAIL** |'
        md.append(row)
    # Total row
    row = '| **Total** | |'
    for r in results:
        row += ' **%d/7** |' % r['gates_pass']
    md.append(row)
    md.append('')

    # Gate values table
    md.append('## Gate Values')
    md.append('')
    header = '| Gate | Metric |'
    sep = '|------|--------|'
    for dv in DEV_THRESH_VALUES:
        header += ' %.1f |' % dv
        sep += '-----|'
    md.append(header)
    md.append(sep)
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        row = '| %s | %s |' % (gid, results[0]['gates'][gid]['name'])
        for r in results:
            row += ' %s |' % r['gates'][gid]['value']
        md.append(row)
    md.append('')

    # Stress test table
    md.append('## Stress Test (2x fees)')
    md.append('')
    md.append('| dev | Trades | PF | WR% | Exp/Wk | DD% |')
    md.append('|-----|--------|----|----|--------|-----|')
    for r in results:
        sm = r['stress_metrics']
        md.append('| %.1f | %d | %.3f | %.1f | $%.2f | %.1f |' % (
            r['dev_thresh'], sm['trades'], sm['pf'], sm['wr'],
            sm['exp_per_week'], sm['dd']))
    md.append('')

    # Walk-forward detail
    md.append('## Walk-Forward Detail (5-fold)')
    md.append('')
    for r in results:
        md.append('### dev_thresh=%.1f (%d/5 positive)' % (
            r['dev_thresh'], r['wf_folds_positive']))
        md.append('')
        md.append('| Fold | Trades | P&L | Status | Top Coin | Top Coin P&L |')
        md.append('|------|--------|-----|--------|----------|-------------|')
        for fd in r['wf_fold_details']:
            status = 'PASS' if fd['positive'] else '**FAIL**'
            md.append('| F%d | %d | $%.0f | %s | %s | $%.0f |' % (
                fd['fold'], fd['trades'], fd['pnl'], status,
                fd.get('top_coin', 'N/A'), fd.get('top_coin_pnl', 0)))
        md.append('')

    # Exit breakdown per dev_thresh
    md.append('## Exit Reason Breakdown')
    md.append('')
    md.append('| dev | Reason | Count | P&L | WR% |')
    md.append('|-----|--------|-------|-----|-----|')
    for r in results:
        for reason, v in r['exit_breakdown'].items():
            md.append('| %.1f | %s | %d | $%.2f | %.1f%% |' % (
                r['dev_thresh'], reason, v['count'], v['pnl'], v['wr']))
    md.append('')

    # Sensitivity curve insight
    md.append('## Sensitivity Curve')
    md.append('')
    md.append('```')
    md.append('dev_thresh  trades  exp/wk   gates')
    for r in results:
        m = r['baseline_metrics']
        bar = '#' * int(max(0, m['exp_per_week'] / 5))
        md.append('  %.1f       %4d   $%6.2f  %d/7  %s' % (
            r['dev_thresh'], m['trades'], m['exp_per_week'], r['gates_pass'], bar))
    md.append('```')
    md.append('')

    # Conclusion
    md.append('## Conclusion')
    md.append('')
    optimal = report['sensitivity_analysis']['optimal_dev_thresh']
    baseline_gates = baseline_result['gates_pass']
    optimal_result = next(r for r in results if r['dev_thresh'] == optimal)

    if optimal == 2.0:
        md.append('dev_thresh=2.0 (baseline) remains optimal. No improvement found.')
    elif optimal_result['gates_pass'] > baseline_gates:
        md.append('dev_thresh=%.1f improves over baseline: %d/7 vs %d/7 gates.' % (
            optimal, optimal_result['gates_pass'], baseline_gates))
        md.append('Consider updating baseline to dev_thresh=%.1f.' % optimal)
    else:
        md.append('dev_thresh=%.1f ties with baseline at %d/7 gates but has better edge.' % (
            optimal, optimal_result['gates_pass']))
    md.append('')

    # Is there a clear winner?
    pass_counts = [r['gates_pass'] for r in results]
    if max(pass_counts) >= 6:
        winners = [r for r in results if r['gates_pass'] >= 6]
        md.append('**GO candidates** (6+ gates): %s' % ', '.join(
            'dev=%.1f (%d/7)' % (r['dev_thresh'], r['gates_pass']) for r in winners))
    elif max(pass_counts) >= 4:
        md.append('**CONDITIONAL** range: no variant passes 6+ gates.')
    else:
        md.append('**NO-GO**: no variant passes 4+ gates.')
    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_dev_thresh_sweep_001.py')
    md.append('at %s*' % datetime.now().strftime('%Y-%m-%d %H:%M'))

    md_path = ROOT / 'reports' / 'hf' / REPORT_MD
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    print('\n' + '=' * 72)
    print('  COMPLETE: %d dev_thresh values tested' % len(DEV_THRESH_VALUES))
    print('  Optimal: dev_thresh=%.1f (%d/7 gates)' % (
        report['sensitivity_analysis']['optimal_dev_thresh'],
        report['sensitivity_analysis']['max_gates_pass']))
    print('  Runtime: %.1fs' % elapsed)
    print('=' * 72)


if __name__ == '__main__':
    main()
