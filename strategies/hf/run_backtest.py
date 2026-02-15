#!/usr/bin/env python3
"""
HF Smoke Run — backtest all HF hypotheses against shared engine (read-only).

Usage:
    python strategies/hf/run_backtest.py              # smoke run → reports/hf/
    python strategies/hf/run_backtest.py --universe tradeable
    python strategies/hf/run_backtest.py --universe live

Outputs:
    reports/hf/smoke.json   — raw results per hypothesis + GRID_BEST baseline
    reports/hf/smoke.md     — human-readable comparison table
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime

# --- Path setup (read-only import from trading_bot/) ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import precompute_all, run_backtest, normalize_cfg  # noqa: E402

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# --- Import hypotheses ---
from hf_strategy import HYPOTHESES, GRID_BEST_REF  # noqa: E402


def load_data(universe: str) -> tuple:
    """Load candle data and return (data_dict, sorted_coins)."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        # Fallback: try live cache in trading_bot/
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        print(f"  Tried: {DATA_FILES.get(universe, 'N/A')}")
        print(f"  Tried: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def run_hypothesis(name: str, cfg: dict, indicators: dict, coins: list) -> dict:
    """Run a single hypothesis config through the shared backtest engine."""
    t0 = time.time()
    result = run_backtest(indicators, coins, cfg)
    elapsed = time.time() - t0

    # Extract exit reason breakdown
    exit_reasons = {}
    for t in result.get("trade_list", []):
        r = t["reason"]
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    return {
        "name": name,
        "cfg": cfg,
        "trades": result["trades"],
        "wr": round(result["wr"], 1),
        "pnl": round(result["pnl"], 2),
        "final_equity": round(result["final_equity"], 2),
        "pf": round(result["pf"], 2) if result["pf"] != float("inf") else "inf",
        "dd": round(result["dd"], 1),
        "exit_reasons": exit_reasons,
        "elapsed_s": round(elapsed, 2),
    }


def generate_markdown(results: list, universe: str, data_path: str, total_time: float) -> str:
    """Generate human-readable markdown comparison."""
    lines = [
        "# HF Smoke Run Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Universe**: {universe}",
        f"**Data**: `{Path(data_path).name}`",
        f"**Total time**: {total_time:.1f}s",
        "",
        "## Hypothesis Comparison",
        "",
        "| Hypothesis | Trades | WR% | P&L | PF | DD% | Time |",
        "|------------|--------|-----|-----|----|-----|------|",
    ]

    for r in results:
        pf_str = str(r["pf"]) if r["pf"] != "inf" else "inf"
        lines.append(
            f"| {r['name']} | {r['trades']} | {r['wr']}% "
            f"| ${r['pnl']:+,.0f} | {pf_str} | {r['dd']}% | {r['elapsed_s']:.1f}s |"
        )

    lines.extend([
        "",
        "## Exit Reason Breakdown",
        "",
    ])

    for r in results:
        lines.append(f"### {r['name']}")
        if r["exit_reasons"]:
            lines.append("| Reason | Count |")
            lines.append("|--------|-------|")
            for reason, count in sorted(r["exit_reasons"].items(), key=lambda x: -x[1]):
                lines.append(f"| {reason} | {count} |")
        else:
            lines.append("_(no trades)_")
        lines.append("")

    lines.extend([
        "## Configs",
        "",
    ])
    for r in results:
        lines.append(f"**{r['name']}**: `{json.dumps(r['cfg'], sort_keys=True)}`")
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="HF Smoke Run")
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print(f"=== HF Smoke Run (universe={args.universe}) ===")

    # 1. Load data
    data, coins, data_path = load_data(args.universe)
    print(f"  Loaded {len(coins)} coins from {Path(data_path).name}")

    # 2. Precompute indicators
    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time() - t0:.1f}s")

    # 3. Run GRID_BEST baseline
    print("  Running GRID_BEST baseline...")
    results = [run_hypothesis("GRID_BEST_baseline", GRID_BEST_REF, indicators, coins)]

    # 4. Run each hypothesis
    for name, h in HYPOTHESES.items():
        print(f"  Running {name}...")
        results.append(run_hypothesis(name, h["cfg"], indicators, coins))

    total_time = time.time() - t0

    # 5. Write reports
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    smoke_json = REPORTS_DIR / "smoke.json"
    with open(smoke_json, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "universe": args.universe,
                "data_file": str(data_path),
                "n_coins": len(coins),
                "total_time_s": round(total_time, 2),
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"  Wrote {smoke_json}")

    smoke_md = REPORTS_DIR / "smoke.md"
    md = generate_markdown(results, args.universe, data_path, total_time)
    with open(smoke_md, "w") as f:
        f.write(md)
    print(f"  Wrote {smoke_md}")

    # 6. Summary
    print("\n=== Results ===")
    print(f"{'Name':<25} {'Trades':>6} {'WR%':>5} {'P&L':>10} {'PF':>6} {'DD%':>5}")
    print("-" * 65)
    for r in results:
        pf_str = f"{r['pf']}" if r["pf"] != "inf" else "inf"
        print(f"{r['name']:<25} {r['trades']:>6} {r['wr']:>5} ${r['pnl']:>+9,.0f} {pf_str:>6} {r['dd']:>5}")

    print(f"\nDone in {total_time:.1f}s")


if __name__ == "__main__":
    main()
