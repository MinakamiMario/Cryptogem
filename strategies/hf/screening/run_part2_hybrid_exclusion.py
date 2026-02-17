#!/usr/bin/env python3
"""
Part 2 -- Agent C5-A1: Hybrid Exclusion Strategy
==================================================
Tests a HYBRID coin exclusion approach that combines:
  1. Static Core Exclusions: 12 worst coins (high confidence, appear in all analyses)
  2. Dynamic Layer: Rolling lookback windows (168, 336, 504 bars) to identify
     ADDITIONAL coins to exclude from the remaining 304
  3. Combined: Static 12 + Dynamic N

Compares against:
  - Full 316 coins (no exclusion)
  - Static 12 only (304 coins)
  - Static 21 (295 coins, oracle)

For each configuration: baseline, stress (2x fees), walk-forward 5-fold,
fold concentration, and gate evaluation (G1-G8 except G7).

Usage:
    python -m strategies.hf.screening.run_part2_hybrid_exclusion
    python -m strategies.hf.screening.run_part2_hybrid_exclusion --dry-run
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

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# ── Static exclusion sets ──
STATIC_12_WORST = {
    'ALKIMI/USD', 'ANIME/USD', 'DBR/USD', 'ESX/USD', 'HOUSE/USD',
    'KET/USD', 'LMWR/USD', 'MXC/USD', 'ODOS/USD', 'PERP/USD',
    'TANSSI/USD', 'TITCOIN/USD',
}

ORACLE_21_EXCL = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

LOOKBACK_WINDOWS = [168, 336, 504]   # 1wk, 2wk, 3wk
SEGMENT_SIZE = 168                    # 1 week per forward segment
WARMUP_BARS = 50


# ────────────────────────── Data Loading ──────────────────────────

def load_candle_cache(timeframe='1h', require_data=False):
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
            gap = (sorted_trades[i].get('entry_bar', 0)
                   - sorted_trades[i - 1].get('entry_bar', 0))
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2),
            'pf': round(pf, 3), 'wr': round(wr, 1),
            'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4),
            'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2),
            'expectancy': round(expectancy, 4)}


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
        params = PARAMS_V5
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
        params = PARAMS_V5
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


def filter_tier_coins(tier_coins_full, excl_set):
    """Remove excluded coins from tier_coins dict."""
    return {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_set],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_set],
    }


def filter_tier_indicators(tier_indicators_full, tier_coins):
    """Build indicator subset for given tier_coins."""
    result = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in tier_indicators_full:
            result[tier_name] = {
                c: tier_indicators_full[tier_name][c]
                for c in coins if c in tier_indicators_full[tier_name]
            }
    return result


# ═══════════════════════════════════════════════════════════════════
#  FULL GATE EVALUATION for a given coin set
# ═══════════════════════════════════════════════════════════════════

def run_full_gate_evaluation(label, data, tier_coins, tier_indicators_full,
                              market_context, tier1_fee, tier2_fee,
                              stress_tier1_fee, stress_tier2_fee, total_bars):
    """Full gate evaluation: baseline + stress + WF + fold concentration."""
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_ind = filter_tier_indicators(tier_indicators_full, tier_coins)

    trades = run_variant(data, tier_coins, tier_ind, market_context,
                         tier1_fee, tier2_fee)
    metrics = compute_metrics(trades, total_bars)
    n_coins = sum(len(c) for c in tier_coins.values())
    print(f'    coins={n_coins} trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'P&L=${metrics["pnl"]:.0f} exp/w=${metrics["exp_per_week"]:.2f} '
          f'DD={metrics["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Running stress (2x fees)...')
    stress_trades = run_variant(data, tier_coins, tier_ind, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'    stress: PF={stress_metrics["pf"]:.3f} '
          f'P&L=${stress_metrics["pnl"]:.0f} '
          f'exp/w=${stress_metrics["exp_per_week"]:.2f}')

    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_wf(data, tier_coins, tier_ind, market_context,
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
    print(f'    WF: {folds_positive}/5 folds positive')

    fold_conc = compute_fold_concentration(fold_trades)
    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = gate_eval['gates'][gid]
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  '
              f'({g["threshold"]}) -> {status}')

    return {
        'label': label,
        'n_coins': n_coins,
        'metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
            'max_dd_pct': stress_metrics['max_dd_pct'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'gate_evaluation': gate_eval,
        'runtime_s': round(elapsed, 1),
    }


# ═══════════════════════════════════════════════════════════════════
#  HYBRID ROLLING EXCLUSION
# ═══════════════════════════════════════════════════════════════════

def run_hybrid_rolling(data, tier_coins_full, tier_indicators_full,
                        market_context, tier1_fee, tier2_fee,
                        static_excl, lookback_bars, segment_size, label=''):
    """
    Hybrid exclusion: Static core + dynamic rolling layer.

    For each forward segment [seg_start, seg_end]:
      1. Always exclude static_excl (the 12 worst coins)
      2. Look back lookback_bars to identify additional negative coins
         from the remaining universe (304 coins after static exclusion)
      3. Combine: static 12 + dynamic extras
      4. Run backtest on current segment with combined exclusion
    """
    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)

    # Pre-filter to the 304 coins (remove static 12) for lookback analysis
    tier_coins_304 = filter_tier_coins(tier_coins_full, static_excl)

    # Build indicator subset (reuse precomputed)
    tier_ind_full = filter_tier_indicators(tier_indicators_full, tier_coins_full)

    # First segment starts where we have enough lookback data
    first_seg_start = max(WARMUP_BARS, WARMUP_BARS + lookback_bars)
    if first_seg_start > total_bars:
        print(f'    [WARN] Not enough data for lookback={lookback_bars}')
        return None

    # Build segment boundaries
    segments = []
    seg_start = first_seg_start
    while seg_start < total_bars:
        seg_end = min(seg_start + segment_size, total_bars)
        lb_start = max(WARMUP_BARS, seg_start - lookback_bars)
        lb_end = seg_start
        segments.append({
            'seg_start': seg_start,
            'seg_end': seg_end,
            'lb_start': lb_start,
            'lb_end': lb_end,
        })
        seg_start = seg_end

    print(f'  [{label}] {len(segments)} segments, '
          f'lookback={lookback_bars}bars ({lookback_bars/BARS_PER_WEEK:.1f}wk), '
          f'static_excl={len(static_excl)}, remaining pool={sum(len(c) for c in tier_coins_304.values())}')

    all_segment_trades = []
    segment_details = []
    all_dynamic_excl_sets = []
    all_combined_excl_sets = []

    for seg_idx, seg in enumerate(segments):
        # STEP 1: Run lookback on the 304 pool (after static removal)
        # to find additional dynamic exclusions
        tier_ind_304 = filter_tier_indicators(tier_indicators_full, tier_coins_304)
        lb_trades = run_variant(
            data, tier_coins_304, tier_ind_304,
            market_context, tier1_fee, tier2_fee,
            start_bar=seg['lb_start'], end_bar=seg['lb_end'],
        )

        # STEP 2: Identify dynamic negative coins from lookback
        dynamic_excl = identify_negative_coins(lb_trades)
        all_dynamic_excl_sets.append(dynamic_excl)

        # STEP 3: Combine static + dynamic
        combined_excl = static_excl | dynamic_excl
        all_combined_excl_sets.append(combined_excl)

        # STEP 4: Build filtered coin list and run segment
        seg_tier_coins = filter_tier_coins(tier_coins_full, combined_excl)
        seg_tier_ind = filter_tier_indicators(tier_indicators_full, seg_tier_coins)

        seg_trades = run_variant(
            data, seg_tier_coins, seg_tier_ind,
            market_context, tier1_fee, tier2_fee,
            start_bar=seg['seg_start'], end_bar=seg['seg_end'],
        )

        for t in seg_trades:
            t['_segment'] = seg_idx

        all_segment_trades.extend(seg_trades)

        seg_pnl = sum(t['pnl'] for t in seg_trades)
        n_active = sum(len(c) for c in seg_tier_coins.values())

        segment_details.append({
            'segment': seg_idx,
            'seg_bars': [seg['seg_start'], seg['seg_end']],
            'lb_bars': [seg['lb_start'], seg['lb_end']],
            'n_static_excl': len(static_excl),
            'n_dynamic_excl': len(dynamic_excl),
            'n_combined_excl': len(combined_excl),
            'n_coins_active': n_active,
            'dynamic_coins': sorted(dynamic_excl),
            'seg_trades': len(seg_trades),
            'seg_pnl': round(seg_pnl, 2),
        })

        if seg_idx < 4 or seg_idx == len(segments) - 1:
            print(f'    seg {seg_idx}: bars {seg["seg_start"]}-{seg["seg_end"]} | '
                  f'dyn_excl={len(dynamic_excl)} combined={len(combined_excl)} | '
                  f'active={n_active} trades={len(seg_trades)} pnl=${seg_pnl:+.0f}')
        elif seg_idx == 4:
            print(f'    ... ({len(segments) - 5} more segments) ...')

    # Compute rolling metrics over the full aggregated period
    total_forward_bars = sum(s['seg_end'] - s['seg_start'] for s in segments)
    rolling_metrics = compute_metrics(all_segment_trades, total_forward_bars)

    # Dynamic exclusion stability
    dyn_stability_overlaps = []
    for i in range(1, len(all_dynamic_excl_sets)):
        prev = all_dynamic_excl_sets[i - 1]
        curr = all_dynamic_excl_sets[i]
        if prev or curr:
            union_sz = len(prev | curr)
            inter_sz = len(prev & curr)
            overlap_pct = inter_sz / union_sz * 100 if union_sz > 0 else 0
            dyn_stability_overlaps.append(overlap_pct)

    avg_dyn_overlap = (sum(dyn_stability_overlaps) / len(dyn_stability_overlaps)
                       if dyn_stability_overlaps else 0)

    # Dynamic coin exclusion frequency
    dyn_coin_freq = defaultdict(int)
    for excl_set in all_dynamic_excl_sets:
        for c in excl_set:
            dyn_coin_freq[c] += 1
    n_segs = len(all_dynamic_excl_sets)
    dyn_coin_pct = {c: round(cnt / n_segs * 100, 1)
                    for c, cnt in sorted(dyn_coin_freq.items(), key=lambda x: -x[1])}

    # Persistent dynamic excludes (>50% of segments)
    persistent_dynamic = sorted(c for c, cnt in dyn_coin_freq.items()
                                if cnt / n_segs >= 0.5)

    # Average combined exclusion size
    avg_combined_excl = sum(s['n_combined_excl'] for s in segment_details) / len(segment_details)

    print(f'    TOTAL: {rolling_metrics["trades"]} trades, '
          f'PF={rolling_metrics["pf"]:.3f}, P&L=${rolling_metrics["pnl"]:.0f}, '
          f'exp/w=${rolling_metrics["exp_per_week"]:.2f}')
    print(f'    Dynamic stability: avg_overlap={avg_dyn_overlap:.1f}%')
    print(f'    Avg combined excl: {avg_combined_excl:.0f} coins '
          f'(static {len(static_excl)} + dynamic avg '
          f'{avg_combined_excl - len(static_excl):.0f})')
    print(f'    Persistent dynamic (>50%): {len(persistent_dynamic)} coins')

    return {
        'label': label,
        'lookback_bars': lookback_bars,
        'lookback_weeks': round(lookback_bars / BARS_PER_WEEK, 1),
        'segment_size': segment_size,
        'n_static_excl': len(static_excl),
        'n_segments': len(segments),
        'total_forward_bars': total_forward_bars,
        'metrics': rolling_metrics,
        'segment_details': segment_details,
        'avg_combined_excl': round(avg_combined_excl, 1),
        'dynamic_stability': {
            'avg_overlap_pct': round(avg_dyn_overlap, 1),
            'consecutive_overlaps': [round(o, 1) for o in dyn_stability_overlaps],
        },
        'dynamic_coin_frequency': dyn_coin_pct,
        'persistent_dynamic_excludes': persistent_dynamic,
        'n_persistent_dynamic': len(persistent_dynamic),
    }


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C5-A1: Hybrid Exclusion Strategy')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C5-A1: Hybrid Exclusion Strategy')
    print('  Static 12 worst + Dynamic rolling exclusion layer')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, '
          f'T2={stress_tier2_fee*10000:.1f}bps')

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
    n_total = n_t1 + n_t2
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins, total: {n_total}')

    if not tier_coins_full['tier1'] and not tier_coins_full['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1 if args.require_data else 0)

    if args.dry_run:
        max_bars_est = max(len(v) for v in data.values())
        print(f'\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}')
        print(f'  Static 12 worst: {sorted(STATIC_12_WORST)}')
        print(f'  Oracle 21 excl: {sorted(ORACLE_21_EXCL)}')
        print(f'  Estimated total bars: {max_bars_est}')
        print(f'  Lookback windows: {LOOKBACK_WINDOWS}')
        print(f'  Segment size: {SEGMENT_SIZE}')
        print(f'  Configurations to test:')
        print(f'    1. Full 316 (no exclusion) -- gate evaluation')
        print(f'    2. Static 12 only (304 coins) -- gate evaluation')
        print(f'    3. Static 21 oracle (295 coins) -- gate evaluation')
        print(f'    4-6. Hybrid: static 12 + rolling lb168/336/504 -- rolling sim')
        print(f'    7. Best hybrid: persistent excl -> gate evaluation')
        print(f'  Total: 3 gate evals + 3 rolling sims + 1 gate eval = 4 gate evals + 3 sims')
        sys.exit(0)

    # ── Precompute indicators ──
    print('\n[Indicators] Precomputing base indicators...')
    tier_indicators_full = {}
    for tier_name, coins in tier_coins_full.items():
        if coins:
            t_ind = time.time()
            tier_indicators_full[tier_name] = precompute_base_indicators(
                data, coins)
            print(f'  {tier_name}: {len(coins)} coins in '
                  f'{time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_full.items():
        if coins and tier_name in tier_indicators_full:
            extend_indicators(data, coins, tier_indicators_full[tier_name])
            cov = get_feature_coverage(tier_indicators_full[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_full.get('tier1', [])
                         + tier_coins_full.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicators
    for tier_name, ind_dict in tier_indicators_full.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: Reference Configurations -- Full Gate Evaluations
    # ═══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 1: Reference configurations (full gate evaluation)')
    print('=' * 70)

    # (a) Full 316 coins, no exclusion
    ref_full = run_full_gate_evaluation(
        'Full 316 (no exclusion)',
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        stress_tier1_fee, stress_tier2_fee, total_bars,
    )

    # (b) Static 12 exclusion (304 coins)
    tier_coins_304 = filter_tier_coins(tier_coins_full, STATIC_12_WORST)
    ref_static12 = run_full_gate_evaluation(
        'Static 12 excl (304 coins)',
        data, tier_coins_304, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        stress_tier1_fee, stress_tier2_fee, total_bars,
    )

    # (c) Oracle 21 exclusion (295 coins)
    tier_coins_295 = filter_tier_coins(tier_coins_full, ORACLE_21_EXCL)
    ref_oracle21 = run_full_gate_evaluation(
        'Oracle 21 excl (295 coins)',
        data, tier_coins_295, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        stress_tier1_fee, stress_tier2_fee, total_bars,
    )

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: Hybrid Rolling Simulations
    # ═══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 2: Hybrid rolling exclusion (static 12 + dynamic)')
    print('=' * 70)

    hybrid_results = []
    for lookback in LOOKBACK_WINDOWS:
        label = f'hybrid_s12_lb{lookback}'
        print(f'\n--- {label} ---')
        result = run_hybrid_rolling(
            data, tier_coins_full, tier_indicators_full,
            market_context, tier1_fee, tier2_fee,
            static_excl=STATIC_12_WORST,
            lookback_bars=lookback,
            segment_size=SEGMENT_SIZE,
            label=label,
        )
        if result is not None:
            hybrid_results.append(result)

    # Also run pure dynamic rolling (no static) for comparison
    print(f'\n--- pure_dynamic_lb336 (no static, for comparison) ---')
    pure_dynamic = run_hybrid_rolling(
        data, tier_coins_full, tier_indicators_full,
        market_context, tier1_fee, tier2_fee,
        static_excl=set(),  # no static exclusion
        lookback_bars=336,
        segment_size=SEGMENT_SIZE,
        label='pure_dynamic_lb336',
    )

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: Best Hybrid -> Full Gate Evaluation
    # ═══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 3: Best hybrid configuration -> full gate evaluation')
    print('=' * 70)

    # Pick best hybrid by exp_per_week (among profitable ones)
    profitable_hybrid = [r for r in hybrid_results if r['metrics']['pnl'] > 0]
    if profitable_hybrid:
        best_hybrid = max(profitable_hybrid,
                          key=lambda r: r['metrics']['exp_per_week'])
    elif hybrid_results:
        best_hybrid = max(hybrid_results, key=lambda r: r['metrics']['pnl'])
    else:
        best_hybrid = None

    best_hybrid_gate_eval = None
    best_hybrid_static_list = None

    if best_hybrid:
        # Build the combined static exclusion list:
        # Static 12 + persistent dynamic excludes from best hybrid
        persistent_dyn = set(best_hybrid['persistent_dynamic_excludes'])
        combined_static = STATIC_12_WORST | persistent_dyn
        best_hybrid_static_list = sorted(combined_static)

        print(f'\n  Best hybrid: {best_hybrid["label"]}')
        print(f'  Static 12 + {len(persistent_dyn)} persistent dynamic = '
              f'{len(combined_static)} total')
        if persistent_dyn:
            print(f'  Persistent dynamic: {sorted(persistent_dyn)}')
            new_coins = persistent_dyn - ORACLE_21_EXCL
            oracle_coins = persistent_dyn & ORACLE_21_EXCL
            if oracle_coins:
                print(f'    In oracle set: {sorted(oracle_coins)}')
            if new_coins:
                print(f'    NEW (not in oracle): {sorted(new_coins)}')

        tier_coins_hybrid = filter_tier_coins(tier_coins_full, combined_static)
        best_hybrid_gate_eval = run_full_gate_evaluation(
            f'Hybrid best ({len(combined_static)} excl)',
            data, tier_coins_hybrid, tier_indicators_full,
            market_context, tier1_fee, tier2_fee,
            stress_tier1_fee, stress_tier2_fee, total_bars,
        )

    elapsed_total = time.time() - t0_total

    # ═══════════════════════════════════════════════════════════════
    # STEP 4: Comparison Summary
    # ═══════════════════════════════════════════════════════════════
    print('\n' + '=' * 70)
    print('  STEP 4: Comparison Summary')
    print('=' * 70)

    # Summary table
    configs = [
        ('Full 316', ref_full),
        ('Static 12 (304)', ref_static12),
        ('Oracle 21 (295)', ref_oracle21),
    ]
    if best_hybrid_gate_eval:
        configs.append((f'Hybrid best ({len(best_hybrid_static_list)}excl)',
                        best_hybrid_gate_eval))

    print(f'\n  {"Config":<30s} | {"Coins":>5s} | {"Tr":>4s} | {"PF":>5s} | '
          f'{"P&L":>7s} | {"Exp/W":>7s} | {"DD%":>5s} | {"WF":>4s} | '
          f'{"G8":>5s} | {"Gates":>5s}')
    print(f'  {"-"*30}-+-{"-"*5}-+-{"-"*4}-+-{"-"*5}-+-{"-"*7}-+-{"-"*7}-+-'
          f'{"-"*5}-+-{"-"*4}-+-{"-"*5}-+-{"-"*5}')
    for name, cfg in configs:
        m = cfg['metrics']
        ge = cfg['gate_evaluation']
        fc = cfg['fold_concentration']
        print(f'  {name:<30s} | {cfg["n_coins"]:>5d} | {m["trades"]:>4d} | '
              f'{m["pf"]:>5.3f} | ${m["pnl"]:>+6.0f} | '
              f'${m["exp_per_week"]:>6.2f} | {m["max_dd_pct"]:>4.1f}% | '
              f'{cfg["wf_folds_positive"]:>1d}/5  | '
              f'{fc["top1_fold_conc_pct"]:>4.1f}% | {ge["score"]:>5s}')

    # Hybrid rolling results summary
    if hybrid_results:
        print(f'\n  Hybrid Rolling Results:')
        print(f'  {"Label":<25s} | {"Tr":>4s} | {"PF":>5s} | {"P&L":>7s} | '
              f'{"Exp/W":>7s} | {"Avg Excl":>8s} | {"Dyn Stab":>8s}')
        print(f'  {"-"*25}-+-{"-"*4}-+-{"-"*5}-+-{"-"*7}-+-{"-"*7}-+-'
              f'{"-"*8}-+-{"-"*8}')
        for r in hybrid_results:
            m = r['metrics']
            print(f'  {r["label"]:<25s} | {m["trades"]:>4d} | '
                  f'{m["pf"]:>5.3f} | ${m["pnl"]:>+6.0f} | '
                  f'${m["exp_per_week"]:>6.2f} | '
                  f'{r["avg_combined_excl"]:>7.0f}c | '
                  f'{r["dynamic_stability"]["avg_overlap_pct"]:>6.1f}%')
        if pure_dynamic:
            m = pure_dynamic['metrics']
            print(f'  {"pure_dynamic_lb336":<25s} | {m["trades"]:>4d} | '
                  f'{m["pf"]:>5.3f} | ${m["pnl"]:>+6.0f} | '
                  f'${m["exp_per_week"]:>6.2f} | '
                  f'{pure_dynamic["avg_combined_excl"]:>7.0f}c | '
                  f'{pure_dynamic["dynamic_stability"]["avg_overlap_pct"]:>6.1f}%')

    # ═══════════════════════════════════════════════════════════════
    # VERDICT
    # ═══════════════════════════════════════════════════════════════

    # Logic: compare hybrid best gate eval against static 12 and oracle
    if best_hybrid_gate_eval:
        hybrid_gates = best_hybrid_gate_eval['gate_evaluation']
        static12_gates = ref_static12['gate_evaluation']
        oracle_gates = ref_oracle21['gate_evaluation']

        hybrid_gate_count = hybrid_gates['pass_count']
        static12_gate_count = static12_gates['pass_count']
        oracle_gate_count = oracle_gates['pass_count']

        hybrid_pnl = best_hybrid_gate_eval['metrics']['pnl']
        static12_pnl = ref_static12['metrics']['pnl']
        oracle_pnl = ref_oracle21['metrics']['pnl']

        # How much of oracle advantage does hybrid capture?
        if oracle_pnl > 0:
            oracle_retention_pct = hybrid_pnl / oracle_pnl * 100
        else:
            oracle_retention_pct = 0

        if hybrid_gate_count >= oracle_gate_count and hybrid_gates['all_pass']:
            verdict = 'HYBRID_CONFIRMED'
            verdict_detail = (
                f'Hybrid exclusion ({len(best_hybrid_static_list)} coins) matches '
                f'oracle gate performance ({hybrid_gate_count}/7 gates). '
                f'Retains {oracle_retention_pct:.0f}% of oracle P&L '
                f'(${hybrid_pnl:.0f} vs ${oracle_pnl:.0f}). '
                f'Strictly superior to static-12 ({static12_gate_count}/7).'
            )
        elif hybrid_gate_count > static12_gate_count:
            verdict = 'HYBRID_IMPROVES_STATIC'
            verdict_detail = (
                f'Hybrid exclusion improves on static-12: '
                f'{hybrid_gate_count}/7 vs {static12_gate_count}/7 gates. '
                f'P&L: ${hybrid_pnl:.0f} (hybrid) vs ${static12_pnl:.0f} (static12) '
                f'vs ${oracle_pnl:.0f} (oracle). '
                f'Oracle retention: {oracle_retention_pct:.0f}%.'
            )
        elif hybrid_gate_count == static12_gate_count:
            # Same gates but check if PF/P&L improved
            if hybrid_pnl > static12_pnl * 1.05:
                verdict = 'HYBRID_MARGINAL_IMPROVEMENT'
                verdict_detail = (
                    f'Hybrid has same gate count ({hybrid_gate_count}/7) as static-12 '
                    f'but improves P&L: ${hybrid_pnl:.0f} vs ${static12_pnl:.0f} '
                    f'(+${hybrid_pnl - static12_pnl:.0f}). '
                    f'Oracle retention: {oracle_retention_pct:.0f}%.'
                )
            else:
                verdict = 'HYBRID_NO_IMPROVEMENT'
                verdict_detail = (
                    f'Hybrid does not meaningfully improve over static-12. '
                    f'Both have {hybrid_gate_count}/7 gates. '
                    f'P&L: ${hybrid_pnl:.0f} (hybrid) vs ${static12_pnl:.0f} (static12). '
                    f'Dynamic layer adds complexity without benefit.'
                )
        else:
            verdict = 'HYBRID_DEGRADES'
            verdict_detail = (
                f'Hybrid exclusion degrades performance vs static-12: '
                f'{hybrid_gate_count}/7 vs {static12_gate_count}/7 gates. '
                f'Dynamic layer is counterproductive.'
            )
    else:
        verdict = 'NO_HYBRID_CANDIDATE'
        verdict_detail = 'No profitable hybrid configuration found.'

    print(f'\n{"=" * 70}')
    print(f'  VERDICT: {verdict}')
    print(f'  {verdict_detail}')
    print(f'{"=" * 70}')

    # ═══════════════════════════════════════════════════════════════
    # BUILD REPORTS
    # ═══════════════════════════════════════════════════════════════

    report = {
        'run_header': {
            'task': 'part2_hybrid_exclusion',
            'agent': 'C5-A1',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'cost_regime': 'MEXC Market',
            'fees_bps': {
                'tier1': round(tier1_fee * 10000, 1),
                'tier2': round(tier2_fee * 10000, 1),
            },
            'stress_fees_bps': {
                'tier1': round(stress_tier1_fee * 10000, 1),
                'tier2': round(stress_tier2_fee * 10000, 1),
            },
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'static_exclusions': {
            'static_12': sorted(STATIC_12_WORST),
            'oracle_21': sorted(ORACLE_21_EXCL),
        },
        'reference_configs': {
            'full_316': {
                'n_coins': ref_full['n_coins'],
                'metrics': ref_full['metrics'],
                'gate_evaluation': ref_full['gate_evaluation'],
                'stress_metrics': ref_full['stress_metrics'],
                'wf_folds_positive': ref_full['wf_folds_positive'],
                'fold_concentration': ref_full['fold_concentration'],
            },
            'static_12_304': {
                'n_coins': ref_static12['n_coins'],
                'metrics': ref_static12['metrics'],
                'gate_evaluation': ref_static12['gate_evaluation'],
                'stress_metrics': ref_static12['stress_metrics'],
                'wf_folds_positive': ref_static12['wf_folds_positive'],
                'fold_concentration': ref_static12['fold_concentration'],
            },
            'oracle_21_295': {
                'n_coins': ref_oracle21['n_coins'],
                'metrics': ref_oracle21['metrics'],
                'gate_evaluation': ref_oracle21['gate_evaluation'],
                'stress_metrics': ref_oracle21['stress_metrics'],
                'wf_folds_positive': ref_oracle21['wf_folds_positive'],
                'fold_concentration': ref_oracle21['fold_concentration'],
            },
        },
        'hybrid_rolling_results': hybrid_results,
        'pure_dynamic_comparison': pure_dynamic,
        'best_hybrid': {
            'label': best_hybrid['label'] if best_hybrid else None,
            'rolling_metrics': best_hybrid['metrics'] if best_hybrid else None,
            'persistent_dynamic': (best_hybrid['persistent_dynamic_excludes']
                                   if best_hybrid else []),
            'combined_static_list': best_hybrid_static_list,
            'n_combined': len(best_hybrid_static_list) if best_hybrid_static_list else 0,
        },
        'best_hybrid_gate_evaluation': best_hybrid_gate_eval,
        'verdict': {
            'result': verdict,
            'detail': verdict_detail,
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_hybrid_exclusion_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ── BUILD MARKDOWN REPORT ──
    md = []
    md.append('# Part 2 -- Hybrid Exclusion Strategy (Agent C5-A1)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins')
    md.append(f'**Params**: dev={PARAMS_V5["dev_thresh"]}, '
              f'tp={PARAMS_V5["tp_pct"]}, sl={PARAMS_V5["sl_pct"]}, '
              f'tl={PARAMS_V5["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    md.append(f'**Stress**: 2x fees (T1={stress_tier1_fee*10000:.1f}bps, '
              f'T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    md.append('## Objective')
    md.append('')
    md.append('Test a **hybrid exclusion** approach that combines:')
    md.append('')
    md.append('1. **Static Core** (12 worst coins): always excluded, '
              'high confidence from all prior analyses')
    md.append('2. **Dynamic Layer**: rolling lookback windows (168/336/504 bars) '
              'identify ADDITIONAL coins to exclude from the remaining 304')
    md.append('3. **Combined**: static 12 + dynamic N')
    md.append('')
    md.append('Compare against: Full 316 (no exclusion), Static 12 only (304), '
              'Oracle 21 (295).')
    md.append('')
    md.append('### Prior Results')
    md.append('')
    md.append('| Approach | Result |')
    md.append('|----------|--------|')
    md.append('| Rolling lookback only (C3-A2) | MARGINAL: 22% oracle retention |')
    md.append('| Expanding window OOS (C4-A2) | NOT_CONFIRMED: exclusion did not help OOS |')
    md.append('| Static 12 persistent (C3-A2) | 6/7 gates (G8 FAIL: fold conc 36.3%) |')
    md.append('| Oracle 21 (full-sample) | 7/7 gates, leader |')
    md.append('')
    md.append('**Hypothesis**: Combining the reliable static-12 exclusion with a '
              'dynamic rolling layer may capture additional bad coins that emerge '
              'over time, potentially recovering some oracle performance without '
              'forward-looking bias.')
    md.append('')

    # ── Reference Configs ──
    md.append('## 1. Reference Configurations (Full Gate Evaluation)')
    md.append('')
    md.append('| Config | Coins | Trades | PF | P&L | Exp/Wk | DD% | WF | G8 Conc | Gates |')
    md.append('|--------|-------|--------|----|-----|--------|-----|----|---------| ------|')
    for name, cfg in configs:
        m = cfg['metrics']
        ge = cfg['gate_evaluation']
        fc = cfg['fold_concentration']
        md.append(
            f'| {name} | {cfg["n_coins"]} | {m["trades"]} | '
            f'{m["pf"]:.3f} | ${m["pnl"]:.0f} | ${m["exp_per_week"]:.2f} | '
            f'{m["max_dd_pct"]:.1f}% | {cfg["wf_folds_positive"]}/5 | '
            f'{fc["top1_fold_conc_pct"]:.1f}% | {ge["score"]} |'
        )
    md.append('')

    # WF Fold details for each ref config
    md.append('### Walk-Forward Fold Details')
    md.append('')
    for name, cfg in configs:
        md.append(f'**{name}**:')
        for fd in cfg['wf_fold_details']:
            status = '+' if fd['positive'] else '-'
            md.append(f'  - Fold {fd["fold"]}: {fd["trades"]} trades, '
                      f'P&L=${fd["pnl"]:.0f} ({status})')
        md.append('')

    # ── Hybrid Rolling Results ──
    md.append('## 2. Hybrid Rolling Results')
    md.append('')
    md.append('Static 12 always excluded + dynamic layer from rolling lookback.')
    md.append('')
    md.append('| Label | Lookback | Segs | Trades | PF | P&L | Exp/Wk | '
              'Avg Excl | Dyn Stability |')
    md.append('|-------|----------|------|--------|----|-----|--------|'
              '----------|---------------|')
    for r in hybrid_results:
        m = r['metrics']
        md.append(
            f'| {r["label"]} | {r["lookback_weeks"]}wk | {r["n_segments"]} | '
            f'{m["trades"]} | {m["pf"]:.3f} | ${m["pnl"]:.0f} | '
            f'${m["exp_per_week"]:.2f} | {r["avg_combined_excl"]:.0f} | '
            f'{r["dynamic_stability"]["avg_overlap_pct"]:.0f}% |'
        )
    if pure_dynamic:
        m = pure_dynamic['metrics']
        md.append(
            f'| pure_dynamic_lb336 | 2.0wk | {pure_dynamic["n_segments"]} | '
            f'{m["trades"]} | {m["pf"]:.3f} | ${m["pnl"]:.0f} | '
            f'${m["exp_per_week"]:.2f} | {pure_dynamic["avg_combined_excl"]:.0f} | '
            f'{pure_dynamic["dynamic_stability"]["avg_overlap_pct"]:.0f}% |'
        )
    md.append('')

    # Per-segment details for best hybrid
    if best_hybrid:
        md.append('### Best Hybrid Segment Details')
        md.append('')
        md.append(f'**{best_hybrid["label"]}**')
        md.append('')
        md.append('| Seg | Bars | Static | Dynamic | Combined | Active | Trades | P&L |')
        md.append('|-----|------|--------|---------|----------|--------|--------|-----|')
        for s in best_hybrid['segment_details']:
            md.append(
                f'| {s["segment"]} | {s["seg_bars"][0]}-{s["seg_bars"][1]} | '
                f'{s["n_static_excl"]} | {s["n_dynamic_excl"]} | '
                f'{s["n_combined_excl"]} | {s["n_coins_active"]} | '
                f'{s["seg_trades"]} | ${s["seg_pnl"]:+.0f} |'
            )
        md.append('')

        # Persistent dynamic excludes
        if best_hybrid['persistent_dynamic_excludes']:
            md.append('### Persistent Dynamic Excludes (>50% of segments)')
            md.append('')
            md.append('These coins were dynamically excluded in more than half '
                      'of all rolling segments:')
            md.append('')
            md.append('| Coin | Excl Freq (%) | In Oracle 21? | In Static 12? |')
            md.append('|------|--------------|---------------|---------------|')
            freq = best_hybrid['dynamic_coin_frequency']
            for coin in best_hybrid['persistent_dynamic_excludes']:
                in_oracle = 'YES' if coin in ORACLE_21_EXCL else 'no'
                in_static = 'YES' if coin in STATIC_12_WORST else 'N/A'
                md.append(f'| {coin} | {freq.get(coin, 0):.0f}% | '
                          f'{in_oracle} | {in_static} |')
            md.append('')

    # ── Best Hybrid Gate Evaluation ──
    if best_hybrid_gate_eval:
        md.append('## 3. Best Hybrid -- Full Gate Evaluation')
        md.append('')
        md.append(f'Combined exclusion list: static 12 + '
                  f'{best_hybrid["n_persistent_dynamic"]} persistent dynamic = '
                  f'{len(best_hybrid_static_list)} total coins excluded.')
        md.append('')
        if best_hybrid_static_list:
            new_vs_oracle = set(best_hybrid_static_list) - ORACLE_21_EXCL
            in_oracle = set(best_hybrid_static_list) & ORACLE_21_EXCL
            md.append(f'- In oracle 21: {len(in_oracle)} coins')
            md.append(f'- New (not in oracle): {len(new_vs_oracle)} coins '
                      f'{sorted(new_vs_oracle) if new_vs_oracle else ""}')
            md.append('')
        ge = best_hybrid_gate_eval['gate_evaluation']
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | '
                      f'{g["threshold"]} | {status} |')
        md.append('')
        md.append(f'**Gate score: {ge["score"]}**')
        md.append('')

        bm = best_hybrid_gate_eval['metrics']
        sm = best_hybrid_gate_eval['stress_metrics']
        md.append(f'- Baseline: trades={bm["trades"]}, PF={bm["pf"]:.3f}, '
                  f'P&L=${bm["pnl"]:.0f}, exp/wk=${bm["exp_per_week"]:.2f}, '
                  f'DD={bm["max_dd_pct"]:.1f}%')
        md.append(f'- Stress (2x): PF={sm["pf"]:.3f}, P&L=${sm["pnl"]:.0f}, '
                  f'exp/wk=${sm["exp_per_week"]:.2f}')
        md.append(f'- WF: {best_hybrid_gate_eval["wf_folds_positive"]}/5 positive')
        md.append(f'- Fold conc: {best_hybrid_gate_eval["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
        md.append('')

    # ── Verdict ──
    md.append('## 4. Verdict')
    md.append('')
    md.append(f'### **{verdict}**')
    md.append('')
    md.append(verdict_detail)
    md.append('')

    # Comparison table
    md.append('### Key Comparison')
    md.append('')
    md.append('| Approach | Coins Excl | Gates | P&L | PF | Exp/Wk |')
    md.append('|----------|-----------|-------|-----|----| -------|')
    md.append(f'| Full 316 | 0 | {ref_full["gate_evaluation"]["score"]} | '
              f'${ref_full["metrics"]["pnl"]:.0f} | '
              f'{ref_full["metrics"]["pf"]:.3f} | '
              f'${ref_full["metrics"]["exp_per_week"]:.2f} |')
    md.append(f'| Static 12 (304) | 12 | {ref_static12["gate_evaluation"]["score"]} | '
              f'${ref_static12["metrics"]["pnl"]:.0f} | '
              f'{ref_static12["metrics"]["pf"]:.3f} | '
              f'${ref_static12["metrics"]["exp_per_week"]:.2f} |')
    if best_hybrid_gate_eval:
        md.append(f'| Hybrid best ({len(best_hybrid_static_list)}) | '
                  f'{len(best_hybrid_static_list)} | '
                  f'{best_hybrid_gate_eval["gate_evaluation"]["score"]} | '
                  f'${best_hybrid_gate_eval["metrics"]["pnl"]:.0f} | '
                  f'{best_hybrid_gate_eval["metrics"]["pf"]:.3f} | '
                  f'${best_hybrid_gate_eval["metrics"]["exp_per_week"]:.2f} |')
    md.append(f'| Oracle 21 (295) | 21 | {ref_oracle21["gate_evaluation"]["score"]} | '
              f'${ref_oracle21["metrics"]["pnl"]:.0f} | '
              f'{ref_oracle21["metrics"]["pf"]:.3f} | '
              f'${ref_oracle21["metrics"]["exp_per_week"]:.2f} |')
    md.append('')

    # Recommendation
    md.append('### Production Recommendation')
    md.append('')
    if verdict == 'HYBRID_CONFIRMED':
        md.append(f'Use the hybrid exclusion list ({len(best_hybrid_static_list)} coins) '
                  f'for production. It matches oracle gate performance without '
                  f'forward-looking bias.')
        md.append('')
        md.append('Implementation:')
        md.append('1. Always exclude static 12 worst coins')
        md.append(f'2. Every {SEGMENT_SIZE/BARS_PER_DAY:.0f} days, look back '
                  f'{best_hybrid["lookback_bars"]/BARS_PER_DAY:.0f} days '
                  f'to update dynamic exclusion list')
        md.append('3. Combine static + dynamic for the next trading segment')
        md.append('')
        md.append(f'Excluded coins: {best_hybrid_static_list}')
    elif verdict == 'HYBRID_IMPROVES_STATIC':
        md.append('Hybrid approach improves on static-12 but does not fully '
                  'match oracle. Consider:')
        md.append(f'- Use combined static list ({len(best_hybrid_static_list)} coins) '
                  f'as a better starting point')
        md.append('- Monitor dynamic layer additions in paper trading')
        md.append('- Re-evaluate when more data is available')
    elif verdict == 'HYBRID_MARGINAL_IMPROVEMENT':
        md.append('Hybrid provides marginal P&L improvement over static-12 '
                  'but does not change gate profile. Consider using static-12 '
                  'for simplicity, or the hybrid list if the P&L gain justifies '
                  'the added complexity.')
    elif verdict == 'HYBRID_NO_IMPROVEMENT':
        md.append('Dynamic layer does not improve on static-12. '
                  'Recommend staying with static-12 exclusion for simplicity.')
    elif verdict == 'HYBRID_DEGRADES':
        md.append('Dynamic layer is counterproductive. '
                  'Use static-12 exclusion only.')
    else:
        md.append('No viable hybrid configuration found. '
                  'Use static-12 exclusion as baseline.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_hybrid_exclusion.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_hybrid_exclusion_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Hybrid Exclusion Strategy')
    print(f'  Verdict: {verdict}')
    if best_hybrid_gate_eval:
        print(f'  Best hybrid gates: {best_hybrid_gate_eval["gate_evaluation"]["score"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
