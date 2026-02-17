#!/usr/bin/env python3
"""
4H DualConfirm Strategy — CLI Runner
-------------------------------------
Thin wrapper around trading_bot/agent_team_v3.py run_backtest().

Usage:
    python -m strategies.4h.runner --config BASELINE --run-id test001
    python -m strategies.4h.runner --config path/to/custom.json --run-id sweep_42
    python -m strategies.4h.runner --config HYBRID_NOTRL --run-id notrl_v1 --output-dir /tmp/results

Output:
    reports/4h/<run_id>/results.json   — full backtest results + metadata
    reports/4h/<run_id>/results.md     — human-readable summary
    reports/4h/<run_id>/params.json    — config used (normalized)
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path setup — ensure trading_bot is importable
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'trading_bot') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'trading_bot'))

from agent_team_v3 import (
    run_backtest, precompute_all, normalize_cfg,
    INITIAL_CAPITAL, KRAKEN_FEE, START_BAR,
)
from .configs import get_config, list_configs, CONFIGS

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


def _load_config(config_arg: str) -> tuple[dict, str]:
    """Load config by name or from JSON file. Returns (cfg_dict, source_label)."""
    # Try as named config first
    if config_arg.upper() in CONFIGS:
        return get_config(config_arg), config_arg.upper()

    # Try as JSON file path
    config_path = Path(config_arg)
    if config_path.exists() and config_path.suffix == '.json':
        with open(config_path) as f:
            cfg = json.load(f)
        return normalize_cfg(dict(cfg)), str(config_path)

    # Neither — error
    available = ', '.join(list_configs())
    raise ValueError(
        f"Config '{config_arg}' is not a known preset ({available}) "
        f"and is not a path to an existing .json file."
    )


def _resolve_dataset(dataset_id: str | None) -> tuple[Path, str]:
    """Resolve dataset identifier to a file path.

    For now, only supports the default 532-coin cache.
    Future: integrate with ~/CryptogemData/manifests/registry.json.
    """
    if dataset_id is None or dataset_id == 'default':
        return DEFAULT_CACHE, 'candle_cache_532 (default)'

    # Try as direct path
    p = Path(dataset_id)
    if p.exists():
        return p, str(p)

    raise FileNotFoundError(
        f"Dataset '{dataset_id}' not found. Use 'default' or provide a path to a JSON cache file."
    )


def _build_metadata(
    cfg: dict,
    config_source: str,
    dataset_path: Path,
    dataset_label: str,
    run_id: str,
    n_coins: int,
    elapsed_s: float,
) -> dict:
    """Build metadata dict for results output."""
    return {
        'run_id': run_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'git_hash': _git_hash(),
        'config_source': config_source,
        'dataset': dataset_label,
        'dataset_path': str(dataset_path),
        'exchange': 'kraken',
        'fee_bps': round(KRAKEN_FEE * 10000, 1),
        'initial_capital': INITIAL_CAPITAL,
        'start_bar': START_BAR,
        'n_coins': n_coins,
        'elapsed_s': round(elapsed_s, 2),
        'engine': 'agent_team_v3.run_backtest',
    }


def _format_results_md(bt: dict, meta: dict, cfg: dict) -> str:
    """Generate a human-readable markdown summary."""
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
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {bt['trades']} |",
        f"| Win Rate | {bt['wr']:.1f}% |",
        f"| P&L | ${bt['pnl']:+,.2f} |",
        f"| Final Equity | ${bt['final_equity']:,.2f} |",
        f"| Profit Factor | {bt['pf']:.2f} |",
        f"| Max Drawdown | {bt['dd']:.1f}% |",
        f"| Broke | {'YES' if bt['broke'] else 'No'} |",
        "",
        "## Exit Classes",
    ]

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


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> dict:
    """Execute a single backtest run and write results."""
    # 1. Load config
    cfg, config_source = _load_config(args.config)
    print(f"  Config: {config_source}")
    print(f"  Params: {json.dumps(cfg, sort_keys=True)}")

    # 2. Resolve dataset
    dataset_path, dataset_label = _resolve_dataset(args.dataset_id)
    print(f"  Dataset: {dataset_label}")

    # 3. Load data
    print(f"  Loading data from {dataset_path}...")
    t0 = time.time()
    with open(dataset_path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"  {len(coins)} coins loaded ({time.time() - t0:.1f}s)")

    # 4. Precompute indicators
    print(f"  Precomputing indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time() - t1:.1f}s")

    # 5. Run backtest
    print(f"  Running backtest...")
    t2 = time.time()
    bt = run_backtest(indicators, coins, cfg)
    elapsed_bt = time.time() - t2
    elapsed_total = time.time() - t0
    print(f"  Backtest: {elapsed_bt:.1f}s")

    # 6. Build metadata
    meta = _build_metadata(
        cfg=cfg,
        config_source=config_source,
        dataset_path=dataset_path,
        dataset_label=dataset_label,
        run_id=args.run_id,
        n_coins=len(coins),
        elapsed_s=elapsed_total,
    )

    # 7. Prepare output directory
    output_dir = Path(args.output_dir) / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # 8. Write results.json (bt + meta, trade_list serialized)
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
        'trades': [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
            for t in bt['trade_list']
        ],
    }
    results_json_path = output_dir / 'results.json'
    with open(results_json_path, 'w') as f:
        json.dump(results_payload, f, indent=2, default=str)
    print(f"  Wrote: {results_json_path}")

    # 9. Write params.json
    params_path = output_dir / 'params.json'
    with open(params_path, 'w') as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
    print(f"  Wrote: {params_path}")

    # 10. Write results.md
    md_path = output_dir / 'results.md'
    md_content = _format_results_md(bt, meta, cfg)
    with open(md_path, 'w') as f:
        f.write(md_content)
    print(f"  Wrote: {md_path}")

    # 11. Print summary
    print(f"\n  === RESULTS ===")
    print(f"  Trades: {bt['trades']} | WR: {bt['wr']:.1f}% | P&L: ${bt['pnl']:+,.2f}")
    print(f"  PF: {bt['pf']:.2f} | DD: {bt['dd']:.1f}% | Equity: ${bt['final_equity']:,.2f}")
    print(f"  Output: {output_dir}")

    return results_payload


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='strategies.4h.runner',
        description='4H DualConfirm Strategy — single-config backtest runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m strategies.4h.runner --config BASELINE --run-id test001\n"
            "  python -m strategies.4h.runner --config BEST_KNOWN --run-id bk_v1\n"
            "  python -m strategies.4h.runner --config /path/to/custom.json --run-id custom01\n"
            "  python -m strategies.4h.runner --config HYBRID_NOTRL --run-id notrl --output-dir /tmp/bt\n"
            f"\nAvailable named configs: {', '.join(list_configs())}"
        ),
    )
    parser.add_argument(
        '--config', required=True,
        help='Config name (BASELINE, BEST_KNOWN, HYBRID_NOTRL) or path to .json file',
    )
    parser.add_argument(
        '--run-id', required=True,
        help='Unique run identifier (used as output subdirectory name)',
    )
    parser.add_argument(
        '--dataset-id', default=None,
        help='Dataset identifier or path (default: candle_cache_532.json)',
    )
    parser.add_argument(
        '--output-dir', default=str(DEFAULT_OUTPUT),
        help=f'Base output directory (default: {DEFAULT_OUTPUT})',
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    print(f"\n{'='*60}")
    print(f"  4H DualConfirm Runner — {args.run_id}")
    print(f"{'='*60}")
    run(args)


if __name__ == '__main__':
    main()
