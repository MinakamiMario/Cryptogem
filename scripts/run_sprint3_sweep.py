#!/usr/bin/env python3
"""
Sprint 3 Sweep Runner — Exit-Intelligence Porting for 4H strategies.

Tests DualConfirm's proven exit system (DC TARGET + RSI RECOVERY + BB TARGET)
on Sprint 2's best entry signals. Uses Sprint 3 engine with exit_mode='dc'
(hybrid_notrl exits) instead of Sprint 1's fixed TP/SL/TM.

Key differences from Sprint 2 runner:
  - Uses Sprint 3 engine (exit_mode='dc') instead of Sprint 1 engine
  - Uses Sprint 3 hypotheses (entry-adapter configs wrapping Sprint 2 signals)
  - Reuses Sprint 2 indicators (already have dc_mid, bb_mid, rsi for DC exits)
  - Reuses Sprint 2 market context (needed for H4S-03 cross-sectional entries)
  - Reuses Sprint 2 relaxed gates (PF > 1.05 advancement)

Usage:
    python3 scripts/run_sprint3_sweep.py
    python3 scripts/run_sprint3_sweep.py --dry-run
    python3 scripts/run_sprint3_sweep.py --force
    python3 scripts/run_sprint3_sweep.py --only 1,5,12
    python3 scripts/run_sprint3_sweep.py --universe strategies/4h/universe_sprint1.json
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
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

# Import modules (digit-prefixed directory needs importlib)
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_sprint3_hyp = importlib.import_module("strategies.4h.sprint3.hypotheses")
_sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")
_sprint2_gates = importlib.import_module("strategies.4h.sprint2.gates")
_sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

run_backtest = _sprint3_engine.run_backtest
precompute_all = _sprint2_indicators.precompute_all  # Sprint 2 extended (has dc_mid, bb_mid, rsi)
evaluate_gates = _sprint2_gates.evaluate_sprint2_gates
gates_to_dict = _sprint2_gates.gates_to_dict
print_gate_report = _sprint2_gates.print_sprint2_report
build_sweep_configs = _sprint3_hyp.build_sweep_configs
precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
resolve_dataset = _data_resolver.resolve_dataset

# Constants
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "4h"
KRAKEN_FEE = 0.0026


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _run_single(
    cfg: dict,
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
    force: bool = False,
) -> dict | None:
    """Run a single config and write results. Returns result dict or None if skipped."""
    run_id = f"{cfg['id']}_{git_hash}"
    run_dir = output_dir / run_id

    # Idempotent check
    results_path = run_dir / "results.json"
    if results_path.exists() and not force:
        print(f"  SKIP {cfg['id']} (exists, use --force to override)")
        with open(results_path) as f:
            return json.load(f)

    run_dir.mkdir(parents=True, exist_ok=True)

    # Inject __market__ into params (needed for H4S-03 cross-sectional entries)
    enriched_params = {**cfg["params"], "__market__": market_ctx}

    # Run backtest with exit_mode='dc' (DualConfirm hybrid_notrl exits)
    t0 = time.time()
    bt = run_backtest(
        data=data,
        coins=coins,
        signal_fn=cfg["signal_fn"],
        params=enriched_params,
        indicators=indicators,
        exit_mode="dc",
    )
    elapsed = time.time() - t0

    # Evaluate Sprint 2 gates (relaxed PF > 1.05)
    bt_dict = {
        "trades": bt.trades,
        "pnl": bt.pnl,
        "pf": bt.pf,
        "wr": bt.wr,
        "dd": bt.dd,
        "final_equity": bt.final_equity,
        "broke": bt.broke,
        "early_stopped": bt.early_stopped,
        "trade_list": bt.trade_list,
        "exit_classes": bt.exit_classes,
    }
    gate_report = evaluate_gates(bt_dict)

    # Build metadata
    meta = {
        "run_id": run_id,
        "config_id": cfg["id"],
        "hypothesis_id": cfg["hypothesis_id"],
        "hypothesis_name": cfg["hypothesis_name"],
        "category": cfg["category"],
        "exit_template": cfg["exit_template"],
        "dataset_id": dataset_id,
        "exchange": "kraken",
        "fee_bps": round(KRAKEN_FEE * 10000, 1),
        "n_coins": len(coins),
        "elapsed_s": round(elapsed, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git_hash,
        "engine": "sprint3.engine (Stage 0) + sprint2 indicators/context",
        "market_context": True,
        "stage0_min_pf": _sprint2_gates.STAGE0_MIN_PF,
        "exit_mode": "dc",
    }

    # Write results.json (strip __market__ from params for serialization)
    clean_params = {k: v for k, v in cfg["params"].items() if not k.startswith("__")}
    results_payload = {
        "metadata": meta,
        "params": clean_params,
        "summary": {
            "trades": bt.trades,
            "wr": round(bt.wr, 2),
            "pnl": round(bt.pnl, 2),
            "final_equity": round(bt.final_equity, 2),
            "pf": round(min(bt.pf, 99.99), 4),
            "dd": round(bt.dd, 2),
            "broke": bt.broke,
        },
        "exit_classes": bt.exit_classes,
        "trade_count": bt.trades,
        "trades": [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
            for t in bt.trade_list
        ],
    }
    with open(results_path, "w") as f:
        json.dump(results_payload, f, indent=2, default=str)

    # Write params.json
    with open(run_dir / "params.json", "w") as f:
        json.dump(clean_params, f, indent=2, sort_keys=True)

    # Write gates.json
    with open(run_dir / "gates.json", "w") as f:
        json.dump(gates_to_dict(gate_report), f, indent=2)

    # Write results.md
    md_lines = [
        f"# Sprint 3 — {cfg['id']}",
        "",
        f"- **Hypothesis**: {cfg['hypothesis_name']} ({cfg['hypothesis_id']})",
        f"- **Category**: {cfg['category']}",
        f"- **Exit template**: {cfg['exit_template']}",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        f"- **Dataset**: {dataset_id} ({len(coins)} coins)",
        f"- **Elapsed**: {elapsed:.1f}s",
        f"- **Market context**: Yes (momentum rank + breadth)",
        "",
        "## Results",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Trades | {bt.trades} |",
        f"| Win Rate | {bt.wr:.1f}% |",
        f"| P&L | ${bt.pnl:+,.2f} |",
        f"| PF | {min(bt.pf, 99.99):.2f} |",
        f"| Max DD | {bt.dd:.1f}% |",
        "",
        "## Exit Classes",
    ]

    # Exit class breakdown
    for cls_label, cls_name in [("A", "Class A (smart)"), ("B", "Class B (mechanical)")]:
        reasons = bt.exit_classes.get(cls_label, {})
        if reasons:
            md_lines.append(f"### {cls_name}")
            md_lines.append("| Reason | Count | P&L | Wins |")
            md_lines.append("|--------|-------|-----|------|")
            for reason, stats in sorted(reasons.items()):
                md_lines.append(
                    f"| {reason} | {stats['count']} | ${stats['pnl']:+,.2f} | {stats['wins']} |"
                )
            md_lines.append("")

    md_lines.extend([
        "## Gates (Stage 0 — relaxed PF > 1.05)",
        f"**Verdict: {gate_report.verdict}** ({gate_report.n_hard_passed}/{gate_report.n_hard_total} hard gates)",
        "",
    ])
    for g in gate_report.gates:
        mark = "PASS" if g.passed else "FAIL"
        md_lines.append(f"- [{mark}] {g.name}: {g.detail}")
    for g in gate_report.soft_gates:
        mark = "OK" if g.passed else "LOW"
        md_lines.append(f"- [{mark}] {g.name}: {g.detail}")

    with open(run_dir / "results.md", "w") as f:
        f.write("\n".join(md_lines) + "\n")

    # Console output
    verdict = gate_report.verdict
    mark = "GO" if verdict == "GO" else "NO-GO" if verdict == "NO-GO" else verdict
    print(
        f"  [{mark:6s}] {cfg['id']:<55s} "
        f"| {bt.trades:4d}tr | PF {min(bt.pf, 99.99):5.2f} "
        f"| DD {bt.dd:5.1f}% | P&L ${bt.pnl:+8.2f} "
        f"| {elapsed:.1f}s"
    )

    return results_payload


def _build_scoreboard(results: list[dict], output_dir: Path, git_hash: str, dataset_id: str):
    """Build summary scoreboard from all results."""
    entries = []
    for r in results:
        if r is None:
            continue
        run_id = r.get("metadata", {}).get("run_id", "")
        run_dir = output_dir / run_id
        gates_path = run_dir / "gates.json"

        gates_data = {}
        if gates_path.exists():
            with open(gates_path) as f:
                gates_data = json.load(f)

        entries.append({
            "run_id": run_id,
            "config_id": r.get("metadata", {}).get("config_id", ""),
            "hypothesis_id": r.get("metadata", {}).get("hypothesis_id", ""),
            "hypothesis_name": r.get("metadata", {}).get("hypothesis_name", ""),
            "category": r.get("metadata", {}).get("category", ""),
            "trades": r.get("summary", {}).get("trades", 0),
            "wr": r.get("summary", {}).get("wr", 0),
            "pnl": r.get("summary", {}).get("pnl", 0),
            "pf": r.get("summary", {}).get("pf", 0),
            "dd": r.get("summary", {}).get("dd", 0),
            "verdict": gates_data.get("verdict", "UNKNOWN"),
            "gates_passed": gates_data.get("n_hard_passed", 0),
            "gates_total": gates_data.get("n_hard_total", 0),
        })

    # Sort: GO first (by PF desc), then NO-GO (by PF desc)
    go_entries = [e for e in entries if e["verdict"] == "GO"]
    nogo_entries = [e for e in entries if e["verdict"] != "GO"]
    go_entries.sort(key=lambda e: (-e["pf"], -e["trades"]))
    nogo_entries.sort(key=lambda e: (-e["pf"], -e["trades"]))

    # Write JSON scoreboard
    scoreboard = {
        "experiment_id": "sprint3",
        "dataset_id": dataset_id,
        "git_hash": git_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_configs": len(entries),
        "go_count": len(go_entries),
        "stage0_min_pf": _sprint2_gates.STAGE0_MIN_PF,
        "exit_mode": "dc",
        "entries": go_entries + nogo_entries,
    }
    sb_json = output_dir / "scoreboard_sprint3.json"
    with open(sb_json, "w") as f:
        json.dump(scoreboard, f, indent=2)
    print(f"\n  Scoreboard JSON: {sb_json}")

    # Write MD scoreboard
    md_lines = [
        "# Sprint 3 Scoreboard — Exit-Intelligence Porting",
        "",
        f"- **Dataset**: {dataset_id}",
        f"- **Git**: {git_hash}",
        f"- **Generated**: {scoreboard['generated_at']}",
        f"- **Total configs**: {len(entries)}",
        f"- **GO (PF > {_sprint2_gates.STAGE0_MIN_PF})**: {len(go_entries)}",
        f"- **Stage 0 gate**: PF > {_sprint2_gates.STAGE0_MIN_PF} (relaxed)",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        "",
    ]

    if go_entries:
        md_lines.append("## GO Configs (advance to truth-pass)")
        md_lines.append("")
        md_lines.append("| # | Config | Family | Cat | Tr | WR | PF | DD | P&L | Gates |")
        md_lines.append("|---|--------|--------|-----|-----|-----|------|------|-------|-------|")
        for i, e in enumerate(go_entries, 1):
            md_lines.append(
                f"| {i} | {e['config_id']} | {e['hypothesis_name']} "
                f"| {e['category']} | {e['trades']} | {e['wr']:.1f}% | {e['pf']:.2f} "
                f"| {e['dd']:.1f}% | ${e['pnl']:+,.2f} "
                f"| {e['gates_passed']}/{e['gates_total']} |"
            )
        md_lines.append("")

    md_lines.append("## All Configs (by PF)")
    md_lines.append("")
    md_lines.append("| # | Verdict | Config | Family | Cat | Tr | PF | DD | P&L |")
    md_lines.append("|---|---------|--------|--------|-----|-----|------|------|-------|")
    all_sorted = go_entries + nogo_entries
    for i, e in enumerate(all_sorted, 1):
        md_lines.append(
            f"| {i} | {e['verdict']} | {e['config_id']} | {e['hypothesis_name']} "
            f"| {e['category']} | {e['trades']} | {e['pf']:.2f} "
            f"| {e['dd']:.1f}% | ${e['pnl']:+,.2f} |"
        )

    # Family summary
    md_lines.append("")
    md_lines.append("## Family Summary")
    md_lines.append("")
    md_lines.append("| Family | Cat | Configs | GO | Best PF | Avg PF | Best P&L |")
    md_lines.append("|--------|-----|---------|-----|---------|--------|----------|")
    family_ids = sorted(set(e["hypothesis_id"] for e in entries))
    for fam_id in family_ids:
        fam_entries = [e for e in entries if e["hypothesis_id"] == fam_id]
        fam_go = [e for e in fam_entries if e["verdict"] == "GO"]
        best_pf = max(e["pf"] for e in fam_entries) if fam_entries else 0
        avg_pf = sum(e["pf"] for e in fam_entries) / len(fam_entries) if fam_entries else 0
        best_pnl = max(e["pnl"] for e in fam_entries) if fam_entries else 0
        name = fam_entries[0]["hypothesis_name"] if fam_entries else fam_id
        cat = fam_entries[0]["category"] if fam_entries else ""
        md_lines.append(
            f"| {name} | {cat} | {len(fam_entries)} | {len(fam_go)} "
            f"| {best_pf:.2f} | {avg_pf:.2f} | ${best_pnl:+,.2f} |"
        )

    sb_md = output_dir / "scoreboard_sprint3.md"
    with open(sb_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  Scoreboard MD:   {sb_md}")


def main():
    parser = argparse.ArgumentParser(description="Sprint 3 Sweep Runner (Stage 0 — Exit-Intelligence Porting)")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Dataset ID or path")
    parser.add_argument("--universe", default=None, help="Universe JSON (overrides dataset filtering)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Output directory")
    parser.add_argument("--force", action="store_true", help="Re-run existing results")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--only", default=None, help="Comma-separated config indices to run (1-based)")
    parser.add_argument("--momentum-period", type=int, default=10,
                        help="Market context momentum period (default: 10)")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)

    print(f"\n{'=' * 72}")
    print(f"  Sprint 3 Sweep — Exit-Intelligence Porting (DC exits)")
    print(f"{'=' * 72}")

    # Build configs
    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Filter if --only
    if args.only:
        indices = [int(x.strip()) for x in args.only.split(",")]
        configs = [c for c in configs if c["idx"] in indices]
        print(f"  Filtered to: {len(configs)} configs (indices: {indices})")

    if args.dry_run:
        print(f"\n  DRY RUN — would execute {len(configs)} configs:")
        for cfg in configs:
            print(f"    [{cfg['idx']:2d}] {cfg['id']} — {cfg['hypothesis_name']} ({cfg['category']})")
            clean_p = {k: v for k, v in cfg['params'].items() if not k.startswith('__')}
            print(f"         params: {json.dumps(clean_p, sort_keys=True)}")
        return

    # Resolve dataset
    try:
        dataset_path = resolve_dataset(args.dataset)
    except (FileNotFoundError, KeyError):
        dataset_path = Path(args.dataset)

    print(f"  Dataset: {dataset_path}")

    # Load data
    print(f"  Loading data...")
    t0 = time.time()
    with open(dataset_path) as f:
        data = json.load(f)

    # Determine coins
    if args.universe:
        with open(args.universe) as f:
            universe = json.load(f)
        coins = universe["coins"]
        print(f"  Universe: {len(coins)} coins from {args.universe}")
    else:
        coins = sorted([k for k in data if not k.startswith("_")])
        print(f"  All coins: {len(coins)}")
    print(f"  Data loaded: {time.time() - t0:.1f}s")

    # Precompute Sprint 2 indicators (extends Sprint 1 with dc_prev_high, +DI, -DI, __coin__)
    # Already has dc_mid, bb_mid, rsi needed for DC exits
    print(f"  Precomputing Sprint 2 indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    # Precompute market context (for Family 3: cross-sectional signals)
    print(f"  Precomputing market context (momentum_period={args.momentum_period})...")
    t2 = time.time()
    market_ctx = precompute_sprint2_context(data, coins, momentum_period=args.momentum_period)
    print(f"  Market context: {time.time() - t2:.1f}s")
    print(f"    n_ranked sample (bar 100): {market_ctx['n_ranked'][100] if len(market_ctx['n_ranked']) > 100 else 'N/A'}")
    print(f"    breadth_up sample (bar 100): {market_ctx['breadth_up'][100]:.3f}" if len(market_ctx['breadth_up']) > 100 else "")

    # Run sweep
    print(f"\n{'─' * 72}")
    print(f"  Running {len(configs)} configs (Stage 0, PF > {_sprint2_gates.STAGE0_MIN_PF}, exit_mode=dc)...")
    print(f"{'─' * 72}")

    results = []
    for cfg in configs:
        result = _run_single(
            cfg, data, coins, indicators, market_ctx, output_dir,
            git_hash, args.dataset, args.force,
        )
        results.append(result)

    # Summary
    valid_results = [r for r in results if r is not None]
    go_count = sum(
        1 for r in valid_results
        if r.get("summary", {}).get("pf", 0) >= _sprint2_gates.STAGE0_MIN_PF
    )
    print(f"\n{'=' * 72}")
    print(f"  Sweep complete: {len(configs)} configs, {go_count} with PF > {_sprint2_gates.STAGE0_MIN_PF}")

    # Build scoreboard
    _build_scoreboard(valid_results, output_dir, git_hash, args.dataset)

    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
