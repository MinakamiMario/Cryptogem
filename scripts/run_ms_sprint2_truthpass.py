#!/usr/bin/env python3
"""
MS Sprint 2 Truth-Pass — Robustness validation for top-4 MS Sprint 1 survivors.

Three robustness tests per config:
  1. 3-Way Window Split: early/mid/late thirds of bar range
  2. Walk-Forward: calibrate on early, test on late (two splits)
  3. Bootstrap Monte Carlo: 1000 trade-order resamples

Verdicts:
  ALL 3 PASS  → VERIFIED
  2/3 PASS    → CONDITIONAL
  ≤1/3 PASS   → FAILED

Top-4 candidates from Sprint 1:
  ms_018_mse_shallow (shift_pb):  PF=2.08, 697 trades, DD=21.3%
  ms_005_msb_base    (fvg_fill):  PF=1.65, 429 trades, DD=19.5%
  ms_017_mse_fib618  (shift_pb):  PF=1.80, 475 trades, DD=28.0%
  ms_007_msb_deep    (fvg_fill):  PF=1.66, 344 trades, DD=22.9%

Usage:
    python3 scripts/run_ms_sprint2_truthpass.py
    python3 scripts/run_ms_sprint2_truthpass.py --only 018,005
    python3 scripts/run_ms_sprint2_truthpass.py --resamples 5000
    python3 scripts/run_ms_sprint2_truthpass.py --dry-run
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

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")

resolve_dataset = _data_resolver.resolve_dataset
run_backtest = _sprint3_engine.run_backtest
precompute_ms_indicators = _ms_indicators.precompute_ms_indicators
build_sweep_configs = _ms_hypotheses.build_sweep_configs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATASET_ID = "4h_default"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "ms"
MIN_BARS = 360
START_BAR = 50
N_RESAMPLES = 1000
SEED = 42

# Top-4 configs from MS Sprint 1 (by PF, all pass hard+soft gates)
TOP4_IDS = [
    "ms_018_mse_shallow",   # shift_pb: PF=2.08, 697 trades, DD=21.3%
    "ms_005_msb_base",      # fvg_fill: PF=1.65, 429 trades, DD=19.5%
    "ms_017_mse_fib618",    # shift_pb: PF=1.80, 475 trades, DD=28.0%
    "ms_007_msb_deep",      # fvg_fill: PF=1.66, 344 trades, DD=22.9%
]


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _determine_max_bars(indicators: dict) -> int:
    """Determine the maximum number of bars across all coins."""
    return max(ind["n"] for ind in indicators.values()) if indicators else 0


def _compute_window_boundaries(max_bars: int) -> dict:
    """Compute bar boundaries for 3-way window split."""
    usable_range = max_bars - START_BAR
    third = usable_range // 3

    early_start = START_BAR
    early_end = START_BAR + third
    mid_start = early_end
    mid_end = mid_start + third
    late_start = mid_end
    late_end = max_bars

    return {
        "early": {"start_bar": early_start, "end_bar": early_end},
        "mid": {"start_bar": mid_start, "end_bar": mid_end},
        "late": {"start_bar": late_start, "end_bar": late_end},
        "max_bars": max_bars,
    }


def _run_bt(
    data: dict,
    coins: list[str],
    signal_fn,
    params: dict,
    indicators: dict,
    start_bar: int = START_BAR,
    end_bar: int | None = None,
) -> dict:
    """Run a single backtest and return summary dict."""
    bt = run_backtest(
        data, coins, signal_fn, params, indicators,
        exit_mode="dc",
        start_bar=start_bar,
        end_bar=end_bar,
    )
    return {
        "trades": bt.trades,
        "pf": round(min(bt.pf, 99.99), 4),
        "pnl": round(bt.pnl, 2),
        "wr": round(bt.wr, 2),
        "dd": round(bt.dd, 2),
        "final_equity": round(bt.final_equity, 2),
        "trade_list": bt.trade_list,
        "exit_classes": bt.exit_classes,
    }


# ---------------------------------------------------------------------------
# Test 1: 3-Way Window Split
# ---------------------------------------------------------------------------

def test_window_split(
    data: dict,
    coins: list[str],
    signal_fn,
    params: dict,
    indicators: dict,
    windows: dict,
) -> dict:
    """Run backtest on each of 3 windows. PASS if >= 2/3 have PF >= 1.0."""
    results = {}
    for window_name in ("early", "mid", "late"):
        w = windows[window_name]
        bt = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=w["start_bar"], end_bar=w["end_bar"])
        results[window_name] = {
            "start_bar": w["start_bar"],
            "end_bar": w["end_bar"],
            "trades": bt["trades"],
            "pf": bt["pf"],
            "pnl": bt["pnl"],
            "wr": bt["wr"],
            "dd": bt["dd"],
        }

    windows_profitable = sum(
        1 for w in ("early", "mid", "late")
        if results[w]["pf"] >= 1.0 and results[w]["trades"] > 0
    )
    passed = windows_profitable >= 2

    results["windows_profitable"] = windows_profitable
    results["pass"] = passed
    return results


# ---------------------------------------------------------------------------
# Test 2: Walk-Forward
# ---------------------------------------------------------------------------

def test_walk_forward(
    data: dict,
    coins: list[str],
    signal_fn,
    params: dict,
    indicators: dict,
    windows: dict,
) -> dict:
    """Walk-forward: two splits. PASS if either split passes."""
    max_bars = windows["max_bars"]
    early = windows["early"]
    mid = windows["mid"]
    late = windows["late"]

    # Split A: calibrate on early only, test on mid+late
    cal_a = _run_bt(data, coins, signal_fn, params, indicators,
                    start_bar=early["start_bar"], end_bar=early["end_bar"])
    test_a = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=mid["start_bar"], end_bar=max_bars)

    split_a = {
        "cal": {
            "start_bar": early["start_bar"], "end_bar": early["end_bar"],
            "trades": cal_a["trades"], "pf": cal_a["pf"],
            "pnl": cal_a["pnl"], "wr": cal_a["wr"], "dd": cal_a["dd"],
        },
        "test": {
            "start_bar": mid["start_bar"], "end_bar": max_bars,
            "trades": test_a["trades"], "pf": test_a["pf"],
            "pnl": test_a["pnl"], "wr": test_a["wr"], "dd": test_a["dd"],
        },
        "pass": (
            cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
            and test_a["pf"] >= 0.9 and test_a["trades"] > 0
        ),
    }

    # Split B: calibrate on early+mid, test on late
    cal_b = _run_bt(data, coins, signal_fn, params, indicators,
                    start_bar=early["start_bar"], end_bar=mid["end_bar"])
    test_b = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=late["start_bar"], end_bar=max_bars)

    split_b = {
        "cal": {
            "start_bar": early["start_bar"], "end_bar": mid["end_bar"],
            "trades": cal_b["trades"], "pf": cal_b["pf"],
            "pnl": cal_b["pnl"], "wr": cal_b["wr"], "dd": cal_b["dd"],
        },
        "test": {
            "start_bar": late["start_bar"], "end_bar": max_bars,
            "trades": test_b["trades"], "pf": test_b["pf"],
            "pnl": test_b["pnl"], "wr": test_b["wr"], "dd": test_b["dd"],
        },
        "pass": (
            cal_b["pf"] >= 1.0 and cal_b["trades"] > 0
            and test_b["pf"] >= 0.9 and test_b["trades"] > 0
        ),
    }

    passed = split_a["pass"] or split_b["pass"]

    return {
        "cal_early_test_midlate": split_a,
        "cal_earlymid_test_late": split_b,
        "pass": passed,
    }


# ---------------------------------------------------------------------------
# Test 3: Bootstrap Monte Carlo
# ---------------------------------------------------------------------------

def test_bootstrap(trade_list: list[dict], n_resamples: int = N_RESAMPLES) -> dict:
    """Bootstrap resample trade P&Ls. PASS if P5_PF >= 0.85 AND >= 60% profitable."""
    if not trade_list:
        return {
            "n_resamples": n_resamples,
            "seed": SEED,
            "n_trades": 0,
            "median_pf": 0.0,
            "p5_pf": 0.0,
            "p95_pf": 0.0,
            "median_pnl": 0.0,
            "p5_pnl": 0.0,
            "pct_profitable": 0.0,
            "pass": False,
        }

    rng = np.random.default_rng(SEED)
    pnls = np.array([t["pnl"] for t in trade_list])
    n_trades = len(pnls)

    resampled_pfs = []
    resampled_pnls = []

    for _ in range(n_resamples):
        sample = rng.choice(pnls, size=n_trades, replace=True)
        total_pnl = float(np.sum(sample))
        wins = sample[sample > 0]
        losses = sample[sample <= 0]
        sum_wins = float(np.sum(wins))
        sum_losses = float(np.abs(np.sum(losses)))
        if sum_losses > 0:
            pf = sum_wins / sum_losses
        elif sum_wins > 0:
            pf = 99.99
        else:
            pf = 0.0
        resampled_pfs.append(pf)
        resampled_pnls.append(total_pnl)

    pfs_arr = np.array(resampled_pfs)
    pnls_arr = np.array(resampled_pnls)

    median_pf = float(np.median(pfs_arr))
    p5_pf = float(np.percentile(pfs_arr, 5))
    p95_pf = float(np.percentile(pfs_arr, 95))
    median_pnl = float(np.median(pnls_arr))
    p5_pnl = float(np.percentile(pnls_arr, 5))
    pct_profitable = float(np.mean(pnls_arr > 0) * 100)

    passed = p5_pf >= 0.85 and pct_profitable >= 60.0

    return {
        "n_resamples": n_resamples,
        "seed": SEED,
        "n_trades": n_trades,
        "median_pf": round(median_pf, 4),
        "p5_pf": round(p5_pf, 4),
        "p95_pf": round(p95_pf, 4),
        "median_pnl": round(median_pnl, 2),
        "p5_pnl": round(p5_pnl, 2),
        "pct_profitable": round(pct_profitable, 2),
        "pass": passed,
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def _verdict(window_pass: bool, wf_pass: bool, bootstrap_pass: bool) -> tuple[str, int]:
    """Return (verdict_string, tests_passed_count)."""
    passed = sum([window_pass, wf_pass, bootstrap_pass])
    if passed == 3:
        return "VERIFIED", 3
    elif passed == 2:
        return "CONDITIONAL", 2
    else:
        return "FAILED", passed


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_json_report(result: dict, output_path: Path) -> None:
    """Write JSON report for a single config."""
    clean = dict(result)
    if "full_run" in clean and "trade_list" in clean["full_run"]:
        clean["full_run"] = {k: v for k, v in clean["full_run"].items()
                             if k != "trade_list"}
    with open(output_path, "w") as f:
        json.dump(clean, f, indent=2, default=str)


def _write_md_report(result: dict, output_path: Path) -> None:
    """Write human-readable markdown report for a single config."""
    r = result
    lines = [
        f"# MS Sprint 2 Truth-Pass: {r['config_id']}",
        "",
        f"- **Verdict**: **{r['verdict']}** ({r['tests_passed']}/3 tests passed)",
        f"- **Family**: {r['family']}",
        f"- **Dataset**: {r['dataset_id']}",
        f"- **Coins**: {r['n_coins']}",
        f"- **Fee model**: {r['fee_model']}",
        f"- **Git**: {r['git_hash']}",
        f"- **Timestamp**: {r['timestamp']}",
        "",
        "## Full Run Baseline",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Trades | {r['full_run']['trades']} |",
        f"| PF | {r['full_run']['pf']:.2f} |",
        f"| P&L | ${r['full_run']['pnl']:+,.2f} |",
        f"| WR | {r['full_run']['wr']:.1f}% |",
        f"| DD | {r['full_run']['dd']:.1f}% |",
        "",
    ]

    # Test 1: Window Split
    ws = r["window_split"]
    mark = "PASS" if ws["pass"] else "FAIL"
    lines.extend([
        f"## Test 1: 3-Way Window Split [{mark}]",
        "",
        f"Windows profitable: {ws['windows_profitable']}/3 (need >= 2)",
        "",
        "| Window | Bars | Trades | PF | P&L | WR | DD |",
        "|--------|------|--------|-----|------|-----|-----|",
    ])
    for wname in ("early", "mid", "late"):
        w = ws[wname]
        pf_mark = " *" if w["pf"] >= 1.0 and w["trades"] > 0 else ""
        lines.append(
            f"| {wname} | {w['start_bar']}-{w['end_bar']} "
            f"| {w['trades']} | {w['pf']:.2f}{pf_mark} "
            f"| ${w['pnl']:+,.2f} | {w['wr']:.1f}% | {w['dd']:.1f}% |"
        )
    lines.append("")

    # Test 2: Walk-Forward
    wf = r["walk_forward"]
    mark = "PASS" if wf["pass"] else "FAIL"
    lines.extend([
        f"## Test 2: Walk-Forward [{mark}]",
        "",
    ])
    for split_name, split_label in [
        ("cal_early_test_midlate", "Cal=Early, Test=Mid+Late"),
        ("cal_earlymid_test_late", "Cal=Early+Mid, Test=Late"),
    ]:
        s = wf[split_name]
        s_mark = "PASS" if s["pass"] else "FAIL"
        lines.extend([
            f"### {split_label} [{s_mark}]",
            "",
            "| Phase | Bars | Trades | PF | P&L | WR |",
            "|-------|------|--------|-----|------|-----|",
            f"| Cal | {s['cal']['start_bar']}-{s['cal']['end_bar']} "
            f"| {s['cal']['trades']} | {s['cal']['pf']:.2f} "
            f"| ${s['cal']['pnl']:+,.2f} | {s['cal']['wr']:.1f}% |",
            f"| Test | {s['test']['start_bar']}-{s['test']['end_bar']} "
            f"| {s['test']['trades']} | {s['test']['pf']:.2f} "
            f"| ${s['test']['pnl']:+,.2f} | {s['test']['wr']:.1f}% |",
            "",
        ])

    # Test 3: Bootstrap
    bs = r["bootstrap"]
    mark = "PASS" if bs["pass"] else "FAIL"
    lines.extend([
        f"## Test 3: Bootstrap Monte Carlo [{mark}]",
        "",
        f"- Resamples: {bs['n_resamples']} (seed={bs['seed']})",
        f"- Trades per resample: {bs['n_trades']}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Median PF | {bs['median_pf']:.2f} |",
        f"| P5 PF | {bs['p5_pf']:.2f} |",
        f"| P95 PF | {bs['p95_pf']:.2f} |",
        f"| Median P&L | ${bs['median_pnl']:+,.2f} |",
        f"| P5 P&L | ${bs['p5_pnl']:+,.2f} |",
        f"| % Profitable | {bs['pct_profitable']:.1f}% |",
        "",
    ])

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _write_summary(all_results: list[dict], output_dir: Path) -> None:
    """Write combined summary JSON and MD."""
    summary = {
        "experiment": "ms_sprint2_truthpass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_configs": len(all_results),
        "verdicts": {
            "VERIFIED": sum(1 for r in all_results if r["verdict"] == "VERIFIED"),
            "CONDITIONAL": sum(1 for r in all_results if r["verdict"] == "CONDITIONAL"),
            "FAILED": sum(1 for r in all_results if r["verdict"] == "FAILED"),
        },
        "configs": [
            {
                "config_id": r["config_id"],
                "family": r["family"],
                "verdict": r["verdict"],
                "tests_passed": r["tests_passed"],
                "full_pf": r["full_run"]["pf"],
                "full_pnl": r["full_run"]["pnl"],
                "full_trades": r["full_run"]["trades"],
                "full_dd": r["full_run"]["dd"],
                "window_pass": r["window_split"]["pass"],
                "wf_pass": r["walk_forward"]["pass"],
                "bootstrap_pass": r["bootstrap"]["pass"],
                "bootstrap_p5_pf": r["bootstrap"]["p5_pf"],
                "bootstrap_pct_profitable": r["bootstrap"]["pct_profitable"],
            }
            for r in all_results
        ],
    }
    json_path = output_dir / "sprint2_truthpass_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    # MD summary
    md_lines = [
        "# MS Sprint 2 Truth-Pass Summary",
        "",
        f"- **Timestamp**: {summary['timestamp']}",
        f"- **Configs tested**: {summary['n_configs']}",
        f"- **VERIFIED**: {summary['verdicts']['VERIFIED']}",
        f"- **CONDITIONAL**: {summary['verdicts']['CONDITIONAL']}",
        f"- **FAILED**: {summary['verdicts']['FAILED']}",
        "",
        "## Scoreboard",
        "",
        "| # | Config | Family | Verdict | Full PF | Full P&L | Trades | DD | Window | WF | Bootstrap (P5 PF / %Prof) |",
        "|---|--------|--------|---------|---------|----------|--------|-----|--------|----|---------------------------|",
    ]
    for i, r in enumerate(all_results, 1):
        ws_mark = "PASS" if r["window_split"]["pass"] else "FAIL"
        wf_mark = "PASS" if r["walk_forward"]["pass"] else "FAIL"
        bs_mark = "PASS" if r["bootstrap"]["pass"] else "FAIL"
        md_lines.append(
            f"| {i} | {r['config_id']} | {r['family']} | **{r['verdict']}** "
            f"| {r['full_run']['pf']:.2f} | ${r['full_run']['pnl']:+,.2f} "
            f"| {r['full_run']['trades']} | {r['full_run']['dd']:.1f}% | {ws_mark} | {wf_mark} "
            f"| {bs_mark} ({r['bootstrap']['p5_pf']:.2f} / {r['bootstrap']['pct_profitable']:.0f}%) |"
        )
    md_lines.append("")

    # Per-config detail
    for r in all_results:
        md_lines.extend([
            f"### {r['config_id']} ({r['family']}) -- {r['verdict']}",
            "",
        ])
        ws = r["window_split"]
        for wname in ("early", "mid", "late"):
            w = ws[wname]
            mark = "+" if w["pf"] >= 1.0 and w["trades"] > 0 else "-"
            md_lines.append(
                f"- Window {wname} [{mark}]: "
                f"{w['trades']}tr PF={w['pf']:.2f} P&L=${w['pnl']:+,.2f}"
            )
        wf = r["walk_forward"]
        for sn, sl in [("cal_early_test_midlate", "Early->Mid+Late"),
                       ("cal_earlymid_test_late", "Early+Mid->Late")]:
            s = wf[sn]
            mark = "+" if s["pass"] else "-"
            md_lines.append(
                f"- WF {sl} [{mark}]: "
                f"cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f}"
            )
        bs = r["bootstrap"]
        mark = "+" if bs["pass"] else "-"
        md_lines.append(
            f"- Bootstrap [{mark}]: "
            f"P5_PF={bs['p5_pf']:.2f} median_PF={bs['median_pf']:.2f} "
            f"%prof={bs['pct_profitable']:.0f}%"
        )
        md_lines.append("")

    md_path = output_dir / "sprint2_truthpass_summary.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"\n  Summary JSON: {json_path}")
    print(f"  Summary MD:   {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="MS Sprint 2 Truth-Pass: robustness validation for top MS Sprint 1 survivors"
    )
    parser.add_argument("--only", default=None,
                        help="Comma-separated 3-digit suffixes to filter configs (e.g. 018,005)")
    parser.add_argument("--resamples", type=int, default=N_RESAMPLES,
                        help=f"Bootstrap resamples (default: {N_RESAMPLES})")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT),
                        help="Output directory for reports")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing results")
    parser.add_argument("--dry-run", action="store_true",
                        help="List configs to test without running")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    n_resamples = args.resamples

    print(f"\n{'=' * 72}")
    print(f"  MS Sprint 2 Truth-Pass -- Robustness Validation")
    print(f"{'=' * 72}")

    # -----------------------------------------------------------------------
    # Determine which configs to test
    # -----------------------------------------------------------------------
    all_configs = build_sweep_configs()
    config_map = {c["id"]: c for c in all_configs}

    if args.only:
        patterns = [p.strip() for p in args.only.split(",")]
        target_ids = []
        for cfg in all_configs:
            for pat in patterns:
                if pat in cfg["id"]:
                    target_ids.append(cfg["id"])
                    break
        if not target_ids:
            print(f"  ERROR: No configs match --only={args.only}")
            print(f"  Available IDs: {[c['id'] for c in all_configs]}")
            sys.exit(1)
    else:
        target_ids = list(TOP4_IDS)

    configs_to_test = []
    for tid in target_ids:
        if tid in config_map:
            configs_to_test.append(config_map[tid])
        else:
            print(f"  WARNING: Config '{tid}' not found in sweep configs, skipping.")

    if not configs_to_test:
        print("  ERROR: No valid configs to test.")
        sys.exit(1)

    print(f"\n  Configs to test: {len(configs_to_test)}")
    for cfg in configs_to_test:
        print(f"    - {cfg['id']} ({cfg['family']})")

    if args.dry_run:
        print(f"\n  DRY RUN — exiting without running backtests.")
        return

    # Check existing results
    summary_json = output_dir / "sprint2_truthpass_summary.json"
    if summary_json.exists() and not args.force:
        print(f"\n  Results already exist at {summary_json}")
        print(f"  Use --force to overwrite")
        return

    # -----------------------------------------------------------------------
    # Load data and precompute
    # -----------------------------------------------------------------------
    print(f"\n  Loading dataset: {DATASET_ID}")
    t0 = time.time()
    dataset_path = resolve_dataset(DATASET_ID)
    with open(dataset_path) as f:
        data = json.load(f)
    print(f"  Dataset loaded: {time.time() - t0:.1f}s")

    # Build universe (same as Sprint 1 sweep)
    coins = [pair for pair in data if not pair.startswith("_")
             and isinstance(data[pair], list) and len(data[pair]) >= MIN_BARS]
    print(f"  Universe: {len(coins)} coins (>= {MIN_BARS} bars)")

    print(f"  Precomputing MS indicators...")
    t1 = time.time()
    indicators = precompute_ms_indicators(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    # Determine bar range
    max_bars = _determine_max_bars(indicators)
    windows = _compute_window_boundaries(max_bars)
    print(f"  Bar range: {START_BAR} to {max_bars} ({max_bars - START_BAR} usable bars)")
    print(f"  Window split: early={windows['early']['start_bar']}-{windows['early']['end_bar']}, "
          f"mid={windows['mid']['start_bar']}-{windows['mid']['end_bar']}, "
          f"late={windows['late']['start_bar']}-{windows['late']['end_bar']}")
    print(f"  Bootstrap resamples: {n_resamples} (seed={SEED})")

    # -----------------------------------------------------------------------
    # Run truth-pass for each config
    # -----------------------------------------------------------------------
    all_results = []

    for ci, cfg in enumerate(configs_to_test, 1):
        config_id = cfg["id"]
        signal_fn = cfg["signal_fn"]
        params = cfg["params"]

        print(f"\n{'=' * 72}")
        print(f"  [{ci}/{len(configs_to_test)}] {config_id} ({cfg['family']})")
        print(f"{'=' * 72}")

        # Full run baseline
        print(f"  Running full baseline...")
        t_start = time.time()
        full = _run_bt(data, coins, signal_fn, params, indicators)
        print(f"    Full: {full['trades']}tr PF={full['pf']:.2f} P&L=${full['pnl']:+,.2f} "
              f"WR={full['wr']:.1f}% DD={full['dd']:.1f}% ({time.time() - t_start:.1f}s)")

        # Test 1: Window Split
        print(f"  Test 1: 3-Way Window Split...")
        t1_start = time.time()
        ws_result = test_window_split(data, coins, signal_fn, params, indicators, windows)
        ws_mark = "PASS" if ws_result["pass"] else "FAIL"
        print(f"    [{ws_mark}] {ws_result['windows_profitable']}/3 windows profitable ({time.time() - t1_start:.1f}s)")
        for wname in ("early", "mid", "late"):
            w = ws_result[wname]
            print(f"      {wname}: {w['trades']}tr PF={w['pf']:.2f} P&L=${w['pnl']:+,.2f}")

        # Test 2: Walk-Forward
        print(f"  Test 2: Walk-Forward...")
        t2_start = time.time()
        wf_result = test_walk_forward(data, coins, signal_fn, params, indicators, windows)
        wf_mark = "PASS" if wf_result["pass"] else "FAIL"
        print(f"    [{wf_mark}] ({time.time() - t2_start:.1f}s)")
        for sn, sl in [("cal_early_test_midlate", "Early->Mid+Late"),
                       ("cal_earlymid_test_late", "Early+Mid->Late")]:
            s = wf_result[sn]
            s_mark = "PASS" if s["pass"] else "FAIL"
            print(f"      [{s_mark}] {sl}: "
                  f"cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                  f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f}")

        # Test 3: Bootstrap
        print(f"  Test 3: Bootstrap Monte Carlo ({n_resamples} resamples)...")
        t3_start = time.time()
        bs_result = test_bootstrap(full["trade_list"], n_resamples=n_resamples)
        bs_mark = "PASS" if bs_result["pass"] else "FAIL"
        print(f"    [{bs_mark}] P5_PF={bs_result['p5_pf']:.2f} "
              f"median_PF={bs_result['median_pf']:.2f} "
              f"%profitable={bs_result['pct_profitable']:.1f}% "
              f"({time.time() - t3_start:.1f}s)")

        # Verdict
        verdict, tests_passed = _verdict(ws_result["pass"], wf_result["pass"], bs_result["pass"])
        print(f"\n  >>> VERDICT: {verdict} ({tests_passed}/3 tests passed)")

        # Build result dict
        result = {
            "config_id": config_id,
            "family": cfg["family"],
            "dataset_id": DATASET_ID,
            "n_coins": len(coins),
            "fee_model": "kraken_spot_26bps",
            "git_hash": git_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "full_run": {
                "trades": full["trades"],
                "pf": full["pf"],
                "pnl": full["pnl"],
                "wr": full["wr"],
                "dd": full["dd"],
            },
            "window_split": ws_result,
            "walk_forward": wf_result,
            "bootstrap": bs_result,
            "verdict": verdict,
            "tests_passed": tests_passed,
        }

        # Write per-config reports
        json_path = output_dir / f"sprint2_truthpass_{config_id}.json"
        md_path = output_dir / f"sprint2_truthpass_{config_id}.md"
        _write_json_report(result, json_path)
        _write_md_report(result, md_path)
        print(f"  Reports: {json_path.name}, {md_path.name}")

        all_results.append(result)

    # -----------------------------------------------------------------------
    # Combined summary
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 72}")
    print(f"  MS SPRINT 2 TRUTH-PASS COMPLETE")
    print(f"{'=' * 72}")

    n_verified = sum(1 for r in all_results if r["verdict"] == "VERIFIED")
    n_conditional = sum(1 for r in all_results if r["verdict"] == "CONDITIONAL")
    n_failed = sum(1 for r in all_results if r["verdict"] == "FAILED")
    print(f"  VERIFIED:    {n_verified}")
    print(f"  CONDITIONAL: {n_conditional}")
    print(f"  FAILED:      {n_failed}")

    for r in all_results:
        print(f"    {r['config_id']} ({r['family']}): {r['verdict']} "
              f"(PF={r['full_run']['pf']:.2f}, {r['tests_passed']}/3)")

    _write_summary(all_results, output_dir)

    print(f"\n{'=' * 72}\n")


if __name__ == "__main__":
    main()
