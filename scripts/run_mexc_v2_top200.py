#!/usr/bin/env python3
"""
MEXC v2 Top-200 Experiments: Volume-filtered universe + stricter entry params.

Two experiments on the same v2 data (439 coins):
  1. MEXC-v2-top200: top 200 coins by median volume, ≥2160 bars
  2. MEXC-v2-top200 + stricter entries: vol_mult=3.5/4.0, rsi_max=35

All runs use fair slicing end_bar=721 for apples-to-apples comparison.

Usage:
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_top200.py
"""
from __future__ import annotations

import sys
import json
import time
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

DATA_ROOT = Path.home() / "CryptogemData"
V2_DATA_FILE = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h" / "candle_cache_4h_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
KRAKEN_FEE = 0.0026
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
END_BAR = 721  # Fair slicing — matches Kraken comparison window

MIN_BARS_TOP200 = 2160  # ≥360 days — quality filter
TOP_N = 200  # Top 200 by volume

N_RESAMPLES = 1000
SEED = 42

# Experiment configs: (label, vol_mult, rsi_max)
EXPERIMENTS = [
    ("baseline_top200",    3.0, 40, "Baseline 041 on top-200"),
    ("strict_vol35",       3.5, 40, "Stricter vol (3.5x) on top-200"),
    ("strict_vol40",       4.0, 40, "Stricter vol (4.0x) on top-200"),
    ("strict_vol35_rsi35", 3.5, 35, "Strict vol (3.5x) + RSI 35 on top-200"),
]

# Kraken reference
KRAKEN_REF = {"pf": 1.4058, "trades": 216, "dd": 36.37, "pnl": 3349.79, "wr": 54.63}


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Step 1: Load data + build top-200 universe
# ===========================================================================

def load_and_filter_top200():
    """Load v2 data, filter to top 200 by median volume with ≥2160 bars."""
    print("\n" + "=" * 70)
    print("  STEP 1: Load Data + Build Top-200 Universe")
    print("=" * 70)

    if not V2_DATA_FILE.exists():
        print(f"  ERROR: V2 data not found: {V2_DATA_FILE}")
        sys.exit(1)

    print("  Loading v2 data...")
    t0 = time.time()
    with open(V2_DATA_FILE) as f:
        raw_data = json.load(f)

    coins_in_data = [k for k in raw_data if not k.startswith("_")]
    print(f"  Total coins in v2 data: {len(coins_in_data)}")

    # Filter by min bars
    eligible = []
    for pair in coins_in_data:
        candles = raw_data[pair]
        n_bars = len(candles)
        if n_bars < MIN_BARS_TOP200:
            continue
        # Compute median volume over last 720 bars (≈120 days)
        vol_window = min(720, n_bars)
        volumes = [c.get("volume", 0) or 0 for c in candles[-vol_window:]]
        med_vol = median(volumes) if volumes else 0
        eligible.append((pair, n_bars, med_vol))

    print(f"  Eligible (≥{MIN_BARS_TOP200} bars): {len(eligible)} coins")

    # Rank by median volume, take top N
    eligible.sort(key=lambda x: x[2], reverse=True)
    top200 = eligible[:TOP_N]
    print(f"  Top-{TOP_N} by median volume: {len(top200)} coins")

    if top200:
        print(f"  Volume range: {top200[0][2]:,.0f} (#{1}) → {top200[-1][2]:,.0f} (#{len(top200)})")
        # Show volume cutoff
        if len(eligible) > TOP_N:
            print(f"  Cutoff: median_vol ≥ {top200[-1][2]:,.0f}")

    coins = sorted([t[0] for t in top200])
    data = {c: raw_data[c] for c in coins}
    bars_counts = [len(data[c]) for c in coins]

    dt = time.time() - t0
    print(f"  Loaded {len(coins)} coins in {dt:.1f}s")
    print(f"  Bars range: {min(bars_counts)} - {max(bars_counts)}, median: {int(median(bars_counts))}")

    # Also compute the full v2 (439-coin) reference universe for comparison
    all_coins_v2 = sorted([pair for pair in coins_in_data
                           if len(raw_data[pair]) >= 720])
    print(f"  Full v2 universe (≥720 bars): {len(all_coins_v2)} coins")

    return data, coins, bars_counts, raw_data, all_coins_v2


# ===========================================================================
# Step 2: Precompute indicators (ONCE for top-200 coins)
# ===========================================================================

def precompute(data, coins):
    """Precompute all indicators for the top-200 universe."""
    print("\n" + "=" * 70)
    print("  STEP 2: Precompute Indicators")
    print("=" * 70)

    import importlib
    _sprint2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")

    t0 = time.time()
    indicators = _sprint2_ind.precompute_all(data, coins)
    market_context = _sprint2_ctx.precompute_sprint2_context(data, coins)
    dt = time.time() - t0
    print(f"  Precomputed in {dt:.1f}s for {len(coins)} coins")
    return indicators, market_context


# ===========================================================================
# Step 3: Run experiments
# ===========================================================================

def _result_to_dict(r) -> dict:
    """Convert BacktestResult dataclass to dict."""
    return {
        "summary": {
            "trades": r.trades,
            "pf": r.pf,
            "pnl": r.pnl,
            "wr": r.wr,
            "dd_pct": r.dd,
            "final_equity": r.final_equity,
        },
        "trades": r.trade_list,
        "exit_classes": r.exit_classes,
    }


def _find_config_041():
    """Find config 041 from sprint4 hypotheses."""
    import importlib
    _sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")
    all_configs = _sprint4_hyp.build_sweep_configs()
    for cfg in all_configs:
        if cfg["hypothesis_id"] == CONFIG_041_HYP_ID:
            return cfg
    raise ValueError(f"Config {CONFIG_041_HYP_ID} not found in hypotheses!")


def run_experiments(data, coins, indicators, market_context):
    """Run all 4 experiments on the top-200 universe."""
    print("\n" + "=" * 70)
    print("  STEP 3: Run Experiments")
    print("=" * 70)

    import importlib
    _sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
    run_backtest = _sprint3_engine.run_backtest

    cfg = _find_config_041()
    signal_fn = cfg["signal_fn"]
    base_params = dict(cfg["params"])

    all_results = {}

    for label, vol_mult, rsi_max, desc in EXPERIMENTS:
        print(f"\n  --- {desc} (vol={vol_mult}, rsi_max={rsi_max}) ---")

        # Prepare params with overrides
        params = dict(base_params)
        params["vol_mult"] = vol_mult
        params["rsi_max"] = rsi_max
        params["__market__"] = market_context
        for c in coins:
            indicators[c]["__coin__"] = c

        t0 = time.time()
        r_raw = run_backtest(
            data, coins, signal_fn, params, indicators,
            fee=MEXC_FEE, exit_mode="dc",
            start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
            cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
            end_bar=END_BAR,
        )
        r = _result_to_dict(r_raw)
        dt = time.time() - t0

        s = r["summary"]
        print(f"  Trades: {s['trades']}, PF: {s['pf']:.4f}, "
              f"P&L: ${s['pnl']:.2f}, DD: {s['dd_pct']:.1f}%, "
              f"WR: {s['wr']:.1f}%, Time: {dt:.1f}s")
        all_results[label] = {
            "result": r,
            "vol_mult": vol_mult,
            "rsi_max": rsi_max,
            "desc": desc,
        }

    return all_results


# ===========================================================================
# Step 4: Analysis
# ===========================================================================

def _window_split(result, max_bars=END_BAR):
    """3-way chronological window split."""
    trades = result.get("trades", [])
    if not trades:
        return {"windows": {}, "windows_profitable": 0, "pass": False}
    span = max_bars - START_BAR
    w_size = span // 3
    boundaries = [
        (START_BAR, START_BAR + w_size),
        (START_BAR + w_size, START_BAR + 2 * w_size),
        (START_BAR + 2 * w_size, max_bars),
    ]
    names = ["early", "mid", "late"]
    windows = {}
    n_profitable = 0
    for name, (start, end) in zip(names, boundaries):
        w_trades = [t for t in trades if start <= t.get("entry_bar", 0) < end]
        if not w_trades:
            windows[name] = {"trades": 0, "pf": 0, "pnl": 0, "wr": 0,
                             "start_bar": start, "end_bar": end}
            continue
        pnls = [t["pnl"] for t in w_trades]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)
        pnl_sum = sum(pnls)
        wr = 100 * sum(1 for p in pnls if p > 0) / len(pnls)
        windows[name] = {
            "trades": len(w_trades), "pf": round(pf, 4), "pnl": round(pnl_sum, 2),
            "wr": round(wr, 2), "start_bar": start, "end_bar": end,
        }
        if pnl_sum > 0:
            n_profitable += 1
    return {"windows": windows, "windows_profitable": n_profitable, "pass": n_profitable >= 2}


def _exit_attribution(result):
    """Exit reason breakdown."""
    trades = result.get("trades", [])
    if not trades:
        return {}
    CLASS_A = {"RSI RECOVERY", "DC TARGET", "BB TARGET", "PROFIT TARGET"}
    by_reason = {}
    for t in trades:
        reason = t.get("reason", "UNKNOWN")
        if reason not in by_reason:
            by_reason[reason] = {"class": "A" if reason in CLASS_A else "B",
                                 "count": 0, "pnl": 0, "wins": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_reason[reason]["wins"] += 1
    for r in by_reason.values():
        r["wr"] = round(100 * r["wins"] / r["count"], 1) if r["count"] > 0 else 0
        r["pnl"] = round(r["pnl"], 2)
        del r["wins"]
    return by_reason


def _bootstrap(result, n_resamples=N_RESAMPLES, seed=SEED):
    """Bootstrap resampling for PF confidence."""
    trades = result.get("trades", [])
    if len(trades) < 10:
        return {"pass": False, "n_trades": len(trades), "note": "too few trades"}
    rng = np.random.default_rng(seed)
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    pfs, final_pnls = [], []
    for _ in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        gp = np.sum(sample[sample > 0])
        gl = np.abs(np.sum(sample[sample < 0]))
        pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)
        pfs.append(pf)
        final_pnls.append(np.sum(sample))
    pfs = np.array(pfs)
    final_pnls = np.array(final_pnls)
    return {
        "n_resamples": n_resamples, "n_trades": n,
        "median_pf": round(float(np.median(pfs)), 4),
        "p5_pf": round(float(np.percentile(pfs, 5)), 4),
        "p95_pf": round(float(np.percentile(pfs, 95)), 4),
        "median_pnl": round(float(np.median(final_pnls)), 2),
        "p5_pnl": round(float(np.percentile(final_pnls, 5)), 2),
        "pct_profitable": round(float(np.mean(final_pnls > 0) * 100), 1),
        "pass": bool(np.percentile(pfs, 5) >= 0.85 and np.mean(final_pnls > 0) >= 0.80),
    }


def analyze_all(all_results):
    """Run full analysis on each experiment."""
    print("\n" + "=" * 70)
    print("  STEP 4: Analysis")
    print("=" * 70)

    analyzed = {}
    for label, entry in all_results.items():
        r = entry["result"]
        print(f"\n  --- {entry['desc']} ---")

        ws = _window_split(r)
        ea = _exit_attribution(r)
        bs = _bootstrap(r)

        print(f"  Window: {ws['windows_profitable']}/3 {'PASS' if ws['pass'] else 'FAIL'}")
        for reason, stats in sorted(ea.items(), key=lambda x: x[1]["pnl"], reverse=True):
            print(f"    {reason}: {stats['count']}x, ${stats['pnl']:+,.0f}, WR={stats['wr']:.0f}%")
        print(f"  Bootstrap: P5_PF={bs.get('p5_pf', 0):.2f}, "
              f"{bs.get('pct_profitable', 0):.1f}% profitable {'PASS' if bs.get('pass') else 'FAIL'}")

        analyzed[label] = {
            **entry,
            "window_split": ws,
            "exit_attribution": ea,
            "bootstrap": bs,
        }

    return analyzed


# ===========================================================================
# Step 5: Report
# ===========================================================================

def write_reports(analyzed, n_coins, bars_counts):
    """Write JSON + MD reports."""
    print("\n" + "=" * 70)
    print("  STEP 5: Reports")
    print("=" * 70)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    git = _git_hash()
    n_days = (END_BAR - START_BAR) * 4 / 24

    # Build JSON report
    report = {
        "experiment": "mexc_v2_top200",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, ≥{MIN_BARS_TOP200} bars",
            "n_coins": n_coins,
            "bars_min": min(bars_counts),
            "bars_max": max(bars_counts),
            "bars_median": int(median(bars_counts)),
        },
        "end_bar": END_BAR,
        "fee": MEXC_FEE,
        "fee_model": "mexc_spot_10bps",
        "configs": {},
        "kraken_reference": KRAKEN_REF,
        "v2_full_reference": {
            "n_coins": 439, "pf": 0.97, "trades": 199, "dd": 47.7,
            "note": "Full v2 pool baseline from mexc_041_portability_002"
        },
    }

    for label, entry in analyzed.items():
        s = entry["result"]["summary"]
        report["configs"][label] = {
            "vol_mult": entry["vol_mult"],
            "rsi_max": entry["rsi_max"],
            "description": entry["desc"],
            "trades": s["trades"],
            "pf": round(s["pf"], 4),
            "pnl": round(s["pnl"], 2),
            "wr": round(s["wr"], 2),
            "dd": round(s["dd_pct"], 2),
            "ev_per_trade": round(s["pnl"] / max(1, s["trades"]), 2),
            "trades_per_day": round(s["trades"] / n_days, 2),
            "window_split": entry["window_split"],
            "exit_attribution": entry["exit_attribution"],
            "bootstrap": entry["bootstrap"],
        }

    json_path = REPORT_DIR / "mexc_v2_top200_003.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  JSON: {json_path}")

    # Build MD report
    md = _build_md(report, analyzed, n_coins)
    md_path = REPORT_DIR / "mexc_v2_top200_003.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  MD: {md_path}")

    return json_path


def _build_md(report, analyzed, n_coins):
    git = report["git_hash"]
    lines = [
        "# MEXC v2 Top-200 Experiments — Config 041",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Dataset**: `ohlcv_4h_mexc_spot_usdt_v2`",
        f"**Universe**: Top {TOP_N} by median volume, ≥{MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Fair slicing**: end_bar={END_BAR}",
        f"**Fee**: MEXC 10bps",
        "",
        "## Comparison Matrix",
        "",
        "| Config | vol | rsi | Trades | PF | P&L | WR | DD | EV/t | Win/3 | Boot%Prof |",
        "|--------|----:|----:|-------:|---:|----:|---:|---:|-----:|------:|----------:|",
    ]

    for label, entry in analyzed.items():
        s = entry["result"]["summary"]
        ws = entry["window_split"]
        bs = entry["bootstrap"]
        n_days = (END_BAR - START_BAR) * 4 / 24
        ev = s["pnl"] / max(1, s["trades"])
        lines.append(
            f"| {entry['desc']} | {entry['vol_mult']} | {entry['rsi_max']} "
            f"| {s['trades']} | {s['pf']:.2f} | ${s['pnl']:+,.0f} "
            f"| {s['wr']:.1f}% | {s['dd_pct']:.1f}% | ${ev:.2f} "
            f"| {ws['windows_profitable']}/3 "
            f"| {bs.get('pct_profitable', 0):.1f}% |"
        )

    # Reference rows
    kr = KRAKEN_REF
    lines.append(
        f"| **Kraken ref (487 coins)** | 3.0 | 40 "
        f"| {kr['trades']} | {kr['pf']:.2f} | ${kr['pnl']:+,.0f} "
        f"| {kr['wr']:.1f}% | {kr['dd']:.1f}% | ${kr['pnl']/kr['trades']:.2f} "
        f"| — | — |"
    )
    lines.append(
        f"| **MEXC v2 full (439 coins)** | 3.0 | 40 "
        f"| 199 | 0.97 | $-147 "
        f"| 53.3% | 47.7% | $-0.74 "
        f"| 1/3 | 43.1% |"
    )
    lines.append("")

    # Per-config detail
    for label, entry in analyzed.items():
        s = entry["result"]["summary"]
        lines.append(f"## {entry['desc']}")
        lines.append("")

        # Exit attribution
        ea = entry["exit_attribution"]
        if ea:
            lines.append("### Exit Attribution")
            lines.append("")
            lines.append("| Exit | Class | Count | P&L | WR |")
            lines.append("|------|-------|------:|----:|---:|")
            for reason in sorted(ea.keys(), key=lambda r: ea[r]["pnl"], reverse=True):
                st = ea[reason]
                lines.append(f"| {reason} | {st['class']} | {st['count']} | ${st['pnl']:+,.0f} | {st['wr']:.0f}% |")
            lines.append("")

        # Window split
        ws = entry["window_split"]
        windows = ws.get("windows", {})
        if windows:
            lines.append("### Window Split")
            lines.append("")
            lines.append("| Window | Trades | PF | P&L |")
            lines.append("|--------|-------:|---:|----:|")
            for name in ["early", "mid", "late"]:
                w = windows.get(name, {})
                lines.append(f"| {name.capitalize()} | {w.get('trades', 0)} | {w.get('pf', 0):.2f} | ${w.get('pnl', 0):+,.0f} |")
            lines.append(f"\n**{ws['windows_profitable']}/3 {'PASS' if ws['pass'] else 'FAIL'}**")
            lines.append("")

        # Bootstrap
        bs = entry["bootstrap"]
        if bs.get("n_trades", 0) >= 10:
            lines.append("### Bootstrap")
            lines.append("")
            lines.append(f"- P5 PF: {bs.get('p5_pf', 0):.2f}")
            lines.append(f"- Median PF: {bs.get('median_pf', 0):.2f}")
            lines.append(f"- % Profitable: {bs.get('pct_profitable', 0):.1f}%")
            lines.append(f"- **{'PASS' if bs.get('pass') else 'FAIL'}**")
            lines.append("")

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    print("\n" + "=" * 70)
    print("  MEXC v2 TOP-200 EXPERIMENTS")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 1: Load data + filter top-200
    data, coins, bars_counts, raw_data, all_v2_coins = load_and_filter_top200()
    n_coins = len(coins)

    # Step 2: Precompute indicators
    indicators, market_context = precompute(data, coins)

    # Step 3: Run all 4 experiments
    all_results = run_experiments(data, coins, indicators, market_context)

    # Step 4: Analyze
    analyzed = analyze_all(all_results)

    # Step 5: Reports
    json_path = write_reports(analyzed, n_coins, bars_counts)

    # Summary
    elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print("  COMPLETE")
    print("=" * 70)
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Universe: top-{TOP_N} ({n_coins} coins)")
    print(f"  Configs tested: {len(EXPERIMENTS)}")
    for label, entry in analyzed.items():
        s = entry["result"]["summary"]
        print(f"    {entry['desc']}: PF={s['pf']:.4f}, {s['trades']} trades, DD={s['dd_pct']:.1f}%")
    print(f"  Reports: {json_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
