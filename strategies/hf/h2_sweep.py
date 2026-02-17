#!/usr/bin/env python3
"""
H2 Momentum Burst — Grid Sweep around the H2 hypothesis.

Sweeps vol_spike_mult, rsi_max, tp_pct, sl_pct, time_max_bars around H2 base.
Applies HF gates and friction stress. Outputs top-10 configs.

Usage:
    python strategies/hf/h2_sweep.py
    python strategies/hf/h2_sweep.py --universe live
    python strategies/hf/h2_sweep.py --top 20

Outputs:
    reports/hf/h2_sweep.json   — full grid results + champion
    reports/hf/h2_sweep.md     — top-10 table + friction results

HF Gates:
    - trades >= 20
    - PF >= 1.6
    - DD <= 30%
    - friction_2x20bps P&L > 0
    - friction_1candle P&L > 0
"""

import sys
import json
import time
import itertools
from pathlib import Path
from datetime import datetime

# --- Path setup (read-only import from trading_bot/) ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE,
)

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# --- HF Gates ---
MIN_TRADES = 20
MIN_PF = 1.6
MAX_DD = 30.0

# Friction regimes
FEE_2X_20BPS = KRAKEN_FEE * 2 + 0.0020     # 2x fees + 20bps slippage
FEE_1CANDLE = KRAKEN_FEE * 2 + 0.0050      # 1-candle-later fill

# --- Grid Definition ---
# Sweep around H2 base: vs4.0, rsi55, tp15, sl8, tm12
GRID = {
    "vol_spike_mult": [3.0, 3.5, 4.0, 4.5, 5.0],
    "rsi_max": [45, 50, 55, 60],
    "tp_pct": [10, 12, 15, 18],
    "sl_pct": [6, 8, 10, 12],
    "time_max_bars": [8, 10, 12, 15],
}

# Fixed params
FIXED = {
    "exit_type": "tp_sl",
    "max_pos": 1,
    "vol_confirm": True,
}


def generate_configs():
    """Generate all grid configs."""
    keys = sorted(GRID.keys())
    values = [GRID[k] for k in keys]
    configs = []
    for combo in itertools.product(*values):
        cfg = dict(FIXED)
        for k, v in zip(keys, combo):
            cfg[k] = v
        configs.append(normalize_cfg(cfg))
    return configs


def passes_gates(result):
    """Check if a backtest result passes HF gates."""
    return (
        result["trades"] >= MIN_TRADES
        and result["pf"] >= MIN_PF
        and result["dd"] <= MAX_DD
    )


def run_friction(cfg, indicators, coins):
    """Run friction stress tests. Returns dict with P&L at each regime."""
    r_2x20 = run_backtest(indicators, coins, cfg, fee_override=FEE_2X_20BPS)
    r_1c = run_backtest(indicators, coins, cfg, fee_override=FEE_1CANDLE)
    return {
        "pnl_2x20bps": round(r_2x20["pnl"], 2),
        "pnl_1candle": round(r_1c["pnl"], 2),
        "pass_2x20bps": r_2x20["pnl"] > 0,
        "pass_1candle": r_1c["pnl"] > 0,
    }


def score_config(result, friction):
    """Score a config. Higher = better. Balances P&L, PF, DD, friction."""
    # Weighted composite: P&L dominance + friction safety margin
    pnl_norm = result["pnl"] / 1000.0  # scale
    pf_score = min(result["pf"], 5.0)   # cap PF to avoid outliers
    dd_penalty = max(0, result["dd"] - 15) * 0.1  # penalize DD > 15%
    friction_margin = friction["pnl_1candle"] / 500.0  # friction headroom
    return round(pnl_norm + pf_score + friction_margin - dd_penalty, 3)


def load_data(universe):
    """Load candle data."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def generate_markdown(top_results, champion, meta):
    """Generate human-readable markdown."""
    lines = [
        "# H2 Momentum Burst — Grid Sweep Results",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Grid size**: {meta['total_configs']} configs",
        f"**Gate-passed**: {meta['gate_passed']} configs",
        f"**Friction-passed**: {meta['friction_passed']} configs",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
        "## HF Gates",
        f"- Trades >= {MIN_TRADES}",
        f"- PF >= {MIN_PF}",
        f"- DD <= {MAX_DD}%",
        f"- Friction 2x+20bps P&L > $0",
        f"- Friction 1-candle-later P&L > $0",
        "",
        "## Top 10 Configs (by composite score)",
        "",
        "| # | Score | Trades | WR% | P&L | PF | DD% | 2x20 P&L | 1c P&L | vs | rsi | tp | sl | tm |",
        "|---|-------|--------|-----|-----|----|-----|-----------|--------|----|-----|----|----|-----|",
    ]

    for i, r in enumerate(top_results[:10], 1):
        c = r["cfg"]
        f = r["friction"]
        lines.append(
            f"| {i} | {r['score']} | {r['trades']} | {r['wr']}% "
            f"| ${r['pnl']:+,.0f} | {r['pf']} | {r['dd']}% "
            f"| ${f['pnl_2x20bps']:+,.0f} | ${f['pnl_1candle']:+,.0f} "
            f"| {c['vol_spike_mult']} | {c['rsi_max']} | {c['tp_pct']} "
            f"| {c['sl_pct']} | {c['time_max_bars']} |"
        )

    if champion:
        lines.extend([
            "",
            "## Champion H2",
            "",
            f"**Score**: {champion['score']}",
            f"**Config**: `{json.dumps(champion['cfg'], sort_keys=True)}`",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Trades | {champion['trades']} |",
            f"| Win Rate | {champion['wr']}% |",
            f"| P&L | ${champion['pnl']:+,.2f} |",
            f"| Profit Factor | {champion['pf']} |",
            f"| Max DD | {champion['dd']}% |",
            f"| P&L @2x+20bps | ${champion['friction']['pnl_2x20bps']:+,.2f} |",
            f"| P&L @1-candle | ${champion['friction']['pnl_1candle']:+,.2f} |",
        ])

        lines.extend([
            "",
            "## Exit Reason Breakdown (Champion)",
            "",
            "| Reason | Count |",
            "|--------|-------|",
        ])
        for reason, count in sorted(
            champion["exit_reasons"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {reason} | {count} |")

    lines.extend([
        "",
        "## Grid Axes",
        "",
    ])
    for k, v in sorted(GRID.items()):
        lines.append(f"- **{k}**: {v}")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="H2 Momentum Burst Grid Sweep")
    parser.add_argument(
        "--universe", choices=["tradeable", "live"],
        default="tradeable",
    )
    parser.add_argument("--top", type=int, default=10, help="Show top N")
    args = parser.parse_args()

    print(f"=== H2 Momentum Burst Grid Sweep (universe={args.universe}) ===")

    # 1. Load data
    data, coins, data_path = load_data(args.universe)
    print(f"  Loaded {len(coins)} coins from {Path(data_path).name}")

    # 2. Precompute
    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    t_precompute = time.time() - t0
    print(f"  Precompute: {t_precompute:.1f}s")

    # 3. Generate grid
    configs = generate_configs()
    print(f"  Grid: {len(configs)} configs")

    # 4. Run all configs (baseline)
    print("  Running baseline backtests...")
    results = []
    for i, cfg in enumerate(configs):
        if (i + 1) % 100 == 0:
            print(f"    {i+1}/{len(configs)}...")
        bt = run_backtest(indicators, coins, cfg)

        exit_reasons = {}
        for t in bt.get("trade_list", []):
            r = t["reason"]
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

        entry = {
            "cfg": cfg,
            "trades": bt["trades"],
            "wr": round(bt["wr"], 1),
            "pnl": round(bt["pnl"], 2),
            "pf": round(bt["pf"], 2) if bt["pf"] != float("inf") else 99.0,
            "dd": round(bt["dd"], 1),
            "exit_reasons": exit_reasons,
        }
        results.append(entry)

    t_baseline = time.time() - t0 - t_precompute
    print(f"  Baseline sweep: {t_baseline:.1f}s")

    # 5. Apply HF gates
    gated = [r for r in results if passes_gates(r)]
    print(f"  Gate-passed: {len(gated)}/{len(results)}")

    if not gated:
        print("  WARNING: No configs passed HF gates. Relaxing to top-10 by P&L.")
        gated = sorted(results, key=lambda x: -x["pnl"])[:10]

    # 6. Run friction on gate-passed configs
    print(f"  Running friction tests on {len(gated)} configs...")
    for r in gated:
        r["friction"] = run_friction(r["cfg"], indicators, coins)

    # 7. Filter friction-passed
    friction_passed = [
        r for r in gated
        if r["friction"]["pass_2x20bps"] and r["friction"]["pass_1candle"]
    ]
    print(f"  Friction-passed: {len(friction_passed)}/{len(gated)}")

    # 8. Score and rank
    candidates = friction_passed if friction_passed else gated
    for r in candidates:
        if "friction" not in r:
            r["friction"] = run_friction(r["cfg"], indicators, coins)
        r["score"] = score_config(r, r["friction"])

    candidates.sort(key=lambda x: -x["score"])
    champion = candidates[0] if candidates else None

    total_time = time.time() - t0

    # 9. Write reports
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "total_configs": len(configs),
        "gate_passed": len([r for r in results if passes_gates(r)]),
        "friction_passed": len(friction_passed),
        "total_time_s": round(total_time, 2),
    }

    json_path = REPORTS_DIR / "h2_sweep.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "meta": meta,
                "champion": champion,
                "top": candidates[: args.top],
                "grid": GRID,
                "gates": {
                    "min_trades": MIN_TRADES,
                    "min_pf": MIN_PF,
                    "max_dd": MAX_DD,
                },
            },
            f,
            indent=2,
        )
    print(f"  Wrote {json_path}")

    md_path = REPORTS_DIR / "h2_sweep.md"
    md = generate_markdown(candidates, champion, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 10. Summary
    if champion:
        c = champion["cfg"]
        f = champion["friction"]
        print(f"\n=== Champion H2 ===")
        print(f"  Config: vs={c['vol_spike_mult']} rsi={c['rsi_max']} "
              f"tp={c['tp_pct']} sl={c['sl_pct']} tm={c['time_max_bars']}")
        print(f"  Trades={champion['trades']} WR={champion['wr']}% "
              f"P&L=${champion['pnl']:+,.0f} PF={champion['pf']} DD={champion['dd']}%")
        print(f"  Friction: 2x+20bps=${f['pnl_2x20bps']:+,.0f} "
              f"1-candle=${f['pnl_1candle']:+,.0f}")
        print(f"  Score: {champion['score']}")
    else:
        print("\n  WARNING: No champion found.")

    print(f"\nDone in {total_time:.1f}s")


if __name__ == "__main__":
    main()
