#!/usr/bin/env python3
"""
Part 2: Tier Decomposition -- T1 vs T2 edge contribution analysis
=================================================================
Decomposes H20 VWAP_DEVIATION v5 edge by tier on the 295-coin universe.

For EACH tier independently AND combined:
  - Baseline metrics (trades, PF, P&L, WR, DD, exp/wk)
  - Stress 2x metrics
  - Walk-forward 5-fold
  - Fold concentration
  - Gate evaluation (G1-G8 except G7)
  - Per-coin attribution (top/worst coins)

Also runs a hypothetical "T2 with T1 fees" scenario to isolate the
fee impact from the signal quality difference.

Output:
  reports/hf/part2_tier_decomp_001.json
  reports/hf/part2_tier_decomp_001.md

Usage:
    python -m strategies.hf.screening.run_part2_tier_decomp
    python -m strategies.hf.screening.run_part2_tier_decomp --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter

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

REPORT_JSON = 'part2_tier_decomp_001.json'
REPORT_MD   = 'part2_tier_decomp_001.md'


# ============================================================
# Data Loading (reuse patterns from existing scripts)
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
# Backtest Runners
# ============================================================

def run_tier_backtest(params, data, coins, indicators, market_ctx, fee, max_pos=1, tier_label=''):
    """Run v5 backtest on a specific set of coins with specific fee."""
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_ctx}
    bt = run_backtest(
        data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
        params=enriched, indicators=indicators, fee=fee, max_pos=max_pos,
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


# ============================================================
# Metrics Computation
# ============================================================

def compute_metrics(trades, total_bars, initial_capital=2000.0, default_fee=0.00125):
    n = len(trades)
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
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tpw = n / total_weeks
    epw = expectancy * tpw
    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        tfee = t.get('_fee_per_side', default_fee)
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
        trades=n, pnl=round(total_pnl, 2), pf=round(pf, 3), wr=round(wr, 2),
        dd=round(max_dd, 2), expectancy=round(expectancy, 4),
        trades_per_week=round(tpw, 2), exp_per_week=round(epw, 4),
        fee_drag_pct=round(fee_drag, 2),
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
# Full Tier Analysis
# ============================================================

def analyze_tier(label, params, data, coins, indicators, market_ctx,
                 fee, total_bars):
    """Run complete analysis for one tier: baseline, stress, WF, gates, coins."""
    print(f'\n  {"="*60}')
    print(f'  {label}: {len(coins)} coins, fee={fee*10000:.1f}bps')
    print(f'  {"="*60}')

    # --- Baseline ---
    print(f'  [1/4] Baseline...')
    t1 = time.time()
    trades = run_tier_backtest(params, data, coins, indicators, market_ctx,
                               fee, tier_label=label)
    m = compute_metrics(trades, total_bars)
    max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    print(f'    {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% '
          f'PnL=${m["pnl"]:.2f} Exp/wk=${m["exp_per_week"]:.4f} DD={m["dd"]:.1f}% '
          f'({time.time()-t1:.1f}s)')

    # --- Walk-Forward ---
    print(f'  [2/4] Walk-Forward 5-fold...')
    t2 = time.time()
    fold_trades = run_tier_walk_forward(params, data, coins, indicators,
                                         market_ctx, fee, tier_label=label)
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
    print(f'    WF: {folds_positive}/5 | Top-1 fold conc: {top1_fold_conc:.2%} ({time.time()-t2:.1f}s)')
    for fd in fold_details:
        tag = 'YES' if fd['positive'] else 'NO'
        print(f'      Fold {fd["fold"]}: {fd["trades"]}tr ${fd["pnl"]:.2f} ({tag})')

    # --- Stress 2x ---
    print(f'  [3/4] Stress 2x (fee={fee*2*10000:.1f}bps)...')
    t3 = time.time()
    stress_fee = fee * 2
    stress_trades = run_tier_backtest(params, data, coins, indicators, market_ctx,
                                      stress_fee, tier_label=label)
    sm = compute_metrics(stress_trades, total_bars)
    print(f'    {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.4f} DD={sm["dd"]:.1f}% '
          f'({time.time()-t3:.1f}s)')

    # --- Per-coin breakdown ---
    print(f'  [4/4] Per-coin breakdown...')
    cb = compute_coin_breakdown(trades)
    print(f'    Coins with trades: {cb["coins_with_trades"]}')
    if cb['top5']:
        print(f'    Top-1 coin: {cb["top5"][0]["coin"]} ${cb["top5"][0]["pnl"]:.2f} '
              f'(conc: {cb["top1_coin_conc"]:.1%})')
        print(f'    Top-3 coin conc: {cb["top3_coin_conc"]:.1%}')

    # --- Gate evaluation ---
    gates, all_pass, failed = evaluate_gates(m, sm, folds_positive, max_gap_days, top1_fold_conc)
    verdict = 'PASS' if all_pass else 'FAIL'
    print(f'\n  GATES ({label}):')
    for gname, gv in gates.items():
        tag = 'PASS' if gv['pass'] else 'FAIL'
        print(f'    {gname}: {gv["value"]} {gv["threshold"]} -> {tag}')
    print(f'  VERDICT: {verdict}')
    if failed:
        print(f'  Failed: {", ".join(failed)}')

    return {
        'label': label,
        'coins': len(coins),
        'fee_bps': round(fee * 10000, 1),
        'baseline': m,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'walk_forward': {
            'folds_positive': folds_positive, 'folds_total': 5,
            'fold_details': fold_details,
            'top1_fold_concentration': top1_fold_conc,
        },
        'stress_2x': {
            'fee_bps': round(stress_fee * 10000, 1),
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'wr': sm['wr'], 'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
        'coin_breakdown': cb,
        'gates': gates,
        'verdict': verdict,
        'failed_gates': failed,
        'trade_list': trades,  # for combined analysis later
    }


# ============================================================
# Combined Analysis (merge T1 + T2 trades)
# ============================================================

def analyze_combined(t1_result, t2_result, total_bars):
    """Compute combined metrics from T1 + T2 trade lists."""
    print(f'\n  {"="*60}')
    print(f'  COMBINED: T1({t1_result["coins"]}) + T2({t2_result["coins"]})')
    print(f'  {"="*60}')

    trades = t1_result['trade_list'] + t2_result['trade_list']
    stress_trades_combined = []  # We recompute from stress metrics

    m = compute_metrics(trades, total_bars)
    max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    cb = compute_coin_breakdown(trades)

    # For combined WF: sum fold P&L across tiers
    t1_wf = t1_result['walk_forward']['fold_details']
    t2_wf = t2_result['walk_forward']['fold_details']
    combined_fold_details = []
    folds_positive = 0
    for i in range(5):
        t1_pnl = t1_wf[i]['pnl'] if i < len(t1_wf) else 0
        t2_pnl = t2_wf[i]['pnl'] if i < len(t2_wf) else 0
        t1_n = t1_wf[i]['trades'] if i < len(t1_wf) else 0
        t2_n = t2_wf[i]['trades'] if i < len(t2_wf) else 0
        combined_pnl = round(t1_pnl + t2_pnl, 2)
        combined_n = t1_n + t2_n
        pos = combined_pnl > 0
        if pos:
            folds_positive += 1
        combined_fold_details.append({
            'fold': i, 'trades': combined_n, 'pnl': combined_pnl,
            'positive': pos, 't1_pnl': t1_pnl, 't2_pnl': t2_pnl,
        })
    top1_fold_conc = compute_top1_fold_concentration(combined_fold_details)

    # Combined stress: sum stress P&L values
    combined_stress_pnl = t1_result['stress_2x']['pnl'] + t2_result['stress_2x']['pnl']
    combined_stress_trades = t1_result['stress_2x']['trades'] + t2_result['stress_2x']['trades']
    # Approximate combined stress metrics
    if combined_stress_trades > 0:
        stress_exp = combined_stress_pnl / combined_stress_trades
        total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
        stress_tpw = combined_stress_trades / total_weeks
        stress_epw = stress_exp * stress_tpw
    else:
        stress_epw = 0.0
    combined_stress = {
        'trades': combined_stress_trades,
        'pnl': round(combined_stress_pnl, 2),
        'exp_per_week': round(stress_epw, 4),
    }

    # Gates
    gates, all_pass, failed = evaluate_gates(m, {'exp_per_week': stress_epw},
                                              folds_positive, max_gap_days, top1_fold_conc)
    verdict = 'PASS' if all_pass else 'FAIL'

    print(f'  {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% '
          f'PnL=${m["pnl"]:.2f} Exp/wk=${m["exp_per_week"]:.4f} DD={m["dd"]:.1f}%')
    print(f'  WF: {folds_positive}/5 | Stress exp/wk: ${stress_epw:.4f}')
    print(f'  VERDICT: {verdict}')
    if failed:
        print(f'  Failed: {", ".join(failed)}')

    return {
        'label': 'COMBINED',
        'coins': t1_result['coins'] + t2_result['coins'],
        'baseline': m,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'walk_forward': {
            'folds_positive': folds_positive, 'folds_total': 5,
            'fold_details': combined_fold_details,
            'top1_fold_concentration': top1_fold_conc,
        },
        'stress_2x': combined_stress,
        'coin_breakdown': cb,
        'gates': gates,
        'verdict': verdict,
        'failed_gates': failed,
    }


# ============================================================
# Fee Impact Analysis
# ============================================================

def analyze_t2_with_t1_fees(params, data, t2_coins, t2_indicators, market_ctx,
                             t1_fee, total_bars):
    """Hypothetical: what if T2 coins had T1 fees (0% maker scenario)?"""
    print(f'\n  {"="*60}')
    print(f'  HYPOTHETICAL: T2 with T1 fees ({t1_fee*10000:.1f}bps)')
    print(f'  {"="*60}')

    trades = run_tier_backtest(params, data, t2_coins, t2_indicators, market_ctx,
                               t1_fee, tier_label='tier2_cheap')
    m = compute_metrics(trades, total_bars)

    # Stress at 2x T1 fee
    stress_trades = run_tier_backtest(params, data, t2_coins, t2_indicators, market_ctx,
                                      t1_fee * 2, tier_label='tier2_cheap_stress')
    sm = compute_metrics(stress_trades, total_bars)

    print(f'  {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% '
          f'PnL=${m["pnl"]:.2f} Exp/wk=${m["exp_per_week"]:.4f} DD={m["dd"]:.1f}%')
    print(f'  Stress: PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.4f}')

    return {
        'label': 'T2 @ T1 fees',
        'coins': len(t2_coins),
        'fee_bps': round(t1_fee * 10000, 1),
        'baseline': m,
        'stress_2x': {
            'fee_bps': round(t1_fee * 2 * 10000, 1),
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'wr': sm['wr'], 'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
    }


# ============================================================
# Markdown Report Builder
# ============================================================

def build_md(report, t1, t2, combined, t2_cheap, elapsed, commit,
             n_t1, n_t2, total_bars, total_weeks, tier1_fee, tier2_fee):
    md = []
    md.append('# Part 2: Tier Decomposition -- T1 vs T2 Edge Analysis')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps/side, T2={tier2_fee*10000:.1f}bps/side')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # ---- Head-to-head comparison table ----
    md.append('## Head-to-Head: T1 vs T2 vs Combined')
    md.append('')
    md.append('| Metric | T1 | T2 | Combined | T2 @ T1 fees |')
    md.append('|--------|----|----|----------|--------------|')

    rows = [
        ('Coins', t1['coins'], t2['coins'], combined['coins'], t2_cheap['coins']),
        ('Fee (bps/side)', t1['fee_bps'], t2['fee_bps'], '-', t2_cheap['fee_bps']),
        ('Trades', t1['baseline']['trades'], t2['baseline']['trades'],
         combined['baseline']['trades'], t2_cheap['baseline']['trades']),
        ('PnL ($)', f"${t1['baseline']['pnl']:.2f}", f"${t2['baseline']['pnl']:.2f}",
         f"${combined['baseline']['pnl']:.2f}", f"${t2_cheap['baseline']['pnl']:.2f}"),
        ('PF', f"{t1['baseline']['pf']:.3f}", f"{t2['baseline']['pf']:.3f}",
         f"{combined['baseline']['pf']:.3f}", f"{t2_cheap['baseline']['pf']:.3f}"),
        ('WR (%)', f"{t1['baseline']['wr']:.1f}", f"{t2['baseline']['wr']:.1f}",
         f"{combined['baseline']['wr']:.1f}", f"{t2_cheap['baseline']['wr']:.1f}"),
        ('Exp/Wk ($)', f"${t1['baseline']['exp_per_week']:.4f}", f"${t2['baseline']['exp_per_week']:.4f}",
         f"${combined['baseline']['exp_per_week']:.4f}", f"${t2_cheap['baseline']['exp_per_week']:.4f}"),
        ('Tr/Wk', f"{t1['baseline']['trades_per_week']:.2f}", f"{t2['baseline']['trades_per_week']:.2f}",
         f"{combined['baseline']['trades_per_week']:.2f}", f"{t2_cheap['baseline']['trades_per_week']:.2f}"),
        ('DD (%)', f"{t1['baseline']['dd']:.1f}", f"{t2['baseline']['dd']:.1f}",
         f"{combined['baseline']['dd']:.1f}", f"{t2_cheap['baseline']['dd']:.1f}"),
        ('Fee Drag (%)', f"{t1['baseline']['fee_drag_pct']:.1f}", f"{t2['baseline']['fee_drag_pct']:.1f}",
         f"{combined['baseline']['fee_drag_pct']:.1f}", f"{t2_cheap['baseline']['fee_drag_pct']:.1f}"),
        ('Max Gap (d)', t1['max_gap']['days'], t2['max_gap']['days'],
         combined['max_gap']['days'], '-'),
    ]
    for row in rows:
        md.append(f'| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |')
    md.append('')

    # ---- Walk-Forward comparison ----
    md.append('## Walk-Forward (5-Fold) by Tier')
    md.append('')
    md.append('| Fold | T1 Trades | T1 PnL | T2 Trades | T2 PnL | Combined PnL |')
    md.append('|------|-----------|--------|-----------|--------|-------------|')
    t1_wf = t1['walk_forward']['fold_details']
    t2_wf = t2['walk_forward']['fold_details']
    c_wf = combined['walk_forward']['fold_details']
    for i in range(5):
        t1f = t1_wf[i] if i < len(t1_wf) else {'trades': 0, 'pnl': 0}
        t2f = t2_wf[i] if i < len(t2_wf) else {'trades': 0, 'pnl': 0}
        cf = c_wf[i] if i < len(c_wf) else {'pnl': 0}
        md.append(f'| {i} | {t1f["trades"]} | ${t1f["pnl"]:.2f} | '
                  f'{t2f["trades"]} | ${t2f["pnl"]:.2f} | ${cf["pnl"]:.2f} |')
    md.append('')
    md.append(f'**T1 WF**: {t1["walk_forward"]["folds_positive"]}/5 positive folds | '
              f'Top-1 fold conc: {t1["walk_forward"]["top1_fold_concentration"]:.2%}')
    md.append(f'**T2 WF**: {t2["walk_forward"]["folds_positive"]}/5 positive folds | '
              f'Top-1 fold conc: {t2["walk_forward"]["top1_fold_concentration"]:.2%}')
    md.append(f'**Combined WF**: {combined["walk_forward"]["folds_positive"]}/5 positive folds | '
              f'Top-1 fold conc: {combined["walk_forward"]["top1_fold_concentration"]:.2%}')
    md.append('')

    # ---- Stress comparison ----
    md.append('## Stress Test (2x Fees)')
    md.append('')
    md.append('| Metric | T1 | T2 | Combined | T2 @ T1 fees |')
    md.append('|--------|----|----|----------|--------------|')
    md.append(f'| Fee 2x (bps) | {t1["stress_2x"]["fee_bps"]} | {t2["stress_2x"]["fee_bps"]} | - | {t2_cheap["stress_2x"]["fee_bps"]} |')
    md.append(f'| Trades | {t1["stress_2x"]["trades"]} | {t2["stress_2x"]["trades"]} | {combined["stress_2x"]["trades"]} | {t2_cheap["stress_2x"]["trades"]} |')
    md.append(f'| PnL ($) | ${t1["stress_2x"]["pnl"]:.2f} | ${t2["stress_2x"]["pnl"]:.2f} | ${combined["stress_2x"]["pnl"]:.2f} | ${t2_cheap["stress_2x"]["pnl"]:.2f} |')
    md.append(f'| PF | {t1["stress_2x"]["pf"]:.3f} | {t2["stress_2x"]["pf"]:.3f} | - | {t2_cheap["stress_2x"]["pf"]:.3f} |')
    md.append(f'| Exp/Wk ($) | ${t1["stress_2x"]["exp_per_week"]:.4f} | ${t2["stress_2x"]["exp_per_week"]:.4f} | ${combined["stress_2x"]["exp_per_week"]:.4f} | ${t2_cheap["stress_2x"]["exp_per_week"]:.4f} |')
    md.append('')

    # ---- Gate comparison ----
    md.append('## Gate Evaluation by Tier')
    md.append('')
    md.append('| Gate | T1 | T2 | Combined |')
    md.append('|------|----|----|----------|')
    for gname in ['G1_trades_per_week', 'G2_max_gap_days', 'G3_exp_per_week_mkt',
                   'G4_exp_per_week_2x', 'G5_max_dd_pct', 'G6_wf_folds_positive',
                   'G8_top1_fold_conc']:
        t1g = t1['gates'].get(gname, {})
        t2g = t2['gates'].get(gname, {})
        cg = combined['gates'].get(gname, {})
        t1_tag = 'PASS' if t1g.get('pass', False) else '**FAIL**'
        t2_tag = 'PASS' if t2g.get('pass', False) else '**FAIL**'
        c_tag = 'PASS' if cg.get('pass', False) else '**FAIL**'
        t1_val = t1g.get('value', '-')
        t2_val = t2g.get('value', '-')
        c_val = cg.get('value', '-')
        if isinstance(t1_val, float):
            t1_val = f'{t1_val:.4f}' if abs(t1_val) < 10 else f'{t1_val:.1f}'
        if isinstance(t2_val, float):
            t2_val = f'{t2_val:.4f}' if abs(t2_val) < 10 else f'{t2_val:.1f}'
        if isinstance(c_val, float):
            c_val = f'{c_val:.4f}' if abs(c_val) < 10 else f'{c_val:.1f}'
        md.append(f'| {gname} | {t1_val} {t1_tag} | {t2_val} {t2_tag} | {c_val} {c_tag} |')
    md.append('')
    md.append(f'**T1 Verdict: {t1["verdict"]}**')
    if t1['failed_gates']:
        md.append(f'  Failed: {", ".join(t1["failed_gates"])}')
    md.append(f'**T2 Verdict: {t2["verdict"]}**')
    if t2['failed_gates']:
        md.append(f'  Failed: {", ".join(t2["failed_gates"])}')
    md.append(f'**Combined Verdict: {combined["verdict"]}**')
    if combined['failed_gates']:
        md.append(f'  Failed: {", ".join(combined["failed_gates"])}')
    md.append('')

    # ---- Fee Impact Analysis ----
    md.append('## Fee Impact Analysis')
    md.append('')
    md.append('What if T2 had T1 fees (hypothetical 0% maker for all tiers)?')
    md.append('')
    md.append('| Metric | T2 (actual) | T2 @ T1 fees | Delta |')
    md.append('|--------|-------------|--------------|-------|')
    t2b = t2['baseline']
    t2c = t2_cheap['baseline']
    for metric, key, fmt in [
        ('PnL ($)', 'pnl', '${:.2f}'),
        ('PF', 'pf', '{:.3f}'),
        ('Exp/Wk ($)', 'exp_per_week', '${:.4f}'),
        ('WR (%)', 'wr', '{:.1f}'),
        ('Fee Drag (%)', 'fee_drag_pct', '{:.1f}'),
    ]:
        v_actual = t2b[key]
        v_cheap = t2c[key]
        delta = v_cheap - v_actual
        sign = '+' if delta >= 0 else ''
        md.append(f'| {metric} | {fmt.format(v_actual)} | {fmt.format(v_cheap)} | {sign}{fmt.format(delta)} |')
    md.append('')

    fee_delta_pnl = t2c['pnl'] - t2b['pnl']
    md.append(f'**Fee impact on T2 PnL**: ${fee_delta_pnl:.2f} '
              f'({fee_delta_pnl/abs(t2b["pnl"])*100 if t2b["pnl"] != 0 else 0:.0f}% of T2 PnL)')
    md.append('')

    # ---- Coin Attribution ----
    md.append('## Per-Tier Coin Attribution')
    md.append('')
    for tier_result in [t1, t2]:
        tier_label = tier_result['label']
        cb = tier_result['coin_breakdown']
        md.append(f'### {tier_label} ({cb["coins_with_trades"]} coins active)')
        md.append('')
        if cb['top5']:
            md.append('**Top 5 contributors:**')
            md.append('')
            for c in cb['top5']:
                md.append(f'- {c["coin"]}: ${c["pnl"]:.2f}')
            md.append('')
        if cb['worst5']:
            md.append('**Worst 5 contributors:**')
            md.append('')
            for c in cb['worst5']:
                md.append(f'- {c["coin"]}: ${c["pnl"]:.2f}')
            md.append('')
        md.append(f'- Top-1 coin concentration: {cb["top1_coin_conc"]:.1%}')
        md.append(f'- Top-3 coin concentration: {cb["top3_coin_conc"]:.1%}')
        md.append('')

    # ---- Edge Contribution ----
    md.append('## Edge Contribution Summary')
    md.append('')
    total_pnl = combined['baseline']['pnl']
    t1_pnl = t1['baseline']['pnl']
    t2_pnl = t2['baseline']['pnl']
    t1_share = t1_pnl / total_pnl * 100 if total_pnl != 0 else 0
    t2_share = t2_pnl / total_pnl * 100 if total_pnl != 0 else 0
    md.append(f'| Tier | PnL | Share | Trades | Trades/Wk | Exp/Wk |')
    md.append(f'|------|-----|-------|--------|-----------|--------|')
    md.append(f'| T1 | ${t1_pnl:.2f} | {t1_share:.1f}% | {t1["baseline"]["trades"]} | '
              f'{t1["baseline"]["trades_per_week"]:.2f} | ${t1["baseline"]["exp_per_week"]:.4f} |')
    md.append(f'| T2 | ${t2_pnl:.2f} | {t2_share:.1f}% | {t2["baseline"]["trades"]} | '
              f'{t2["baseline"]["trades_per_week"]:.2f} | ${t2["baseline"]["exp_per_week"]:.4f} |')
    md.append(f'| **Total** | **${total_pnl:.2f}** | **100%** | **{combined["baseline"]["trades"]}** | '
              f'**{combined["baseline"]["trades_per_week"]:.2f}** | **${combined["baseline"]["exp_per_week"]:.4f}** |')
    md.append('')

    # ---- Verdict ----
    md.append('## Verdict: Is T2 Worth Keeping?')
    md.append('')
    # Determine verdict based on data
    if t2_pnl > 0 and t2['walk_forward']['folds_positive'] >= 2:
        md.append('**T2 is a net positive contributor.**')
        md.append('')
        md.append(f'- T2 contributes ${t2_pnl:.2f} ({t2_share:.1f}% of total PnL)')
        md.append(f'- T2 adds {t2["baseline"]["trades"]} trades '
                  f'({t2["baseline"]["trades_per_week"]:.2f}/wk)')
        md.append(f'- T2 passes {t2["walk_forward"]["folds_positive"]}/5 WF folds independently')
        if t2['stress_2x']['exp_per_week'] > 0:
            md.append(f'- T2 survives stress 2x (exp/wk=${t2["stress_2x"]["exp_per_week"]:.4f})')
        else:
            md.append(f'- T2 does NOT survive stress 2x (exp/wk=${t2["stress_2x"]["exp_per_week"]:.4f})')
        md.append(f'- Fee drag: T2 {t2["baseline"]["fee_drag_pct"]:.1f}% vs T1 {t1["baseline"]["fee_drag_pct"]:.1f}%')
        md.append('')
        md.append('**Recommendation**: Keep T2 in universe. The additional trades and edge ')
        md.append('contribution justify the higher fees.')
    elif t2_pnl > 0 and t2['walk_forward']['folds_positive'] < 2:
        md.append('**T2 shows positive P&L but weak walk-forward stability.**')
        md.append('')
        md.append(f'- T2 contributes ${t2_pnl:.2f} but only {t2["walk_forward"]["folds_positive"]}/5 WF folds')
        md.append('- Edge may be concentrated in specific time periods')
        md.append('')
        md.append('**Recommendation**: T2 is borderline. Consider monitoring in paper trading.')
    elif t2_pnl <= 0:
        md.append('**T2 is a net NEGATIVE contributor.**')
        md.append('')
        md.append(f'- T2 loses ${abs(t2_pnl):.2f} (drags combined edge down)')
        md.append(f'- Fee drag: T2 {t2["baseline"]["fee_drag_pct"]:.1f}% vs T1 {t1["baseline"]["fee_drag_pct"]:.1f}%')
        md.append(f'- T2 at T1 fees would make ${t2_cheap["baseline"]["pnl"]:.2f} '
                  f'(fees explain ${fee_delta_pnl:.2f} of the loss)')
        md.append('')
        if t2_cheap['baseline']['pnl'] > 0:
            md.append('**Recommendation**: T2 edge exists but is eaten by fees. Consider removing T2 ')
            md.append('or finding a way to reduce T2 execution costs (e.g., maker orders).')
        else:
            md.append('**Recommendation**: Remove T2 from universe. Even with T1 fees, T2 is negative.')
    md.append('')

    # ---- What-if: T1-only ----
    md.append('## What-If: T1-Only Strategy')
    md.append('')
    md.append(f'If we ran T1 only:')
    md.append(f'- PnL: ${t1_pnl:.2f} (vs combined ${total_pnl:.2f})')
    delta = t1_pnl - total_pnl
    md.append(f'- Delta: ${delta:+.2f}')
    md.append(f'- WF: {t1["walk_forward"]["folds_positive"]}/5 (vs combined {combined["walk_forward"]["folds_positive"]}/5)')
    md.append(f'- DD: {t1["baseline"]["dd"]:.1f}% (vs combined {combined["baseline"]["dd"]:.1f}%)')
    md.append(f'- Trades/Wk: {t1["baseline"]["trades_per_week"]:.2f} (vs combined {combined["baseline"]["trades_per_week"]:.2f})')
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_tier_decomp.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2: Tier Decomposition -- T1 vs T2 Edge Analysis',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2: Tier Decomposition -- T1 vs T2 Edge Analysis')
    print('  H20 VWAP_DEVIATION v5 on 295-coin universe')
    print('=' * 70)
    t0 = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    print(f'[Costs] MEXC Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')

    stress_regime = stress_multiplier('mexc_market', 2.0)
    stress_t1 = stress_regime['tier1']['total_per_side_bps'] / 10000.0
    stress_t2 = stress_regime['tier2']['total_per_side_bps'] / 10000.0
    print(f'[Stress] 2x: T1={stress_t1*10000:.1f}bps, T2={stress_t2*10000:.1f}bps')

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
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (after exclusion)')

    if n_total < 200:
        print(f'[WARN] Expected ~295 coins but only {n_total} available.')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    if args.dry_run:
        print('\n[DRY RUN] Data loaded. Would analyze T1, T2, combined, and T2@T1fees.')
        print(f'  T1: {n_t1} coins at {tier1_fee*10000:.1f}bps')
        print(f'  T2: {n_t2} coins at {tier2_fee*10000:.1f}bps')
        print(f'  T2 @ T1 fees: {n_t2} coins at {tier1_fee*10000:.1f}bps')
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

    # Estimate total bars (use max across all tiers)
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
    # Run Analyses
    # ============================================================

    # 1. T1 analysis
    t1_result = analyze_tier(
        'T1', PARAMS_V5, data, tier_coins['tier1'],
        tier_indicators.get('tier1', {}), market_context,
        tier1_fee, total_bars,
    )

    # 2. T2 analysis
    t2_result = analyze_tier(
        'T2', PARAMS_V5, data, tier_coins['tier2'],
        tier_indicators.get('tier2', {}), market_context,
        tier2_fee, total_bars,
    )

    # 3. Combined analysis
    combined_result = analyze_combined(t1_result, t2_result, total_bars)

    # 4. T2 with T1 fees (hypothetical)
    t2_cheap_result = analyze_t2_with_t1_fees(
        PARAMS_V5, data, tier_coins['tier2'],
        tier_indicators.get('tier2', {}), market_context,
        tier1_fee, total_bars,
    )

    elapsed = time.time() - t0

    # ============================================================
    # Save reports
    # ============================================================

    # Strip trade_list from saved results (too large for JSON)
    t1_save = {k: v for k, v in t1_result.items() if k != 'trade_list'}
    t2_save = {k: v for k, v in t2_result.items() if k != 'trade_list'}

    report = {
        'run_header': {
            'task': 'part2_tier_decomp',
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
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'tier1': t1_save,
        'tier2': t2_save,
        'combined': combined_result,
        't2_at_t1_fees': t2_cheap_result,
        'edge_contribution': {
            't1_pnl': t1_result['baseline']['pnl'],
            't2_pnl': t2_result['baseline']['pnl'],
            'combined_pnl': combined_result['baseline']['pnl'],
            't1_share_pct': round(t1_result['baseline']['pnl'] / combined_result['baseline']['pnl'] * 100
                                  if combined_result['baseline']['pnl'] != 0 else 0, 1),
            't2_share_pct': round(t2_result['baseline']['pnl'] / combined_result['baseline']['pnl'] * 100
                                  if combined_result['baseline']['pnl'] != 0 else 0, 1),
            'fee_impact_on_t2': round(t2_cheap_result['baseline']['pnl'] - t2_result['baseline']['pnl'], 2),
        },
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / REPORT_JSON
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md = build_md(report, t1_save, t2_save, combined_result, t2_cheap_result,
                  elapsed, commit, n_t1, n_t2, total_bars, total_weeks,
                  tier1_fee, tier2_fee)
    md_path = out_dir / REPORT_MD
    md_path.write_text(md)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{"="*70}')
    print(f'  TIER DECOMPOSITION COMPLETE')
    print(f'{"="*70}')
    print(f'\n  T1 ({n_t1} coins):')
    print(f'    {t1_result["baseline"]["trades"]}tr PF={t1_result["baseline"]["pf"]:.3f} '
          f'PnL=${t1_result["baseline"]["pnl"]:.2f} Exp/wk=${t1_result["baseline"]["exp_per_week"]:.4f}')
    print(f'    WF: {t1_result["walk_forward"]["folds_positive"]}/5 | Verdict: {t1_result["verdict"]}')

    print(f'\n  T2 ({n_t2} coins):')
    print(f'    {t2_result["baseline"]["trades"]}tr PF={t2_result["baseline"]["pf"]:.3f} '
          f'PnL=${t2_result["baseline"]["pnl"]:.2f} Exp/wk=${t2_result["baseline"]["exp_per_week"]:.4f}')
    print(f'    WF: {t2_result["walk_forward"]["folds_positive"]}/5 | Verdict: {t2_result["verdict"]}')

    print(f'\n  Combined:')
    print(f'    {combined_result["baseline"]["trades"]}tr PF={combined_result["baseline"]["pf"]:.3f} '
          f'PnL=${combined_result["baseline"]["pnl"]:.2f} Exp/wk=${combined_result["baseline"]["exp_per_week"]:.4f}')
    print(f'    WF: {combined_result["walk_forward"]["folds_positive"]}/5 | Verdict: {combined_result["verdict"]}')

    print(f'\n  T2 @ T1 fees:')
    print(f'    {t2_cheap_result["baseline"]["trades"]}tr PF={t2_cheap_result["baseline"]["pf"]:.3f} '
          f'PnL=${t2_cheap_result["baseline"]["pnl"]:.2f} Exp/wk=${t2_cheap_result["baseline"]["exp_per_week"]:.4f}')

    # Edge contribution
    total_pnl = combined_result['baseline']['pnl']
    if total_pnl != 0:
        t1_share = t1_result['baseline']['pnl'] / total_pnl * 100
        t2_share = t2_result['baseline']['pnl'] / total_pnl * 100
    else:
        t1_share = t2_share = 0
    print(f'\n  Edge contribution:')
    print(f'    T1: ${t1_result["baseline"]["pnl"]:.2f} ({t1_share:.1f}%)')
    print(f'    T2: ${t2_result["baseline"]["pnl"]:.2f} ({t2_share:.1f}%)')
    fee_impact = t2_cheap_result['baseline']['pnl'] - t2_result['baseline']['pnl']
    print(f'    Fee impact on T2: ${fee_impact:.2f}')

    print(f'\n  Runtime: {elapsed:.1f}s')
    print(f'{"="*70}')


if __name__ == '__main__':
    main()
