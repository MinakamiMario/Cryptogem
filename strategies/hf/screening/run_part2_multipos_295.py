#!/usr/bin/env python3
"""
Part 2 -- Agent C4-A1: Multi-Position Test (max_pos=2) on 295 Coins
====================================================================
Tests max_pos=2 (two simultaneous positions) vs max_pos=1 (default)
using v5 params on the 295-coin universe (excl_all_negative).

max_pos=2 allows two concurrent positions, which means:
  - Potentially more trades (no blocking when one position is open)
  - Smaller position sizes per trade (capital split between 2 slots)
  - Different risk profile (diversification vs concentration)

For EACH max_pos setting runs:
  1. Baseline backtest (MEXC market fees)
  2. Stress test (2x fees)
  3. Walk-forward 5-fold
  4. Fold concentration
  5. Full 8-gate evaluation (G1-G8 except G7)

Output:
  reports/hf/part2_multipos_295_001.json
  reports/hf/part2_multipos_295_001.md

Usage:
    python -m strategies.hf.screening.run_part2_multipos_295
    python -m strategies.hf.screening.run_part2_multipos_295 --dry-run
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

# v5 baseline params (leader config)
PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# 21 net-negative coins identified by A3 loss cluster analysis
EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

GATE_THRESHOLDS = {
    'G1_trades_per_week': 10,
    'G2_max_gap_days': 2.5,
    'G3_exp_per_week_market': 0,
    'G4_exp_per_week_stress': 0,
    'G5_max_dd_pct': 20,
    'G6_wf_folds_positive': 4,
    'G8_top1_fold_conc_pct': 35,
}

# Max positions to test
MAX_POS_VALUES = [1, 2]


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


def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params, max_pos=1):
    """Run backtest across tiers with given max_pos."""
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
            params=signal_params, indicators=indicators, fee=fee,
            max_pos=max_pos,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None, max_pos=1):
    """Run walk-forward across tiers with given max_pos."""
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
            fee=fee, max_pos=max_pos,
        )
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)
    return tier_fold_trades


def compute_metrics(trades, total_bars):
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
                'trades_per_week': 0.0, 'exp_per_week': 0.0,
                'max_dd_pct': 0.0, 'max_gap_days': 0.0, 'expectancy': 0.0,
                'fee_drag_pct': 0.0}
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
    # Drawdown
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
    # Max gap
    max_gap_bars = 0
    if len(sorted_trades) > 1:
        for i in range(1, len(sorted_trades)):
            gap = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i-1].get('entry_bar', 0)
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        fee = t.get('_fee_per_side', 0.00125)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * fee + (size + gross) * fee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag_pct = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
    return {
        'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
        'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4),
        'fee_drag_pct': round(fee_drag_pct, 2),
    }


def compute_concentration(trades):
    coin_pnl = defaultdict(float)
    for t in trades:
        coin_pnl[t.get('pair', 'unknown')] += t['pnl']
    positive_coins = {c: p for c, p in coin_pnl.items() if p > 0}
    total_positive = sum(positive_coins.values())
    if total_positive <= 0:
        return {'top1_pct': 100.0, 'top3_pct': 100.0, 'top1_coin': '?'}
    sorted_positive = sorted(positive_coins.items(), key=lambda x: x[1], reverse=True)
    top1_pct = sorted_positive[0][1] / total_positive * 100
    top3_pct = sum(v for _, v in sorted_positive[:3]) / total_positive * 100
    return {'top1_pct': round(top1_pct, 1), 'top3_pct': round(top3_pct, 1),
            'top1_coin': sorted_positive[0][0]}


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
    gates['G1'] = {'name': 'Trades/week', 'value': round(g1_val, 2),
                   'threshold': '>= 10', 'pass': g1_val >= 10}
    g2_val = metrics['max_gap_days']
    gates['G2'] = {'name': 'Max gap (days)', 'value': round(g2_val, 2),
                   'threshold': '<= 2.5', 'pass': g2_val <= 2.5}
    g3_val = metrics['exp_per_week']
    gates['G3'] = {'name': 'Exp/week (market)', 'value': round(g3_val, 2),
                   'threshold': '> $0', 'pass': g3_val > 0}
    g4_val = stress_metrics['exp_per_week']
    gates['G4'] = {'name': 'Exp/week (2x stress)', 'value': round(g4_val, 2),
                   'threshold': '> $0', 'pass': g4_val > 0}
    g5_val = metrics['max_dd_pct']
    gates['G5'] = {'name': 'Max DD%', 'value': round(g5_val, 1),
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


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def tier_pnl_breakdown(trades):
    t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
    t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
    t1_pnl = sum(t['pnl'] for t in t1_trades)
    t2_pnl = sum(t['pnl'] for t in t2_trades)
    return {
        'tier1': {'trades': len(t1_trades), 'pnl': round(t1_pnl, 2)},
        'tier2': {'trades': len(t2_trades), 'pnl': round(t2_pnl, 2)},
    }


def exit_reason_breakdown(trades):
    """Break down trades by exit reason."""
    reasons = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0})
    for t in trades:
        r = t.get('reason', 'UNKNOWN')
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1
    return {r: {'count': s['count'], 'pnl': round(s['pnl'], 2),
                'wr': round(s['wins'] / s['count'] * 100, 1) if s['count'] > 0 else 0}
            for r, s in sorted(reasons.items(), key=lambda x: x[1]['pnl'], reverse=True)}


def run_full_evaluation(label, data, tier_coins, tier_indicators,
                        market_context, tier1_fee, tier2_fee,
                        stress_tier1_fee, stress_tier2_fee, total_bars,
                        params, max_pos):
    """Run baseline + stress + WF + gate evaluation for given max_pos."""
    t0 = time.time()
    print(f'\n  [{label}] Running baseline (max_pos={max_pos})...')
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, params=params, max_pos=max_pos)
    metrics = compute_metrics(trades, total_bars)
    conc = compute_concentration(trades)
    tier_split = tier_pnl_breakdown(trades)
    exit_reasons = exit_reason_breakdown(trades)
    n_coins_with_trades = len(set(t.get('pair', '') for t in trades))
    print(f'    trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'WR={metrics["wr"]:.1f}% exp/w=${metrics["exp_per_week"]:.2f} '
          f'DD={metrics["max_dd_pct"]:.1f}% gap={metrics["max_gap_days"]:.2f}d')

    print(f'  [{label}] Running stress (2x fees, max_pos={max_pos})...')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee,
                                params=params, max_pos=max_pos)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'    stress: trades={stress_metrics["trades"]} '
          f'exp/w=${stress_metrics["exp_per_week"]:.2f} PF={stress_metrics["pf"]:.3f}')

    print(f'  [{label}] Running walk-forward 5-fold (max_pos={max_pos})...')
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5, params=params,
                         max_pos=max_pos)
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
    fold_conc = compute_fold_concentration(fold_trades)
    print(f'    WF={folds_positive}/5  fold_conc={fold_conc["top1_fold_conc_pct"]:.1f}%')

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)
    elapsed = time.time() - t0
    print(f'    Gates: {gate_eval["score"]}  ({elapsed:.1f}s)')
    for gid, g in gate_eval['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'      {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    return {
        'label': label,
        'params': params,
        'max_pos': max_pos,
        'n_coins': sum(len(c) for c in tier_coins.values()),
        'n_t1': len(tier_coins.get('tier1', [])),
        'n_t2': len(tier_coins.get('tier2', [])),
        'n_coins_with_trades': n_coins_with_trades,
        'metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'], 'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'], 'wr': stress_metrics['wr'],
            'exp_per_week': stress_metrics['exp_per_week'],
            'max_dd_pct': stress_metrics['max_dd_pct'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'concentration': conc,
        'tier_split': tier_split,
        'exit_reasons': exit_reasons,
        'gate_evaluation': gate_eval,
        'runtime_s': round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C4-A1: Multi-Position Test (max_pos=2) on 295 coins')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C4-A1: Multi-Position Test')
    print('  max_pos=1 vs max_pos=2 with v5 params on 295-coin universe')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps')
    print(f'[Params] v5: {PARAMS_V5}')

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)
    n_t1_full = len(tier_coins_full['tier1'])
    n_t2_full = len(tier_coins_full['tier2'])
    print(f'[Universe] Full: T1={n_t1_full}, T2={n_t2_full}, total={n_t1_full+n_t2_full}')

    # Build 295-coin universe (exclude 21 net-negative)
    tier_coins_295 = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }
    n_t1 = len(tier_coins_295['tier1'])
    n_t2 = len(tier_coins_295['tier2'])
    n_excluded = (n_t1_full - n_t1) + (n_t2_full - n_t2)
    print(f'[Universe] 295-coin: T1={n_t1}, T2={n_t2}, total={n_t1+n_t2} (excluded {n_excluded})')

    if not tier_coins_295['tier1'] and not tier_coins_295['tier2']:
        print('[ERROR] No coins after exclusion.')
        sys.exit(1)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2} (295 coins)')
        print(f'  Params: {PARAMS_V5}')
        print(f'  max_pos values to test: {MAX_POS_VALUES}')
        print(f'  Tests per max_pos: baseline, stress 2x, walk-forward 5-fold, 7 gates')
        sys.exit(0)

    # Precompute indicators (shared between max_pos=1 and max_pos=2)
    print('[Indicators] Precomputing base indicators for 295-coin universe...')
    tier_indicators = {}
    for tier_name, coins in tier_coins_295.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_295.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_295.get('tier1', []) + tier_coins_295.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__ into indicators
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins_295)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ===== RUN 1: max_pos=1 (baseline) =====
    print('\n' + '=' * 70)
    print('  RUN 1: max_pos=1 (single position) - v5 params on 295 coins')
    print('=' * 70)
    mp1_result = run_full_evaluation(
        label='v5_maxpos1',
        data=data, tier_coins=tier_coins_295,
        tier_indicators=tier_indicators, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars, params=PARAMS_V5, max_pos=1,
    )

    # ===== RUN 2: max_pos=2 =====
    print('\n' + '=' * 70)
    print('  RUN 2: max_pos=2 (dual positions) - v5 params on 295 coins')
    print('=' * 70)
    mp2_result = run_full_evaluation(
        label='v5_maxpos2',
        data=data, tier_coins=tier_coins_295,
        tier_indicators=tier_indicators, market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars, params=PARAMS_V5, max_pos=2,
    )

    elapsed_total = time.time() - t0_total

    # ===== HEAD-TO-HEAD COMPARISON =====
    print('\n' + '=' * 70)
    print('  HEAD-TO-HEAD: max_pos=1 vs max_pos=2')
    print('=' * 70)
    for label, r in [('max_pos=1', mp1_result), ('max_pos=2', mp2_result)]:
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        sm = r['stress_metrics']
        print(f'\n  {label}:')
        print(f'    Trades={m["trades"]}  PF={m["pf"]:.3f}  WR={m["wr"]:.1f}%  P&L=${m["pnl"]:.0f}')
        print(f'    Exp/wk=${m["exp_per_week"]:.2f}  DD={m["max_dd_pct"]:.1f}%  Gap={m["max_gap_days"]:.2f}d')
        print(f'    Stress: exp/wk=${sm["exp_per_week"]:.2f}  PF={sm["pf"]:.3f}')
        print(f'    WF={r["wf_folds_positive"]}/5  Fold conc={fc["top1_fold_conc_pct"]:.1f}%')
        print(f'    Gates: {ge["score"]}  all_pass={ge["all_pass"]}')

    # ===== BUILD JSON REPORT =====
    def better(a, b, higher_is_better=True):
        if higher_is_better:
            return 'mp1' if a > b else ('mp2' if b > a else 'tie')
        else:
            return 'mp1' if a < b else ('mp2' if b < a else 'tie')

    head_to_head = {
        'mp1_gates': mp1_result['gate_evaluation']['score'],
        'mp2_gates': mp2_result['gate_evaluation']['score'],
        'mp1_all_pass': mp1_result['gate_evaluation']['all_pass'],
        'mp2_all_pass': mp2_result['gate_evaluation']['all_pass'],
        'mp1_pnl': mp1_result['metrics']['pnl'],
        'mp2_pnl': mp2_result['metrics']['pnl'],
        'mp1_exp_per_week': mp1_result['metrics']['exp_per_week'],
        'mp2_exp_per_week': mp2_result['metrics']['exp_per_week'],
        'mp1_trades': mp1_result['metrics']['trades'],
        'mp2_trades': mp2_result['metrics']['trades'],
        'mp1_dd': mp1_result['metrics']['max_dd_pct'],
        'mp2_dd': mp2_result['metrics']['max_dd_pct'],
        'mp1_fold_conc': mp1_result['fold_concentration']['top1_fold_conc_pct'],
        'mp2_fold_conc': mp2_result['fold_concentration']['top1_fold_conc_pct'],
        'trade_increase_pct': round(
            (mp2_result['metrics']['trades'] - mp1_result['metrics']['trades'])
            / mp1_result['metrics']['trades'] * 100, 1)
            if mp1_result['metrics']['trades'] > 0 else 0,
        'winner_by_gates': better(mp1_result['gate_evaluation']['pass_count'],
                                   mp2_result['gate_evaluation']['pass_count']),
    }

    report = {
        'run_header': {
            'task': 'part2_multipos_295', 'agent': 'C4-A1',
            'date': datetime.now().strftime('%Y-%m-%d'), 'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'max_pos_tested': MAX_POS_VALUES,
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1),
                        'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                               'tier2': round(stress_tier2_fee * 10000, 1)},
            'universe_full': f'T1({n_t1_full})+T2({n_t2_full})',
            'universe_295': f'T1({n_t1})+T2({n_t2})',
            'excluded_coins': sorted(EXCLUDED_COINS),
            'n_excluded': n_excluded,
            'timeframe': '1h', 'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'mp1_result': mp1_result,
        'mp2_result': mp2_result,
        'head_to_head': head_to_head,
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_multipos_295_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ===== BUILD MARKDOWN REPORT =====
    md = []
    md.append('# Part 2 -- Multi-Position Test: max_pos=1 vs max_pos=2 (Agent C4-A1)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: 295 coins (316 minus {n_excluded} net-negative)')
    md.append(f'**Tier split**: T1={n_t1}, T2={n_t2}')
    md.append(f'**Params**: v5 (dev={PARAMS_V5["dev_thresh"]}, tp={PARAMS_V5["tp_pct"]}, '
              f'sl={PARAMS_V5["sl_pct"]}, tl={PARAMS_V5["time_limit"]})')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, '
              f'T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Head-to-head comparison
    md.append('## 1. Head-to-Head Comparison')
    md.append('')
    md.append('| Metric | max_pos=1 | max_pos=2 | Better |')
    md.append('|--------|-----------|-----------|--------|')

    m1 = mp1_result['metrics']
    m2 = mp2_result['metrics']
    s1 = mp1_result['stress_metrics']
    s2 = mp2_result['stress_metrics']
    g1 = mp1_result['gate_evaluation']
    g2 = mp2_result['gate_evaluation']
    fc1 = mp1_result['fold_concentration']['top1_fold_conc_pct']
    fc2 = mp2_result['fold_concentration']['top1_fold_conc_pct']

    def better_str(a, b, higher_is_better=True):
        if higher_is_better:
            return 'mp1' if a > b else ('mp2' if b > a else 'TIE')
        else:
            return 'mp1' if a < b else ('mp2' if b < a else 'TIE')

    md.append(f'| Trades | {m1["trades"]} | {m2["trades"]} | '
              f'{better_str(m1["trades"], m2["trades"])} |')
    md.append(f'| Trades/wk | {m1["trades_per_week"]:.2f} | {m2["trades_per_week"]:.2f} | '
              f'{better_str(m1["trades_per_week"], m2["trades_per_week"])} |')
    md.append(f'| P&L | ${m1["pnl"]:.0f} | ${m2["pnl"]:.0f} | '
              f'{better_str(m1["pnl"], m2["pnl"])} |')
    md.append(f'| PF | {m1["pf"]:.3f} | {m2["pf"]:.3f} | '
              f'{better_str(m1["pf"], m2["pf"])} |')
    md.append(f'| WR | {m1["wr"]:.1f}% | {m2["wr"]:.1f}% | '
              f'{better_str(m1["wr"], m2["wr"])} |')
    md.append(f'| Exp/wk | ${m1["exp_per_week"]:.2f} | ${m2["exp_per_week"]:.2f} | '
              f'{better_str(m1["exp_per_week"], m2["exp_per_week"])} |')
    md.append(f'| Max DD | {m1["max_dd_pct"]:.1f}% | {m2["max_dd_pct"]:.1f}% | '
              f'{better_str(m1["max_dd_pct"], m2["max_dd_pct"], False)} |')
    md.append(f'| Max Gap | {m1["max_gap_days"]:.2f}d | {m2["max_gap_days"]:.2f}d | '
              f'{better_str(m1["max_gap_days"], m2["max_gap_days"], False)} |')
    md.append(f'| Fee Drag | {m1["fee_drag_pct"]:.1f}% | {m2["fee_drag_pct"]:.1f}% | '
              f'{better_str(m1["fee_drag_pct"], m2["fee_drag_pct"], False)} |')
    md.append(f'| Stress Exp/wk | ${s1["exp_per_week"]:.2f} | ${s2["exp_per_week"]:.2f} | '
              f'{better_str(s1["exp_per_week"], s2["exp_per_week"])} |')
    md.append(f'| Stress PF | {s1["pf"]:.3f} | {s2["pf"]:.3f} | '
              f'{better_str(s1["pf"], s2["pf"])} |')
    md.append(f'| WF folds+ | {mp1_result["wf_folds_positive"]}/5 | '
              f'{mp2_result["wf_folds_positive"]}/5 | '
              f'{better_str(mp1_result["wf_folds_positive"], mp2_result["wf_folds_positive"])} |')
    md.append(f'| Fold conc | {fc1:.1f}% | {fc2:.1f}% | '
              f'{better_str(fc1, fc2, False)} |')
    md.append(f'| Coins traded | {mp1_result["n_coins_with_trades"]} | '
              f'{mp2_result["n_coins_with_trades"]} | '
              f'{better_str(mp1_result["n_coins_with_trades"], mp2_result["n_coins_with_trades"])} |')
    md.append(f'| **Gates** | **{g1["score"]}** | **{g2["score"]}** | '
              f'**{better_str(g1["pass_count"], g2["pass_count"])}** |')
    md.append('')

    # Gate detail for each
    for label, r in [('max_pos=1', mp1_result), ('max_pos=2', mp2_result)]:
        ge = r['gate_evaluation']
        md.append(f'## 2. Gate Detail: {label}')
        md.append('')
        md.append(f'**max_pos**: {r["max_pos"]}')
        md.append(f'**Coins**: {r["n_coins"]} (T1={r["n_t1"]}, T2={r["n_t2"]})')
        md.append('')
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')

        # Walk-forward folds
        md.append('**Walk-Forward Folds:**')
        md.append('')
        md.append('| Fold | Trades | P&L | Positive |')
        md.append('|------|--------|-----|----------|')
        for fd in r.get('wf_fold_details', []):
            pos_str = 'YES' if fd['positive'] else 'NO'
            md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.2f} | {pos_str} |')
        md.append('')

        # Stress metrics
        sm = r['stress_metrics']
        md.append(f'**Stress 2x**: trades={sm["trades"]}, PF={sm["pf"]:.3f}, '
                  f'exp/wk=${sm["exp_per_week"]:.2f}, DD={sm["max_dd_pct"]:.1f}%')
        md.append('')

        # Coin concentration
        md.append(f'**Coin concentration**: top1={r["concentration"]["top1_pct"]:.1f}% '
                  f'({r["concentration"]["top1_coin"]}), '
                  f'top3={r["concentration"]["top3_pct"]:.1f}%')
        md.append('')

        # Tier split
        ts = r['tier_split']
        md.append(f'**Tier split**: T1={ts["tier1"]["trades"]} trades (${ts["tier1"]["pnl"]:.0f}), '
                  f'T2={ts["tier2"]["trades"]} trades (${ts["tier2"]["pnl"]:.0f})')
        md.append('')

        # Exit reasons
        md.append('**Exit reasons:**')
        md.append('')
        md.append('| Reason | Count | P&L | WR% |')
        md.append('|--------|-------|-----|-----|')
        for reason, stats in r['exit_reasons'].items():
            md.append(f'| {reason} | {stats["count"]} | ${stats["pnl"]:.0f} | {stats["wr"]:.1f}% |')
        md.append('')

    # Impact analysis
    md.append('## 3. Multi-Position Impact Analysis')
    md.append('')
    trade_diff = m2['trades'] - m1['trades']
    trade_diff_pct = head_to_head['trade_increase_pct']
    pnl_diff = m2['pnl'] - m1['pnl']
    dd_diff = m2['max_dd_pct'] - m1['max_dd_pct']
    exp_diff = m2['exp_per_week'] - m1['exp_per_week']
    md.append(f'- **Trade count change**: {m1["trades"]} -> {m2["trades"]} '
              f'({trade_diff:+d}, {trade_diff_pct:+.1f}%)')
    md.append(f'- **P&L change**: ${m1["pnl"]:.0f} -> ${m2["pnl"]:.0f} '
              f'(${pnl_diff:+.0f})')
    md.append(f'- **Exp/wk change**: ${m1["exp_per_week"]:.2f} -> ${m2["exp_per_week"]:.2f} '
              f'(${exp_diff:+.2f})')
    md.append(f'- **DD change**: {m1["max_dd_pct"]:.1f}% -> {m2["max_dd_pct"]:.1f}% '
              f'({dd_diff:+.1f}pp)')
    md.append(f'- **Fold conc change**: {fc1:.1f}% -> {fc2:.1f}% '
              f'({fc2 - fc1:+.1f}pp)')
    md.append(f'- **Gate pass change**: {g1["pass_count"]}/7 -> {g2["pass_count"]}/7')
    md.append('')

    # Why max_pos=2 differs
    md.append('### Mechanism')
    md.append('')
    md.append('With max_pos=2:')
    md.append('- Capital is split across 2 slots when both are filled')
    md.append('- More signals can be acted on (no blocking by existing position)')
    md.append('- Individual position sizes are smaller (half capital per trade)')
    md.append('- Diversification benefit: two coins can offset each other')
    md.append('- Risk: if both positions lose simultaneously, DD may be worse')
    md.append('')

    # Conclusions
    md.append('## 4. Conclusions')
    md.append('')
    if g1['all_pass'] and g2['all_pass']:
        md.append('**Both max_pos=1 and max_pos=2 pass ALL 7 gates.**')
    elif g1['all_pass'] and not g2['all_pass']:
        mp2_fails = [gid for gid, g in g2['gates'].items() if not g['pass']]
        md.append(f'**max_pos=1 passes all 7 gates. max_pos=2 FAILS: {", ".join(mp2_fails)}.**')
    elif not g1['all_pass'] and g2['all_pass']:
        mp1_fails = [gid for gid, g in g1['gates'].items() if not g['pass']]
        md.append(f'**max_pos=2 passes all 7 gates. max_pos=1 FAILS: {", ".join(mp1_fails)}.**')
    else:
        mp1_fails = [gid for gid, g in g1['gates'].items() if not g['pass']]
        mp2_fails = [gid for gid, g in g2['gates'].items() if not g['pass']]
        md.append(f'**max_pos=1 fails: {", ".join(mp1_fails)}. '
                  f'max_pos=2 fails: {", ".join(mp2_fails)}.**')
    md.append('')

    # Recommendation
    if g2['all_pass'] and m2['exp_per_week'] > m1['exp_per_week']:
        recommendation = (
            'max_pos=2 passes all gates AND has higher exp/week. '
            'RECOMMEND: Adopt max_pos=2 for production.'
        )
    elif g2['all_pass'] and m2['exp_per_week'] <= m1['exp_per_week']:
        recommendation = (
            'max_pos=2 passes all gates but has lower exp/week than max_pos=1. '
            'max_pos=2 trades more with smaller positions; net edge is reduced. '
            'RECOMMEND: Keep max_pos=1 unless trade count diversity is valued.'
        )
    elif not g2['all_pass']:
        mp2_fails = [gid for gid, g in g2['gates'].items() if not g['pass']]
        recommendation = (
            f'max_pos=2 FAILS gates {", ".join(mp2_fails)}. '
            'RECOMMEND: Keep max_pos=1.'
        )
    else:
        recommendation = 'Inconclusive. Further analysis needed.'

    md.append(f'**Recommendation**: {recommendation}')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_multipos_295.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_multipos_295_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: Multi-Position Test')
    print(f'  max_pos=1: {g1["score"]} gates | P&L=${m1["pnl"]:.0f} | '
          f'exp/w=${m1["exp_per_week"]:.2f} | DD={m1["max_dd_pct"]:.1f}%')
    print(f'  max_pos=2: {g2["score"]} gates | P&L=${m2["pnl"]:.0f} | '
          f'exp/w=${m2["exp_per_week"]:.2f} | DD={m2["max_dd_pct"]:.1f}%')
    print(f'  Trade increase: {trade_diff_pct:+.1f}%')
    print(f'  Winner by gates: {head_to_head["winner_by_gates"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
