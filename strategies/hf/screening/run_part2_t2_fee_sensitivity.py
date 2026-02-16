#!/usr/bin/env python3
"""
Part 2: T2 Fee Sensitivity Analysis
====================================
Agent C6-A2: T2 contributes 67.7% of P&L but has 14.5% fee drag (vs T1's 6.6%).
What happens at different T2 fee levels? At what T2 fee does the strategy break?

Sweep:
  - 15 T2 fee levels (0 to 100 bps/side) while T1 stays at 12.5bps
  - Full backtest + WF 5-fold + gate evaluation at each level
  - Binary search for exact T2 breakeven fee (where G3 or G4 first fails)
  - Gate transition table: at which fee level each gate first fails
  - "Better fees" scenario: what if T2 gets MEXC 0% maker treatment

Output:
  reports/hf/part2_t2_fee_sensitivity_001.json
  reports/hf/part2_t2_fee_sensitivity_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_t2_fee_sensitivity.py
    python strategies/hf/screening/run_part2_t2_fee_sensitivity.py --dry-run
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

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168   # 24 * 7
BARS_PER_DAY = 24

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

T1_FEE_BPS = 12.5   # Fixed: T1 always at 12.5 bps/side
T1_FEE = T1_FEE_BPS / 10000.0

CURRENT_T2_BPS = 23.5  # Current T2 fee

# 15 T2 fee levels to sweep (bps/side)
T2_FEE_LEVELS_BPS = [
    0, 5, 10, 12.5, 15, 20, 23.5, 30, 40, 50, 60, 70, 80, 90, 100,
]

EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}


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

def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                 market_ctx, t1_fee, t2_fee, params):
    """Run backtests for T1 and T2 separately, merge trade lists."""
    enriched = {**params, '__market__': market_ctx}
    all_trades = []

    # T1
    if t1_coins:
        bt_t1 = run_backtest(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1,
        )
        for t in bt_t1.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = t1_fee
        all_trades.extend(bt_t1.trade_list)

    # T2
    if t2_coins:
        bt_t2 = run_backtest(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, fee=t2_fee, max_pos=1,
        )
        for t in bt_t2.trade_list:
            t['_tier'] = 'tier2'
            t['_fee_per_side'] = t2_fee
        all_trades.extend(bt_t2.trade_list)

    return all_trades


def run_combined_wf(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                    market_ctx, t1_fee, t2_fee, params, n_folds=5):
    """Run walk-forward for T1 and T2 separately, merge fold trades."""
    enriched = {**params, '__market__': market_ctx}
    fold_trades = {}

    # T1 WF
    if t1_coins:
        t1_results = walk_forward(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, n_folds=n_folds,
            fee=t1_fee, max_pos=1,
        )
        for idx, fold_bt in enumerate(t1_results):
            if idx not in fold_trades:
                fold_trades[idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = 'tier1'
                t['_fee_per_side'] = t1_fee
            fold_trades[idx].extend(fold_bt.trade_list)

    # T2 WF
    if t2_coins:
        t2_results = walk_forward(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, n_folds=n_folds,
            fee=t2_fee, max_pos=1,
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
# Metrics
# ============================================================

def compute_metrics(trades, total_bars, initial_capital=2000.0):
    n = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n == 0:
        return dict(trades=0, pnl=0.0, pf=0.0, wr=0.0, dd=0.0,
                    expectancy=0.0, trades_per_week=0.0, exp_per_week=0.0,
                    fee_drag_pct=0.0)
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n
    tpw = n / total_weeks
    epw = expectancy * tpw
    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        tfee = t.get('_fee_per_side', T1_FEE)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * tfee + (size + gross) * tfee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
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
        trades=n, pnl=round(total_pnl, 2), pf=round(pf, 3), wr=round(wr, 1),
        dd=round(max_dd, 1), expectancy=round(expectancy, 4),
        trades_per_week=round(tpw, 2), exp_per_week=round(epw, 4),
        fee_drag_pct=round(fee_drag, 1),
    )


def tier_pnl_breakdown(trades):
    t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
    t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
    t1_pnl = sum(t['pnl'] for t in t1_trades)
    t2_pnl = sum(t['pnl'] for t in t2_trades)
    total_pnl = t1_pnl + t2_pnl
    return {
        'tier1': {'trades': len(t1_trades), 'pnl': round(t1_pnl, 2)},
        'tier2': {'trades': len(t2_trades), 'pnl': round(t2_pnl, 2)},
        'total': {'trades': len(trades), 'pnl': round(total_pnl, 2)},
        't2_pnl_share': round(t2_pnl / total_pnl * 100 if total_pnl != 0 else 0, 1),
    }


def compute_max_gap(trades, total_bars):
    if not trades:
        return total_bars, round(total_bars / BARS_PER_DAY, 2)
    entry_bars = sorted(t['entry_bar'] for t in trades)
    gaps = [entry_bars[i+1] - entry_bars[i] for i in range(len(entry_bars) - 1)]
    gaps.append(entry_bars[0])
    gaps.append(total_bars - entry_bars[-1])
    max_gap = max(gaps) if gaps else total_bars
    return max_gap, round(max_gap / BARS_PER_DAY, 2)


def compute_fold_concentration(fold_pnls):
    """Top-1 fold concentration among positive folds."""
    positive_pnls = [max(0, p) for p in fold_pnls]
    total_pos = sum(positive_pnls)
    if total_pos <= 0:
        return 1.0
    return max(positive_pnls) / total_pos


# ============================================================
# Gate Evaluation
# ============================================================

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days,
                   top1_fold_conc, total_bars):
    """Evaluate gates G1-G8 (except G7)."""
    gates = {
        'G1_trades_per_week': {
            'value': round(metrics['trades_per_week'], 2),
            'threshold': '>=0.5/wk',
            'pass': metrics['trades_per_week'] >= 0.5,
        },
        'G2_max_gap_days': {
            'value': max_gap_days,
            'threshold': '<=21d',
            'pass': max_gap_days <= 21,
        },
        'G3_exp_per_week': {
            'value': round(metrics['exp_per_week'], 4),
            'threshold': '>$0',
            'pass': metrics['exp_per_week'] > 0,
        },
        'G4_stress_exp_per_week': {
            'value': round(stress_metrics['exp_per_week'], 4),
            'threshold': '>$0',
            'pass': stress_metrics['exp_per_week'] > 0,
        },
        'G5_max_dd_pct': {
            'value': round(metrics['dd'], 1),
            'threshold': '<=50%',
            'pass': metrics['dd'] <= 50,
        },
        'G6_wf_folds_positive': {
            'value': wf_folds_positive,
            'threshold': '>=3/5',
            'pass': wf_folds_positive >= 3,
        },
        'G8_top1_fold_conc': {
            'value': round(top1_fold_conc, 4),
            'threshold': '<0.60',
            'pass': top1_fold_conc < 0.60,
        },
    }
    all_pass = all(g['pass'] for g in gates.values())
    failed = [k for k, g in gates.items() if not g['pass']]
    return gates, all_pass, failed


# ============================================================
# Full Analysis at a Given T2 Fee Level
# ============================================================

def analyze_fee_level(t2_bps, data, t1_coins, t2_coins,
                      t1_indicators, t2_indicators, market_ctx,
                      total_bars, run_wf=True):
    """Run full analysis at a specific T2 fee level."""
    t2_fee = t2_bps / 10000.0
    t_start = time.time()

    # --- Baseline ---
    trades = run_combined(data, t1_coins, t2_coins,
                          t1_indicators, t2_indicators, market_ctx,
                          T1_FEE, t2_fee, PARAMS_V5)
    m = compute_metrics(trades, total_bars)
    tb = tier_pnl_breakdown(trades)
    max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)

    # --- Stress 2x T2 fee ---
    stress_t2_fee = t2_fee * 2
    stress_trades = run_combined(data, t1_coins, t2_coins,
                                  t1_indicators, t2_indicators, market_ctx,
                                  T1_FEE, stress_t2_fee, PARAMS_V5)
    sm = compute_metrics(stress_trades, total_bars)

    # --- Walk-Forward 5-fold ---
    wf_folds_positive = 0
    fold_pnls = []
    fold_details = []
    top1_fold_conc = 1.0

    if run_wf:
        fold_trades = run_combined_wf(data, t1_coins, t2_coins,
                                       t1_indicators, t2_indicators, market_ctx,
                                       T1_FEE, t2_fee, PARAMS_V5, n_folds=5)
        for fi in sorted(fold_trades.keys()):
            fpnl = sum(t['pnl'] for t in fold_trades[fi])
            fn = len(fold_trades[fi])
            pos = fpnl > 0
            if pos:
                wf_folds_positive += 1
            fold_pnls.append(fpnl)
            fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2),
                                 'positive': pos})
        top1_fold_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    else:
        # Lightweight: skip WF, use baseline metrics only
        wf_folds_positive = -1  # sentinel: not computed
        fold_details = []
        top1_fold_conc = -1

    # --- Gate evaluation ---
    gates, all_pass, failed = evaluate_gates(
        m, sm, wf_folds_positive, max_gap_days, top1_fold_conc, total_bars,
    )

    elapsed = time.time() - t_start

    return {
        't2_fee_bps': t2_bps,
        't1_fee_bps': T1_FEE_BPS,
        'baseline': m,
        'tier_breakdown': tb,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'stress_2x': {
            'fee_bps': round(stress_t2_fee * 10000, 1),
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
        'walk_forward': {
            'folds_positive': wf_folds_positive,
            'fold_details': fold_details,
            'top1_fold_conc': round(top1_fold_conc, 4) if top1_fold_conc >= 0 else None,
        },
        'gates': gates,
        'all_gates_pass': all_pass,
        'failed_gates': failed,
        'runtime_s': round(elapsed, 1),
    }


# ============================================================
# Binary Search for T2 Breakeven Fee
# ============================================================

def find_t2_breakeven(data, t1_coins, t2_coins,
                      t1_indicators, t2_indicators, market_ctx,
                      total_bars, gate='G3', tol_bps=0.5, max_iter=20):
    """Binary search for T2 fee where a specific gate first fails.

    G3 = exp/wk <= 0 (baseline profitability)
    G4 = stress exp/wk <= 0 (2x stress profitability)

    Returns (breakeven_bps, iterations, last_exp_per_week)
    """
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0

    # Start from current (23.5) and go up
    lo = CURRENT_T2_BPS
    hi = 500.0  # Extend to 500 bps to find true breakeven

    # Check that lo passes
    lo_result = analyze_fee_level(lo, data, t1_coins, t2_coins,
                                   t1_indicators, t2_indicators, market_ctx,
                                   total_bars, run_wf=False)
    if gate == 'G3':
        lo_passes = lo_result['baseline']['exp_per_week'] > 0
    elif gate == 'G4':
        lo_passes = lo_result['stress_2x']['exp_per_week'] > 0
    else:
        lo_passes = lo_result['all_gates_pass']

    if not lo_passes:
        # Already failing at current fee
        return lo, 0, lo_result['baseline']['exp_per_week']

    # Check that hi fails
    hi_result = analyze_fee_level(hi, data, t1_coins, t2_coins,
                                   t1_indicators, t2_indicators, market_ctx,
                                   total_bars, run_wf=False)
    if gate == 'G3':
        hi_passes = hi_result['baseline']['exp_per_week'] > 0
    elif gate == 'G4':
        hi_passes = hi_result['stress_2x']['exp_per_week'] > 0
    else:
        hi_passes = hi_result['all_gates_pass']

    if hi_passes:
        return hi, 0, hi_result['baseline']['exp_per_week']

    # Binary search
    iterations = 0
    last_epw = 0.0
    for _ in range(max_iter):
        iterations += 1
        mid = (lo + hi) / 2.0
        mid_result = analyze_fee_level(mid, data, t1_coins, t2_coins,
                                        t1_indicators, t2_indicators, market_ctx,
                                        total_bars, run_wf=False)
        if gate == 'G3':
            mid_passes = mid_result['baseline']['exp_per_week'] > 0
            last_epw = mid_result['baseline']['exp_per_week']
        elif gate == 'G4':
            mid_passes = mid_result['stress_2x']['exp_per_week'] > 0
            last_epw = mid_result['stress_2x']['exp_per_week']
        else:
            mid_passes = mid_result['all_gates_pass']
            last_epw = mid_result['baseline']['exp_per_week']

        if mid_passes:
            lo = mid
        else:
            hi = mid

        if (hi - lo) < tol_bps:
            break

    return round((lo + hi) / 2.0, 1), iterations, round(last_epw, 4)


# ============================================================
# Markdown Report Builder
# ============================================================

def build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks):
    md = []
    md.append('# Part 2: T2 Fee Sensitivity Analysis')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Agent**: C6-A2')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**T1 Fee**: Fixed at {T1_FEE_BPS} bps/side (all levels)')
    md.append(f'**T2 Fee**: Variable (0 to 100 bps/side)')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # ---- Objective ----
    md.append('## Objective')
    md.append('')
    md.append('T2 contributes ~67.7% of total P&L but bears 14.5% fee drag (vs T1\'s 6.6%).')
    md.append('This analysis isolates T2 fee sensitivity by sweeping T2 fees from 0 to 100 bps/side')
    md.append('while holding T1 constant at 12.5 bps/side. Key questions:')
    md.append('')
    md.append('1. At what T2 fee does the combined strategy break even (G3 fails)?')
    md.append('2. How much fee margin exists before each gate fails?')
    md.append('3. How much would the strategy improve with better T2 fees?')
    md.append('')

    # ---- Fee Ladder Table ----
    md.append('## Fee Ladder (15 T2 Fee Levels)')
    md.append('')
    md.append('| T2 bps | Trades | PF | WR% | P&L | Exp/Wk | DD% | Fee Drag | T2 P&L | T2 Share | WF | Gates |')
    md.append('|--------|--------|----|-----|-----|--------|-----|----------|--------|----------|-------|-------|')

    ladder = report['fee_ladder']
    for level in ladder:
        m = level['baseline']
        tb = level['tier_breakdown']
        wf_str = f'{level["walk_forward"]["folds_positive"]}/5' if level['walk_forward']['folds_positive'] >= 0 else 'N/A'
        gates_str = 'ALL PASS' if level['all_gates_pass'] else f'FAIL: {", ".join(level["failed_gates"])}'
        md.append(
            f'| {level["t2_fee_bps"]:.1f} | {m["trades"]} | {m["pf"]:.3f} | {m["wr"]:.1f} '
            f'| ${m["pnl"]:.0f} | ${m["exp_per_week"]:.2f} | {m["dd"]:.1f} | {m["fee_drag_pct"]:.1f}% '
            f'| ${tb["tier2"]["pnl"]:.0f} | {tb["t2_pnl_share"]:.1f}% '
            f'| {wf_str} | {gates_str} |'
        )
    md.append('')

    # ---- Gate Transition Table ----
    md.append('## Gate Transition Table')
    md.append('')
    md.append('At which T2 fee level does each gate FIRST fail?')
    md.append('')
    md.append('| Gate | First Fails At | Current (23.5) | Margin |')
    md.append('|------|---------------|----------------|--------|')

    gate_transitions = report['gate_transitions']
    for gate_name, info in sorted(gate_transitions.items()):
        if info['first_fail_bps'] is None:
            md.append(f'| {gate_name} | Never (survives 100 bps) | PASS | >76.5 bps |')
        else:
            margin = info['first_fail_bps'] - CURRENT_T2_BPS
            status = 'PASS' if info['passes_at_current'] else 'FAIL'
            md.append(
                f'| {gate_name} | {info["first_fail_bps"]:.1f} bps | {status} '
                f'| {margin:+.1f} bps |'
            )
    md.append('')

    # ---- Breakeven Analysis ----
    md.append('## Breakeven Analysis (Binary Search)')
    md.append('')
    be = report['breakeven']
    md.append(f'| Metric | G3 (Profitability) | G4 (Stress 2x) |')
    md.append(f'|--------|-------------------|----------------|')
    md.append(f'| Breakeven T2 fee | **{be["G3"]["breakeven_bps"]:.1f} bps** | **{be["G4"]["breakeven_bps"]:.1f} bps** |')
    md.append(f'| Margin from current | +{be["G3"]["breakeven_bps"] - CURRENT_T2_BPS:.1f} bps | +{be["G4"]["breakeven_bps"] - CURRENT_T2_BPS:.1f} bps |')
    md.append(f'| Multiplier vs current | {be["G3"]["breakeven_bps"] / CURRENT_T2_BPS:.2f}x | {be["G4"]["breakeven_bps"] / CURRENT_T2_BPS:.2f}x |')
    md.append(f'| Iterations | {be["G3"]["iterations"]} | {be["G4"]["iterations"]} |')
    md.append('')

    # ---- Better Fees Scenario ----
    md.append('## "Better Fees" Scenario: What If T2 Gets Cheaper?')
    md.append('')
    md.append('| T2 bps | Scenario | P&L | vs Current | PF | Exp/Wk | Fee Drag |')
    md.append('|--------|----------|-----|------------|----|---------|-----------| ')

    current_pnl = None
    for level in ladder:
        if level['t2_fee_bps'] == CURRENT_T2_BPS:
            current_pnl = level['baseline']['pnl']
            break

    for level in ladder:
        if level['t2_fee_bps'] <= CURRENT_T2_BPS:
            m = level['baseline']
            delta = m['pnl'] - (current_pnl or 0)
            scenario = 'CURRENT' if level['t2_fee_bps'] == CURRENT_T2_BPS else (
                'MEXC 0% maker' if level['t2_fee_bps'] == 0 else
                f'Reduced fees' if level['t2_fee_bps'] < CURRENT_T2_BPS else 'Baseline'
            )
            md.append(
                f'| {level["t2_fee_bps"]:.1f} | {scenario} | ${m["pnl"]:.0f} '
                f'| {delta:+.0f} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} '
                f'| {m["fee_drag_pct"]:.1f}% |'
            )
    md.append('')

    # ---- Fee Margin Summary ----
    md.append('## Fee Margin Summary')
    md.append('')
    md.append(f'- **Current T2 fee**: {CURRENT_T2_BPS} bps/side')
    md.append(f'- **G3 breakeven** (combined exp/wk > $0): {be["G3"]["breakeven_bps"]:.1f} bps/side')
    md.append(f'- **G4 breakeven** (stress 2x exp/wk > $0): {be["G4"]["breakeven_bps"]:.1f} bps/side')
    md.append(f'- **Fee margin to G3 break**: {be["G3"]["breakeven_bps"] - CURRENT_T2_BPS:.1f} bps ({be["G3"]["breakeven_bps"] / CURRENT_T2_BPS:.2f}x current)')
    md.append(f'- **Fee margin to G4 break**: {be["G4"]["breakeven_bps"] - CURRENT_T2_BPS:.1f} bps ({be["G4"]["breakeven_bps"] / CURRENT_T2_BPS:.2f}x current)')
    md.append('')

    if current_pnl and current_pnl > 0:
        # Best scenario (T2 at 0 bps)
        best_level = next((l for l in ladder if l['t2_fee_bps'] == 0), None)
        if best_level:
            uplift = best_level['baseline']['pnl'] - current_pnl
            md.append(f'- **Best case** (T2 at 0 bps): +${uplift:.0f} uplift ({uplift/current_pnl*100:.0f}% improvement)')
    md.append('')

    # ---- Verdict ----
    md.append('## Verdict')
    md.append('')
    verdict_lines = report.get('verdict_lines', [])
    for line in verdict_lines:
        md.append(line)
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_t2_fee_sensitivity.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2: T2 Fee Sensitivity Analysis',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Part 2: T2 Fee Sensitivity Analysis (Agent C6-A2)')
    print('  H20 VWAP_DEVIATION v5 | T1 fixed at 12.5bps | T2 variable')
    print(sep)
    t0 = time.time()

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    print(f'[Config] T1 fee: {T1_FEE_BPS} bps/side (fixed)')
    print(f'[Config] T2 fee levels: {T2_FEE_LEVELS_BPS}')

    # --- Load data ---
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

    if args.dry_run:
        print(f'\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  Would run {len(T2_FEE_LEVELS_BPS)} fee levels x (baseline + stress + WF)')
        print(f'  + Binary search for G3 and G4 breakeven (~20 iterations each)')
        print(f'  Estimated: {len(T2_FEE_LEVELS_BPS) * 3 + 40} backtest runs')
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
    # PART 1: Fee Ladder (15 levels with full analysis)
    # ============================================================
    print(f'\n{sep}')
    print('  PART 1: Fee Ladder — 15 T2 Fee Levels')
    print(sep)

    fee_ladder = []

    for i, t2_bps in enumerate(T2_FEE_LEVELS_BPS):
        print(f'\n  [{i+1}/{len(T2_FEE_LEVELS_BPS)}] T2 fee = {t2_bps:.1f} bps/side...')
        result = analyze_fee_level(
            t2_bps, data, t1_coins, t2_coins,
            t1_indicators, t2_indicators, market_context,
            total_bars, run_wf=True,
        )
        fee_ladder.append(result)

        m = result['baseline']
        wf = result['walk_forward']
        wf_str = f'{wf["folds_positive"]}/5' if wf['folds_positive'] >= 0 else 'N/A'
        gates_str = 'ALL PASS' if result['all_gates_pass'] else f'FAIL: {",".join(result["failed_gates"])}'
        print(f'    {m["trades"]}tr PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
              f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}% '
              f'WF={wf_str} [{gates_str}] ({result["runtime_s"]:.1f}s)')

    # ============================================================
    # PART 2: Gate Transition Table
    # ============================================================
    print(f'\n{sep}')
    print('  PART 2: Gate Transition Table')
    print(sep)

    gate_names = ['G1_trades_per_week', 'G2_max_gap_days', 'G3_exp_per_week',
                  'G4_stress_exp_per_week', 'G5_max_dd_pct',
                  'G6_wf_folds_positive', 'G8_top1_fold_conc']

    gate_transitions = {}
    for gname in gate_names:
        first_fail_bps = None
        passes_current = True
        for level in fee_ladder:
            gate_info = level['gates'].get(gname, {})
            if not gate_info.get('pass', True):
                if first_fail_bps is None:
                    first_fail_bps = level['t2_fee_bps']
                if level['t2_fee_bps'] == CURRENT_T2_BPS:
                    passes_current = False
            if level['t2_fee_bps'] == CURRENT_T2_BPS and not gate_info.get('pass', True):
                passes_current = False
        gate_transitions[gname] = {
            'first_fail_bps': first_fail_bps,
            'passes_at_current': passes_current,
        }
        margin = (first_fail_bps - CURRENT_T2_BPS) if first_fail_bps is not None else None
        print(f'  {gname}: first fails at {first_fail_bps} bps '
              f'(margin: {f"+{margin:.1f} bps" if margin is not None else ">76.5 bps"})')

    # ============================================================
    # PART 3: Binary Search for Breakeven
    # ============================================================
    print(f'\n{sep}')
    print('  PART 3: Binary Search for T2 Breakeven Fee')
    print(sep)

    # G3 breakeven
    print('  [G3] Searching for exp/wk = $0 breakeven...')
    t_bs = time.time()
    g3_be_bps, g3_iters, g3_epw = find_t2_breakeven(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, total_bars, gate='G3', tol_bps=0.5, max_iter=20,
    )
    print(f'    G3 breakeven: {g3_be_bps:.1f} bps ({g3_iters} iters, {time.time()-t_bs:.1f}s)')
    print(f'    Margin from current: +{g3_be_bps - CURRENT_T2_BPS:.1f} bps '
          f'({g3_be_bps / CURRENT_T2_BPS:.2f}x current)')

    # G4 breakeven
    print('  [G4] Searching for stress 2x breakeven...')
    t_bs = time.time()
    g4_be_bps, g4_iters, g4_epw = find_t2_breakeven(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, total_bars, gate='G4', tol_bps=0.5, max_iter=20,
    )
    print(f'    G4 breakeven: {g4_be_bps:.1f} bps ({g4_iters} iters, {time.time()-t_bs:.1f}s)')
    print(f'    Margin from current: +{g4_be_bps - CURRENT_T2_BPS:.1f} bps '
          f'({g4_be_bps / CURRENT_T2_BPS:.2f}x current)')

    elapsed = time.time() - t0

    # ============================================================
    # Build Verdict
    # ============================================================
    current_level = next((l for l in fee_ladder if l['t2_fee_bps'] == CURRENT_T2_BPS), None)
    best_level = next((l for l in fee_ladder if l['t2_fee_bps'] == 0), None)

    verdict_lines = []
    verdict_lines.append(f'**G3 breakeven**: T2 can absorb up to {g3_be_bps:.1f} bps/side '
                         f'before combined exp/wk turns negative '
                         f'(margin: +{g3_be_bps - CURRENT_T2_BPS:.1f} bps, '
                         f'{g3_be_bps / CURRENT_T2_BPS:.2f}x current).')
    verdict_lines.append('')
    verdict_lines.append(f'**G4 breakeven**: T2 can absorb up to {g4_be_bps:.1f} bps/side '
                         f'before 2x stress exp/wk turns negative '
                         f'(margin: +{g4_be_bps - CURRENT_T2_BPS:.1f} bps, '
                         f'{g4_be_bps / CURRENT_T2_BPS:.2f}x current).')
    verdict_lines.append('')

    if g3_be_bps > CURRENT_T2_BPS * 2:
        verdict_lines.append(f'The strategy has **strong fee resilience** -- T2 fees can more than '
                             f'double before breaking. This confirms T2 is a robust contributor.')
    elif g3_be_bps > CURRENT_T2_BPS * 1.5:
        verdict_lines.append(f'The strategy has **moderate fee resilience** -- T2 fees have ~50% '
                             f'room before breaking.')
    else:
        verdict_lines.append(f'The strategy has **thin fee margin** -- T2 fees can only increase '
                             f'by {g3_be_bps - CURRENT_T2_BPS:.1f} bps before breaking. '
                             f'Fee negotiation is critical.')
    verdict_lines.append('')

    if best_level and current_level:
        uplift = best_level['baseline']['pnl'] - current_level['baseline']['pnl']
        verdict_lines.append(f'**Fee improvement potential**: If T2 achieved 0 bps (MEXC maker), '
                             f'P&L would increase by ${uplift:.0f} '
                             f'({uplift/max(abs(current_level["baseline"]["pnl"]),1)*100:.0f}%).')

    # ============================================================
    # Build JSON Report
    # ============================================================

    report = {
        'run_header': {
            'task': 'part2_t2_fee_sensitivity',
            'agent': 'C6-A2',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'fees': {
                't1_fixed_bps': T1_FEE_BPS,
                't2_current_bps': CURRENT_T2_BPS,
                't2_levels_tested': T2_FEE_LEVELS_BPS,
            },
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'fee_ladder': fee_ladder,
        'gate_transitions': gate_transitions,
        'breakeven': {
            'G3': {
                'breakeven_bps': g3_be_bps,
                'margin_bps': round(g3_be_bps - CURRENT_T2_BPS, 1),
                'multiplier_vs_current': round(g3_be_bps / CURRENT_T2_BPS, 2),
                'iterations': g3_iters,
                'last_exp_per_week': g3_epw,
            },
            'G4': {
                'breakeven_bps': g4_be_bps,
                'margin_bps': round(g4_be_bps - CURRENT_T2_BPS, 1),
                'multiplier_vs_current': round(g4_be_bps / CURRENT_T2_BPS, 2),
                'iterations': g4_iters,
                'last_exp_per_week': g4_epw,
            },
        },
        'verdict_lines': verdict_lines,
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / 'part2_t2_fee_sensitivity_001.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md_text = build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks)
    md_path = out_dir / 'part2_t2_fee_sensitivity_001.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{sep}')
    print(f'  T2 FEE SENSITIVITY ANALYSIS COMPLETE')
    print(sep)

    print(f'\n  T1 fee: {T1_FEE_BPS} bps/side (fixed)')
    print(f'  T2 current: {CURRENT_T2_BPS} bps/side')
    print(f'  T2 G3 breakeven: {g3_be_bps:.1f} bps (margin: +{g3_be_bps-CURRENT_T2_BPS:.1f} bps)')
    print(f'  T2 G4 breakeven: {g4_be_bps:.1f} bps (margin: +{g4_be_bps-CURRENT_T2_BPS:.1f} bps)')

    if current_level:
        print(f'\n  Current (T2={CURRENT_T2_BPS}bps):')
        m = current_level['baseline']
        print(f'    {m["trades"]}tr PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
              f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    if best_level:
        print(f'\n  Best case (T2=0bps):')
        m = best_level['baseline']
        print(f'    {m["trades"]}tr PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
              f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    print(f'\n  Fee ladder: {len(fee_ladder)} levels tested')
    print(f'  Gate transitions computed for {len(gate_transitions)} gates')
    print(f'  Runtime: {elapsed:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
