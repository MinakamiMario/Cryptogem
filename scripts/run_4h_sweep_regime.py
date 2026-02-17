#!/usr/bin/env python3
"""
4H Sweep Runner — Regime-aware variant

Adds a per-coin SMA50 slope regime gate to the entry filter WITHOUT
modifying agent_team_v3.py. Uses monkeypatching of check_entry_at_bar.

Usage:
    python scripts/run_4h_sweep_regime.py \
        --plan strategies/4h/sweep_plan_v1b_regime.json \
        --data reports/4h/windows/candle_cache_early_360.json

The sweep plan configs can include:
    "regime_filter": {"sma_period": 50, "slope_max_pct": -8.0}

When regime_filter is present, entries are blocked when the coin's
SMA slope is ABOVE slope_max_pct (i.e., not bearish enough).
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
    INITIAL_CAPITAL, KRAKEN_FEE, START_BAR,
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
# SMA slope computation
# ---------------------------------------------------------------------------

def add_sma_slope_to_indicators(indicators: dict, sma_period: int = 50) -> None:
    """Add sma_slope array to each coin's indicator dict. In-place."""
    for pair, ind in indicators.items():
        n = ind['n']
        closes = ind['closes']
        sma_slope = [None] * n
        for bar in range(sma_period, n):
            # SMA at current bar
            sma_now = sum(closes[bar - sma_period + 1:bar + 1]) / sma_period
            # SMA at bar - sma_period/2 (mid lookback)
            half = sma_period // 2
            if bar >= sma_period + half:
                sma_prev = sum(closes[bar - sma_period - half + 1:bar - half + 1]) / sma_period
                if sma_prev > 0:
                    sma_slope[bar] = (sma_now - sma_prev) / sma_prev * 100
            elif sma_now > 0:
                # Fallback: slope over available range
                sma_start = sum(closes[:sma_period]) / sma_period
                if sma_start > 0:
                    sma_slope[bar] = (sma_now - sma_start) / sma_start * 100
        ind['sma_slope'] = sma_slope


def _make_regime_entry_filter(original_fn, slope_max_pct: float):
    """Return a wrapped check_entry_at_bar that adds SMA slope gate."""
    def wrapped(ind, bar, cfg):
        # First check regime gate
        slope = ind.get('sma_slope', [None] * (bar + 1))
        if bar < len(slope) and slope[bar] is not None:
            if slope[bar] > slope_max_pct:
                return False, 0
        # Then original entry check
        return original_fn(ind, bar, cfg)
    return wrapped


# ---------------------------------------------------------------------------
# Helpers (from run_4h_sweep.py — minimal duplication)
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
    return f"sweep_v1b_{idx:03d}_{safe_label}_{git_short}"


def _build_metadata(cfg, label, dataset_path, run_id, n_coins, elapsed_s, plan_path, idx):
    return {
        'run_id': run_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'git_hash': _git_hash(),
        'config_source': f'sweep_plan:{label} (idx={idx})',
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


def _format_results_md(bt, meta, cfg, gate_dict, regime_info=None):
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
    if regime_info:
        lines.append(f"- **Regime Filter**: SMA{regime_info['sma_period']} slope <= {regime_info['slope_max_pct']}%")
    lines.extend([
        "",
        "## Results",
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
    print(f"  4H Sweep Runner — REGIME-AWARE")
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
    n_coins = len(coins)
    print(f"  {n_coins} coins loaded ({time.time()-t_load:.1f}s)")

    # Precompute base indicators
    print(f"  Precomputing indicators...")
    t_pre = time.time()
    indicators = precompute_all(data, coins)
    del data

    # Check if any config has regime_filter — if so, add SMA slope
    any_regime = any(c.get('regime_filter') or c.get('params', {}).get('regime_filter')
                     for c in configs)
    if any_regime:
        # Determine sma_period from first config that has it
        for c in configs:
            rf = c.get('regime_filter') or c.get('params', {}).get('regime_filter', {})
            if rf:
                sma_period = rf.get('sma_period', 50)
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

    # Save original entry function
    original_check = engine.check_entry_at_bar

    for i, entry in enumerate(configs):
        idx = entry.get('idx', i + 1)
        label = entry.get('label', f'config_{idx}')
        cfg_raw = entry.get('params', entry.get('cfg', entry.get('config', {})))
        regime_filter = entry.get('regime_filter') or cfg_raw.pop('regime_filter', None)
        run_id = _build_run_id(idx, label, git_short)

        if only_indices and idx not in only_indices:
            n_skipped += 1
            continue

        done = n_completed + n_skipped + n_failed
        print(f"  {_progress_bar(done, n_total)}")
        print(f"  [{idx:03d}] {label}", end="")
        if regime_filter:
            print(f"  [REGIME: slope<={regime_filter.get('slope_max_pct', -8)}%]", end="")
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

            # Apply regime filter via monkeypatch
            if regime_filter:
                slope_max = regime_filter.get('slope_max_pct', -8.0)
                engine.check_entry_at_bar = _make_regime_entry_filter(original_check, slope_max)
            else:
                engine.check_entry_at_bar = original_check

            t_run = time.time()
            bt = run_backtest(indicators, coins, cfg)
            bt_elapsed = time.time() - t_run

            # Restore original
            engine.check_entry_at_bar = original_check

            meta = _build_metadata(cfg, label, dataset_path, run_id, n_coins, bt_elapsed, plan_path, idx)
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
                'regime_filter': regime_filter,
                'trades': [
                    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
                    for t in bt['trade_list']
                ],
            }
            with open(results_json, 'w') as f:
                json.dump(payload, f, indent=2, default=str)
            with open(run_dir / 'params.json', 'w') as f:
                json.dump(cfg, f, indent=2, sort_keys=True)
            with open(run_dir / 'gates.json', 'w') as f:
                json.dump(gate_dict, f, indent=2)
            regime_info = {'sma_period': regime_filter.get('sma_period', 50),
                           'slope_max_pct': regime_filter.get('slope_max_pct', -8.0)} if regime_filter else None
            md = _format_results_md(bt, meta, cfg, gate_dict, regime_info)
            with open(run_dir / 'results.md', 'w') as f:
                f.write(md)

            verdict = gate_dict['verdict']
            ev = bt['pnl'] / bt['trades'] if bt['trades'] > 0 else 0
            print(
                f"        {bt['trades']:3d}tr | WR {bt['wr']:5.1f}% | "
                f"P&L ${bt['pnl']:+8,.2f} | PF {bt['pf']:5.2f} | "
                f"DD {bt['dd']:5.1f}% | EV ${ev:+6.1f} | "
                f"Gates {gate_dict['n_passed']}/{gate_dict['n_total']} {verdict:4s} | {bt_elapsed:.2f}s"
            )

            n_completed += 1
            results_summary.append({
                'idx': idx, 'label': label, 'run_id': run_id, 'status': 'completed',
                'trades': bt['trades'], 'pnl': round(bt['pnl'], 2),
                'pf': round(bt['pf'], 4), 'dd': round(bt['dd'], 2),
                'wr': round(bt['wr'], 2), 'ev_per_trade': round(ev, 2),
                'verdict': verdict,
            })

        except Exception as e:
            engine.check_entry_at_bar = original_check
            print(f"        FAILED: {e}")
            n_failed += 1
            results_summary.append({'idx': idx, 'label': label, 'run_id': run_id,
                                    'status': 'failed', 'error': str(e)})

    engine.check_entry_at_bar = original_check

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
            print(f"  #{rank}: [{r['idx']:03d}] {r['label']} | "
                  f"{r['trades']}tr PF={r['pf']:.2f} P&L=${r['pnl']:+,.0f} DD={r['dd']:.1f}%")
    else:
        print(f"\n  No GO configs found")

    print(f"\n  Output: {output_base}")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description='4H Sweep Runner — regime-aware')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--data', default=None)
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--only', default=None)
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()
