#!/usr/bin/env python3
"""
Part 2: T1-Only Test -- H20 VWAP_DEVIATION v5 on Tier-1 (100 liquid coins)
==========================================================================
Tests whether the H20 microstructure signal retains edge on high-liquidity
coins alone (T1), where DualConfirm at 4H had near-zero edge.

Configs tested:
  - v5 baseline:  dev=2.0, tp=8, sl=5, tl=10
  - tp=10 variant: dev=2.0, tp=10, sl=5, tl=10

Fee regime: MEXC T1 only (12.5 bps per side).
Stress: 2x T1 = 25 bps per side.

Output:
  reports/hf/part2_t1_only_001.json
  reports/hf/part2_t1_only_001.md

Usage:
    python -m strategies.hf.screening.run_part2_t1_only
    python -m strategies.hf.screening.run_part2_t1_only --dry-run
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

MEXC_T1_FEE = 0.00125
try:
    from strategies.hf.screening.costs_mexc_v2 import get_harness_fee
    MEXC_T1_FEE = get_harness_fee('mexc_market', 'tier1')
except ImportError:
    pass

STRESS_2X_T1 = MEXC_T1_FEE * 2
BARS_PER_WEEK = 168
BARS_PER_DAY  = 24

V5_PARAMS   = {'dev_thresh': 2.0, 'tp_pct': 8,  'sl_pct': 5, 'time_limit': 10, 'label': 'v5_tp8'}
TP10_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 10, 'label': 'v5_tp10'}
CONFIGS = [V5_PARAMS, TP10_PARAMS]

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


def load_universe_tiering():
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        print(f'[ERROR] Missing {path}')
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def get_t1_coins(tiering, available):
    tb = tiering.get('tier_breakdown', {})
    t1_info = tb.get('1', {})
    all_t1 = t1_info.get('coins', [])
    return [c for c in all_t1 if c in available]

def run_t1_backtest(params, data, coins, indicators, market_ctx, fee, max_pos=1):
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_ctx}
    bt = run_backtest(
        data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
        params=enriched, indicators=indicators, fee=fee, max_pos=max_pos,
    )
    for t in bt.trade_list:
        t['_tier'] = 'tier1'
        t['_fee_per_side'] = fee
    return bt.trade_list


def run_t1_walk_forward(params, data, coins, indicators, market_ctx, fee, n_folds=5):
    signal_params = {k: v for k, v in params.items() if k != 'label'}
    enriched = {**signal_params, '__market__': market_ctx}
    fold_results = walk_forward(
        data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
        params=enriched, indicators=indicators, n_folds=n_folds, fee=fee, max_pos=1,
    )
    fold_trades = {}
    for idx, fold_bt in enumerate(fold_results):
        for t in fold_bt.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = fee
        fold_trades[idx] = fold_bt.trade_list
    return fold_trades

def compute_metrics(trades, total_bars, initial_capital=2000.0):
    n = len(trades)
    if n == 0:
        return dict(trades=0, pnl=0.0, pf=0.0, wr=0.0, dd=0.0,
                    expectancy=0.0, trades_per_week=0.0, exp_per_week=0.0,
                    fee_drag_pct=0.0)
    total_pnl = sum(t['pnl'] for t in trades)
    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tpw = n / total_weeks
    epw = expectancy * tpw
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size  = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        tfee  = t.get('_fee_per_side', MEXC_T1_FEE)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees  = size * tfee + (size + gross) * tfee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
    equity = initial_capital
    peak   = equity
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


def main():
    parser = argparse.ArgumentParser(description='Part 2: T1-Only H20 Test')
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2: T1-Only Test -- H20 VWAP_DEVIATION')
    print(f'  Fee: MEXC T1 = {MEXC_T1_FEE*10000:.1f} bps per side')
    print(f'  Stress: 2x T1 = {STRESS_2X_T1*10000:.1f} bps per side')
    print('  Configs: v5 (tp=8) + tp=10 variant')
    print('=' * 70)
    t0 = time.time()

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_cache('1h', require_data=True)
    available = set(data.keys())

    tiering = load_universe_tiering()
    t1_coins = get_t1_coins(tiering, available)
    print(f'[Universe] T1 coins available: {len(t1_coins)}')
    if not t1_coins:
        print('[ERROR] No T1 coins found in candle data.')
        sys.exit(1)

    print('[Indicators] Precomputing base indicators for T1...')
    ti = time.time()
    indicators = precompute_base_indicators(data, t1_coins)
    print(f'  {len(t1_coins)} coins in {time.time()-ti:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    extend_indicators(data, t1_coins, indicators)
    cov = get_feature_coverage(indicators, t1_coins)
    print(f'  VWAP coverage: {cov["vwap_pct"]:.0f}% ({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    ctx_coins = list(t1_coins)
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available and btc not in ctx_coins:
            ctx_coins.append(btc)
            print(f'  Added {btc} to market context')
    market_ctx = precompute_market_context(data, ctx_coins)
    print('  Done.')

    for coin in indicators:
        indicators[coin]['__coin__'] = coin

    total_bars = max(ind.get('n', 0) for ind in indicators.values()) if indicators else 0
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    if args.dry_run:
        print('\n[DRY RUN] Data loaded. Skipping backtests.')
        sys.exit(0)

    results = {}

    for cfg in CONFIGS:
        label = cfg['label']
        print(f'\n{"="*60}')
        print(f'  CONFIG: {label}  (T1 only, {len(t1_coins)} coins)')
        print(f'{"="*60}')

        print(f'  [1/4] Baseline (market fee={MEXC_T1_FEE*10000:.1f}bps)...')
        trades = run_t1_backtest(cfg, data, t1_coins, indicators, market_ctx, MEXC_T1_FEE)
        m = compute_metrics(trades, total_bars)
        max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
        print(f'    {m["trades"]}tr PF={m["pf"]:.3f} WR={m["wr"]:.1f}% '
              f'PnL=${m["pnl"]:.2f} Exp/wk=${m["exp_per_week"]:.4f}')
        print(f'    DD={m["dd"]:.1f}% MaxGap={max_gap_days}d Tr/wk={m["trades_per_week"]:.2f}')

        print(f'  [2/4] Walk-Forward 5-fold...')
        twf = time.time()
        fold_trades = run_t1_walk_forward(cfg, data, t1_coins, indicators, market_ctx, MEXC_T1_FEE)
        folds_positive = 0
        fold_details = []
        for fi in sorted(fold_trades.keys()):
            fpnl = sum(t['pnl'] for t in fold_trades[fi])
            fn   = len(fold_trades[fi])
            pos  = fpnl > 0
            if pos:
                folds_positive += 1
            fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos})
        top1_fold_conc = compute_top1_fold_concentration(fold_details)
        print(f'    WF: {folds_positive}/5 ({time.time()-twf:.1f}s)')
        print(f'    Top-1 fold concentration: {top1_fold_conc:.2%}')
        for fd in fold_details:
            tag = 'YES' if fd['positive'] else 'NO'
            print(f'      Fold {fd["fold"]}: {fd["trades"]}tr ${fd["pnl"]:.2f} ({tag})')

        print(f'  [3/4] Stress 2x ({STRESS_2X_T1*10000:.1f}bps)...')
        stress_trades = run_t1_backtest(cfg, data, t1_coins, indicators, market_ctx, STRESS_2X_T1)
        sm = compute_metrics(stress_trades, total_bars)
        print(f'    {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.4f} DD={sm["dd"]:.1f}%')

        print(f'  [4/4] Per-coin breakdown...')
        coin_pnl = {}
        for t in trades:
            c = t.get('pair', 'unknown')
            coin_pnl[c] = coin_pnl.get(c, 0.0) + t['pnl']
        top_coins = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
        worst_coins = sorted(coin_pnl.items(), key=lambda x: x[1])[:3]
        total_pos_pnl = sum(v for v in coin_pnl.values() if v > 0)
        top1_coin_conc = top_coins[0][1] / total_pos_pnl if total_pos_pnl > 0 and top_coins and top_coins[0][1] > 0 else 0.0
        top3_coin_conc = sum(v for _, v in top_coins[:3] if v > 0) / total_pos_pnl if total_pos_pnl > 0 else 0.0
        print(f'    Coins with trades: {len(coin_pnl)}')
        if top_coins:
            print(f'    Top-1 coin: {top_coins[0][0]} ${top_coins[0][1]:.2f} ({top1_coin_conc:.1%})')
        print(f'    Top-3 coin conc: {top3_coin_conc:.1%}')

        gates = {
            'G1_trades_per_week':    {'value': m['trades_per_week'],   'threshold': '>=0.5/wk'},
            'G2_max_gap_days':       {'value': max_gap_days,          'threshold': '<=21d'},
            'G3_exp_per_week_mkt':   {'value': m['exp_per_week'],     'threshold': '>$0'},
            'G4_exp_per_week_2x':    {'value': sm['exp_per_week'],    'threshold': '>$0'},
            'G5_max_dd_pct':         {'value': m['dd'],               'threshold': '<=50%'},
            'G6_wf_folds_positive':  {'value': folds_positive,        'threshold': '>=3/5'},
            'G8_top1_fold_conc':     {'value': top1_fold_conc,        'threshold': '<0.60'},
        }
        gates['G1_trades_per_week']['pass'] = m['trades_per_week'] >= 0.5
        gates['G2_max_gap_days']['pass']    = max_gap_days <= 21
        gates['G3_exp_per_week_mkt']['pass'] = m['exp_per_week'] > 0
        gates['G4_exp_per_week_2x']['pass'] = sm['exp_per_week'] > 0
        gates['G5_max_dd_pct']['pass']       = m['dd'] <= 50
        gates['G6_wf_folds_positive']['pass'] = folds_positive >= 3
        gates['G8_top1_fold_conc']['pass']   = top1_fold_conc < 0.60

        all_pass = all(g['pass'] for g in gates.values())
        verdict = 'PASS' if all_pass else 'FAIL'
        failed_gates = [k for k, g in gates.items() if not g['pass']]

        print(f'\n  GATES ({label}):')
        for gname, gv in gates.items():
            tag = 'PASS' if gv['pass'] else 'FAIL'
            print(f'    {gname}: {gv["value"]} {gv["threshold"]} -> {tag}')
        print(f'  VERDICT: {verdict}')
        if failed_gates:
            print(f'  Failed: {", ".join(failed_gates)}')

        results[label] = {
            'params': {k: v for k, v in cfg.items() if k != 'label'},
            'universe': {'tier': 'T1', 'coins': len(t1_coins), 'fee_bps': round(MEXC_T1_FEE*10000, 1)},
            'baseline': m,
            'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
            'walk_forward': {
                'folds_positive': folds_positive, 'folds_total': 5,
                'fold_details': fold_details,
                'top1_fold_concentration': top1_fold_conc,
            },
            'stress_2x': {
                'fee_bps': round(STRESS_2X_T1*10000, 1),
                'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
                'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
            },
            'coin_breakdown': {
                'coins_with_trades': len(coin_pnl),
                'top5': [{'coin': c, 'pnl': round(p, 2)} for c, p in top_coins],
                'worst3': [{'coin': c, 'pnl': round(p, 2)} for c, p in worst_coins],
                'top1_coin_conc': round(top1_coin_conc, 4),
                'top3_coin_conc': round(top3_coin_conc, 4),
            },
            'gates': gates,
            'verdict': verdict,
            'failed_gates': failed_gates,
        }

    elapsed = time.time() - t0

    v5   = results[V5_PARAMS['label']]
    tp10 = results[TP10_PARAMS['label']]
    comparison = {
        'v5_vs_tp10': {
            'trades':      {'v5': v5['baseline']['trades'],     'tp10': tp10['baseline']['trades']},
            'pnl':         {'v5': v5['baseline']['pnl'],        'tp10': tp10['baseline']['pnl']},
            'pf':          {'v5': v5['baseline']['pf'],         'tp10': tp10['baseline']['pf']},
            'exp_per_week':{'v5': v5['baseline']['exp_per_week'],'tp10': tp10['baseline']['exp_per_week']},
            'dd':          {'v5': v5['baseline']['dd'],         'tp10': tp10['baseline']['dd']},
            'wf_folds':    {'v5': v5['walk_forward']['folds_positive'], 'tp10': tp10['walk_forward']['folds_positive']},
            'stress_epw':  {'v5': v5['stress_2x']['exp_per_week'], 'tp10': tp10['stress_2x']['exp_per_week']},
        },
    }

    report = {
        'run_header': {
            'task': 'part2_t1_only',
            'status': 'DONE',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'universe': f'T1 only ({len(t1_coins)} coins)',
            'fee_regime': 'MEXC Market T1',
            'fee_bps_per_side': round(MEXC_T1_FEE * 10000, 1),
            'stress_bps_per_side': round(STRESS_2X_T1 * 10000, 1),
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        't1_coins': sorted(t1_coins),
        'configs': results,
        'comparison': comparison,
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / 'part2_t1_only_001.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md = build_md(report, elapsed, commit, len(t1_coins), total_bars, total_weeks)
    md_path = out_dir / 'part2_t1_only_001.md'
    md_path.write_text(md)
    print(f'[Report] MD:   {md_path}')

    print(f'\n{"="*70}')
    print(f'  T1-ONLY TEST COMPLETE')
    print(f'{"="*70}')
    for cfg in CONFIGS:
        lbl = cfg['label']
        r   = results[lbl]
        b   = r['baseline']
        s   = r['stress_2x']
        wf  = r['walk_forward']['folds_positive']
        print(f'\n  {lbl}:')
        print(f'    Market:  {b["trades"]}tr PF={b["pf"]:.3f} WR={b["wr"]:.1f}% '
              f'PnL=${b["pnl"]:.2f} Exp/wk=${b["exp_per_week"]:.4f} DD={b["dd"]:.1f}%')
        print(f'    Stress:  PF={s["pf"]:.3f} Exp/wk=${s["exp_per_week"]:.4f}')
        print(f'    WF: {wf}/5 | Verdict: {r["verdict"]}')
        if r['failed_gates']:
            print(f'    Failed:  {", ".join(r["failed_gates"])}')
    print(f'\n  Runtime: {elapsed:.1f}s')
    print(f'{"="*70}')


def build_md(report, elapsed, commit, n_t1, total_bars, total_weeks):
    lines = []
    lines.append('# Part 2: T1-Only Test -- H20 VWAP_DEVIATION')
    lines.append('')
    lines.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'**Commit**: {commit}')
    lines.append(f'**Universe**: T1 only ({n_t1} coins)')
    lines.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    lines.append(f'**Fee**: MEXC T1 = {MEXC_T1_FEE*10000:.1f} bps/side')
    lines.append(f'**Stress**: 2x = {STRESS_2X_T1*10000:.1f} bps/side')
    lines.append(f'**Runtime**: {elapsed:.1f}s')
    lines.append('')

    lines.append('## Context')
    lines.append('')
    lines.append('DualConfirm at 4H had near-zero edge on T1 (liquid coins).')
    lines.append('H20 VWAP_DEVIATION is microstructure-based -- does it work differently on T1?')
    lines.append('')
    lines.append('Key comparisons:')
    lines.append('- Full 316 coins: PF=1.138, DD=53%, WF=3/5 (FAIL)')
    lines.append('- 135 coins (alphabetical): PF=1.85, WF=5/5 (PASS)')
    lines.append('- T1 fee is much lower (12.5bps vs 23.5bps per side)')
    lines.append('')

    lines.append('## Head-to-Head: v5 (tp=8) vs tp=10')
    lines.append('')
    lines.append('| Metric | v5 (tp=8) | tp=10 | Winner |')
    lines.append('|--------|-----------|-------|--------|')

    comp = report['comparison']['v5_vs_tp10']
    for metric, key, fmt, lower_better in [
        ('Trades', 'trades', '{}', False),
        ('PnL ($)', 'pnl', '${:.2f}', False),
        ('PF', 'pf', '{:.3f}', False),
        ('Exp/Wk ($)', 'exp_per_week', '${:.4f}', False),
        ('DD (%)', 'dd', '{:.1f}%', True),
        ('WF Folds', 'wf_folds', '{}/5', False),
        ('Stress Exp/Wk', 'stress_epw', '${:.4f}', False),
    ]:
        v5v = comp[key]['v5']
        t10v = comp[key]['tp10']
        if key == 'wf_folds':
            v5s = f'{v5v}/5'
            t10s = f'{t10v}/5'
        else:
            v5s = fmt.format(v5v)
            t10s = fmt.format(t10v)
        if lower_better:
            w = 'tp=10' if t10v < v5v else ('v5' if v5v < t10v else 'tie')
        else:
            w = 'tp=10' if t10v > v5v else ('v5' if v5v > t10v else 'tie')
        lines.append(f'| {metric} | {v5s} | {t10s} | {w} |')
    lines.append('')

    for cfg in CONFIGS:
        lbl = cfg['label']
        r = report['configs'][lbl]
        b = r['baseline']
        s = r['stress_2x']
        wf = r['walk_forward']

        lines.append(f'## {lbl}')
        lines.append('')
        lines.append('### Baseline Metrics')
        lines.append('')
        lines.append('| Metric | Value |')
        lines.append('|--------|-------|')
        lines.append(f'| Trades | {b["trades"]} |')
        lines.append(f'| PnL | ${b["pnl"]:.2f} |')
        lines.append(f'| PF | {b["pf"]:.3f} |')
        lines.append(f'| WR | {b["wr"]:.1f}% |')
        lines.append(f'| Expectancy | ${b["expectancy"]:.4f} |')
        lines.append(f'| Exp/Week | ${b["exp_per_week"]:.4f} |')
        lines.append(f'| Trades/Week | {b["trades_per_week"]:.2f} |')
        lines.append(f'| Max DD | {b["dd"]:.1f}% |')
        lines.append(f'| Fee Drag | {b["fee_drag_pct"]:.1f}% |')
        lines.append(f'| Max Gap | {r["max_gap"]["days"]}d ({r["max_gap"]["bars"]} bars) |')
        lines.append('')

        lines.append('### Walk-Forward (5-fold)')
        lines.append('')
        lines.append(f'**Result: {wf["folds_positive"]}/5** | Top-1 fold conc: {wf["top1_fold_concentration"]:.1%}')
        lines.append('')
        lines.append('| Fold | Trades | PnL | Positive |')
        lines.append('|------|--------|-----|----------|')
        for fd in wf['fold_details']:
            tag = 'YES' if fd['positive'] else 'NO'
            lines.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.2f} | {tag} |')
        lines.append('')

        lines.append('### Stress 2x')
        lines.append('')
        lines.append(f'PF={s["pf"]:.3f} | Exp/Wk=${s["exp_per_week"]:.4f} | '
                      f'Trades={s["trades"]} | DD={s["dd"]:.1f}%')
        lines.append('')

        lines.append('### Coin Breakdown')
        lines.append('')
        cb = r['coin_breakdown']
        lines.append(f'- Coins with trades: {cb["coins_with_trades"]}')
        lines.append(f'- Top-1 coin concentration: {cb["top1_coin_conc"]:.1%}')
        lines.append(f'- Top-3 coin concentration: {cb["top3_coin_conc"]:.1%}')
        top5_str = ", ".join(f'{c["coin"]} (${c["pnl"]:.0f})' for c in cb["top5"])
        worst3_str = ", ".join(f'{c["coin"]} (${c["pnl"]:.0f})' for c in cb["worst3"])
        lines.append(f'- Top 5: {top5_str}')
        lines.append(f'- Worst 3: {worst3_str}')
        lines.append('')

        lines.append('### Gate Verdicts')
        lines.append('')
        lines.append('| Gate | Value | Threshold | Pass |')
        lines.append('|------|-------|-----------|------|')
        for gname, gv in r['gates'].items():
            tag = 'PASS' if gv['pass'] else '**FAIL**'
            lines.append(f'| {gname} | {gv["value"]} | {gv["threshold"]} | {tag} |')
        lines.append('')
        lines.append(f'**VERDICT: {r["verdict"]}**')
        if r['failed_gates']:
            lines.append(f'Failed gates: {", ".join(r["failed_gates"])}')
        lines.append('')

    lines.append('## Conclusion')
    lines.append('')
    v5r = report['configs'][V5_PARAMS['label']]
    t10r = report['configs'][TP10_PARAMS['label']]
    lines.append(f'- v5 (tp=8): {v5r["verdict"]} -- {v5r["baseline"]["trades"]}tr '
                  f'PF={v5r["baseline"]["pf"]:.3f} Exp/wk=${v5r["baseline"]["exp_per_week"]:.4f}')
    lines.append(f'- tp=10: {t10r["verdict"]} -- {t10r["baseline"]["trades"]}tr '
                  f'PF={t10r["baseline"]["pf"]:.3f} Exp/wk=${t10r["baseline"]["exp_per_week"]:.4f}')
    lines.append('')
    lines.append('T1 coins have lower fees (12.5bps vs ~23.5bps) but also fewer microstructure')
    lines.append('dislocations. The question is whether the fee advantage compensates.')
    lines.append('')
    lines.append('---')
    lines.append(f'*Generated at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(lines)


if __name__ == '__main__':
    main()
