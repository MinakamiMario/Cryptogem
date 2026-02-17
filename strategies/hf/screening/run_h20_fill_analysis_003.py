#!/usr/bin/env python3
"""
H20 VWAP_DEVIATION Comprehensive Fill-Model Analysis (Part 2, Run 003)
======================================================================
Runs throughput + robustness + fill-model analysis for BOTH:
  - v5 baseline (tp_pct=8)
  - tp=10 variant (robustness winner from h20_robustness_002)

Tasks:
  A) Verify v5 throughput (already done as 002, re-verify)
  B) Run throughput for tp=10 variant
  C) Apply fill model v2 (5 modes) to both configs
  D) Stress test at 2x fees for both configs

Output:
  reports/hf/h20_throughput_tp10_003.json + .md
  reports/hf/h20_fill_analysis_003.json + .md

Usage:
    python -m strategies.hf.screening.run_h20_fill_analysis_003
    python -m strategies.hf.screening.run_h20_fill_analysis_003 --dry-run
"""
import sys
import json
import math
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter
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
from strategies.hf.screening.fill_model_v2 import (
    apply_fill_model, adjust_backtest_result, get_all_modes_summary,
)

BARS_PER_WEEK = 168
BARS_PER_DAY = 24

MEXC_MARKET_T1 = 0.0005
MEXC_MARKET_T2 = 0.0020
try:
    from strategies.hf.screening.costs_mexc_v2 import get_harness_fee
    MEXC_MARKET_T1 = get_harness_fee('mexc_market', 'tier1')
    MEXC_MARKET_T2 = get_harness_fee('mexc_market', 'tier2')
except ImportError:
    pass

STRESS_2X_T1 = MEXC_MARKET_T1 * 2
STRESS_2X_T2 = MEXC_MARKET_T2 * 2

V5_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10, 'label': 'v5_baseline_tp8'}
TP10_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 10, 'label': 'tp10_variant'}
CONFIGS = [V5_PARAMS, TP10_PARAMS]
FILL_MODES = ['market', 'limit_moderate', 'limit_conservative', 'hybrid_optimistic', 'hybrid_conservative']
MAX_POS_VALUES = [1, 2, 3]


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
            tier_coins['tier1'] = [c for c in tiers[tier_key_name].get('coins', []) if c in available_coins]
            break
    for tier_key_name in ['tier_2', 'Tier 2 (Mid)', 'tier2', '2']:
        if tier_key_name in tiers:
            tier_coins['tier2'] = [c for c in tiers[tier_key_name].get('coins', []) if c in available_coins]
            break
    return tier_coins


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            ind = indicators.get(coin, {})
            n = ind.get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def run_h20_variant(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee, max_pos=1):
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}
    all_trades = []
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
                          params=enriched_params, indicators=indicators, fee=fee, max_pos=max_pos)
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_h20_walk_forward(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee, n_folds=5):
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched_params = {**signal_params, '__market__': market_context}
    tier_fold_trades = {}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
                                    params=enriched_params, indicators=indicators, n_folds=n_folds,
                                    fee=fee, max_pos=1)
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)
    return tier_fold_trades


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    n_trades = len(trades)
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0, 'dd': 0.0,
                'expectancy': 0.0, 'trades_per_week': 0.0, 'exp_per_week': 0.0, 'fee_drag_pct': 0.0}
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
    return {'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
            'wr': round(wr, 2), 'dd': round(max_dd, 2), 'expectancy': round(expectancy, 4),
            'trades_per_week': round(trades_per_week, 2), 'exp_per_week': round(exp_per_week, 4),
            'fee_drag_pct': round(fee_drag_pct, 2)}


def composite_score(exp_per_week, wf_folds_positive, trades, n_folds=5):
    trade_penalty = min(1.0, trades / 50.0)
    wf_ratio = wf_folds_positive / n_folds if n_folds > 0 else 0.0
    return exp_per_week * wf_ratio * trade_penalty


def analyze_throughput(trades, total_bars):
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades_total': 0, 'trades_per_week': 0.0, 'trades_t1': 0, 'trades_t2': 0,
                'max_gap_bars': total_bars, 'max_gap_days': total_bars / BARS_PER_DAY,
                'median_gap_bars': 0, 'mean_gap_bars': 0,
                'rolling_4w_mean': 0.0, 'rolling_4w_std': 0.0, 'rolling_4w_cv': 0.0,
                'utilization_pct': 0.0, 'total_weeks': round(total_weeks, 2)}
    trades_t1 = sum(1 for t in trades if t.get('_tier') == 'tier1')
    trades_t2 = sum(1 for t in trades if t.get('_tier') == 'tier2')
    entry_bars = sorted(t['entry_bar'] for t in trades)
    gaps = [entry_bars[i+1] - entry_bars[i] for i in range(len(entry_bars)-1)]
    max_gap = max(gaps) if gaps else 0
    median_gap = sorted(gaps)[len(gaps)//2] if gaps else 0
    mean_gap = sum(gaps)/len(gaps) if gaps else 0
    window_bars = 4 * BARS_PER_WEEK
    n_windows = max(1, (total_bars - window_bars) // BARS_PER_WEEK + 1)
    rolling_counts = []
    for w in range(n_windows):
        w_start = w * BARS_PER_WEEK
        w_end = w_start + window_bars
        count = sum(1 for eb in entry_bars if w_start <= eb < w_end)
        rolling_counts.append(count)
    r_mean = sum(rolling_counts)/len(rolling_counts) if rolling_counts else 0.0
    r_var = sum((c-r_mean)**2 for c in rolling_counts)/len(rolling_counts) if rolling_counts else 0.0
    r_std = math.sqrt(r_var)
    r_cv = r_std / r_mean if r_mean > 0 else 0.0
    bars_with_position = set()
    for t in trades:
        for b in range(t['entry_bar'], t.get('exit_bar', t['entry_bar']+1)):
            bars_with_position.add(b)
    utilization = len(bars_with_position) / total_bars * 100 if total_bars > 0 else 0.0
    return {'trades_total': n_trades, 'trades_per_week': round(n_trades/total_weeks, 2),
            'trades_t1': trades_t1, 'trades_t2': trades_t2,
            'max_gap_bars': max_gap, 'max_gap_days': round(max_gap/BARS_PER_DAY, 2),
            'median_gap_bars': median_gap, 'mean_gap_bars': round(mean_gap, 1),
            'rolling_4w_mean': round(r_mean, 2), 'rolling_4w_std': round(r_std, 2),
            'rolling_4w_cv': round(r_cv, 3), 'utilization_pct': round(utilization, 2),
            'total_weeks': round(total_weeks, 2)}


def analyze_capacity(data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee, total_bars, params):
    results = {}
    for mp in MAX_POS_VALUES:
        trades = run_h20_variant(params=params, data=data, tier_coins=tier_coins,
                                 tier_indicators=tier_indicators, market_context=market_context,
                                 tier1_fee=tier1_fee, tier2_fee=tier2_fee, max_pos=mp)
        basic = compute_metrics(trades, total_bars=total_bars)
        tp = analyze_throughput(trades, total_bars)
        results[f'max_pos_{mp}'] = {'trades': basic['trades'], 'pnl': basic['pnl'],
                                     'pf': basic['pf'], 'wr': basic['wr'],
                                     'exp_per_week': basic['exp_per_week'],
                                     'utilization_pct': tp['utilization_pct'],
                                     'trades_per_week': tp['trades_per_week']}
    if 'max_pos_1' in results and 'max_pos_2' in results:
        results['missed_at_mp1_vs_mp2'] = results['max_pos_2']['trades'] - results['max_pos_1']['trades']
    if 'max_pos_2' in results and 'max_pos_3' in results:
        results['missed_at_mp2_vs_mp3'] = results['max_pos_3']['trades'] - results['max_pos_2']['trades']
    return results


def run_fill_analysis(trades, total_bars, config_label):
    results = {}
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    n_trades = len(trades)
    total_pnl = sum(t['pnl'] for t in trades)
    for mode in FILL_MODES:
        mode_results = {}
        for tier in ['tier1', 'tier2']:
            adjusted = adjust_backtest_result(mode=mode, tier=tier, n_trades=n_trades,
                                              total_pnl=total_pnl, trade_list=trades)
            adj_pnl = adjusted['adjusted_pnl']
            eff_trades = adjusted['effective_trades']
            adj_expectancy = adj_pnl / eff_trades if eff_trades > 0 else 0.0
            adj_trades_per_week = eff_trades / total_weeks
            adj_exp_per_week = adj_expectancy * adj_trades_per_week
            mode_results[tier] = {**adjusted,
                                  'adjusted_expectancy': round(adj_expectancy, 4),
                                  'adjusted_trades_per_week': round(adj_trades_per_week, 2),
                                  'adjusted_exp_per_week': round(adj_exp_per_week, 4),
                                  'pnl_delta_vs_market': round(adj_pnl - total_pnl, 2),
                                  'config': config_label}
        results[mode] = mode_results
    return results


def build_comparison(all_results, v5_key, tp10_key, total_bars):
    v5 = all_results[v5_key]
    tp10 = all_results[tp10_key]
    comp = {'head_to_head': []}
    metrics_to_compare = [
        ('Trades', 'trades', 'baseline_metrics'),
        ('PnL ($)', 'pnl', 'baseline_metrics'),
        ('PF', 'pf', 'baseline_metrics'),
        ('WR (%)', 'wr', 'baseline_metrics'),
        ('Exp/Week ($)', 'exp_per_week', 'baseline_metrics'),
        ('DD (%)', 'dd', 'baseline_metrics'),
        ('Fee Drag (%)', 'fee_drag_pct', 'baseline_metrics'),
        ('WF Folds', 'wf_folds_positive', None),
        ('Composite Score', 'composite_score', None),
        ('Stress PF', 'pf', 'stress_2x'),
        ('Stress Exp/Wk ($)', 'exp_per_week', 'stress_2x'),
    ]
    for label, key, subkey in metrics_to_compare:
        v5_val = v5[subkey][key] if subkey else v5[key]
        tp10_val = tp10[subkey][key] if subkey else tp10[key]
        delta = tp10_val - v5_val
        if key in ('dd', 'fee_drag_pct'):
            winner = tp10_key if tp10_val < v5_val else v5_key
        else:
            winner = tp10_key if tp10_val > v5_val else v5_key
        comp['head_to_head'].append({'metric': label, v5_key: v5_val, tp10_key: tp10_val,
                                     'delta': round(delta, 4), 'winner': winner})
    return comp


def build_throughput_md(config_data, throughput, clustering, weekly_dist,
                        total_bars, total_weeks, n_t1, n_t2, commit, elapsed):
    m = config_data['baseline_metrics']
    p = config_data['params']
    md = []
    md.append(f'# H20 VWAP_DEVIATION Throughput: tp=10 variant')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2})')
    md.append(f'**Params**: dev_thresh={p["dev_thresh"]}, tp_pct={p["tp_pct"]}, sl_pct={p["sl_pct"]}, time_limit={p["time_limit"]}')
    md.append(f'**Fees**: MEXC Market (T1={MEXC_MARKET_T1*10000:.1f}bps, T2={MEXC_MARKET_T2*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')
    md.append('## Baseline Metrics')
    md.append('')
    md.append('| Metric | Value |')
    md.append('|--------|-------|')
    for k, fmt in [('trades', '{}'), ('pnl', '${:.2f}'), ('pf', '{:.3f}'), ('wr', '{:.1f}%'),
                    ('expectancy', '${:.2f}'), ('exp_per_week', '${:.2f}'), ('dd', '{:.1f}%'), ('fee_drag_pct', '{:.1f}%')]:
        md.append(f'| {k} | {fmt.format(m[k])} |')
    md.append('')
    md.append('## Throughput')
    md.append('')
    md.append('| Metric | Value |')
    md.append('|--------|-------|')
    md.append(f'| Trades/week | {throughput["trades_per_week"]} |')
    md.append(f'| T1 trades | {throughput["trades_t1"]} |')
    md.append(f'| T2 trades | {throughput["trades_t2"]} |')
    md.append(f'| Max gap (bars) | {throughput["max_gap_bars"]} |')
    md.append(f'| Max gap (days) | {throughput["max_gap_days"]} |')
    md.append(f'| Utilization | {throughput["utilization_pct"]:.1f}% |')
    cv = throughput["rolling_4w_cv"]
    verdict = "CONSISTENT" if cv < 0.5 else ("MODERATE" if cv < 1.0 else "ERRATIC")
    md.append(f'| Rolling 4wk CV | {cv:.3f} ({verdict}) |')
    md.append('')
    md.append('## Clustering')
    md.append('')
    md.append(f'- Active weeks: {clustering["weeks_with_trades"]}/{clustering["total_weeks_in_data"]}')
    md.append(f'- Busiest week: {clustering["busiest_week_trades"]} trades')
    md.append(f'- Weekly: {weekly_dist}')
    md.append('')
    md.append('## Capacity')
    md.append('')
    md.append('| max_pos | Trades | PnL | PF | WR% | Exp/Wk | Util% |')
    md.append('|---------|--------|-----|----|-----|--------|-------|')
    cap = config_data['capacity']
    for mp in MAX_POS_VALUES:
        key = f'max_pos_{mp}'
        if key in cap:
            c = cap[key]
            md.append(f'| {mp} | {c["trades"]} | ${c["pnl"]:.0f} | {c["pf"]:.3f} | {c["wr"]:.1f} | ${c["exp_per_week"]:.2f} | {c["utilization_pct"]:.1f} |')
    md.append('')
    md.append('## Walk-Forward (5-fold)')
    md.append('')
    md.append(f'**Result: {config_data["wf_folds_positive"]}/5**')
    md.append('')
    md.append('| Fold | Trades | PnL | Positive |')
    md.append('|------|--------|-----|----------|')
    for fd in config_data['wf_fold_details']:
        md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.2f} | {"YES" if fd["positive"] else "NO"} |')
    md.append('')
    md.append('## Stress 2x Fees')
    md.append('')
    s = config_data['stress_2x']
    md.append(f'PF={s["pf"]:.3f} | Exp/Wk=${s["exp_per_week"]:.2f} | Trades={s["trades"]} | DD={s["dd"]:.1f}%')
    md.append('')
    md.append('---')
    md.append(f'*Generated at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


def build_fill_md(all_results, fill_report, total_bars, total_weeks, n_t1, n_t2, commit, elapsed):
    md = []
    md.append('# H20 VWAP_DEVIATION Fill Model Analysis (003)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}), {total_bars} bars ({total_weeks:.1f} wk)')
    md.append(f'**Fees**: MEXC Market (T1={MEXC_MARKET_T1*10000:.1f}bps, T2={MEXC_MARKET_T2*10000:.1f}bps)')
    md.append(f'**Stress**: 2x (T1={STRESS_2X_T1*10000:.1f}bps, T2={STRESS_2X_T2*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')
    md.append('## Head-to-Head: v5 (tp=8) vs tp=10')
    md.append('')
    md.append('| Metric | v5 (tp=8) | tp=10 | Delta | Winner |')
    md.append('|--------|-----------|-------|-------|--------|')
    for row in fill_report['comparison']['head_to_head']:
        v5_val = row[V5_PARAMS['label']]
        tp10_val = row[TP10_PARAMS['label']]
        if isinstance(v5_val, float):
            v5_s = f'{v5_val:.2f}'
            tp10_s = f'{tp10_val:.2f}'
            d_s = f'{row["delta"]:+.2f}'
        else:
            v5_s = str(v5_val)
            tp10_s = str(tp10_val)
            d_s = f'{row["delta"]:+}'
        w = 'tp=10' if 'tp10' in row['winner'] else 'v5'
        md.append(f'| {row["metric"]} | {v5_s} | {tp10_s} | {d_s} | {w} |')
    md.append('')
    for cfg in CONFIGS:
        cfg_key = cfg['label']
        r = all_results[cfg_key]
        m = r['baseline_metrics']
        md.append(f'## {cfg_key}')
        md.append('')
        md.append(f'Baseline: {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% PnL=${m["pnl"]:.2f} Exp/Wk=${m["exp_per_week"]:.2f}')
        md.append(f'WF: {r["wf_folds_positive"]}/5 | Score: {r["composite_score"]:.1f}')
        md.append('')
        md.append('### Fill Model (T1)')
        md.append('')
        md.append('| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |')
        md.append('|------|-------|--------|---------|------------|-------|')
        for mode in FILL_MODES:
            t1 = r['fill_model'][mode]['tier1']
            md.append(f'| {mode} | {t1["fill_rate"]*100:.0f}% | {t1["effective_trades"]} | ${t1["adjusted_pnl"]:.2f} | ${t1["adjusted_exp_per_week"]:.2f} | ${t1["pnl_delta_vs_market"]:.2f} |')
        md.append('')
        md.append('### Fill Model (T2)')
        md.append('')
        md.append('| Mode | Fill% | Eff.Tr | Adj.PnL | Adj.Exp/Wk | Delta |')
        md.append('|------|-------|--------|---------|------------|-------|')
        for mode in FILL_MODES:
            t2 = r['fill_model'][mode]['tier2']
            md.append(f'| {mode} | {t2["fill_rate"]*100:.0f}% | {t2["effective_trades"]} | ${t2["adjusted_pnl"]:.2f} | ${t2["adjusted_exp_per_week"]:.2f} | ${t2["pnl_delta_vs_market"]:.2f} |')
        md.append('')
        s = r['stress_2x']
        md.append(f'### Stress 2x: PF={s["pf"]:.3f} Exp/Wk=${s["exp_per_week"]:.2f} DD={s["dd"]:.1f}%')
        md.append('')
    md.append('## Verdict')
    md.append('')
    v5_r = all_results[V5_PARAMS['label']]
    tp10_r = all_results[TP10_PARAMS['label']]
    v5_score = v5_r['composite_score']
    tp10_score = tp10_r['composite_score']
    winner = 'tp=10 variant' if tp10_score > v5_score else 'v5 baseline (tp=8)'
    md.append(f'**Winner: {winner}** (scores: v5={v5_score:.1f}, tp10={tp10_score:.1f})')
    md.append('')
    md.append('Fill model impact summary:')
    for cfg in CONFIGS:
        cfg_key = cfg['label']
        r = all_results[cfg_key]
        base_pnl = r['baseline_metrics']['pnl']
        worst_mode = min(FILL_MODES, key=lambda m: r['fill_model'][m]['tier1']['adjusted_pnl'])
        worst_pnl = r['fill_model'][worst_mode]['tier1']['adjusted_pnl']
        best_mode = max(FILL_MODES, key=lambda m: r['fill_model'][m]['tier1']['adjusted_pnl'])
        best_pnl = r['fill_model'][best_mode]['tier1']['adjusted_pnl']
        md.append(f'- **{cfg_key}**: base=${base_pnl:.0f}, best={best_mode} (${best_pnl:.0f}), worst={worst_mode} (${worst_pnl:.0f})')
    md.append('')
    md.append('---')
    md.append(f'*Generated at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)


def main():
    parser = argparse.ArgumentParser(description='H20 Comprehensive Fill-Model Analysis')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  H20 VWAP_DEVIATION Comprehensive Fill-Model Analysis')
    print('  Configs: v5 (tp=8) + tp=10 variant')
    print(f'  Fees: MEXC Market (T1={MEXC_MARKET_T1*10000:.1f}bps, T2={MEXC_MARKET_T2*10000:.1f}bps)')
    print('=' * 70)
    t0 = time.time()

    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT)).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())
    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins = build_tier_coins(tiering, available_coins)
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins')
    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

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
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% ({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(c for coins in tier_coins.values() for c in coins))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    if args.dry_run:
        print('\n[DRY RUN] Data loaded successfully. Skipping backtests.')
        sys.exit(0)

    all_config_results = {}
    all_trades_cache = {}  # cache trades for report building

    for cfg in CONFIGS:
        cfg_key = cfg['label']
        print(f'\n{"="*60}')
        print(f'  CONFIG: {cfg_key}')
        print(f'{"="*60}')

        print(f'\n  [1/5] Baseline backtest (max_pos=1)...')
        trades = run_h20_variant(params=cfg, data=data, tier_coins=tier_coins,
                                 tier_indicators=tier_indicators, market_context=market_context,
                                 tier1_fee=MEXC_MARKET_T1, tier2_fee=MEXC_MARKET_T2, max_pos=1)
        all_trades_cache[cfg_key] = trades
        metrics = compute_metrics(trades, total_bars=total_bars)
        throughput = analyze_throughput(trades, total_bars)
        print(f'    Trades: {metrics["trades"]}, PF={metrics["pf"]:.3f}, WR={metrics["wr"]:.1f}%, PnL=${metrics["pnl"]:.2f}')
        print(f'    Trades/wk: {throughput["trades_per_week"]}, Exp/wk: ${metrics["exp_per_week"]:.2f}')
        print(f'    Max gap: {throughput["max_gap_bars"]}bars ({throughput["max_gap_days"]}d), Util: {throughput["utilization_pct"]:.1f}%')

        print(f'  [2/5] Walk-Forward 5-fold...')
        t_wf = time.time()
        fold_trades = run_h20_walk_forward(params=cfg, data=data, tier_coins=tier_coins,
                                           tier_indicators=tier_indicators, market_context=market_context,
                                           tier1_fee=MEXC_MARKET_T1, tier2_fee=MEXC_MARKET_T2, n_folds=5)
        folds_positive = 0
        fold_details = []
        for fold_idx in sorted(fold_trades.keys()):
            fold_pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
            fold_n = len(fold_trades[fold_idx])
            is_positive = fold_pnl > 0
            if is_positive:
                folds_positive += 1
            fold_details.append({'fold': fold_idx, 'trades': fold_n, 'pnl': round(fold_pnl, 2), 'positive': is_positive})
        print(f'    WF: {folds_positive}/5 positive folds ({time.time()-t_wf:.1f}s)')

        print(f'  [3/5] Capacity analysis (max_pos 1/2/3)...')
        capacity = analyze_capacity(data=data, tier_coins=tier_coins, tier_indicators=tier_indicators,
                                    market_context=market_context, tier1_fee=MEXC_MARKET_T1,
                                    tier2_fee=MEXC_MARKET_T2, total_bars=total_bars, params=cfg)
        for mp in MAX_POS_VALUES:
            key = f'max_pos_{mp}'
            if key in capacity:
                c = capacity[key]
                print(f'    mp={mp}: {c["trades"]}tr, PF={c["pf"]:.3f}, ${c["pnl"]:.0f}, util={c["utilization_pct"]:.1f}%')

        print(f'  [4/5] Stress test (2x fees)...')
        stress_trades = run_h20_variant(params=cfg, data=data, tier_coins=tier_coins,
                                        tier_indicators=tier_indicators, market_context=market_context,
                                        tier1_fee=STRESS_2X_T1, tier2_fee=STRESS_2X_T2, max_pos=1)
        stress_metrics = compute_metrics(stress_trades, total_bars=total_bars)
        print(f'    Stress 2x: PF={stress_metrics["pf"]:.3f}, Exp/wk=${stress_metrics["exp_per_week"]:.2f}, DD={stress_metrics["dd"]:.1f}%')

        print(f'  [5/5] Fill model analysis (5 modes)...')
        fill_results = run_fill_analysis(trades, total_bars, cfg_key)
        for mode in FILL_MODES:
            t1 = fill_results[mode]['tier1']
            print(f'    {mode:25s} T1: {t1["effective_trades"]}tr, adj_pnl=${t1["adjusted_pnl"]:.2f}, exp/wk=${t1["adjusted_exp_per_week"]:.2f}')

        score = composite_score(exp_per_week=metrics['exp_per_week'], wf_folds_positive=folds_positive, trades=metrics['trades'])

        all_config_results[cfg_key] = {
            'params': {k: v for k, v in cfg.items() if k != 'label'},
            'baseline_metrics': metrics, 'throughput': throughput,
            'wf_folds_positive': folds_positive, 'wf_folds_total': 5, 'wf_fold_details': fold_details,
            'capacity': capacity,
            'stress_2x': {'pf': stress_metrics['pf'], 'exp_per_week': stress_metrics['exp_per_week'],
                          'trades': stress_metrics['trades'], 'wr': stress_metrics['wr'], 'dd': stress_metrics['dd']},
            'fill_model': fill_results, 'composite_score': round(score, 4),
        }

    elapsed = time.time() - t0

    # Build TP10 throughput report
    tp10_key = TP10_PARAMS['label']
    tp10_data = all_config_results[tp10_key]
    tp10_throughput = tp10_data['throughput']
    tp10_trades = all_trades_cache[tp10_key]
    entry_bars = sorted(t['entry_bar'] for t in tp10_trades)
    week_counts = Counter()
    for eb in entry_bars:
        week_counts[eb // BARS_PER_WEEK] += 1
    n_weeks_int = max(1, total_bars // BARS_PER_WEEK)
    weekly_dist = [week_counts.get(w, 0) for w in range(n_weeks_int)]
    empty_weeks = sum(1 for c in weekly_dist if c == 0)
    busiest = max(weekly_dist) if weekly_dist else 0
    tp10_clustering = {'busiest_week_trades': busiest, 'empty_weeks': empty_weeks,
                       'total_weeks_in_data': n_weeks_int,
                       'weeks_with_trades': n_weeks_int - empty_weeks,
                       'pct_weeks_active': round((n_weeks_int - empty_weeks) / n_weeks_int * 100, 1)}

    tp10_json_report = {
        'run_header': {'task': 'h20_throughput_tp10', 'status': 'DONE',
                       'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
                       'hypothesis': 'H20_VWAP_DEVIATION',
                       'config': 'tp=10 variant (dev_thresh=2.0, tp_pct=10, sl_pct=5, time_limit=10)',
                       'cost_regime': 'MEXC Market',
                       'fees_bps': {'tier1': round(MEXC_MARKET_T1*10000, 1), 'tier2': round(MEXC_MARKET_T2*10000, 1)},
                       'universe': f'T1({n_t1})+T2({n_t2})', 'timeframe': '1h',
                       'total_bars': total_bars, 'total_weeks': round(total_weeks, 1),
                       'runtime_s': round(elapsed, 1)},
        'throughput': tp10_throughput, 'clustering': tp10_clustering,
        'weekly_trade_counts': weekly_dist, 'capacity': tp10_data['capacity'],
        'baseline_metrics': tp10_data['baseline_metrics'],
        'wf': {'folds_positive': tp10_data['wf_folds_positive'], 'folds_total': 5,
               'fold_details': tp10_data['wf_fold_details']},
        'stress_2x': tp10_data['stress_2x'],
    }

    tp10_json_path = ROOT / 'reports' / 'hf' / 'h20_throughput_tp10_003.json'
    tp10_json_path.parent.mkdir(parents=True, exist_ok=True)
    tp10_json_path.write_text(json.dumps(tp10_json_report, indent=2, default=str))
    print(f'\n[Report] TP10 throughput JSON: {tp10_json_path}')

    tp10_md = build_throughput_md(tp10_data, tp10_throughput, tp10_clustering, weekly_dist,
                                  total_bars, total_weeks, n_t1, n_t2, commit, elapsed)
    tp10_md_path = ROOT / 'reports' / 'hf' / 'h20_throughput_tp10_003.md'
    tp10_md_path.write_text(tp10_md)
    print(f'[Report] TP10 throughput MD:   {tp10_md_path}')

    v5_key = V5_PARAMS['label']
    fill_report = {
        'run_header': {'task': 'h20_fill_analysis', 'status': 'DONE',
                       'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
                       'hypothesis': 'H20_VWAP_DEVIATION',
                       'configs_tested': [c['label'] for c in CONFIGS],
                       'fill_modes': FILL_MODES, 'cost_regime': 'MEXC Market',
                       'fees_bps': {'tier1': round(MEXC_MARKET_T1*10000, 1), 'tier2': round(MEXC_MARKET_T2*10000, 1)},
                       'stress_fees_bps': {'tier1': round(STRESS_2X_T1*10000, 1), 'tier2': round(STRESS_2X_T2*10000, 1)},
                       'universe': f'T1({n_t1})+T2({n_t2})', 'timeframe': '1h',
                       'total_bars': total_bars, 'total_weeks': round(total_weeks, 1), 'runtime_s': round(elapsed, 1)},
        'fill_mode_definitions': get_all_modes_summary('tier1'),
        'configs': {},
        'comparison': build_comparison(all_config_results, v5_key, tp10_key, total_bars),
    }
    for cfg in CONFIGS:
        cfg_key = cfg['label']
        r = all_config_results[cfg_key]
        fill_report['configs'][cfg_key] = {
            'params': r['params'], 'baseline_metrics': r['baseline_metrics'],
            'wf_folds_positive': r['wf_folds_positive'], 'wf_fold_details': r['wf_fold_details'],
            'stress_2x': r['stress_2x'], 'composite_score': r['composite_score'],
            'fill_model': {mode: {'tier1': r['fill_model'][mode]['tier1'],
                                  'tier2': r['fill_model'][mode]['tier2']} for mode in FILL_MODES},
        }

    fill_json_path = ROOT / 'reports' / 'hf' / 'h20_fill_analysis_003.json'
    fill_json_path.write_text(json.dumps(fill_report, indent=2, default=str))
    print(f'[Report] Fill analysis JSON: {fill_json_path}')

    fill_md = build_fill_md(all_config_results, fill_report, total_bars, total_weeks, n_t1, n_t2, commit, elapsed)
    fill_md_path = ROOT / 'reports' / 'hf' / 'h20_fill_analysis_003.md'
    fill_md_path.write_text(fill_md)
    print(f'[Report] Fill analysis MD:   {fill_md_path}')

    print(f'\n{"="*70}')
    print(f'  COMPREHENSIVE FILL ANALYSIS COMPLETE')
    print(f'{"="*70}')
    for cfg in CONFIGS:
        cfg_key = cfg['label']
        r = all_config_results[cfg_key]
        m = r['baseline_metrics']
        s = r['stress_2x']
        print(f'\n  {cfg_key}:')
        print(f'    Market:   {m["trades"]}tr PF={m["pf"]:.3f} Exp/wk=${m["exp_per_week"]:.2f} WF={r["wf_folds_positive"]}/5 Score={r["composite_score"]:.1f}')
        print(f'    Stress2x: PF={s["pf"]:.3f} Exp/wk=${s["exp_per_week"]:.2f}')
        for mode in FILL_MODES:
            t1 = r['fill_model'][mode]['tier1']
            print(f'    {mode:25s} {t1["effective_trades"]}tr adj_pnl=${t1["adjusted_pnl"]:.2f} exp/wk=${t1["adjusted_exp_per_week"]:.2f}')
    print(f'\n  Runtime: {elapsed:.1f}s')
    print(f'{"="*70}')


if __name__ == '__main__':
    main()
