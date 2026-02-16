#!/usr/bin/env python3
"""
Part 2: T1 Concentration Risk Analysis
=======================================
XL1/USD accounts for 48.3% of T1 P&L. This script studies what happens
when XL1/USD is excluded or capped, and whether T1 remains viable without
its top contributor(s).

Variants:
  1. Baseline v5/295 (reference)
  2. v5/295 excluding XL1/USD
  3. v5/295 excluding top-3 T1 coins (XL1/USD, GHIBLI/USD, XAN/USD)
  4. v5/295 T2-only (all T1 excluded)

For each: baseline metrics, WF 5-fold, stress 2x, 7 gates, HHI.

Output:
  reports/hf/part2_t1_concentration_001.json
  reports/hf/part2_t1_concentration_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_t1_concentration.py
    python strategies/hf/screening/run_part2_t1_concentration.py --dry-run
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
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee, stress_multiplier

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168  # 24 * 7
BARS_PER_DAY = 24

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

# Top T1 coins to test exclusion
TOP3_T1_COINS = {'XL1/USD', 'GHIBLI/USD', 'XAN/USD'}

REPORT_JSON = 'part2_t1_concentration_001.json'
REPORT_MD   = 'part2_t1_concentration_001.md'


# ============================================================
# Data Loading (reuse patterns from tier_decomp)
# ============================================================

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
            print(f'[ERROR] No cache found')
            sys.exit(1)
        print('[SKIP] No 1H candle cache found.')
        return None
    print('[Load] Loading from per-coin parts...')
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
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        if require_data:
            print(f'[ERROR] Tiering not found: {path}')
            sys.exit(1)
        print('[SKIP] No tiering file found.')
        return None
    with open(path) as f:
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


# ============================================================
# Backtest Runners (per-tier, then merge)
# ============================================================

def run_tier_backtest(params, data, coins, indicators, market_ctx, fee, tier_label=''):
    """Run v5 backtest on a specific set of coins with specific fee."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_ctx}
    bt = run_backtest(
        data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
        params=enriched, indicators=indicators, fee=fee, max_pos=1,
    )
    for t in bt.trade_list:
        t['_tier'] = tier_label
        t['_fee_per_side'] = fee
    return bt.trade_list


def run_tier_walk_forward(params, data, coins, indicators, market_ctx, fee, n_folds=5, tier_label=''):
    """Run walk-forward on a specific set of coins with specific fee."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_ctx}
    fold_results = walk_forward(
        data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
        params=enriched, indicators=indicators, n_folds=n_folds, fee=fee, max_pos=1,
    )
    fold_trades = {}
    for idx, fold_bt in enumerate(fold_results):
        for t in fold_bt.trade_list:
            t['_tier'] = tier_label
            t['_fee_per_side'] = fee
        fold_trades[idx] = fold_bt.trade_list
    return fold_trades


def run_combined_backtest(params, data, tier_coins, tier_indicators, market_ctx,
                          tier1_fee, tier2_fee, t1_coins_override=None, t2_coins_override=None):
    """Run combined T1+T2 backtest, merging trade lists."""
    t1_coins = t1_coins_override if t1_coins_override is not None else tier_coins.get('tier1', [])
    t2_coins = t2_coins_override if t2_coins_override is not None else tier_coins.get('tier2', [])

    all_trades = []
    if t1_coins:
        t1_trades = run_tier_backtest(params, data, t1_coins,
                                       tier_indicators.get('tier1', {}),
                                       market_ctx, tier1_fee, 'tier1')
        all_trades.extend(t1_trades)
    if t2_coins:
        t2_trades = run_tier_backtest(params, data, t2_coins,
                                       tier_indicators.get('tier2', {}),
                                       market_ctx, tier2_fee, 'tier2')
        all_trades.extend(t2_trades)
    return all_trades


def run_combined_walk_forward(params, data, tier_coins, tier_indicators, market_ctx,
                               tier1_fee, tier2_fee, n_folds=5,
                               t1_coins_override=None, t2_coins_override=None):
    """Run combined T1+T2 walk-forward, merging fold trades."""
    t1_coins = t1_coins_override if t1_coins_override is not None else tier_coins.get('tier1', [])
    t2_coins = t2_coins_override if t2_coins_override is not None else tier_coins.get('tier2', [])

    t1_folds = {}
    t2_folds = {}
    if t1_coins:
        t1_folds = run_tier_walk_forward(params, data, t1_coins,
                                          tier_indicators.get('tier1', {}),
                                          market_ctx, tier1_fee, n_folds, 'tier1')
    if t2_coins:
        t2_folds = run_tier_walk_forward(params, data, t2_coins,
                                          tier_indicators.get('tier2', {}),
                                          market_ctx, tier2_fee, n_folds, 'tier2')

    # Merge fold trades
    combined_folds = {}
    all_fold_idxs = set(list(t1_folds.keys()) + list(t2_folds.keys()))
    for fi in sorted(all_fold_idxs):
        combined_folds[fi] = t1_folds.get(fi, []) + t2_folds.get(fi, [])
    return combined_folds


def run_combined_stress(params, data, tier_coins, tier_indicators, market_ctx,
                        stress_t1_fee, stress_t2_fee,
                        t1_coins_override=None, t2_coins_override=None):
    """Run combined stress backtest with 2x fees."""
    return run_combined_backtest(params, data, tier_coins, tier_indicators, market_ctx,
                                 stress_t1_fee, stress_t2_fee,
                                 t1_coins_override, t2_coins_override)


# ============================================================
# Metrics Computation
# ============================================================

def compute_metrics(trades, total_bars, initial_capital=2000.0):
    n = len(trades)
    if n == 0:
        return dict(trades=0, pnl=0.0, pf=0.0, wr=0.0, dd=0.0,
                    expectancy=0.0, trades_per_week=0.0, exp_per_week=0.0)
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tpw = n / total_weeks
    epw = expectancy * tpw
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
    return dict(
        trades=n, pnl=round(total_pnl, 2), pf=round(pf, 3), wr=round(wr, 2),
        dd=round(max_dd, 2), expectancy=round(expectancy, 4),
        trades_per_week=round(tpw, 2), exp_per_week=round(epw, 4),
    )


def compute_max_gap(trades, total_bars):
    if not trades:
        return total_bars, round(total_bars / BARS_PER_DAY, 2)
    entry_bars = sorted(t['entry_bar'] for t in trades)
    gaps = [entry_bars[i+1] - entry_bars[i] for i in range(len(entry_bars) - 1)]
    gaps.append(entry_bars[0])
    gaps.append(total_bars - entry_bars[-1])
    max_gap = max(gaps) if gaps else total_bars
    return max_gap, round(max_gap / BARS_PER_DAY, 2)


def compute_top1_fold_concentration(fold_details):
    positive_pnls = [f['pnl'] for f in fold_details if f['pnl'] > 0]
    if not positive_pnls:
        return 1.0
    total_pos = sum(positive_pnls)
    if total_pos <= 0:
        return 1.0
    return round(max(positive_pnls) / total_pos, 4)


def compute_coin_breakdown(trades):
    """Compute per-coin P&L breakdown."""
    coin_pnl = {}
    for t in trades:
        c = t.get('pair', 'unknown')
        coin_pnl[c] = coin_pnl.get(c, 0.0) + t['pnl']
    if not coin_pnl:
        return {
            'coins_with_trades': 0, 'top5': [], 'worst5': [],
            'top1_coin_conc': 0.0, 'top3_coin_conc': 0.0,
        }
    top_coins = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
    worst_coins = sorted(coin_pnl.items(), key=lambda x: x[1])[:5]
    total_pos_pnl = sum(v for v in coin_pnl.values() if v > 0)
    top1_coin_conc = (top_coins[0][1] / total_pos_pnl
                      if total_pos_pnl > 0 and top_coins and top_coins[0][1] > 0
                      else 0.0)
    top3_coin_conc = (sum(v for _, v in top_coins[:3] if v > 0) / total_pos_pnl
                      if total_pos_pnl > 0 else 0.0)
    return {
        'coins_with_trades': len(coin_pnl),
        'top5': [{'coin': c, 'pnl': round(p, 2)} for c, p in top_coins],
        'worst5': [{'coin': c, 'pnl': round(p, 2)} for c, p in worst_coins],
        'top1_coin_conc': round(top1_coin_conc, 4),
        'top3_coin_conc': round(top3_coin_conc, 4),
        'all_coin_pnl': {c: round(p, 2) for c, p in coin_pnl.items()},
    }


# ============================================================
# HHI Calculation
# ============================================================

def compute_hhi(trade_list):
    """Herfindahl-Hirschman Index for P&L concentration by coin (positive attribution)."""
    coin_pnl = defaultdict(float)
    for t in trade_list:
        coin_pnl[t['pair']] += max(0, t['pnl'])  # positive attribution only
    total = sum(coin_pnl.values())
    if total == 0:
        return 1.0  # maximum concentration (degenerate)
    shares = [v / total for v in coin_pnl.values()]
    hhi = sum(s**2 for s in shares)
    return round(hhi, 6)


def hhi_interpretation(hhi, n_coins_active):
    """Interpret HHI value."""
    if hhi > 0.25:
        return 'HIGHLY CONCENTRATED'
    elif hhi > 0.15:
        return 'MODERATELY CONCENTRATED'
    elif hhi > 0.10:
        return 'MILDLY CONCENTRATED'
    else:
        return 'DIVERSIFIED'


# ============================================================
# Gate Evaluation
# ============================================================

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days, top1_fold_conc):
    """Evaluate gates G1-G8 (except G7 which is neighborhood stability)."""
    gates = {
        'G1_trades_per_week':   {'value': metrics['trades_per_week'],   'threshold': '>=0.5/wk',
                                 'pass': metrics['trades_per_week'] >= 0.5},
        'G2_max_gap_days':      {'value': max_gap_days,                'threshold': '<=21d',
                                 'pass': max_gap_days <= 21},
        'G3_exp_per_week_mkt':  {'value': metrics['exp_per_week'],     'threshold': '>$0',
                                 'pass': metrics['exp_per_week'] > 0},
        'G4_exp_per_week_2x':   {'value': stress_metrics['exp_per_week'], 'threshold': '>$0',
                                 'pass': stress_metrics['exp_per_week'] > 0},
        'G5_max_dd_pct':        {'value': metrics['dd'],               'threshold': '<=50%',
                                 'pass': metrics['dd'] <= 50},
        'G6_wf_folds_positive': {'value': wf_folds_positive,          'threshold': '>=3/5',
                                 'pass': wf_folds_positive >= 3},
        'G8_top1_fold_conc':    {'value': top1_fold_conc,             'threshold': '<0.60',
                                 'pass': top1_fold_conc < 0.60},
    }
    all_pass = all(g['pass'] for g in gates.values())
    failed = [k for k, g in gates.items() if not g['pass']]
    return gates, all_pass, failed


# ============================================================
# Full Variant Analysis
# ============================================================

def analyze_variant(label, params, data, tier_coins, tier_indicators, market_ctx,
                    tier1_fee, tier2_fee, stress_t1_fee, stress_t2_fee, total_bars,
                    t1_coins_override=None, t2_coins_override=None):
    """Run complete analysis for one variant: baseline, WF, stress, gates, HHI."""
    t1_coins = t1_coins_override if t1_coins_override is not None else tier_coins.get('tier1', [])
    t2_coins = t2_coins_override if t2_coins_override is not None else tier_coins.get('tier2', [])
    n_t1 = len(t1_coins)
    n_t2 = len(t2_coins)
    n_total = n_t1 + n_t2

    print(f'\n  {"="*60}')
    print(f'  {label}: T1={n_t1}, T2={n_t2}, total={n_total}')
    print(f'  {"="*60}')

    # --- Baseline ---
    print(f'  [1/4] Baseline...')
    t1 = time.time()
    trades = run_combined_backtest(params, data, tier_coins, tier_indicators,
                                    market_ctx, tier1_fee, tier2_fee,
                                    t1_coins, t2_coins)
    m = compute_metrics(trades, total_bars)
    max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    cb = compute_coin_breakdown(trades)
    hhi = compute_hhi(trades)
    print(f'    {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% '
          f'PnL=${m["pnl"]:.2f} Exp/wk=${m["exp_per_week"]:.4f} DD={m["dd"]:.1f}% '
          f'HHI={hhi:.4f} ({time.time()-t1:.1f}s)')

    # --- Walk-Forward ---
    print(f'  [2/4] Walk-Forward 5-fold...')
    t2_start = time.time()
    fold_trades = run_combined_walk_forward(params, data, tier_coins, tier_indicators,
                                             market_ctx, tier1_fee, tier2_fee,
                                             n_folds=5, t1_coins_override=t1_coins,
                                             t2_coins_override=t2_coins)
    folds_positive = 0
    fold_details = []
    for fi in sorted(fold_trades.keys()):
        fpnl = sum(t['pnl'] for t in fold_trades[fi])
        fn = len(fold_trades[fi])
        pos = fpnl > 0
        if pos:
            folds_positive += 1
        fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos})
    top1_fold_conc = compute_top1_fold_concentration(fold_details)
    print(f'    WF: {folds_positive}/5 | Top-1 fold conc: {top1_fold_conc:.2%} ({time.time()-t2_start:.1f}s)')
    for fd in fold_details:
        tag = 'YES' if fd['positive'] else 'NO'
        print(f'      Fold {fd["fold"]}: {fd["trades"]}tr ${fd["pnl"]:.2f} ({tag})')

    # --- Stress 2x ---
    print(f'  [3/4] Stress 2x...')
    t3 = time.time()
    stress_trades = run_combined_stress(params, data, tier_coins, tier_indicators,
                                         market_ctx, stress_t1_fee, stress_t2_fee,
                                         t1_coins, t2_coins)
    sm = compute_metrics(stress_trades, total_bars)
    print(f'    {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.4f} DD={sm["dd"]:.1f}% '
          f'({time.time()-t3:.1f}s)')

    # --- Gate evaluation ---
    gates, all_pass, failed = evaluate_gates(m, sm, folds_positive, max_gap_days, top1_fold_conc)
    verdict = 'PASS' if all_pass else 'FAIL'
    print(f'  [4/4] Gates:')
    for gname, gv in gates.items():
        tag = 'PASS' if gv['pass'] else 'FAIL'
        print(f'    {gname}: {gv["value"]} {gv["threshold"]} -> {tag}')
    print(f'  VERDICT: {verdict}')
    if failed:
        print(f'  Failed: {", ".join(failed)}')

    return {
        'label': label,
        'coins_t1': n_t1,
        'coins_t2': n_t2,
        'coins_total': n_total,
        'baseline': m,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'walk_forward': {
            'folds_positive': folds_positive, 'folds_total': 5,
            'fold_details': fold_details,
            'top1_fold_concentration': top1_fold_conc,
        },
        'stress_2x': {
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'wr': sm['wr'], 'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
        'coin_breakdown': cb,
        'hhi': hhi,
        'hhi_interpretation': hhi_interpretation(hhi, cb['coins_with_trades']),
        'gates': gates,
        'verdict': verdict,
        'failed_gates': failed,
    }


# ============================================================
# Markdown Report Builder
# ============================================================

def build_md(report, variants, elapsed, commit, n_t1, n_t2, total_bars, total_weeks,
             tier1_fee, tier2_fee):
    md = []
    md.append('# Part 2: T1 Concentration Risk Analysis')
    md.append('')
    md.append('## Objective')
    md.append('')
    md.append('XL1/USD accounts for 48.3% of T1 P&L ($549 of $1058). This analysis')
    md.append('studies whether the strategy remains viable when top T1 contributors are')
    md.append('excluded, to quantify concentration risk and determine if T1 edge is')
    md.append('dependent on a single coin.')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps/side, T2={tier2_fee*10000:.1f}bps/side')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # ---- Comparison table ----
    md.append('## Comparison Table: All Variants')
    md.append('')
    headers = ['Metric'] + [v['label'] for v in variants]
    md.append('| ' + ' | '.join(headers) + ' |')
    md.append('|' + '|'.join(['--------'] * len(headers)) + '|')

    rows = [
        ('Coins (T1+T2)', lambda v: f'{v["coins_t1"]}+{v["coins_t2"]}={v["coins_total"]}'),
        ('Trades', lambda v: str(v['baseline']['trades'])),
        ('PnL ($)', lambda v: f'${v["baseline"]["pnl"]:.2f}'),
        ('PF', lambda v: f'{v["baseline"]["pf"]:.3f}'),
        ('WR (%)', lambda v: f'{v["baseline"]["wr"]:.1f}'),
        ('Exp/Wk ($)', lambda v: f'${v["baseline"]["exp_per_week"]:.4f}'),
        ('Tr/Wk', lambda v: f'{v["baseline"]["trades_per_week"]:.2f}'),
        ('DD (%)', lambda v: f'{v["baseline"]["dd"]:.1f}'),
        ('Max Gap (d)', lambda v: str(v['max_gap']['days'])),
        ('WF (+/5)', lambda v: f'{v["walk_forward"]["folds_positive"]}/5'),
        ('Fold Conc', lambda v: f'{v["walk_forward"]["top1_fold_concentration"]:.2%}'),
        ('Stress PF', lambda v: f'{v["stress_2x"]["pf"]:.3f}'),
        ('Stress Exp/Wk', lambda v: f'${v["stress_2x"]["exp_per_week"]:.4f}'),
        ('HHI', lambda v: f'{v["hhi"]:.4f}'),
        ('HHI Class', lambda v: v['hhi_interpretation']),
        ('Gates', lambda v: v['verdict']),
    ]
    for row_name, accessor in rows:
        vals = [accessor(v) for v in variants]
        md.append('| ' + row_name + ' | ' + ' | '.join(vals) + ' |')
    md.append('')

    # ---- Per-variant gate tables ----
    md.append('## Per-Variant Gate Details')
    md.append('')
    for v in variants:
        md.append(f'### {v["label"]} ({v["verdict"]})')
        md.append('')
        md.append('| Gate | Value | Threshold | Result |')
        md.append('|------|-------|-----------|--------|')
        for gname, gv in v['gates'].items():
            tag = 'PASS' if gv['pass'] else '**FAIL**'
            val = gv['value']
            if isinstance(val, float):
                val = f'{val:.4f}' if abs(val) < 10 else f'{val:.1f}'
            md.append(f'| {gname} | {val} | {gv["threshold"]} | {tag} |')
        if v['failed_gates']:
            md.append(f'\nFailed: {", ".join(v["failed_gates"])}')
        md.append('')

    # ---- Walk-Forward detail ----
    md.append('## Walk-Forward Detail (5-Fold)')
    md.append('')
    wf_headers = ['Fold'] + [v['label'] for v in variants]
    md.append('| ' + ' | '.join(wf_headers) + ' |')
    md.append('|' + '|'.join(['------'] * len(wf_headers)) + '|')
    for fi in range(5):
        vals = []
        for v in variants:
            fd = v['walk_forward']['fold_details']
            if fi < len(fd):
                tag = '+' if fd[fi]['positive'] else '-'
                vals.append(f'{fd[fi]["trades"]}tr ${fd[fi]["pnl"]:.0f} ({tag})')
            else:
                vals.append('-')
        md.append(f'| {fi} | ' + ' | '.join(vals) + ' |')
    md.append('')

    # ---- HHI Analysis ----
    md.append('## HHI Concentration Analysis')
    md.append('')
    md.append('The Herfindahl-Hirschman Index (HHI) measures P&L concentration across coins.')
    md.append('HHI uses positive profit attribution (only winning P&L counts).')
    md.append('')
    md.append('| Variant | HHI | Interpretation | Coins Active | Top-1 Coin Conc | Top-3 Coin Conc |')
    md.append('|---------|-----|---------------|-------------|----------------|----------------|')
    for v in variants:
        cb = v['coin_breakdown']
        md.append(f'| {v["label"]} | {v["hhi"]:.4f} | {v["hhi_interpretation"]} | '
                  f'{cb["coins_with_trades"]} | {cb["top1_coin_conc"]:.1%} | {cb["top3_coin_conc"]:.1%} |')
    md.append('')
    md.append('**HHI thresholds**: <0.10 = diversified, 0.10-0.15 = mildly concentrated, ')
    md.append('0.15-0.25 = moderately concentrated, >0.25 = highly concentrated.')
    md.append('')

    # ---- Top coin attribution per variant ----
    md.append('## Per-Variant Top Coin Attribution')
    md.append('')
    for v in variants:
        cb = v['coin_breakdown']
        md.append(f'### {v["label"]}')
        md.append('')
        if cb['top5']:
            md.append('**Top 5:**')
            for c in cb['top5']:
                md.append(f'- {c["coin"]}: ${c["pnl"]:.2f}')
            md.append('')
        if cb['worst5']:
            md.append('**Worst 5:**')
            for c in cb['worst5']:
                md.append(f'- {c["coin"]}: ${c["pnl"]:.2f}')
            md.append('')

    # ---- Impact Analysis ----
    md.append('## Impact Analysis')
    md.append('')
    baseline = variants[0]  # Full 295
    for v in variants[1:]:
        delta_pnl = v['baseline']['pnl'] - baseline['baseline']['pnl']
        delta_trades = v['baseline']['trades'] - baseline['baseline']['trades']
        delta_pf = v['baseline']['pf'] - baseline['baseline']['pf']
        pnl_pct = delta_pnl / baseline['baseline']['pnl'] * 100 if baseline['baseline']['pnl'] != 0 else 0
        md.append(f'**{v["label"]} vs Baseline:**')
        md.append(f'- PnL delta: ${delta_pnl:+.2f} ({pnl_pct:+.1f}%)')
        md.append(f'- Trade delta: {delta_trades:+d}')
        md.append(f'- PF delta: {delta_pf:+.3f}')
        md.append(f'- HHI: {v["hhi"]:.4f} vs {baseline["hhi"]:.4f} '
                  f'({"better" if v["hhi"] < baseline["hhi"] else "worse"} diversification)')
        md.append(f'- Gates: {v["verdict"]} (baseline: {baseline["verdict"]})')
        md.append('')

    # ---- Verdict ----
    md.append('## Verdict: T1 Concentration Risk')
    md.append('')

    no_xl1 = variants[1]  # excl XL1/USD
    no_top3 = variants[2]  # excl top-3 T1
    t2_only = variants[3]  # T2-only

    # Determine verdict
    xl1_impact_pct = ((no_xl1['baseline']['pnl'] - baseline['baseline']['pnl'])
                      / baseline['baseline']['pnl'] * 100) if baseline['baseline']['pnl'] != 0 else 0

    md.append(f'1. **XL1/USD exclusion impact**: ${no_xl1["baseline"]["pnl"] - baseline["baseline"]["pnl"]:+.2f} '
              f'({xl1_impact_pct:+.1f}% of total PnL)')
    md.append(f'   - Gates: {no_xl1["verdict"]}')
    md.append(f'   - Strategy {"SURVIVES" if no_xl1["verdict"] == "PASS" else "FAILS"} without XL1/USD')
    md.append('')

    top3_impact_pct = ((no_top3['baseline']['pnl'] - baseline['baseline']['pnl'])
                       / baseline['baseline']['pnl'] * 100) if baseline['baseline']['pnl'] != 0 else 0
    md.append(f'2. **Top-3 T1 exclusion impact**: ${no_top3["baseline"]["pnl"] - baseline["baseline"]["pnl"]:+.2f} '
              f'({top3_impact_pct:+.1f}% of total PnL)')
    md.append(f'   - Gates: {no_top3["verdict"]}')
    md.append(f'   - Strategy {"SURVIVES" if no_top3["verdict"] == "PASS" else "STRUGGLES"} without top-3 T1 coins')
    md.append('')

    t2_only_pct = (t2_only['baseline']['pnl'] / baseline['baseline']['pnl'] * 100
                   if baseline['baseline']['pnl'] != 0 else 0)
    md.append(f'3. **T2-only viability**: ${t2_only["baseline"]["pnl"]:.2f} '
              f'({t2_only_pct:.1f}% of baseline PnL)')
    md.append(f'   - Gates: {t2_only["verdict"]}')
    md.append(f'   - T2 alone {"IS" if t2_only["verdict"] == "PASS" else "IS NOT"} viable as standalone')
    md.append('')

    # Overall risk assessment
    if no_xl1['verdict'] == 'PASS' and no_top3['verdict'] == 'PASS':
        md.append('**OVERALL**: T1 concentration risk is **MANAGEABLE**. The strategy passes all gates')
        md.append('even without the top-3 T1 contributors. The edge is distributed, not concentrated.')
    elif no_xl1['verdict'] == 'PASS':
        md.append('**OVERALL**: T1 concentration risk is **MODERATE**. Strategy survives without XL1/USD')
        md.append('but removing all top-3 T1 coins degrades performance below gate thresholds.')
    else:
        md.append('**OVERALL**: T1 concentration risk is **HIGH**. Strategy cannot pass gates')
        md.append('without XL1/USD. The T1 edge is critically dependent on one coin.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_t1_concentration.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2: T1 Concentration Risk Analysis',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2: T1 Concentration Risk Analysis')
    print('  XL1/USD = 48.3% of T1 P&L — is this a problem?')
    print('=' * 70)
    t0 = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    print(f'[Costs] MEXC Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')

    stress_regime = stress_multiplier('mexc_market', 2.0)
    stress_t1_fee = stress_regime['tier1']['total_per_side_bps'] / 10000.0
    stress_t2_fee = stress_regime['tier2']['total_per_side_bps'] / 10000.0
    print(f'[Stress] 2x: T1={stress_t1_fee*10000:.1f}bps, T2={stress_t2_fee*10000:.1f}bps')

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

    # --- Apply 21-coin exclusion ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (after exclusion)')

    # Check which top-3 coins exist in T1
    for coin in sorted(TOP3_T1_COINS):
        in_t1 = coin in tier_coins['tier1']
        in_data = coin in available_coins
        print(f'  {coin}: in_T1={in_t1}, in_data={in_data}')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    if args.dry_run:
        print(f'\n[DRY RUN] Would run 4 variants on T1({n_t1})+T2({n_t2})={n_total}:')
        print(f'  1. Baseline (full 295)')
        print(f'  2. Excl XL1/USD')
        print(f'  3. Excl top-3 T1 (XL1/USD, GHIBLI/USD, XAN/USD)')
        print(f'  4. T2-only ({n_t2} coins)')
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
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
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
            ind = indicators.get(coin, {})
            n = ind.get('n', 0)
            if n > total_bars:
                total_bars = n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ============================================================
    # Define variants
    # ============================================================

    # Build coin lists for each variant
    # V1: Baseline (all T1 + T2)
    v1_t1 = tier_coins['tier1']
    v1_t2 = tier_coins['tier2']

    # V2: Exclude XL1/USD
    v2_t1 = [c for c in tier_coins['tier1'] if c != 'XL1/USD']
    v2_t2 = tier_coins['tier2']  # T2 unchanged

    # V3: Exclude top-3 T1 coins
    v3_t1 = [c for c in tier_coins['tier1'] if c not in TOP3_T1_COINS]
    v3_t2 = tier_coins['tier2']  # T2 unchanged

    # V4: T2-only
    v4_t1 = []
    v4_t2 = tier_coins['tier2']

    variant_defs = [
        ('Baseline (295)', v1_t1, v1_t2),
        ('Excl XL1/USD', v2_t1, v2_t2),
        ('Excl Top-3 T1', v3_t1, v3_t2),
        ('T2-Only', v4_t1, v4_t2),
    ]

    # ============================================================
    # Run all variants
    # ============================================================

    variant_results = []
    for label, t1_c, t2_c in variant_defs:
        result = analyze_variant(
            label, PARAMS_V5, data, tier_coins, tier_indicators, market_context,
            tier1_fee, tier2_fee, stress_t1_fee, stress_t2_fee, total_bars,
            t1_coins_override=t1_c, t2_coins_override=t2_c,
        )
        variant_results.append(result)

    elapsed = time.time() - t0

    # ============================================================
    # Save Reports
    # ============================================================

    report = {
        'run_header': {
            'task': 'part2_t1_concentration',
            'status': 'DONE',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'fees': {
                'tier1_bps': round(tier1_fee * 10000, 1),
                'tier2_bps': round(tier2_fee * 10000, 1),
            },
            'stress_fees': {
                'tier1_bps': round(stress_t1_fee * 10000, 1),
                'tier2_bps': round(stress_t2_fee * 10000, 1),
            },
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
            'top3_t1_coins': sorted(TOP3_T1_COINS),
        },
        'variants': variant_results,
        'concentration_analysis': {
            'xl1_pnl_share_of_baseline': round(
                (variant_results[0]['baseline']['pnl'] - variant_results[1]['baseline']['pnl'])
                / variant_results[0]['baseline']['pnl'] * 100
                if variant_results[0]['baseline']['pnl'] != 0 else 0, 2),
            'top3_t1_pnl_share_of_baseline': round(
                (variant_results[0]['baseline']['pnl'] - variant_results[2]['baseline']['pnl'])
                / variant_results[0]['baseline']['pnl'] * 100
                if variant_results[0]['baseline']['pnl'] != 0 else 0, 2),
            't2_only_pnl_share_of_baseline': round(
                variant_results[3]['baseline']['pnl']
                / variant_results[0]['baseline']['pnl'] * 100
                if variant_results[0]['baseline']['pnl'] != 0 else 0, 2),
            'hhi_comparison': {
                v['label']: {'hhi': v['hhi'], 'interpretation': v['hhi_interpretation']}
                for v in variant_results
            },
        },
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / REPORT_JSON
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md = build_md(report, variant_results, elapsed, commit, n_t1, n_t2,
                  total_bars, total_weeks, tier1_fee, tier2_fee)
    md_path = out_dir / REPORT_MD
    md_path.write_text(md)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{"="*70}')
    print(f'  T1 CONCENTRATION RISK ANALYSIS COMPLETE')
    print(f'{"="*70}')

    for v in variant_results:
        print(f'\n  {v["label"]} (T1={v["coins_t1"]}, T2={v["coins_t2"]}):')
        print(f'    {v["baseline"]["trades"]}tr PF={v["baseline"]["pf"]:.3f} '
              f'PnL=${v["baseline"]["pnl"]:.2f} Exp/wk=${v["baseline"]["exp_per_week"]:.4f} '
              f'DD={v["baseline"]["dd"]:.1f}%')
        print(f'    WF: {v["walk_forward"]["folds_positive"]}/5 | '
              f'HHI={v["hhi"]:.4f} ({v["hhi_interpretation"]}) | '
              f'Verdict: {v["verdict"]}')

    # Quick concentration summary
    print(f'\n  Concentration Impact:')
    baseline_pnl = variant_results[0]['baseline']['pnl']
    for v in variant_results[1:]:
        delta = v['baseline']['pnl'] - baseline_pnl
        pct = delta / baseline_pnl * 100 if baseline_pnl != 0 else 0
        print(f'    {v["label"]}: ${delta:+.2f} ({pct:+.1f}%) -> {v["verdict"]}')

    print(f'\n  Runtime: {elapsed:.1f}s')
    print(f'{"="*70}')


if __name__ == '__main__':
    main()
