#!/usr/bin/env python3
"""
Multi-Exchange Validation Runner
=================================
Run the 24-combo backtest matrix (2 configs × 4 regimes × 3 sizes) on any exchange.

Uses the exchange-parametric infrastructure:
- exchange_config.py for fee defaults + CLI overrides
- universe_tiering_{exchange}_001.json for coin universe
- candle_cache_1h_{exchange}.json for OHLCV data
- {exchange}_orderbook_costs_001.json for measured OB regimes
- orderbook_analysis.py with exchange parameter for regime building

Reuses all proven logic from run_part2_measured_cost_rerun.py:
- Same analyze_combination() flow
- Same 7 STRICT gates (G1-G6 + G8)
- Same fill model (bar-structure, maker regimes only)
- Same walk-forward 5-fold

Key differences from MEXC-specific runner:
- NO hardcoded EXCLUDED_COINS (report net-negatives separately instead)
- Exchange-parametric paths for all data files
- Fee snapshot embedded in report for reproducibility
- Optional --exclude-file for per-exchange exclusion lists

Usage:
    python -m strategies.hf.screening.run_multi_exchange_validation --exchange bybit
    python -m strategies.hf.screening.run_multi_exchange_validation --exchange bybit --dry-run
    python -m strategies.hf.screening.run_multi_exchange_validation --exchange mexc  # replicate MEXC
    python -m strategies.hf.screening.run_multi_exchange_validation --exchange bybit --config v5 --skip-fill-model
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

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
from strategies.hf.screening.costs_mexc_v2 import (
    register_regime, COST_REGIMES,
)
from strategies.hf.screening.fill_model_v3 import full_fill_model_v3
from strategies.hf.screening.orderbook_analysis import (
    load_snapshots, compute_distributions, build_measured_regimes,
)
from strategies.hf.screening.exchange_config import (
    add_exchange_args, build_fee_snapshot, get_exchange,
)

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168  # 24 * 7
BARS_PER_DAY = 24

CONFIGS = {
    'v5': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
    'sl7': {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10},
}

REGIMES_TO_TEST = [
    'measured_ob_maker_p50', 'measured_ob_maker_p90',
    'measured_ob_taker_p50', 'measured_ob_taker_p90',
]

SIZES = [200, 500, 2000]


# ============================================================
# Data loading (exchange-parametric)
# ============================================================

def load_candle_cache_exchange(exchange_id, require_data=False):
    """Load 1H candle cache for a specific exchange.

    Tries:
    1. data/candle_cache_1h_{exchange}.json (merged cache)
    2. data/cache_parts_hf/1h/{exchange}/ (per-coin parts)
    3. For MEXC backward compat: data/candle_cache_1h.json
    """
    # 1. Exchange-specific merged cache
    cache_path = ROOT / 'data' / f'candle_cache_1h_{exchange_id}.json'
    if cache_path.exists():
        print(f'[Load] Reading {cache_path.name}...')
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        print(f'[Load] {len(coins_data)} coins loaded (merged cache)')
        return coins_data

    # 2. Per-coin parts
    parts_dir = ROOT / 'data' / 'cache_parts_hf' / '1h' / exchange_id
    if parts_dir.exists():
        print(f'[Load] Loading from per-coin parts: {parts_dir}')
        coins_data = {}
        for coin_file in sorted(parts_dir.glob('*.json')):
            if coin_file.name == 'manifest.json':
                continue
            symbol = coin_file.stem.replace('_', '/')
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
        if coins_data:
            print(f'[Load] {len(coins_data)} coins loaded (from part files)')
            return coins_data

    # 3. MEXC backward compat: legacy path without exchange suffix
    if exchange_id == 'mexc':
        legacy_path = ROOT / 'data' / 'candle_cache_1h.json'
        if legacy_path.exists():
            print(f'[Load] Reading legacy {legacy_path.name}...')
            with open(legacy_path) as f:
                data = json.load(f)
            coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
            print(f'[Load] {len(coins_data)} coins loaded (legacy MEXC cache)')
            return coins_data

    if require_data:
        print(f'[ERROR] No candle cache found for {exchange_id}')
        print(f'  Expected: {cache_path}')
        print(f'  Or parts: {parts_dir}/')
        print(f'  Run: python -m strategies.hf.screening.candle_downloader --exchange {exchange_id}')
        sys.exit(1)

    print(f'[SKIP] No 1H candle cache found for {exchange_id}.')
    return None


def load_universe_tiering_exchange(exchange_id, require_data=False):
    """Load universe tiering for a specific exchange."""
    path = ROOT / 'reports' / 'hf' / f'universe_tiering_{exchange_id}_001.json'
    if not path.exists():
        # MEXC backward compat
        if exchange_id == 'mexc':
            legacy = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
            if legacy.exists():
                path = legacy

    if not path.exists():
        if require_data:
            print(f'[ERROR] Tiering not found: {path}')
            print(f'  Run: python -m strategies.hf.screening.universe_builder --exchange {exchange_id}')
            sys.exit(1)
        print(f'[SKIP] No tiering file found for {exchange_id}.')
        return None

    with open(path) as f:
        return json.load(f)


def build_tier_coins(tiering, available_coins):
    """Build tier coin lists from tiering data, filtered by available candle data."""
    tier_coins = {'tier1': [], 'tier2': []}
    tb = tiering.get('tier_breakdown', {})
    if tb:
        for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
            if tier_num in tb:
                coins = tb[tier_num].get('coins', [])
                tier_coins[tier_key] = [c for c in coins if c in available_coins]
        if tier_coins['tier1'] or tier_coins['tier2']:
            return tier_coins

    # Fallback for older schema
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


def load_excluded_coins(exchange_id, exclude_file=None):
    """Load exchange-specific exclusion list.

    For MEXC: use the hardcoded 21 net-negative coins from MEXC validation.
    For other exchanges: no exclusion (report net-negatives separately).
    Optional --exclude-file overrides.
    """
    if exclude_file:
        path = Path(exclude_file)
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(data)
            if isinstance(data, dict):
                return set(data.get('coins', []))
        print(f'[WARN] Exclude file not found: {exclude_file}')
        return set()

    # MEXC: use known net-negative coins
    if exchange_id == 'mexc':
        return {
            'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
            'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
            'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
            'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
            'WMTX/USD',
        }

    # Other exchanges: no exclusion
    return set()


# ============================================================
# Metric computation (identical to run_part2_exec_realism_002)
# ============================================================

def compute_metrics(trades, total_bars, initial_capital=2000.0):
    """Compute standard backtest metrics."""
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
        tfee = t.get('_fee_per_side', 0.00125)
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


def compute_max_gap(trades, total_bars):
    """Compute max gap between trades in days."""
    if len(trades) < 2:
        gap = total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
        return total_bars, round(gap, 2)
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    mg = st[0].get('entry_bar', 50) - 50
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i-1].get('exit_bar', 0)
        if g > mg:
            mg = g
    eg = total_bars - st[-1].get('exit_bar', 0)
    if eg > mg:
        mg = eg
    max_gap_days = mg / BARS_PER_DAY
    return mg, round(max_gap_days, 2)


def compute_fold_concentration(fold_pnls):
    """Top-1 fold concentration among positive folds."""
    positive_pnls = [max(0, p) for p in fold_pnls]
    total_pos = sum(positive_pnls)
    if total_pos <= 0:
        return 1.0
    return max(positive_pnls) / total_pos


def evaluate_gates_strict(metrics, stress_metrics, wf_folds_positive,
                          max_gap_days, top1_fold_conc):
    """Evaluate 7 STRICT gates (G1-G6 + G8)."""
    gates = {
        'G1_trades_per_week': {
            'value': round(metrics['trades_per_week'], 2),
            'threshold': '>=10/wk',
            'pass': metrics['trades_per_week'] >= 10,
        },
        'G2_max_gap_days': {
            'value': max_gap_days,
            'threshold': '<=2.5d',
            'pass': max_gap_days <= 2.5,
        },
        'G3_exp_per_week': {
            'value': round(metrics['exp_per_week'], 4),
            'threshold': '>$0',
            'pass': metrics['exp_per_week'] > 0,
        },
        'G4_stress_exp_per_week': {
            'value': round(stress_metrics['exp_per_week'], 4),
            'threshold': '>$0 (stress 2x)',
            'pass': stress_metrics['exp_per_week'] > 0,
        },
        'G5_max_dd_pct': {
            'value': round(metrics['dd'], 1),
            'threshold': '<=20%',
            'pass': metrics['dd'] <= 20,
        },
        'G6_wf_folds_positive': {
            'value': wf_folds_positive,
            'threshold': '>=4/5',
            'pass': wf_folds_positive >= 4,
        },
        'G8_top1_fold_conc': {
            'value': round(top1_fold_conc, 4),
            'threshold': '<0.35',
            'pass': top1_fold_conc < 0.35,
        },
    }
    all_pass = all(g['pass'] for g in gates.values())
    failed = [k for k, g in gates.items() if not g['pass']]
    passed = [k for k, g in gates.items() if g['pass']]
    return gates, all_pass, failed, passed


def tier_pnl_breakdown(trades):
    """P&L breakdown by tier."""
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


# ============================================================
# Size-specific regime adjustment (from run_part2_measured_cost_rerun)
# ============================================================

def build_size_specific_regime(base_regime, distributions, size):
    """Adjust taker regime slippage based on trade size."""
    import copy
    regime = copy.deepcopy(base_regime)
    exec_mode = regime.get('execution_mode', '')

    if 'maker' in exec_mode:
        return regime

    size_key = f'slippage_{size}_bps'
    pct_label = regime.get('percentile', 'p50')

    for tier_key in ('tier1', 'tier2'):
        tier_dist = distributions.get(tier_key, {})
        slip_dist = tier_dist.get(size_key, {})
        new_slip = slip_dist.get(pct_label, 0.0)

        tier = regime[tier_key]
        tier['slippage_bps'] = round(new_slip, 1)

        total = (
            tier.get('exchange_fee_bps', 0.0)
            + tier.get('spread_bps', 0.0)
            + tier['slippage_bps']
            + tier.get('adverse_selection_bps', 0.0)
        )
        tier['total_per_side_bps'] = round(total, 1)

    regime['description'] += f' (size=${size})'
    return regime


def get_half_spread_for_fill(distributions, tier_key, exec_mode):
    """Determine half_spread_bps for the fill model."""
    if 'taker' in exec_mode:
        return 0.0
    tier_dist = distributions.get(tier_key, {})
    spread_dist = tier_dist.get('spread_bps', {})
    spread_p50 = spread_dist.get('p50', 0.0)
    return spread_p50 / 2.0


# ============================================================
# Stress fee helper
# ============================================================

def compute_stress_fees(regime_info, multiplier=2.0):
    """Compute stress fees by multiplying a regime's per-side fees."""
    t1_total = regime_info.get('tier1', {}).get('total_per_side_bps', 0.0)
    t2_total = regime_info.get('tier2', {}).get('total_per_side_bps', 0.0)
    return {
        'tier1_fee': t1_total * multiplier / 10000.0,
        'tier2_fee': t2_total * multiplier / 10000.0,
        'tier1_bps': round(t1_total * multiplier, 1),
        'tier2_bps': round(t2_total * multiplier, 1),
    }


# ============================================================
# Backtest runners
# ============================================================

def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                 market_ctx, t1_fee, t2_fee, params, initial_capital=2000.0):
    """Run backtests for T1 and T2 separately, merge trade lists."""
    enriched = {**params, '__market__': market_ctx}
    all_trades = []

    if t1_coins:
        bt_t1 = run_backtest(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t1.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = t1_fee
        all_trades.extend(bt_t1.trade_list)

    if t2_coins:
        bt_t2 = run_backtest(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, fee=t2_fee, max_pos=1,
            initial_capital=initial_capital,
        )
        for t in bt_t2.trade_list:
            t['_tier'] = 'tier2'
            t['_fee_per_side'] = t2_fee
        all_trades.extend(bt_t2.trade_list)

    return all_trades


def run_combined_wf(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                    market_ctx, t1_fee, t2_fee, params, n_folds=5,
                    initial_capital=2000.0):
    """Run walk-forward for T1 and T2 separately, merge fold trades."""
    enriched = {**params, '__market__': market_ctx}
    fold_trades = {}

    if t1_coins:
        t1_results = walk_forward(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, n_folds=n_folds,
            fee=t1_fee, max_pos=1, initial_capital=initial_capital,
        )
        for idx, fold_bt in enumerate(t1_results):
            if idx not in fold_trades:
                fold_trades[idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = 'tier1'
                t['_fee_per_side'] = t1_fee
            fold_trades[idx].extend(fold_bt.trade_list)

    if t2_coins:
        t2_results = walk_forward(
            data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t2_indicators, n_folds=n_folds,
            fee=t2_fee, max_pos=1, initial_capital=initial_capital,
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
# Single combination analysis
# ============================================================

def analyze_combination(
    config_name, config_params, regime_name, regime, size,
    data, t1_coins, t2_coins, t1_indicators, t2_indicators,
    market_ctx, total_bars, distributions, skip_fill_model=False,
):
    """Run full analysis for one config x regime x size combination."""
    t_start = time.time()
    exec_mode = regime.get('execution_mode', '')

    t1_fee = regime['tier1']['total_per_side_bps'] / 10000.0
    t2_fee = regime['tier2']['total_per_side_bps'] / 10000.0

    label = f'{config_name}/{regime_name}/${size}'
    print(f'  [{label}] fees T1={regime["tier1"]["total_per_side_bps"]}bps '
          f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    # Baseline backtest
    print(f'  [{label}] Running baseline backtest...')
    trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, initial_capital=size,
    )
    pre_fill_count = len(trades)
    pre_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    # Fill model
    fill_result = None
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)

        t1_trades = [t for t in trades if t.get('_tier') == 'tier1']
        t2_trades = [t for t in trades if t.get('_tier') == 'tier2']
        surviving = []

        fill_summary_combined = {
            'total': len(trades), 'filled': 0, 'missed': 0,
            'fill_rate': 0.0, 'tier_detail': {},
        }

        if t1_trades and hs_t1 > 0:
            fm_t1 = full_fill_model_v3(t1_trades, data, half_spread_bps=hs_t1)
            surviving.extend(fm_t1['trades'])
            fill_summary_combined['tier_detail']['tier1'] = fm_t1['fill_summary']
            fill_summary_combined['filled'] += fm_t1['fill_summary']['filled']
            fill_summary_combined['missed'] += fm_t1['fill_summary']['missed']
        elif t1_trades:
            surviving.extend(t1_trades)
            fill_summary_combined['filled'] += len(t1_trades)

        if t2_trades and hs_t2 > 0:
            fm_t2 = full_fill_model_v3(t2_trades, data, half_spread_bps=hs_t2)
            surviving.extend(fm_t2['trades'])
            fill_summary_combined['tier_detail']['tier2'] = fm_t2['fill_summary']
            fill_summary_combined['filled'] += fm_t2['fill_summary']['filled']
            fill_summary_combined['missed'] += fm_t2['fill_summary']['missed']
        elif t2_trades:
            surviving.extend(t2_trades)
            fill_summary_combined['filled'] += len(t2_trades)

        total_fm = fill_summary_combined['filled'] + fill_summary_combined['missed']
        fill_summary_combined['fill_rate'] = (
            fill_summary_combined['filled'] / total_fm if total_fm > 0 else 0.0
        )
        trades = surviving
        fill_result = fill_summary_combined
    elif not skip_fill_model and 'taker' in exec_mode:
        fill_result = {
            'total': len(trades), 'filled': len(trades), 'missed': 0,
            'fill_rate': 1.0, 'note': 'taker mode: market orders always fill',
        }

    post_fill_count = len(trades)
    post_fill_pnl = sum(t['pnl'] for t in trades) if trades else 0.0

    m = compute_metrics(trades, total_bars, initial_capital=size)
    tb = tier_pnl_breakdown(trades)

    if len(trades) >= 2:
        max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)
    else:
        max_gap_days = total_bars / BARS_PER_DAY if total_bars > 0 else 999.0
        max_gap_bars = total_bars

    print(f'    Baseline: {pre_fill_count}tr -> {post_fill_count}tr (post-fill) '
          f'PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
          f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    # Stress 2x
    stress_fees = compute_stress_fees(regime, 2.0)
    print(f'  [{label}] Running stress 2x backtest '
          f'(T1={stress_fees["tier1_bps"]}bps, T2={stress_fees["tier2_bps"]}bps)...')
    stress_trades = run_combined(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, stress_fees['tier1_fee'], stress_fees['tier2_fee'],
        config_params, initial_capital=size,
    )

    # Apply fill model to stress trades too
    if not skip_fill_model and 'maker' in exec_mode:
        hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
        hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)

        st1 = [t for t in stress_trades if t.get('_tier') == 'tier1']
        st2 = [t for t in stress_trades if t.get('_tier') == 'tier2']
        stress_surviving = []
        if st1 and hs_t1 > 0:
            fm = full_fill_model_v3(st1, data, half_spread_bps=hs_t1)
            stress_surviving.extend(fm['trades'])
        elif st1:
            stress_surviving.extend(st1)
        if st2 and hs_t2 > 0:
            fm = full_fill_model_v3(st2, data, half_spread_bps=hs_t2)
            stress_surviving.extend(fm['trades'])
        elif st2:
            stress_surviving.extend(st2)
        stress_trades = stress_surviving

    sm = compute_metrics(stress_trades, total_bars, initial_capital=size)
    print(f'    Stress: {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.2f}')

    # Walk-Forward 5-fold
    print(f'  [{label}] Running walk-forward 5-fold...')
    fold_trades = run_combined_wf(
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_ctx, t1_fee, t2_fee, config_params, n_folds=5,
        initial_capital=size,
    )

    # Apply fill model per fold for maker regimes
    wf_folds_positive = 0
    fold_pnls = []
    fold_details = []
    for fi in sorted(fold_trades.keys()):
        fold_tr = fold_trades[fi]

        if not skip_fill_model and 'maker' in exec_mode:
            hs_t1 = get_half_spread_for_fill(distributions, 'tier1', exec_mode)
            hs_t2 = get_half_spread_for_fill(distributions, 'tier2', exec_mode)

            ft1 = [t for t in fold_tr if t.get('_tier') == 'tier1']
            ft2 = [t for t in fold_tr if t.get('_tier') == 'tier2']
            fold_surviving = []
            if ft1 and hs_t1 > 0:
                fm = full_fill_model_v3(ft1, data, half_spread_bps=hs_t1, seed=42 + fi)
                fold_surviving.extend(fm['trades'])
            elif ft1:
                fold_surviving.extend(ft1)
            if ft2 and hs_t2 > 0:
                fm = full_fill_model_v3(ft2, data, half_spread_bps=hs_t2, seed=42 + fi)
                fold_surviving.extend(fm['trades'])
            elif ft2:
                fold_surviving.extend(ft2)
            fold_tr = fold_surviving

        fpnl = sum(t['pnl'] for t in fold_tr)
        fn = len(fold_tr)
        pos = fpnl > 0
        if pos:
            wf_folds_positive += 1
        fold_pnls.append(fpnl)
        fold_details.append({
            'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos,
        })

    top1_fold_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    print(f'    WF: {wf_folds_positive}/5 folds positive, top1 conc={top1_fold_conc:.3f}')

    # Gate evaluation
    gates, all_pass, failed, passed = evaluate_gates_strict(
        m, sm, wf_folds_positive, max_gap_days, top1_fold_conc,
    )
    gate_count = sum(1 for g in gates.values() if g['pass'])
    total_gates = len(gates)

    elapsed = time.time() - t_start
    status = 'ALL PASS' if all_pass else f'FAIL: {", ".join(failed)}'
    print(f'    Gates: {gate_count}/{total_gates} {status} ({elapsed:.1f}s)')

    return {
        'config': config_name,
        'config_params': config_params,
        'regime': regime_name,
        'regime_description': regime.get('description', ''),
        'execution_mode': exec_mode,
        'size': size,
        'fees': {
            'tier1_bps': regime['tier1']['total_per_side_bps'],
            'tier2_bps': regime['tier2']['total_per_side_bps'],
            'tier1_fee': t1_fee,
            'tier2_fee': t2_fee,
        },
        'stress_fees': {
            'tier1_bps': stress_fees['tier1_bps'],
            'tier2_bps': stress_fees['tier2_bps'],
        },
        'pre_fill': {
            'trades': pre_fill_count,
            'pnl': round(pre_fill_pnl, 2),
        },
        'post_fill': {
            'trades': post_fill_count,
            'pnl': round(post_fill_pnl, 2),
        },
        'fill_model': fill_result,
        'baseline': m,
        'tier_breakdown': tb,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'stress_2x': {
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
        },
        'walk_forward': {
            'folds_positive': wf_folds_positive,
            'fold_details': fold_details,
            'top1_fold_conc': round(top1_fold_conc, 4),
        },
        'gates': gates,
        'all_gates_pass': all_pass,
        'gates_passed': gate_count,
        'gates_total': total_gates,
        'failed_gates': failed,
        'passed_gates': passed,
        'runtime_s': round(elapsed, 1),
    }


# ============================================================
# Markdown report
# ============================================================

def build_md(report, elapsed, commit, exchange_id, fee_snapshot,
             n_t1, n_t2, n_excluded, total_bars, total_weeks):
    md = []
    md.append(f'# {exchange_id.upper()} Multi-Exchange Validation Report')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Exchange**: {exchange_id.upper()}')
    md.append(f'**Fees**: maker={fee_snapshot["maker_fee_bps"]}bps, '
              f'taker={fee_snapshot["taker_fee_bps"]}bps '
              f'({fee_snapshot.get("account_tier", "default")})')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins '
              f'(excl {n_excluded})')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5/sl7 variants')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append(f'**Matrix**: {report["run_header"]["matrix_description"]}')
    md.append('')

    # Objective
    md.append('## Objective')
    md.append('')
    md.append(f'Test H20 VWAP_DEVIATION signal on {exchange_id.upper()} under measured '
              f'orderbook cost regimes with 7 STRICT gates.')
    md.append('')

    # Summary scoreboard
    md.append('## Summary Scoreboard')
    md.append('')
    md.append('| Config | Regime | Size | T1 bps | T2 bps | Pre-Fill | Post-Fill | PF | Exp/Wk | DD% | WF | Gates |')
    md.append('|--------|--------|------|--------|--------|----------|-----------|----|----|-----|----|----|')

    for r in report['combinations']:
        m = r['baseline']
        wf = r.get('walk_forward', {})
        wf_str = f'{wf.get("folds_positive", 0)}/5'
        fees = r.get('fees', {})
        pre = r.get('pre_fill', {})
        gate_info = r.get('gates_passed', '-')
        gate_total = r.get('gates_total', '-')
        if r.get('all_gates_pass'):
            gate_str = f'**{gate_info}/{gate_total}**'
        else:
            gate_str = f'{gate_info}/{gate_total}'
        md.append(
            f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
            f'| {fees.get("tier1_bps", "-")} | {fees.get("tier2_bps", "-")} '
            f'| {pre.get("trades", 0)} | {m["trades"]} '
            f'| {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} '
            f'| {m["dd"]:.1f} | {wf_str} | {gate_str} |'
        )
    md.append('')

    # Pass/fail summary
    passing = [r for r in report['combinations'] if r.get('all_gates_pass')]
    failing = [r for r in report['combinations'] if not r.get('all_gates_pass')]

    md.append('## Gate Results Summary')
    md.append('')
    md.append(f'- **Passing ALL gates**: {len(passing)}/{len(report["combinations"])}')
    if passing:
        md.append('')
        for r in passing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}')
    md.append('')
    if failing:
        md.append(f'- **Failing**: {len(failing)}/{len(report["combinations"])}')
        md.append('')
        for r in failing:
            md.append(f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                      f'fails {", ".join(r.get("failed_gates", []))}')
        md.append('')

    # Fill model impact
    maker_results = [r for r in report['combinations'] if 'maker' in r.get('execution_mode', '')]
    if maker_results:
        md.append('## Fill Model Impact (Maker Regimes)')
        md.append('')
        md.append('| Config | Regime | Size | Pre-Fill | Post-Fill | Fill Rate | Pre PnL | Post PnL |')
        md.append('|--------|--------|------|----------|-----------|-----------|---------|----------|')
        for r in maker_results:
            pre = r.get('pre_fill', {})
            post = r.get('post_fill', {})
            fm = r.get('fill_model', {})
            fr = fm.get('fill_rate', 1.0) if fm else 1.0
            md.append(
                f'| {r["config"]} | {r["regime"][:25]} | ${r["size"]} '
                f'| {pre.get("trades", 0)} | {post.get("trades", 0)} '
                f'| {fr:.1%} | ${pre.get("pnl", 0):.0f} | ${post.get("pnl", 0):.0f} |'
            )
        md.append('')

    # Per-combination detail
    for r in report['combinations']:
        md.append(f'### {r["config"]} / {r["regime"]} / ${r["size"]}')
        md.append('')
        md.append(f'- **Execution mode**: {r.get("execution_mode", "?")}')
        md.append(f'- **Fees**: T1={r["fees"]["tier1_bps"]}bps, T2={r["fees"]["tier2_bps"]}bps per side')

        m = r['baseline']
        md.append(f'- **Baseline**: {m["trades"]}tr, PF={m["pf"]:.3f}, WR={m["wr"]:.1f}%, '
                  f'P&L=${m["pnl"]:.0f}, Exp/Wk=${m["exp_per_week"]:.2f}, DD={m["dd"]:.1f}%')

        pre = r.get('pre_fill', {})
        post = r.get('post_fill', {})
        if pre.get('trades', 0) != post.get('trades', 0):
            md.append(f'- **Fill model**: {pre["trades"]} -> {post["trades"]} trades '
                      f'(PnL ${pre["pnl"]:.0f} -> ${post["pnl"]:.0f})')

        gap = r.get('max_gap', {})
        md.append(f'- **Max Gap**: {gap.get("days", "?")}d ({gap.get("bars", "?")} bars)')

        s = r.get('stress_2x', {})
        md.append(f'- **Stress 2x**: {s.get("trades", "?")}tr, PF={s.get("pf", 0):.3f}, '
                  f'Exp/Wk=${s.get("exp_per_week", 0):.2f}')

        wf = r.get('walk_forward', {})
        md.append(f'- **Walk-Forward**: {wf.get("folds_positive", 0)}/5 folds positive, '
                  f'top1 conc={wf.get("top1_fold_conc", 0):.3f}')
        md.append('')

        # Gate table
        md.append('| Gate | Value | Threshold | Verdict |')
        md.append('|------|-------|-----------|---------|')
        for gname, ginfo in r['gates'].items():
            verdict = 'PASS' if ginfo['pass'] else '**FAIL**'
            md.append(f'| {gname} | {ginfo["value"]} | {ginfo["threshold"]} | {verdict} |')
        md.append('')

        # Fold details
        fold_details = wf.get('fold_details', [])
        if fold_details:
            md.append('| Fold | Trades | P&L | Positive? |')
            md.append('|------|--------|-----|-----------|')
            for fd in fold_details:
                md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.0f} | '
                          f'{"Yes" if fd["positive"] else "No"} |')
            md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_multi_exchange_validation.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Multi-Exchange Validation: 24-combo backtest matrix with 7 STRICT gates',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if data missing')
    parser.add_argument('--config', choices=['v5', 'sl7', 'both'], default='both',
                        help='Config to test (default: both)')
    parser.add_argument('--skip-fill-model', action='store_true',
                        help='Skip fill model for faster iteration')
    parser.add_argument('--exclude-file', type=str, default=None,
                        help='JSON file with coins to exclude (default: per-exchange)')
    parser.add_argument('--output-label', type=str, default='001',
                        help='Output file label (default: 001)')

    add_exchange_args(parser)
    args = parser.parse_args()

    exchange_cfg = get_exchange(args.exchange)
    fee_snap = build_fee_snapshot(args)
    exchange_id = exchange_cfg.id

    sep = '=' * 70
    print(sep)
    print(f'  Multi-Exchange Validation: {exchange_id.upper()}')
    print(f'  H20 VWAP_DEVIATION v5/sl7 | Measured OB Regimes | STRICT Gates')
    print(f'  Fees: maker={fee_snap.maker_fee_bps}bps taker={fee_snap.taker_fee_bps}bps')
    print(sep)
    t0 = time.time()

    # Commit hash
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # Select configs
    if args.config == 'both':
        configs_to_test = CONFIGS
    else:
        configs_to_test = {args.config: CONFIGS[args.config]}

    # --- Load orderbook data and build measured regimes ---
    print(f'[Orderbook] Loading measured cost data for {exchange_id}...')
    distributions = None

    # Try exchange-specific OB report first
    ob_report_path = ROOT / 'reports' / 'hf' / f'{exchange_id}_orderbook_costs_{args.output_label}.json'
    # MEXC backward compat
    if not ob_report_path.exists() and exchange_id == 'mexc':
        ob_report_path = ROOT / 'reports' / 'hf' / 'mexc_orderbook_costs_001.json'

    ob_input_path = ROOT / 'data' / 'orderbook_snapshots' / f'{exchange_id}_orderbook_{args.output_label}.jsonl'
    # MEXC backward compat
    if not ob_input_path.exists() and exchange_id == 'mexc':
        ob_input_path = ROOT / 'data' / 'orderbook_snapshots' / 'mexc_orderbook_001.jsonl'

    if ob_report_path.exists():
        print(f'  Loading from report: {ob_report_path}')
        with open(ob_report_path) as f:
            ob_report = json.load(f)
        distributions = ob_report.get('distributions', {})
        measured_regimes = ob_report.get('regimes', {})
        print(f'  Found {len(measured_regimes)} regimes from report')
    elif ob_input_path.exists():
        print(f'  Loading raw snapshots from: {ob_input_path}')
        snapshots = load_snapshots(str(ob_input_path))
        distributions = compute_distributions(snapshots)
        measured_regimes = build_measured_regimes(
            distributions,
            exchange=exchange_cfg,
            fee_snapshot=fee_snap,
        )
        print(f'  Built {len(measured_regimes)} regimes from raw data')
    else:
        print(f'[ERROR] No orderbook data found for {exchange_id}')
        print(f'  Expected: {ob_report_path}')
        print(f'  Or raw: {ob_input_path}')
        print(f'  Run: python -m strategies.hf.screening.orderbook_collector_generic --exchange {exchange_id}')
        print(f'  Then: python -m strategies.hf.screening.orderbook_analysis --exchange {exchange_id}')
        sys.exit(1)

    # Register measured regimes
    for name, regime in measured_regimes.items():
        if name in REGIMES_TO_TEST:
            register_regime(name, regime)
            print(f'  Registered: {name} -> '
                  f'T1={regime["tier1"]["total_per_side_bps"]}bps '
                  f'T2={regime["tier2"]["total_per_side_bps"]}bps')

    missing = [r for r in REGIMES_TO_TEST if r not in COST_REGIMES]
    if missing:
        print(f'[ERROR] Missing regimes: {missing}')
        print(f'  Available: {list(COST_REGIMES.keys())}')
        sys.exit(1)

    # --- Load candle data ---
    data = load_candle_cache_exchange(exchange_id, require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering_exchange(exchange_id, require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # Apply exclusion
    excluded = load_excluded_coins(exchange_id, args.exclude_file)
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in excluded],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in excluded],
    }

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    n_excluded = len(excluded)
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins '
          f'(excl {n_excluded})')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    n_configs = len(configs_to_test)
    n_regimes = len(REGIMES_TO_TEST)
    n_sizes = len(SIZES)
    n_combos = n_configs * n_regimes * n_sizes

    if args.dry_run:
        print(f'\n--- DRY RUN ({exchange_id.upper()}) ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  Excluded: {n_excluded} coins')
        print(f'  Configs: {list(configs_to_test.keys())}')
        print(f'  Regimes: {REGIMES_TO_TEST}')
        print(f'  Sizes: {SIZES}')
        print(f'  Total combinations: {n_combos}')
        print(f'  Fees: maker={fee_snap.maker_fee_bps}bps taker={fee_snap.taker_fee_bps}bps')
        print(f'  Each: baseline + stress 2x + WF 5-fold + fill model + gates')
        print(f'  Skip fill model: {args.skip_fill_model}')
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
    # Run all combinations
    # ============================================================
    all_results = []
    combo_idx = 0

    for config_name, config_params in configs_to_test.items():
        for regime_name in REGIMES_TO_TEST:
            base_regime = measured_regimes[regime_name]

            for size in SIZES:
                combo_idx += 1
                print(f'\n{sep}')
                print(f'  [{exchange_id.upper()}] COMBINATION {combo_idx}/{n_combos}: '
                      f'{config_name} / {regime_name} / ${size}')
                print(sep)

                if distributions is not None:
                    regime = build_size_specific_regime(
                        base_regime, distributions, size,
                    )
                else:
                    regime = base_regime

                result = analyze_combination(
                    config_name=config_name,
                    config_params=config_params,
                    regime_name=regime_name,
                    regime=regime,
                    size=size,
                    data=data,
                    t1_coins=t1_coins,
                    t2_coins=t2_coins,
                    t1_indicators=t1_indicators,
                    t2_indicators=t2_indicators,
                    market_ctx=market_context,
                    total_bars=total_bars,
                    distributions=distributions,
                    skip_fill_model=args.skip_fill_model,
                )
                all_results.append(result)

    elapsed = time.time() - t0

    # ============================================================
    # Verdict
    # ============================================================
    verdict_lines = []
    passing = [r for r in all_results if r.get('all_gates_pass')]
    failing = [r for r in all_results if not r.get('all_gates_pass')]

    verdict_lines.append(
        f'**{exchange_id.upper()} — Combinations passing ALL STRICT gates**: '
        f'{len(passing)}/{len(all_results)}'
    )
    verdict_lines.append('')

    if passing:
        verdict_lines.append('**Passing combinations**:')
        for r in passing:
            m = r['baseline']
            verdict_lines.append(
                f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                f'{m["trades"]}tr PF={m["pf"]:.3f} Exp/wk=${m["exp_per_week"]:.2f}'
            )
        verdict_lines.append('')

    if failing:
        verdict_lines.append('**Failing combinations**:')
        for r in failing:
            verdict_lines.append(
                f'  - {r["config"]}/{r["regime"]}/${r["size"]}: '
                f'fails {", ".join(r.get("failed_gates", []))}'
            )
        verdict_lines.append('')

    # Maker vs taker comparison
    verdict_lines.append(f'**Maker vs Taker** (v5 config, $200 size):')
    for pct in ('p50', 'p90'):
        maker = next((r for r in all_results
                      if r['config'] == 'v5' and r['size'] == 200
                      and f'maker_{pct}' in r['regime']), None)
        taker = next((r for r in all_results
                      if r['config'] == 'v5' and r['size'] == 200
                      and f'taker_{pct}' in r['regime']), None)
        if maker and taker:
            mm = maker['baseline']
            tm = taker['baseline']
            verdict_lines.append(
                f'  {pct}: maker {mm["trades"]}tr Exp/wk=${mm["exp_per_week"]:.2f} '
                f'vs taker {tm["trades"]}tr Exp/wk=${tm["exp_per_week"]:.2f}'
            )
    verdict_lines.append('')

    # Conclusion
    if len(passing) == len(all_results):
        verdict_lines.append(
            f'**CONCLUSION**: Strategy passes ALL STRICT gates on {exchange_id.upper()} '
            f'under ALL measured cost regimes and trade sizes.'
        )
    elif len(passing) > len(all_results) * 0.5:
        verdict_lines.append(
            f'**CONCLUSION**: Strategy passes STRICT gates in {len(passing)}/{len(all_results)} '
            f'combinations on {exchange_id.upper()}. Review failing combinations.'
        )
    else:
        verdict_lines.append(
            f'**CONCLUSION**: Strategy fails STRICT gates in majority of combinations '
            f'({len(failing)}/{len(all_results)}) on {exchange_id.upper()}. '
            f'Cost structure may be prohibitive.'
        )

    # ============================================================
    # JSON Report
    # ============================================================
    report = {
        'run_header': {
            'task': f'part2_{exchange_id}_validation_{args.output_label}',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'exchange': exchange_id,
            'fee_snapshot': fee_snap.to_dict(),
            'hypothesis': 'H20_VWAP_DEVIATION',
            'configs': {k: v for k, v in configs_to_test.items()},
            'regimes_tested': REGIMES_TO_TEST,
            'sizes': SIZES,
            'matrix_description': (
                f'{n_configs} configs x {n_regimes} regimes x {n_sizes} sizes '
                f'= {n_combos} combinations'
            ),
            'universe': f'T1({n_t1})+T2({n_t2}) [excl {n_excluded}]',
            'universe_total': n_total,
            'excluded_count': n_excluded,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
            'fill_model': 'fill_model_v3 (bar-structure, maker regimes only)',
            'skip_fill_model': args.skip_fill_model,
            'strict_gates': {
                'G1': '>=10 trades/week',
                'G2': '<=2.5 days max gap',
                'G3': '>$0 exp/week (market)',
                'G4': '>$0 exp/week (stress 2x)',
                'G5': '<=20% max DD',
                'G6': '>=4/5 WF folds positive',
                'G8': '<35% top-1 fold concentration',
            },
        },
        'measured_regimes': {
            name: {
                'description': regime.get('description', ''),
                'execution_mode': regime.get('execution_mode', ''),
                'tier1_total_bps': regime.get('tier1', {}).get('total_per_side_bps', 0),
                'tier2_total_bps': regime.get('tier2', {}).get('total_per_side_bps', 0),
            }
            for name, regime in measured_regimes.items()
            if name in REGIMES_TO_TEST
        },
        'combinations': all_results,
        'verdict_lines': verdict_lines,
        'summary': {
            'passing': len(passing),
            'failing': len(failing),
            'total': len(all_results),
            'passing_combos': [
                f'{r["config"]}/{r["regime"]}/${r["size"]}' for r in passing
            ],
        },
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f'part2_{exchange_id}_measured_cost_{args.output_label}.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md_text = build_md(
        report, elapsed, commit, exchange_id, fee_snap.to_dict(),
        n_t1, n_t2, n_excluded, total_bars, total_weeks,
    )
    md_path = out_dir / f'part2_{exchange_id}_measured_cost_{args.output_label}.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{sep}')
    print(f'  {exchange_id.upper()} VALIDATION COMPLETE')
    print(sep)

    for r in all_results:
        m = r['baseline']
        g = r.get('gates_passed', '?')
        gt = r.get('gates_total', '?')
        ap = r.get('all_gates_pass', False)
        pre = r.get('pre_fill', {}).get('trades', '?')
        post = m['trades']
        status = 'ALL PASS' if ap else f'FAIL ({", ".join(r.get("failed_gates", []))})'
        print(f'  {r["config"]:4s} {r["regime"]:28s} ${r["size"]:>5}  '
              f'{pre}->{post}tr  PF={m["pf"]:.3f}  '
              f'Exp/wk=${m["exp_per_week"]:.2f}  DD={m["dd"]:.1f}%  '
              f'Gates={g}/{gt} {status}')

    print(f'\n  Passing: {len(passing)}/{len(all_results)}')
    print(f'  Runtime: {elapsed:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
