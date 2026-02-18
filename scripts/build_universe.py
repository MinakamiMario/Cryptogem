#!/usr/bin/env python3
"""
Build Universe — Filter coins by minimum bar count and liquidity proxy.

Usage:
    python3 scripts/build_universe.py \\
        --dataset ohlcv_4h_kraken_spot_usd_526 \\
        --min-bars 360 \\
        --output strategies/4h/universe_sprint1.json

    python3 scripts/build_universe.py \\
        --dataset /path/to/candle_cache.json \\
        --min-bars 360 \\
        --min-median-vol 1000 \\
        --output strategies/4h/universe_sprint1.json
"""
from __future__ import annotations

import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import importlib
_data_resolver = importlib.import_module('strategies.4h.data_resolver')
resolve_dataset = _data_resolver.resolve_dataset


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def build_universe(
    data: dict,
    min_bars: int = 360,
    min_median_vol: float = 0.0,
) -> tuple[list[str], dict]:
    """Filter coins by bar count and liquidity.

    Returns (coins, stats) where stats has rejection reasons.
    """
    stats = {"total": 0, "rejected_bars": 0, "rejected_vol": 0, "accepted": 0}
    coins = []

    for pair in sorted(data.keys()):
        if pair.startswith("_"):
            continue
        stats["total"] += 1
        candles = data[pair]

        # Filter 1: minimum bar count
        if len(candles) < min_bars:
            stats["rejected_bars"] += 1
            continue

        # Filter 2: liquidity proxy (median volume over last min_bars)
        if min_median_vol > 0:
            vols = []
            for c in candles[-min_bars:]:
                v = c.get("volume", 0) if isinstance(c, dict) else 0
                vols.append(v)
            med_vol = median(vols) if vols else 0
            if med_vol < min_median_vol:
                stats["rejected_vol"] += 1
                continue

        coins.append(pair)

    stats["accepted"] = len(coins)
    return coins, stats


def main():
    parser = argparse.ArgumentParser(
        description="Build trading universe by filtering coins on bar count and liquidity",
    )
    parser.add_argument(
        "--dataset", required=True,
        help="Dataset ID (registry) or path to candle cache JSON",
    )
    parser.add_argument(
        "--min-bars", type=int, default=360,
        help="Minimum number of bars required (default: 360)",
    )
    parser.add_argument(
        "--min-median-vol", type=float, default=0.0,
        help="Minimum median volume over last min-bars (0 = disabled)",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output JSON file path",
    )
    args = parser.parse_args()

    # Resolve dataset
    dataset_arg = args.dataset
    try:
        dataset_path = resolve_dataset(dataset_arg)
        dataset_id = dataset_arg
    except (FileNotFoundError, KeyError):
        dataset_path = Path(dataset_arg)
        dataset_id = str(dataset_path)
        if not dataset_path.exists():
            print(f"ERROR: Dataset not found: {dataset_arg}", file=sys.stderr)
            sys.exit(1)

    print(f"Loading dataset: {dataset_path}")
    with open(dataset_path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} entries")

    # Build universe
    coins, stats = build_universe(
        data,
        min_bars=args.min_bars,
        min_median_vol=args.min_median_vol,
    )

    # Build output
    output = {
        "coins": coins,
        "meta": {
            "dataset_id": dataset_id,
            "dataset_path": str(dataset_path),
            "min_bars": args.min_bars,
            "min_median_vol": args.min_median_vol,
            "count": len(coins),
            "stats": stats,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_hash": _git_hash(),
        },
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nUniverse built: {len(coins)} coins")
    print(f"  Total: {stats['total']}")
    print(f"  Rejected (bars < {args.min_bars}): {stats['rejected_bars']}")
    print(f"  Rejected (vol < {args.min_median_vol}): {stats['rejected_vol']}")
    print(f"  Accepted: {stats['accepted']}")
    print(f"  Output: {out_path}")


if __name__ == "__main__":
    main()
