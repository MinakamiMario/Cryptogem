#!/usr/bin/env python3
"""
4H Sweep Runner — Batch executor for sweep_plan_v1.json

Reads a sweep plan, runs each config through the 4H backtest engine,
applies gates-lite validation, and writes per-run results.

Usage:
    python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json
    python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --force
    python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --dry-run
    python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --only 1,5,12
    python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --data reports/4h/windows/candle_cache_early_360.json

Key features:
    - Precomputes indicators ONCE (saves ~50s per run)
    - Idempotent: skips completed runs (use --force to override)
    - Applies gates-lite after each backtest
    - Writes results + gates to reports/4h/<run_id>/
    - Prints progress with timing
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
# Path setup — ensure trading_bot and strategies are importable
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'trading_bot') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'trading_bot'))

from agent_team_v3 import (
    run_backtest, precompute_all, normalize_cfg,
    INITIAL_CAPITAL, KRAKEN_FEE, START_BAR,
)

# strategies/4h/ starts with a digit — can't use dotted import syntax
_gates_mod = importlib.import_module('strategies.4h.gates_4h')
evaluate_gates = _gates_mod.evaluate_gates
gates_to_dict = _gates_mod.gates_to_dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CACHE = REPO_ROOT / 'trading_bot' / 'candle_cache_532.json'
DEFAULT_OUTPUT = REPO_ROOT / 'reports' / '4h'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_hash() -> str:
    """Return short git commit hash, or 'unknown' if not in a repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def _build_run_id(idx: int, label: str, git_short: str) -> str:
    """Build run_id per contract: sweep_v1_{idx:03d}_{label}_{gitshort}."""
    # Sanitize label: max 30 chars, lowercase, replace spaces with underscores
    safe_label = label.strip().lower().replace(' ', '_').replace('-', '_')
    safe_label = safe_label[:30]
    return f"sweep_v1_{idx:03d}_{safe_label}_{git_short}"


def _build_metadata(
    cfg: dict,
    config_label: str,
    dataset_path: Path,
    run_id: str,
    n_coins: int,
    elapsed_s: float,
    sweep_plan_path: str,
    sweep_idx: int,
) -> dict:
    """Build metadata dict for results output."""
    return {
        'run_id': run_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'git_hash': _git_hash(),
        'config_source': f'sweep_plan:{config_label} (idx={sweep_idx})',
        'dataset': 'candle_cache_532',
        'dataset_path': str(dataset_path),
        'exchange': 'kraken',
        'fee_bps': round(KRAKEN_FEE * 10000, 1),
        'initial_capital': INITIAL_CAPITAL,
        'start_bar': START_BAR,
        'n_coins': n_coins,
        'elapsed_s': round(elapsed_s, 2),
        'engine': 'agent_team_v3.run_backtest',
        'sweep_plan': sweep_plan_path,
        'sweep_index': sweep_idx,
    }


def _format_results_md(bt: dict, meta: dict, cfg: dict, gate_report_dict: dict) -> str:
    """Generate a human-readable markdown summary including gates."""
    lines = [
        f"# 4H DualConfirm Backtest — {meta['run_id']}",
        "",
        "## Metadata",
        f"- **Timestamp**: {meta['timestamp']}",
        f"- **Git**: {meta['git_hash']}",
        f"- **Config**: {meta['config_source']}",
        f"- **Dataset**: {meta['dataset']} ({meta['n_coins']} coins)",
        f"- **Exchange**: {meta['exchange']} (fee: {meta['fee_bps']} bps/side)",
        f"- **Initial Capital**: ${meta['initial_capital']}",
        f"- **Elapsed**: {meta['elapsed_s']:.1f}s",
        "",
        "## Results",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Trades | {bt['trades']} |",
        f"| Win Rate | {bt['wr']:.1f}% |",
        f"| P&L | ${bt['pnl']:+,.2f} |",
        f"| Final Equity | ${bt['final_equity']:,.2f} |",
        f"| Profit Factor | {bt['pf']:.2f} |",
        f"| Max Drawdown | {bt['dd']:.1f}% |",
        f"| Broke | {'YES' if bt['broke'] else 'No'} |",
        "",
        "## Gates-Lite",
        f"- **Verdict**: {gate_report_dict['verdict']}",
        f"- **Passed**: {gate_report_dict['n_passed']}/{gate_report_dict['n_total']}",
        "",
        "| Gate | Result | Detail |",
        "|------|--------|--------|",
    ]
    for g in gate_report_dict.get('gates', []):
        mark = "PASS" if g['passed'] else "FAIL"
        lines.append(f"| {g['name']} | {mark} | {g['detail']} |")

    lines.extend([
        "",
        "## Exit Classes",
    ])

    for cls_name in ['A', 'B']:
        cls = bt.get('exit_classes', {}).get(cls_name, {})
        if cls:
            lines.append(f"\n### Class {cls_name}")
            lines.append("| Reason | Count | P&L | Wins |")
            lines.append("|--------|-------|-----|------|")
            for reason, stats in sorted(cls.items()):
                lines.append(
                    f"| {reason} | {stats['count']} | ${stats['pnl']:+,.2f} | {stats['wins']} |"
                )

    lines.extend([
        "",
        "## Config",
        "```json",
        json.dumps(cfg, indent=2, sort_keys=True),
        "```",
        "",
    ])

    return '\n'.join(lines)


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def _progress_bar(current: int, total: int, width: int = 30) -> str:
    """Build a simple ASCII progress bar."""
    filled = int(width * current / total) if total > 0 else 0
    bar = '#' * filled + '-' * (width - filled)
    pct = current / total * 100 if total > 0 else 0
    return f"[{bar}] {current}/{total} ({pct:.0f}%)"


# ---------------------------------------------------------------------------
# Core sweep execution
# ---------------------------------------------------------------------------

def run_sweep(args: argparse.Namespace) -> dict:
    """Execute the full sweep plan and return a summary dict."""

    # 1. Load sweep plan
    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"ERROR: Sweep plan not found: {plan_path}")
        sys.exit(1)

    with open(plan_path) as f:
        sweep_plan = json.load(f)

    configs = sweep_plan.get('configs', sweep_plan)
    if isinstance(configs, dict):
        # If the plan is a single dict with a 'configs' key containing a list
        configs = configs if isinstance(configs, list) else [configs]
    if not isinstance(configs, list):
        print(f"ERROR: Sweep plan must contain a list of configs (got {type(configs).__name__})")
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print(f"  4H Sweep Runner")
    print(f"{'=' * 70}")
    print(f"  Plan: {plan_path} ({len(configs)} configs)")
    print(f"  Output: {args.output_dir}")
    print(f"  Force: {args.force}")
    print(f"  Dry-run: {args.dry_run}")

    # 2. Filter by --only indices if specified
    only_indices = None
    if args.only:
        only_indices = set()
        for part in args.only.split(','):
            part = part.strip()
            if part.isdigit():
                only_indices.add(int(part))
        print(f"  Only: indices {sorted(only_indices)}")

    # 3. Git hash (computed once)
    git_short = _git_hash()
    print(f"  Git: {git_short}")

    output_base = Path(args.output_dir)

    # 4. Dry-run mode: just print what would run
    if args.dry_run:
        print(f"\n  DRY RUN — would execute:\n")
        for i, entry in enumerate(configs):
            idx = entry.get('idx', i + 1)
            label = entry.get('label', f'config_{idx}')
            run_id = _build_run_id(idx, label, git_short)
            results_path = output_base / run_id / 'results.json'
            exists = results_path.exists()

            if only_indices and idx not in only_indices:
                status = "SKIP (not in --only)"
            elif exists and not args.force:
                status = "SKIP (exists)"
            else:
                status = "RUN"

            cfg_summary = entry.get('params', entry.get('cfg', entry.get('config', {})))
            exit_type = cfg_summary.get('exit_type', '?')
            rsi_max = cfg_summary.get('rsi_max', '?')
            print(f"  [{status:18s}] {run_id}  exit={exit_type} rsi={rsi_max}")
        print(f"\n  Total: {len(configs)} configs")
        return {'dry_run': True, 'total': len(configs)}

    # 5. Load candle data
    dataset_path = Path(args.data) if args.data else DEFAULT_CACHE
    print(f"\n  Loading data from {dataset_path}...")
    t_load = time.time()
    with open(dataset_path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    n_coins = len(coins)
    print(f"  {n_coins} coins loaded ({time.time() - t_load:.1f}s)")

    # 6. Precompute indicators ONCE
    print(f"  Precomputing indicators...")
    t_precompute = time.time()
    indicators = precompute_all(data, coins)
    precompute_elapsed = time.time() - t_precompute
    print(f"  Precompute: {precompute_elapsed:.1f}s")

    # Free the raw data — we only need indicators from here
    del data

    # 7. Main loop
    t_sweep_start = time.time()
    results_summary = []
    n_completed = 0
    n_skipped = 0
    n_failed = 0
    n_total = len(configs)

    print(f"\n{'=' * 70}")
    print(f"  Starting sweep: {n_total} configs")
    print(f"{'=' * 70}\n")

    for i, entry in enumerate(configs):
        idx = entry.get('idx', i + 1)
        label = entry.get('label', f'config_{idx}')
        cfg_raw = entry.get('params', entry.get('cfg', entry.get('config', {})))
        run_id = _build_run_id(idx, label, git_short)

        # Filter by --only
        if only_indices and idx not in only_indices:
            n_skipped += 1
            continue

        # Progress header
        elapsed_so_far = time.time() - t_sweep_start
        done_count = n_completed + n_skipped + n_failed
        if done_count > 0 and n_completed > 0:
            avg_per_run = elapsed_so_far / n_completed
            remaining = (n_total - done_count) * avg_per_run
            eta_str = f"ETA {_format_elapsed(remaining)}"
        else:
            eta_str = "ETA --"

        progress = _progress_bar(done_count, n_total)
        print(f"  {progress} {eta_str}")
        print(f"  [{idx:03d}] {label}")

        # Idempotency check
        run_dir = output_base / run_id
        results_json_path = run_dir / 'results.json'
        if results_json_path.exists() and not args.force:
            print(f"        SKIP (results.json exists)")
            n_skipped += 1
            results_summary.append({
                'idx': idx, 'label': label, 'run_id': run_id,
                'status': 'skipped', 'reason': 'exists',
            })
            continue

        # Run backtest
        try:
            cfg = normalize_cfg(dict(cfg_raw))
            t_run = time.time()
            bt = run_backtest(indicators, coins, cfg)
            bt_elapsed = time.time() - t_run
            total_elapsed = time.time() - t_load

            # Build metadata
            meta = _build_metadata(
                cfg=cfg,
                config_label=label,
                dataset_path=dataset_path,
                run_id=run_id,
                n_coins=n_coins,
                elapsed_s=bt_elapsed,
                sweep_plan_path=str(plan_path),
                sweep_idx=idx,
            )

            # Evaluate gates
            gate_report = evaluate_gates(bt)
            gate_dict = gates_to_dict(gate_report)

            # Prepare output directory
            run_dir.mkdir(parents=True, exist_ok=True)

            # Write results.json (bt + meta + gates)
            results_payload = {
                'metadata': meta,
                'summary': {
                    'trades': bt['trades'],
                    'wr': round(bt['wr'], 2),
                    'pnl': round(bt['pnl'], 2),
                    'final_equity': round(bt['final_equity'], 2),
                    'pf': round(bt['pf'], 4),
                    'dd': round(bt['dd'], 2),
                    'broke': bt['broke'],
                    'early_stopped': bt['early_stopped'],
                },
                'exit_classes': bt['exit_classes'],
                'trade_count': bt['trades'],
                'gates': gate_dict,
                'trades': [
                    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
                    for t in bt['trade_list']
                ],
            }

            with open(results_json_path, 'w') as f:
                json.dump(results_payload, f, indent=2, default=str)

            # Write params.json
            params_path = run_dir / 'params.json'
            with open(params_path, 'w') as f:
                json.dump(cfg, f, indent=2, sort_keys=True)

            # Write results.md
            md_path = run_dir / 'results.md'
            md_content = _format_results_md(bt, meta, cfg, gate_dict)
            with open(md_path, 'w') as f:
                f.write(md_content)

            # Write gates.json
            gates_path = run_dir / 'gates.json'
            with open(gates_path, 'w') as f:
                json.dump(gate_dict, f, indent=2)

            # One-line summary
            verdict = gate_dict['verdict']
            gates_str = f"{gate_dict['n_passed']}/{gate_dict['n_total']}"
            ev_per_trade = bt['pnl'] / bt['trades'] if bt['trades'] > 0 else 0
            print(
                f"        {bt['trades']:3d}tr | "
                f"WR {bt['wr']:5.1f}% | "
                f"P&L ${bt['pnl']:+8,.2f} | "
                f"PF {bt['pf']:5.2f} | "
                f"DD {bt['dd']:5.1f}% | "
                f"EV ${ev_per_trade:+6.1f} | "
                f"Gates {gates_str} {verdict:4s} | "
                f"{bt_elapsed:.2f}s"
            )

            n_completed += 1
            results_summary.append({
                'idx': idx, 'label': label, 'run_id': run_id,
                'status': 'completed',
                'trades': bt['trades'],
                'pnl': round(bt['pnl'], 2),
                'pf': round(bt['pf'], 4),
                'dd': round(bt['dd'], 2),
                'wr': round(bt['wr'], 2),
                'ev_per_trade': round(ev_per_trade, 2),
                'verdict': verdict,
                'gates_passed': gate_dict['n_passed'],
                'gates_total': gate_dict['n_total'],
                'elapsed_s': round(bt_elapsed, 2),
            })

        except Exception as e:
            print(f"        FAILED: {e}")
            n_failed += 1
            results_summary.append({
                'idx': idx, 'label': label, 'run_id': run_id,
                'status': 'failed', 'error': str(e),
            })
            continue

    # 8. Final summary
    total_elapsed = time.time() - t_sweep_start
    print(f"\n{'=' * 70}")
    print(f"  SWEEP COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Completed: {n_completed}")
    print(f"  Skipped:   {n_skipped}")
    print(f"  Failed:    {n_failed}")
    print(f"  Total:     {n_total}")
    print(f"  Precompute: {precompute_elapsed:.1f}s")
    print(f"  Backtests:  {_format_elapsed(total_elapsed)}")
    print(f"  Total wall: {_format_elapsed(time.time() - t_load)}")

    # Print GO configs
    go_configs = [r for r in results_summary if r.get('verdict') == 'GO']
    if go_configs:
        print(f"\n  --- GO CONFIGS ({len(go_configs)}) ---")
        # Sort by PF descending (contract ranking rule)
        go_configs.sort(key=lambda r: (-r.get('pf', 0), -r.get('ev_per_trade', 0),
                                        r.get('dd', 100), -r.get('trades', 0)))
        for rank, r in enumerate(go_configs, 1):
            print(
                f"  #{rank}: [{r['idx']:03d}] {r['label']} | "
                f"{r['trades']}tr PF={r['pf']:.2f} P&L=${r['pnl']:+,.0f} "
                f"DD={r['dd']:.1f}% EV=${r['ev_per_trade']:+.1f}"
            )
    else:
        no_go_count = sum(1 for r in results_summary if r.get('verdict') in ('NO-GO', 'INSUFFICIENT_SAMPLE'))
        print(f"\n  No GO configs found ({no_go_count} NO-GO, {n_failed} failed, {n_skipped} skipped)")

    print(f"\n  Output: {output_base}")
    print(f"{'=' * 70}\n")

    return {
        'completed': n_completed,
        'skipped': n_skipped,
        'failed': n_failed,
        'total': n_total,
        'precompute_s': round(precompute_elapsed, 2),
        'sweep_s': round(total_elapsed, 2),
        'go_count': len(go_configs) if go_configs else 0,
        'results': results_summary,
    }


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='run_4h_sweep',
        description='4H Sweep Runner — batch executor for sweep_plan_v1.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json\n"
            "  python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --force\n"
            "  python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --dry-run\n"
            "  python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --only 1,5,12\n"
        ),
    )
    parser.add_argument(
        '--plan', required=True,
        help='Path to sweep plan JSON file (required)',
    )
    parser.add_argument(
        '--force', action='store_true', default=False,
        help='Re-run all configs, even if results.json already exists',
    )
    parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help='Print what would run without executing backtests',
    )
    parser.add_argument(
        '--output-dir', default=str(DEFAULT_OUTPUT),
        help=f'Base output directory (default: {DEFAULT_OUTPUT})',
    )
    parser.add_argument(
        '--only', default=None,
        help='Comma-separated list of config indices to run (e.g., 1,5,12)',
    )
    parser.add_argument(
        '--data', default=None,
        help='Path to candle cache JSON (default: trading_bot/candle_cache_532.json)',
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()
