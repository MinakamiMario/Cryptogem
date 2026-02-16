#!/usr/bin/env python3
"""
P0-5: Losers Cluster Diagnostics (Agent C7-E)
==============================================
Deep diagnostic of ALL 316-coin universe to identify losers, cluster them
by tier/volume/persistence, and test new exclusion candidates.

Analyses:
  1. Per-coin P&L attribution (all 316 coins) with volume and fees
  2. Loser analysis: count, total loss, T1/T2 breakdown, volume profiles
  3. Regime/Fold analysis: per-fold negative coins, persistent vs fold-specific
  4. Volume-based clustering: T2 quartile decomposition
  5. New exclusion candidates: persistent + low-volume losers

Output:
  reports/hf/part2_losers_cluster_001.json
  reports/hf/part2_losers_cluster_001.md

Usage:
    python strategies/hf/screening/run_part2_losers_cluster_001.py
    python strategies/hf/screening/run_part2_losers_cluster_001.py --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
import statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
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
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

BARS_PER_WEEK = 168
BARS_PER_DAY = 24

BASELINE_PARAMS = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

# Known excluded set from previous analysis
EXCLUDED_21 = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}


# ===================================================================
# DATA LOADING (same pattern as other Part 2 scripts)
# ===================================================================

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


# ===================================================================
# VOLUME ANALYSIS
# ===================================================================

def compute_coin_volumes(data, coins):
    """Compute median daily volume per coin from candle data."""
    volumes = {}
    for coin in coins:
        candles = data.get(coin, [])
        if candles:
            total_vol = sum(c.get('volume', 0) for c in candles)
            n_days = len(candles) / 24  # 1H candles
            volumes[coin] = total_vol / max(1, n_days)
    return volumes


def volume_quartiles(volumes, coins):
    """Split coins into volume quartiles Q1 (lowest) through Q4 (highest)."""
    coin_vols = [(c, volumes.get(c, 0)) for c in coins]
    coin_vols.sort(key=lambda x: x[1])
    n = len(coin_vols)
    if n == 0:
        return {'Q1': [], 'Q2': [], 'Q3': [], 'Q4': []}
    q_size = n // 4
    remainder = n % 4
    # Distribute remainder to last quartiles
    sizes = [q_size] * 4
    for i in range(remainder):
        sizes[3 - i] += 1
    quartiles = {}
    idx = 0
    for qi, label in enumerate(['Q1', 'Q2', 'Q3', 'Q4']):
        quartiles[label] = [c for c, v in coin_vols[idx:idx + sizes[qi]]]
        idx += sizes[qi]
    return quartiles


# ===================================================================
# BACKTEST HELPERS
# ===================================================================

def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None):
    """Run backtest returning all trades with tier/fee annotations."""
    if params is None:
        params = BASELINE_PARAMS
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
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    """Run walk-forward returning per-fold trade lists."""
    if params is None:
        params = BASELINE_PARAMS
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


def compute_metrics(trades, total_bars):
    """Compute standard metrics from trade list."""
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
            gap = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i - 1].get('entry_bar', 0)
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
            'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4)}


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


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ===================================================================
# PER-COIN ATTRIBUTION
# ===================================================================

def coin_pnl_attribution(trades, coin_volumes, t1_set, t2_set):
    """Build per-coin stats with volume, tier, fees."""
    coin_stats = defaultdict(lambda: {
        'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0,
        'total_fees': 0.0, 'pnl_list': [],
    })
    for t in trades:
        coin = t.get('pair', 'unknown')
        cs = coin_stats[coin]
        cs['pnl'] += t['pnl']
        cs['trades'] += 1
        cs['pnl_list'].append(t['pnl'])
        if t['pnl'] > 0:
            cs['wins'] += 1
        else:
            cs['losses'] += 1
        # Estimate fees from trade data
        fee_per_side = t.get('_fee_per_side', 0.00125)
        size = t.get('size', 2000)
        gross = t.get('pnl', 0) + size * fee_per_side + (size + t.get('pnl', 0)) * fee_per_side
        fees_est = size * fee_per_side * 2  # approximate round-trip
        cs['total_fees'] += fees_est

    # Compute derived stats
    result = []
    for coin, cs in coin_stats.items():
        tier = 'T1' if coin in t1_set else 'T2'
        avg_pnl = cs['pnl'] / cs['trades'] if cs['trades'] > 0 else 0
        wr = cs['wins'] / cs['trades'] * 100 if cs['trades'] > 0 else 0
        vol = coin_volumes.get(coin, 0)
        result.append({
            'coin': coin,
            'tier': tier,
            'pnl': round(cs['pnl'], 2),
            'trades': cs['trades'],
            'wins': cs['wins'],
            'losses': cs['losses'],
            'wr_pct': round(wr, 1),
            'avg_pnl_per_trade': round(avg_pnl, 2),
            'total_fees_est': round(cs['total_fees'], 2),
            'daily_volume_usd': round(vol, 0),
        })
    # Sort by P&L ascending (worst first)
    result.sort(key=lambda x: x['pnl'])
    return result


# ===================================================================
# PER-FOLD COIN ANALYSIS
# ===================================================================

def per_fold_coin_pnl(fold_trades):
    """For each fold, compute per-coin P&L. Returns {fold_idx: {coin: pnl}}."""
    fold_coin_pnl = {}
    for fold_idx, trades in fold_trades.items():
        coin_pnl = defaultdict(float)
        for t in trades:
            coin_pnl[t.get('pair', 'unknown')] += t['pnl']
        fold_coin_pnl[fold_idx] = dict(coin_pnl)
    return fold_coin_pnl


def identify_persistent_losers(fold_coin_pnl, n_folds=5, threshold=3):
    """Identify coins that are net-negative in >= threshold folds."""
    coin_negative_folds = defaultdict(int)
    coin_fold_pnls = defaultdict(dict)
    for fold_idx, coin_pnl in fold_coin_pnl.items():
        for coin, pnl in coin_pnl.items():
            coin_fold_pnls[coin][fold_idx] = round(pnl, 2)
            if pnl < 0:
                coin_negative_folds[coin] += 1

    persistent = {}  # coins negative in >= threshold folds
    fold_specific = {}  # coins negative in 1-2 folds only
    for coin, neg_count in coin_negative_folds.items():
        total_folds_traded = len(coin_fold_pnls[coin])
        entry = {
            'coin': coin,
            'negative_folds': neg_count,
            'total_folds_traded': total_folds_traded,
            'fold_pnls': coin_fold_pnls[coin],
        }
        if neg_count >= threshold:
            persistent[coin] = entry
        else:
            fold_specific[coin] = entry

    return persistent, fold_specific


# ===================================================================
# GATE EVALUATION (full pipeline)
# ===================================================================

def run_full_evaluation(label, data, tier_coins, all_indicators_cache,
                        market_context, tier1_fee, tier2_fee,
                        stress_tier1_fee, stress_tier2_fee, total_bars):
    t0 = time.time()
    print(f'\n  [{label}] Running baseline...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if tier_name in all_indicators_cache:
            tier_indicators[tier_name] = {
                c: all_indicators_cache[tier_name][c]
                for c in coins if c in all_indicators_cache[tier_name]
            }
    trades = run_variant(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee)
    metrics = compute_metrics(trades, total_bars)
    n_coins_with_trades = len(set(t.get('pair', '') for t in trades))
    print(f'    trades={metrics["trades"]} PF={metrics["pf"]:.3f} '
          f'exp/w=${metrics["exp_per_week"]:.2f} DD={metrics["max_dd_pct"]:.1f}%')

    print(f'  [{label}] Running stress (2x fees)...')
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    stress_metrics = compute_metrics(stress_trades, total_bars)
    print(f'    stress: trades={stress_metrics["trades"]} exp/w=${stress_metrics["exp_per_week"]:.2f}')

    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
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
        'n_coins': sum(len(c) for c in tier_coins.values()),
        'n_t1': len(tier_coins.get('tier1', [])),
        'n_t2': len(tier_coins.get('tier2', [])),
        'n_coins_with_trades': n_coins_with_trades,
        'metrics': metrics,
        'stress_metrics': {'trades': stress_metrics['trades'], 'pnl': stress_metrics['pnl'],
                           'pf': stress_metrics['pf'], 'exp_per_week': stress_metrics['exp_per_week']},
        'wf_folds_positive': folds_positive, 'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'gate_evaluation': gate_eval, 'runtime_s': round(elapsed, 1),
    }


# ===================================================================
# MAIN
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description='P0-5: Losers Cluster Diagnostics')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  P0-5: Losers Cluster Diagnostics (Agent C7-E)')
    print('  Full 316-coin universe -- deep loser analysis')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps')

    # --- Commit ---
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
    n_t1 = len(tier_coins_full['tier1'])
    n_t2 = len(tier_coins_full['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins, total: {n_t1+n_t2}')

    if not tier_coins_full['tier1'] and not tier_coins_full['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}')
        print(f'  Params: {BASELINE_PARAMS}')
        print(f'  Will run: per-coin attribution, WF 5-fold per-coin, volume quartiles, exclusion test')
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators_full = {}
    for tier_name, coins in tier_coins_full.items():
        if coins:
            t_ind = time.time()
            tier_indicators_full[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins_full.items():
        if coins and tier_name in tier_indicators_full:
            extend_indicators(data, coins, tier_indicators_full[tier_name])
            cov = get_feature_coverage(tier_indicators_full[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins_full.get('tier1', []) + tier_coins_full.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    for tier_name, ind_dict in tier_indicators_full.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators_full, tier_coins_full)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    t1_set = set(tier_coins_full['tier1'])
    t2_set = set(tier_coins_full['tier2'])

    # --- Compute daily volumes ---
    print('[Volume] Computing daily volumes per coin...')
    all_universe_coins = tier_coins_full['tier1'] + tier_coins_full['tier2']
    coin_volumes = compute_coin_volumes(data, all_universe_coins)
    print(f'  {len(coin_volumes)} coins with volume data')

    # ============================================================
    # STEP 1: Full baseline + per-coin P&L attribution
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 1: Full baseline + per-coin P&L attribution (316 coins)')
    print('=' * 70)
    baseline_trades = run_variant(data, tier_coins_full, tier_indicators_full,
                                  market_context, tier1_fee, tier2_fee)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'  Baseline: {baseline_metrics["trades"]} trades, PF={baseline_metrics["pf"]:.3f}, '
          f'P&L=${baseline_metrics["pnl"]:.0f}, exp/w=${baseline_metrics["exp_per_week"]:.2f}')

    attribution = coin_pnl_attribution(baseline_trades, coin_volumes, t1_set, t2_set)
    n_trading = len(attribution)
    n_negative = sum(1 for a in attribution if a['pnl'] < 0)
    n_positive = sum(1 for a in attribution if a['pnl'] > 0)
    n_zero = sum(1 for a in attribution if a['pnl'] == 0)

    # Coins with NO trades at all
    coins_no_trades = set(all_universe_coins) - set(a['coin'] for a in attribution)

    print(f'\n  Coins with trades: {n_trading} / {n_t1+n_t2}')
    print(f'  Coins with NO trades: {len(coins_no_trades)}')
    print(f'  Net-negative: {n_negative}, Net-positive: {n_positive}, Breakeven: {n_zero}')

    print(f'\n  --- Top-10 WORST coins ---')
    for i, a in enumerate(attribution[:10]):
        print(f'    {i+1:2d}. {a["coin"]:16s} [{a["tier"]}]  P&L=${a["pnl"]:+8.2f}  '
              f'trades={a["trades"]}  WR={a["wr_pct"]:.0f}%  '
              f'avg/trade=${a["avg_pnl_per_trade"]:+.2f}  vol=${a["daily_volume_usd"]:.0f}/d')

    print(f'\n  --- Top-10 BEST coins ---')
    for i, a in enumerate(reversed(attribution[-10:])):
        print(f'    {i+1:2d}. {a["coin"]:16s} [{a["tier"]}]  P&L=${a["pnl"]:+8.2f}  '
              f'trades={a["trades"]}  WR={a["wr_pct"]:.0f}%  '
              f'avg/trade=${a["avg_pnl_per_trade"]:+.2f}  vol=${a["daily_volume_usd"]:.0f}/d')

    # ============================================================
    # STEP 2: Loser Analysis
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 2: Loser Analysis')
    print('=' * 70)

    losers = [a for a in attribution if a['pnl'] < 0]
    winners = [a for a in attribution if a['pnl'] > 0]
    total_loser_pnl = sum(a['pnl'] for a in losers)
    total_winner_pnl = sum(a['pnl'] for a in winners)

    loser_t1 = [a for a in losers if a['tier'] == 'T1']
    loser_t2 = [a for a in losers if a['tier'] == 'T2']
    winner_t1 = [a for a in winners if a['tier'] == 'T1']
    winner_t2 = [a for a in winners if a['tier'] == 'T2']

    print(f'  Total losers: {len(losers)} coins, total loss: ${total_loser_pnl:+.2f}')
    print(f'  Total winners: {len(winners)} coins, total gain: ${total_winner_pnl:+.2f}')
    print(f'  Net P&L: ${total_loser_pnl + total_winner_pnl:+.2f}')
    print(f'\n  Loser breakdown by tier:')
    print(f'    T1 losers: {len(loser_t1)} coins, loss: ${sum(a["pnl"] for a in loser_t1):+.2f}')
    print(f'    T2 losers: {len(loser_t2)} coins, loss: ${sum(a["pnl"] for a in loser_t2):+.2f}')
    print(f'  Winner breakdown by tier:')
    print(f'    T1 winners: {len(winner_t1)} coins, gain: ${sum(a["pnl"] for a in winner_t1):+.2f}')
    print(f'    T2 winners: {len(winner_t2)} coins, gain: ${sum(a["pnl"] for a in winner_t2):+.2f}')

    # Volume profiles: losers vs winners
    loser_vols = [a['daily_volume_usd'] for a in losers if a['daily_volume_usd'] > 0]
    winner_vols = [a['daily_volume_usd'] for a in winners if a['daily_volume_usd'] > 0]

    def vol_stats(vols, label):
        if not vols:
            return {'label': label, 'count': 0, 'median': 0, 'p25': 0, 'p75': 0, 'mean': 0}
        vols_sorted = sorted(vols)
        n = len(vols_sorted)
        return {
            'label': label,
            'count': n,
            'median': round(vols_sorted[n // 2], 0),
            'p25': round(vols_sorted[n // 4], 0) if n >= 4 else round(vols_sorted[0], 0),
            'p75': round(vols_sorted[3 * n // 4], 0) if n >= 4 else round(vols_sorted[-1], 0),
            'mean': round(sum(vols) / len(vols), 0),
        }

    loser_vol_stats = vol_stats(loser_vols, 'losers')
    winner_vol_stats = vol_stats(winner_vols, 'winners')
    print(f'\n  Volume profiles:')
    print(f'    Losers:  median=${loser_vol_stats["median"]:.0f}/d, '
          f'p25=${loser_vol_stats["p25"]:.0f}, p75=${loser_vol_stats["p75"]:.0f}, '
          f'mean=${loser_vol_stats["mean"]:.0f}')
    print(f'    Winners: median=${winner_vol_stats["median"]:.0f}/d, '
          f'p25=${winner_vol_stats["p25"]:.0f}, p75=${winner_vol_stats["p75"]:.0f}, '
          f'mean=${winner_vol_stats["mean"]:.0f}')

    # ============================================================
    # STEP 3: Regime/Fold Analysis
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 3: Walk-Forward 5-Fold per-coin analysis')
    print('=' * 70)

    print('  Running walk-forward 5-fold on full 316 coins...')
    fold_trades = run_wf(data, tier_coins_full, tier_indicators_full,
                         market_context, tier1_fee, tier2_fee, n_folds=5)

    # Per-fold summary
    fold_summaries = []
    for fold_idx in sorted(fold_trades.keys()):
        trades_in_fold = fold_trades[fold_idx]
        fold_pnl = sum(t['pnl'] for t in trades_in_fold)
        fold_n = len(trades_in_fold)
        fold_summaries.append({
            'fold': fold_idx,
            'trades': fold_n,
            'pnl': round(fold_pnl, 2),
            'positive': fold_pnl > 0,
        })
        print(f'    Fold {fold_idx}: {fold_n} trades, P&L=${fold_pnl:+.2f}, '
              f'{"POSITIVE" if fold_pnl > 0 else "NEGATIVE"}')

    # Per-fold per-coin analysis
    fcp = per_fold_coin_pnl(fold_trades)
    persistent_losers, fold_specific_losers = identify_persistent_losers(fcp, n_folds=5, threshold=3)

    print(f'\n  Persistent losers (negative in >=3/5 folds): {len(persistent_losers)} coins')
    for coin, info in sorted(persistent_losers.items(), key=lambda x: x[1]['negative_folds'], reverse=True):
        tier = 'T1' if coin in t1_set else 'T2'
        fold_str = ', '.join(f'F{k}=${v:+.0f}' for k, v in sorted(info['fold_pnls'].items()))
        print(f'    {coin:16s} [{tier}] neg_folds={info["negative_folds"]}/{info["total_folds_traded"]}  {fold_str}')

    print(f'\n  Fold-specific losers (negative in 1-2 folds only): {len(fold_specific_losers)} coins')
    for coin, info in sorted(fold_specific_losers.items(), key=lambda x: x[1]['negative_folds'], reverse=True)[:10]:
        tier = 'T1' if coin in t1_set else 'T2'
        fold_str = ', '.join(f'F{k}=${v:+.0f}' for k, v in sorted(info['fold_pnls'].items()))
        print(f'    {coin:16s} [{tier}] neg_folds={info["negative_folds"]}/{info["total_folds_traded"]}  {fold_str}')
    if len(fold_specific_losers) > 10:
        print(f'    ... and {len(fold_specific_losers) - 10} more')

    # Per-fold: which coins are negative?
    fold_negative_coins = {}
    for fold_idx, coin_pnl in fcp.items():
        neg_coins = sorted([c for c, p in coin_pnl.items() if p < 0])
        fold_negative_coins[fold_idx] = neg_coins
        print(f'\n    Fold {fold_idx}: {len(neg_coins)} negative coins')
        for c in neg_coins[:5]:
            tier = 'T1' if c in t1_set else 'T2'
            print(f'      {c:16s} [{tier}] P&L=${coin_pnl[c]:+.2f}')
        if len(neg_coins) > 5:
            print(f'      ... and {len(neg_coins) - 5} more')

    # ============================================================
    # STEP 4: Volume-based clustering (T2 only)
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 4: T2 Volume Quartile Analysis')
    print('=' * 70)

    t2_coins_list = tier_coins_full['tier2']
    t2_quartiles = volume_quartiles(coin_volumes, t2_coins_list)

    # For each quartile, find trades and compute metrics
    t2_trades_by_coin = defaultdict(list)
    for t in baseline_trades:
        if t.get('_tier') == 'tier2':
            t2_trades_by_coin[t['pair']].append(t)

    quartile_results = {}
    for q_label in ['Q1', 'Q2', 'Q3', 'Q4']:
        q_coins = t2_quartiles[q_label]
        q_trades = []
        for c in q_coins:
            q_trades.extend(t2_trades_by_coin.get(c, []))
        q_pnl = sum(t['pnl'] for t in q_trades)
        q_wins = sum(1 for t in q_trades if t['pnl'] > 0)
        q_n = len(q_trades)
        q_wr = q_wins / q_n * 100 if q_n > 0 else 0
        q_tw = sum(t['pnl'] for t in q_trades if t['pnl'] > 0)
        q_tl = abs(sum(t['pnl'] for t in q_trades if t['pnl'] <= 0))
        q_pf = q_tw / q_tl if q_tl > 0 else (float('inf') if q_tw > 0 else 0)
        q_vols = [coin_volumes.get(c, 0) for c in q_coins]
        q_vol_median = round(statistics.median(q_vols), 0) if q_vols else 0
        q_vol_range = f'${min(q_vols):.0f}-${max(q_vols):.0f}' if q_vols else 'N/A'
        # Count negative coins in this quartile
        q_neg_coins = sum(1 for c in q_coins if sum(t['pnl'] for t in t2_trades_by_coin.get(c, [])) < 0)
        q_pos_coins = sum(1 for c in q_coins if sum(t['pnl'] for t in t2_trades_by_coin.get(c, [])) > 0)
        q_no_trades = sum(1 for c in q_coins if not t2_trades_by_coin.get(c, []))

        quartile_results[q_label] = {
            'n_coins': len(q_coins),
            'trades': q_n,
            'pnl': round(q_pnl, 2),
            'wr_pct': round(q_wr, 1),
            'pf': round(q_pf, 3),
            'vol_median': q_vol_median,
            'vol_range': q_vol_range,
            'neg_coins': q_neg_coins,
            'pos_coins': q_pos_coins,
            'no_trade_coins': q_no_trades,
            'coins': q_coins,
        }
        print(f'  {q_label} (n={len(q_coins)}, vol_med=${q_vol_median:.0f}): '
              f'trades={q_n}, P&L=${q_pnl:+.2f}, WR={q_wr:.1f}%, PF={q_pf:.3f}, '
              f'neg_coins={q_neg_coins}, pos_coins={q_pos_coins}, no_trade={q_no_trades}')

    # ============================================================
    # STEP 5: New exclusion candidates
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 5: New Exclusion Candidates')
    print('=' * 70)

    # Criteria: negative P&L AND persistent (>=3/5 folds) AND low volume
    # Also check: in current EXCLUDED_21?
    candidate_blacklist = []
    for a in attribution:
        if a['pnl'] >= 0:
            continue
        coin = a['coin']
        is_persistent = coin in persistent_losers
        vol = a['daily_volume_usd']
        in_excluded_21 = coin in EXCLUDED_21

        # Candidate if: persistent loser OR single-trade loser with low volume
        # OR any negative coin already in EXCLUDED_21
        is_candidate = False
        reason_parts = []
        if is_persistent:
            is_candidate = True
            neg_folds = persistent_losers[coin]['negative_folds']
            reason_parts.append(f'persistent ({neg_folds}/5 folds negative)')
        if a['trades'] == 1 and a['pnl'] < -50:
            is_candidate = True
            reason_parts.append('single-trade loser (P&L < -$50)')
        if a['pnl'] < -100:
            is_candidate = True
            reason_parts.append(f'large loss (${a["pnl"]:.0f})')

        if is_candidate:
            candidate_blacklist.append({
                'coin': coin,
                'tier': a['tier'],
                'pnl': a['pnl'],
                'trades': a['trades'],
                'daily_volume_usd': vol,
                'in_excluded_21': in_excluded_21,
                'is_persistent': is_persistent,
                'reason': ' + '.join(reason_parts),
            })

    # Whitelist: coins that are net-negative but show signs of recovery
    candidate_whitelist = []
    for a in attribution:
        if a['pnl'] >= 0:
            continue
        coin = a['coin']
        if coin in persistent_losers:
            continue  # persistent losers stay on blacklist
        # Whitelist if: small loss AND high volume AND not persistent
        if abs(a['pnl']) < 30 and a['daily_volume_usd'] > 100000:
            candidate_whitelist.append({
                'coin': coin,
                'tier': a['tier'],
                'pnl': a['pnl'],
                'trades': a['trades'],
                'daily_volume_usd': a['daily_volume_usd'],
                'reason': 'small loss + high volume + not persistent',
            })

    print(f'  Candidate blacklist: {len(candidate_blacklist)} coins')
    for cb in candidate_blacklist:
        tag = ' [IN EXCL-21]' if cb['in_excluded_21'] else ' [NEW]'
        print(f'    {cb["coin"]:16s} [{cb["tier"]}] P&L=${cb["pnl"]:+.2f}  '
              f'vol=${cb["daily_volume_usd"]:.0f}/d  {cb["reason"]}{tag}')

    new_candidates = [cb for cb in candidate_blacklist if not cb['in_excluded_21']]
    confirmed_21 = [cb for cb in candidate_blacklist if cb['in_excluded_21']]
    print(f'\n  New candidates (not in EXCLUDED_21): {len(new_candidates)}')
    print(f'  Confirmed from EXCLUDED_21: {len(confirmed_21)}')

    print(f'\n  Candidate whitelist (should NOT exclude): {len(candidate_whitelist)} coins')
    for cw in candidate_whitelist:
        print(f'    {cw["coin"]:16s} [{cw["tier"]}] P&L=${cw["pnl"]:+.2f}  '
              f'vol=${cw["daily_volume_usd"]:.0f}/d  {cw["reason"]}')

    # ============================================================
    # STEP 6: Gate evaluation with new exclusion list
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 6: Gate Evaluation -- Baseline vs EXCLUDED_21 vs New List')
    print('=' * 70)

    # Build new exclusion set = EXCLUDED_21 + new candidates
    new_exclusion_set = EXCLUDED_21 | set(cb['coin'] for cb in new_candidates)

    exclusion_strategies = [
        ('full_316', set()),
        ('excl_21_current', EXCLUDED_21),
        ('excl_new_candidates', new_exclusion_set),
    ]

    eval_results = []
    for name, excl_set in exclusion_strategies:
        excl_t1 = excl_set & t1_set
        excl_t2 = excl_set & t2_set
        kept_coins = {
            'tier1': [c for c in tier_coins_full['tier1'] if c not in excl_set],
            'tier2': [c for c in tier_coins_full['tier2'] if c not in excl_set],
        }
        n_kept = len(kept_coins['tier1']) + len(kept_coins['tier2'])
        print(f'\n  {name}: {n_kept} coins (excl {len(excl_set)}: T1={len(excl_t1)}, T2={len(excl_t2)})')

        result = run_full_evaluation(
            label=name, data=data, tier_coins=kept_coins,
            all_indicators_cache=tier_indicators_full, market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
        )
        result['excluded_coins'] = sorted(excl_set)
        eval_results.append(result)

    elapsed_total = time.time() - t0_total

    # ============================================================
    # VERDICT
    # ============================================================
    print('\n' + '=' * 70)
    print('  VERDICT')
    print('=' * 70)

    loser_t2_pct = len(loser_t2) / len(losers) * 100 if losers else 0
    loser_t1_pct = len(loser_t1) / len(losers) * 100 if losers else 0
    loser_t2_loss_pct = abs(sum(a['pnl'] for a in loser_t2)) / abs(total_loser_pnl) * 100 if total_loser_pnl else 0

    is_t2_dominant = loser_t2_pct > 70 and loser_t2_loss_pct > 60
    q1_loss = quartile_results.get('Q1', {}).get('pnl', 0)
    q4_loss = quartile_results.get('Q4', {}).get('pnl', 0)
    is_low_vol_concentrated = q1_loss < q4_loss and q1_loss < 0

    if is_t2_dominant and is_low_vol_concentrated:
        verdict = 'CONFIRMED: Loss is primarily T2-low-volume pattern'
    elif is_t2_dominant:
        verdict = 'PARTIAL: T2 dominates losses but not clearly low-volume concentrated'
    elif loser_t2_pct > 50:
        verdict = 'MIXED: T2 majority of losers but T1 also contributes significantly'
    else:
        verdict = 'REJECTED: Loss is NOT primarily T2-low-volume'

    print(f'  Loser T2%: {loser_t2_pct:.1f}% of losers are T2')
    print(f'  Loser T2 loss%: {loser_t2_loss_pct:.1f}% of total loss from T2')
    print(f'  Q1 (lowest vol) P&L: ${q1_loss:+.2f}')
    print(f'  Q4 (highest vol) P&L: ${q4_loss:+.2f}')
    print(f'  Persistent losers: {len(persistent_losers)} coins')
    print(f'  -> {verdict}')
    print(f'\n  New exclusion candidates: {len(new_candidates)} coins')
    if new_candidates:
        for nc in new_candidates:
            print(f'    {nc["coin"]}')

    # ============================================================
    # BUILD JSON REPORT
    # ============================================================
    report = {
        'run_header': {
            'task': 'P0-5_losers_cluster_diagnostics',
            'agent': 'C7-E',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': BASELINE_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees_bps': {'tier1': round(tier1_fee * 10000, 1), 'tier2': round(tier2_fee * 10000, 1)},
            'stress_fees_bps': {'tier1': round(stress_tier1_fee * 10000, 1),
                                'tier2': round(stress_tier2_fee * 10000, 1)},
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'step1_per_coin_attribution': {
            'total_coins_in_universe': n_t1 + n_t2,
            'coins_with_trades': n_trading,
            'coins_no_trades': len(coins_no_trades),
            'coins_net_negative': n_negative,
            'coins_net_positive': n_positive,
            'coins_breakeven': n_zero,
            'full_attribution': attribution,
        },
        'step2_loser_analysis': {
            'total_losers': len(losers),
            'total_loss': round(total_loser_pnl, 2),
            'total_winners': len(winners),
            'total_gain': round(total_winner_pnl, 2),
            'net_pnl': round(total_loser_pnl + total_winner_pnl, 2),
            'loser_tier_breakdown': {
                'T1': {'count': len(loser_t1), 'loss': round(sum(a['pnl'] for a in loser_t1), 2)},
                'T2': {'count': len(loser_t2), 'loss': round(sum(a['pnl'] for a in loser_t2), 2)},
            },
            'winner_tier_breakdown': {
                'T1': {'count': len(winner_t1), 'gain': round(sum(a['pnl'] for a in winner_t1), 2)},
                'T2': {'count': len(winner_t2), 'gain': round(sum(a['pnl'] for a in winner_t2), 2)},
            },
            'volume_profiles': {
                'losers': loser_vol_stats,
                'winners': winner_vol_stats,
            },
            'loser_t2_pct': round(loser_t2_pct, 1),
            'loser_t2_loss_pct': round(loser_t2_loss_pct, 1),
        },
        'step3_fold_analysis': {
            'fold_summaries': fold_summaries,
            'persistent_losers': {
                'count': len(persistent_losers),
                'coins': {k: v for k, v in sorted(persistent_losers.items(),
                          key=lambda x: x[1]['negative_folds'], reverse=True)},
            },
            'fold_specific_losers': {
                'count': len(fold_specific_losers),
                'coins': {k: v for k, v in sorted(fold_specific_losers.items(),
                          key=lambda x: x[1]['negative_folds'], reverse=True)},
            },
            'fold_negative_coins': {
                str(k): v for k, v in fold_negative_coins.items()
            },
        },
        'step4_volume_quartiles': {
            q: {k: v for k, v in qr.items() if k != 'coins'}
            for q, qr in quartile_results.items()
        },
        'step4_volume_quartiles_coins': {
            q: qr['coins'] for q, qr in quartile_results.items()
        },
        'step5_exclusion_candidates': {
            'candidate_blacklist': candidate_blacklist,
            'new_candidates_not_in_21': [cb for cb in candidate_blacklist if not cb['in_excluded_21']],
            'confirmed_from_21': [cb for cb in candidate_blacklist if cb['in_excluded_21']],
            'candidate_whitelist': candidate_whitelist,
            'new_exclusion_set': sorted(new_exclusion_set),
            'new_exclusion_count': len(new_exclusion_set),
        },
        'step6_gate_evaluations': eval_results,
        'verdict': {
            'loser_t2_pct': round(loser_t2_pct, 1),
            'loser_t2_loss_pct': round(loser_t2_loss_pct, 1),
            'q1_pnl': quartile_results.get('Q1', {}).get('pnl', 0),
            'q4_pnl': quartile_results.get('Q4', {}).get('pnl', 0),
            'persistent_loser_count': len(persistent_losers),
            'is_t2_low_volume_pattern': is_t2_dominant and is_low_vol_concentrated,
            'verdict_text': verdict,
            'new_candidates_count': len(new_candidates),
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_losers_cluster_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # BUILD MARKDOWN REPORT
    # ============================================================
    md = []
    md.append('# P0-5: Losers Cluster Diagnostics')
    md.append('')
    md.append(f'**Agent**: C7-E')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    md.append(f'**Params**: dev={BASELINE_PARAMS["dev_thresh"]}, tp={BASELINE_PARAMS["tp_pct"]}, '
              f'sl={BASELINE_PARAMS["sl_pct"]}, tl={BASELINE_PARAMS["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Section 1: Per-coin attribution
    md.append('## 1. Per-Coin P&L Attribution (All 316 Coins)')
    md.append('')
    md.append(f'- Coins in universe: {n_t1+n_t2}')
    md.append(f'- Coins with trades: {n_trading}')
    md.append(f'- Coins with NO trades: {len(coins_no_trades)}')
    md.append(f'- Net-negative: {n_negative}')
    md.append(f'- Net-positive: {n_positive}')
    md.append(f'- **Baseline P&L**: ${baseline_metrics["pnl"]:.0f} (PF={baseline_metrics["pf"]:.3f})')
    md.append('')
    md.append('### Full Per-Coin Table (sorted worst first)')
    md.append('')
    md.append('| # | Coin | Tier | P&L | Trades | WR% | Avg/Trade | Fees Est | Vol $/d |')
    md.append('|---|------|------|-----|--------|-----|-----------|----------|---------|')
    for i, a in enumerate(attribution):
        md.append(f'| {i+1} | {a["coin"]} | {a["tier"]} | ${a["pnl"]:+.2f} | '
                  f'{a["trades"]} | {a["wr_pct"]:.0f}% | ${a["avg_pnl_per_trade"]:+.2f} | '
                  f'${a["total_fees_est"]:.0f} | ${a["daily_volume_usd"]:.0f} |')
    md.append('')

    # Section 2: Loser analysis
    md.append('## 2. Loser Analysis')
    md.append('')
    md.append(f'- **Total losers**: {len(losers)} coins, total loss: ${total_loser_pnl:+.2f}')
    md.append(f'- **Total winners**: {len(winners)} coins, total gain: ${total_winner_pnl:+.2f}')
    md.append(f'- **Net**: ${total_loser_pnl + total_winner_pnl:+.2f}')
    md.append('')
    md.append('### Tier Breakdown')
    md.append('')
    md.append('| Group | T1 Count | T1 P&L | T2 Count | T2 P&L |')
    md.append('|-------|----------|--------|----------|--------|')
    md.append(f'| Losers | {len(loser_t1)} | ${sum(a["pnl"] for a in loser_t1):+.2f} | '
              f'{len(loser_t2)} | ${sum(a["pnl"] for a in loser_t2):+.2f} |')
    md.append(f'| Winners | {len(winner_t1)} | ${sum(a["pnl"] for a in winner_t1):+.2f} | '
              f'{len(winner_t2)} | ${sum(a["pnl"] for a in winner_t2):+.2f} |')
    md.append('')
    md.append('### Volume Profiles')
    md.append('')
    md.append('| Group | Count | Median $/d | P25 $/d | P75 $/d | Mean $/d |')
    md.append('|-------|-------|-----------|---------|---------|----------|')
    for vs in [loser_vol_stats, winner_vol_stats]:
        md.append(f'| {vs["label"]} | {vs["count"]} | ${vs["median"]:.0f} | '
                  f'${vs["p25"]:.0f} | ${vs["p75"]:.0f} | ${vs["mean"]:.0f} |')
    md.append('')

    # Section 3: Fold analysis
    md.append('## 3. Walk-Forward Fold Analysis')
    md.append('')
    md.append('### Fold Summaries')
    md.append('')
    md.append('| Fold | Trades | P&L | Positive |')
    md.append('|------|--------|-----|----------|')
    for fs in fold_summaries:
        md.append(f'| {fs["fold"]} | {fs["trades"]} | ${fs["pnl"]:.0f} | '
                  f'{"YES" if fs["positive"] else "NO"} |')
    md.append('')

    md.append(f'### Persistent Losers (negative in >=3/5 folds): {len(persistent_losers)} coins')
    md.append('')
    if persistent_losers:
        md.append('| Coin | Tier | Neg Folds | Fold P&Ls |')
        md.append('|------|------|-----------|-----------|')
        for coin, info in sorted(persistent_losers.items(), key=lambda x: x[1]['negative_folds'], reverse=True):
            tier = 'T1' if coin in t1_set else 'T2'
            fold_str = ', '.join(f'F{k}=${v:+.0f}' for k, v in sorted(info['fold_pnls'].items()))
            md.append(f'| {coin} | {tier} | {info["negative_folds"]}/{info["total_folds_traded"]} | {fold_str} |')
        md.append('')

    md.append(f'### Fold-Specific Losers (negative in 1-2 folds): {len(fold_specific_losers)} coins')
    md.append('')
    if fold_specific_losers:
        md.append('| Coin | Tier | Neg Folds | Fold P&Ls |')
        md.append('|------|------|-----------|-----------|')
        for coin, info in sorted(fold_specific_losers.items(), key=lambda x: x[1]['negative_folds'], reverse=True):
            tier = 'T1' if coin in t1_set else 'T2'
            fold_str = ', '.join(f'F{k}=${v:+.0f}' for k, v in sorted(info['fold_pnls'].items()))
            md.append(f'| {coin} | {tier} | {info["negative_folds"]}/{info["total_folds_traded"]} | {fold_str} |')
        md.append('')

    md.append('### Per-Fold Negative Coins')
    md.append('')
    for fold_idx in sorted(fold_negative_coins.keys()):
        neg_coins = fold_negative_coins[fold_idx]
        md.append(f'**Fold {fold_idx}**: {len(neg_coins)} negative coins: '
                  + ', '.join(neg_coins))
        md.append('')

    # Section 4: Volume quartiles
    md.append('## 4. T2 Volume Quartile Analysis')
    md.append('')
    md.append('| Quartile | Coins | Trades | P&L | WR% | PF | Vol Median $/d | Neg Coins | Pos Coins | No Trades |')
    md.append('|----------|-------|--------|-----|-----|----|-----------      |-----------|-----------|-----------|')
    for q_label in ['Q1', 'Q2', 'Q3', 'Q4']:
        qr = quartile_results[q_label]
        md.append(f'| {q_label} | {qr["n_coins"]} | {qr["trades"]} | ${qr["pnl"]:+.2f} | '
                  f'{qr["wr_pct"]:.1f}% | {qr["pf"]:.3f} | ${qr["vol_median"]:.0f} | '
                  f'{qr["neg_coins"]} | {qr["pos_coins"]} | {qr["no_trade_coins"]} |')
    md.append('')

    # Section 5: Exclusion candidates
    md.append('## 5. Exclusion Candidates')
    md.append('')
    md.append(f'### Candidate Blacklist ({len(candidate_blacklist)} coins)')
    md.append('')
    if candidate_blacklist:
        md.append('| Coin | Tier | P&L | Trades | Vol $/d | In Excl-21 | Persistent | Reason |')
        md.append('|------|------|-----|--------|---------|------------|------------|--------|')
        for cb in candidate_blacklist:
            md.append(f'| {cb["coin"]} | {cb["tier"]} | ${cb["pnl"]:+.2f} | {cb["trades"]} | '
                      f'${cb["daily_volume_usd"]:.0f} | {"YES" if cb["in_excluded_21"] else "NO"} | '
                      f'{"YES" if cb["is_persistent"] else "NO"} | {cb["reason"]} |')
        md.append('')

    md.append(f'### New Candidates NOT in EXCLUDED_21: {len(new_candidates)}')
    md.append('')
    if new_candidates:
        for nc in new_candidates:
            md.append(f'- **{nc["coin"]}** [{nc["tier"]}]: P&L=${nc["pnl"]:+.2f}, '
                      f'vol=${nc["daily_volume_usd"]:.0f}/d, {nc["reason"]}')
        md.append('')

    md.append(f'### Whitelist (should NOT exclude): {len(candidate_whitelist)}')
    md.append('')
    if candidate_whitelist:
        for cw in candidate_whitelist:
            md.append(f'- **{cw["coin"]}** [{cw["tier"]}]: P&L=${cw["pnl"]:+.2f}, '
                      f'vol=${cw["daily_volume_usd"]:.0f}/d, {cw["reason"]}')
        md.append('')

    # Section 6: Gate evaluations
    md.append('## 6. Gate Evaluation Comparison')
    md.append('')
    md.append('| Strategy | Coins | Trades | PF | Exp/Wk | DD% | WF | Fold Conc | Score |')
    md.append('|----------|-------|--------|----|--------|-----|----|-----------|-------|')
    for r in eval_results:
        m = r['metrics']
        ge = r['gate_evaluation']
        fc = r['fold_concentration']
        md.append(f'| {r["label"]} | {r["n_coins"]} | {m["trades"]} | {m["pf"]:.3f} '
                  f'| ${m["exp_per_week"]:.2f} | {m["max_dd_pct"]:.1f}% '
                  f'| {r["wf_folds_positive"]}/5 | {fc["top1_fold_conc_pct"]:.1f}% '
                  f'| **{ge["score"]}** |')
    md.append('')

    for r in eval_results:
        ge = r['gate_evaluation']
        md.append(f'### {r["label"]} ({r["n_coins"]} coins)')
        md.append('')
        md.append('| Gate | Metric | Value | Threshold | Verdict |')
        md.append('|------|--------|-------|-----------|---------|')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = ge['gates'][gid]
            status = 'PASS' if g['pass'] else '**FAIL**'
            md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
        md.append('')
        if r.get('wf_fold_details'):
            md.append('Walk-Forward Folds:')
            md.append('')
            for fd in r['wf_fold_details']:
                pos_str = 'YES' if fd['positive'] else 'NO'
                md.append(f'- Fold {fd["fold"]}: {fd["trades"]} trades, ${fd["pnl"]:.0f}, {pos_str}')
            md.append('')

    # Section 7: Verdict
    md.append('## 7. Verdict')
    md.append('')
    md.append(f'**{verdict}**')
    md.append('')
    md.append(f'- Loser T2%: {loser_t2_pct:.1f}% of losers are T2')
    md.append(f'- Loser T2 loss%: {loser_t2_loss_pct:.1f}% of total loss from T2')
    md.append(f'- T2 Q1 (lowest vol) P&L: ${q1_loss:+.2f}')
    md.append(f'- T2 Q4 (highest vol) P&L: ${q4_loss:+.2f}')
    md.append(f'- Persistent losers (>=3/5 folds): {len(persistent_losers)} coins')
    md.append(f'- New exclusion candidates: {len(new_candidates)} coins')
    md.append(f'- Current EXCLUDED_21 confirmed: {len(confirmed_21)}/{len(EXCLUDED_21)}')
    md.append('')

    # List all losers
    md.append('### All Net-Negative Coins')
    md.append('')
    md.append('| # | Coin | Tier | P&L | Trades | WR% | Vol $/d | Persistent | In Excl-21 |')
    md.append('|---|------|------|-----|--------|-----|---------|------------|------------|')
    for i, a in enumerate(losers):
        coin = a['coin']
        is_pers = 'YES' if coin in persistent_losers else 'NO'
        in_21 = 'YES' if coin in EXCLUDED_21 else 'NO'
        md.append(f'| {i+1} | {coin} | {a["tier"]} | ${a["pnl"]:+.2f} | '
                  f'{a["trades"]} | {a["wr_pct"]:.0f}% | ${a["daily_volume_usd"]:.0f} | '
                  f'{is_pers} | {in_21} |')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_losers_cluster_001.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_losers_cluster_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # FINAL SUMMARY
    # ============================================================
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: P0-5 Losers Cluster Diagnostics')
    print(f'  Universe: {n_t1+n_t2} coins ({n_trading} with trades)')
    print(f'  Net-negative coins: {n_negative}')
    print(f'  Persistent losers (>=3/5 folds): {len(persistent_losers)}')
    print(f'  New exclusion candidates: {len(new_candidates)}')
    print(f'  Verdict: {verdict}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
