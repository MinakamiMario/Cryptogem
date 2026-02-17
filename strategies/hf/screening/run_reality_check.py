#!/usr/bin/env python3
"""
Reality Check: H20 VWAP_DEVIATION under multiple cost regimes
==============================================================
Re-runs the closest-to-viable Sprint 5 hypothesis (H20 VWAP_DEVIATION)
under 3 MEXC cost regimes to determine if zero-fee exchanges change the verdict.

Regimes:
  1. MARKET (MEXC taker): 5/20 bps T1/T2, fill_rate=1.0
  2. LIMIT_OPTIMISTIC:     3/8  bps T1/T2, fill_rate=0.80 (random miss)
  3. LIMIT_REALISTIC:      8/15 bps T1/T2, fill_rate=0.55 (adverse miss)

Also includes Kraken baseline (31/56 bps) for comparison.

Usage:
    python -m strategies.hf.screening.run_reality_check
"""
import sys
import json
import time
import math
import subprocess
from pathlib import Path
from datetime import datetime
from copy import deepcopy

# Ensure project root on path
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import (
    get_hypothesis_s5, GRID_H20, signal_h20_vwap_deviation,
)
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context

# ============================================================
# Constants
# ============================================================

BARS_PER_WEEK = 168  # 24 * 7

# Cost regime definitions (per-side fees)
REGIMES = {
    'kraken_baseline': {
        'label': 'Kraken Baseline',
        'tier1_fee': 0.0031,    # 31 bps
        'tier2_fee': 0.0056,    # 56 bps
        'fill_rate': 1.0,
        'fill_mode': 'full',    # no fill adjustment
        'description': 'Kraken T1=31bps T2=56bps per side',
    },
    'mexc_market': {
        'label': 'MEXC Market',
        'tier1_fee': 0.0005,    # 5 bps (0 exchange + 3 spread + 2 slippage)
        'tier2_fee': 0.0020,    # 20 bps (0 exchange + 12 spread + 8 slippage)
        'fill_rate': 1.0,
        'fill_mode': 'full',
        'description': 'MEXC 0-fee + spread/slippage: T1=5bps T2=20bps',
    },
    'mexc_limit_optimistic': {
        'label': 'MEXC Limit Optimistic',
        'tier1_fee': 0.0003,    # 3 bps (0 exchange + 0 spread + 3 adverse)
        'tier2_fee': 0.0008,    # 8 bps (0 exchange + 0 spread + 8 adverse)
        'fill_rate': 0.80,
        'fill_mode': 'random',  # random 20% miss
        'description': 'MEXC limit: T1=3bps T2=8bps, 80% fill (random miss)',
    },
    'mexc_limit_realistic': {
        'label': 'MEXC Limit Realistic',
        'tier1_fee': 0.0008,    # 8 bps (0 exchange + 0 spread + 8 adverse)
        'tier2_fee': 0.0015,    # 15 bps (0 exchange + 0 spread + 15 adverse)
        'fill_rate': 0.55,
        'fill_mode': 'adverse', # remove strongest trades first
        'description': 'MEXC limit: T1=8bps T2=15bps, 55% fill (adverse miss)',
    },
}

# Stress multipliers for spread+slippage components
STRESS_MULTIPLIERS = {
    'p90': 1.5,
    'p95': 2.0,
}

# Spread+slippage breakdown per regime (for stress scaling)
# Format: (spread_bps, slippage_bps) per side -- only for market regime
SPREAD_SLIP_BREAKDOWN = {
    'mexc_market': {
        'tier1': {'spread': 3, 'slippage': 2},   # total 5 bps
        'tier2': {'spread': 12, 'slippage': 8},   # total 20 bps
    },
    'mexc_limit_optimistic': {
        'tier1': {'spread': 0, 'slippage': 3},    # adverse selection only
        'tier2': {'spread': 0, 'slippage': 8},
    },
    'mexc_limit_realistic': {
        'tier1': {'spread': 0, 'slippage': 8},
        'tier2': {'spread': 0, 'slippage': 15},
    },
}


# ============================================================
# Data Loading (reuse from run_screen_s5.py)
# ============================================================

def load_candle_cache(timeframe='1h'):
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if not cache_path.exists():
        raise FileNotFoundError(f'Cache not found: {cache_path}')
    print(f'[Load] Reading {cache_path.name}...')
    with open(cache_path) as f:
        data = json.load(f)
    coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
    print(f'[Load] {len(coins_data)} coins loaded')
    return coins_data


def load_universe_tiering():
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        raise FileNotFoundError(f'Tiering not found: {tiering_path}')
    with open(tiering_path) as f:
        tiering = json.load(f)
    return tiering


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
# Backtest Runner per Regime
# ============================================================

def run_h20_variant(
    variant_idx, params, data, tier_coins, tier_indicators,
    market_context, tier1_fee, tier2_fee,
):
    """Run one H20 variant across both tiers, return composite results + trade_list."""
    enriched_params = {**params, '__market__': market_context}
    signal_fn = signal_h20_vwap_deviation

    all_trades = []
    total_pnl = 0.0
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=enriched_params,
            indicators=indicators,
            fee=fee,
            max_pos=1,
        )

        # Tag trades with tier for fee attribution
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
        total_pnl += bt.pnl

    return all_trades, total_pnl


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    """Compute standard metrics from a trade list."""
    n_trades = len(trades)
    if n_trades == 0:
        return {
            'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
            'dd': 0.0, 'expectancy': 0.0, 'trades_per_week': 0.0,
            'exp_per_week': 0.0, 'fee_drag_pct': 0.0,
        }

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n_trades

    # Trades per week
    total_weeks = total_bars / BARS_PER_WEEK if total_bars and total_bars > 0 else 1.0
    trades_per_week = n_trades / total_weeks
    exp_per_week = expectancy * trades_per_week

    # Fee drag
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)
        fee = t.get('_fee_per_side', 0.0031)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * fee + (size + gross) * fee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag_pct = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0

    # Max drawdown (simplified from equity curve)
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
        'pnl': total_pnl,
        'pf': round(pf, 3),
        'wr': round(wr, 2),
        'dd': round(max_dd, 2),
        'expectancy': round(expectancy, 4),
        'trades_per_week': round(trades_per_week, 2),
        'exp_per_week': round(exp_per_week, 4),
        'fee_drag_pct': round(fee_drag_pct, 2),
    }


def apply_fill_rate(trades, fill_rate, fill_mode):
    """Post-process trade list to simulate fill rate < 1.0.

    fill_mode='random': remove random (1-fill_rate) fraction
    fill_mode='adverse': remove strongest trades first (worst case)
    """
    if fill_rate >= 1.0 or fill_mode == 'full':
        return trades

    n_remove = int(len(trades) * (1.0 - fill_rate))
    if n_remove == 0:
        return trades

    if fill_mode == 'adverse':
        # Remove strongest trades first (they wouldn't fill because price ran away)
        sorted_trades = sorted(trades, key=lambda t: t.get('_strength', 0), reverse=True)
        kept = sorted_trades[n_remove:]
        return kept
    else:
        # Random removal: deterministic via step sampling for reproducibility
        import hashlib
        step = max(1, len(trades) // n_remove)
        remove_indices = set()
        idx = 0
        while len(remove_indices) < n_remove and idx < len(trades):
            remove_indices.add(idx)
            idx += step
        # If we didn't remove enough, fill from the end
        idx = len(trades) - 1
        while len(remove_indices) < n_remove and idx >= 0:
            remove_indices.add(idx)
            idx -= 1
        return [t for i, t in enumerate(trades) if i not in remove_indices]


def compute_stress_fees(regime_key, multiplier):
    """Compute stressed tier fees by scaling spread+slippage components."""
    if regime_key not in SPREAD_SLIP_BREAKDOWN:
        # Kraken: scale the entire fee by a fraction
        base = REGIMES[regime_key]
        # For Kraken, approximate: exchange=26bps, rest is spread/slip ~5bps
        # But Kraken fees are exchange-dominated, stress mainly affects execution costs
        # We'll scale only an estimated 5bps spread+slip portion
        kraken_spread_slip_t1 = 5   # bps estimate
        kraken_spread_slip_t2 = 10  # bps estimate
        t1_extra = kraken_spread_slip_t1 * (multiplier - 1) / 10000
        t2_extra = kraken_spread_slip_t2 * (multiplier - 1) / 10000
        return (
            base['tier1_fee'] + t1_extra,
            base['tier2_fee'] + t2_extra,
        )

    breakdown = SPREAD_SLIP_BREAKDOWN[regime_key]
    base = REGIMES[regime_key]

    # Scale spread+slippage components by multiplier
    t1_base_exchange = 0  # MEXC has 0 exchange fees
    t1_spread = breakdown['tier1']['spread']
    t1_slip = breakdown['tier1']['slippage']
    t1_stressed = t1_base_exchange + (t1_spread + t1_slip) * multiplier

    t2_spread = breakdown['tier2']['spread']
    t2_slip = breakdown['tier2']['slippage']
    t2_stressed = t1_base_exchange + (t2_spread + t2_slip) * multiplier

    return (t1_stressed / 10000, t2_stressed / 10000)  # bps to decimal


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


# ============================================================
# Main
# ============================================================

def main():
    print('=' * 70)
    print('  REALITY CHECK: H20 VWAP_DEVIATION under Multiple Cost Regimes')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Get commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    data = load_candle_cache('1h')
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    tier_coins = build_tier_coins(tiering, available_coins)

    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1: {n_t1} coins, T2: {n_t2} coins')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2.')
        sys.exit(1)

    # --- Precompute base indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    # --- Extend indicators (H20 needs VWAP) ---
    print('[Indicators] Extending with VWAP fields...')
    feature_coverage = {}
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            feature_coverage[tier_name] = cov
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # --- Precompute market context (H20 doesn't use __market__ but we
    #     inject it for protocol compliance) ---
    print('[Market Context] Precomputing...')
    all_coins = []
    for coins in tier_coins.values():
        all_coins.extend(coins)
    all_coins = list(set(all_coins))
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins)
    print(f'  Done.')

    # Inject __coin__ into each coin's indicators dict
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ============================================================
    # Run backtests across all regimes
    # ============================================================

    results_by_regime = {}

    for regime_key, regime in REGIMES.items():
        print(f'\n--- Regime: {regime["label"]} ---')
        print(f'  {regime["description"]}')
        regime_results = []

        for var_idx, params in enumerate(GRID_H20):
            t_var = time.time()

            # Run full backtest at this regime's fees
            all_trades, total_pnl = run_h20_variant(
                variant_idx=var_idx,
                params=params,
                data=data,
                tier_coins=tier_coins,
                tier_indicators=tier_indicators,
                market_context=market_context,
                tier1_fee=regime['tier1_fee'],
                tier2_fee=regime['tier2_fee'],
            )

            # Tag trades with strength for adverse fill removal
            # We need to re-run the signal to get strength, but it's stored
            # during backtest via the signal dict. The harness stores
            # 'strength' in the buy tuple but doesn't persist it in trade_list.
            # We'll approximate strength from trade PnL percentages as proxy.
            # Better: use the entry price deviation from stop/target as proxy.
            for t in all_trades:
                entry = t.get('entry', 0)
                target = t.get('_target_price', 0)
                stop = t.get('_stop_price', 0)
                # Proxy strength: larger target-to-stop ratio = stronger signal
                if entry > 0 and stop > 0:
                    # Use pnl_pct as strength proxy (absolute value)
                    t['_strength'] = abs(t.get('pnl_pct', 0))
                else:
                    t['_strength'] = 0

            # Apply fill rate adjustment
            adjusted_trades = apply_fill_rate(
                all_trades, regime['fill_rate'], regime['fill_mode']
            )

            metrics = compute_metrics(
                adjusted_trades,
                initial_capital=2000.0,
                total_bars=total_bars,
            )

            result = {
                'variant_idx': var_idx,
                'params': params,
                **metrics,
            }
            regime_results.append(result)

            print(f'  v{var_idx}: trades={metrics["trades"]} '
                  f'PF={metrics["pf"]:.3f} exp/w=${metrics["exp_per_week"]:.2f} '
                  f'WR={metrics["wr"]:.1f}% DD={metrics["dd"]:.1f}% '
                  f'fee_drag={metrics["fee_drag_pct"]:.1f}% '
                  f'({time.time()-t_var:.1f}s)')

        results_by_regime[regime_key] = regime_results

    # ============================================================
    # Stress tests (P90, P95)
    # ============================================================

    print('\n--- Stress Tests ---')
    stress_results = {}

    for stress_label, multiplier in STRESS_MULTIPLIERS.items():
        print(f'\n  [{stress_label}] spread+slippage x{multiplier}')
        stress_results[stress_label] = {}

        for regime_key in ['mexc_market', 'mexc_limit_optimistic', 'mexc_limit_realistic']:
            regime = REGIMES[regime_key]
            t1_stress, t2_stress = compute_stress_fees(regime_key, multiplier)

            print(f'    {regime["label"]}: T1={t1_stress*10000:.1f}bps T2={t2_stress*10000:.1f}bps')

            stress_regime_results = []
            for var_idx, params in enumerate(GRID_H20):
                all_trades, _ = run_h20_variant(
                    variant_idx=var_idx,
                    params=params,
                    data=data,
                    tier_coins=tier_coins,
                    tier_indicators=tier_indicators,
                    market_context=market_context,
                    tier1_fee=t1_stress,
                    tier2_fee=t2_stress,
                )

                for t in all_trades:
                    t['_strength'] = abs(t.get('pnl_pct', 0))

                adjusted_trades = apply_fill_rate(
                    all_trades, regime['fill_rate'], regime['fill_mode']
                )

                metrics = compute_metrics(
                    adjusted_trades,
                    initial_capital=2000.0,
                    total_bars=total_bars,
                )
                stress_regime_results.append({
                    'variant_idx': var_idx,
                    'params': params,
                    **metrics,
                })

            stress_results[stress_label][regime_key] = stress_regime_results

            # Print best variant for this stress+regime
            best = max(stress_regime_results, key=lambda r: r['exp_per_week'])
            print(f'      Best: v{best["variant_idx"]} PF={best["pf"]:.3f} '
                  f'exp/w=${best["exp_per_week"]:.2f}')

    # ============================================================
    # Find best variant per regime
    # ============================================================

    best_variant_comparison = {}
    for regime_key, regime_results in results_by_regime.items():
        best = max(regime_results, key=lambda r: r['exp_per_week'])
        best_variant_comparison[regime_key] = {
            'variant': f'v{best["variant_idx"]}',
            'params': best['params'],
            'pf': best['pf'],
            'wr': best['wr'],
            'trades': best['trades'],
            'exp_trade': best['expectancy'],
            'exp_week': best['exp_per_week'],
            'dd': best['dd'],
            'fee_drag_pct': best['fee_drag_pct'],
        }

    # ============================================================
    # Verdict
    # ============================================================

    any_positive = False
    verdict_parts = []
    for regime_key, best in best_variant_comparison.items():
        label = REGIMES[regime_key]['label']
        if best['exp_week'] > 0 and best['pf'] > 1.0:
            verdict_parts.append(
                f'{label}: POSITIVE edge (PF={best["pf"]:.3f}, '
                f'exp/w=${best["exp_week"]:.2f})'
            )
            any_positive = True
        else:
            verdict_parts.append(
                f'{label}: NO edge (PF={best["pf"]:.3f}, '
                f'exp/w=${best["exp_week"]:.2f})'
            )

    if any_positive:
        verdict = (
            'VWAP_DEVIATION shows positive expectancy under at least one MEXC regime. '
            + ' | '.join(verdict_parts)
        )
    else:
        verdict = (
            'VWAP_DEVIATION does NOT break even under any tested regime. '
            + ' | '.join(verdict_parts)
        )

    elapsed = time.time() - t0

    # ============================================================
    # Build JSON report
    # ============================================================

    report = {
        'run_header': {
            'sprint': 'reality_check',
            'task': 'vwap_mr_rerun',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'variants_tested': len(GRID_H20),
            'universe': f'T1({n_t1})+T2({n_t2})',
            'timeframe': '1h',
            'runtime_s': round(elapsed, 1),
        },
        'regimes': {k: v['description'] for k, v in REGIMES.items()},
        'results_by_regime': results_by_regime,
        'best_variant_comparison': best_variant_comparison,
        'stress_results': stress_results,
        'verdict': verdict,
    }

    # Write JSON
    json_path = ROOT / 'reports' / 'hf' / 'reality_check_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # Build Markdown report
    # ============================================================

    md_lines = []
    md_lines.append('# Reality Check: H20 VWAP_DEVIATION under Multiple Cost Regimes')
    md_lines.append('')
    md_lines.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md_lines.append(f'**Commit**: {commit}')
    md_lines.append(f'**Universe**: T1({n_t1}) + T2({n_t2})')
    md_lines.append(f'**Timeframe**: 1H')
    md_lines.append(f'**Runtime**: {elapsed:.1f}s')
    md_lines.append(f'**Hypothesis**: H20 VWAP_DEVIATION (6 variants)')
    md_lines.append('')

    # Regime descriptions
    md_lines.append('## Cost Regimes')
    md_lines.append('')
    md_lines.append('| Regime | T1 Fee (bps) | T2 Fee (bps) | Fill Rate | Fill Mode |')
    md_lines.append('|--------|-------------|-------------|-----------|-----------|')
    for rk, rv in REGIMES.items():
        md_lines.append(
            f'| {rv["label"]} | {rv["tier1_fee"]*10000:.0f} | '
            f'{rv["tier2_fee"]*10000:.0f} | {rv["fill_rate"]*100:.0f}% | '
            f'{rv["fill_mode"]} |'
        )
    md_lines.append('')

    # Main comparison table
    md_lines.append('## All Variants by Regime')
    md_lines.append('')
    md_lines.append('| Variant | Params | Regime | Trades | PF | WR% | Exp/Trade | Exp/Week | DD% | Fee Drag% |')
    md_lines.append('|---------|--------|--------|--------|-----|------|-----------|----------|------|-----------|')

    for var_idx, params in enumerate(GRID_H20):
        params_str = f'dev={params["dev_thresh"]} tp={params["tp_pct"]} sl={params["sl_pct"]}'
        for regime_key in REGIMES:
            r = results_by_regime[regime_key][var_idx]
            label = REGIMES[regime_key]['label']
            md_lines.append(
                f'| v{var_idx} | {params_str} | {label} '
                f'| {r["trades"]} | {r["pf"]:.3f} | {r["wr"]:.1f}% '
                f'| ${r["expectancy"]:.4f} | ${r["exp_per_week"]:.2f} '
                f'| {r["dd"]:.1f}% | {r["fee_drag_pct"]:.1f}% |'
            )
    md_lines.append('')

    # Best variant per regime
    md_lines.append('## Best Variant per Regime')
    md_lines.append('')
    md_lines.append('| Regime | Best Variant | PF | WR% | Trades | Exp/Trade | Exp/Week | DD% | Fee Drag% |')
    md_lines.append('|--------|--------------|----|------|--------|-----------|----------|------|-----------|')
    for regime_key, best in best_variant_comparison.items():
        label = REGIMES[regime_key]['label']
        md_lines.append(
            f'| {label} | {best["variant"]} | {best["pf"]:.3f} | {best["wr"]:.1f}% '
            f'| {best["trades"]} | ${best["exp_trade"]:.4f} '
            f'| ${best["exp_week"]:.2f} | {best["dd"]:.1f}% '
            f'| {best["fee_drag_pct"]:.1f}% |'
        )
    md_lines.append('')

    # Stress test results
    md_lines.append('## Stress Test Results')
    md_lines.append('')
    for stress_label, mult in STRESS_MULTIPLIERS.items():
        md_lines.append(f'### {stress_label.upper()} (spread+slippage x{mult})')
        md_lines.append('')
        md_lines.append('| Regime | Best Variant | PF | Exp/Week | Trades |')
        md_lines.append('|--------|--------------|----|----------|--------|')
        for regime_key in ['mexc_market', 'mexc_limit_optimistic', 'mexc_limit_realistic']:
            sr = stress_results[stress_label][regime_key]
            best = max(sr, key=lambda r: r['exp_per_week'])
            label = REGIMES[regime_key]['label']
            md_lines.append(
                f'| {label} | v{best["variant_idx"]} | {best["pf"]:.3f} '
                f'| ${best["exp_per_week"]:.2f} | {best["trades"]} |'
            )
        md_lines.append('')

    # Verdict
    md_lines.append('## Verdict')
    md_lines.append('')
    md_lines.append(verdict)
    md_lines.append('')

    # Footer
    md_lines.append('---')
    md_lines.append(
        f'*Generated by strategies/hf/screening/run_reality_check.py '
        f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*'
    )

    md_path = ROOT / 'reports' / 'hf' / 'reality_check_001.md'
    md_path.write_text('\n'.join(md_lines))
    print(f'[Report] MD:   {md_path}')

    # Print summary
    print(f'\n{"=" * 70}')
    print(f'  VERDICT: {verdict}')
    print(f'  Runtime: {elapsed:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
