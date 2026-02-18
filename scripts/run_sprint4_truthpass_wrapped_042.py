#!/usr/bin/env python3
"""
Sprint 4 Truth-Pass with Vol-Scale Wrapper -- Config 042

Loads the existing trade list from sprint4_042 results, applies
the vol_scale risk wrapper (ATR14, percentile=25), then runs
the 3-test truth-pass battery on WRAPPED trades:

  1. 3-Way Window Split:  early/mid/late by entry_bar, 2/3 PF >= 1.0
  2. Walk-Forward:        early->mid+late, early+mid->late
                          at least 1 fold with cal PF >= 1.0 AND test PF >= 1.0
  3. Bootstrap Monte Carlo: 1000 resamples, P5 PF >= 0.85, >= 80% profitable

Vol_scale wrapper:
  - For each trade, look up ATR(14) at trade's pair+entry_bar
  - Reference ATR = percentile 25 of all trade ATRs
  - Scale: base_size * (ref_atr / trade_atr), capped [0.25x, 2.0x]
  - Wrapped pnl = original_pnl_pct / 100 * scaled_size

Output:
  reports/4h/sprint4_truthpass_wrapped_042.json
  reports/4h/sprint4_truthpass_wrapped_042.md

Usage:
    python3 scripts/run_sprint4_truthpass_wrapped_042.py
    python3 scripts/run_sprint4_truthpass_wrapped_042.py --resamples 5000
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

# Import modules
_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")

resolve_dataset = _data_resolver.resolve_dataset
precompute_all = _sprint2_indicators.precompute_all

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_ID = "sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35"
GIT_HASH_FROZEN = "9a606d9"
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "4h"
INITIAL_CAPITAL = 2000.0
KRAKEN_FEE = 0.0026
START_BAR = 50
N_RESAMPLES = 1000
SEED = 42

# Vol-scale wrapper params (best from DDfix P1 for config 042)
VOL_SCALE_ATR_LOOKBACK = 14
VOL_SCALE_PERCENTILE = 25
VOL_SCALE_MIN = 0.25
VOL_SCALE_MAX = 2.0


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
# Vol-Scale Wrapper (reuses logic from run_sprint4_ddfix.py)
# ---------------------------------------------------------------------------

def apply_vol_scaling(
    trades: list[dict],
    atr_by_pair: dict,
    target_percentile: int = VOL_SCALE_PERCENTILE,
) -> list[dict]:
    """Scale position size inversely proportional to ATR(14) at entry.

    size = base_size * (target_atr / current_atr), capped at [0.25, 2.0].
    Wrapped pnl = original_pnl_pct / 100 * scaled_size.

    Returns new trade list with adjusted pnl and size fields.
    """
    # Collect ATR at each trade's entry bar
    atr_at_entry = []
    for t in trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])
        if bar < len(atr_arr) and atr_arr[bar] is not None:
            atr_at_entry.append(atr_arr[bar])

    if not atr_at_entry:
        print("  WARNING: No ATR data found for any trade, returning unchanged")
        return list(trades)

    # Compute reference ATR as the given percentile
    atr_at_entry_sorted = sorted(atr_at_entry)
    idx = max(0, int(len(atr_at_entry_sorted) * target_percentile / 100) - 1)
    target_atr = atr_at_entry_sorted[idx]

    if target_atr <= 0:
        print("  WARNING: target ATR is 0, returning unchanged")
        return list(trades)

    result = []
    n_scaled = 0
    scale_values = []

    for t in trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])

        if bar < len(atr_arr) and atr_arr[bar] is not None and atr_arr[bar] > 0:
            current_atr = atr_arr[bar]
            scale = target_atr / current_atr
            scale = max(VOL_SCALE_MIN, min(VOL_SCALE_MAX, scale))
        else:
            scale = 1.0

        # Compute wrapped pnl from pnl_pct and scaled size
        original_size = t["size"]
        scaled_size = original_size * scale
        wrapped_pnl = t["pnl_pct"] / 100.0 * scaled_size

        new_trade = dict(t)
        new_trade["pnl"] = wrapped_pnl
        new_trade["size"] = scaled_size
        new_trade["_scale"] = scale
        new_trade["_original_pnl"] = t["pnl"]
        new_trade["_original_size"] = original_size
        result.append(new_trade)

        scale_values.append(scale)
        if abs(scale - 1.0) > 0.01:
            n_scaled += 1

    print(f"    Scaled {n_scaled}/{len(trades)} trades "
          f"(scale range: {min(scale_values):.3f} - {max(scale_values):.3f}, "
          f"median: {sorted(scale_values)[len(scale_values)//2]:.3f})")
    print(f"    Target ATR (P{target_percentile}): {target_atr:.6f}")

    return result


# ---------------------------------------------------------------------------
# Metrics computation (from ddfix)
# ---------------------------------------------------------------------------

def _compute_metrics(trades: list[dict], initial_capital: float = INITIAL_CAPITAL) -> dict:
    """Compute PF, DD, P&L, WR from trade list."""
    if not trades:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0, "dd": 0.0,
                "wr": 0.0, "final_equity": initial_capital}

    equity = initial_capital
    peak_equity = initial_capital
    max_dd = 0.0
    wins_sum = 0.0
    losses_sum = 0.0
    n_wins = 0

    for t in trades:
        pnl = t["pnl"]
        equity += pnl

        if pnl > 0:
            wins_sum += pnl
            n_wins += 1
        else:
            losses_sum += abs(pnl)

        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            dd_pct = (peak_equity - equity) / peak_equity * 100
            if dd_pct > max_dd:
                max_dd = dd_pct

    n = len(trades)
    pf = wins_sum / losses_sum if losses_sum > 0 else (99.99 if wins_sum > 0 else 0.0)
    total_pnl = equity - initial_capital
    wr = n_wins / n * 100 if n > 0 else 0.0

    return {
        "trades": n,
        "pf": round(min(pf, 99.99), 4),
        "pnl": round(total_pnl, 2),
        "dd": round(max_dd, 2),
        "wr": round(wr, 2),
        "final_equity": round(equity, 2),
    }


# ---------------------------------------------------------------------------
# Window boundaries (same as original truthpass)
# ---------------------------------------------------------------------------

def _compute_window_boundaries(trade_list: list[dict]) -> dict:
    """Compute bar boundaries for 3-way window split based on trade entry_bars."""
    if not trade_list:
        return {"early": {}, "mid": {}, "late": {}, "max_bars": 0}

    entry_bars = sorted(set(t["entry_bar"] for t in trade_list))
    min_bar = min(entry_bars)
    max_bar = max(entry_bars)

    # Use the same method as original truthpass: bar range divided into thirds
    # We need max_bars from indicators, but for wrapped trades we use the
    # actual bar range of the trades
    all_bars = sorted(set(t["entry_bar"] for t in trade_list) |
                      set(t["exit_bar"] for t in trade_list))
    max_bars = max(all_bars) + 1

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


def _filter_trades_by_window(trades: list[dict], start_bar: int, end_bar: int) -> list[dict]:
    """Filter trades whose entry_bar falls within [start_bar, end_bar)."""
    return [t for t in trades if start_bar <= t["entry_bar"] < end_bar]


# ---------------------------------------------------------------------------
# Test 1: 3-Way Window Split (on wrapped trades)
# ---------------------------------------------------------------------------

def test_window_split(trades: list[dict], windows: dict) -> dict:
    """Divide wrapped trades into 3 windows by entry_bar.
    PASS if >= 2/3 have PF >= 1.0."""
    results = {}

    for window_name in ("early", "mid", "late"):
        w = windows[window_name]
        window_trades = _filter_trades_by_window(
            trades, w["start_bar"], w["end_bar"]
        )
        m = _compute_metrics(window_trades)
        results[window_name] = {
            "start_bar": w["start_bar"],
            "end_bar": w["end_bar"],
            "trades": m["trades"],
            "pf": m["pf"],
            "pnl": m["pnl"],
            "wr": m["wr"],
            "dd": m["dd"],
        }

    windows_profitable = sum(
        1 for wn in ("early", "mid", "late")
        if results[wn]["pf"] >= 1.0 and results[wn]["trades"] > 0
    )
    passed = windows_profitable >= 2

    results["windows_profitable"] = windows_profitable
    results["pass"] = passed
    return results


# ---------------------------------------------------------------------------
# Test 2: Walk-Forward (on wrapped trades)
# ---------------------------------------------------------------------------

def test_walk_forward(trades: list[dict], windows: dict) -> dict:
    """Walk-forward on wrapped trades. PASS if at least 1 split has
    cal PF >= 1.0 AND test PF >= 1.0."""
    max_bars = windows["max_bars"]
    early = windows["early"]
    mid = windows["mid"]
    late = windows["late"]

    # Split A: calibrate on early, test on mid+late
    cal_a_trades = _filter_trades_by_window(trades, early["start_bar"], early["end_bar"])
    test_a_trades = _filter_trades_by_window(trades, mid["start_bar"], max_bars)
    cal_a = _compute_metrics(cal_a_trades)
    test_a = _compute_metrics(test_a_trades)

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
            and test_a["pf"] >= 1.0 and test_a["trades"] > 0
        ),
    }

    # Split B: calibrate on early+mid, test on late
    cal_b_trades = _filter_trades_by_window(trades, early["start_bar"], mid["end_bar"])
    test_b_trades = _filter_trades_by_window(trades, late["start_bar"], max_bars)
    cal_b = _compute_metrics(cal_b_trades)
    test_b = _compute_metrics(test_b_trades)

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
            and test_b["pf"] >= 1.0 and test_b["trades"] > 0
        ),
    }

    passed = split_a["pass"] or split_b["pass"]

    return {
        "cal_early_test_midlate": split_a,
        "cal_earlymid_test_late": split_b,
        "pass": passed,
    }


# ---------------------------------------------------------------------------
# Test 3: Bootstrap Monte Carlo (on wrapped trades)
# ---------------------------------------------------------------------------

def test_bootstrap(trade_list: list[dict], n_resamples: int = N_RESAMPLES) -> dict:
    """Bootstrap resample wrapped trade P&Ls.
    PASS if P5_PF >= 0.85 AND >= 80% profitable."""
    if not trade_list:
        return {
            "n_resamples": n_resamples, "seed": SEED, "n_trades": 0,
            "median_pf": 0.0, "p5_pf": 0.0, "p95_pf": 0.0,
            "median_pnl": 0.0, "p5_pnl": 0.0,
            "pct_profitable": 0.0, "pass": False,
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

    passed = p5_pf >= 0.85 and pct_profitable >= 80.0

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
# Verdict
# ---------------------------------------------------------------------------

def _verdict(window_pass: bool, wf_pass: bool, bootstrap_pass: bool) -> tuple[str, int]:
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
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)


def _write_md_report(result: dict, output_path: Path) -> None:
    r = result
    lines = [
        f"# Sprint 4 Truth-Pass (Vol-Scale Wrapped): {r['config_id']}",
        "",
        f"- **Verdict**: **{r['verdict']}** ({r['tests_passed']}/3 tests passed)",
        f"- **Wrapper**: vol_scale (ATR{VOL_SCALE_ATR_LOOKBACK}, "
        f"pctl={VOL_SCALE_PERCENTILE}, cap=[{VOL_SCALE_MIN}x, {VOL_SCALE_MAX}x])",
        f"- **Dataset**: {r['dataset_id']}",
        f"- **Fee model**: {r['fee_model']}",
        f"- **Git**: {r['git_hash']}",
        f"- **Timestamp**: {r['timestamp']}",
        "",
        "## Wrapper Effect",
        "",
        "| Metric | Raw | Wrapped | Delta |",
        "|--------|-----|---------|-------|",
        f"| Trades | {r['raw_run']['trades']} | {r['wrapped_run']['trades']} | -- |",
        f"| PF | {r['raw_run']['pf']:.2f} | {r['wrapped_run']['pf']:.2f} "
        f"| {r['wrapped_run']['pf'] - r['raw_run']['pf']:+.2f} |",
        f"| P&L | ${r['raw_run']['pnl']:+,.2f} | ${r['wrapped_run']['pnl']:+,.2f} "
        f"| ${r['wrapped_run']['pnl'] - r['raw_run']['pnl']:+,.2f} |",
        f"| WR | {r['raw_run']['wr']:.1f}% | {r['wrapped_run']['wr']:.1f}% "
        f"| {r['wrapped_run']['wr'] - r['raw_run']['wr']:+.1f}pp |",
        f"| DD | {r['raw_run']['dd']:.1f}% | {r['wrapped_run']['dd']:.1f}% "
        f"| {r['wrapped_run']['dd'] - r['raw_run']['dd']:+.1f}pp |",
        "",
        f"- Target ATR (P{VOL_SCALE_PERCENTILE}): {r['vol_scale_info']['target_atr']:.6f}",
        f"- Trades with ATR data: {r['vol_scale_info']['n_with_atr']}/"
        f"{r['vol_scale_info']['n_total']}",
        f"- Scale range: {r['vol_scale_info']['scale_min']:.3f} - "
        f"{r['vol_scale_info']['scale_max']:.3f} "
        f"(median: {r['vol_scale_info']['scale_median']:.3f})",
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
        "Gate: at least 1 split with cal PF >= 1.0 AND test PF >= 1.0",
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
        f"- Gate: P5 PF >= 0.85 AND >= 80% profitable",
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sprint 4 Truth-Pass with Vol-Scale Wrapper for config 042"
    )
    parser.add_argument("--resamples", type=int, default=N_RESAMPLES,
                        help=f"Bootstrap resamples (default: {N_RESAMPLES})")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT),
                        help="Output directory for reports")
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    n_resamples = args.resamples

    print(f"\n{'=' * 72}")
    print(f"  Sprint 4 Truth-Pass (Vol-Scale Wrapped) -- Config 042")
    print(f"{'=' * 72}")
    print(f"  Config:  {CONFIG_ID}")
    print(f"  Wrapper: vol_scale (ATR{VOL_SCALE_ATR_LOOKBACK}, "
          f"pctl={VOL_SCALE_PERCENTILE}, cap=[{VOL_SCALE_MIN}x, {VOL_SCALE_MAX}x])")
    print(f"  Git:     {git_hash}")

    # -------------------------------------------------------------------
    # Step 1: Load existing trade list
    # -------------------------------------------------------------------
    result_path = (
        DEFAULT_OUTPUT / f"{CONFIG_ID}_{GIT_HASH_FROZEN}" / "results.json"
    )
    print(f"\n  Loading trade list from: {result_path.name}")

    if not result_path.exists():
        print(f"  ERROR: Result file not found: {result_path}")
        sys.exit(1)

    with open(result_path) as f:
        raw_result = json.load(f)

    raw_trades = raw_result.get("trades", [])
    if not raw_trades:
        print("  ERROR: No trades in result file")
        sys.exit(1)

    # Sort trades chronologically
    raw_trades = sorted(raw_trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))

    # Compute raw metrics
    raw_metrics = _compute_metrics(raw_trades)
    print(f"  Raw: {raw_metrics['trades']} trades | PF {raw_metrics['pf']:.2f} | "
          f"DD {raw_metrics['dd']:.1f}% | P&L ${raw_metrics['pnl']:+,.2f}")

    # Verify against stored summary
    stored = raw_result.get("summary", {})
    print(f"  (Stored: {stored.get('trades', '?')} trades | "
          f"PF {stored.get('pf', '?')} | DD {stored.get('dd', '?')}% | "
          f"P&L ${stored.get('pnl', 0):+,.2f})")

    # -------------------------------------------------------------------
    # Step 2: Load ATR data
    # -------------------------------------------------------------------
    print(f"\n  Loading ATR data for vol_scale wrapper...")
    t0 = time.time()

    # Collect all unique pairs from trades
    all_pairs = sorted(set(t["pair"] for t in raw_trades))
    print(f"    Unique pairs in trades: {len(all_pairs)}")

    # Load dataset and precompute indicators
    dataset_path = resolve_dataset(DEFAULT_DATASET)
    with open(dataset_path) as f:
        data = json.load(f)

    # Filter to pairs that exist in dataset
    coins = sorted(set(all_pairs) & set(data.keys()))
    print(f"    Pairs in dataset: {len(coins)}")

    indicators = precompute_all(data, coins)
    print(f"    Indicators precomputed in {time.time() - t0:.1f}s")

    # Extract ATR arrays
    atr_by_pair = {}
    for pair in coins:
        ind = indicators.get(pair)
        if ind and "atr" in ind:
            atr_by_pair[pair] = ind["atr"]

    # Also determine max_bars for window boundaries from full indicator set
    # Load universe to get full max_bars
    universe_path = REPO_ROOT / "strategies" / "4h" / "universe_sprint1.json"
    with open(universe_path) as f:
        universe_data = json.load(f)
    universe_coins = universe_data["coins"] if isinstance(universe_data, dict) else universe_data

    # Load full indicators for max_bars determination
    full_indicators = precompute_all(data, universe_coins)
    max_bars = max(ind["n"] for ind in full_indicators.values()) if full_indicators else 0
    print(f"    Max bars (full universe): {max_bars}")

    # -------------------------------------------------------------------
    # Step 3: Apply vol_scale wrapper
    # -------------------------------------------------------------------
    print(f"\n  Applying vol_scale wrapper...")

    # Compute target ATR for info reporting
    atr_at_entry = []
    for t in raw_trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])
        if bar < len(atr_arr) and atr_arr[bar] is not None:
            atr_at_entry.append(atr_arr[bar])

    atr_at_entry_sorted = sorted(atr_at_entry)
    idx = max(0, int(len(atr_at_entry_sorted) * VOL_SCALE_PERCENTILE / 100) - 1)
    target_atr = atr_at_entry_sorted[idx] if atr_at_entry_sorted else 0.0

    wrapped_trades = apply_vol_scaling(raw_trades, atr_by_pair, VOL_SCALE_PERCENTILE)

    # Compute wrapped metrics
    wrapped_metrics = _compute_metrics(wrapped_trades)
    print(f"  Wrapped: {wrapped_metrics['trades']} trades | "
          f"PF {wrapped_metrics['pf']:.2f} | DD {wrapped_metrics['dd']:.1f}% | "
          f"P&L ${wrapped_metrics['pnl']:+,.2f}")

    # Collect scale info
    scale_values = [t.get("_scale", 1.0) for t in wrapped_trades]
    n_with_atr = len(atr_at_entry)

    vol_scale_info = {
        "target_atr": round(target_atr, 8),
        "n_with_atr": n_with_atr,
        "n_total": len(raw_trades),
        "scale_min": round(min(scale_values), 4),
        "scale_max": round(max(scale_values), 4),
        "scale_median": round(sorted(scale_values)[len(scale_values) // 2], 4),
        "atr_lookback": VOL_SCALE_ATR_LOOKBACK,
        "target_percentile": VOL_SCALE_PERCENTILE,
        "scale_cap_min": VOL_SCALE_MIN,
        "scale_cap_max": VOL_SCALE_MAX,
    }

    # -------------------------------------------------------------------
    # Step 4: Compute window boundaries (use full universe max_bars)
    # -------------------------------------------------------------------
    usable_range = max_bars - START_BAR
    third = usable_range // 3

    windows = {
        "early": {"start_bar": START_BAR, "end_bar": START_BAR + third},
        "mid": {"start_bar": START_BAR + third, "end_bar": START_BAR + 2 * third},
        "late": {"start_bar": START_BAR + 2 * third, "end_bar": max_bars},
        "max_bars": max_bars,
    }
    print(f"\n  Window boundaries: "
          f"early={windows['early']['start_bar']}-{windows['early']['end_bar']}, "
          f"mid={windows['mid']['start_bar']}-{windows['mid']['end_bar']}, "
          f"late={windows['late']['start_bar']}-{windows['late']['end_bar']}")

    # -------------------------------------------------------------------
    # Test 1: 3-Way Window Split
    # -------------------------------------------------------------------
    print(f"\n  Test 1: 3-Way Window Split (on wrapped trades)...")
    t1_start = time.time()
    ws_result = test_window_split(wrapped_trades, windows)
    ws_mark = "PASS" if ws_result["pass"] else "FAIL"
    print(f"    [{ws_mark}] {ws_result['windows_profitable']}/3 windows profitable "
          f"({time.time() - t1_start:.2f}s)")
    for wname in ("early", "mid", "late"):
        w = ws_result[wname]
        pf_mark = " *" if w["pf"] >= 1.0 and w["trades"] > 0 else ""
        print(f"      {wname}: {w['trades']}tr PF={w['pf']:.2f}{pf_mark} "
              f"P&L=${w['pnl']:+,.2f}")

    # -------------------------------------------------------------------
    # Test 2: Walk-Forward
    # -------------------------------------------------------------------
    print(f"\n  Test 2: Walk-Forward (on wrapped trades)...")
    t2_start = time.time()
    wf_result = test_walk_forward(wrapped_trades, windows)
    wf_mark = "PASS" if wf_result["pass"] else "FAIL"
    print(f"    [{wf_mark}] ({time.time() - t2_start:.2f}s)")
    for sn, sl in [("cal_early_test_midlate", "Early->Mid+Late"),
                   ("cal_earlymid_test_late", "Early+Mid->Late")]:
        s = wf_result[sn]
        s_mark = "PASS" if s["pass"] else "FAIL"
        print(f"      [{s_mark}] {sl}: "
              f"cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
              f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f}")

    # -------------------------------------------------------------------
    # Test 3: Bootstrap Monte Carlo
    # -------------------------------------------------------------------
    print(f"\n  Test 3: Bootstrap Monte Carlo ({n_resamples} resamples, "
          f"on wrapped trades)...")
    t3_start = time.time()
    bs_result = test_bootstrap(wrapped_trades, n_resamples=n_resamples)
    bs_mark = "PASS" if bs_result["pass"] else "FAIL"
    print(f"    [{bs_mark}] P5_PF={bs_result['p5_pf']:.2f} "
          f"median_PF={bs_result['median_pf']:.2f} "
          f"%profitable={bs_result['pct_profitable']:.1f}% "
          f"({time.time() - t3_start:.2f}s)")

    # -------------------------------------------------------------------
    # Verdict
    # -------------------------------------------------------------------
    verdict, tests_passed = _verdict(
        ws_result["pass"], wf_result["pass"], bs_result["pass"]
    )
    print(f"\n  >>> VERDICT: {verdict} ({tests_passed}/3 tests passed)")

    # -------------------------------------------------------------------
    # Build result dict
    # -------------------------------------------------------------------
    result = {
        "config_id": CONFIG_ID,
        "experiment": "sprint4_truthpass_vol_scale_wrapped",
        "dataset_id": DEFAULT_DATASET,
        "universe_id": "universe_sprint1",
        "fee_model": "kraken_spot_26bps",
        "git_hash": git_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wrapper": {
            "name": "vol_scale",
            "params": {
                "atr_lookback": VOL_SCALE_ATR_LOOKBACK,
                "target_percentile": VOL_SCALE_PERCENTILE,
                "scale_cap": [VOL_SCALE_MIN, VOL_SCALE_MAX],
            },
        },
        "raw_run": {
            "trades": raw_metrics["trades"],
            "pf": raw_metrics["pf"],
            "pnl": raw_metrics["pnl"],
            "wr": raw_metrics["wr"],
            "dd": raw_metrics["dd"],
        },
        "wrapped_run": {
            "trades": wrapped_metrics["trades"],
            "pf": wrapped_metrics["pf"],
            "pnl": wrapped_metrics["pnl"],
            "wr": wrapped_metrics["wr"],
            "dd": wrapped_metrics["dd"],
        },
        "vol_scale_info": vol_scale_info,
        "window_boundaries": {
            "early": windows["early"],
            "mid": windows["mid"],
            "late": windows["late"],
            "max_bars": max_bars,
        },
        "window_split": ws_result,
        "walk_forward": wf_result,
        "bootstrap": bs_result,
        "verdict": verdict,
        "tests_passed": tests_passed,
    }

    # -------------------------------------------------------------------
    # Write reports
    # -------------------------------------------------------------------
    json_path = output_dir / "sprint4_truthpass_wrapped_042.json"
    md_path = output_dir / "sprint4_truthpass_wrapped_042.md"

    _write_json_report(result, json_path)
    _write_md_report(result, md_path)

    print(f"\n  Reports written:")
    print(f"    JSON: {json_path}")
    print(f"    MD:   {md_path}")
    print(f"\n{'=' * 72}\n")


if __name__ == "__main__":
    main()
