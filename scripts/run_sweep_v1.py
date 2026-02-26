#!/usr/bin/env python3
"""
Sweep v1 Runner -- New Edge Discovery with 30 candidate entries across 5 families.

Two-phase architecture (cloned from Sprint 4):
  Phase 0: Load data, precompute indicators + RSI rank, build universe, verify provenance
  Phase 1: Score ALL entries for DC-compatibility using compat_scorer
  Phase 2: Backtest top-N entries via Sprint 3 engine (exit_mode='dc')

Key differences from Sprint 4 runner:
  - Import hypotheses from strategies.4h.sweep_v1.hypotheses (30 configs, 5 families)
  - Use strategies.4h.sweep_v1.indicators.precompute_all (extended with pivots, ATR%, BB squeeze, swing)
  - Inject cross-sectional RSI rank into per-coin indicators after precompute_all
  - Use strategies.4h.sweep_v1.gates.evaluate_sweep_v1_gates (relaxed DD=25%, soft trades=50)
  - Edge decomposition via sprint4.analysis for research classification
  - Output to reports/4h/sweep_v1/

Families:
  SV1-A: Swing Low Fractal Bounce     (6 configs)
  SV1-B: Wick Sweep & Reclaim         (6 configs)
  SV1-C: Trend Pullback to Channel    (6 configs)
  SV1-D: ATR Regime Exhaustion        (6 configs)
  SV1-E: Cross-Sectional RSI Extreme  (6 configs)

Usage:
    python3 scripts/run_sweep_v1.py
    python3 scripts/run_sweep_v1.py --dry-run
    python3 scripts/run_sweep_v1.py --force
    python3 scripts/run_sweep_v1.py --top-n 15
    python3 scripts/run_sweep_v1.py --top-n 30        # backtest all
    python3 scripts/run_sweep_v1.py --only WickSweepReclaim
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

# ---------------------------------------------------------------------------
# Import modules (digit-prefixed directory needs importlib)
# ---------------------------------------------------------------------------
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_sweep_v1_hyp = importlib.import_module("strategies.4h.sweep_v1.hypotheses")
_sweep_v1_ind = importlib.import_module("strategies.4h.sweep_v1.indicators")
_sweep_v1_gates = importlib.import_module("strategies.4h.sweep_v1.gates")
_sprint4_compat = importlib.import_module("strategies.4h.sprint4.compat_scorer")
_sprint4_analysis = importlib.import_module("strategies.4h.sprint4.analysis")
_sprint4_guardrail = importlib.import_module("strategies.4h.sprint4.guardrail")
_sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

run_backtest = _sprint3_engine.run_backtest
precompute_all = _sweep_v1_ind.precompute_all
precompute_rsi_rank = _sweep_v1_ind.precompute_rsi_rank
build_sweep_configs = _sweep_v1_hyp.build_sweep_configs
evaluate_gates = _sweep_v1_gates.evaluate_sweep_v1_gates
gates_to_dict = _sweep_v1_gates.gates_to_dict
print_gate_report = _sweep_v1_gates.print_gate_report
score_hypothesis_entries = _sprint4_compat.score_hypothesis_entries
decompose_edge = _sprint4_analysis.decompose_edge
batch_analysis = _sprint4_analysis.batch_analysis
write_analysis_report = _sprint4_analysis.write_analysis_report
verify_provenance = _sprint4_guardrail.verify_provenance
replay_test = _sprint4_guardrail.replay_test
precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
resolve_dataset = _data_resolver.resolve_dataset

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "4h" / "sweep_v1"
KRAKEN_FEE = 0.0026
INITIAL_CAPITAL = 2000
MIN_BARS = 360
STRICT_PF = 1.05
RESEARCH_PF = 1.00


def _git_hash() -> str:
    """Get short git hash of current HEAD."""
    try:
        r = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            timeout=5, cwd=str(REPO_ROOT),
        )
        return r.decode().strip()[:8]
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

        compat_summary = {
            "total_entries": compat_result["total_entries"],
            "passing_entries": compat_result["passing_entries"],
            "avg_composite": compat_result["avg_composite"],
            "median_composite": compat_result["median_composite"],
            "top_quartile_composite": compat_result["top_quartile_composite"],
            "avg_features": compat_result["avg_features"],
            "elapsed_s": round(elapsed, 2),
        }

        hard_pass = compat_result["passing_entries"] > 0
        compat_summary["hard_pass"] = hard_pass
        scored.append((cfg, compat_summary))

        status = "PASS" if hard_pass else "SKIP"
        n_total = compat_result["total_entries"]
        n_pass = compat_result["passing_entries"]
        avg_comp = compat_result["avg_composite"]
        print(
            f"  [{status:4s}] {cfg['id']:<60s} "
            f"| {n_total:4d} entries | {n_pass:4d} pass "
            f"| avg_compat {avg_comp:.4f} "
            f"| {elapsed:.1f}s"
        )

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

    enriched_params = {**cfg["params"], "__market__": market_ctx}

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

    # Evaluate gates
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

    # Edge decomposition
    result_for_decomp = {
        "summary": {
            "trades": bt.trades,
            "pnl": round(bt.pnl, 2),
            "pf": round(min(bt.pf, 99.99), 4),
            "wr": round(bt.wr, 2),
            "dd": round(bt.dd, 2),
        },
        "exit_classes": bt.exit_classes,
        "trades": bt.trade_list,
    }
    decomp = decompose_edge(result_for_decomp, cfg["id"])

    # Metadata
    meta = {
        "run_id": run_id,
        "config_id": cfg["id"],
        "hypothesis_id": cfg["hypothesis_id"],
        "hypothesis_name": cfg["hypothesis_name"],
        "family": cfg["family"],
        "category": cfg["category"],
        "dataset_id": dataset_id,
        "universe_id": f"sweep_v1_{len(coins)}coins_min{MIN_BARS}bars",
        "exchange": "kraken",
        "fee_model": "kraken_spot_26bps",
        "fee_bps": round(KRAKEN_FEE * 10000, 1),
        "n_coins": len(coins),
        "elapsed_s": round(elapsed, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git_hash,
        "engine": "sprint3.engine (exit_mode=dc) + sweep_v1 indicators",
        "exit_mode": "dc",
        "strict_pf": STRICT_PF,
        "research_pf": RESEARCH_PF,
    }

    if compat_score is not None:
        meta["compat_score"] = compat_score

    # Build results payload
    clean_params = {k: v for k, v in cfg["params"].items() if not k.startswith("__")}
    ev_per_trade = round(bt.pnl / bt.trades, 2) if bt.trades > 0 else 0.0

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
            "ev_per_trade": ev_per_trade,
        },
        "exit_classes": bt.exit_classes,
        "edge_decomposition": {
            "class_a_share": round(decomp.class_a_share, 4),
            "class_a_pnl": round(decomp.class_a_pnl, 2),
            "class_b_pnl": round(decomp.class_b_pnl, 2),
            "stopout_ratio": round(decomp.stopout_ratio, 4),
            "breakeven_fee_bps": decomp.breakeven_fee_bps,
            "research_grade": decomp.research_grade,
            "research_notes": decomp.research_notes,
        },
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

    # Provenance block
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
        f"# Sweep v1 -- {cfg['id']}",
        "",
        f"- **Hypothesis**: {cfg['hypothesis_name']} ({cfg['hypothesis_id']})",
        f"- **Family**: {cfg['family']}",
        f"- **Category**: {cfg['category']}",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        f"- **Dataset**: {dataset_id} ({len(coins)} coins)",
        f"- **Elapsed**: {elapsed:.1f}s",
        f"- **Compat score**: avg={compat_avg}, entries={compat_pass}/{compat_total}",
        f"- **Research grade**: {decomp.research_grade}",
        "",
        "## Results",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Trades | {bt.trades} |",
        f"| Win Rate | {bt.wr:.1f}% |",
        f"| P&L | ${bt.pnl:+,.2f} |",
        f"| PF | {min(bt.pf, 99.99):.2f} |",
        f"| Max DD | {bt.dd:.1f}% |",
        f"| EV/trade | ${ev_per_trade:+.2f} |",
        f"| Class A share | {decomp.class_a_share:.0%} |",
        f"| Stopout ratio | {decomp.stopout_ratio:.0%} |",
        f"| Breakeven fee | {decomp.breakeven_fee_bps:.0f} bps |",
        "",
        "## Exit Classes",
    ]

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
        f"## Gates (Sweep v1 -- PF > {STRICT_PF})",
        f"**Verdict: {gate_report.verdict}** ({gate_report.n_hard_passed}/{gate_report.n_hard_total} hard gates)",
        "",
    ])
    for g in gate_report.gates:
        mark = "PASS" if g.passed else "FAIL"
        md_lines.append(f"- [{mark}] {g.name}: {g.detail}")
    for g in gate_report.soft_gates:
        mark = "OK" if g.passed else "LOW"
        md_lines.append(f"- [{mark}] {g.name}: {g.detail}")

    if decomp.research_notes:
        md_lines.append("")
        md_lines.append("## Research Notes")
        for note in decomp.research_notes:
            md_lines.append(f"- {note}")

    with open(run_dir / "results.md", "w") as f:
        f.write("\n".join(md_lines) + "\n")

    # Console output
    verdict = gate_report.verdict
    mark = "GO" if verdict == "GO" else "NO-GO" if verdict == "NO-GO" else verdict
    compat_str = f"compat={compat_avg:.4f}" if isinstance(compat_avg, float) else "compat=N/A"
    print(
        f"  [{mark:6s}] {cfg['id']:<60s} "
        f"| {bt.trades:4d}tr | PF {min(bt.pf, 99.99):5.2f} "
        f"| DD {bt.dd:5.1f}% | P&L ${bt.pnl:+8.2f} "
        f"| EV ${ev_per_trade:+6.2f} "
        f"| {decomp.research_grade:12s} "
        f"| {compat_str} | {elapsed:.1f}s"
    )

    return results_payload


# ---------------------------------------------------------------------------
# Scoreboard
# ---------------------------------------------------------------------------

def _build_scoreboard(
    results: list[dict],
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
    compat_scores: dict[str, dict],
    n_coins: int,
):
    """Build the unified Sweep v1 scoreboard (JSON + MD).

    Contains three sections:
      1. Strict LEADs (PF > 1.05 + all gates pass)
      2. Research LEADs (PF > 1.00)
      3. All Results
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

        cs = compat_scores.get(config_id, {})
        ed = r.get("edge_decomposition", {})

        ev_per_trade = r.get("summary", {}).get("ev_per_trade", 0.0)

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
            "ev_per_trade": ev_per_trade,
            "verdict": gates_data.get("verdict", "UNKNOWN"),
            "gates_passed": gates_data.get("n_hard_passed", 0),
            "gates_total": gates_data.get("n_hard_total", 0),
            "compat_score": cs.get("avg_composite", 0),
            "compat_entries": cs.get("passing_entries", 0),
            "compat_total": cs.get("total_entries", 0),
            "class_a_share": ed.get("class_a_share", 0),
            "stopout_ratio": ed.get("stopout_ratio", 0),
            "breakeven_fee_bps": ed.get("breakeven_fee_bps", 0),
            "research_grade": ed.get("research_grade", "UNKNOWN"),
        })

    # Sort by PF descending, then trades descending
    entries.sort(key=lambda e: (-e["pf"], -e["trades"]))

    # Classify
    strict_leads = [e for e in entries if e["pf"] >= STRICT_PF and e["verdict"] == "GO"]
    research_leads = [e for e in entries if e["pf"] >= RESEARCH_PF]
    strong_leads = [e for e in entries if e["research_grade"] == "STRONG_LEAD"]

    # Write JSON scoreboard
    scoreboard = {
        "experiment_id": "sweep_v1",
        "dataset_id": dataset_id,
        "git_hash": git_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_configs": len(entries),
        "strict_count": len(strict_leads),
        "research_count": len(research_leads),
        "strong_lead_count": len(strong_leads),
        "pf_strict": STRICT_PF,
        "pf_research": RESEARCH_PF,
        "exit_mode": "dc",
        "n_coins": n_coins,
        "fee_bps": round(KRAKEN_FEE * 10000, 1),
        "entries": entries,
    }
    sb_json = output_dir / "sweep_v1_scoreboard.json"
    with open(sb_json, "w") as f:
        json.dump(scoreboard, f, indent=2)
    print(f"\n  Scoreboard JSON: {sb_json}")

    # Write MD scoreboard
    md_lines = [
        "# Sweep v1 Scoreboard",
        "",
        f"- **Dataset**: {dataset_id} ({n_coins} coins)",
        f"- **Git**: {git_hash}",
        f"- **Generated**: {scoreboard['generated_at']}",
        f"- **Total configs**: {len(entries)}",
        f"- **Strict LEADs (PF > {STRICT_PF} + gates)**: {len(strict_leads)}",
        f"- **Research LEADs (PF > {RESEARCH_PF})**: {len(research_leads)}",
        f"- **STRONG LEADs (edge decomp)**: {len(strong_leads)}",
        f"- **Exit mode**: dc (hybrid_notrl: DC TARGET + RSI RECOVERY + BB TARGET)",
        f"- **Fee**: {KRAKEN_FEE * 10000:.0f} bps per side (Kraken)",
        "",
    ]

    # Section 1: Strict LEADs
    if strict_leads:
        md_lines.append(f"## Strict LEADs (PF > {STRICT_PF} + all gates pass)")
        md_lines.append("")
        md_lines.append(
            "| # | ID | Family | PF | Trades | DD% | WR% | P&L | EV/t | A% | Grade | Gates |"
        )
        md_lines.append(
            "|---|-----|--------|-----|--------|------|------|------|-------|-----|-------|-------|"
        )
        for i, e in enumerate(strict_leads, 1):
            md_lines.append(
                f"| {i} | {e['config_id']} | {e['family']} "
                f"| {e['pf']:.2f} | {e['trades']} | {e['dd']:.1f}% | {e['wr']:.1f}% "
                f"| ${e['pnl']:+,.2f} | ${e['ev_per_trade']:+.2f} "
                f"| {e['class_a_share']:.0%} | {e['research_grade']} "
                f"| {e['gates_passed']}/{e['gates_total']} |"
            )
        md_lines.append("")

    # Section 2: Research LEADs
    research_only = [e for e in research_leads if e not in strict_leads]
    if research_only:
        md_lines.append(f"## Research LEADs (PF > {RESEARCH_PF}, not strict)")
        md_lines.append("")
        md_lines.append(
            "| # | ID | Family | PF | Trades | DD% | WR% | P&L | EV/t | A% | Grade | Gates |"
        )
        md_lines.append(
            "|---|-----|--------|-----|--------|------|------|------|-------|-----|-------|-------|"
        )
        for i, e in enumerate(research_only, 1):
            md_lines.append(
                f"| {i} | {e['config_id']} | {e['family']} "
                f"| {e['pf']:.2f} | {e['trades']} | {e['dd']:.1f}% | {e['wr']:.1f}% "
                f"| ${e['pnl']:+,.2f} | ${e['ev_per_trade']:+.2f} "
                f"| {e['class_a_share']:.0%} | {e['research_grade']} "
                f"| {e['gates_passed']}/{e['gates_total']} |"
            )
        md_lines.append("")

    # Section 3: All Results
    md_lines.append("## All Results")
    md_lines.append("")
    md_lines.append(
        "| # | ID | Family | PF | Trades | DD% | P&L | EV/t | A% | Stopout | Grade | Compat |"
    )
    md_lines.append(
        "|---|-----|--------|-----|--------|------|------|-------|-----|---------|-------|--------|"
    )
    for i, e in enumerate(entries, 1):
        md_lines.append(
            f"| {i} | {e['config_id']} | {e['family']} "
            f"| {e['pf']:.2f} | {e['trades']} | {e['dd']:.1f}% "
            f"| ${e['pnl']:+,.2f} | ${e['ev_per_trade']:+.2f} "
            f"| {e['class_a_share']:.0%} | {e['stopout_ratio']:.0%} "
            f"| {e['research_grade']} | {e['compat_score']:.4f} |"
        )
    md_lines.append("")

    # Family summary
    md_lines.append("## Family Summary")
    md_lines.append("")
    md_lines.append(
        "| Family | Cat | Configs | Strict | Research | Best PF | Avg PF | Avg Compat | Best P&L |"
    )
    md_lines.append(
        "|--------|-----|---------|--------|----------|---------|--------|------------|----------|"
    )
    family_ids = sorted(set(e["family"] for e in entries))
    for fam_id in family_ids:
        fam_entries = [e for e in entries if e["family"] == fam_id]
        fam_strict = [e for e in fam_entries if e["pf"] >= STRICT_PF and e["verdict"] == "GO"]
        fam_research = [e for e in fam_entries if e["pf"] >= RESEARCH_PF]
        best_pf = max(e["pf"] for e in fam_entries) if fam_entries else 0
        avg_pf = sum(e["pf"] for e in fam_entries) / len(fam_entries) if fam_entries else 0
        avg_compat = sum(e["compat_score"] for e in fam_entries) / len(fam_entries) if fam_entries else 0
        best_pnl = max(e["pnl"] for e in fam_entries) if fam_entries else 0
        cat = fam_entries[0]["category"] if fam_entries else ""
        md_lines.append(
            f"| {fam_id} | {cat} | {len(fam_entries)} | {len(fam_strict)} "
            f"| {len(fam_research)} | {best_pf:.2f} | {avg_pf:.2f} "
            f"| {avg_compat:.4f} | ${best_pnl:+,.2f} |"
        )
    md_lines.append("")

    sb_md = output_dir / "sweep_v1_scoreboard.md"
    with open(sb_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  Scoreboard MD:   {sb_md}")

    return scoreboard


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sweep v1 Runner -- New Edge Discovery (5 families, 30 configs)"
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Dataset ID or path")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Output directory")
    parser.add_argument("--force", action="store_true", help="Re-run existing results")
    parser.add_argument("--dry-run", action="store_true", help="Phase 0 + Phase 1 only (no backtest)")
    parser.add_argument("--only", default=None, help="Filter to one family (e.g., WickSweepReclaim)")
    parser.add_argument("--top-n", type=int, default=15,
                        help="Top N compat entries to backtest (default: 15, use 30 for all)")
    parser.add_argument("--momentum-period", type=int, default=10,
                        help="Market context momentum period (default: 10)")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)

    print(f"\n{'=' * 80}")
    print(f"  Sweep v1 -- New Edge Discovery (5 families, 30 configs)")
    print(f"{'=' * 80}")

    # ===================================================================
    # PHASE 0: Load data, precompute, build universe
    # ===================================================================
    print(f"\n{'=' * 80}")
    print(f"  PHASE 0: Data Loading & Preparation")
    print(f"{'=' * 80}")

    # Build configs
    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Filter by family if --only
    if args.only:
        configs = [c for c in configs if c["family"] == args.only]
        print(f"  Filtered to family '{args.only}': {len(configs)} configs")
        if not configs:
            print(f"  ERROR: No configs match family '{args.only}'.")
            print(f"  Available families: {sorted(set(c['family'] for c in build_sweep_configs()))}")
            sys.exit(1)

    if args.dry_run:
        print(f"\n  DRY RUN -- configs to be evaluated:")
        for cfg in configs:
            print(f"    [{cfg['idx']:2d}] {cfg['id']} -- {cfg['hypothesis_name']} ({cfg['family']})")
            clean_p = {k: v for k, v in cfg["params"].items() if not k.startswith("__")}
            print(f"         params: {json.dumps(clean_p, sort_keys=True)}")

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

    # Build universe (coins with >= MIN_BARS bars)
    all_coins = sorted([k for k in data if not k.startswith("_")])
    coins = [c for c in all_coins if len(data.get(c, [])) >= MIN_BARS]
    print(f"  All coins: {len(all_coins)}, universe (>={MIN_BARS} bars): {len(coins)}")
    print(f"  Data loaded: {time.time() - t0:.1f}s")

    # Verify provenance
    print(f"\n  Verifying provenance...")
    prov_ok, prov_violations = verify_provenance(data, coins)
    if not prov_ok:
        print(f"  PROVENANCE VIOLATIONS:")
        for v in prov_violations:
            print(f"    - {v}")
        print(f"  ABORTING: provenance check failed. Fix data/universe and retry.")
        sys.exit(1)
    print(f"  Provenance: OK ({len(coins)} coins)")

    # Precompute Sweep v1 indicators (extends Sprint 2 with pivots, ATR%, BB squeeze, swing)
    print(f"  Precomputing Sweep v1 indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    # Compute cross-sectional RSI rank
    n_bars = max(ind["n"] for ind in indicators.values()) if indicators else 0
    print(f"  Precomputing RSI rank (cross-sectional, {n_bars} bars)...")
    t_rsi = time.time()
    rsi_rank = precompute_rsi_rank(indicators, coins, n_bars)
    print(f"  RSI rank: {time.time() - t_rsi:.1f}s")

    # Inject RSI rank into per-coin indicators
    for coin in coins:
        ind = indicators.get(coin)
        if ind is None:
            continue
        ind["__rsi_percentile__"] = rsi_rank["rsi_percentile"].get(coin, [None] * n_bars)
        ind["__rsi_median__"] = rsi_rank["rsi_median"]

    # Precompute market context (for families that need cross-sectional data)
    print(f"  Precomputing market context (momentum_period={args.momentum_period})...")
    t2 = time.time()
    market_ctx = precompute_sprint2_context(data, coins, momentum_period=args.momentum_period)
    print(f"  Market context: {time.time() - t2:.1f}s")

    # Deterministic replay test on first config
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

    # Summary
    total_elapsed = time.time() - t0
    print(f"\n  Phase 0 complete: {len(coins)} coins, {n_bars} max bars, {total_elapsed:.1f}s total")

    # ===================================================================
    # PHASE 1: Compatibility Pre-scoring
    # ===================================================================
    print(f"\n{'=' * 80}")
    print(f"  PHASE 1: Compatibility Pre-scoring ({len(configs)} configs)")
    print(f"{'=' * 80}")

    scored = _prescore_configs(configs, data, coins, indicators, market_ctx)

    compat_scores: dict[str, dict] = {}
    for cfg, cs in scored:
        compat_scores[cfg["id"]] = cs

    # Write compat scores JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    compat_json_path = output_dir / "sweep_v1_compat_scores.json"
    compat_json = {
        "experiment_id": "sweep_v1",
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

    # Phase 1 summary
    n_passing = sum(1 for _, cs in scored if cs["hard_pass"])
    print(f"  Phase 1 complete: {n_passing}/{len(scored)} configs have passing entries")
    if scored:
        print(f"  Top compat: {scored[0][0]['id']} avg={scored[0][1]['avg_composite']:.4f}")
        if len(scored) > 1:
            print(f"  2nd compat: {scored[1][0]['id']} avg={scored[1][1]['avg_composite']:.4f}")

    if args.dry_run:
        print(f"\n  --dry-run: skipping Phase 2 (backtest).")
        print(f"{'=' * 80}\n")
        return

    # Select top-N for backtesting (only those with hard_pass=True)
    passing_scored = [(cfg, cs) for cfg, cs in scored if cs["hard_pass"]]
    top_n = min(args.top_n, len(passing_scored))
    if top_n == 0:
        print(f"\n  WARNING: No configs passed hard filter. Nothing to backtest.")
        print(f"{'=' * 80}\n")
        return

    backtest_configs = passing_scored[:top_n]
    print(f"\n  Selected top-{top_n} configs for backtesting:")
    for cfg, cs in backtest_configs:
        print(f"    {cfg['id']} -- avg_compat={cs['avg_composite']:.4f}")

    # ===================================================================
    # PHASE 2: Backtest
    # ===================================================================
    print(f"\n{'=' * 80}")
    print(f"  PHASE 2: Backtest ({len(backtest_configs)} configs, exit_mode=dc)")
    print(f"{'=' * 80}")

    results = []
    for cfg, cs in backtest_configs:
        result = _run_single(
            cfg, data, coins, indicators, market_ctx, output_dir,
            git_hash, args.dataset, compat_score=cs, force=args.force,
        )
        results.append(result)

    # Phase 2 summary
    valid_results = [r for r in results if r is not None]
    strict_count = sum(
        1 for r in valid_results
        if r.get("summary", {}).get("pf", 0) >= STRICT_PF
    )
    research_count = sum(
        1 for r in valid_results
        if r.get("summary", {}).get("pf", 0) >= RESEARCH_PF
    )
    strong_count = sum(
        1 for r in valid_results
        if r.get("edge_decomposition", {}).get("research_grade") == "STRONG_LEAD"
    )

    print(f"\n{'=' * 80}")
    print(f"  Phase 2 complete: {len(backtest_configs)} configs backtested")
    print(f"  Strict LEADs (PF > {STRICT_PF}): {strict_count}")
    print(f"  Research      (PF > {RESEARCH_PF}): {research_count}")
    print(f"  STRONG LEADs  (decomp):     {strong_count}")

    # Build scoreboard
    scoreboard = _build_scoreboard(
        valid_results, output_dir, git_hash, args.dataset,
        compat_scores, n_coins=len(coins),
    )

    # Write edge decomposition batch analysis report
    print(f"\n  Writing edge decomposition report...")
    analysis_configs = []
    for r in valid_results:
        config_id = r.get("metadata", {}).get("config_id", "")
        cfg_match = next((c for c, _ in backtest_configs if c["id"] == config_id), None)
        if cfg_match is not None:
            analysis_configs.append((
                {
                    "id": config_id,
                    "family": r.get("metadata", {}).get("family", ""),
                },
                {
                    "summary": r.get("summary", {}),
                    "exit_classes": r.get("exit_classes", {}),
                    "trades": r.get("trades", []),
                },
            ))

    if analysis_configs:
        batch_result = batch_analysis(analysis_configs, compat_scores=compat_scores)
        report_base = str(output_dir / "sweep_v1_edge_analysis")
        json_path, md_path = write_analysis_report(batch_result, report_base)
        print(f"  Edge analysis JSON: {json_path}")
        print(f"  Edge analysis MD:   {md_path}")

    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
