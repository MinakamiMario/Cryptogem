#!/usr/bin/env python3
"""
P0-1: Universe Policy Sweep — Comprehensive
=============================================
Tests multiple universe construction policies for H20 VWAP_DEVIATION v5
under MEXC Market tiered fees.

Universe variants tested:
  1. T1-only (~96 coins)
  2. T1 + top-50% T2 by volume (~196 coins)
  3. T1 + top-70% T2 (~235 coins)
  4. T1 + top-90% T2 (~275 coins)
  5. Volume floor cutoffs: $50K, $100K, $200K, $500K minimum daily volume
  6. Top-N by average volume: N=50, 100, 150 (pre-filter, max_pos=1)
  7. Reference: full 316, excl_worst12 (304), excl_all_negative (295)

Per variant: baseline + stress 2x + walk-forward 5-fold + 8-gate evaluation.

Output:
  reports/hf/part2_universe_sweep_001.json
  reports/hf/part2_universe_sweep_001.md

Usage:
    python strategies/hf/screening/run_part2_universe_sweep_001.py
    python strategies/hf/screening/run_part2_universe_sweep_001.py --dry-run
"""
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from statistics import median

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

# ============================================================
# Constants
# ============================================================
BARS_PER_WEEK = 168
BARS_PER_DAY = 24
V5_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}

T1_FEE = get_harness_fee('mexc_market', 'tier1')
T2_FEE = get_harness_fee('mexc_market', 'tier2')

_stress = stress_multiplier('mexc_market', 2.0)
T1_STRESS = _stress['tier1']['total_per_side_bps'] / 10000.0
T2_STRESS = _stress['tier2']['total_per_side_bps'] / 10000.0

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}
EXCLUDED_12 = {
    'ALKIMI/USD', 'ANIME/USD', 'DBR/USD', 'ESX/USD', 'HOUSE/USD',
    'KET/USD', 'LMWR/USD', 'MXC/USD', 'ODOS/USD', 'PERP/USD',
    'TANSSI/USD', 'TITCOIN/USD',
}

GATE_THRESHOLDS = {
    'G1_trades_per_week': 10,
    'G2_max_gap_days': 2.5,
    'G3_exp_per_week_market': 0,
    'G4_exp_per_week_stress': 0,
    'G5_max_dd_pct': 20,
    'G6_wf_positive_folds': 4,
    'G8_fold_concentration': 0.35,
}


# ============================================================
# Data Loading
# ============================================================

def load_candle_parts():
    """Load 1h candle data from part files."""
    parts_base = ROOT / 'data' / 'cache_parts_hf' / '1h'
    if not parts_base.exists():
        print('[ERROR] No 1H part files found: %s' % parts_base)
        sys.exit(1)
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir():
            continue
        for coin_file in sorted(exchange_dir.glob('*.json')):
            symbol = coin_file.stem.replace('_', '/')
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 50:
                coins_data[symbol] = candles
    print('[Load] %d coins loaded from part files' % len(coins_data))
    return coins_data


def load_tiering():
    """Load universe tiering from report."""
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        print('[ERROR] Tiering not found: %s' % path)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def build_tier_sets(tiering, available_coins):
    """Build tier1 and tier2 coin lists from tiering data."""
    tb = tiering.get('tier_breakdown', {})
    t1_all = [c for c in tb.get('1', {}).get('coins', []) if c in available_coins]
    t2_all = [c for c in tb.get('2', {}).get('coins', []) if c in available_coins]
    return t1_all, t2_all


# ============================================================
# Volume Computation
# ============================================================

def compute_median_daily_volume(data, coins):
    """Compute median daily dollar volume per coin.

    Each candle is 1h, so daily = sum of 24 consecutive close*volume values.
    For simplicity, compute median(close*volume) per bar, then multiply by 24.
    """
    volumes = {}
    for coin in coins:
        candles = data.get(coin, [])
        if not candles:
            continue
        dvols = []
        for c in candles:
            cl = c.get('close', 0)
            vol = c.get('volume', 0)
            if cl > 0 and vol > 0:
                dvols.append(cl * vol)
        if dvols:
            # median hourly dollar volume * 24 = estimated daily volume
            volumes[coin] = median(dvols) * 24
        else:
            volumes[coin] = 0.0
    return volumes


# ============================================================
# Metric Computation
# ============================================================

def compute_max_gap(trades, total_bars):
    """Compute maximum gap between trades in days."""
    if len(trades) < 2:
        return total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    mg = st[0].get('entry_bar', 50) - 50
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i - 1].get('exit_bar', 0)
        if g > mg:
            mg = g
    eg = total_bars - st[-1].get('exit_bar', 0)
    if eg > mg:
        mg = eg
    return mg / BARS_PER_DAY


def compute_drawdown(trades, initial_capital=2000.0):
    """Compute max drawdown percentage from trade list."""
    if not trades:
        return 0.0
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
    return max_dd


def compute_fold_concentration(fold_pnls):
    """Compute top-1 fold concentration (fraction of total positive P&L)."""
    pos = [p for p in fold_pnls if p > 0]
    if not pos:
        return 1.0
    total = sum(pos)
    return max(pos) / total if total > 0 else 1.0


def compute_metrics(trades, total_bars, initial_capital=2000.0):
    """Compute standard metrics from trade list."""
    nt = len(trades)
    if nt == 0:
        return {
            'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
            'dd': 0.0, 'exp_per_trade': 0.0,
            'trades_per_week': 0.0, 'exp_per_week': 0.0,
        }
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / nt * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    exp = total_pnl / nt

    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tpw = nt / total_weeks
    epw = exp * tpw
    dd = compute_drawdown(trades, initial_capital)

    return {
        'trades': nt,
        'pnl': round(total_pnl, 2),
        'pf': round(pf, 3),
        'wr': round(wr, 1),
        'dd': round(dd, 1),
        'exp_per_trade': round(exp, 4),
        'trades_per_week': round(tpw, 2),
        'exp_per_week': round(epw, 4),
    }


def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days, fold_conc):
    """Evaluate all 7 hard gates (G7 neighbor stability skipped at universe level)."""
    gates = {}
    gates['G1'] = {
        'value': round(metrics['trades_per_week'], 2),
        'threshold': '>= 10',
        'pass': metrics['trades_per_week'] >= GATE_THRESHOLDS['G1_trades_per_week'],
    }
    gates['G2'] = {
        'value': round(max_gap_days, 2),
        'threshold': '<= 2.5d',
        'pass': max_gap_days <= GATE_THRESHOLDS['G2_max_gap_days'],
    }
    gates['G3'] = {
        'value': round(metrics['exp_per_week'], 2),
        'threshold': '> $0',
        'pass': metrics['exp_per_week'] > 0,
    }
    gates['G4'] = {
        'value': round(stress_metrics['exp_per_week'], 2),
        'threshold': '> $0 (stress 2x)',
        'pass': stress_metrics['exp_per_week'] > 0,
    }
    gates['G5'] = {
        'value': round(metrics['dd'], 1),
        'threshold': '<= 20%',
        'pass': metrics['dd'] <= GATE_THRESHOLDS['G5_max_dd_pct'],
    }
    gates['G6'] = {
        'value': wf_folds_positive,
        'threshold': '>= 4/5',
        'pass': wf_folds_positive >= GATE_THRESHOLDS['G6_wf_positive_folds'],
    }
    gates['G8'] = {
        'value': round(fold_conc, 3),
        'threshold': '< 35%',
        'pass': fold_conc < GATE_THRESHOLDS['G8_fold_concentration'],
    }
    n_pass = sum(1 for g in gates.values() if g['pass'])
    return gates, n_pass


# ============================================================
# Per-Variant Runner
# ============================================================

def run_variant(label, t1_coins, t2_coins, data, all_ind, mkt_ctx, total_bars):
    """Run full evaluation for a universe variant: baseline, stress, walk-forward, gates."""
    t_start = time.time()
    n_t1, n_t2 = len(t1_coins), len(t2_coins)
    n_total = n_t1 + n_t2
    print('  [%s] T1=%d T2=%d total=%d' % (label, n_t1, n_t2, n_total))

    if n_total == 0:
        print('    SKIP: empty universe')
        return None

    # Build tier-specific indicator dicts
    tier_ind = {}
    if t1_coins:
        tier_ind['tier1'] = {c: all_ind[c] for c in t1_coins if c in all_ind}
    if t2_coins:
        tier_ind['tier2'] = {c: all_ind[c] for c in t2_coins if c in all_ind}
    tc = {'tier1': t1_coins, 'tier2': t2_coins}
    params = {**V5_PARAMS, '__market__': mkt_ctx}

    # --- Baseline backtest ---
    all_trades = []
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_FEE if tn == 'tier1' else T2_FEE
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=params, indicators=tier_ind.get(tn, {}), fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tn
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    metrics = compute_metrics(all_trades, total_bars)
    max_gap = compute_max_gap(all_trades, total_bars)
    print('    Baseline: %dtr PF=%.3f WR=%.1f%% Exp/wk=$%.2f DD=%.1f%%' % (
        metrics['trades'], metrics['pf'], metrics['wr'],
        metrics['exp_per_week'], metrics['dd']))

    # --- Stress 2x ---
    stress_trades = []
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_STRESS if tn == 'tier1' else T2_STRESS
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=params, indicators=tier_ind.get(tn, {}), fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tn
        stress_trades.extend(bt.trade_list)

    stress_metrics = compute_metrics(stress_trades, total_bars)
    print('    Stress:   %dtr PF=%.3f Exp/wk=$%.2f' % (
        stress_metrics['trades'], stress_metrics['pf'],
        stress_metrics['exp_per_week']))

    # --- Walk-forward 5-fold ---
    tier_fold_trades = {}
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_FEE if tn == 'tier1' else T2_FEE
        folds = walk_forward(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=params, indicators=tier_ind.get(tn, {}),
            n_folds=5, fee=fee, max_pos=1,
        )
        for fi, fbt in enumerate(folds):
            if fi not in tier_fold_trades:
                tier_fold_trades[fi] = []
            for t in fbt.trade_list:
                t['_tier'] = tn
            tier_fold_trades[fi].extend(fbt.trade_list)

    fold_pnls = []
    fold_details = []
    for fi in range(5):
        ft = tier_fold_trades.get(fi, [])
        fp = sum(t['pnl'] for t in ft)
        fold_pnls.append(fp)
        fold_details.append({'fold': fi + 1, 'trades': len(ft), 'pnl': round(fp, 2)})

    wf_positive = sum(1 for p in fold_pnls if p > 0)
    fold_conc = compute_fold_concentration(fold_pnls)
    fold_str = ' '.join(['$%.0f' % p for p in fold_pnls])
    print('    WF:       %d/5 [%s] conc=%.0f%%' % (wf_positive, fold_str, fold_conc * 100))

    # --- Gate evaluation ---
    gates, n_pass = evaluate_gates(metrics, stress_metrics, wf_positive, max_gap, fold_conc)
    elapsed = time.time() - t_start

    status = 'ALL PASS' if n_pass == 7 else '%d/7' % n_pass
    print('    Gates:    %s (%.1fs)' % (status, elapsed))

    # Tier P&L breakdown
    t1_pnl = sum(t['pnl'] for t in all_trades if t.get('_tier') == 'tier1')
    t2_pnl = sum(t['pnl'] for t in all_trades if t.get('_tier') == 'tier2')
    t1_trades = sum(1 for t in all_trades if t.get('_tier') == 'tier1')
    t2_trades = sum(1 for t in all_trades if t.get('_tier') == 'tier2')

    return {
        'label': label,
        'n_t1': n_t1, 'n_t2': n_t2, 'n_total': n_total,
        'baseline': metrics,
        'stress': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'wr': stress_metrics['wr'],
            'exp_per_week': stress_metrics['exp_per_week'],
            'dd': stress_metrics['dd'],
        },
        'wf_folds_positive': wf_positive,
        'fold_details': fold_details,
        'fold_concentration': round(fold_conc, 3),
        'max_gap_days': round(max_gap, 2),
        'gates': gates,
        'gates_passed': n_pass,
        'gates_total': 7,
        'tier_split': {
            't1_trades': t1_trades, 't1_pnl': round(t1_pnl, 2),
            't2_trades': t2_trades, 't2_pnl': round(t2_pnl, 2),
        },
        'runtime_s': round(elapsed, 1),
    }


# ============================================================
# Universe Variant Builders
# ============================================================

def build_variants(t1_all, t2_all, data, daily_volumes):
    """Build all universe variant definitions.

    Returns list of (label, t1_coins, t2_coins) tuples.
    """
    t1_set = set(t1_all)
    t2_set = set(t2_all)
    all_tier = set(t1_all) | set(t2_all)

    variants = []

    # --- Category 1: Tier-based filtering ---

    # V1: T1-only
    variants.append(('T1_only', list(t1_all), []))

    # V2-V4: T1 + top-X% of T2 by volume
    t2_by_vol = sorted(t2_all, key=lambda c: daily_volumes.get(c, 0), reverse=True)
    n_t2 = len(t2_by_vol)

    for pct, label_suffix in [(50, '50pct'), (70, '70pct'), (90, '90pct')]:
        cutoff = max(1, int(n_t2 * pct / 100))
        t2_subset = t2_by_vol[:cutoff]
        variants.append(('T1+T2_%s' % label_suffix, list(t1_all), t2_subset))

    # --- Category 2: Volume floor cutoffs ---
    for floor_k in [50, 100, 200, 500]:
        floor_usd = floor_k * 1000
        t1_filt = [c for c in t1_all if daily_volumes.get(c, 0) >= floor_usd]
        t2_filt = [c for c in t2_all if daily_volumes.get(c, 0) >= floor_usd]
        variants.append(('vol_floor_%dK' % floor_k, t1_filt, t2_filt))

    # --- Category 3: Top-N by volume (pre-filter) ---
    all_coins_ranked = sorted(
        list(all_tier), key=lambda c: daily_volumes.get(c, 0), reverse=True
    )
    for topn in [50, 100, 150]:
        subset = all_coins_ranked[:topn]
        t1_sub = [c for c in subset if c in t1_set]
        t2_sub = [c for c in subset if c in t2_set]
        variants.append(('top%d_by_vol' % topn, t1_sub, t2_sub))

    # --- Category 4: Reference variants ---
    # Full 316
    variants.append(('full_316', list(t1_all), list(t2_all)))

    # Excl worst 12
    t1_excl12 = [c for c in t1_all if c not in EXCLUDED_12]
    t2_excl12 = [c for c in t2_all if c not in EXCLUDED_12]
    variants.append(('excl_worst12_304', t1_excl12, t2_excl12))

    # Excl all negative 21
    t1_excl21 = [c for c in t1_all if c not in EXCLUDED_21]
    t2_excl21 = [c for c in t2_all if c not in EXCLUDED_21]
    variants.append(('excl_neg21_295', t1_excl21, t2_excl21))

    return variants


# ============================================================
# Main
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='P0-1: Universe Policy Sweep (comprehensive)',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Print variant list and exit without running backtests')
    args = parser.parse_args()

    print('=' * 72)
    print('  P0-1: Universe Policy Sweep')
    print('  Signal: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    print('  Fees: MEXC Market (T1=%.1fbps, T2=%.1fbps)' % (T1_FEE * 10000, T2_FEE * 10000))
    print('  Stress: 2x (T1=%.1fbps, T2=%.1fbps)' % (T1_STRESS * 10000, T2_STRESS * 10000))
    print('  Gates: G1-G6,G8 STRICT (G7 neighbor skipped)')
    print('=' * 72)
    t0 = time.time()

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    data = load_candle_parts()
    available = set(data.keys())

    tiering = load_tiering()
    t1_all, t2_all = build_tier_sets(tiering, available)
    t1_set = set(t1_all)
    t2_set = set(t2_all)
    all_tier = t1_all + t2_all
    print('[Universe] T1: %d, T2: %d, Total: %d' % (len(t1_all), len(t2_all), len(all_tier)))

    # --- Compute volumes ---
    print('[Volume] Computing median daily dollar volume per coin...')
    daily_volumes = compute_median_daily_volume(data, all_tier)
    ranked_by_vol = sorted(daily_volumes.items(), key=lambda x: x[1], reverse=True)
    print('[Volume] Top 5:')
    for i, (c, v) in enumerate(ranked_by_vol[:5]):
        print('  %d. %s $%.0f/day' % (i + 1, c, v))
    print('[Volume] Bottom 3:')
    for c, v in ranked_by_vol[-3:]:
        print('  %s $%.0f/day' % (c, v))

    # --- Build variants ---
    variants = build_variants(t1_all, t2_all, data, daily_volumes)
    print('[Variants] %d universe policies to test' % len(variants))

    if args.dry_run:
        print('\n--- DRY RUN: Variant List ---')
        for i, (label, t1c, t2c) in enumerate(variants):
            print('  %2d. %-25s T1=%3d T2=%3d total=%3d' % (
                i + 1, label, len(t1c), len(t2c), len(t1c) + len(t2c)))
        print('\nWould run %d variants x 3 passes (baseline + stress + WF5)' % len(variants))
        sys.exit(0)

    # --- Precompute indicators for ALL coins (once) ---
    print('[Indicators] Precomputing base indicators for all %d tier coins...' % len(all_tier))
    t_ind = time.time()
    all_ind = precompute_base_indicators(data, all_tier)
    print('  Base: %d coins in %.1fs' % (len(all_ind), time.time() - t_ind))

    print('[Indicators] Extending with VWAP fields...')
    extend_indicators(data, all_tier, all_ind)
    cov = get_feature_coverage(all_ind, all_tier)
    print('  VWAP: %.0f%% (%d/%d)' % (cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

    for coin in all_ind:
        all_ind[coin]['__coin__'] = coin

    # --- Market context ---
    print('[Market Context] Precomputing...')
    ctx_coins = list(set(all_tier))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available and btc not in ctx_coins:
            ctx_coins.append(btc)
    mkt_ctx = precompute_market_context(data, ctx_coins)
    print('  Done.')

    total_bars = max((all_ind.get(c, {}).get('n', 0) for c in all_tier), default=0)
    total_weeks = total_bars / BARS_PER_WEEK
    print('[Data] total_bars=%d, total_weeks=%.1f' % (total_bars, total_weeks))

    # ============================================================
    # Run all variants
    # ============================================================
    print()
    print('=' * 72)
    print('  SWEEP: %d universe policies' % len(variants))
    print('=' * 72)

    results = []
    for i, (label, t1c, t2c) in enumerate(variants):
        print('\n[%d/%d] %s' % (i + 1, len(variants), label))
        r = run_variant(label, t1c, t2c, data, all_ind, mkt_ctx, total_bars)
        if r is not None:
            results.append(r)

    elapsed = time.time() - t0

    # ============================================================
    # Analysis
    # ============================================================
    all_pass = [r for r in results if r['gates_passed'] == 7]
    best = max(results, key=lambda r: r['gates_passed'] * 10000 + r['baseline']['exp_per_week'])

    print()
    print('=' * 72)
    print('  RESULTS SUMMARY')
    print('=' * 72)
    print()
    print('%-28s %4s %4s %5s %6s %5s %7s %5s %6s %3s %5s %5s' % (
        'Variant', 'T1', 'T2', 'Trds', 'PF', 'WR%', 'Exp/wk', 'DD%',
        'StExp', 'WF', 'FConc', 'Gates'))
    print('-' * 100)
    for r in results:
        m = r['baseline']
        s = r['stress']
        marker = ' ***' if r['gates_passed'] == 7 else ''
        print('%-28s %4d %4d %5d %6.3f %5.1f %7.2f %5.1f %6.2f %d/5 %5.1f%% %d/7%s' % (
            r['label'], r['n_t1'], r['n_t2'],
            m['trades'], m['pf'], m['wr'], m['exp_per_week'], m['dd'],
            s['exp_per_week'], r['wf_folds_positive'],
            r['fold_concentration'] * 100, r['gates_passed'], marker))

    print()
    if all_pass:
        print('PASS ALL 7 GATES: %d variants' % len(all_pass))
        for r in all_pass:
            print('  - %s (%d coins, Exp/wk=$%.2f)' % (
                r['label'], r['n_total'], r['baseline']['exp_per_week']))
    else:
        print('NO variant passes all 7 gates.')
        print('Best: %s (%d/7 gates, Exp/wk=$%.2f)' % (
            best['label'], best['gates_passed'], best['baseline']['exp_per_week']))

    # ============================================================
    # JSON Report
    # ============================================================
    report = {
        'run_header': {
            'task': 'P0-1_universe_policy_sweep',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'signal': 'H20_VWAP_DEVIATION v5',
            'params': V5_PARAMS,
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees': {
                'market': {
                    'tier1_bps': round(T1_FEE * 10000, 1),
                    'tier2_bps': round(T2_FEE * 10000, 1),
                },
                'stress_2x': {
                    'tier1_bps': round(T1_STRESS * 10000, 1),
                    'tier2_bps': round(T2_STRESS * 10000, 1),
                },
            },
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'variants_tested': len(results),
            'runtime_s': round(elapsed, 1),
        },
        'gate_thresholds': {
            'G1': '>= 10 trades/week',
            'G2': '<= 2.5 days max gap',
            'G3': '> $0 exp/week (market)',
            'G4': '> $0 exp/week (stress 2x)',
            'G5': '<= 20% max DD',
            'G6': '>= 4/5 WF folds positive',
            'G8': '< 35% top-1 fold concentration',
        },
        'volume_info': {
            'method': 'median(close * volume) * 24 per coin',
            'top10': [
                {'rank': i + 1, 'coin': c, 'daily_vol_usd': round(v, 0)}
                for i, (c, v) in enumerate(ranked_by_vol[:10])
            ],
        },
        'sweep_results': results,
        'summary': {
            'all_pass_variants': [r['label'] for r in all_pass],
            'all_pass_count': len(all_pass),
            'best_variant': best['label'],
            'best_gates_passed': best['gates_passed'],
            'best_exp_per_week': best['baseline']['exp_per_week'],
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_universe_sweep_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ============================================================
    # Markdown Report
    # ============================================================
    md = []
    md.append('# P0-1: Universe Policy Sweep')
    md.append('')
    md.append('**Date**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M'))
    md.append('**Commit**: %s' % commit)
    md.append('**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append('**Fees**: MEXC Market (T1=%.1fbps, T2=%.1fbps)' % (T1_FEE * 10000, T2_FEE * 10000))
    md.append('**Stress**: 2x (T1=%.1fbps, T2=%.1fbps)' % (T1_STRESS * 10000, T2_STRESS * 10000))
    md.append('**Data**: %d bars (%.1f weeks)' % (total_bars, total_weeks))
    md.append('**Variants tested**: %d' % len(results))
    md.append('**Runtime**: %.1fs' % elapsed)
    md.append('')

    # Gate thresholds
    md.append('## Gate Thresholds (STRICT)')
    md.append('')
    md.append('| Gate | Metric | Threshold |')
    md.append('|------|--------|-----------|')
    md.append('| G1 | Trades/week | >= 10 |')
    md.append('| G2 | Max gap | <= 2.5 days |')
    md.append('| G3 | Exp/week (market) | > $0 |')
    md.append('| G4 | Exp/week (stress 2x) | > $0 |')
    md.append('| G5 | Max DD | <= 20% |')
    md.append('| G6 | WF positive folds | >= 4/5 |')
    md.append('| G8 | Top-1 fold concentration | < 35% |')
    md.append('')

    # Summary comparison table
    md.append('## Summary Comparison')
    md.append('')
    md.append('| Variant | Coins | T1 | T2 | Trades | PF | WR% | Exp/wk | DD% | StressExp | WF | FoldConc | Gates |')
    md.append('|---------|-------|----|----|--------|-----|------|--------|------|-----------|-----|----------|-------|')
    for r in results:
        m = r['baseline']
        s = r['stress']
        gp = r['gates_passed']
        marker = ' **ALL**' if gp == 7 else ''
        md.append('| %s | %d | %d | %d | %d | %.3f | %.1f | $%.2f | %.1f | $%.2f | %d/5 | %.0f%% | %d/7%s |' % (
            r['label'], r['n_total'], r['n_t1'], r['n_t2'],
            m['trades'], m['pf'], m['wr'], m['exp_per_week'], m['dd'],
            s['exp_per_week'], r['wf_folds_positive'],
            r['fold_concentration'] * 100, gp, marker))
    md.append('')

    # Gate pass/fail matrix
    md.append('## Gate Pass/Fail Matrix')
    md.append('')
    gate_keys = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']
    md.append('| Variant | ' + ' | '.join(gate_keys) + ' | Total |')
    md.append('|---------|' + '|'.join(['------'] * len(gate_keys)) + '|-------|')
    for r in results:
        g = r['gates']
        cells = []
        for gk in gate_keys:
            if g[gk]['pass']:
                cells.append('PASS')
            else:
                cells.append('**FAIL**')
        md.append('| %s | %s | %d/7 |' % (r['label'], ' | '.join(cells), r['gates_passed']))
    md.append('')

    # Walk-forward detail
    md.append('## Walk-Forward Detail (5-Fold)')
    md.append('')
    md.append('| Variant | F1 | F2 | F3 | F4 | F5 | Positive | Conc |')
    md.append('|---------|----|----|----|----|-----|----------|------|')
    for r in results:
        fds = r.get('fold_details', [])
        pnls = ['$%.0f' % fd['pnl'] for fd in fds]
        while len(pnls) < 5:
            pnls.append('-')
        md.append('| %s | %s | %s | %s | %s | %s | %d/5 | %.0f%% |' % (
            r['label'], pnls[0], pnls[1], pnls[2], pnls[3], pnls[4],
            r['wf_folds_positive'], r['fold_concentration'] * 100))
    md.append('')

    # Tier P&L breakdown
    md.append('## Tier P&L Breakdown')
    md.append('')
    md.append('| Variant | T1 Trades | T1 P&L | T2 Trades | T2 P&L | Total P&L |')
    md.append('|---------|-----------|--------|-----------|--------|-----------|')
    for r in results:
        ts = r['tier_split']
        md.append('| %s | %d | $%.0f | %d | $%.0f | $%.0f |' % (
            r['label'], ts['t1_trades'], ts['t1_pnl'],
            ts['t2_trades'], ts['t2_pnl'], r['baseline']['pnl']))
    md.append('')

    # Best feasible region analysis
    md.append('## Best Feasible Region Analysis')
    md.append('')
    if all_pass:
        md.append('**%d variants pass all 7 gates:**' % len(all_pass))
        md.append('')
        for r in all_pass:
            m = r['baseline']
            md.append('- **%s** (%d coins): PF=%.3f, Exp/wk=$%.2f, DD=%.1f%%, WF=%d/5' % (
                r['label'], r['n_total'], m['pf'], m['exp_per_week'],
                m['dd'], r['wf_folds_positive']))
        md.append('')
        # Find optimal = most coins that still passes
        optimal = max(all_pass, key=lambda r: r['n_total'])
        md.append('**Optimal (largest passing universe)**: %s (%d coins)' % (
            optimal['label'], optimal['n_total']))
        # Find best edge = highest exp/wk among all-pass
        best_edge = max(all_pass, key=lambda r: r['baseline']['exp_per_week'])
        md.append('**Best edge (highest Exp/wk)**: %s ($%.2f/wk)' % (
            best_edge['label'], best_edge['baseline']['exp_per_week']))
    else:
        md.append('**No variant passes all 7 gates.**')
        md.append('')
        # Find closest to passing
        closest = sorted(results, key=lambda r: (-r['gates_passed'], -r['baseline']['exp_per_week']))
        md.append('Closest variants:')
        for r in closest[:5]:
            failed = [gk for gk in gate_keys if not r['gates'][gk]['pass']]
            md.append('- **%s** (%d coins, %d/7 gates): fails %s' % (
                r['label'], r['n_total'], r['gates_passed'], ', '.join(failed)))
    md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    if all_pass:
        optimal = max(all_pass, key=lambda r: r['n_total'])
        best_edge = max(all_pass, key=lambda r: r['baseline']['exp_per_week'])
        md.append('**FEASIBLE REGION FOUND**: %d of %d variants pass all 7 strict gates.' % (
            len(all_pass), len(results)))
        md.append('')
        md.append('Recommended universe policy:')
        md.append('- **Largest passing**: %s (%d coins) -- maximizes trade count' % (
            optimal['label'], optimal['n_total']))
        md.append('- **Best edge**: %s ($%.2f/wk) -- maximizes expected profit' % (
            best_edge['label'], best_edge['baseline']['exp_per_week']))
    else:
        md.append('**NO FEASIBLE REGION**: No universe policy passes all 7 strict gates.')
        md.append('')
        md.append('Closest: %s (%d/7 gates, Exp/wk=$%.2f)' % (
            best['label'], best['gates_passed'], best['baseline']['exp_per_week']))
        md.append('')
        md.append('Consider relaxing thresholds or adjusting signal parameters.')
    md.append('')

    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_universe_sweep_001.py at %s*' % (
        datetime.now().strftime('%Y-%m-%d %H:%M')))

    md_path = ROOT / 'reports' / 'hf' / 'part2_universe_sweep_001.md'
    md_path.write_text('\n'.join(md))
    print('[Report] MD: %s' % md_path)

    print()
    print('=' * 72)
    print('  COMPLETE: %d variants tested in %.1fs' % (len(results), elapsed))
    if all_pass:
        print('  ALL-PASS: %d variants' % len(all_pass))
        for r in all_pass:
            print('    - %s (%d coins)' % (r['label'], r['n_total']))
    else:
        print('  BEST: %s (%d/7 gates)' % (best['label'], best['gates_passed']))
    print('=' * 72)


if __name__ == '__main__':
    main()
