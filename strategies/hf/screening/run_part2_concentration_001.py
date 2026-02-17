#!/usr/bin/env python3
"""
Part 2 -- Agent C7-D: Concentration Control (P0-2)
===================================================
G8 fold concentration = 48.6% on 316 coins (FAIL, threshold < 35%).
Even 295-coin variants hover near 34.2%.

This script diagnoses which coins/folds cause concentration, then tests
5 control mechanisms:
  1. Diagnosis: per-coin, per-fold, per-coin-per-fold P&L breakdown
  2. Cap per coin: max_trades_per_coin = 1, 2, 3
  3. Cap per coin P&L share: max_pnl_share = 10%, 15%, 20%, 25%
  4. max_pos tuning: max_pos = 1, 2, 3, 5
  5. Signal strength filter: strength_min = 0, 0.5, 1.0, 1.5, 2.0

For EACH variant, evaluates STRICT gates:
  G1: trades/week >= 10
  G2: max gap <= 2.5d
  G3: exp/week > $0
  G4: exp/week > $0 (stress 2x)
  G5: DD <= 20%
  G6: WF >= 4/5
  G8: fold_conc < 35%

Output:
  reports/hf/part2_concentration_001.json
  reports/hf/part2_concentration_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_concentration_001.py
    python strategies/hf/screening/run_part2_concentration_001.py --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

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

EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

REPORT_JSON = 'part2_concentration_001.json'
REPORT_MD = 'part2_concentration_001.md'


# ============================================================
# Data Loading (same pattern as other run_part2 scripts)
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
    for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
        if tier_num in tb:
            coins = tb[tier_num].get('coins', [])
            tier_coins[tier_key] = [c for c in coins if c in available_coins]
    return tier_coins


# ============================================================
# Backtest Runners (per-tier, merged)
# ============================================================

def run_combined_backtest(data, tier_coins, tier_indicators, market_ctx,
                          tier1_fee, tier2_fee, params, max_pos=1,
                          signal_fn=None):
    """Run combined T1+T2 backtest, merging trade lists."""
    if signal_fn is None:
        signal_fn = signal_h20_vwap_deviation
    signal_params = {**params, '__market__': market_ctx}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    all_trades = []
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_fn,
            params=signal_params, indicators=indicators, fee=fee,
            max_pos=max_pos,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_combined_walk_forward(data, tier_coins, tier_indicators, market_ctx,
                               tier1_fee, tier2_fee, params, n_folds=5,
                               max_pos=1, signal_fn=None):
    """Run combined T1+T2 walk-forward, merging fold trades."""
    if signal_fn is None:
        signal_fn = signal_h20_vwap_deviation
    signal_params = {**params, '__market__': market_ctx}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    tier_fold_trades = {}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_fn,
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


# ============================================================
# Metrics Computation
# ============================================================

def compute_metrics(trades, total_bars):
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
                'trades_per_week': 0.0, 'exp_per_week': 0.0,
                'max_dd_pct': 0.0, 'max_gap_days': 999.0, 'expectancy': 0.0}
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
        entry_bars = [t.get('entry_bar', 0) for t in sorted_trades]
        for i in range(1, len(entry_bars)):
            gap = entry_bars[i] - entry_bars[i - 1]
            if gap > max_gap_bars:
                max_gap_bars = gap
        # Also check gap from start and to end
        max_gap_bars = max(max_gap_bars, entry_bars[0])
        max_gap_bars = max(max_gap_bars, total_bars - entry_bars[-1])
    else:
        max_gap_bars = total_bars
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {
        'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
        'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
        'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4),
    }


def compute_fold_concentration(fold_trades):
    """Compute top-1 fold concentration as % of total positive fold P&L."""
    fold_pnls = {}
    for fold_idx, trades in fold_trades.items():
        fold_pnls[fold_idx] = sum(t['pnl'] for t in trades)
    positive_pnls = [max(0, p) for p in fold_pnls.values()]
    total_pos = sum(positive_pnls)
    if total_pos <= 0:
        return {'top1_fold_conc_pct': 100.0, 'fold_pnls': fold_pnls}
    max_fold_positive = max(positive_pnls)
    top1_conc = max_fold_positive / total_pos * 100
    return {
        'top1_fold_conc_pct': round(top1_conc, 1),
        'fold_pnls': {k: round(v, 2) for k, v in fold_pnls.items()},
    }


# ============================================================
# Gate Evaluation (STRICT thresholds from task spec)
# ============================================================

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, fold_conc_pct):
    """
    Evaluate STRICT gates:
      G1: trades/week >= 10
      G2: max gap <= 2.5d
      G3: exp/week > $0
      G4: exp/week > $0 (stress 2x)
      G5: DD <= 20%
      G6: WF >= 4/5
      G8: fold_conc < 35%
    """
    gates = {}
    gates['G1'] = {
        'name': 'Trades/week', 'value': metrics['trades_per_week'],
        'threshold': '>= 10', 'pass': metrics['trades_per_week'] >= 10,
    }
    gates['G2'] = {
        'name': 'Max gap (days)', 'value': metrics['max_gap_days'],
        'threshold': '<= 2.5', 'pass': metrics['max_gap_days'] <= 2.5,
    }
    gates['G3'] = {
        'name': 'Exp/week (market)', 'value': metrics['exp_per_week'],
        'threshold': '> $0', 'pass': metrics['exp_per_week'] > 0,
    }
    gates['G4'] = {
        'name': 'Exp/week (2x stress)', 'value': stress_metrics['exp_per_week'],
        'threshold': '> $0', 'pass': stress_metrics['exp_per_week'] > 0,
    }
    gates['G5'] = {
        'name': 'Max DD%', 'value': metrics['max_dd_pct'],
        'threshold': '<= 20%', 'pass': metrics['max_dd_pct'] <= 20,
    }
    gates['G6'] = {
        'name': 'WF folds positive', 'value': f'{wf_folds_positive}/5',
        'threshold': '>= 4/5', 'pass': wf_folds_positive >= 4,
    }
    gates['G8'] = {
        'name': 'Fold concentration', 'value': f'{fold_conc_pct:.1f}%',
        'threshold': '< 35%', 'pass': fold_conc_pct < 35,
    }
    n_pass = sum(1 for g in gates.values() if g['pass'])
    all_pass = n_pass == len(gates)
    failed = [gid for gid, g in gates.items() if not g['pass']]
    return gates, n_pass, len(gates), all_pass, failed


# ============================================================
# Diagnosis Helpers
# ============================================================

def diagnose_concentration(trades, fold_trades):
    """
    Detailed diagnosis of which coins/folds drive concentration.
    Returns per-coin P&L, per-fold P&L, per-coin-per-fold P&L.
    """
    # Per-coin P&L
    coin_pnl = defaultdict(float)
    coin_trades = defaultdict(int)
    for t in trades:
        coin = t.get('pair', 'unknown')
        coin_pnl[coin] += t['pnl']
        coin_trades[coin] += 1

    total_positive = sum(v for v in coin_pnl.values() if v > 0)

    top_coins = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)
    top5_coins = []
    for coin, pnl in top_coins[:5]:
        share = pnl / total_positive * 100 if total_positive > 0 and pnl > 0 else 0
        top5_coins.append({
            'coin': coin, 'pnl': round(pnl, 2), 'trades': coin_trades[coin],
            'pnl_share_pct': round(share, 1),
        })

    # Per-fold P&L
    fold_pnls = {}
    for fold_idx, ftrades in fold_trades.items():
        fold_pnls[fold_idx] = round(sum(t['pnl'] for t in ftrades), 2)

    positive_fold_pnls = [max(0, p) for p in fold_pnls.values()]
    total_fold_positive = sum(positive_fold_pnls)

    fold_details = []
    for fold_idx in sorted(fold_trades.keys()):
        fpnl = fold_pnls[fold_idx]
        share = max(0, fpnl) / total_fold_positive * 100 if total_fold_positive > 0 and fpnl > 0 else 0
        fold_details.append({
            'fold': fold_idx, 'pnl': fpnl, 'trades': len(fold_trades[fold_idx]),
            'pnl_share_pct': round(share, 1),
        })

    # Per-coin-per-fold P&L (for top contributing coins)
    coin_fold_pnl = defaultdict(lambda: defaultdict(float))
    for fold_idx, ftrades in fold_trades.items():
        for t in ftrades:
            coin = t.get('pair', 'unknown')
            coin_fold_pnl[coin][fold_idx] += t['pnl']

    # Top-3 coins per fold
    top3_per_fold = {}
    for fold_idx in sorted(fold_trades.keys()):
        fold_coin_pnl = {}
        for coin in coin_fold_pnl:
            if fold_idx in coin_fold_pnl[coin]:
                fold_coin_pnl[coin] = coin_fold_pnl[coin][fold_idx]
        sorted_coins = sorted(fold_coin_pnl.items(), key=lambda x: x[1], reverse=True)
        top3_per_fold[fold_idx] = [
            {'coin': c, 'pnl': round(p, 2)} for c, p in sorted_coins[:3]
        ]

    # Fold with highest concentration
    max_fold = max(fold_details, key=lambda x: x['pnl_share_pct'])

    return {
        'top5_coins': top5_coins,
        'total_positive_pnl': round(total_positive, 2),
        'coins_with_trades': len(coin_pnl),
        'fold_details': fold_details,
        'top3_per_fold': {str(k): v for k, v in top3_per_fold.items()},
        'highest_conc_fold': max_fold,
        'coin_fold_pnl': {
            coin: {str(fi): round(p, 2) for fi, p in fpnls.items()}
            for coin, fpnls in sorted(coin_fold_pnl.items(),
                                       key=lambda x: sum(x[1].values()), reverse=True)[:10]
        },
    }


# ============================================================
# Trade Filtering Helpers
# ============================================================

def cap_trades_per_coin(trades, max_per_coin):
    """Keep only the first N trades per coin (sorted by entry_bar)."""
    coin_count = Counter()
    filtered = []
    sorted_trades = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    for t in sorted_trades:
        coin = t['pair']
        if coin_count[coin] < max_per_coin:
            filtered.append(t)
            coin_count[coin] += 1
    return filtered


def cap_pnl_share(trades, max_share):
    """
    Diagnostic: for each coin, if its positive P&L share > max_share,
    cap its contribution by removing its worst-performing (latest) trades
    until it's under the cap. Returns adjusted trade list.
    """
    # Compute per-coin positive P&L
    coin_trades = defaultdict(list)
    for t in trades:
        coin_trades[t['pair']].append(t)

    total_positive = sum(max(0, t['pnl']) for t in trades)
    if total_positive <= 0:
        return trades

    # Check which coins exceed the share cap
    adjusted = []
    for coin, ctrades in coin_trades.items():
        coin_positive = sum(max(0, t['pnl']) for t in ctrades)
        coin_share = coin_positive / total_positive if total_positive > 0 else 0
        if coin_share > max_share:
            # Sort by P&L descending, keep removing highest-pnl trades until under cap
            sorted_ct = sorted(ctrades, key=lambda t: t['pnl'], reverse=True)
            kept = []
            running_positive = 0.0
            cap_amount = total_positive * max_share
            for t in sorted_ct:
                if t['pnl'] > 0 and running_positive + t['pnl'] > cap_amount:
                    continue  # skip this trade to stay under cap
                running_positive += max(0, t['pnl'])
                kept.append(t)
            adjusted.extend(kept)
        else:
            adjusted.extend(ctrades)
    return adjusted


def make_strength_filtered_signal(base_fn, min_strength):
    """Create a signal wrapper that filters trades below strength threshold."""
    def filtered(candles, bar, indicators, params):
        result = base_fn(candles, bar, indicators, params)
        if result is None:
            return None
        if result.get('strength', 0) < min_strength:
            return None
        return result
    return filtered


# ============================================================
# Full Evaluation for a Variant
# ============================================================

def evaluate_variant(label, trades, fold_trades, total_bars,
                     stress_trades=None, stress_total_bars=None):
    """Compute metrics and gates for a given trade list + fold trades."""
    metrics = compute_metrics(trades, total_bars)
    fold_conc = compute_fold_concentration(fold_trades)

    folds_positive = 0
    fold_details = []
    for fi in sorted(fold_trades.keys()):
        fpnl = sum(t['pnl'] for t in fold_trades[fi])
        fn = len(fold_trades[fi])
        is_pos = fpnl > 0
        if is_pos:
            folds_positive += 1
        fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': is_pos})

    # Stress metrics
    if stress_trades is not None:
        s_bars = stress_total_bars if stress_total_bars else total_bars
        stress_metrics = compute_metrics(stress_trades, s_bars)
    else:
        stress_metrics = {'exp_per_week': 0.0}

    fold_conc_pct = fold_conc['top1_fold_conc_pct']
    gates, n_pass, n_total, all_pass, failed = evaluate_gates(
        metrics, stress_metrics, folds_positive, fold_conc_pct,
    )

    # Coin concentration
    coin_pnl = defaultdict(float)
    for t in trades:
        coin_pnl[t.get('pair', 'unknown')] += t['pnl']
    positive_coins = {c: p for c, p in coin_pnl.items() if p > 0}
    total_positive = sum(positive_coins.values())
    sorted_pos = sorted(positive_coins.items(), key=lambda x: x[1], reverse=True)
    top1_coin_pct = sorted_pos[0][1] / total_positive * 100 if sorted_pos and total_positive > 0 else 0
    top3_coin_pct = sum(v for _, v in sorted_pos[:3]) / total_positive * 100 if total_positive > 0 else 0

    return {
        'label': label,
        'metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics.get('trades', 0),
            'pnl': stress_metrics.get('pnl', 0.0),
            'pf': stress_metrics.get('pf', 0.0),
            'exp_per_week': stress_metrics.get('exp_per_week', 0.0),
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'top1_coin_pct': round(top1_coin_pct, 1),
        'top3_coin_pct': round(top3_coin_pct, 1),
        'coins_with_trades': len(coin_pnl),
        'gates': gates,
        'n_gates_pass': n_pass,
        'n_gates_total': n_total,
        'all_gates_pass': all_pass,
        'failed_gates': failed,
    }


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2 -- Agent C7-D: Concentration Control (P0-2)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- Agent C7-D: Concentration Control (P0-2)')
    print('  G8 fold_conc FAIL -- diagnosing and testing controls')
    print('  STRICT gates: G1>=10/wk, G2<=2.5d, G5<=20%, G6>=4/5, G8<35%')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

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

    # --- Apply 21-coin exclusion -> 295-coin universe ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (after exclusion)')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins after exclusion.')
        sys.exit(1)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  Tests:')
        print(f'    1. Diagnosis (baseline)')
        print(f'    2. Cap per coin: max_trades_per_coin = 1, 2, 3')
        print(f'    3. Cap P&L share: 10%, 15%, 20%, 25%')
        print(f'    4. max_pos: 1, 2, 3, 5')
        print(f'    5. Strength filter: 0, 0.5, 1.0, 1.5, 2.0')
        sys.exit(0)

    # --- Precompute indicators (shared across all tests) ---
    print('[Indicators] Precomputing base indicators for 295-coin universe...')
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

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    all_results = {}

    # ==================================================================
    # SECTION 1: BASELINE + DIAGNOSIS
    # ==================================================================
    print('\n' + '=' * 70)
    print('  SECTION 1: Baseline + Diagnosis')
    print('=' * 70)

    t_sec = time.time()

    # Baseline backtest
    print('  [1a] Baseline backtest...')
    baseline_trades = run_combined_backtest(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, PARAMS_V5, max_pos=1,
    )
    print(f'    -> {len(baseline_trades)} trades')

    # Baseline walk-forward
    print('  [1b] Baseline walk-forward 5-fold...')
    baseline_fold_trades = run_combined_walk_forward(
        data, tier_coins, tier_indicators, market_context,
        tier1_fee, tier2_fee, PARAMS_V5, n_folds=5, max_pos=1,
    )

    # Baseline stress
    print('  [1c] Baseline stress 2x...')
    baseline_stress = run_combined_backtest(
        data, tier_coins, tier_indicators, market_context,
        stress_t1_fee, stress_t2_fee, PARAMS_V5, max_pos=1,
    )

    baseline_result = evaluate_variant(
        'Baseline (295, mp1)', baseline_trades, baseline_fold_trades,
        total_bars, stress_trades=baseline_stress,
    )
    all_results['baseline'] = baseline_result

    # Diagnosis
    print('  [1d] Running concentration diagnosis...')
    diagnosis = diagnose_concentration(baseline_trades, baseline_fold_trades)

    print(f'\n  --- DIAGNOSIS ---')
    print(f'  Total positive P&L: ${diagnosis["total_positive_pnl"]:.2f}')
    print(f'  Coins with trades: {diagnosis["coins_with_trades"]}')
    print(f'\n  Top-5 coins by P&L:')
    for c in diagnosis['top5_coins']:
        print(f'    {c["coin"]}: ${c["pnl"]:.2f} ({c["pnl_share_pct"]:.1f}%) | {c["trades"]} trades')
    print(f'\n  Fold details:')
    for fd in diagnosis['fold_details']:
        print(f'    Fold {fd["fold"]}: ${fd["pnl"]:.2f} ({fd["pnl_share_pct"]:.1f}% share) | {fd["trades"]} trades')
    print(f'\n  Highest concentration fold: Fold {diagnosis["highest_conc_fold"]["fold"]} '
          f'({diagnosis["highest_conc_fold"]["pnl_share_pct"]:.1f}%)')
    print(f'\n  Top-3 coins per fold:')
    for fi in sorted(diagnosis['top3_per_fold'].keys()):
        coins_str = ', '.join(f'{c["coin"]}=${c["pnl"]:.1f}' for c in diagnosis['top3_per_fold'][fi])
        print(f'    Fold {fi}: {coins_str}')

    print(f'\n  Baseline gates: {baseline_result["n_gates_pass"]}/{baseline_result["n_gates_total"]}')
    for gid, g in baseline_result['gates'].items():
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'    {gid}: {g["name"]} = {g["value"]} ({g["threshold"]}) -> {status}')
    print(f'  Section 1 time: {time.time()-t_sec:.1f}s')

    # ==================================================================
    # SECTION 2: CAP PER COIN (max trades per coin)
    # ==================================================================
    print('\n' + '=' * 70)
    print('  SECTION 2: Cap per coin (max_trades_per_coin)')
    print('=' * 70)

    cap_coin_results = {}
    for max_tpc in [1, 2, 3]:
        t_v = time.time()
        label = f'cap_coin_{max_tpc}'
        print(f'\n  [{label}] Filtering to max {max_tpc} trades per coin...')

        # Filter baseline trades
        filtered_trades = cap_trades_per_coin(baseline_trades, max_tpc)
        print(f'    -> {len(filtered_trades)} trades (from {len(baseline_trades)})')

        # Filter fold trades too
        filtered_fold_trades = {}
        for fi, ftrades in baseline_fold_trades.items():
            filtered_fold_trades[fi] = cap_trades_per_coin(ftrades, max_tpc)

        # Filter stress trades
        filtered_stress = cap_trades_per_coin(baseline_stress, max_tpc)

        result = evaluate_variant(
            f'Cap {max_tpc}/coin', filtered_trades, filtered_fold_trades,
            total_bars, stress_trades=filtered_stress,
        )
        cap_coin_results[max_tpc] = result
        all_results[label] = result

        print(f'    trades={result["metrics"]["trades"]} PF={result["metrics"]["pf"]:.3f} '
              f'exp/w=${result["metrics"]["exp_per_week"]:.2f} DD={result["metrics"]["max_dd_pct"]:.1f}%')
        print(f'    WF={result["wf_folds_positive"]}/5  fold_conc={result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
        print(f'    Gates: {result["n_gates_pass"]}/{result["n_gates_total"]}  '
              f'failed={result["failed_gates"]}  ({time.time()-t_v:.1f}s)')

    # ==================================================================
    # SECTION 3: CAP P&L SHARE
    # ==================================================================
    print('\n' + '=' * 70)
    print('  SECTION 3: Cap per-coin P&L share (diagnostic)')
    print('=' * 70)

    pnl_cap_results = {}
    for max_share_pct in [10, 15, 20, 25]:
        t_v = time.time()
        max_share = max_share_pct / 100.0
        label = f'pnl_cap_{max_share_pct}pct'
        print(f'\n  [{label}] Capping coin P&L share at {max_share_pct}%...')

        filtered_trades = cap_pnl_share(baseline_trades, max_share)
        print(f'    -> {len(filtered_trades)} trades (from {len(baseline_trades)})')

        # Also filter fold trades
        filtered_fold_trades = {}
        for fi, ftrades in baseline_fold_trades.items():
            filtered_fold_trades[fi] = cap_pnl_share(ftrades, max_share)

        # Stress
        filtered_stress = cap_pnl_share(baseline_stress, max_share)

        result = evaluate_variant(
            f'PnL cap {max_share_pct}%', filtered_trades, filtered_fold_trades,
            total_bars, stress_trades=filtered_stress,
        )
        pnl_cap_results[max_share_pct] = result
        all_results[label] = result

        print(f'    trades={result["metrics"]["trades"]} PF={result["metrics"]["pf"]:.3f} '
              f'exp/w=${result["metrics"]["exp_per_week"]:.2f} DD={result["metrics"]["max_dd_pct"]:.1f}%')
        print(f'    WF={result["wf_folds_positive"]}/5  fold_conc={result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
        print(f'    top1_coin={result["top1_coin_pct"]:.1f}%  top3_coin={result["top3_coin_pct"]:.1f}%')
        print(f'    Gates: {result["n_gates_pass"]}/{result["n_gates_total"]}  '
              f'failed={result["failed_gates"]}  ({time.time()-t_v:.1f}s)')

    # ==================================================================
    # SECTION 4: MAX_POS TUNING
    # ==================================================================
    print('\n' + '=' * 70)
    print('  SECTION 4: max_pos tuning')
    print('=' * 70)

    maxpos_results = {}
    for mp in [1, 2, 3, 5]:
        t_v = time.time()
        label = f'maxpos_{mp}'
        print(f'\n  [{label}] Running backtest with max_pos={mp}...')

        trades = run_combined_backtest(
            data, tier_coins, tier_indicators, market_context,
            tier1_fee, tier2_fee, PARAMS_V5, max_pos=mp,
        )
        fold_trades_mp = run_combined_walk_forward(
            data, tier_coins, tier_indicators, market_context,
            tier1_fee, tier2_fee, PARAMS_V5, n_folds=5, max_pos=mp,
        )
        stress_trades_mp = run_combined_backtest(
            data, tier_coins, tier_indicators, market_context,
            stress_t1_fee, stress_t2_fee, PARAMS_V5, max_pos=mp,
        )

        result = evaluate_variant(
            f'max_pos={mp}', trades, fold_trades_mp,
            total_bars, stress_trades=stress_trades_mp,
        )
        maxpos_results[mp] = result
        all_results[label] = result

        print(f'    trades={result["metrics"]["trades"]} PF={result["metrics"]["pf"]:.3f} '
              f'exp/w=${result["metrics"]["exp_per_week"]:.2f} DD={result["metrics"]["max_dd_pct"]:.1f}%')
        print(f'    WF={result["wf_folds_positive"]}/5  fold_conc={result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
        print(f'    Gates: {result["n_gates_pass"]}/{result["n_gates_total"]}  '
              f'failed={result["failed_gates"]}  ({time.time()-t_v:.1f}s)')

    # ==================================================================
    # SECTION 5: SIGNAL STRENGTH FILTER
    # ==================================================================
    print('\n' + '=' * 70)
    print('  SECTION 5: Signal strength filter')
    print('=' * 70)

    strength_results = {}
    for smin in [0, 0.5, 1.0, 1.5, 2.0]:
        t_v = time.time()
        label = f'strength_{smin}'
        print(f'\n  [{label}] Running backtest with strength_min={smin}...')

        if smin == 0:
            sig_fn = signal_h20_vwap_deviation
        else:
            sig_fn = make_strength_filtered_signal(signal_h20_vwap_deviation, smin)

        trades = run_combined_backtest(
            data, tier_coins, tier_indicators, market_context,
            tier1_fee, tier2_fee, PARAMS_V5, max_pos=1, signal_fn=sig_fn,
        )
        fold_trades_s = run_combined_walk_forward(
            data, tier_coins, tier_indicators, market_context,
            tier1_fee, tier2_fee, PARAMS_V5, n_folds=5, max_pos=1, signal_fn=sig_fn,
        )
        stress_trades_s = run_combined_backtest(
            data, tier_coins, tier_indicators, market_context,
            stress_t1_fee, stress_t2_fee, PARAMS_V5, max_pos=1, signal_fn=sig_fn,
        )

        result = evaluate_variant(
            f'strength>={smin}', trades, fold_trades_s,
            total_bars, stress_trades=stress_trades_s,
        )
        strength_results[smin] = result
        all_results[label] = result

        print(f'    trades={result["metrics"]["trades"]} PF={result["metrics"]["pf"]:.3f} '
              f'exp/w=${result["metrics"]["exp_per_week"]:.2f} DD={result["metrics"]["max_dd_pct"]:.1f}%')
        print(f'    WF={result["wf_folds_positive"]}/5  fold_conc={result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
        print(f'    Gates: {result["n_gates_pass"]}/{result["n_gates_total"]}  '
              f'failed={result["failed_gates"]}  ({time.time()-t_v:.1f}s)')

    elapsed_total = time.time() - t0_total

    # ==================================================================
    # VERDICTS
    # ==================================================================
    print('\n' + '=' * 70)
    print('  VERDICTS')
    print('=' * 70)

    # Find variants that help G8 without breaking others
    g8_helpers = []
    for key, result in all_results.items():
        fc = result['fold_concentration']['top1_fold_conc_pct']
        if fc < 35:
            g8_helpers.append({
                'key': key, 'label': result['label'],
                'fold_conc': fc,
                'all_pass': result['all_gates_pass'],
                'n_pass': result['n_gates_pass'],
                'failed': result['failed_gates'],
                'trades': result['metrics']['trades'],
                'pf': result['metrics']['pf'],
                'exp_per_week': result['metrics']['exp_per_week'],
            })

    print(f'\n  Variants passing G8 (fold_conc < 35%): {len(g8_helpers)}')
    for h in sorted(g8_helpers, key=lambda x: x['n_pass'], reverse=True):
        tag = 'ALL PASS' if h['all_pass'] else f'FAIL: {",".join(h["failed"])}'
        print(f'    {h["label"]}: conc={h["fold_conc"]:.1f}%, gates={h["n_pass"]}/7, '
              f'trades={h["trades"]}, PF={h["pf"]:.3f}, exp/w=${h["exp_per_week"]:.2f} [{tag}]')

    # Find the best overall variant (most gates passed, then lowest fold_conc)
    best = sorted(all_results.values(),
                  key=lambda x: (x['n_gates_pass'], -x['fold_concentration']['top1_fold_conc_pct']),
                  reverse=True)
    print(f'\n  Best variant overall: {best[0]["label"]}')
    print(f'    Gates: {best[0]["n_gates_pass"]}/{best[0]["n_gates_total"]}')
    print(f'    Fold conc: {best[0]["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')

    # ==================================================================
    # JSON REPORT
    # ==================================================================

    report = {
        'run_header': {
            'task': 'part2_concentration_001',
            'agent': 'C7-D',
            'status': 'DONE',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1),
                         'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_t1_fee * 10000, 1),
                                'tier2': round(stress_t2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
            'strict_gates': {
                'G1': 'trades/week >= 10',
                'G2': 'max gap <= 2.5d',
                'G3': 'exp/week > $0',
                'G4': 'exp/week > $0 (stress 2x)',
                'G5': 'DD <= 20%',
                'G6': 'WF >= 4/5',
                'G8': 'fold_conc < 35%',
            },
        },
        'diagnosis': diagnosis,
        'baseline': baseline_result,
        'cap_per_coin': {str(k): v for k, v in cap_coin_results.items()},
        'pnl_cap': {str(k): v for k, v in pnl_cap_results.items()},
        'max_pos': {str(k): v for k, v in maxpos_results.items()},
        'strength_filter': {str(k): v for k, v in strength_results.items()},
        'g8_helpers': g8_helpers,
        'best_variant': best[0]['label'] if best else None,
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / REPORT_JSON
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ==================================================================
    # MARKDOWN REPORT
    # ==================================================================

    md = []
    md.append('# Part 2 -- Concentration Control (Agent C7-D, P0-2)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins (excl 21 net-negative)')
    md.append(f'**Params**: v5 (dev={PARAMS_V5["dev_thresh"]}, tp={PARAMS_V5["tp_pct"]}, '
              f'sl={PARAMS_V5["sl_pct"]}, tl={PARAMS_V5["time_limit"]})')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    md.append(f'**Stress**: 2x (T1={stress_t1_fee*10000:.1f}bps, T2={stress_t2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')
    md.append('## STRICT Gate Thresholds')
    md.append('')
    md.append('| Gate | Threshold |')
    md.append('|------|-----------|')
    md.append('| G1 | trades/week >= 10 |')
    md.append('| G2 | max gap <= 2.5d |')
    md.append('| G3 | exp/week > $0 |')
    md.append('| G4 | exp/week > $0 (stress 2x) |')
    md.append('| G5 | DD <= 20% |')
    md.append('| G6 | WF >= 4/5 |')
    md.append('| G8 | fold_conc < 35% |')
    md.append('')

    # --- Section 1: Diagnosis ---
    md.append('## 1. Diagnosis: What Drives Concentration')
    md.append('')
    md.append(f'**Baseline**: {baseline_result["metrics"]["trades"]} trades, '
              f'PF={baseline_result["metrics"]["pf"]:.3f}, '
              f'exp/wk=${baseline_result["metrics"]["exp_per_week"]:.2f}')
    md.append(f'**Fold concentration**: {baseline_result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
    md.append(f'**Total positive P&L**: ${diagnosis["total_positive_pnl"]:.2f}')
    md.append(f'**Coins with trades**: {diagnosis["coins_with_trades"]}')
    md.append('')

    md.append('### Top-5 Coins by P&L')
    md.append('')
    md.append('| Rank | Coin | P&L | Share% | Trades |')
    md.append('|------|------|-----|--------|--------|')
    for i, c in enumerate(diagnosis['top5_coins']):
        md.append(f'| {i+1} | {c["coin"]} | ${c["pnl"]:.2f} | {c["pnl_share_pct"]:.1f}% | {c["trades"]} |')
    md.append('')

    md.append('### Per-Fold P&L Breakdown')
    md.append('')
    md.append('| Fold | P&L | Share% | Trades | Positive |')
    md.append('|------|-----|--------|--------|----------|')
    for fd in diagnosis['fold_details']:
        pos_str = 'YES' if fd['pnl'] > 0 else 'NO'
        md.append(f'| {fd["fold"]} | ${fd["pnl"]:.2f} | {fd["pnl_share_pct"]:.1f}% | {fd["trades"]} | {pos_str} |')
    md.append('')

    md.append(f'**Highest concentration fold**: Fold {diagnosis["highest_conc_fold"]["fold"]} '
              f'({diagnosis["highest_conc_fold"]["pnl_share_pct"]:.1f}% of positive P&L)')
    md.append('')

    md.append('### Top-3 Coins per Fold')
    md.append('')
    for fi in sorted(diagnosis['top3_per_fold'].keys()):
        coins_str = ', '.join(f'{c["coin"]} (${c["pnl"]:.1f})' for c in diagnosis['top3_per_fold'][fi])
        md.append(f'- **Fold {fi}**: {coins_str}')
    md.append('')

    # --- Section 2: Baseline Gate Table ---
    md.append('### Baseline Gate Evaluation')
    md.append('')
    md.append('| Gate | Metric | Value | Threshold | Verdict |')
    md.append('|------|--------|-------|-----------|---------|')
    for gid, g in baseline_result['gates'].items():
        status = 'PASS' if g['pass'] else '**FAIL**'
        md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
    md.append('')

    # --- Section 3: Summary Comparison Table ---
    md.append('## 2. Summary Comparison: All Controls')
    md.append('')
    md.append('| Variant | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Top1 Coin% | Gates | Verdict |')
    md.append('|---------|--------|----|--------|-----|----|-----------|-----------:|-------|---------|')

    # Collect all result entries in display order
    display_order = []
    display_order.append(('Baseline', baseline_result))
    for k in [1, 2, 3]:
        display_order.append((f'Cap {k}/coin', cap_coin_results[k]))
    for k in [10, 15, 20, 25]:
        display_order.append((f'PnL cap {k}%', pnl_cap_results[k]))
    for k in [1, 2, 3, 5]:
        display_order.append((f'max_pos={k}', maxpos_results[k]))
    for k in [0, 0.5, 1.0, 1.5, 2.0]:
        display_order.append((f'str>={k}', strength_results[k]))

    for dlabel, r in display_order:
        m = r['metrics']
        fc = r['fold_concentration']['top1_fold_conc_pct']
        verdict = 'ALL PASS' if r['all_gates_pass'] else f'FAIL: {",".join(r["failed_gates"])}'
        md.append(f'| {dlabel} | {m["trades"]} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} | '
                  f'{m["max_dd_pct"]:.1f} | {r["wf_folds_positive"]}/5 | {fc:.1f}% | '
                  f'{r["top1_coin_pct"]:.1f}% | {r["n_gates_pass"]}/7 | {verdict} |')
    md.append('')

    # --- Section 4: Per-control before/after ---
    md.append('## 3. Before/After: Cap per Coin')
    md.append('')
    md.append('| max_trades | Trades | PF | DD% | WF | Fold Conc | Top1% | Top3% | Gates |')
    md.append('|-----------|--------|----|-----|----|-----------:|------:|------:|-------|')
    base_m = baseline_result['metrics']
    base_fc = baseline_result['fold_concentration']['top1_fold_conc_pct']
    md.append(f'| baseline | {base_m["trades"]} | {base_m["pf"]:.3f} | {base_m["max_dd_pct"]:.1f} | '
              f'{baseline_result["wf_folds_positive"]}/5 | {base_fc:.1f}% | '
              f'{baseline_result["top1_coin_pct"]:.1f}% | {baseline_result["top3_coin_pct"]:.1f}% | '
              f'{baseline_result["n_gates_pass"]}/7 |')
    for k in [1, 2, 3]:
        r = cap_coin_results[k]
        m = r['metrics']
        fc = r['fold_concentration']['top1_fold_conc_pct']
        md.append(f'| {k} | {m["trades"]} | {m["pf"]:.3f} | {m["max_dd_pct"]:.1f} | '
                  f'{r["wf_folds_positive"]}/5 | {fc:.1f}% | '
                  f'{r["top1_coin_pct"]:.1f}% | {r["top3_coin_pct"]:.1f}% | '
                  f'{r["n_gates_pass"]}/7 |')
    md.append('')

    md.append('## 4. Before/After: P&L Share Cap')
    md.append('')
    md.append('| max_share | Trades | PF | DD% | WF | Fold Conc | Top1% | Top3% | Gates |')
    md.append('|----------|--------|----|-----|----|-----------:|------:|------:|-------|')
    md.append(f'| baseline | {base_m["trades"]} | {base_m["pf"]:.3f} | {base_m["max_dd_pct"]:.1f} | '
              f'{baseline_result["wf_folds_positive"]}/5 | {base_fc:.1f}% | '
              f'{baseline_result["top1_coin_pct"]:.1f}% | {baseline_result["top3_coin_pct"]:.1f}% | '
              f'{baseline_result["n_gates_pass"]}/7 |')
    for k in [10, 15, 20, 25]:
        r = pnl_cap_results[k]
        m = r['metrics']
        fc = r['fold_concentration']['top1_fold_conc_pct']
        md.append(f'| {k}% | {m["trades"]} | {m["pf"]:.3f} | {m["max_dd_pct"]:.1f} | '
                  f'{r["wf_folds_positive"]}/5 | {fc:.1f}% | '
                  f'{r["top1_coin_pct"]:.1f}% | {r["top3_coin_pct"]:.1f}% | '
                  f'{r["n_gates_pass"]}/7 |')
    md.append('')

    md.append('## 5. Before/After: max_pos Tuning')
    md.append('')
    md.append('| max_pos | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Gates |')
    md.append('|---------|--------|----|--------|-----|----|-----------:|-------|')
    for k in [1, 2, 3, 5]:
        r = maxpos_results[k]
        m = r['metrics']
        fc = r['fold_concentration']['top1_fold_conc_pct']
        md.append(f'| {k} | {m["trades"]} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} | '
                  f'{m["max_dd_pct"]:.1f} | {r["wf_folds_positive"]}/5 | {fc:.1f}% | '
                  f'{r["n_gates_pass"]}/7 |')
    md.append('')

    md.append('## 6. Before/After: Signal Strength Filter')
    md.append('')
    md.append('| strength_min | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Gates |')
    md.append('|-------------|--------|----|--------|-----|----|-----------:|-------|')
    for k in [0, 0.5, 1.0, 1.5, 2.0]:
        r = strength_results[k]
        m = r['metrics']
        fc = r['fold_concentration']['top1_fold_conc_pct']
        md.append(f'| {k} | {m["trades"]} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} | '
                  f'{m["max_dd_pct"]:.1f} | {r["wf_folds_positive"]}/5 | {fc:.1f}% | '
                  f'{r["n_gates_pass"]}/7 |')
    md.append('')

    # --- Section 7: Gate Table for Each Variant ---
    md.append('## 7. Per-Variant Gate Tables')
    md.append('')
    for dlabel, r in display_order:
        if dlabel == 'Baseline':
            continue  # already shown above
        md.append(f'### {dlabel}')
        md.append('')
        md.append('| Gate | Value | Threshold | Verdict |')
        md.append('|------|-------|-----------|---------|')
        for gid, g in r['gates'].items():
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')

    # --- Section 8: Verdict ---
    md.append('## 8. Verdict: Which Controls Help G8')
    md.append('')
    if g8_helpers:
        md.append(f'{len(g8_helpers)} variant(s) pass G8 (fold_conc < 35%):')
        md.append('')
        md.append('| Variant | Fold Conc | Gates | Trades | PF | Exp/Wk | Failed |')
        md.append('|---------|-----------|-------|--------|----|--------|--------|')
        for h in sorted(g8_helpers, key=lambda x: (-x['n_pass'], x['fold_conc'])):
            failed_str = ', '.join(h['failed']) if h['failed'] else 'NONE'
            md.append(f'| {h["label"]} | {h["fold_conc"]:.1f}% | {h["n_pass"]}/7 | '
                      f'{h["trades"]} | {h["pf"]:.3f} | ${h["exp_per_week"]:.2f} | {failed_str} |')
        md.append('')
    else:
        md.append('**No variant passes G8 (fold_conc < 35%).** ')
        md.append('The fold concentration problem is structural and not easily fixed by these controls.')
        md.append('')

    # Overall assessment
    all_pass_variants = [h for h in g8_helpers if h['all_pass']]
    if all_pass_variants:
        best_v = all_pass_variants[0]
        md.append(f'**BEST VARIANT**: {best_v["label"]} -- passes ALL 7 strict gates.')
        md.append(f'  Fold conc: {best_v["fold_conc"]:.1f}%, trades: {best_v["trades"]}, '
                  f'PF: {best_v["pf"]:.3f}, exp/wk: ${best_v["exp_per_week"]:.2f}')
    else:
        md.append('**No variant passes all 7 strict gates simultaneously.** ')
        md.append('Concentration control alone is insufficient to pass the strict gate set.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_concentration_001.py at '
              f'{datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = out_dir / REPORT_MD
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # --- Final summary ---
    print(f'\n{"="*70}')
    print(f'  CONCENTRATION CONTROL COMPLETE')
    print(f'  Baseline fold_conc: {baseline_result["fold_concentration"]["top1_fold_conc_pct"]:.1f}%')
    print(f'  G8 helpers: {len(g8_helpers)} variants pass fold_conc < 35%')
    print(f'  All-pass variants: {len(all_pass_variants)}')
    if all_pass_variants:
        print(f'  Best: {all_pass_variants[0]["label"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"="*70}')


if __name__ == '__main__':
    main()
