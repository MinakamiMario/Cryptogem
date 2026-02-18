#!/usr/bin/env python3
"""
Sprint 4 Sweep Runner -- DC-Compatible Entry Mining for 4H strategies.

Two-pass architecture:
  Phase 1: Score ALL entries for DC-compatibility using compat_scorer
  Phase 2: Backtest ONLY top-N entries (by compat score)

Key innovation: entries are pre-scored for geometric compatibility with
DualConfirm exits BEFORE expensive backtesting. This filters out entries
that can't possibly work with DC/BB/RSI RECOVERY exits.

Sprint 3 proved: arbitrary entries + DC exits = 0 GO.
Sprint 4 tests: entries DESIGNED for DC geometry + DC exits = ???

Uses Sprint 3 engine with exit_mode='dc' (hybrid_notrl exits).
Uses Sprint 2 indicators (has dc_mid, bb_mid, rsi, bb_width, bb_lower).
Uses Sprint 2 market context (available for families that need it).
Uses Sprint 2 gates (PF > 1.05 advancement).

Two scoreboards:
  - scoreboard_sprint4_strict.json/md  -- PF > 1.05 (production GO)
  - scoreboard_sprint4_research.json/md -- PF > 1.00 (research leads)

Usage:
    python3 scripts/run_sprint4_sweep.py
    python3 scripts/run_sprint4_sweep.py --dry-run
    python3 scripts/run_sprint4_sweep.py --force
    python3 scripts/run_sprint4_sweep.py --only 1,5,12
    python3 scripts/run_sprint4_sweep.py --top-n 15
    python3 scripts/run_sprint4_sweep.py --score-all          # Phase 1 only
    python3 scripts/run_sprint4_sweep.py --skip-scoring        # Skip Phase 1
    python3 scripts/run_sprint4_sweep.py --universe strategies/4h/universe_sprint1.json
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
_sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")
_sprint4_compat = importlib.import_module("strategies.4h.sprint4.compat_scorer")
_sprint4_guardrail = importlib.import_module("strategies.4h.sprint4.guardrail")
_sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")
_sprint2_gates = importlib.import_module("strategies.4h.sprint2.gates")
_sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

run_backtest = _sprint3_engine.run_backtest
precompute_all = _sprint2_indicators.precompute_all  # Sprint 2 extended (has dc_mid, bb_mid, rsi, bb_width, bb_lower)
evaluate_gates = _sprint2_gates.evaluate_sprint2_gates
gates_to_dict = _sprint2_gates.gates_to_dict
print_gate_report = _sprint2_gates.print_sprint2_report
build_sweep_configs = _sprint4_hyp.build_sweep_configs
score_hypothesis_entries = _sprint4_compat.score_hypothesis_entries
verify_provenance = _sprint4_guardrail.verify_provenance
replay_test = _sprint4_guardrail.replay_test
precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
resolve_dataset = _data_resolver.resolve_dataset

# Constants
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "4h"
KRAKEN_FEE = 0.0026
STRICT_PF = 1.05   # Production GO
RESEARCH_PF = 1.00  # Research leads threshold


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Phase 1: Compatibility Pre-scoring
# ---------------------------------------------------------------------------

def _prescore_configs(
    configs: list[dict],
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
) -> list[tuple[dict, dict]]:
    """Score ALL configs for DC-compatibility before backtesting.

    For each config, run signal_fn on ALL coins/bars, collect entries,
    score each entry using compat_scorer.score_entry(), aggregate.

    Returns list of (config, compat_result) sorted by avg_composite desc.
    """
    scored: list[tuple[dict, dict]] = []

    for cfg in configs:
        # Inject __market__ into params (needed for families with cross-sectional signals)
        enriched_params = {**cfg["params"], "__market__": market_ctx}

        t0 = time.time()
        compat_result = score_hypothesis_entries(
            data=data,
            coins=coins,
            signal_fn=cfg["signal_fn"],
            params=enriched_params,
            indicators=indicators,
            start_bar=50,
        )
        elapsed = time.time() - t0

        # Strip individual entry details to keep memory manageable
        compat_summary = {
            "total_entries": compat_result["total_entries"],
            "passing_entries": compat_result["passing_entries"],
            "avg_composite": compat_result["avg_composite"],
            "median_composite": compat_result["median_composite"],
            "top_quartile_composite": compat_result["top_quartile_composite"],
            "avg_features": compat_result["avg_features"],
            "elapsed_s": round(elapsed, 2),
        }

        # Determine if config passes hard filter (at least some entries pass)
        hard_pass = compat_result["passing_entries"] > 0

        compat_summary["hard_pass"] = hard_pass

        scored.append((cfg, compat_summary))

        # Console output
        status = "PASS" if hard_pass else "SKIP"
        n_total = compat_result["total_entries"]
        n_pass = compat_result["passing_entries"]
        avg_comp = compat_result["avg_composite"]
        print(
            f"  [{status:4s}] {cfg['id']:<55s} "
            f"| {n_total:4d} entries | {n_pass:4d} pass "
            f"| avg_compat {avg_comp:.4f} "
            f"| {elapsed:.1f}s"
        )

    # Sort by avg_composite descending (best compatibility first)
    scored.sort(key=lambda x: -x[1]["avg_composite"])

    return scored


# ---------------------------------------------------------------------------
# Phase 2: Backtest
# ---------------------------------------------------------------------------

def _run_single(
    cfg: dict,
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
    compat_score: dict | None = None,
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

    # Inject __market__ into params (available for families that need it)
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
        "family": cfg["family"],
        "category": cfg["category"],
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
        "strict_pf": STRICT_PF,
        "research_pf": RESEARCH_PF,
    }

    # Add compat score to metadata if available
    if compat_score is not None:
        meta["compat_score"] = compat_score

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
            {
                k: (
                    round(v, 10) if isinstance(v, float) and k in ("entry", "exit")
                    else round(v, 4) if isinstance(v, float)
                    else v
                )
                for k, v in t.items()
            }
            for t in bt.trade_list
        ],
    }
    with open(results_path, "w") as f:
        json.dump(results_payload, f, indent=2, default=str)

    # Provenance block for params.json and gates.json
    _provenance = {
        "timestamp": meta["timestamp"],
        "dataset_id": meta["dataset_id"],
        "git_hash": meta["git_hash"],
        "fee_bps": meta["fee_bps"],
    }

    # Write params.json
    params_payload = {**clean_params, "_provenance": _provenance}
    with open(run_dir / "params.json", "w") as f:
        json.dump(params_payload, f, indent=2, sort_keys=True)

    # Write gates.json
    gates_payload = {**gates_to_dict(gate_report), "_provenance": _provenance}
    with open(run_dir / "gates.json", "w") as f:
        json.dump(gates_payload, f, indent=2)

    # Write results.md
    compat_avg = compat_score["avg_composite"] if compat_score else "N/A"
    compat_pass = compat_score["passing_entries"] if compat_score else "N/A"
    compat_total = compat_score["total_entries"] if compat_score else "N/A"
    md_lines = [
        f"# Sprint 4 -- {cfg['id']}",
        "",
        f"- **Hypothesis**: {cfg['hypothesis_name']} ({cfg['hypothesis_id']})",
        f"- **Family**: {cfg['family']}",
        f"- **Category**: {cfg['category']}",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        f"- **Dataset**: {dataset_id} ({len(coins)} coins)",
        f"- **Elapsed**: {elapsed:.1f}s",
        f"- **Market context**: Yes (momentum rank + breadth)",
        f"- **Compat score**: avg={compat_avg}, entries={compat_pass}/{compat_total}",
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
        "## Gates (Stage 0 -- relaxed PF > 1.05)",
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
    compat_str = f"compat={compat_avg:.4f}" if isinstance(compat_avg, float) else "compat=N/A"
    print(
        f"  [{mark:6s}] {cfg['id']:<55s} "
        f"| {bt.trades:4d}tr | PF {min(bt.pf, 99.99):5.2f} "
        f"| DD {bt.dd:5.1f}% | P&L ${bt.pnl:+8.2f} "
        f"| {compat_str} | {elapsed:.1f}s"
    )

    return results_payload


# ---------------------------------------------------------------------------
# Scoreboards
# ---------------------------------------------------------------------------

def _build_scoreboards(
    results: list[dict],
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
    compat_scores: dict[str, dict],
):
    """Build TWO scoreboards:
    1. scoreboard_sprint4_strict.json/md  -- PF > 1.05 (production GO)
    2. scoreboard_sprint4_research.json/md -- PF > 1.00 (research leads)

    Both include compat_score column.
    """
    entries = []
    for r in results:
        if r is None:
            continue
        run_id = r.get("metadata", {}).get("run_id", "")
        config_id = r.get("metadata", {}).get("config_id", "")
        run_dir = output_dir / run_id
        gates_path = run_dir / "gates.json"

        gates_data = {}
        if gates_path.exists():
            with open(gates_path) as f:
                gates_data = json.load(f)

        # Look up compat score
        cs = compat_scores.get(config_id, {})

        entries.append({
            "run_id": run_id,
            "config_id": config_id,
            "hypothesis_id": r.get("metadata", {}).get("hypothesis_id", ""),
            "hypothesis_name": r.get("metadata", {}).get("hypothesis_name", ""),
            "family": r.get("metadata", {}).get("family", ""),
            "category": r.get("metadata", {}).get("category", ""),
            "trades": r.get("summary", {}).get("trades", 0),
            "wr": r.get("summary", {}).get("wr", 0),
            "pnl": r.get("summary", {}).get("pnl", 0),
            "pf": r.get("summary", {}).get("pf", 0),
            "dd": r.get("summary", {}).get("dd", 0),
            "verdict": gates_data.get("verdict", "UNKNOWN"),
            "gates_passed": gates_data.get("n_hard_passed", 0),
            "gates_total": gates_data.get("n_hard_total", 0),
            "compat_score": cs.get("avg_composite", 0),
            "compat_entries": cs.get("passing_entries", 0),
            "compat_total": cs.get("total_entries", 0),
        })

    # Build strict scoreboard (PF > 1.05)
    _write_scoreboard(
        entries=entries,
        output_dir=output_dir,
        git_hash=git_hash,
        dataset_id=dataset_id,
        pf_threshold=STRICT_PF,
        label="strict",
        title="Sprint 4 Scoreboard -- DC-Compatible Entry Mining (STRICT: PF > 1.05)",
        description="Production GO threshold. Configs that pass advance to truth-pass.",
    )

    # Build research scoreboard (PF > 1.00)
    _write_scoreboard(
        entries=entries,
        output_dir=output_dir,
        git_hash=git_hash,
        dataset_id=dataset_id,
        pf_threshold=RESEARCH_PF,
        label="research",
        title="Sprint 4 Scoreboard -- DC-Compatible Entry Mining (RESEARCH: PF > 1.00)",
        description="Research leads threshold. Configs worth deeper investigation.",
    )


def _write_scoreboard(
    entries: list[dict],
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
    pf_threshold: float,
    label: str,
    title: str,
    description: str,
):
    """Write a single scoreboard (JSON + MD) for the given PF threshold."""
    # Classify
    go_entries = [e for e in entries if e["pf"] >= pf_threshold]
    nogo_entries = [e for e in entries if e["pf"] < pf_threshold]
    go_entries.sort(key=lambda e: (-e["pf"], -e["trades"]))
    nogo_entries.sort(key=lambda e: (-e["pf"], -e["trades"]))

    # Write JSON scoreboard
    scoreboard = {
        "experiment_id": "sprint4",
        "dataset_id": dataset_id,
        "git_hash": git_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_configs": len(entries),
        "go_count": len(go_entries),
        "pf_threshold": pf_threshold,
        "label": label,
        "exit_mode": "dc",
        "entries": go_entries + nogo_entries,
    }
    sb_json = output_dir / f"scoreboard_sprint4_{label}.json"
    with open(sb_json, "w") as f:
        json.dump(scoreboard, f, indent=2)
    print(f"\n  Scoreboard JSON ({label}): {sb_json}")

    # Write MD scoreboard
    md_lines = [
        f"# {title}",
        "",
        f"- **Dataset**: {dataset_id}",
        f"- **Git**: {git_hash}",
        f"- **Generated**: {scoreboard['generated_at']}",
        f"- **Total configs**: {len(entries)}",
        f"- **GO (PF > {pf_threshold})**: {len(go_entries)}",
        f"- **PF threshold**: {pf_threshold} ({label})",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        f"- {description}",
        "",
    ]

    if go_entries:
        md_lines.append(f"## GO Configs (PF > {pf_threshold})")
        md_lines.append("")
        md_lines.append("| # | Verdict | Config | Family | CompatScore | Tr | WR | PF | DD | P&L | Gates |")
        md_lines.append("|---|---------|--------|--------|-------------|-----|-----|------|------|-------|-------|")
        for i, e in enumerate(go_entries, 1):
            md_lines.append(
                f"| {i} | {e['verdict']} | {e['config_id']} | {e['family']} "
                f"| {e['compat_score']:.4f} | {e['trades']} | {e['wr']:.1f}% | {e['pf']:.2f} "
                f"| {e['dd']:.1f}% | ${e['pnl']:+,.2f} "
                f"| {e['gates_passed']}/{e['gates_total']} |"
            )
        md_lines.append("")

    md_lines.append("## All Configs (by PF)")
    md_lines.append("")
    md_lines.append("| # | Verdict | Config | Family | CompatScore | Tr | PF | DD | P&L |")
    md_lines.append("|---|---------|--------|--------|-------------|-----|------|------|-------|")
    all_sorted = go_entries + nogo_entries
    for i, e in enumerate(all_sorted, 1):
        md_lines.append(
            f"| {i} | {e['verdict']} | {e['config_id']} | {e['family']} "
            f"| {e['compat_score']:.4f} | {e['trades']} | {e['pf']:.2f} "
            f"| {e['dd']:.1f}% | ${e['pnl']:+,.2f} |"
        )

    # Family summary
    md_lines.append("")
    md_lines.append("## Family Summary")
    md_lines.append("")
    md_lines.append("| Family | Cat | Configs | GO | Best PF | Avg PF | Avg Compat | Best P&L |")
    md_lines.append("|--------|-----|---------|-----|---------|--------|------------|----------|")
    family_ids = sorted(set(e["family"] for e in entries))
    for fam_id in family_ids:
        fam_entries = [e for e in entries if e["family"] == fam_id]
        fam_go = [e for e in fam_entries if e["pf"] >= pf_threshold]
        best_pf = max(e["pf"] for e in fam_entries) if fam_entries else 0
        avg_pf = sum(e["pf"] for e in fam_entries) / len(fam_entries) if fam_entries else 0
        avg_compat = sum(e["compat_score"] for e in fam_entries) / len(fam_entries) if fam_entries else 0
        best_pnl = max(e["pnl"] for e in fam_entries) if fam_entries else 0
        cat = fam_entries[0]["category"] if fam_entries else ""
        md_lines.append(
            f"| {fam_id} | {cat} | {len(fam_entries)} | {len(fam_go)} "
            f"| {best_pf:.2f} | {avg_pf:.2f} | {avg_compat:.4f} | ${best_pnl:+,.2f} |"
        )

    sb_md = output_dir / f"scoreboard_sprint4_{label}.md"
    with open(sb_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  Scoreboard MD  ({label}): {sb_md}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sprint 4 Sweep Runner (DC-Compatible Entry Mining)"
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Dataset ID or path")
    parser.add_argument("--universe", default=None, help="Universe JSON (overrides dataset filtering)")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Output directory")
    parser.add_argument("--force", action="store_true", help="Re-run existing results")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--only", default=None, help="Comma-separated config indices to run (1-based)")
    parser.add_argument("--momentum-period", type=int, default=10,
                        help="Market context momentum period (default: 10)")
    parser.add_argument("--top-n", type=int, default=10,
                        help="Top N compat entries to backtest (default: 10)")
    parser.add_argument("--score-all", action="store_true",
                        help="Score but skip backtest (phase 1 only)")
    parser.add_argument("--skip-scoring", action="store_true",
                        help="Skip scoring, backtest ALL configs")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)

    print(f"\n{'=' * 72}")
    print(f"  Sprint 4 Sweep -- DC-Compatible Entry Mining")
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
        print(f"\n  DRY RUN -- would execute {len(configs)} configs:")
        for cfg in configs:
            print(f"    [{cfg['idx']:2d}] {cfg['id']} -- {cfg['hypothesis_name']} ({cfg['family']})")
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

    # -----------------------------------------------------------------------
    # Guardrail: verify provenance
    # -----------------------------------------------------------------------
    print(f"\n  Verifying provenance...")
    prov_ok, prov_violations = verify_provenance(data, coins)
    if not prov_ok:
        print(f"  PROVENANCE VIOLATIONS:")
        for v in prov_violations:
            print(f"    - {v}")
        print(f"  ABORTING: provenance check failed. Fix data/universe and retry.")
        sys.exit(1)
    print(f"  Provenance: OK ({len(coins)} coins)")

    # Precompute Sprint 2 indicators (extends Sprint 1 with dc_prev_low, +DI, -DI, __coin__)
    # Already has dc_mid, bb_mid, rsi, bb_width, bb_lower needed for DC exits and compat scoring
    print(f"  Precomputing Sprint 2 indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    # Precompute market context (available for families that need it)
    print(f"  Precomputing market context (momentum_period={args.momentum_period})...")
    t2 = time.time()
    market_ctx = precompute_sprint2_context(data, coins, momentum_period=args.momentum_period)
    print(f"  Market context: {time.time() - t2:.1f}s")
    if len(market_ctx.get("n_ranked", [])) > 100:
        print(f"    n_ranked sample (bar 100): {market_ctx['n_ranked'][100]}")
    if len(market_ctx.get("breadth_up", [])) > 100:
        print(f"    breadth_up sample (bar 100): {market_ctx['breadth_up'][100]:.3f}")

    # -----------------------------------------------------------------------
    # Guardrail: deterministic replay test on first config
    # -----------------------------------------------------------------------
    print(f"\n  Running deterministic replay test...")
    first_cfg = configs[0]
    enriched_first = {**first_cfg["params"], "__market__": market_ctx}
    det_ok, det_details = replay_test(
        data, coins, first_cfg["signal_fn"], enriched_first,
        indicators, exit_mode="dc", n_runs=2,
    )
    if not det_ok:
        print(f"  REPLAY TEST FAILED: non-deterministic results!")
        for m in det_details.get("mismatches", []):
            print(f"    - {m}")
        print(f"  ABORTING: engine is non-deterministic.")
        sys.exit(1)
    ref = det_details.get("reference", {})
    print(f"  Replay test: OK (deterministic, ref={ref.get('trades', '?')} trades)")

    # -----------------------------------------------------------------------
    # Phase 1: Compatibility Pre-scoring
    # -----------------------------------------------------------------------
    compat_scores: dict[str, dict] = {}  # config_id -> compat_result
    backtest_configs: list[tuple[dict, dict | None]] = []  # (config, compat_result_or_None)

    if not args.skip_scoring:
        print(f"\n{'=' * 72}")
        print(f"  PHASE 1: Compatibility Pre-scoring ({len(configs)} configs)")
        print(f"{'=' * 72}")

        scored = _prescore_configs(configs, data, coins, indicators, market_ctx)

        # Store compat scores
        for cfg, cs in scored:
            compat_scores[cfg["id"]] = cs

        # Write compat scores JSON
        output_dir.mkdir(parents=True, exist_ok=True)
        compat_json_path = output_dir / "sprint4_compat_scores.json"
        compat_json = {
            "experiment_id": "sprint4",
            "dataset_id": args.dataset,
            "git_hash": git_hash,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_configs": len(scored),
            "passing_configs": sum(1 for _, cs in scored if cs["hard_pass"]),
            "scores": [
                {
                    "config_id": cfg["id"],
                    "hypothesis_id": cfg["hypothesis_id"],
                    "family": cfg["family"],
                    **cs,
                }
                for cfg, cs in scored
            ],
        }
        with open(compat_json_path, "w") as f:
            json.dump(compat_json, f, indent=2)
        print(f"\n  Compat scores: {compat_json_path}")

        # Summary
        n_passing = sum(1 for _, cs in scored if cs["hard_pass"])
        print(f"  Phase 1 complete: {n_passing}/{len(scored)} configs have passing entries")
        if scored:
            print(f"  Top compat: {scored[0][0]['id']} avg={scored[0][1]['avg_composite']:.4f}")
            if len(scored) > 1:
                print(f"  2nd compat: {scored[1][0]['id']} avg={scored[1][1]['avg_composite']:.4f}")

        if args.score_all:
            print(f"\n  --score-all: skipping Phase 2 (backtest).")
            print(f"{'=' * 72}\n")
            return

        # Select top-N for backtesting (only those with hard_pass=True)
        passing_scored = [(cfg, cs) for cfg, cs in scored if cs["hard_pass"]]
        top_n = min(args.top_n, len(passing_scored))
        if top_n == 0:
            print(f"\n  WARNING: No configs passed hard filter. Nothing to backtest.")
            print(f"{'=' * 72}\n")
            return

        top_configs = passing_scored[:top_n]
        backtest_configs = [(cfg, cs) for cfg, cs in top_configs]
        print(f"\n  Selected top-{top_n} configs for backtesting:")
        for cfg, cs in backtest_configs:
            print(f"    {cfg['id']} -- avg_compat={cs['avg_composite']:.4f}")

    else:
        # --skip-scoring: backtest ALL configs without scoring
        print(f"\n  --skip-scoring: backtesting ALL {len(configs)} configs without compat scoring")
        backtest_configs = [(cfg, None) for cfg in configs]

    # -----------------------------------------------------------------------
    # Phase 2: Backtest
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 72}")
    print(f"  PHASE 2: Backtest ({len(backtest_configs)} configs, exit_mode=dc)")
    print(f"{'=' * 72}")

    results = []
    for cfg, cs in backtest_configs:
        result = _run_single(
            cfg, data, coins, indicators, market_ctx, output_dir,
            git_hash, args.dataset, compat_score=cs, force=args.force,
        )
        results.append(result)

    # Summary
    valid_results = [r for r in results if r is not None]
    strict_count = sum(
        1 for r in valid_results
        if r.get("summary", {}).get("pf", 0) >= STRICT_PF
    )
    research_count = sum(
        1 for r in valid_results
        if r.get("summary", {}).get("pf", 0) >= RESEARCH_PF
    )
    print(f"\n{'=' * 72}")
    print(f"  Phase 2 complete: {len(backtest_configs)} configs backtested")
    print(f"  Strict GO  (PF > {STRICT_PF}): {strict_count}")
    print(f"  Research   (PF > {RESEARCH_PF}): {research_count}")

    # Build scoreboards
    _build_scoreboards(valid_results, output_dir, git_hash, args.dataset, compat_scores)

    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
