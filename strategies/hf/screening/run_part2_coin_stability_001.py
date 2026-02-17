#!/usr/bin/env python3
"""
C8-E: Coin Stability / Edge Persistence Analysis on 295 coins
==============================================================
Investigates whether profitable coins show consistent edge across
walk-forward folds or if profitability comes from one-off outlier trades.

Analysis dimensions:
  1. Per-coin fold consistency (appear in how many folds, profitable in each?)
  2. Stable winners: coins profitable in >=3/5 folds they appear in
  3. Stable losers: coins negative in >=3/5 folds
  4. One-shot coins: appear in only 1 fold
  5. Edge concentration: % of P&L from stable winners vs one-shot
  6. Fold-level coin diversity: unique coins per fold
  7. Stable-winners-only backtest: rerun full BT + WF on stable winners only

Gate thresholds (strict):
  G1 >= 10/wk, G2 <= 2.5d, G3 > $0, G4 > $0 (stress 2x), G5 <= 20%,
  G6 >= 4/5, G8 < 35%

Output:
  reports/hf/part2_coin_stability_001.json
  reports/hf/part2_coin_stability_001.md

Usage:
    python -m strategies.hf.screening.run_part2_coin_stability_001
    python -m strategies.hf.screening.run_part2_coin_stability_001 --dry-run
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
BARS_PER_WEEK = 168   # 24 * 7
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

REPORT_JSON = 'part2_coin_stability_001.json'
REPORT_MD = 'part2_coin_stability_001.md'

# Gate thresholds
GATE_THRESHOLDS = {
    'G1_trades_per_week': 10,     # >= 10/wk
    'G2_max_gap_days': 2.5,       # <= 2.5d
    'G3_pnl_positive': 0.0,       # > $0
    'G4_stress_pnl_positive': 0.0, # > $0 at 2x stress
    'G5_top1_share': 20,          # <= 20%
    'G6_wf_folds': 4,             # >= 4/5
    'G8_dd': 35,                  # < 35%
}


# ============================================================
# Data Loading
# ============================================================
def load_candle_cache():
    cache_path = ROOT / 'data' / 'candle_cache_1h.json'
    if cache_path.exists():
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        return coins_data
    # Fallback to parts
    parts_base = ROOT / 'data' / 'cache_parts_hf' / '1h'
    if not parts_base.exists():
        return None
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir():
            continue
        for coin_file in sorted(exchange_dir.glob('*.json')):
            symbol = coin_file.stem.replace('_', '/')
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
    return coins_data if coins_data else None


def load_universe_tiering():
    p = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not p.exists():
        return None
    with open(p) as f:
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
    for key_name in ['tier_1', 'Tier 1 (Liquid)', 'tier1', '1']:
        if key_name in tiers:
            coins = tiers[key_name].get('coins', [])
            tier_coins['tier1'] = [c for c in coins if c in available_coins]
            break
    for key_name in ['tier_2', 'Tier 2 (Mid)', 'tier2', '2']:
        if key_name in tiers:
            coins = tiers[key_name].get('coins', [])
            tier_coins['tier2'] = [c for c in coins if c in available_coins]
            break
    return tier_coins


# ============================================================
# Helpers
# ============================================================
def compute_max_gap(trades, total_bars):
    """Compute maximum gap between trades in days (uses exit_bar)."""
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


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    """Compute standard metrics from trade list."""
    n_trades = len(trades)
    if n_trades == 0:
        return {
            'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
            'dd': 0.0, 'expectancy': 0.0, 'trades_per_week': 0.0,
            'exp_per_week': 0.0, 'max_gap_days': 999.0, 'top1_share': 100.0,
        }

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

    max_gap_days = compute_max_gap(trades, total_bars) if total_bars else 999.0

    # Top-1 share (positive profit attribution)
    total_profit = sum(max(0, t['pnl']) for t in trades)
    if total_profit > 0:
        sorted_by_pnl = sorted(trades, key=lambda t: t['pnl'], reverse=True)
        top1_profit = max(0, sorted_by_pnl[0]['pnl'])
        top1_share = min(100.0, top1_profit / total_profit * 100)
    else:
        top1_share = 100.0

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

    return {
        'trades': n_trades,
        'pnl': round(total_pnl, 2),
        'pf': round(pf, 3),
        'wr': round(wr, 2),
        'dd': round(max_dd, 2),
        'expectancy': round(expectancy, 4),
        'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4),
        'max_gap_days': round(max_gap_days, 2),
        'top1_share': round(top1_share, 2),
    }


def estimate_total_bars(tier_indicators, tier_coins):
    """Estimate total bars from indicator data."""
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            ind = indicators.get(coin, {})
            n = ind.get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None):
    """Run H20 v5 across both tiers, return combined trade list."""
    if params is None:
        params = V5_PARAMS
    enriched_params = {**params, '__market__': market_context}
    signal_fn = signal_h20_vwap_deviation
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    all_trades = []

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_fn,
            params=enriched_params, indicators=indicators,
            fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    """Walk-forward across both tiers, return dict fold_idx -> trade list."""
    if params is None:
        params = V5_PARAMS
    enriched_params = {**params, '__market__': market_context}
    signal_fn = signal_h20_vwap_deviation
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    fold_trades = {}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_fn,
            params=enriched_params, indicators=indicators,
            n_folds=n_folds, fee=fee, max_pos=1,
        )
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in fold_trades:
                fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            fold_trades[fold_idx].extend(fold_bt.trade_list)

    return fold_trades


def gate_check(metrics, wf_folds_positive, total_bars):
    """Check strict gates and return dict of gate results."""
    gates = {}

    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tpw = metrics['trades'] / total_weeks if total_weeks > 0 else 0

    gates['G1_throughput'] = {
        'value': round(tpw, 2),
        'threshold': '>= 10/wk',
        'pass': tpw >= GATE_THRESHOLDS['G1_trades_per_week'],
    }
    gates['G2_max_gap'] = {
        'value': metrics['max_gap_days'],
        'threshold': '<= 2.5d',
        'pass': metrics['max_gap_days'] <= GATE_THRESHOLDS['G2_max_gap_days'],
    }
    gates['G3_pnl'] = {
        'value': metrics['pnl'],
        'threshold': '> $0',
        'pass': metrics['pnl'] > GATE_THRESHOLDS['G3_pnl_positive'],
    }
    gates['G5_top1_share'] = {
        'value': metrics['top1_share'],
        'threshold': '<= 20%',
        'pass': metrics['top1_share'] <= GATE_THRESHOLDS['G5_top1_share'],
    }
    gates['G6_wf_folds'] = {
        'value': wf_folds_positive,
        'threshold': '>= 4/5',
        'pass': wf_folds_positive >= GATE_THRESHOLDS['G6_wf_folds'],
    }
    gates['G8_dd'] = {
        'value': metrics['dd'],
        'threshold': '< 35%',
        'pass': metrics['dd'] < GATE_THRESHOLDS['G8_dd'],
    }

    all_pass = all(g['pass'] for g in gates.values())
    return gates, all_pass


# ============================================================
# Core Analysis: Coin Stability
# ============================================================
def analyze_coin_stability(full_trades, fold_trades):
    """
    Per-coin fold consistency analysis.

    Returns:
        coin_profiles: dict coin -> {folds_present, folds_positive, ...}
        classifications: dict coin -> 'stable_winner' | 'stable_loser' | 'one_shot' | 'mixed'
        summary: dict with aggregate stats
    """
    # Full backtest per-coin stats
    coin_full_pnl = defaultdict(float)
    coin_full_count = defaultdict(int)
    for t in full_trades:
        coin_full_pnl[t['pair']] += t['pnl']
        coin_full_count[t['pair']] += 1

    # Per-fold per-coin stats
    coin_fold_data = defaultdict(lambda: defaultdict(list))  # coin -> fold -> [pnl values]
    for fold_idx, trades in fold_trades.items():
        for t in trades:
            coin_fold_data[t['pair']][fold_idx].append(t['pnl'])

    all_coins = set(coin_full_pnl.keys()) | set(coin_fold_data.keys())
    n_folds = max(fold_trades.keys()) + 1 if fold_trades else 5

    coin_profiles = {}
    for coin in sorted(all_coins):
        folds_present = set(coin_fold_data[coin].keys())
        n_present = len(folds_present)

        fold_pnls = {}
        folds_positive = 0
        folds_negative = 0
        for fold_idx in folds_present:
            fold_pnl = sum(coin_fold_data[coin][fold_idx])
            fold_pnls[fold_idx] = round(fold_pnl, 2)
            if fold_pnl > 0:
                folds_positive += 1
            elif fold_pnl < 0:
                folds_negative += 1

        total_fold_pnl = sum(fold_pnls.values())
        full_pnl = round(coin_full_pnl.get(coin, 0.0), 2)
        full_trades_n = coin_full_count.get(coin, 0)

        # Consistency score: positive folds / folds present
        consistency = folds_positive / n_present if n_present > 0 else 0.0

        coin_profiles[coin] = {
            'folds_present': n_present,
            'folds_positive': folds_positive,
            'folds_negative': folds_negative,
            'fold_pnls': fold_pnls,
            'total_fold_pnl': round(total_fold_pnl, 2),
            'full_pnl': full_pnl,
            'full_trades': full_trades_n,
            'consistency_score': round(consistency, 3),
            'folds_list': sorted(folds_present),
        }

    # Classification
    classifications = {}
    for coin, profile in coin_profiles.items():
        n_present = profile['folds_present']
        n_positive = profile['folds_positive']
        n_negative = profile['folds_negative']

        if n_present <= 1:
            classifications[coin] = 'one_shot'
        elif n_positive >= 3:
            classifications[coin] = 'stable_winner'
        elif n_negative >= 3:
            classifications[coin] = 'stable_loser'
        else:
            classifications[coin] = 'mixed'

    # Summary stats
    stable_winners = [c for c, cls in classifications.items() if cls == 'stable_winner']
    stable_losers = [c for c, cls in classifications.items() if cls == 'stable_loser']
    one_shots = [c for c, cls in classifications.items() if cls == 'one_shot']
    mixed = [c for c, cls in classifications.items() if cls == 'mixed']

    total_profit = sum(max(0, t['pnl']) for t in full_trades)

    # P&L from stable winners
    sw_pnl = sum(coin_profiles[c]['full_pnl'] for c in stable_winners)
    sl_pnl = sum(coin_profiles[c]['full_pnl'] for c in stable_losers)
    os_pnl = sum(coin_profiles[c]['full_pnl'] for c in one_shots)
    mx_pnl = sum(coin_profiles[c]['full_pnl'] for c in mixed)
    total_pnl = sum(t['pnl'] for t in full_trades)

    # Profit concentration
    sw_profit = sum(
        max(0, t['pnl']) for t in full_trades if classifications.get(t['pair']) == 'stable_winner'
    )
    os_profit = sum(
        max(0, t['pnl']) for t in full_trades if classifications.get(t['pair']) == 'one_shot'
    )

    sw_profit_share = sw_profit / total_profit * 100 if total_profit > 0 else 0.0
    os_profit_share = os_profit / total_profit * 100 if total_profit > 0 else 0.0

    # Fold diversity
    fold_diversity = {}
    for fold_idx, trades in fold_trades.items():
        unique_coins = set(t['pair'] for t in trades)
        fold_diversity[fold_idx] = {
            'unique_coins': len(unique_coins),
            'trades': len(trades),
            'pnl': round(sum(t['pnl'] for t in trades), 2),
            'coins': sorted(unique_coins),
        }

    summary = {
        'total_coins_with_trades': len(all_coins),
        'n_stable_winners': len(stable_winners),
        'n_stable_losers': len(stable_losers),
        'n_one_shot': len(one_shots),
        'n_mixed': len(mixed),
        'stable_winners': sorted(stable_winners),
        'stable_losers': sorted(stable_losers),
        'one_shots': sorted(one_shots),
        'mixed_coins': sorted(mixed),
        'pnl_by_class': {
            'stable_winner': round(sw_pnl, 2),
            'stable_loser': round(sl_pnl, 2),
            'one_shot': round(os_pnl, 2),
            'mixed': round(mx_pnl, 2),
            'total': round(total_pnl, 2),
        },
        'profit_concentration': {
            'stable_winner_profit_share_pct': round(sw_profit_share, 1),
            'one_shot_profit_share_pct': round(os_profit_share, 1),
            'total_profit': round(total_profit, 2),
        },
        'fold_diversity': fold_diversity,
    }

    return coin_profiles, classifications, summary


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='C8-E: Coin Stability / Edge Persistence Analysis on 295 coins',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Load data and print overview, skip backtests')
    args = parser.parse_args()

    print('=' * 70)
    print('  C8-E: Coin Stability / Edge Persistence Analysis')
    print('  Universe: 295 coins (excl 21 net-negative)')
    print('  Signal: H20 VWAP_DEVIATION v5')
    print('  Cost: MEXC Market (T1=%.1fbps, T2=%.1fbps)' % (T1_FEE * 10000, T2_FEE * 10000))
    print('=' * 70)
    print('Started: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    t0 = time.time()

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    print('[Load] Loading candle cache...')
    data = load_candle_cache()
    if data is None:
        print('[ERROR] No candle cache found.')
        sys.exit(1)
    available_coins = set(data.keys())
    print('[Load] %d coins in cache.' % len(available_coins))

    tiering = load_universe_tiering()
    if tiering is None:
        print('[ERROR] No tiering file found.')
        sys.exit(1)

    tier_coins_full = build_tier_coins(tiering, available_coins)

    # Apply exclusion
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print('[Universe] T1(%d) + T2(%d) = %d coins (excl %d)' % (
        n_t1, n_t2, n_total, len(EXCLUDED_21)))

    if args.dry_run:
        print('\n--- DRY RUN: would run full BT + 5-fold WF + stress + stable-winner retest ---')
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print('  %s: %d coins in %.1fs' % (tier_name, len(coins), time.time() - t_ind))

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print('  %s: VWAP %.0f%% (%d/%d)' % (
                tier_name, cov['vwap_pct'], cov['vwap_available'], cov['total_coins']))

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

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print('[Data] total_bars=%d, total_weeks=%.1f' % (total_bars, total_weeks))

    # ============================================================
    # Step 1: Full backtest on 295 coins
    # ============================================================
    print('\n--- Step 1: Full Backtest (295 coins, MEXC baseline) ---')
    t_step = time.time()
    full_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                              T1_FEE, T2_FEE)
    full_metrics = compute_metrics(full_trades, total_bars=total_bars)
    print('  trades=%d, PF=%.3f, WR=%.1f%%, P&L=$%.2f, DD=%.1f%% (%.1fs)' % (
        full_metrics['trades'], full_metrics['pf'], full_metrics['wr'],
        full_metrics['pnl'], full_metrics['dd'], time.time() - t_step))

    # ============================================================
    # Step 2: Walk-forward 5-fold on 295 coins
    # ============================================================
    print('\n--- Step 2: Walk-Forward 5-Fold (295 coins) ---')
    t_step = time.time()
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         T1_FEE, T2_FEE, n_folds=5)
    folds_positive = 0
    fold_summary = []
    for fold_idx in sorted(fold_trades.keys()):
        fold_pnl = sum(t['pnl'] for t in fold_trades[fold_idx])
        fold_n = len(fold_trades[fold_idx])
        is_pos = fold_pnl > 0
        if is_pos:
            folds_positive += 1
        fold_summary.append({
            'fold': fold_idx, 'trades': fold_n,
            'pnl': round(fold_pnl, 2), 'positive': is_pos,
        })
        print('  Fold %d: %d trades, P&L=$%.2f %s' % (
            fold_idx, fold_n, fold_pnl, 'PASS' if is_pos else 'fail'))
    print('  WF result: %d/5 positive (%.1fs)' % (folds_positive, time.time() - t_step))

    # ============================================================
    # Step 3: Coin Stability Analysis
    # ============================================================
    print('\n--- Step 3: Coin Stability / Edge Persistence Analysis ---')
    t_step = time.time()
    coin_profiles, classifications, stability_summary = analyze_coin_stability(
        full_trades, fold_trades)

    print('  Total coins with trades: %d' % stability_summary['total_coins_with_trades'])
    print('  Stable winners (>=3/5 positive): %d  %s' % (
        stability_summary['n_stable_winners'],
        ', '.join(stability_summary['stable_winners'][:5]) +
        ('...' if stability_summary['n_stable_winners'] > 5 else '')))
    print('  Stable losers  (>=3/5 negative): %d  %s' % (
        stability_summary['n_stable_losers'],
        ', '.join(stability_summary['stable_losers'][:5]) +
        ('...' if stability_summary['n_stable_losers'] > 5 else '')))
    print('  One-shot (1 fold only):          %d' % stability_summary['n_one_shot'])
    print('  Mixed:                           %d' % stability_summary['n_mixed'])

    print('\n  P&L by class:')
    for cls, pnl in stability_summary['pnl_by_class'].items():
        print('    %-15s  $%.2f' % (cls, pnl))

    conc = stability_summary['profit_concentration']
    print('\n  Profit concentration:')
    print('    Stable winners: %.1f%% of total profit' % conc['stable_winner_profit_share_pct'])
    print('    One-shots:      %.1f%% of total profit' % conc['one_shot_profit_share_pct'])

    print('\n  Fold diversity:')
    for fold_idx, fd in stability_summary['fold_diversity'].items():
        print('    Fold %s: %d unique coins, %d trades, P&L=$%.2f' % (
            fold_idx, fd['unique_coins'], fd['trades'], fd['pnl']))

    print('  (%.1fs)' % (time.time() - t_step))

    # ============================================================
    # Step 4: Stable-Winners-Only Backtest + WF + Stress
    # ============================================================
    sw_coins = stability_summary['stable_winners']
    print('\n--- Step 4: Stable-Winners-Only Backtest ---')
    print('  Universe: %d stable winner coins' % len(sw_coins))

    if len(sw_coins) > 0:
        # Build tier coins for stable winners only
        tier_coins_sw = {
            'tier1': [c for c in tier_coins['tier1'] if c in sw_coins],
            'tier2': [c for c in tier_coins['tier2'] if c in sw_coins],
        }
        print('  SW T1(%d) + SW T2(%d)' % (
            len(tier_coins_sw['tier1']), len(tier_coins_sw['tier2'])))

        # Reuse existing indicators (they're already computed for all 295)
        # No need to recompute

        # Full backtest on SW coins
        t_step = time.time()
        sw_trades = run_variant(data, tier_coins_sw, tier_indicators, market_context,
                                T1_FEE, T2_FEE)
        sw_metrics = compute_metrics(sw_trades, total_bars=total_bars)
        print('  [Baseline] trades=%d, PF=%.3f, WR=%.1f%%, P&L=$%.2f, DD=%.1f%%' % (
            sw_metrics['trades'], sw_metrics['pf'], sw_metrics['wr'],
            sw_metrics['pnl'], sw_metrics['dd']))

        # WF on SW coins
        sw_fold_trades = run_wf(data, tier_coins_sw, tier_indicators, market_context,
                                T1_FEE, T2_FEE, n_folds=5)
        sw_folds_positive = 0
        sw_fold_details = []
        for fold_idx in sorted(sw_fold_trades.keys()):
            fold_pnl = sum(t['pnl'] for t in sw_fold_trades[fold_idx])
            fold_n = len(sw_fold_trades[fold_idx])
            is_pos = fold_pnl > 0
            if is_pos:
                sw_folds_positive += 1
            sw_fold_details.append({
                'fold': fold_idx, 'trades': fold_n,
                'pnl': round(fold_pnl, 2), 'positive': is_pos,
            })
            print('  [WF] Fold %d: %d trades, P&L=$%.2f %s' % (
                fold_idx, fold_n, fold_pnl, 'PASS' if is_pos else 'fail'))
        print('  [WF] %d/5 positive' % sw_folds_positive)

        # Stress 2x on SW coins
        sw_stress_trades = run_variant(data, tier_coins_sw, tier_indicators, market_context,
                                       T1_STRESS, T2_STRESS)
        sw_stress_metrics = compute_metrics(sw_stress_trades, total_bars=total_bars)
        print('  [Stress 2x] trades=%d, PF=%.3f, P&L=$%.2f' % (
            sw_stress_metrics['trades'], sw_stress_metrics['pf'], sw_stress_metrics['pnl']))

        # Gate check on SW
        sw_gates, sw_all_pass = gate_check(sw_metrics, sw_folds_positive, total_bars)
        # Also check G4 separately
        sw_gates['G4_stress_pnl'] = {
            'value': sw_stress_metrics['pnl'],
            'threshold': '> $0',
            'pass': sw_stress_metrics['pnl'] > 0,
        }
        sw_all_pass = sw_all_pass and sw_gates['G4_stress_pnl']['pass']

        print('\n  Gate check (stable winners only):')
        for gate_name, gate_result in sw_gates.items():
            status = 'PASS' if gate_result['pass'] else 'FAIL'
            print('    %s: %.2f (%s) -> %s' % (
                gate_name, gate_result['value'], gate_result['threshold'], status))
        print('  All gates: %s' % ('PASS' if sw_all_pass else 'FAIL'))

        print('  (%.1fs)' % (time.time() - t_step))

        sw_result = {
            'universe_size': len(sw_coins),
            'tier_split': {
                'tier1': len(tier_coins_sw['tier1']),
                'tier2': len(tier_coins_sw['tier2']),
            },
            'baseline_metrics': sw_metrics,
            'wf_folds_positive': sw_folds_positive,
            'wf_fold_details': sw_fold_details,
            'stress_metrics': {
                'pnl': sw_stress_metrics['pnl'],
                'pf': sw_stress_metrics['pf'],
                'trades': sw_stress_metrics['trades'],
            },
            'gates': sw_gates,
            'all_gates_pass': sw_all_pass,
        }
    else:
        print('  No stable winners found — skipping backtest.')
        sw_result = {'universe_size': 0, 'all_gates_pass': False}

    # ============================================================
    # Step 5: Gate Check on full 295 universe
    # ============================================================
    print('\n--- Step 5: Gate Check (full 295 universe) ---')

    # Stress 2x on full 295
    t_step = time.time()
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                T1_STRESS, T2_STRESS)
    stress_metrics = compute_metrics(stress_trades, total_bars=total_bars)
    print('  [Stress 2x] trades=%d, PF=%.3f, P&L=$%.2f (%.1fs)' % (
        stress_metrics['trades'], stress_metrics['pf'],
        stress_metrics['pnl'], time.time() - t_step))

    full_gates, full_all_pass = gate_check(full_metrics, folds_positive, total_bars)
    full_gates['G4_stress_pnl'] = {
        'value': stress_metrics['pnl'],
        'threshold': '> $0',
        'pass': stress_metrics['pnl'] > 0,
    }
    full_all_pass = full_all_pass and full_gates['G4_stress_pnl']['pass']

    print('\n  Gate check (full 295):')
    for gate_name, gate_result in full_gates.items():
        status = 'PASS' if gate_result['pass'] else 'FAIL'
        print('    %s: %.2f (%s) -> %s' % (
            gate_name, gate_result['value'], gate_result['threshold'], status))
    print('  All gates: %s' % ('PASS' if full_all_pass else 'FAIL'))

    elapsed = time.time() - t0
    print('\nTotal runtime: %.1fs' % elapsed)

    # ============================================================
    # Build JSON report
    # ============================================================
    # Coin profiles table (serializable)
    coin_profiles_serial = {}
    for coin, profile in coin_profiles.items():
        coin_profiles_serial[coin] = {
            **profile,
            'classification': classifications[coin],
            'fold_pnls': {str(k): v for k, v in profile['fold_pnls'].items()},
        }

    report = {
        'run_header': {
            'task': 'part2_coin_stability_001',
            'agent': 'C8-E',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'cost_regime': 'MEXC Market (costs_mexc_v2)',
            'fees': {
                'baseline': {'tier1_bps': round(T1_FEE * 10000, 1), 'tier2_bps': round(T2_FEE * 10000, 1)},
                'stress_2x': {'tier1_bps': round(T1_STRESS * 10000, 1), 'tier2_bps': round(T2_STRESS * 10000, 1)},
            },
            'universe': 'T1(%d)+T2(%d)=%d [excl 21 net-negative]' % (n_t1, n_t2, n_total),
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'full_295_baseline': {
            'metrics': full_metrics,
            'wf_folds_positive': folds_positive,
            'wf_fold_details': fold_summary,
            'stress_metrics': {
                'pnl': stress_metrics['pnl'],
                'pf': stress_metrics['pf'],
                'trades': stress_metrics['trades'],
            },
            'gates': full_gates,
            'all_gates_pass': full_all_pass,
        },
        'coin_stability': {
            'summary': stability_summary,
            'coin_profiles': coin_profiles_serial,
        },
        'stable_winners_only': sw_result,
        'verdict': {
            'full_295_gates': 'PASS' if full_all_pass else 'FAIL',
            'sw_only_gates': 'PASS' if sw_result.get('all_gates_pass', False) else 'FAIL',
            'edge_persistence': 'STRONG' if stability_summary['n_stable_winners'] >= 3 and
                                conc['stable_winner_profit_share_pct'] >= 50 else
                                'MODERATE' if stability_summary['n_stable_winners'] >= 2 else 'WEAK',
            'recommendation': '',  # filled below
        },
    }

    # Build recommendation
    rec_parts = []
    if stability_summary['n_stable_winners'] >= 3:
        rec_parts.append('Strong stable winner base (%d coins).' % stability_summary['n_stable_winners'])
    else:
        rec_parts.append('Limited stable winners (%d coins).' % stability_summary['n_stable_winners'])

    if conc['stable_winner_profit_share_pct'] >= 50:
        rec_parts.append('Stable winners dominate profit (%.0f%%).' % conc['stable_winner_profit_share_pct'])
    elif conc['one_shot_profit_share_pct'] > 50:
        rec_parts.append('WARNING: One-shot coins dominate profit (%.0f%%).' % conc['one_shot_profit_share_pct'])

    if sw_result.get('all_gates_pass', False):
        rec_parts.append('Stable-winners-only universe passes all gates.')
    else:
        failing_gates = [g for g, r in sw_result.get('gates', {}).items() if not r.get('pass', True)]
        if failing_gates:
            rec_parts.append('Stable-winners-only fails: %s.' % ', '.join(failing_gates))

    report['verdict']['recommendation'] = ' '.join(rec_parts)

    # Write JSON
    json_path = ROOT / 'reports' / 'hf' / REPORT_JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print('\n[Report] JSON: %s' % json_path)

    # ============================================================
    # Markdown Report
    # ============================================================
    md = []
    md.append('# C8-E: Coin Stability / Edge Persistence Analysis')
    md.append('')
    md.append('**Date**: %s | **Commit**: %s | **Runtime**: %.1fs' % (
        datetime.now().strftime('%Y-%m-%d %H:%M'), commit, elapsed))
    md.append('**Universe**: T1(%d) + T2(%d) = %d coins (excl 21 net-negative)' % (n_t1, n_t2, n_total))
    md.append('**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append('**Fees**: MEXC Market T1=%.1fbps T2=%.1fbps | Stress 2x T1=%.1fbps T2=%.1fbps' % (
        T1_FEE * 10000, T2_FEE * 10000, T1_STRESS * 10000, T2_STRESS * 10000))
    md.append('')

    # Verdict box
    md.append('## Verdict')
    md.append('')
    md.append('| Check | Result |')
    md.append('|-------|--------|')
    md.append('| Edge Persistence | **%s** |' % report['verdict']['edge_persistence'])
    md.append('| Full 295 Gates | **%s** |' % report['verdict']['full_295_gates'])
    md.append('| Stable-Winners-Only Gates | **%s** |' % report['verdict']['sw_only_gates'])
    md.append('')
    md.append('**Recommendation**: %s' % report['verdict']['recommendation'])
    md.append('')

    # Full 295 Gate Check
    md.append('## Gate Check: Full 295 Universe')
    md.append('')
    md.append('| Gate | Value | Threshold | Verdict |')
    md.append('|------|-------|-----------|---------|')
    for gate_name, gr in full_gates.items():
        status = 'PASS' if gr['pass'] else '**FAIL**'
        md.append('| %s | %.2f | %s | %s |' % (gate_name, gr['value'], gr['threshold'], status))
    md.append('')
    md.append('**Baseline**: %d trades, PF=%.3f, WR=%.1f%%, P&L=$%.2f, DD=%.1f%%' % (
        full_metrics['trades'], full_metrics['pf'], full_metrics['wr'],
        full_metrics['pnl'], full_metrics['dd']))
    md.append('')

    # WF detail
    md.append('### Walk-Forward Detail (5-Fold)')
    md.append('')
    md.append('| Fold | Trades | P&L | Positive |')
    md.append('|------|--------|-----|----------|')
    for fd in fold_summary:
        md.append('| %d | %d | $%.2f | %s |' % (
            fd['fold'], fd['trades'], fd['pnl'], 'YES' if fd['positive'] else 'no'))
    md.append('')

    # Coin Stability Analysis
    md.append('## Coin Stability Analysis')
    md.append('')
    md.append('| Category | Count | P&L | Coins |')
    md.append('|----------|-------|-----|-------|')
    md.append('| Stable Winners (>=3/5 positive) | %d | $%.2f | %s |' % (
        stability_summary['n_stable_winners'],
        stability_summary['pnl_by_class']['stable_winner'],
        ', '.join(stability_summary['stable_winners'][:8]) +
        ('...' if len(stability_summary['stable_winners']) > 8 else '')))
    md.append('| Stable Losers (>=3/5 negative) | %d | $%.2f | %s |' % (
        stability_summary['n_stable_losers'],
        stability_summary['pnl_by_class']['stable_loser'],
        ', '.join(stability_summary['stable_losers'][:8]) +
        ('...' if len(stability_summary['stable_losers']) > 8 else '')))
    md.append('| One-Shot (1 fold) | %d | $%.2f | %s |' % (
        stability_summary['n_one_shot'],
        stability_summary['pnl_by_class']['one_shot'],
        ', '.join(stability_summary['one_shots'][:8]) +
        ('...' if len(stability_summary['one_shots']) > 8 else '')))
    md.append('| Mixed | %d | $%.2f | %s |' % (
        stability_summary['n_mixed'],
        stability_summary['pnl_by_class']['mixed'],
        ', '.join(stability_summary['mixed_coins'][:8]) +
        ('...' if len(stability_summary['mixed_coins']) > 8 else '')))
    md.append('')

    # Profit Concentration
    md.append('### Profit Concentration')
    md.append('')
    md.append('| Source | % of Total Profit |')
    md.append('|--------|-------------------|')
    md.append('| Stable Winners | %.1f%% |' % conc['stable_winner_profit_share_pct'])
    md.append('| One-Shots | %.1f%% |' % conc['one_shot_profit_share_pct'])
    md.append('| Total Profit | $%.2f |' % conc['total_profit'])
    md.append('')

    # Fold Diversity
    md.append('### Fold Diversity')
    md.append('')
    md.append('| Fold | Unique Coins | Trades | P&L |')
    md.append('|------|-------------|--------|-----|')
    for fold_idx, fd in stability_summary['fold_diversity'].items():
        md.append('| %s | %d | %d | $%.2f |' % (fold_idx, fd['unique_coins'], fd['trades'], fd['pnl']))
    md.append('')

    # Per-Coin Detail Table
    md.append('## Per-Coin Profiles')
    md.append('')
    md.append('| Coin | Class | Folds Present | Folds Positive | Full P&L | Full Trades | Consistency | Fold P&Ls |')
    md.append('|------|-------|--------------|----------------|----------|-------------|-------------|-----------|')
    sorted_coins = sorted(coin_profiles.keys(),
                          key=lambda c: coin_profiles[c]['full_pnl'], reverse=True)
    for coin in sorted_coins:
        p = coin_profiles[coin]
        cls = classifications[coin]
        fold_pnl_str = ', '.join('F%s:$%.1f' % (k, v) for k, v in sorted(p['fold_pnls'].items()))
        md.append('| %s | %s | %d | %d | $%.2f | %d | %.3f | %s |' % (
            coin, cls, p['folds_present'], p['folds_positive'],
            p['full_pnl'], p['full_trades'], p['consistency_score'], fold_pnl_str))
    md.append('')

    # Stable-Winners-Only Results
    md.append('## Stable-Winners-Only Backtest')
    md.append('')
    if sw_result.get('universe_size', 0) > 0:
        md.append('**Universe**: %d coins (T1:%d T2:%d)' % (
            sw_result['universe_size'],
            sw_result['tier_split']['tier1'], sw_result['tier_split']['tier2']))
        md.append('')
        swm = sw_result['baseline_metrics']
        md.append('**Baseline**: %d trades, PF=%.3f, WR=%.1f%%, P&L=$%.2f, DD=%.1f%%' % (
            swm['trades'], swm['pf'], swm['wr'], swm['pnl'], swm['dd']))
        md.append('')
        md.append('**Walk-Forward**: %d/5 positive' % sw_result['wf_folds_positive'])
        md.append('')

        md.append('| Fold | Trades | P&L | Positive |')
        md.append('|------|--------|-----|----------|')
        for fd in sw_result.get('wf_fold_details', []):
            md.append('| %d | %d | $%.2f | %s |' % (
                fd['fold'], fd['trades'], fd['pnl'], 'YES' if fd['positive'] else 'no'))
        md.append('')

        ssm = sw_result.get('stress_metrics', {})
        md.append('**Stress 2x**: PF=%.3f, P&L=$%.2f' % (ssm.get('pf', 0), ssm.get('pnl', 0)))
        md.append('')

        md.append('### Gate Check (Stable Winners Only)')
        md.append('')
        md.append('| Gate | Value | Threshold | Verdict |')
        md.append('|------|-------|-----------|---------|')
        for gate_name, gr in sw_result.get('gates', {}).items():
            status = 'PASS' if gr['pass'] else '**FAIL**'
            md.append('| %s | %.2f | %s | %s |' % (gate_name, gr['value'], gr['threshold'], status))
        md.append('')
        md.append('**All gates**: %s' % ('PASS' if sw_result['all_gates_pass'] else 'FAIL'))
    else:
        md.append('No stable winners found.')
    md.append('')

    # Footer
    md.append('---')
    md.append('*Generated by strategies/hf/screening/run_part2_coin_stability_001.py at %s*' % (
        datetime.now().strftime('%Y-%m-%d %H:%M')))

    md_path = ROOT / 'reports' / 'hf' / REPORT_MD
    md_path.write_text('\n'.join(md))
    print('[Report] MD:   %s' % md_path)

    # Final summary
    print('\n' + '=' * 70)
    print('  C8-E COMPLETE: Coin Stability / Edge Persistence')
    print('  Coins with trades: %d' % stability_summary['total_coins_with_trades'])
    print('  Stable winners: %d (%s)' % (
        stability_summary['n_stable_winners'],
        ', '.join(stability_summary['stable_winners'][:5])))
    print('  SW profit share: %.1f%%' % conc['stable_winner_profit_share_pct'])
    print('  Edge persistence: %s' % report['verdict']['edge_persistence'])
    print('  Full 295 gates: %s' % report['verdict']['full_295_gates'])
    print('  SW-only gates:  %s' % report['verdict']['sw_only_gates'])
    print('  Runtime: %.1fs' % elapsed)
    print('=' * 70)


if __name__ == '__main__':
    main()
