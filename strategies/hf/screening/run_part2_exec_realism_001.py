#!/usr/bin/env python3
"""
Part 2: Execution Realism Upgrade (P0-3)
=========================================
Agent C7-B: Test the H20 VWAP_DEVIATION v5 signal under 3 execution regimes
that model progressively more realistic fill assumptions.

Regimes:
  1. Market Conservative: P90 cost model (15.6/41.4 bps per side)
  2. Hybrid Realistic: 60% maker entries + 40% taker timeout; 30% maker exits + 70% taker
  3. Adverse Selection: Winners get 5bps/10bps extra cost (worse fills on profitable trades)

STRICT gate thresholds:
  G1: trades/week >= 10
  G2: max gap <= 2.5 days
  G3: exp/week > $0 (market)
  G4: exp/week > $0 (stress 2x)
  G5: max DD <= 20%
  G6: WF >= 4/5 folds positive
  G8: top-1 fold concentration < 35%

Output:
  reports/hf/part2_exec_realism_001.json
  reports/hf/part2_exec_realism_001.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_exec_realism_001.py
    python strategies/hf/screening/run_part2_exec_realism_001.py --dry-run
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
    get_harness_fee, get_cost_breakdown, COST_REGIMES, stress_multiplier,
)

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168   # 24 * 7
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


# ============================================================
# Data Loading
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
# Fee computation helpers
# ============================================================

def compute_regime_fees():
    """Compute per-side fees for each execution regime + tier."""
    regimes = {}

    # ----- Regime 1: Market Conservative (P90) -----
    t1_fee_p90 = get_harness_fee('mexc_market_p90', 'tier1')   # 0.00156
    t2_fee_p90 = get_harness_fee('mexc_market_p90', 'tier2')   # 0.00414
    regimes['market_conservative_p90'] = {
        'description': 'MEXC taker P90 spread+slippage',
        'tier1_fee': t1_fee_p90,
        'tier2_fee': t2_fee_p90,
        'tier1_bps': round(t1_fee_p90 * 10000, 1),
        'tier2_bps': round(t2_fee_p90 * 10000, 1),
    }

    # ----- Regime 2: Hybrid Realistic (maker+taker blend) -----
    t1_maker = get_harness_fee('mexc_maker', 'tier1')     # 0.00025
    t2_maker = get_harness_fee('mexc_maker', 'tier2')     # 0.00135
    t1_taker = get_harness_fee('mexc_market', 'tier1')    # 0.00125
    t2_taker = get_harness_fee('mexc_market', 'tier2')    # 0.00235

    # Entry: 60% maker + 40% taker; Exit: 30% maker + 70% taker
    t1_entry = 0.6 * t1_maker + 0.4 * t1_taker
    t1_exit  = 0.3 * t1_maker + 0.7 * t1_taker
    t1_hybrid = (t1_entry + t1_exit) / 2.0

    t2_entry = 0.6 * t2_maker + 0.4 * t2_taker
    t2_exit  = 0.3 * t2_maker + 0.7 * t2_taker
    t2_hybrid = (t2_entry + t2_exit) / 2.0

    regimes['hybrid_realistic'] = {
        'description': 'Hybrid: entry 60%maker+40%taker, exit 30%maker+70%taker',
        'tier1_fee': t1_hybrid,
        'tier2_fee': t2_hybrid,
        'tier1_bps': round(t1_hybrid * 10000, 2),
        'tier2_bps': round(t2_hybrid * 10000, 2),
        'detail': {
            't1_entry_bps': round(t1_entry * 10000, 2),
            't1_exit_bps': round(t1_exit * 10000, 2),
            't2_entry_bps': round(t2_entry * 10000, 2),
            't2_exit_bps': round(t2_exit * 10000, 2),
            'maker_t1_bps': round(t1_maker * 10000, 2),
            'maker_t2_bps': round(t2_maker * 10000, 2),
            'taker_t1_bps': round(t1_taker * 10000, 2),
            'taker_t2_bps': round(t2_taker * 10000, 2),
        },
    }

    # ----- Baseline (P50 market, for reference) -----
    t1_baseline = get_harness_fee('mexc_market', 'tier1')
    t2_baseline = get_harness_fee('mexc_market', 'tier2')
    regimes['baseline_p50'] = {
        'description': 'MEXC taker P50 (reference baseline)',
        'tier1_fee': t1_baseline,
        'tier2_fee': t2_baseline,
        'tier1_bps': round(t1_baseline * 10000, 1),
        'tier2_bps': round(t2_baseline * 10000, 1),
    }

    return regimes


def compute_stress_fees(regime_info, multiplier=2.0):
    """Compute stress fees by multiplying a regime's per-side fees."""
    return {
        'tier1_fee': regime_info['tier1_fee'] * multiplier,
        'tier2_fee': regime_info['tier2_fee'] * multiplier,
        'tier1_bps': round(regime_info['tier1_fee'] * multiplier * 10000, 1),
        'tier2_bps': round(regime_info['tier2_fee'] * multiplier * 10000, 1),
    }


# ============================================================
# Backtest runners
# ============================================================

def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators,
                 market_ctx, t1_fee, t2_fee, params):
    """Run backtests for T1 and T2 separately, merge trade lists."""
    enriched = {**params, '__market__': market_ctx}
    all_trades = []

    if t1_coins:
        bt_t1 = run_backtest(
            data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1,
        )
        for t in bt_t1.trade_list:
            t['_tier'] = 'tier1'
            t['_fee_per_side'] = t1_fee
        all_trades.extend(bt_t1.trade_list)

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
# Adverse Selection Model
# ============================================================

def apply_adverse_selection(trades, penalty_bps=5):
    """Post-hoc adverse selection: winners get worse fills.

    For each winning trade: adjusted_pnl = pnl - (size * penalty_bps/10000 * 2)
    Two sides: entry gets filled worse, exit gets filled worse.
    Losers keep as-is (filled at market).
    """
    adjusted = []
    total_penalty = 0.0
    n_penalized = 0
    for t in trades:
        t2 = dict(t)
        if t['pnl'] > 0:
            size = t.get('size', 200)
            penalty = size * (penalty_bps / 10000) * 2  # both sides
            t2['pnl'] = t['pnl'] - penalty
            t2['_adverse_penalty'] = round(penalty, 4)
            total_penalty += penalty
            n_penalized += 1
        adjusted.append(t2)
    return adjusted, total_penalty, n_penalized


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


# ============================================================
# STRICT Gate Evaluation
# ============================================================

def evaluate_gates_strict(metrics, stress_metrics, wf_folds_positive,
                          max_gap_days, top1_fold_conc):
    """Evaluate STRICT gates per task spec."""
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


# ============================================================
# Full regime analysis
# ============================================================

def analyze_regime(regime_name, regime_info, data, t1_coins, t2_coins,
                   t1_indicators, t2_indicators, market_ctx, total_bars,
                   stress_multiplier_val=2.0):
    """Run full analysis for one regime: baseline + stress + WF + gates."""
    t_start = time.time()
    t1_fee = regime_info['tier1_fee']
    t2_fee = regime_info['tier2_fee']

    # --- Baseline ---
    print(f'  [{regime_name}] Running baseline backtest...')
    trades = run_combined(data, t1_coins, t2_coins,
                          t1_indicators, t2_indicators, market_ctx,
                          t1_fee, t2_fee, PARAMS_V5)
    m = compute_metrics(trades, total_bars)
    tb = tier_pnl_breakdown(trades)
    max_gap_bars, max_gap_days = compute_max_gap(trades, total_bars)

    print(f'    Baseline: {m["trades"]}tr PF={m["pf"]:.3f} PnL=${m["pnl"]:.0f} '
          f'Exp/wk=${m["exp_per_week"]:.2f} DD={m["dd"]:.1f}%')

    # --- Stress 2x ---
    stress_fees = compute_stress_fees(regime_info, stress_multiplier_val)
    print(f'  [{regime_name}] Running stress {stress_multiplier_val}x backtest '
          f'(T1={stress_fees["tier1_bps"]}bps, T2={stress_fees["tier2_bps"]}bps)...')
    stress_trades = run_combined(data, t1_coins, t2_coins,
                                  t1_indicators, t2_indicators, market_ctx,
                                  stress_fees['tier1_fee'], stress_fees['tier2_fee'],
                                  PARAMS_V5)
    sm = compute_metrics(stress_trades, total_bars)
    print(f'    Stress: {sm["trades"]}tr PF={sm["pf"]:.3f} Exp/wk=${sm["exp_per_week"]:.2f}')

    # --- Walk-Forward 5-fold ---
    print(f'  [{regime_name}] Running walk-forward 5-fold...')
    fold_trades = run_combined_wf(data, t1_coins, t2_coins,
                                   t1_indicators, t2_indicators, market_ctx,
                                   t1_fee, t2_fee, PARAMS_V5, n_folds=5)
    wf_folds_positive = 0
    fold_pnls = []
    fold_details = []
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
    print(f'    WF: {wf_folds_positive}/5 folds positive, top1 conc={top1_fold_conc:.3f}')

    # --- Gate evaluation ---
    gates, all_pass, failed, passed = evaluate_gates_strict(
        m, sm, wf_folds_positive, max_gap_days, top1_fold_conc,
    )
    gate_count = sum(1 for g in gates.values() if g['pass'])
    total_gates = len(gates)

    elapsed = time.time() - t_start
    print(f'    Gates: {gate_count}/{total_gates} PASS '
          f'{"(ALL PASS)" if all_pass else "FAIL: " + ", ".join(failed)} '
          f'({elapsed:.1f}s)')

    return {
        'regime': regime_name,
        'description': regime_info['description'],
        'fees': {
            'tier1_bps': regime_info['tier1_bps'],
            'tier2_bps': regime_info['tier2_bps'],
            'tier1_fee': regime_info['tier1_fee'],
            'tier2_fee': regime_info['tier2_fee'],
        },
        'stress_fees': {
            'tier1_bps': stress_fees['tier1_bps'],
            'tier2_bps': stress_fees['tier2_bps'],
        },
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


def analyze_adverse_selection(trades, total_bars, penalty_bps, regime_label,
                              stress_trades, stress_total_bars=None):
    """Run adverse-selection post-hoc adjustment and evaluate gates.

    Uses the baseline trade list, adjusts PnL for winners, then re-evaluates.
    For stress: also adjust stress trades.
    """
    if stress_total_bars is None:
        stress_total_bars = total_bars

    adj_trades, total_penalty, n_penalized = apply_adverse_selection(trades, penalty_bps)
    m = compute_metrics(adj_trades, total_bars)
    max_gap_bars, max_gap_days = compute_max_gap(adj_trades, total_bars)

    # Stress: apply same adverse selection to stress trades
    adj_stress, stress_penalty, stress_n_pen = apply_adverse_selection(
        stress_trades, penalty_bps)
    sm = compute_metrics(adj_stress, total_bars)

    # WF: we cannot re-run WF fold-by-fold from post-hoc data.
    # Instead, approximate: use baseline WF fold results and adjust.
    # This is a post-hoc model, so we note this limitation.
    # For the WF gate we'll use -1 as sentinel to indicate "estimated from baseline".
    # Actually, let's be conservative and compute what we can:
    # We'll report WF as N/A for adverse selection (post-hoc model).
    wf_folds_positive = -1  # Sentinel: not applicable for post-hoc
    top1_fold_conc = -1.0

    gates, all_pass, failed, passed = evaluate_gates_strict(
        m, sm, wf_folds_positive, max_gap_days, top1_fold_conc,
    )
    # Override G6 and G8 to show N/A
    gates['G6_wf_folds_positive']['value'] = 'N/A (post-hoc)'
    gates['G6_wf_folds_positive']['pass'] = None  # Unknown
    gates['G8_top1_fold_conc']['value'] = 'N/A (post-hoc)'
    gates['G8_top1_fold_conc']['pass'] = None  # Unknown

    # Re-evaluate all_pass excluding G6 and G8
    known_gates = {k: v for k, v in gates.items()
                   if k not in ('G6_wf_folds_positive', 'G8_top1_fold_conc')}
    known_all_pass = all(g['pass'] for g in known_gates.values())
    known_failed = [k for k, g in known_gates.items() if not g['pass']]

    gate_count = sum(1 for g in known_gates.values() if g['pass'])
    total_known = len(known_gates)

    tb = tier_pnl_breakdown(adj_trades)

    return {
        'regime': regime_label,
        'description': f'Adverse selection: winners penalized {penalty_bps}bps/side each way',
        'penalty_bps': penalty_bps,
        'total_penalty': round(total_penalty, 2),
        'n_penalized': n_penalized,
        'baseline': m,
        'tier_breakdown': tb,
        'max_gap': {'bars': max_gap_bars, 'days': max_gap_days},
        'stress_2x': {
            'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'],
            'exp_per_week': sm['exp_per_week'], 'dd': sm['dd'],
            'stress_penalty': round(stress_penalty, 2),
        },
        'walk_forward': {
            'folds_positive': 'N/A (post-hoc model)',
            'fold_details': [],
            'top1_fold_conc': 'N/A',
            'note': 'Adverse selection is applied post-hoc; WF fold-level data unavailable.',
        },
        'gates': gates,
        'known_gates_pass': known_all_pass,
        'gates_passed': gate_count,
        'gates_total': total_known,
        'gates_total_incl_unknown': len(gates),
        'failed_gates': known_failed,
        'unknown_gates': ['G6_wf_folds_positive', 'G8_top1_fold_conc'],
        'runtime_s': 0.0,  # Post-hoc, no backtest time
    }


def analyze_adverse_wf(penalty_bps, data, t1_coins, t2_coins,
                       t1_indicators, t2_indicators, market_ctx,
                       t1_fee, t2_fee, total_bars):
    """Run full WF for adverse selection by adjusting fold-level trades."""
    enriched = {**PARAMS_V5, '__market__': market_ctx}
    fold_trades = run_combined_wf(data, t1_coins, t2_coins,
                                   t1_indicators, t2_indicators, market_ctx,
                                   t1_fee, t2_fee, PARAMS_V5, n_folds=5)

    wf_folds_positive = 0
    fold_pnls = []
    fold_details = []
    for fi in sorted(fold_trades.keys()):
        # Apply adverse selection to this fold's trades
        adj_fold, _, _ = apply_adverse_selection(fold_trades[fi], penalty_bps)
        fpnl = sum(t['pnl'] for t in adj_fold)
        fn = len(adj_fold)
        pos = fpnl > 0
        if pos:
            wf_folds_positive += 1
        fold_pnls.append(fpnl)
        fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2),
                             'positive': pos})
    top1_fold_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    return wf_folds_positive, fold_details, top1_fold_conc, fold_pnls


# ============================================================
# Markdown report
# ============================================================

def build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks):
    md = []
    md.append('# Part 2: Execution Realism Upgrade (P0-3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Agent**: C7-B')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')

    # Objective
    md.append('## Objective')
    md.append('')
    md.append('Test strategy resilience under 3 progressively more realistic execution regimes:')
    md.append('1. **Market Conservative (P90)**: Wider spreads+slippage (P90 instead of P50)')
    md.append('2. **Hybrid Realistic**: Blended maker/taker fills (60/40 entry, 30/70 exit)')
    md.append('3. **Adverse Selection**: Winners get 5-10bps extra cost (worse fills on profits)')
    md.append('')
    md.append('STRICT gate thresholds: G1>=10 trades/wk, G2<=2.5d gap, G3/G4>$0 exp/wk,')
    md.append('G5<=20% DD, G6>=4/5 WF folds, G8<35% fold concentration.')
    md.append('')

    # Summary comparison table
    md.append('## Summary Comparison')
    md.append('')
    md.append('| Regime | T1 bps | T2 bps | Trades | PF | P&L | Exp/Wk | DD% | WF | Fold Conc | Gates |')
    md.append('|--------|--------|--------|--------|----|-----|--------|-----|----|-----------|----|')

    for r in report['regimes']:
        m = r['baseline']
        wf = r.get('walk_forward', {})
        wf_str = str(wf.get('folds_positive', 'N/A'))
        if isinstance(wf_str, str) and wf_str.isdigit():
            wf_str = f'{wf_str}/5'
        elif wf_str == 'N/A (post-hoc model)':
            wf_str = 'N/A'
        else:
            wf_str = f'{wf_str}/5' if isinstance(wf.get('folds_positive'), int) and wf.get('folds_positive') >= 0 else 'N/A'

        fc = wf.get('top1_fold_conc', 'N/A')
        fc_str = f'{fc:.3f}' if isinstance(fc, (int, float)) and fc >= 0 else 'N/A'

        fees = r.get('fees', {})
        t1b = fees.get('tier1_bps', '-')
        t2b = fees.get('tier2_bps', '-')

        gate_info = r.get('gates_passed', '-')
        gate_total = r.get('gates_total', '-')
        if r.get('all_gates_pass'):
            gate_str = f'**{gate_info}/{gate_total} PASS**'
        elif r.get('known_gates_pass') is not None:
            gate_str = f'{gate_info}/{gate_total}+2?'
        else:
            gate_str = f'{gate_info}/{gate_total} FAIL'

        md.append(f'| {r["regime"]} | {t1b} | {t2b} | {m["trades"]} | '
                  f'{m["pf"]:.3f} | ${m["pnl"]:.0f} | ${m["exp_per_week"]:.2f} | '
                  f'{m["dd"]:.1f} | {wf_str} | {fc_str} | {gate_str} |')
    md.append('')

    # Per-regime detail
    for r in report['regimes']:
        md.append(f'## Regime: {r["regime"]}')
        md.append('')
        md.append(f'**Description**: {r["description"]}')
        md.append('')

        fees = r.get('fees', {})
        md.append(f'- Fees: T1={fees.get("tier1_bps", "?")} bps, T2={fees.get("tier2_bps", "?")} bps per side')

        m = r['baseline']
        md.append(f'- Baseline: {m["trades"]}tr, PF={m["pf"]:.3f}, WR={m["wr"]:.1f}%, '
                  f'P&L=${m["pnl"]:.0f}, Exp/Wk=${m["exp_per_week"]:.2f}, DD={m["dd"]:.1f}%')

        s = r.get('stress_2x', {})
        md.append(f'- Stress 2x: {s.get("trades", "?")}tr, PF={s.get("pf", 0):.3f}, '
                  f'Exp/Wk=${s.get("exp_per_week", 0):.2f}')

        wf = r.get('walk_forward', {})
        wfp = wf.get('folds_positive', 'N/A')
        md.append(f'- Walk-Forward: {wfp}/5 folds positive' if isinstance(wfp, int) and wfp >= 0
                  else f'- Walk-Forward: {wfp}')

        if 'penalty_bps' in r:
            md.append(f'- Adverse penalty: {r["penalty_bps"]}bps/side each way')
            md.append(f'- Total penalty extracted: ${r["total_penalty"]:.2f} from {r["n_penalized"]} winners')
        md.append('')

        # Gate table
        md.append('| Gate | Value | Threshold | Verdict |')
        md.append('|------|-------|-----------|---------|')
        for gname, ginfo in r['gates'].items():
            val = ginfo['value']
            thr = ginfo['threshold']
            p = ginfo['pass']
            if p is None:
                verdict = 'UNKNOWN'
            elif p:
                verdict = 'PASS'
            else:
                verdict = '**FAIL**'
            md.append(f'| {gname} | {val} | {thr} | {verdict} |')
        md.append('')

        # Fold details if available
        fold_details = wf.get('fold_details', [])
        if fold_details:
            md.append('**Walk-Forward Fold Details**:')
            md.append('')
            md.append('| Fold | Trades | P&L | Positive? |')
            md.append('|------|--------|-----|-----------|')
            for fd in fold_details:
                md.append(f'| {fd["fold"]} | {fd["trades"]} | ${fd["pnl"]:.0f} | '
                          f'{"Yes" if fd["positive"] else "No"} |')
            md.append('')

    # Sensitivity: expectancy vs fill-rate equivalent
    md.append('## Sensitivity: Expectancy vs. Fill-Rate Impact')
    md.append('')
    md.append('| Regime | Avg Cost/Side (bps) | Exp/Trade | Exp/Wk | Fill-Rate Equiv |')
    md.append('|--------|---------------------|-----------|--------|-----------------|')

    baseline_r = next((r for r in report['regimes'] if r['regime'] == 'baseline_p50'), None)
    for r in report['regimes']:
        m = r['baseline']
        fees = r.get('fees', {})
        avg_bps = (fees.get('tier1_bps', 0) + fees.get('tier2_bps', 0)) / 2
        fill_equiv = ''
        if baseline_r and baseline_r['baseline']['exp_per_week'] > 0:
            ratio = m['exp_per_week'] / baseline_r['baseline']['exp_per_week']
            fill_equiv = f'{ratio*100:.1f}% of baseline'
        md.append(f'| {r["regime"]} | {avg_bps:.1f} | ${m["expectancy"]:.2f} | '
                  f'${m["exp_per_week"]:.2f} | {fill_equiv} |')
    md.append('')

    # Adverse selection impact
    adv_regimes = [r for r in report['regimes'] if 'penalty_bps' in r]
    if adv_regimes:
        md.append('## Adverse Selection Impact')
        md.append('')
        md.append('| Penalty | Winners Affected | Total Penalty | PF | P&L | Exp/Wk | vs Baseline |')
        md.append('|---------|-----------------|---------------|----|----|--------|-------------|')

        for r in adv_regimes:
            m = r['baseline']
            if baseline_r:
                delta = m['pnl'] - baseline_r['baseline']['pnl']
                delta_str = f'{delta:+.0f}'
            else:
                delta_str = '-'
            md.append(f'| {r["penalty_bps"]}bps | {r["n_penalized"]} | ${r["total_penalty"]:.0f} | '
                      f'{m["pf"]:.3f} | ${m["pnl"]:.0f} | ${m["exp_per_week"]:.2f} | {delta_str} |')
        md.append('')

    # Verdict
    md.append('## Verdict')
    md.append('')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append('')

    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_exec_realism_001.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    return '\n'.join(md)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Part 2: Execution Realism Upgrade (P0-3)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Load data only, skip backtests')
    parser.add_argument('--require-data', action='store_true', help='Exit 1 if cache missing')
    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Part 2: Execution Realism Upgrade (P0-3) -- Agent C7-B')
    print('  H20 VWAP_DEVIATION v5 | 3 Execution Regimes | STRICT Gates')
    print(sep)
    t0 = time.time()

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Compute fee regimes ---
    regimes = compute_regime_fees()
    print('[Regimes]')
    for rname, rinfo in regimes.items():
        print(f'  {rname}: T1={rinfo["tier1_bps"]}bps, T2={rinfo["tier2_bps"]}bps -- {rinfo["description"]}')

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
        print(f'  Would run: 3 regimes x (baseline + stress + WF)')
        print(f'  + 2 adverse selection levels (5bps, 10bps) post-hoc')
        print(f'  + Adverse WF for each level')
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
    # Run all regimes
    # ============================================================
    all_results = []

    # --- Regime 0: Baseline P50 (reference) ---
    print(f'\n{sep}')
    print('  REGIME 0: Baseline P50 (reference)')
    print(sep)
    r_baseline = analyze_regime(
        'baseline_p50', regimes['baseline_p50'],
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, total_bars,
    )
    all_results.append(r_baseline)

    # --- Regime 1: Market Conservative (P90) ---
    print(f'\n{sep}')
    print('  REGIME 1: Market Conservative (P90)')
    print(sep)
    r_p90 = analyze_regime(
        'market_conservative_p90', regimes['market_conservative_p90'],
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, total_bars,
    )
    all_results.append(r_p90)

    # --- Regime 2: Hybrid Realistic ---
    print(f'\n{sep}')
    print('  REGIME 2: Hybrid Realistic (maker+taker blend)')
    print(sep)
    r_hybrid = analyze_regime(
        'hybrid_realistic', regimes['hybrid_realistic'],
        data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, total_bars,
    )
    # Add detail about blended fee computation
    r_hybrid['fee_blend_detail'] = regimes['hybrid_realistic'].get('detail', {})
    all_results.append(r_hybrid)

    # --- Regime 3a: Adverse Selection 5bps ---
    print(f'\n{sep}')
    print('  REGIME 3a: Adverse Selection (5bps penalty on winners)')
    print(sep)

    # Need baseline trades for adverse selection
    baseline_fee_t1 = regimes['baseline_p50']['tier1_fee']
    baseline_fee_t2 = regimes['baseline_p50']['tier2_fee']

    print('  [adverse_5bps] Running baseline backtest for trade list...')
    base_trades = run_combined(data, t1_coins, t2_coins,
                                t1_indicators, t2_indicators, market_context,
                                baseline_fee_t1, baseline_fee_t2, PARAMS_V5)

    # Stress trades for adverse selection
    stress_base = compute_stress_fees(regimes['baseline_p50'], 2.0)
    stress_base_trades = run_combined(data, t1_coins, t2_coins,
                                       t1_indicators, t2_indicators, market_context,
                                       stress_base['tier1_fee'], stress_base['tier2_fee'],
                                       PARAMS_V5)

    r_adv5 = analyze_adverse_selection(
        base_trades, total_bars, penalty_bps=5,
        regime_label='adverse_selection_5bps',
        stress_trades=stress_base_trades,
    )
    # Now run WF with adverse selection applied per fold
    print('  [adverse_5bps] Running walk-forward with per-fold adverse selection...')
    t_wf = time.time()
    wf5_pos, wf5_details, wf5_conc, wf5_pnls = analyze_adverse_wf(
        5, data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, baseline_fee_t1, baseline_fee_t2, total_bars,
    )
    print(f'    WF: {wf5_pos}/5 folds positive, top1 conc={wf5_conc:.3f} ({time.time()-t_wf:.1f}s)')

    # Update adverse result with real WF data
    r_adv5['walk_forward'] = {
        'folds_positive': wf5_pos,
        'fold_details': wf5_details,
        'top1_fold_conc': round(wf5_conc, 4),
    }
    # Re-evaluate gates with real WF data
    max_gap_days = r_adv5['max_gap']['days']
    gates_adv5, all_pass_adv5, failed_adv5, passed_adv5 = evaluate_gates_strict(
        r_adv5['baseline'], r_adv5['stress_2x'], wf5_pos, max_gap_days, wf5_conc,
    )
    r_adv5['gates'] = gates_adv5
    r_adv5['all_gates_pass'] = all_pass_adv5
    r_adv5['gates_passed'] = sum(1 for g in gates_adv5.values() if g['pass'])
    r_adv5['gates_total'] = len(gates_adv5)
    r_adv5['failed_gates'] = failed_adv5
    r_adv5['passed_gates'] = passed_adv5
    del r_adv5['known_gates_pass']
    del r_adv5['unknown_gates']
    r_adv5['fees'] = {
        'tier1_bps': regimes['baseline_p50']['tier1_bps'],
        'tier2_bps': regimes['baseline_p50']['tier2_bps'],
        'note': f'+{5}bps adverse selection on winners',
    }
    r_adv5['runtime_s'] = round(time.time() - t_wf, 1)

    gate_count = r_adv5['gates_passed']
    gate_total = r_adv5['gates_total']
    print(f'    Gates: {gate_count}/{gate_total} '
          f'{"(ALL PASS)" if all_pass_adv5 else "FAIL: " + ", ".join(failed_adv5)}')
    all_results.append(r_adv5)

    # --- Regime 3b: Adverse Selection 10bps ---
    print(f'\n{sep}')
    print('  REGIME 3b: Adverse Selection (10bps penalty on winners)')
    print(sep)

    r_adv10 = analyze_adverse_selection(
        base_trades, total_bars, penalty_bps=10,
        regime_label='adverse_selection_10bps',
        stress_trades=stress_base_trades,
    )
    # WF with 10bps adverse
    print('  [adverse_10bps] Running walk-forward with per-fold adverse selection...')
    t_wf2 = time.time()
    wf10_pos, wf10_details, wf10_conc, wf10_pnls = analyze_adverse_wf(
        10, data, t1_coins, t2_coins, t1_indicators, t2_indicators,
        market_context, baseline_fee_t1, baseline_fee_t2, total_bars,
    )
    print(f'    WF: {wf10_pos}/5 folds positive, top1 conc={wf10_conc:.3f} ({time.time()-t_wf2:.1f}s)')

    r_adv10['walk_forward'] = {
        'folds_positive': wf10_pos,
        'fold_details': wf10_details,
        'top1_fold_conc': round(wf10_conc, 4),
    }
    max_gap_days_10 = r_adv10['max_gap']['days']
    gates_adv10, all_pass_adv10, failed_adv10, passed_adv10 = evaluate_gates_strict(
        r_adv10['baseline'], r_adv10['stress_2x'], wf10_pos, max_gap_days_10, wf10_conc,
    )
    r_adv10['gates'] = gates_adv10
    r_adv10['all_gates_pass'] = all_pass_adv10
    r_adv10['gates_passed'] = sum(1 for g in gates_adv10.values() if g['pass'])
    r_adv10['gates_total'] = len(gates_adv10)
    r_adv10['failed_gates'] = failed_adv10
    r_adv10['passed_gates'] = passed_adv10
    del r_adv10['known_gates_pass']
    del r_adv10['unknown_gates']
    r_adv10['fees'] = {
        'tier1_bps': regimes['baseline_p50']['tier1_bps'],
        'tier2_bps': regimes['baseline_p50']['tier2_bps'],
        'note': f'+{10}bps adverse selection on winners',
    }
    r_adv10['runtime_s'] = round(time.time() - t_wf2, 1)

    gate_count = r_adv10['gates_passed']
    gate_total = r_adv10['gates_total']
    print(f'    Gates: {gate_count}/{gate_total} '
          f'{"(ALL PASS)" if all_pass_adv10 else "FAIL: " + ", ".join(failed_adv10)}')
    all_results.append(r_adv10)

    elapsed = time.time() - t0

    # ============================================================
    # Verdict
    # ============================================================
    verdict_lines = []
    passing_regimes = [r['regime'] for r in all_results if r.get('all_gates_pass')]
    failing_regimes = [r['regime'] for r in all_results if not r.get('all_gates_pass')]

    verdict_lines.append(f'**Regimes passing ALL STRICT gates**: '
                         f'{", ".join(passing_regimes) if passing_regimes else "NONE"}')
    verdict_lines.append('')

    if failing_regimes:
        verdict_lines.append(f'**Regimes failing**: {", ".join(failing_regimes)}')
        for r in all_results:
            if not r.get('all_gates_pass'):
                failed = r.get('failed_gates', [])
                verdict_lines.append(f'  - {r["regime"]}: fails {", ".join(failed)}')
        verdict_lines.append('')

    # Sensitivity summary
    baseline_epw = r_baseline['baseline']['exp_per_week']
    verdict_lines.append('**Expectancy degradation by regime**:')
    for r in all_results:
        epw = r['baseline']['exp_per_week']
        if baseline_epw > 0:
            pct = (epw / baseline_epw - 1) * 100
            verdict_lines.append(f'  - {r["regime"]}: ${epw:.2f}/wk ({pct:+.1f}% vs baseline)')
        else:
            verdict_lines.append(f'  - {r["regime"]}: ${epw:.2f}/wk')
    verdict_lines.append('')

    # Overall conclusion
    if all(r.get('all_gates_pass') for r in all_results):
        verdict_lines.append('**CONCLUSION**: Strategy passes ALL STRICT gates under ALL execution regimes. '
                             'Execution realism is NOT a concern.')
    elif r_p90.get('all_gates_pass') and r_hybrid.get('all_gates_pass'):
        verdict_lines.append('**CONCLUSION**: Strategy passes STRICT gates under cost-model regimes '
                             '(P90 + Hybrid). Adverse selection may erode edge.')
    else:
        verdict_lines.append('**CONCLUSION**: Strategy fails STRICT gates under realistic execution. '
                             'STRICT thresholds are very demanding. Review gate calibration.')

    # ============================================================
    # JSON Report
    # ============================================================
    report = {
        'run_header': {
            'task': 'part2_exec_realism_001',
            'agent': 'C7-B',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'baseline': 'v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)',
            'universe': f'T1({n_t1})+T2({n_t2}) [excl_all_negative]',
            'universe_total': n_total,
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
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
        'fee_regimes': {k: {kk: vv for kk, vv in v.items() if kk != 'detail'}
                        for k, v in regimes.items()},
        'regimes': all_results,
        'verdict_lines': verdict_lines,
        'summary': {
            'passing_regimes': passing_regimes,
            'failing_regimes': failing_regimes,
            'total_regimes_tested': len(all_results),
        },
    }

    out_dir = ROOT / 'reports' / 'hf'
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / 'part2_exec_realism_001.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    md_text = build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks)
    md_path = out_dir / 'part2_exec_realism_001.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    # ============================================================
    # Final Summary
    # ============================================================
    print(f'\n{sep}')
    print('  EXECUTION REALISM ANALYSIS COMPLETE')
    print(sep)

    for r in all_results:
        m = r['baseline']
        g = r.get('gates_passed', '?')
        gt = r.get('gates_total', '?')
        ap = r.get('all_gates_pass', False)
        status = 'ALL PASS' if ap else f'FAIL ({", ".join(r.get("failed_gates", []))})'
        print(f'  {r["regime"]:30s}  {m["trades"]}tr  PF={m["pf"]:.3f}  '
              f'Exp/wk=${m["exp_per_week"]:.2f}  DD={m["dd"]:.1f}%  '
              f'Gates={g}/{gt} {status}')

    print(f'\n  Passing regimes: {", ".join(passing_regimes) if passing_regimes else "NONE"}')
    print(f'  Runtime: {elapsed:.1f}s')
    print(sep)


if __name__ == '__main__':
    main()
