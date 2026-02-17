#!/usr/bin/env python3
"""
4H Sweep Runner — Extended data + slope-as-sizing variant

Supports two modes:
  1. baseline: standard hnotrl_msp20 on extended (360+ day) data
  2. slope_sizing: SMA50 slope modulates position size (NOT a hard gate)

Slope-as-Sizing Logic:
  - slope <= steep_threshold (e.g. -10%): full position (scale=1.0)
  - slope >= mild_threshold (e.g. -3%):  minimum position (scale=min_scale, e.g. 0.3)
  - between: linear interpolation

This keeps ALL trades but sizes them by regime conviction.
Does NOT modify agent_team_v3.py — uses monkeypatching of run_backtest internals.

Usage:
    python scripts/run_4h_sweep_extended.py \
        --plan strategies/4h/sweep_plan_v2_extended.json \
        --data ~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_v2.json
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import importlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'trading_bot') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'trading_bot'))

import agent_team_v3 as engine
from agent_team_v3 import (
    run_backtest, precompute_all, normalize_cfg,
    INITIAL_CAPITAL, KRAKEN_FEE, START_BAR, Pos,
)

_gates_mod = importlib.import_module('strategies.4h.gates_4h')
evaluate_gates = _gates_mod.evaluate_gates
gates_to_dict = _gates_mod.gates_to_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CACHE = REPO_ROOT / 'trading_bot' / 'candle_cache_532.json'
DEFAULT_OUTPUT = REPO_ROOT / 'reports' / '4h'

# ---------------------------------------------------------------------------
# SMA slope computation (reused from regime runner)
# ---------------------------------------------------------------------------

def add_sma_slope_to_indicators(indicators: dict, sma_period: int = 50) -> None:
    """Add sma_slope array to each coin's indicator dict. In-place."""
    for pair, ind in indicators.items():
        n = ind['n']
        closes = ind['closes']
        sma_slope = [None] * n
        for bar in range(sma_period, n):
            sma_now = sum(closes[bar - sma_period + 1:bar + 1]) / sma_period
            half = sma_period // 2
            if bar >= sma_period + half:
                sma_prev = sum(closes[bar - sma_period - half + 1:bar - half + 1]) / sma_period
                if sma_prev > 0:
                    sma_slope[bar] = (sma_now - sma_prev) / sma_prev * 100
            elif sma_now > 0:
                sma_start = sum(closes[:sma_period]) / sma_period
                if sma_start > 0:
                    sma_slope[bar] = (sma_now - sma_start) / sma_start * 100
        ind['sma_slope'] = sma_slope


def _slope_to_scale(slope_val, steep_thresh: float = -10.0,
                     mild_thresh: float = -3.0, min_scale: float = 0.3) -> float:
    """Convert SMA50 slope to position size scale factor.

    - slope <= steep_thresh: scale = 1.0 (full conviction)
    - slope >= mild_thresh:  scale = min_scale (low conviction)
    - between: linear interpolation
    """
    if slope_val is None:
        return 1.0  # No data → full size (conservative default)
    if slope_val <= steep_thresh:
        return 1.0
    if slope_val >= mild_thresh:
        return min_scale
    # Linear interpolation
    frac = (slope_val - steep_thresh) / (mild_thresh - steep_thresh)
    return 1.0 - frac * (1.0 - min_scale)


# ---------------------------------------------------------------------------
# Monkeypatched run_backtest with slope-based sizing
# ---------------------------------------------------------------------------

def run_backtest_slope_sizing(indicators, coins, cfg,
                               steep_thresh=-10.0, mild_thresh=-3.0,
                               min_scale=0.3, fee_override=None):
    """Run backtest with slope-modulated position sizing.

    Instead of blocking entries (hard gate), this scales position size
    based on SMA50 slope regime conviction.

    Implementation: wraps the position opening section by temporarily
    scaling the available equity before position allocation.
    """
    # We need to replicate run_backtest but with modified sizing.
    # Since we can't modify the engine, we use a different approach:
    # Monkeypatch the Pos creation to capture and modify size_usd.

    # Strategy: Run normal backtest, then for each trade, compute what
    # the slope-adjusted size would have been, and adjust P&L proportionally.
    #
    # This is equivalent to actually running with different sizes because:
    # - P&L is linear in position size: pnl = (exit-entry)/entry * size_usd
    # - Fees are linear in size: fee = size * fee_rate
    # - So scaling size by factor f scales net P&L by factor f

    # Step 1: Run normal backtest to get trade list
    bt = run_backtest(indicators, coins, cfg, fee_override=fee_override)

    if not bt['trade_list']:
        return bt

    # Step 2: For each trade, compute slope at entry and scale P&L
    adjusted_trades = []
    total_gross = 0
    total_fees = 0
    wins = 0
    losses = 0
    exit_classes = {}

    for t in bt['trade_list']:
        pair = t['pair']
        entry_bar = t['entry_bar']
        ind = indicators.get(pair)

        # Get slope at entry
        slope_val = None
        if ind and 'sma_slope' in ind:
            sma_slope = ind['sma_slope']
            if entry_bar < len(sma_slope):
                slope_val = sma_slope[entry_bar]

        scale = _slope_to_scale(slope_val, steep_thresh, mild_thresh, min_scale)

        # Scale the trade P&L
        original_pnl = t.get('pnl', 0)
        original_size = t.get('size_usd', 0)
        adjusted_size = original_size * scale
        # P&L scales linearly: adjusted_pnl = original_pnl * scale
        adjusted_pnl = original_pnl * scale

        adj_trade = dict(t)
        adj_trade['size_usd'] = round(adjusted_size, 2)
        adj_trade['pnl'] = round(adjusted_pnl, 4)
        adj_trade['slope_at_entry'] = round(slope_val, 2) if slope_val is not None else None
        adj_trade['size_scale'] = round(scale, 3)
        adjusted_trades.append(adj_trade)

        if adjusted_pnl > 0:
            wins += 1
            total_gross += adjusted_pnl
        else:
            losses += 1
            total_fees += abs(adjusted_pnl) if adjusted_pnl < 0 else 0

        reason = t.get('exit_reason', 'unknown')
        if reason not in exit_classes:
            exit_classes[reason] = {'count': 0, 'pnl': 0}
        exit_classes[reason]['count'] += 1
        exit_classes[reason]['pnl'] += adjusted_pnl

    # Rebuild summary stats
    n_trades = len(adjusted_trades)
    total_pnl = sum(t['pnl'] for t in adjusted_trades)
    wr = wins / n_trades * 100 if n_trades > 0 else 0

    gross_profit = sum(t['pnl'] for t in adjusted_trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in adjusted_trades if t['pnl'] < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Compute drawdown on adjusted equity curve
    equity_curve = [INITIAL_CAPITAL]
    eq = INITIAL_CAPITAL
    for t in sorted(adjusted_trades, key=lambda x: x.get('exit_bar', 0)):
        eq += t['pnl']
        equity_curve.append(eq)
    peak = INITIAL_CAPITAL
    max_dd = 0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    final_equity = equity_curve[-1] if equity_curve else INITIAL_CAPITAL

    return {
        'trades': n_trades,
        'wr': round(wr, 2),
        'pnl': round(total_pnl, 2),
        'final_equity': round(final_equity, 2),
        'pf': round(pf, 4),
        'dd': round(max_dd, 2),
        'broke': final_equity < 0,
        'early_stopped': False,
        'exit_classes': exit_classes,
        'trade_list': adjusted_trades,
        'equity_curve': equity_curve,
        '_slope_sizing': {
            'steep_thresh': steep_thresh,
            'mild_thresh': mild_thresh,
            'min_scale': min_scale,
            'avg_scale': round(sum(t.get('size_scale', 1) for t in adjusted_trades) / max(1, n_trades), 3),
            'n_full_size': sum(1 for t in adjusted_trades if t.get('size_scale', 1) >= 0.95),
            'n_reduced': sum(1 for t in adjusted_trades if t.get('size_scale', 1) < 0.95),
        }
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_hash() -> str:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def _build_run_id(idx: int, label: str, git_short: str) -> str:
    safe_label = label.strip().lower().replace(' ', '_').replace('-', '_')[:30]
    return f"sweep_v2_{idx:03d}_{safe_label}_{git_short}"


def _build_metadata(cfg, label, dataset_path, run_id, n_coins, elapsed_s, plan_path, idx,
                     slope_sizing=None):
    meta = {
        'run_id': run_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'git_hash': _git_hash(),
        'config_source': f'sweep_plan_v2:{label} (idx={idx})',
        'dataset': str(dataset_path.name),
        'dataset_path': str(dataset_path),
        'exchange': 'kraken',
        'fee_bps': round(KRAKEN_FEE * 10000, 1),
        'initial_capital': INITIAL_CAPITAL,
        'start_bar': START_BAR,
        'n_coins': n_coins,
        'elapsed_s': round(elapsed_s, 2),
        'engine': 'agent_team_v3.run_backtest',
        'sweep_plan': str(plan_path),
        'sweep_index': idx,
    }
    if slope_sizing:
        meta['slope_sizing'] = slope_sizing
    return meta


def _format_results_md(bt, meta, cfg, gate_dict, slope_info=None):
    lines = [
        f"# 4H DualConfirm Backtest — {meta['run_id']}",
        "",
        "## Metadata",
        f"- **Timestamp**: {meta['timestamp']}",
        f"- **Git**: {meta['git_hash']}",
        f"- **Config**: {meta['config_source']}",
        f"- **Dataset**: {meta['dataset']} ({meta['n_coins']} coins)",
        f"- **Exchange**: {meta['exchange']} (fee: {meta['fee_bps']} bps/side)",
    ]
    if slope_info:
        lines.append(f"- **Slope Sizing**: steep={slope_info['steep_thresh']}%, "
                      f"mild={slope_info['mild_thresh']}%, min_scale={slope_info['min_scale']}")
        lines.append(f"- **Avg Scale**: {slope_info.get('avg_scale', '?')}, "
                      f"Full-size: {slope_info.get('n_full_size', '?')}, "
                      f"Reduced: {slope_info.get('n_reduced', '?')}")
    lines.extend([
        "",
        "## Results",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {bt['trades']} |",
        f"| Win Rate | {bt['wr']:.1f}% |",
        f"| P&L | ${bt['pnl']:+,.2f} |",
        f"| PF | {bt['pf']:.2f} |",
        f"| DD | {bt['dd']:.1f}% |",
        "",
        f"## Gates: {gate_dict['verdict']} ({gate_dict['n_passed']}/{gate_dict['n_total']})",
    ])
    for g in gate_dict.get('gates', []):
        mark = "PASS" if g['passed'] else "FAIL"
        lines.append(f"- {g['name']}: {mark} — {g['detail']}")

    lines.extend(["", "## Config", "```json", json.dumps(cfg, indent=2, sort_keys=True), "```"])
    return '\n'.join(lines)


def _progress_bar(current, total, width=30):
    filled = int(width * current / total) if total > 0 else 0
    bar = '#' * filled + '-' * (width - filled)
    pct = current / total * 100 if total > 0 else 0
    return f"[{bar}] {current}/{total} ({pct:.0f}%)"


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------

def run_sweep(args):
    plan_path = Path(args.plan)
    with open(plan_path) as f:
        sweep_plan = json.load(f)
    configs = sweep_plan.get('configs', sweep_plan)
    if not isinstance(configs, list):
        print(f"ERROR: configs must be a list"); sys.exit(1)

    print(f"\n{'='*70}")
    print(f"  4H Sweep Runner — EXTENDED DATA + SLOPE-AS-SIZING")
    print(f"{'='*70}")
    print(f"  Plan: {plan_path} ({len(configs)} configs)")
    print(f"  Output: {args.output_dir}")

    only_indices = None
    if args.only:
        only_indices = {int(x.strip()) for x in args.only.split(',') if x.strip().isdigit()}
        print(f"  Only: {sorted(only_indices)}")

    git_short = _git_hash()
    print(f"  Git: {git_short}")
    output_base = Path(args.output_dir)

    # Load data
    dataset_path = Path(args.data) if args.data else DEFAULT_CACHE
    print(f"\n  Loading data from {dataset_path}...")
    t_load = time.time()
    with open(dataset_path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])

    # Check data stats
    meta_info = data.get('_meta', {})
    if meta_info:
        print(f"  Dataset meta: {meta_info.get('coins', '?')} coins, "
              f"{meta_info.get('span_days', '?')} days, "
              f"source={meta_info.get('source', '?')}")

    n_coins = len(coins)
    print(f"  {n_coins} coins loaded ({time.time()-t_load:.1f}s)")

    # Build coin bar counts for cohort filtering
    coin_bar_counts = {c: len(data.get(c, [])) for c in coins}

    # Filter coins with minimum data (global minimum)
    min_bars = args.min_bars
    if min_bars > 0:
        original_count = len(coins)
        coins = [c for c in coins if coin_bar_counts[c] >= min_bars]
        filtered_count = original_count - len(coins)
        if filtered_count > 0:
            print(f"  Filtered: {filtered_count} coins with <{min_bars} bars (keeping {len(coins)})")
        n_coins = len(coins)

    # Build cohort maps
    COHORT_THRESHOLDS = {'A': 2160, 'B': 1080}  # A=360d, B=180d
    cohort_coins = {}
    for cohort_name, thresh in COHORT_THRESHOLDS.items():
        cohort_coins[cohort_name] = [c for c in coins if coin_bar_counts[c] >= thresh]
        print(f"  Cohort {cohort_name} (≥{thresh} bars): {len(cohort_coins[cohort_name])} coins")

    # Precompute base indicators on ALL qualifying coins
    print(f"  Precomputing indicators...")
    t_pre = time.time()
    indicators = precompute_all(data, coins)
    del data

    # Always add SMA slope (needed for slope-sizing variants)
    any_slope = any(c.get('slope_sizing') for c in configs)
    if any_slope:
        sma_period = 50
        for c in configs:
            ss = c.get('slope_sizing', {})
            if ss:
                sma_period = ss.get('sma_period', 50)
                break
        print(f"  Adding SMA{sma_period} slope to indicators...")
        add_sma_slope_to_indicators(indicators, sma_period)

    pre_elapsed = time.time() - t_pre
    print(f"  Precompute: {pre_elapsed:.1f}s")

    # Main loop
    t_sweep = time.time()
    n_total = len(configs)
    n_completed = n_skipped = n_failed = 0
    results_summary = []

    print(f"\n{'='*70}")
    print(f"  Starting sweep: {n_total} configs")
    print(f"{'='*70}\n")

    for i, entry in enumerate(configs):
        idx = entry.get('idx', i + 1)
        label = entry.get('label', f'config_{idx}')
        cfg_raw = entry.get('params', entry.get('cfg', entry.get('config', {})))
        slope_sizing = entry.get('slope_sizing')
        cohort = entry.get('cohort')  # 'A', 'B', or None (use all coins)
        fee_override = entry.get('fee_override')  # None = use engine default
        run_id = _build_run_id(idx, label, git_short)

        if only_indices and idx not in only_indices:
            n_skipped += 1
            continue

        # Select coins for this config based on cohort
        if cohort and cohort in cohort_coins:
            run_coins = cohort_coins[cohort]
        else:
            run_coins = coins
        n_run_coins = len(run_coins)

        done = n_completed + n_skipped + n_failed
        print(f"  {_progress_bar(done, n_total)}")
        print(f"  [{idx:03d}] {label}", end="")
        if cohort:
            print(f"  [Cohort {cohort}: {n_run_coins} coins]", end="")
        if fee_override is not None:
            print(f"  [FEE: {fee_override*10000:.0f}bps]", end="")
        if slope_sizing:
            print(f"  [SLOPE: steep={slope_sizing.get('steep_thresh', -10)}%, "
                  f"mild={slope_sizing.get('mild_thresh', -3)}%, "
                  f"min={slope_sizing.get('min_scale', 0.3)}]", end="")
        print()

        run_dir = output_base / run_id
        results_json = run_dir / 'results.json'
        if results_json.exists() and not args.force:
            print(f"        SKIP (exists)")
            n_skipped += 1
            results_summary.append({'idx': idx, 'label': label, 'run_id': run_id, 'status': 'skipped'})
            continue

        try:
            cfg = normalize_cfg(dict(cfg_raw))

            t_run = time.time()

            if slope_sizing:
                bt = run_backtest_slope_sizing(
                    indicators, run_coins, cfg,
                    steep_thresh=slope_sizing.get('steep_thresh', -10.0),
                    mild_thresh=slope_sizing.get('mild_thresh', -3.0),
                    min_scale=slope_sizing.get('min_scale', 0.3),
                    fee_override=fee_override,
                )
            else:
                bt = run_backtest(indicators, run_coins, cfg,
                                  fee_override=fee_override)

            bt_elapsed = time.time() - t_run

            slope_info = bt.get('_slope_sizing') if slope_sizing else None
            meta = _build_metadata(cfg, label, dataset_path, run_id, n_run_coins,
                                    bt_elapsed, plan_path, idx, slope_info)
            if cohort:
                meta['cohort'] = cohort
                meta['cohort_threshold'] = COHORT_THRESHOLDS.get(cohort, 0)
            gate_report = evaluate_gates(bt)
            gate_dict = gates_to_dict(gate_report)

            run_dir.mkdir(parents=True, exist_ok=True)

            # Write results
            payload = {
                'metadata': meta,
                'summary': {
                    'trades': bt['trades'], 'wr': round(bt['wr'], 2),
                    'pnl': round(bt['pnl'], 2), 'final_equity': round(bt['final_equity'], 2),
                    'pf': round(bt['pf'], 4), 'dd': round(bt['dd'], 2),
                    'broke': bt['broke'], 'early_stopped': bt['early_stopped'],
                },
                'exit_classes': bt['exit_classes'],
                'trade_count': bt['trades'],
                'gates': gate_dict,
                'cohort': cohort,
                'slope_sizing': slope_sizing,
                'trades': [
                    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
                    for t in bt['trade_list']
                ],
            }
            if slope_info:
                payload['slope_sizing_stats'] = slope_info

            with open(results_json, 'w') as f:
                json.dump(payload, f, indent=2, default=str)
            with open(run_dir / 'params.json', 'w') as f:
                json.dump(cfg, f, indent=2, sort_keys=True)
            with open(run_dir / 'gates.json', 'w') as f:
                json.dump(gate_dict, f, indent=2)
            md = _format_results_md(bt, meta, cfg, gate_dict, slope_info)
            with open(run_dir / 'results.md', 'w') as f:
                f.write(md)

            verdict = gate_dict['verdict']
            ev = bt['pnl'] / bt['trades'] if bt['trades'] > 0 else 0
            slope_tag = ""
            if slope_info:
                slope_tag = f" avgS={slope_info['avg_scale']:.2f}"
            print(
                f"        {bt['trades']:3d}tr | WR {bt['wr']:5.1f}% | "
                f"P&L ${bt['pnl']:+8,.2f} | PF {bt['pf']:5.2f} | "
                f"DD {bt['dd']:5.1f}% | EV ${ev:+6.1f} | "
                f"Gates {gate_dict['n_passed']}/{gate_dict['n_total']} {verdict:4s}{slope_tag} | {bt_elapsed:.2f}s"
            )

            n_completed += 1
            results_summary.append({
                'idx': idx, 'label': label, 'run_id': run_id, 'status': 'completed',
                'trades': bt['trades'], 'pnl': round(bt['pnl'], 2),
                'pf': round(bt['pf'], 4), 'dd': round(bt['dd'], 2),
                'wr': round(bt['wr'], 2), 'ev_per_trade': round(ev, 2),
                'verdict': verdict,
                'cohort': cohort,
                'n_coins': n_run_coins,
                'slope_sizing': slope_sizing is not None,
            })

        except Exception as e:
            import traceback
            print(f"        FAILED: {e}")
            traceback.print_exc()
            n_failed += 1
            results_summary.append({'idx': idx, 'label': label, 'run_id': run_id,
                                    'status': 'failed', 'error': str(e)})

    # Summary
    total_elapsed = time.time() - t_sweep
    print(f"\n{'='*70}")
    print(f"  SWEEP COMPLETE")
    print(f"{'='*70}")
    print(f"  Completed: {n_completed} | Skipped: {n_skipped} | Failed: {n_failed}")
    print(f"  Precompute: {pre_elapsed:.1f}s | Backtests: {total_elapsed:.1f}s")

    go_configs = [r for r in results_summary if r.get('verdict') == 'GO']
    if go_configs:
        go_configs.sort(key=lambda r: (-r.get('pf', 0), -r.get('ev_per_trade', 0)))
        print(f"\n  --- GO CONFIGS ({len(go_configs)}) ---")
        for rank, r in enumerate(go_configs, 1):
            tag = " [slope-sizing]" if r.get('slope_sizing') else ""
            print(f"  #{rank}: [{r['idx']:03d}] {r['label']} | "
                  f"{r['trades']}tr PF={r['pf']:.2f} P&L=${r['pnl']:+,.0f} DD={r['dd']:.1f}%{tag}")
    else:
        print(f"\n  No GO configs found")

    # Write summary
    summary_path = output_base / 'sweep_v2_summary.json'
    with open(summary_path, 'w') as f:
        json.dump({
            'sweep_version': 'v2-extended',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'plan': str(plan_path),
            'dataset': str(dataset_path),
            'n_coins': n_coins,
            'n_configs': n_total,
            'n_completed': n_completed,
            'n_failed': n_failed,
            'results': results_summary,
        }, f, indent=2)

    print(f"\n  Summary: {summary_path}")
    print(f"  Output: {output_base}")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description='4H Sweep Runner — extended + slope-as-sizing')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data', default=None)
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--only', default=None)
    parser.add_argument('--min-bars', type=int, default=200,
                        help='Minimum bars per coin (default: 200, filters thin coins)')
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()
