#!/usr/bin/env python3
"""
MEXC v2 Top-200 Truth-Pass + Fixed-Notional P&L.

Runs the canonical 3-test truth-pass battery on MEXC top-200 full-range:
  1. 3-Way Window Split (≥2/3 windows PF≥1.0)
  2. Walk-Forward (cal PF≥1.0, test PF≥0.9)
  3. Bootstrap Monte Carlo (P5 PF≥0.85, ≥60% profitable)

Additional:
  - Fixed-notional run ($2000/trade always) alongside equity-proportional
  - Determinism check (rerun → exact match)
  - Both configs: vol 3.5x RSI35 (primary) and vol 4.0x RSI40 (secondary)

Usage:
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_top200_truthpass.py
"""
from __future__ import annotations

import sys
import json
import time
import copy
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median

import numpy as np

# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

DATA_ROOT = Path.home() / "CryptogemData"
V2_DATA_FILE = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h" / "candle_cache_4h_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

MIN_BARS_TOP200 = 2160
TOP_N = 200
N_RESAMPLES = 1000
SEED = 42

CONFIGS = [
    ("vol35_rsi35", 3.5, 35, "Vol 3.5x RSI 35 (primary)"),
    ("vol40_rsi40", 4.0, 40, "Vol 4.0x RSI 40 (secondary)"),
]


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _result_to_dict(r) -> dict:
    return {
        "summary": {
            "trades": r.trades, "pf": r.pf, "pnl": r.pnl,
            "wr": r.wr, "dd_pct": r.dd, "final_equity": r.final_equity,
        },
        "trades": r.trade_list,
        "exit_classes": r.exit_classes,
    }


# ===========================================================================
# Data loading
# ===========================================================================

def load_top200():
    """Load MEXC v2 data, filter to top-200 by median volume with ≥2160 bars."""
    print("\n  Loading top-200 universe...")
    with open(V2_DATA_FILE) as f:
        raw_data = json.load(f)

    coins_all = [k for k in raw_data if not k.startswith("_")]
    eligible = []
    for pair in coins_all:
        candles = raw_data[pair]
        n = len(candles)
        if n < MIN_BARS_TOP200:
            continue
        vols = [c.get("volume", 0) or 0 for c in candles[-720:]]
        eligible.append((pair, n, median(vols)))

    eligible.sort(key=lambda x: x[2], reverse=True)
    top200 = eligible[:TOP_N]
    coins = sorted([t[0] for t in top200])
    data = {c: raw_data[c] for c in coins}
    bars_counts = [len(data[c]) for c in coins]

    print(f"  Coins: {len(coins)}, Bars: {min(bars_counts)}-{max(bars_counts)}, "
          f"median: {int(median(bars_counts))}")
    return data, coins, bars_counts


# ===========================================================================
# Fixed-notional backtest wrapper
# ===========================================================================

MAX_RETURN_RATIO = 1.0  # Cap per-trade return at ±100% of notional

def run_fixed_notional(data, coins, signal_fn, params, indicators,
                       fee, start_bar, end_bar=None):
    """Run backtest but normalize trade P&Ls to fixed $2000 notional.

    The engine uses equity-proportional sizing, so we post-process:
    each trade's P&L is rescaled as if size_usd was always $2000.
    Return ratios > MAX_RETURN_RATIO are capped (data anomaly filter).
    """
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")

    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=fee, exit_mode="dc",
        start_bar=start_bar, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=end_bar,
    )

    # Post-process: rescale each trade to $2000 notional
    fixed_trades = []
    n_capped = 0
    for t in r.trade_list:
        size = t.get("size", t.get("size_usd", INITIAL_CAPITAL))
        if size <= 0:
            size = INITIAL_CAPITAL
        # Return ratio = pnl / size_usd. Apply to fixed notional.
        ret_ratio = t["pnl"] / size
        # Cap extreme returns (data anomalies like PUMP/USD 8T% spike)
        if abs(ret_ratio) > MAX_RETURN_RATIO:
            ret_ratio = MAX_RETURN_RATIO if ret_ratio > 0 else -MAX_RETURN_RATIO
            n_capped += 1
        fixed_pnl = ret_ratio * INITIAL_CAPITAL
        ft = dict(t)
        ft["pnl"] = round(fixed_pnl, 2)
        ft["size_usd"] = INITIAL_CAPITAL
        ft["_orig_pnl"] = round(t["pnl"], 2)
        ft["_orig_size"] = round(size, 2)
        ft["_capped"] = abs(t["pnl"] / size) > MAX_RETURN_RATIO
        fixed_trades.append(ft)

    # Recompute summary metrics
    total_pnl = sum(t["pnl"] for t in fixed_trades)
    wins = [t["pnl"] for t in fixed_trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in fixed_trades if t["pnl"] <= 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else (99.99 if gp > 0 else 0)
    wr = 100 * len(wins) / len(fixed_trades) if fixed_trades else 0

    # DD: simulate equity curve with fixed notional
    equity = INITIAL_CAPITAL
    peak = equity
    max_dd = 0
    for t in fixed_trades:
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd:
            max_dd = dd_pct

    return {
        "trades": len(fixed_trades),
        "pf": round(min(pf, 99.99), 4),
        "pnl": round(total_pnl, 2),
        "wr": round(wr, 2),
        "dd_pct": round(max_dd, 2),
        "final_equity": round(equity, 2),
        "n_capped": n_capped,
        "trade_list": fixed_trades,
    }


# ===========================================================================
# Truth-pass tests (same logic as sprint4 truth-pass)
# ===========================================================================

def _compute_windows(max_bars):
    usable = max_bars - START_BAR
    third = usable // 3
    return {
        "early": {"start": START_BAR, "end": START_BAR + third},
        "mid":   {"start": START_BAR + third, "end": START_BAR + 2 * third},
        "late":  {"start": START_BAR + 2 * third, "end": max_bars},
        "max_bars": max_bars,
    }


def _run_bt_fixed(data, coins, signal_fn, params, indicators, fee,
                  start_bar=START_BAR, end_bar=None):
    """Single fixed-notional backtest for truth-pass sub-windows."""
    return run_fixed_notional(data, coins, signal_fn, params, indicators,
                              fee=fee, start_bar=start_bar, end_bar=end_bar)


def test_window_split(data, coins, signal_fn, params, indicators, fee, windows):
    """3-Way window split. PASS if ≥2/3 windows PF≥1.0."""
    results = {}
    n_profitable = 0
    for name in ("early", "mid", "late"):
        w = windows[name]
        bt = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=w["start"], end_bar=w["end"])
        results[name] = {
            "start": w["start"], "end": w["end"],
            "trades": bt["trades"], "pf": bt["pf"],
            "pnl": bt["pnl"], "wr": bt["wr"], "dd": bt["dd_pct"],
        }
        if bt["pf"] >= 1.0 and bt["trades"] > 0:
            n_profitable += 1
    results["n_profitable"] = n_profitable
    results["pass"] = n_profitable >= 2
    return results


def test_walk_forward(data, coins, signal_fn, params, indicators, fee, windows):
    """Walk-forward: 2 splits. PASS if either split passes."""
    max_bars = windows["max_bars"]
    early, mid, late = windows["early"], windows["mid"], windows["late"]

    # Split A: cal=early, test=mid+late
    cal_a = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                          fee=fee, start_bar=early["start"], end_bar=early["end"])
    test_a = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=mid["start"], end_bar=max_bars)
    split_a_pass = (cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
                    and test_a["pf"] >= 0.9 and test_a["trades"] > 0)

    # Split B: cal=early+mid, test=late
    cal_b = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                          fee=fee, start_bar=early["start"], end_bar=mid["end"])
    test_b = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=late["start"], end_bar=max_bars)
    split_b_pass = (cal_b["pf"] >= 1.0 and cal_b["trades"] > 0
                    and test_b["pf"] >= 0.9 and test_b["trades"] > 0)

    return {
        "split_a": {
            "cal": {"bars": f"{early['start']}-{early['end']}", "trades": cal_a["trades"], "pf": cal_a["pf"], "pnl": cal_a["pnl"]},
            "test": {"bars": f"{mid['start']}-{max_bars}", "trades": test_a["trades"], "pf": test_a["pf"], "pnl": test_a["pnl"]},
            "pass": split_a_pass,
        },
        "split_b": {
            "cal": {"bars": f"{early['start']}-{mid['end']}", "trades": cal_b["trades"], "pf": cal_b["pf"], "pnl": cal_b["pnl"]},
            "test": {"bars": f"{late['start']}-{max_bars}", "trades": test_b["trades"], "pf": test_b["pf"], "pnl": test_b["pnl"]},
            "pass": split_b_pass,
        },
        "pass": split_a_pass or split_b_pass,
    }


def test_bootstrap(trade_list, n_resamples=N_RESAMPLES):
    """Bootstrap. PASS if P5 PF≥0.85 AND ≥60% profitable."""
    if len(trade_list) < 10:
        return {"pass": False, "n_trades": len(trade_list)}
    rng = np.random.default_rng(SEED)
    pnls = np.array([t["pnl"] for t in trade_list])
    n = len(pnls)
    pfs, final_pnls = [], []
    for _ in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        gp = np.sum(sample[sample > 0])
        gl = np.abs(np.sum(sample[sample < 0]))
        pf = gp / gl if gl > 0 else (99.99 if gp > 0 else 0)
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
        "pass": bool(np.percentile(pfs, 5) >= 0.85 and np.mean(final_pnls > 0) >= 0.60),
    }


def _verdict(ws_pass, wf_pass, bs_pass):
    n = sum([ws_pass, wf_pass, bs_pass])
    if n == 3:
        return "VERIFIED", 3
    elif n == 2:
        return "CONDITIONAL", 2
    else:
        return "FAILED", n


# ===========================================================================
# Determinism check
# ===========================================================================

def check_determinism(data, coins, signal_fn, params, indicators, fee, max_bars):
    """Rerun full-range and verify exact match."""
    r1 = run_fixed_notional(data, coins, signal_fn, params, indicators,
                            fee=fee, start_bar=START_BAR)
    r2 = run_fixed_notional(data, coins, signal_fn, params, indicators,
                            fee=fee, start_bar=START_BAR)
    match = (r1["trades"] == r2["trades"]
             and abs(r1["pf"] - r2["pf"]) < 1e-6
             and abs(r1["pnl"] - r2["pnl"]) < 0.01)
    return {
        "pass": match,
        "run1": {"trades": r1["trades"], "pf": r1["pf"], "pnl": r1["pnl"]},
        "run2": {"trades": r2["trades"], "pf": r2["pf"], "pnl": r2["pnl"]},
    }


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    print("\n" + "=" * 70)
    print("  MEXC TOP-200 TRUTH-PASS + FIXED-NOTIONAL")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Load data
    data, coins, bars_counts = load_top200()
    n_coins = len(coins)
    max_bar = max(bars_counts)

    # Precompute
    import importlib
    _s2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _s2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
    _hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = _s2_ind.precompute_all(data, coins)
    market_context = _s2_ctx.precompute_sprint2_context(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s")

    # Find config 041 base
    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])

    windows = _compute_windows(max_bar)
    n_days = (max_bar - START_BAR) * 4 / 24
    git = _git_hash()

    print(f"  Max bars: {max_bar}, Days: ~{n_days:.0f}")
    print(f"  Windows: early={windows['early']['start']}-{windows['early']['end']}, "
          f"mid={windows['mid']['start']}-{windows['mid']['end']}, "
          f"late={windows['late']['start']}-{windows['late']['end']}")

    all_results = {}

    for label, vol_mult, rsi_max, desc in CONFIGS:
        print(f"\n{'='*70}")
        print(f"  {desc}")
        print(f"{'='*70}")

        params = dict(base_params)
        params["vol_mult"] = vol_mult
        params["rsi_max"] = rsi_max
        params["__market__"] = market_context
        for c in coins:
            indicators[c]["__coin__"] = c

        # --- Full-range fixed-notional ---
        print(f"\n  [1] Full-range fixed-notional backtest...")
        t0 = time.time()
        full = _run_bt_fixed(data, coins, signal_fn, params, indicators,
                             fee=MEXC_FEE)
        capped_note = f" ({full['n_capped']} capped)" if full.get('n_capped', 0) else ""
        print(f"      Trades: {full['trades']}, PF: {full['pf']:.4f}, "
              f"P&L: ${full['pnl']:+,.2f}, DD: {full['dd_pct']:.1f}%, "
              f"WR: {full['wr']:.1f}%{capped_note} "
              f"({time.time()-t0:.1f}s)")

        # --- Test 1: Window Split ---
        print(f"\n  [2] 3-Way Window Split...")
        t0 = time.time()
        ws = test_window_split(data, coins, signal_fn, params, indicators,
                               fee=MEXC_FEE, windows=windows)
        for name in ("early", "mid", "late"):
            w = ws[name]
            mark = "✅" if w["pf"] >= 1.0 and w["trades"] > 0 else "❌"
            print(f"      {name}: {w['trades']}tr, PF={w['pf']:.2f}, "
                  f"${w['pnl']:+,.2f} {mark}")
        print(f"      → {ws['n_profitable']}/3 {'PASS' if ws['pass'] else 'FAIL'} "
              f"({time.time()-t0:.1f}s)")

        # --- Test 2: Walk-Forward ---
        print(f"\n  [3] Walk-Forward...")
        t0 = time.time()
        wf = test_walk_forward(data, coins, signal_fn, params, indicators,
                               fee=MEXC_FEE, windows=windows)
        for sname, s in [("A", wf["split_a"]), ("B", wf["split_b"])]:
            mark = "✅" if s["pass"] else "❌"
            print(f"      Split {sname}: cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                  f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f} {mark}")
        print(f"      → {'PASS' if wf['pass'] else 'FAIL'} ({time.time()-t0:.1f}s)")

        # --- Test 3: Bootstrap ---
        print(f"\n  [4] Bootstrap ({N_RESAMPLES} resamples)...")
        t0 = time.time()
        bs = test_bootstrap(full["trade_list"])
        print(f"      P5 PF: {bs['p5_pf']:.2f}, Median PF: {bs['median_pf']:.2f}, "
              f"%Prof: {bs['pct_profitable']:.1f}%")
        print(f"      → {'PASS' if bs['pass'] else 'FAIL'} ({time.time()-t0:.1f}s)")

        # --- Verdict ---
        verdict, n_pass = _verdict(ws["pass"], wf["pass"], bs["pass"])
        print(f"\n  >>> VERDICT: {verdict} ({n_pass}/3)")

        # --- Determinism ---
        print(f"\n  [5] Determinism check...")
        det = check_determinism(data, coins, signal_fn, params, indicators,
                                fee=MEXC_FEE, max_bars=max_bar)
        print(f"      {'PASS' if det['pass'] else 'FAIL'}: "
              f"run1={det['run1']['trades']}tr PF={det['run1']['pf']:.4f}, "
              f"run2={det['run2']['trades']}tr PF={det['run2']['pf']:.4f}")

        all_results[label] = {
            "label": label, "desc": desc,
            "vol_mult": vol_mult, "rsi_max": rsi_max,
            "full_range": {
                "trades": full["trades"], "pf": full["pf"],
                "pnl": full["pnl"], "wr": full["wr"],
                "dd_pct": full["dd_pct"], "final_equity": full["final_equity"],
                "trades_per_day": round(full["trades"] / n_days, 2),
                "n_capped": full.get("n_capped", 0),
            },
            "window_split": ws,
            "walk_forward": wf,
            "bootstrap": bs,
            "verdict": verdict,
            "tests_passed": n_pass,
            "determinism": det,
        }

    # ===========================================================================
    # Reports
    # ===========================================================================
    print(f"\n{'='*70}")
    print("  REPORTS")
    print(f"{'='*70}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "mexc_v2_top200_truthpass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, ≥{MIN_BARS_TOP200} bars",
            "id": f"mexc_4h_top200_2160_v1",
            "n_coins": n_coins,
            "bars_min": min(bars_counts),
            "bars_max": max(bars_counts),
            "bars_median": int(median(bars_counts)),
            "full_range_days": round(n_days, 1),
        },
        "fee": MEXC_FEE,
        "fee_model": "mexc_spot_10bps",
        "sizing": "fixed_notional_2000",
        "configs": all_results,
    }

    # Strip trade_list from JSON report
    report_clean = json.loads(json.dumps(report, default=str))
    for label in report_clean["configs"]:
        if "full_range" in report_clean["configs"][label]:
            report_clean["configs"][label].pop("trade_list", None)

    json_path = REPORT_DIR / "mexc_v2_top200_truthpass_005.json"
    with open(json_path, "w") as f:
        json.dump(report_clean, f, indent=2)
    print(f"  JSON: {json_path}")

    # MD Report
    md_lines = [
        "# MEXC v2 Top-200 Truth-Pass (Fixed Notional)",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Universe**: Top {TOP_N} by volume, ≥{MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Full range**: ~{n_days:.0f} days, {max_bar} bars",
        f"**Fee**: MEXC 10bps",
        f"**Sizing**: Fixed $2,000/trade (no compounding)",
        "",
        "## Verdict Summary",
        "",
        "| Config | Verdict | PF | P&L | Trades | DD | WR | Window | WF | Bootstrap |",
        "|--------|---------|---:|----:|-------:|---:|---:|-------:|---:|----------:|",
    ]

    for label, entry in all_results.items():
        fr = entry["full_range"]
        ws = entry["window_split"]
        wf = entry["walk_forward"]
        bs = entry["bootstrap"]
        md_lines.append(
            f"| {entry['desc']} | **{entry['verdict']}** | {fr['pf']:.2f} "
            f"| ${fr['pnl']:+,.0f} | {fr['trades']} | {fr['dd_pct']:.1f}% "
            f"| {fr['wr']:.1f}% | {'PASS' if ws['pass'] else 'FAIL'} ({ws['n_profitable']}/3) "
            f"| {'PASS' if wf['pass'] else 'FAIL'} "
            f"| {'PASS' if bs['pass'] else 'FAIL'} (P5={bs['p5_pf']:.2f}, {bs['pct_profitable']:.0f}%) |"
        )
    md_lines.append("")

    # Detail per config
    for label, entry in all_results.items():
        md_lines.append(f"## {entry['desc']}")
        md_lines.append("")

        fr = entry["full_range"]
        md_lines.append(f"**Full range**: {fr['trades']} trades, PF={fr['pf']:.2f}, "
                       f"P&L=${fr['pnl']:+,.2f}, DD={fr['dd_pct']:.1f}%, "
                       f"WR={fr['wr']:.1f}%, {fr['trades_per_day']:.2f} trades/day")
        md_lines.append("")

        # Window
        ws = entry["window_split"]
        md_lines.append("### Window Split")
        md_lines.append("")
        md_lines.append("| Window | Trades | PF | P&L |")
        md_lines.append("|--------|-------:|---:|----:|")
        for name in ("early", "mid", "late"):
            w = ws[name]
            md_lines.append(f"| {name} | {w['trades']} | {w['pf']:.2f} | ${w['pnl']:+,.0f} |")
        md_lines.append(f"\n**{ws['n_profitable']}/3 {'PASS' if ws['pass'] else 'FAIL'}**")
        md_lines.append("")

        # WF
        wf = entry["walk_forward"]
        md_lines.append("### Walk-Forward")
        md_lines.append("")
        for sname, s in [("A (cal=early, test=mid+late)", wf["split_a"]),
                          ("B (cal=early+mid, test=late)", wf["split_b"])]:
            mark = "PASS" if s["pass"] else "FAIL"
            md_lines.append(f"- **Split {sname}** [{mark}]: "
                           f"cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                           f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f}")
        md_lines.append("")

        # Bootstrap
        bs = entry["bootstrap"]
        md_lines.append("### Bootstrap")
        md_lines.append("")
        md_lines.append(f"- P5 PF: {bs['p5_pf']:.2f}, Median PF: {bs['median_pf']:.2f}")
        md_lines.append(f"- % Profitable: {bs['pct_profitable']:.1f}%")
        md_lines.append(f"- **{'PASS' if bs['pass'] else 'FAIL'}**")
        md_lines.append("")

        # Determinism
        det = entry["determinism"]
        md_lines.append(f"### Determinism: **{'PASS' if det['pass'] else 'FAIL'}**")
        md_lines.append("")

    md_path = REPORT_DIR / "mexc_v2_top200_truthpass_005.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  MD: {md_path}")

    # ===========================================================================
    # Final summary
    # ===========================================================================
    print(f"\n{'='*70}")
    print("  FINAL VERDICTS")
    print(f"{'='*70}")
    for label, entry in all_results.items():
        fr = entry["full_range"]
        print(f"  {entry['desc']}: {entry['verdict']} ({entry['tests_passed']}/3)")
        print(f"    PF={fr['pf']:.2f}, P&L=${fr['pnl']:+,.2f}, {fr['trades']}tr, DD={fr['dd_pct']:.1f}%")
        print(f"    Determinism: {'PASS' if entry['determinism']['pass'] else 'FAIL'}")

    elapsed = time.time() - t_total
    print(f"\n  Total time: {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
