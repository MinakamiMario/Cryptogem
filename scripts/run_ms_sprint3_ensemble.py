#!/usr/bin/env python3
"""
MS Sprint 3 — Ensemble Analysis: shift_pb + fvg_fill combined.

Tests whether combining the two VERIFIED MS families creates a stronger portfolio:
  - ms_018 (shift_pb shallow) + ms_005 (fvg_fill base): Primary ensemble
  - Signal overlap analysis: how often do both families trigger on same bar/coin?
  - Combined portfolio metrics: PF, DD, trade count, per-source attribution
  - Truth-pass on ensemble config

Ensemble modes:
  priority:   shift_pb first, fvg_fill if no shift_pb signal (no overlap)
  strongest:  if both trigger, pick highest strength score
  both:       allow both signals (double exposure OK, max_pos handles it)

Usage:
    python3 scripts/run_ms_sprint3_ensemble.py
    python3 scripts/run_ms_sprint3_ensemble.py --mode strongest
    python3 scripts/run_ms_sprint3_ensemble.py --truth-pass
    python3 scripts/run_ms_sprint3_ensemble.py --dry-run
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
from collections import Counter

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

# Ensemble pairs: (primary, secondary)
ENSEMBLE_PAIRS = [
    ("ms_018_mse_shallow", "ms_005_msb_base"),   # best shift_pb + best fvg_fill (by DD)
    ("ms_018_mse_shallow", "ms_007_msb_deep"),   # best shift_pb + best fvg_fill (by PF)
    ("ms_017_mse_fib618", "ms_005_msb_base"),    # 2nd shift_pb + best fvg_fill
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
    return max(ind["n"] for ind in indicators.values()) if indicators else 0


def _compute_window_boundaries(max_bars: int) -> dict:
    usable_range = max_bars - START_BAR
    third = usable_range // 3
    return {
        "early": {"start_bar": START_BAR, "end_bar": START_BAR + third},
        "mid": {"start_bar": START_BAR + third, "end_bar": START_BAR + 2 * third},
        "late": {"start_bar": START_BAR + 2 * third, "end_bar": max_bars},
        "max_bars": max_bars,
    }


# ---------------------------------------------------------------------------
# Ensemble signal function factory
# ---------------------------------------------------------------------------

def make_ensemble_signal_fn(
    cfg_a: dict,
    cfg_b: dict,
    mode: str = "priority",
    tracker: dict | None = None,
):
    """Create an ensemble signal_fn that combines two signals.

    Modes:
        priority:  Try A first, then B if A returns None.
        strongest: If both fire, pick the one with higher strength.
        both:      Return A if it fires, else B. (Same as priority for engine,
                   but we track both for overlap analysis.)

    tracker: mutable dict for recording per-source attribution.
    """
    signal_fn_a = cfg_a["signal_fn"]
    params_a = cfg_a["params"]
    signal_fn_b = cfg_b["signal_fn"]
    params_b = cfg_b["params"]

    if tracker is None:
        tracker = {"a_count": 0, "b_count": 0, "both_count": 0, "total": 0}

    def ensemble_signal(candles, bar, indicators, params):
        # Try both signals
        result_a = signal_fn_a(candles, bar, indicators, params_a)
        result_b = signal_fn_b(candles, bar, indicators, params_b)

        # Track overlap
        a_fires = result_a is not None
        b_fires = result_b is not None

        if a_fires and b_fires:
            tracker["both_count"] += 1

        if not a_fires and not b_fires:
            return None

        tracker["total"] += 1

        if mode == "priority":
            if a_fires:
                tracker["a_count"] += 1
                result_a["_source"] = "A"
                return result_a
            tracker["b_count"] += 1
            result_b["_source"] = "B"
            return result_b

        elif mode == "strongest":
            if a_fires and b_fires:
                if result_a.get("strength", 0) >= result_b.get("strength", 0):
                    tracker["a_count"] += 1
                    result_a["_source"] = "A"
                    return result_a
                else:
                    tracker["b_count"] += 1
                    result_b["_source"] = "B"
                    return result_b
            elif a_fires:
                tracker["a_count"] += 1
                result_a["_source"] = "A"
                return result_a
            else:
                tracker["b_count"] += 1
                result_b["_source"] = "B"
                return result_b

        else:  # "both" — same as priority for single-signal engine
            if a_fires:
                tracker["a_count"] += 1
                result_a["_source"] = "A"
                return result_a
            tracker["b_count"] += 1
            result_b["_source"] = "B"
            return result_b

    return ensemble_signal, tracker


# ---------------------------------------------------------------------------
# Backtest wrapper
# ---------------------------------------------------------------------------

def _run_bt(
    data: dict,
    coins: list[str],
    signal_fn,
    params: dict,
    indicators: dict,
    start_bar: int = START_BAR,
    end_bar: int | None = None,
) -> dict:
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
# Truth-pass tests (reused from Sprint 2)
# ---------------------------------------------------------------------------

def test_window_split(data, coins, signal_fn, params, indicators, windows):
    results = {}
    for wn in ("early", "mid", "late"):
        w = windows[wn]
        bt = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=w["start_bar"], end_bar=w["end_bar"])
        results[wn] = {
            "start_bar": w["start_bar"], "end_bar": w["end_bar"],
            "trades": bt["trades"], "pf": bt["pf"],
            "pnl": bt["pnl"], "wr": bt["wr"], "dd": bt["dd"],
        }
    wp = sum(1 for w in ("early", "mid", "late")
             if results[w]["pf"] >= 1.0 and results[w]["trades"] > 0)
    results["windows_profitable"] = wp
    results["pass"] = wp >= 2
    return results


def test_walk_forward(data, coins, signal_fn, params, indicators, windows):
    mb = windows["max_bars"]
    e, m, l = windows["early"], windows["mid"], windows["late"]

    cal_a = _run_bt(data, coins, signal_fn, params, indicators,
                    start_bar=e["start_bar"], end_bar=e["end_bar"])
    test_a = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=m["start_bar"], end_bar=mb)
    sa = {
        "cal": {"start_bar": e["start_bar"], "end_bar": e["end_bar"],
                "trades": cal_a["trades"], "pf": cal_a["pf"],
                "pnl": cal_a["pnl"], "wr": cal_a["wr"], "dd": cal_a["dd"]},
        "test": {"start_bar": m["start_bar"], "end_bar": mb,
                 "trades": test_a["trades"], "pf": test_a["pf"],
                 "pnl": test_a["pnl"], "wr": test_a["wr"], "dd": test_a["dd"]},
        "pass": (cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
                 and test_a["pf"] >= 0.9 and test_a["trades"] > 0),
    }

    cal_b = _run_bt(data, coins, signal_fn, params, indicators,
                    start_bar=e["start_bar"], end_bar=m["end_bar"])
    test_b = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=l["start_bar"], end_bar=mb)
    sb = {
        "cal": {"start_bar": e["start_bar"], "end_bar": m["end_bar"],
                "trades": cal_b["trades"], "pf": cal_b["pf"],
                "pnl": cal_b["pnl"], "wr": cal_b["wr"], "dd": cal_b["dd"]},
        "test": {"start_bar": l["start_bar"], "end_bar": mb,
                 "trades": test_b["trades"], "pf": test_b["pf"],
                 "pnl": test_b["pnl"], "wr": test_b["wr"], "dd": test_b["dd"]},
        "pass": (cal_b["pf"] >= 1.0 and cal_b["trades"] > 0
                 and test_b["pf"] >= 0.9 and test_b["trades"] > 0),
    }

    return {
        "cal_early_test_midlate": sa,
        "cal_earlymid_test_late": sb,
        "pass": sa["pass"] or sb["pass"],
    }


def test_bootstrap(trade_list, n_resamples=N_RESAMPLES):
    if not trade_list:
        return {"n_resamples": n_resamples, "seed": SEED, "n_trades": 0,
                "median_pf": 0.0, "p5_pf": 0.0, "p95_pf": 0.0,
                "median_pnl": 0.0, "p5_pnl": 0.0, "pct_profitable": 0.0,
                "pass": False}

    rng = np.random.default_rng(SEED)
    pnls = np.array([t["pnl"] for t in trade_list])
    n = len(pnls)
    pfs, total_pnls = [], []
    for _ in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        wins = float(np.sum(sample[sample > 0]))
        losses = float(np.abs(np.sum(sample[sample <= 0])))
        pf = wins / losses if losses > 0 else (99.99 if wins > 0 else 0.0)
        pfs.append(pf)
        total_pnls.append(float(np.sum(sample)))

    pfs_arr, pnls_arr = np.array(pfs), np.array(total_pnls)
    p5_pf = float(np.percentile(pfs_arr, 5))
    return {
        "n_resamples": n_resamples, "seed": SEED, "n_trades": n,
        "median_pf": round(float(np.median(pfs_arr)), 4),
        "p5_pf": round(p5_pf, 4),
        "p95_pf": round(float(np.percentile(pfs_arr, 95)), 4),
        "median_pnl": round(float(np.median(pnls_arr)), 2),
        "p5_pnl": round(float(np.percentile(pnls_arr, 5)), 2),
        "pct_profitable": round(float(np.mean(pnls_arr > 0) * 100), 2),
        "pass": p5_pf >= 0.85 and float(np.mean(pnls_arr > 0) * 100) >= 60.0,
    }


def _verdict(wp, wfp, bp):
    passed = sum([wp, wfp, bp])
    if passed == 3: return "VERIFIED", 3
    elif passed == 2: return "CONDITIONAL", 2
    else: return "FAILED", passed


# ---------------------------------------------------------------------------
# Overlap analysis
# ---------------------------------------------------------------------------

def run_overlap_analysis(
    data: dict,
    coins: list[str],
    cfg_a: dict,
    cfg_b: dict,
    indicators: dict,
) -> dict:
    """Measure signal overlap between two configs (not through engine)."""
    signal_fn_a = cfg_a["signal_fn"]
    params_a = cfg_a["params"]
    signal_fn_b = cfg_b["signal_fn"]
    params_b = cfg_b["params"]

    a_only = 0
    b_only = 0
    both = 0
    neither = 0
    total_bars = 0

    for coin in coins:
        ind = indicators.get(coin)
        if ind is None:
            continue
        n = ind["n"]
        candles = data[coin]
        for bar in range(START_BAR, n):
            total_bars += 1
            r_a = signal_fn_a(candles, bar, ind, params_a)
            r_b = signal_fn_b(candles, bar, ind, params_b)
            a_fires = r_a is not None
            b_fires = r_b is not None
            if a_fires and b_fires:
                both += 1
            elif a_fires:
                a_only += 1
            elif b_fires:
                b_only += 1
            else:
                neither += 1

    total_signals = a_only + b_only + both
    return {
        "total_bars": total_bars,
        "a_only": a_only,
        "b_only": b_only,
        "both": both,
        "neither": neither,
        "total_signals": total_signals,
        "overlap_rate": round(both / total_signals * 100, 2) if total_signals > 0 else 0,
        "a_share": round((a_only + both) / total_signals * 100, 2) if total_signals > 0 else 0,
        "b_share": round((b_only + both) / total_signals * 100, 2) if total_signals > 0 else 0,
        "signal_rate_per_1000": round(total_signals / total_bars * 1000, 2) if total_bars > 0 else 0,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_summary(all_results: list[dict], output_dir: Path) -> None:
    json_path = output_dir / "sprint3_ensemble_summary.json"
    with open(json_path, "w") as f:
        json.dump({
            "experiment": "ms_sprint3_ensemble",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "n_ensembles": len(all_results),
            "results": [
                {k: v for k, v in r.items() if k != "trade_list"}
                for r in all_results
            ],
        }, f, indent=2, default=str)

    md_lines = [
        "# MS Sprint 3 — Ensemble Analysis Summary",
        "",
        f"- **Timestamp**: {datetime.now(timezone.utc).isoformat()}",
        f"- **Ensembles tested**: {len(all_results)}",
        "",
        "## Scoreboard",
        "",
        "| # | Ensemble | Mode | Trades | PF | P&L | DD | A/B Split | Overlap | Verdict |",
        "|---|----------|------|--------|-----|------|-----|-----------|---------|---------|",
    ]
    for i, r in enumerate(all_results, 1):
        ov = r.get("overlap", {})
        tp = r.get("truth_pass", {})
        verdict = tp.get("verdict", "N/A") if tp else "N/A"
        md_lines.append(
            f"| {i} | {r['ensemble_id']} | {r['mode']} "
            f"| {r['full_run']['trades']} | {r['full_run']['pf']:.2f} "
            f"| ${r['full_run']['pnl']:+,.2f} | {r['full_run']['dd']:.1f}% "
            f"| {r['tracker']['a_count']}/{r['tracker']['b_count']} "
            f"| {ov.get('overlap_rate', 0):.1f}% | {verdict} |"
        )
    md_lines.append("")

    # Per-ensemble detail
    for r in all_results:
        md_lines.extend([
            f"### {r['ensemble_id']} ({r['mode']})",
            "",
            f"- **Components**: {r['config_a_id']} (A) + {r['config_b_id']} (B)",
            f"- **Full run**: {r['full_run']['trades']}tr PF={r['full_run']['pf']:.2f} "
            f"P&L=${r['full_run']['pnl']:+,.2f} DD={r['full_run']['dd']:.1f}%",
            "",
        ])
        # Tracker
        t = r["tracker"]
        md_lines.extend([
            f"- **Source A** ({r['config_a_id']}): {t['a_count']} entries",
            f"- **Source B** ({r['config_b_id']}): {t['b_count']} entries",
            f"- **Both fired**: {t['both_count']} times",
            "",
        ])
        # Overlap
        ov = r.get("overlap", {})
        if ov:
            md_lines.extend([
                f"- **Signal overlap**: {ov['overlap_rate']:.1f}% "
                f"(A-only={ov['a_only']}, B-only={ov['b_only']}, both={ov['both']})",
                f"- **Signal rate**: {ov['signal_rate_per_1000']:.1f} per 1000 bars",
                "",
            ])
        # Comparison to components
        for key in ("vs_a", "vs_b"):
            comp = r.get(key)
            if comp:
                md_lines.append(
                    f"- **vs {comp['id']}**: "
                    f"PF {comp['standalone_pf']:.2f}→{r['full_run']['pf']:.2f}, "
                    f"DD {comp['standalone_dd']:.1f}%→{r['full_run']['dd']:.1f}%, "
                    f"trades {comp['standalone_trades']}→{r['full_run']['trades']}"
                )
        md_lines.append("")
        # Truth-pass
        tp = r.get("truth_pass")
        if tp:
            md_lines.extend([
                f"- **Truth-pass**: **{tp['verdict']}** ({tp['tests_passed']}/3)",
                f"  - Window: {'PASS' if tp['window_pass'] else 'FAIL'}",
                f"  - WF: {'PASS' if tp['wf_pass'] else 'FAIL'}",
                f"  - Bootstrap: {'PASS' if tp['bootstrap_pass'] else 'FAIL'} "
                f"(P5_PF={tp['bootstrap_p5_pf']:.2f}, %prof={tp['bootstrap_pct_profitable']:.0f}%)",
                "",
            ])

    md_path = output_dir / "sprint3_ensemble_summary.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"\n  Summary JSON: {json_path}")
    print(f"  Summary MD:   {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="MS Sprint 3: Ensemble analysis (shift_pb + fvg_fill)"
    )
    parser.add_argument("--mode", default="priority",
                        choices=["priority", "strongest"],
                        help="Ensemble mode (default: priority)")
    parser.add_argument("--truth-pass", action="store_true",
                        help="Run truth-pass on ensemble configs")
    parser.add_argument("--resamples", type=int, default=N_RESAMPLES)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 72}")
    print(f"  MS Sprint 3 — Ensemble Analysis (shift_pb + fvg_fill)")
    print(f"{'=' * 72}")

    # Resolve configs
    all_configs = build_sweep_configs()
    config_map = {c["id"]: c for c in all_configs}

    ensembles_to_test = []
    for (id_a, id_b) in ENSEMBLE_PAIRS:
        if id_a not in config_map or id_b not in config_map:
            print(f"  WARNING: Pair ({id_a}, {id_b}) not found, skipping.")
            continue
        ensembles_to_test.append((config_map[id_a], config_map[id_b]))

    print(f"\n  Ensemble pairs: {len(ensembles_to_test)}")
    for cfg_a, cfg_b in ensembles_to_test:
        print(f"    - {cfg_a['id']} + {cfg_b['id']}")
    print(f"  Mode: {args.mode}")
    print(f"  Truth-pass: {'yes' if args.truth_pass else 'no'}")

    if args.dry_run:
        print(f"\n  DRY RUN — exiting.")
        return

    # Check existing
    summary_json = output_dir / "sprint3_ensemble_summary.json"
    if summary_json.exists() and not args.force:
        print(f"\n  Results exist at {summary_json}. Use --force to overwrite.")
        return

    # Load data
    print(f"\n  Loading dataset: {DATASET_ID}")
    t0 = time.time()
    dataset_path = resolve_dataset(DATASET_ID)
    with open(dataset_path) as f:
        data = json.load(f)
    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    print(f"  Loaded: {len(coins)} coins ({time.time() - t0:.1f}s)")

    print(f"  Precomputing MS indicators...")
    t1 = time.time()
    indicators = precompute_ms_indicators(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    max_bars = _determine_max_bars(indicators)
    windows = _compute_window_boundaries(max_bars)

    # Run standalone baselines for comparison
    print(f"\n  Running standalone baselines...")
    standalone_cache = {}
    standalone_ids = set()
    for cfg_a, cfg_b in ensembles_to_test:
        standalone_ids.add(cfg_a["id"])
        standalone_ids.add(cfg_b["id"])

    for sid in sorted(standalone_ids):
        cfg = config_map[sid]
        t_s = time.time()
        bt = _run_bt(data, coins, cfg["signal_fn"], cfg["params"], indicators)
        standalone_cache[sid] = bt
        print(f"    {sid}: {bt['trades']}tr PF={bt['pf']:.2f} "
              f"DD={bt['dd']:.1f}% ({time.time() - t_s:.1f}s)")

    # Run ensembles
    all_results = []

    for ei, (cfg_a, cfg_b) in enumerate(ensembles_to_test, 1):
        ensemble_id = f"ens_{cfg_a['id']}+{cfg_b['id']}"
        print(f"\n{'=' * 72}")
        print(f"  [{ei}/{len(ensembles_to_test)}] {cfg_a['id']} + {cfg_b['id']} ({args.mode})")
        print(f"{'=' * 72}")

        # Overlap analysis
        print(f"  Overlap analysis...")
        t_ov = time.time()
        overlap = run_overlap_analysis(data, coins, cfg_a, cfg_b, indicators)
        print(f"    Signals: A-only={overlap['a_only']}, B-only={overlap['b_only']}, "
              f"both={overlap['both']} (overlap={overlap['overlap_rate']:.1f}%) "
              f"({time.time() - t_ov:.1f}s)")

        # Ensemble backtest
        tracker = {"a_count": 0, "b_count": 0, "both_count": 0, "total": 0}
        ens_fn, tracker = make_ensemble_signal_fn(cfg_a, cfg_b, mode=args.mode, tracker=tracker)

        print(f"  Full ensemble run...")
        t_full = time.time()
        full = _run_bt(data, coins, ens_fn, {}, indicators)
        print(f"    Full: {full['trades']}tr PF={full['pf']:.2f} P&L=${full['pnl']:+,.2f} "
              f"DD={full['dd']:.1f}% ({time.time() - t_full:.1f}s)")
        print(f"    Source: A={tracker['a_count']} B={tracker['b_count']} "
              f"(both fired={tracker['both_count']})")

        # Comparison to standalone
        sa = standalone_cache[cfg_a["id"]]
        sb = standalone_cache[cfg_b["id"]]

        result = {
            "ensemble_id": ensemble_id,
            "config_a_id": cfg_a["id"],
            "config_b_id": cfg_b["id"],
            "family_a": cfg_a["family"],
            "family_b": cfg_b["family"],
            "mode": args.mode,
            "git_hash": git_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "full_run": {
                "trades": full["trades"], "pf": full["pf"],
                "pnl": full["pnl"], "wr": full["wr"], "dd": full["dd"],
            },
            "tracker": tracker,
            "overlap": overlap,
            "vs_a": {
                "id": cfg_a["id"],
                "standalone_pf": sa["pf"],
                "standalone_trades": sa["trades"],
                "standalone_dd": sa["dd"],
                "standalone_pnl": sa["pnl"],
            },
            "vs_b": {
                "id": cfg_b["id"],
                "standalone_pf": sb["pf"],
                "standalone_trades": sb["trades"],
                "standalone_dd": sb["dd"],
                "standalone_pnl": sb["pnl"],
            },
        }

        # Truth-pass on ensemble
        if args.truth_pass:
            print(f"  Truth-pass...")
            # Need fresh tracker for each window/WF run
            def _make_ens_fn():
                t = {"a_count": 0, "b_count": 0, "both_count": 0, "total": 0}
                fn, _ = make_ensemble_signal_fn(cfg_a, cfg_b, mode=args.mode, tracker=t)
                return fn

            t_tp = time.time()

            # Window split
            ws = test_window_split(data, coins, _make_ens_fn(), {}, indicators, windows)
            ws_mark = "PASS" if ws["pass"] else "FAIL"
            print(f"    Window: [{ws_mark}] {ws['windows_profitable']}/3")
            for wn in ("early", "mid", "late"):
                w = ws[wn]
                print(f"      {wn}: {w['trades']}tr PF={w['pf']:.2f}")

            # Walk-forward
            wf = test_walk_forward(data, coins, _make_ens_fn(), {}, indicators, windows)
            wf_mark = "PASS" if wf["pass"] else "FAIL"
            print(f"    WF: [{wf_mark}]")
            for sn, sl in [("cal_early_test_midlate", "E→M+L"),
                           ("cal_earlymid_test_late", "E+M→L")]:
                s = wf[sn]
                sm = "PASS" if s["pass"] else "FAIL"
                print(f"      [{sm}] {sl}: cal PF={s['cal']['pf']:.2f}, test PF={s['test']['pf']:.2f}")

            # Bootstrap
            bs = test_bootstrap(full["trade_list"], n_resamples=args.resamples)
            bs_mark = "PASS" if bs["pass"] else "FAIL"
            print(f"    Bootstrap: [{bs_mark}] P5_PF={bs['p5_pf']:.2f} %prof={bs['pct_profitable']:.0f}%")

            verdict, tests_passed = _verdict(ws["pass"], wf["pass"], bs["pass"])
            print(f"    >>> VERDICT: {verdict} ({tests_passed}/3)")
            print(f"    ({time.time() - t_tp:.1f}s)")

            result["truth_pass"] = {
                "verdict": verdict,
                "tests_passed": tests_passed,
                "window_pass": ws["pass"],
                "wf_pass": wf["pass"],
                "bootstrap_pass": bs["pass"],
                "bootstrap_p5_pf": bs["p5_pf"],
                "bootstrap_pct_profitable": bs["pct_profitable"],
                "window_split": ws,
                "walk_forward": wf,
                "bootstrap": bs,
            }

        all_results.append(result)

    # Summary
    print(f"\n{'=' * 72}")
    print(f"  MS SPRINT 3 ENSEMBLE ANALYSIS COMPLETE")
    print(f"{'=' * 72}")

    for r in all_results:
        tp = r.get("truth_pass", {})
        verdict = tp.get("verdict", "N/A") if tp else "N/A"
        print(f"  {r['config_a_id']} + {r['config_b_id']} ({r['mode']}): "
              f"PF={r['full_run']['pf']:.2f} DD={r['full_run']['dd']:.1f}% "
              f"trades={r['full_run']['trades']} "
              f"[A={r['tracker']['a_count']} B={r['tracker']['b_count']}] "
              f"verdict={verdict}")

    _write_summary(all_results, output_dir)
    print(f"\n{'=' * 72}\n")


if __name__ == "__main__":
    main()
