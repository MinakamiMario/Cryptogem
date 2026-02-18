#!/usr/bin/env python3
"""
MEXC v2 Top-200 FULL-RANGE test: do the best configs become robust with more bars?

Runs 2 configs on the same top-200 universe (≥2160 bars) with NO end_bar limit:
  - vol=4.0, rsi=40  (best PF on 721 bars)
  - vol=3.5, rsi=35  (best risk-adjusted on 721 bars)

Each config gets:
  1. Full-range backtest (all available bars, ~2500 median)
  2. 3-way window split over the FULL range
  3. 5-way window split for finer granularity
  4. Bootstrap (1000 resamples)
  5. 721-bar re-run for delta check

Usage:
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_top200_fullrange.py
"""
from __future__ import annotations

import sys
import json
import time
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

# ---------------------------------------------------------------------------
CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
END_BAR_SHORT = 721

MIN_BARS_TOP200 = 2160
TOP_N = 200
N_RESAMPLES = 1000
SEED = 42

CONFIGS = [
    ("vol40_rsi40", 4.0, 40, "Vol 4.0x RSI 40"),
    ("vol35_rsi35", 3.5, 35, "Vol 3.5x RSI 35"),
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
# Data loading (same top-200 logic as previous script)
# ===========================================================================

def load_top200():
    print("\n" + "=" * 70)
    print("  STEP 1: Load Top-200 Universe")
    print("=" * 70)

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

    print(f"  Coins: {len(coins)}")
    print(f"  Bars: min={min(bars_counts)}, max={max(bars_counts)}, median={int(median(bars_counts))}")
    print(f"  Full-range days: ~{(median(bars_counts) - START_BAR) * 4 / 24:.0f}")

    return data, coins, bars_counts


# ===========================================================================
# Analysis helpers
# ===========================================================================

def _window_split(trades, start_bar, end_bar, n_windows=3):
    """N-way chronological window split."""
    if not trades:
        return {"windows": [], "n_profitable": 0, "n_windows": n_windows, "pass": False}

    span = end_bar - start_bar
    w_size = span // n_windows
    windows = []
    n_profitable = 0

    for i in range(n_windows):
        w_start = start_bar + i * w_size
        w_end = start_bar + (i + 1) * w_size if i < n_windows - 1 else end_bar
        w_trades = [t for t in trades if w_start <= t.get("entry_bar", 0) < w_end]

        if not w_trades:
            windows.append({"idx": i + 1, "trades": 0, "pf": 0, "pnl": 0, "wr": 0,
                            "start": w_start, "end": w_end})
            continue

        pnls = [t["pnl"] for t in w_trades]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)
        pnl_sum = sum(pnls)
        wr = 100 * sum(1 for p in pnls if p > 0) / len(pnls)

        windows.append({
            "idx": i + 1, "trades": len(w_trades),
            "pf": round(pf, 4), "pnl": round(pnl_sum, 2),
            "wr": round(wr, 1), "start": w_start, "end": w_end,
        })
        if pnl_sum > 0:
            n_profitable += 1

    # Gate: at least ceil(2/3) windows must be profitable
    gate_threshold = (n_windows * 2 + 2) // 3  # ceil(2n/3)
    return {
        "windows": windows,
        "n_profitable": n_profitable,
        "n_windows": n_windows,
        "gate_threshold": gate_threshold,
        "pass": n_profitable >= gate_threshold,
    }


def _exit_attribution(trades):
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


def _bootstrap(trades, n_resamples=N_RESAMPLES, seed=SEED):
    if len(trades) < 10:
        return {"pass": False, "n_trades": len(trades)}
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


# ===========================================================================
# Main experiment loop
# ===========================================================================

def main():
    t_total = time.time()
    print("\n" + "=" * 70)
    print("  MEXC v2 TOP-200 FULL-RANGE TEST")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    data, coins, bars_counts = load_top200()
    n_coins = len(coins)
    max_bar = max(bars_counts)
    med_bar = int(median(bars_counts))

    # Precompute
    print("\n" + "=" * 70)
    print("  STEP 2: Precompute")
    print("=" * 70)

    import importlib
    _s2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _s2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
    _engine = importlib.import_module("strategies.4h.sprint3.engine")
    _hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

    t0 = time.time()
    indicators = _s2_ind.precompute_all(data, coins)
    market_context = _s2_ctx.precompute_sprint2_context(data, coins)
    print(f"  Done in {time.time() - t0:.1f}s")

    # Find config 041
    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])

    run_backtest = _engine.run_backtest

    # Run experiments
    print("\n" + "=" * 70)
    print("  STEP 3: Experiments")
    print("=" * 70)

    all_results = {}

    for label, vol_mult, rsi_max, desc in CONFIGS:
        print(f"\n{'='*70}")
        print(f"  CONFIG: {desc} (vol={vol_mult}, rsi={rsi_max})")
        print(f"{'='*70}")

        params = dict(base_params)
        params["vol_mult"] = vol_mult
        params["rsi_max"] = rsi_max
        params["__market__"] = market_context
        for c in coins:
            indicators[c]["__coin__"] = c

        # --- Run A: Full range (no end_bar) ---
        print(f"\n  [A] Full range (all bars, max={max_bar})...")
        t0 = time.time()
        r_full_raw = run_backtest(
            data, coins, signal_fn, params, indicators,
            fee=MEXC_FEE, exit_mode="dc",
            start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
            cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        )
        r_full = _result_to_dict(r_full_raw)
        sf = r_full["summary"]
        n_days_full = (max_bar - START_BAR) * 4 / 24
        print(f"      Trades: {sf['trades']}, PF: {sf['pf']:.4f}, P&L: ${sf['pnl']:.2f}, "
              f"DD: {sf['dd_pct']:.1f}%, WR: {sf['wr']:.1f}%, Time: {time.time()-t0:.1f}s")
        print(f"      Days: ~{n_days_full:.0f}, Trades/day: {sf['trades']/n_days_full:.2f}")

        # --- Run B: 721-bar (for delta reference) ---
        print(f"\n  [B] 721-bar window (reference)...")
        t0 = time.time()
        r_short_raw = run_backtest(
            data, coins, signal_fn, params, indicators,
            fee=MEXC_FEE, exit_mode="dc",
            start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
            cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
            end_bar=END_BAR_SHORT,
        )
        r_short = _result_to_dict(r_short_raw)
        ss = r_short["summary"]
        print(f"      Trades: {ss['trades']}, PF: {ss['pf']:.4f}, P&L: ${ss['pnl']:.2f}, "
              f"DD: {ss['dd_pct']:.1f}%, WR: {ss['wr']:.1f}%")

        # --- Analysis on FULL range ---
        trades_full = r_full["trades"]

        # 3-way window split
        ws3 = _window_split(trades_full, START_BAR, max_bar, n_windows=3)
        print(f"\n  [C] 3-way window split (full range):")
        for w in ws3["windows"]:
            status = "✅" if w["pnl"] > 0 else "❌"
            bars_span = w["end"] - w["start"]
            days = bars_span * 4 / 24
            print(f"      W{w['idx']}: {w['trades']}tr, PF={w['pf']:.2f}, "
                  f"${w['pnl']:+,.0f}, WR={w['wr']:.0f}% ({days:.0f}d) {status}")
        print(f"      → {ws3['n_profitable']}/{ws3['n_windows']} profitable "
              f"(need ≥{ws3['gate_threshold']}) {'PASS' if ws3['pass'] else 'FAIL'}")

        # 5-way window split
        ws5 = _window_split(trades_full, START_BAR, max_bar, n_windows=5)
        print(f"\n  [D] 5-way window split (full range):")
        for w in ws5["windows"]:
            status = "✅" if w["pnl"] > 0 else "❌"
            bars_span = w["end"] - w["start"]
            days = bars_span * 4 / 24
            print(f"      W{w['idx']}: {w['trades']}tr, PF={w['pf']:.2f}, "
                  f"${w['pnl']:+,.0f}, WR={w['wr']:.0f}% ({days:.0f}d) {status}")
        print(f"      → {ws5['n_profitable']}/{ws5['n_windows']} profitable "
              f"(need ≥{ws5['gate_threshold']}) {'PASS' if ws5['pass'] else 'FAIL'}")

        # Exit attribution
        ea = _exit_attribution(trades_full)
        print(f"\n  [E] Exit attribution (full range):")
        for reason in sorted(ea.keys(), key=lambda r: ea[r]["pnl"], reverse=True):
            s = ea[reason]
            print(f"      {reason} ({s['class']}): {s['count']}x, ${s['pnl']:+,.0f}, WR={s['wr']:.0f}%")

        # Bootstrap
        bs = _bootstrap(trades_full)
        print(f"\n  [F] Bootstrap (full range, {bs['n_trades']} trades):")
        print(f"      Median PF: {bs['median_pf']:.2f}, P5 PF: {bs['p5_pf']:.2f}, "
              f"P95 PF: {bs['p95_pf']:.2f}")
        print(f"      % Profitable: {bs['pct_profitable']:.1f}% "
              f"{'PASS' if bs['pass'] else 'FAIL'}")

        # Delta: full vs 721
        print(f"\n  [G] Delta (full vs 721-bar):")
        print(f"      PF: {ss['pf']:.4f} → {sf['pf']:.4f} ({sf['pf']-ss['pf']:+.4f})")
        print(f"      Trades: {ss['trades']} → {sf['trades']} ({sf['trades']-ss['trades']:+d})")
        print(f"      DD: {ss['dd_pct']:.1f}% → {sf['dd_pct']:.1f}% ({sf['dd_pct']-ss['dd_pct']:+.1f}pp)")

        all_results[label] = {
            "vol_mult": vol_mult, "rsi_max": rsi_max, "desc": desc,
            "full_range": {
                "summary": {k: round(v, 4) if isinstance(v, float) else v
                            for k, v in sf.items()},
                "n_days": round(n_days_full, 1),
                "trades_per_day": round(sf["trades"] / n_days_full, 2),
            },
            "short_range": {
                "summary": {k: round(v, 4) if isinstance(v, float) else v
                            for k, v in ss.items()},
            },
            "window_split_3": ws3,
            "window_split_5": ws5,
            "exit_attribution": ea,
            "bootstrap": bs,
        }

    # ===========================================================================
    # Report
    # ===========================================================================
    print("\n" + "=" * 70)
    print("  STEP 4: Reports")
    print("=" * 70)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    git = _git_hash()

    report = {
        "experiment": "mexc_v2_top200_fullrange",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, ≥{MIN_BARS_TOP200} bars",
            "n_coins": n_coins,
            "bars_min": min(bars_counts),
            "bars_max": max(bars_counts),
            "bars_median": med_bar,
            "full_range_days": round(n_days_full, 1),
        },
        "fee": MEXC_FEE,
        "fee_model": "mexc_spot_10bps",
        "configs": all_results,
    }

    json_path = REPORT_DIR / "mexc_v2_top200_fullrange_004.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  JSON: {json_path}")

    # MD
    md_lines = [
        "# MEXC v2 Top-200 Full-Range Test",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Universe**: Top {TOP_N} by volume, ≥{MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Bars**: {min(bars_counts)}-{max(bars_counts)}, median {med_bar}",
        f"**Full range**: ~{n_days_full:.0f} days",
        f"**Fee**: MEXC 10bps",
        "",
        "## Summary",
        "",
        "| Config | Range | Trades | PF | P&L | DD | WR | Tr/day | Win3 | Win5 | Boot%Prof |",
        "|--------|-------|-------:|---:|----:|---:|---:|-------:|-----:|-----:|----------:|",
    ]

    for label, entry in all_results.items():
        sf = entry["full_range"]["summary"]
        ss = entry["short_range"]["summary"]
        ws3 = entry["window_split_3"]
        ws5 = entry["window_split_5"]
        bs = entry["bootstrap"]
        tpd = entry["full_range"]["trades_per_day"]

        md_lines.append(
            f"| {entry['desc']} | Full | {sf['trades']} | {sf['pf']:.2f} | "
            f"${sf['pnl']:+,.0f} | {sf['dd_pct']:.1f}% | {sf['wr']:.1f}% | "
            f"{tpd:.2f} | {ws3['n_profitable']}/{ws3['n_windows']} | "
            f"{ws5['n_profitable']}/{ws5['n_windows']} | {bs['pct_profitable']:.1f}% |"
        )
        n_days_short = (END_BAR_SHORT - START_BAR) * 4 / 24
        md_lines.append(
            f"| {entry['desc']} | 721b | {ss['trades']} | {ss['pf']:.2f} | "
            f"${ss['pnl']:+,.0f} | {ss['dd_pct']:.1f}% | {ss['wr']:.1f}% | "
            f"{ss['trades']/n_days_short:.2f} | — | — | — |"
        )

    md_lines.append("")

    # Detail per config
    for label, entry in all_results.items():
        md_lines.append(f"## {entry['desc']}")
        md_lines.append("")

        # 3-way
        md_lines.append("### 3-Way Window Split")
        md_lines.append("")
        md_lines.append("| Window | Trades | PF | P&L | WR | Days |")
        md_lines.append("|--------|-------:|---:|----:|---:|-----:|")
        for w in entry["window_split_3"]["windows"]:
            days = (w["end"] - w["start"]) * 4 / 24
            md_lines.append(f"| W{w['idx']} | {w['trades']} | {w['pf']:.2f} | "
                           f"${w['pnl']:+,.0f} | {w['wr']:.0f}% | {days:.0f} |")
        ws3 = entry["window_split_3"]
        md_lines.append(f"\n**{ws3['n_profitable']}/{ws3['n_windows']} "
                       f"{'PASS' if ws3['pass'] else 'FAIL'}** (need ≥{ws3['gate_threshold']})")
        md_lines.append("")

        # 5-way
        md_lines.append("### 5-Way Window Split")
        md_lines.append("")
        md_lines.append("| Window | Trades | PF | P&L | WR | Days |")
        md_lines.append("|--------|-------:|---:|----:|---:|-----:|")
        for w in entry["window_split_5"]["windows"]:
            days = (w["end"] - w["start"]) * 4 / 24
            md_lines.append(f"| W{w['idx']} | {w['trades']} | {w['pf']:.2f} | "
                           f"${w['pnl']:+,.0f} | {w['wr']:.0f}% | {days:.0f} |")
        ws5 = entry["window_split_5"]
        md_lines.append(f"\n**{ws5['n_profitable']}/{ws5['n_windows']} "
                       f"{'PASS' if ws5['pass'] else 'FAIL'}** (need ≥{ws5['gate_threshold']})")
        md_lines.append("")

        # Exit
        md_lines.append("### Exit Attribution")
        md_lines.append("")
        md_lines.append("| Exit | Class | Count | P&L | WR |")
        md_lines.append("|------|-------|------:|----:|---:|")
        ea = entry["exit_attribution"]
        for reason in sorted(ea.keys(), key=lambda r: ea[r]["pnl"], reverse=True):
            s = ea[reason]
            md_lines.append(f"| {reason} | {s['class']} | {s['count']} | ${s['pnl']:+,.0f} | {s['wr']:.0f}% |")
        md_lines.append("")

        # Bootstrap
        bs = entry["bootstrap"]
        md_lines.append("### Bootstrap")
        md_lines.append("")
        md_lines.append(f"- Trades: {bs['n_trades']}")
        md_lines.append(f"- P5 PF: {bs['p5_pf']:.2f}")
        md_lines.append(f"- Median PF: {bs['median_pf']:.2f}")
        md_lines.append(f"- % Profitable: {bs['pct_profitable']:.1f}%")
        md_lines.append(f"- **{'PASS' if bs['pass'] else 'FAIL'}**")
        md_lines.append("")

    md_path = REPORT_DIR / "mexc_v2_top200_fullrange_004.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  MD: {md_path}")

    # ===========================================================================
    # Verdict
    # ===========================================================================
    print("\n" + "=" * 70)
    print("  VERDICT")
    print("=" * 70)

    for label, entry in all_results.items():
        sf = entry["full_range"]["summary"]
        ws3 = entry["window_split_3"]
        ws5 = entry["window_split_5"]
        bs = entry["bootstrap"]

        gates = {
            "PF > 1.0": sf["pf"] > 1.0,
            "Window 3/3 ≥2": ws3["pass"],
            "Window 5/5 ≥4": ws5["pass"],
            "Bootstrap ≥80%": bs["pct_profitable"] >= 80.0,
            "P5 PF ≥0.85": bs.get("p5_pf", 0) >= 0.85,
        }
        n_pass = sum(gates.values())
        print(f"\n  {entry['desc']}:")
        for gate, passed in gates.items():
            print(f"    {'✅' if passed else '❌'} {gate}")
        print(f"    → {n_pass}/{len(gates)} gates")

        if n_pass == len(gates):
            print(f"    ⇒ PAPERTRADE CANDIDATE")
        elif n_pass >= 3:
            print(f"    ⇒ CONDITIONAL — needs more validation")
        else:
            print(f"    ⇒ PARK MEXC")

    elapsed = time.time() - t_total
    print(f"\n  Total time: {elapsed:.1f}s")
    print(f"  Reports: {REPORT_DIR / 'mexc_v2_top200_fullrange_004.*'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
