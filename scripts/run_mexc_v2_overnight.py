#!/usr/bin/env python3
"""
MEXC v2 Overnight Pipeline: Universe → Download → Backtest → Analysis → Report.

Runs autonomously. All phases chained. Checkpointed (resume-safe).

Usage:
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_overnight.py
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_overnight.py --skip-universe  # if universe already built
    PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_overnight.py --skip-download  # if data already downloaded
"""
from __future__ import annotations

import sys
import json
import time
import hashlib
import argparse
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
REGISTRY_PATH = DATA_ROOT / "manifests" / "registry.json"

# V2 paths
V2_OUTPUT_DIR = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h"
V2_DATA_FILE = V2_OUTPUT_DIR / "candle_cache_4h_mexc_v2.json"
V2_UNIVERSE_FILE = REPO_ROOT / "strategies" / "4h" / "mexc_universe_4h_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

# Existing v1 universe (will be overwritten by universe builder to default path)
V1_UNIVERSE_DEFAULT = REPO_ROOT / "strategies" / "4h" / "mexc_universe_4h.json"

# Sprint4 config 041
CONFIG_041_HYP_ID = "H4S4-G05"

# Fee models
MEXC_FEE = 0.0010
KRAKEN_FEE = 0.0026

# Engine constants
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
MAX_BARS_COMPARE = 721  # Match Kraken comparison window

# Universe params
MIN_BARS_UNIVERSE = 720  # 120 days — wider net
MAX_COINS = 800

# Bootstrap
N_RESAMPLES = 1000
SEED = 42


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ===========================================================================
# Phase 1: Build Universe
# ===========================================================================

def phase1_universe(skip: bool = False) -> dict:
    """Build or load MEXC universe v2."""
    print("\n" + "=" * 70)
    print("  PHASE 1: MEXC Universe v2")
    print("=" * 70)

    if skip and V2_UNIVERSE_FILE.exists():
        with open(V2_UNIVERSE_FILE) as f:
            universe = json.load(f)
        print(f"  Loaded existing universe: {len(universe['coins'])} coins")
        return universe

    # The universe builder writes to the default V1_UNIVERSE_DEFAULT path.
    # We'll check if it was recently generated (within last 2 hours) and reuse.
    if V1_UNIVERSE_DEFAULT.exists():
        import os
        mtime = os.path.getmtime(V1_UNIVERSE_DEFAULT)
        age_min = (time.time() - mtime) / 60
        if age_min < 120:
            # Recently built, probably by our concurrent build — use it
            with open(V1_UNIVERSE_DEFAULT) as f:
                universe = json.load(f)
            n = len(universe.get("coins", []))
            min_b = universe.get("min_bars", 0)
            print(f"  Found recent universe ({age_min:.0f}m old): {n} coins, min_bars={min_b}")
            if n >= 200:  # Looks like a v2-scale build
                # Copy to v2 path
                V2_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(V2_UNIVERSE_FILE, "w") as f:
                    json.dump(universe, f, indent=2)
                print(f"  Copied to {V2_UNIVERSE_FILE.name}")
                return universe

    # Need to build from scratch
    print(f"  Building universe (min_bars={MIN_BARS_UNIVERSE}, max_coins={MAX_COINS})...")
    print(f"  This takes 30-90 minutes (API rate limits).")
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_mexc_universe.py"),
        "--min-bars", str(MIN_BARS_UNIVERSE),
        "--max-coins", str(MAX_COINS),
    ]
    result = subprocess.run(cmd, capture_output=False, text=True, timeout=7200)
    if result.returncode != 0:
        print("  ERROR: Universe build failed!")
        sys.exit(1)

    # Read the output (written to default path)
    with open(V1_UNIVERSE_DEFAULT) as f:
        universe = json.load(f)

    # Copy to v2
    V2_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(V2_UNIVERSE_FILE, "w") as f:
        json.dump(universe, f, indent=2)

    print(f"  Universe v2: {len(universe['coins'])} coins")
    return universe


# ===========================================================================
# Phase 2: Download
# ===========================================================================

def phase2_download(universe: dict, skip: bool = False) -> Path:
    """Download 4H data for universe coins."""
    print("\n" + "=" * 70)
    print("  PHASE 2: Download MEXC 4H Data")
    print("=" * 70)

    if skip and V2_DATA_FILE.exists():
        print(f"  Using existing data: {V2_DATA_FILE}")
        return V2_DATA_FILE

    n_coins = len(universe.get("coins", []))
    est_min = n_coins * 5 * 1.2 / 60
    print(f"  Coins: {n_coins}")
    print(f"  Estimated time: ~{est_min:.0f} minutes")

    # Use existing downloader with --output and --universe pointing to v2
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "download_mexc_4h.py"),
        "--days", "400",
        "--universe", str(V2_UNIVERSE_FILE),
        "--output", str(V2_DATA_FILE),
        "--resume",
    ]
    print(f"  Command: {' '.join(cmd[-6:])}")
    result = subprocess.run(cmd, capture_output=False, text=True, timeout=14400)
    if result.returncode != 0:
        print("  ERROR: Download failed!")
        sys.exit(1)

    print(f"  Data saved: {V2_DATA_FILE}")
    return V2_DATA_FILE


# ===========================================================================
# Phase 3: Backtest
# ===========================================================================

def _find_config_041():
    """Find config 041 from sprint4 hypotheses."""
    import importlib
    _sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")
    all_configs = _sprint4_hyp.build_sweep_configs()
    for cfg in all_configs:
        if cfg["hypothesis_id"] == CONFIG_041_HYP_ID:
            return cfg
    raise ValueError(f"Config {CONFIG_041_HYP_ID} not found in hypotheses!")


def _result_to_dict(r) -> dict:
    """Convert BacktestResult dataclass to dict for pipeline consumption.

    Returns: {"summary": {...}, "trades": [...], "exit_classes": {...}}
    """
    n_trades = r.trades
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


def phase3_backtest(data_path: Path, universe: dict):
    """Run 041 backtest on MEXC v2 data with both fee models."""
    print("\n" + "=" * 70)
    print("  PHASE 3: Backtest Config 041")
    print("=" * 70)

    import importlib
    _sprint2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
    _sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")

    precompute_all = _sprint2_ind.precompute_all
    precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
    run_backtest = _sprint3_engine.run_backtest

    # Load data
    print("  Loading data...")
    t0 = time.time()
    with open(data_path) as f:
        raw_data = json.load(f)

    coins_in_data = [k for k in raw_data if not k.startswith("_")]
    print(f"  Coins in data: {len(coins_in_data)}")

    # Filter by universe membership and min bars
    universe_coins = set(universe.get("coins", []))
    data = {}
    dropped_bars = 0
    dropped_universe = 0
    for pair in coins_in_data:
        candles = raw_data[pair]
        if pair not in universe_coins:
            dropped_universe += 1
            continue
        if len(candles) < MIN_BARS_UNIVERSE:
            dropped_bars += 1
            continue
        data[pair] = candles

    coins = sorted(data.keys())
    n_coins = len(coins)
    bars_counts = [len(data[c]) for c in coins]
    print(f"  After filter: {n_coins} coins (dropped: {dropped_bars} bars, {dropped_universe} universe)")
    print(f"  Bars range: {min(bars_counts)} - {max(bars_counts)}, median: {int(median(bars_counts))}")

    # Get config 041
    cfg = _find_config_041()
    signal_fn = cfg["signal_fn"]
    params = dict(cfg["params"])  # copy to avoid mutation
    print(f"  Config: {cfg['id']} ({cfg['hypothesis_name']})")
    print(f"  Params: max_pos={params.get('max_pos')}, rsi_max={params.get('rsi_max')}, "
          f"vol_mult={params.get('vol_mult')}")

    # Precompute indicators
    print("  Precomputing indicators...")
    indicators = precompute_all(data, coins)
    market_context = precompute_sprint2_context(data, coins)
    params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c
    t_prep = time.time() - t0
    print(f"  Prep done in {t_prep:.1f}s")

    results = {}

    # --- Run 1: MEXC 10bps, 721-bar limit ---
    print(f"\n  --- Run 1: MEXC 10bps, max_bars={MAX_BARS_COMPARE} ---")
    t1 = time.time()
    r1_raw = run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=MEXC_FEE, exit_mode="dc",
        start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=MAX_BARS_COMPARE,
    )
    r1 = _result_to_dict(r1_raw)
    dt1 = time.time() - t1
    print(f"  Trades: {r1['summary']['trades']}, PF: {r1['summary']['pf']:.4f}, "
          f"P&L: ${r1['summary']['pnl']:.2f}, DD: {r1['summary']['dd_pct']:.1f}%, "
          f"Time: {dt1:.1f}s")
    results["mexc_10bps"] = r1

    # --- Run 2: Kraken-equivalent 26bps, 721-bar limit ---
    print(f"\n  --- Run 2: Kraken 26bps (fee isolation), max_bars={MAX_BARS_COMPARE} ---")
    t2 = time.time()
    r2_raw = run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=KRAKEN_FEE, exit_mode="dc",
        start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=MAX_BARS_COMPARE,
    )
    r2 = _result_to_dict(r2_raw)
    dt2 = time.time() - t2
    print(f"  Trades: {r2['summary']['trades']}, PF: {r2['summary']['pf']:.4f}, "
          f"P&L: ${r2['summary']['pnl']:.2f}, DD: {r2['summary']['dd_pct']:.1f}%, "
          f"Time: {dt2:.1f}s")
    results["mexc_26bps"] = r2

    # --- Run 3: MEXC 10bps, full range ---
    print(f"\n  --- Run 3: MEXC 10bps, FULL RANGE ---")
    t3 = time.time()
    r3_raw = run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=MEXC_FEE, exit_mode="dc",
        start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
    )
    r3 = _result_to_dict(r3_raw)
    dt3 = time.time() - t3
    max_bar = max(len(data[c]) for c in coins)
    n_days_full = (max_bar - START_BAR) * 4 / 24
    print(f"  Trades: {r3['summary']['trades']}, PF: {r3['summary']['pf']:.4f}, "
          f"DD: {r3['summary']['dd_pct']:.1f}%, "
          f"Max bars: {max_bar}, Days: {n_days_full:.0f}, Time: {dt3:.1f}s")
    results["full_range_10bps"] = r3

    return results, n_coins, bars_counts


# ===========================================================================
# Phase 4: Analysis
# ===========================================================================

def _window_split(result, max_bars=MAX_BARS_COMPARE):
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
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0)
        pnl = sum(pnls)
        wr = 100 * sum(1 for p in pnls if p > 0) / len(pnls)
        windows[name] = {
            "trades": len(w_trades), "pf": round(pf, 4), "pnl": round(pnl, 2),
            "wr": round(wr, 2), "start_bar": start, "end_bar": end,
        }
        if pnl > 0:
            n_profitable += 1

    return {"windows": windows, "windows_profitable": n_profitable,
            "pass": n_profitable >= 2}


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


def _top10(result):
    """Top 10 trades by absolute PnL."""
    trades = result.get("trades", [])
    if not trades:
        return {"top10_pnl_share": 0, "top10_coins": 0, "total_coins": 0, "top10_trades": []}

    total_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    sorted_trades = sorted(trades, key=lambda t: abs(t["pnl"]), reverse=True)[:10]
    top10_pnl = sum(t["pnl"] for t in sorted_trades if t["pnl"] > 0)
    share = top10_pnl / total_profit if total_profit > 0 else 0

    unique_coins = set(t.get("pair", "") for t in trades)
    top10_coins = set(t.get("pair", "") for t in sorted_trades)

    return {
        "top10_pnl_share": round(share, 4),
        "top10_coins": len(top10_coins),
        "total_coins": len(unique_coins),
        "top10_trades": [
            {"pair": t.get("pair", ""), "pnl": round(t["pnl"], 2),
             "reason": t.get("reason", "")}
            for t in sorted_trades
        ],
    }


def _bootstrap(result, n_resamples=N_RESAMPLES, seed=SEED):
    """Bootstrap resampling for PF confidence."""
    trades = result.get("trades", [])
    if len(trades) < 10:
        return {"pass": False, "n_trades": len(trades)}

    rng = np.random.default_rng(seed)
    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)

    pfs = []
    final_pnls = []
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
        "n_resamples": n_resamples,
        "n_trades": n,
        "median_pf": round(float(np.median(pfs)), 4),
        "p5_pf": round(float(np.percentile(pfs, 5)), 4),
        "p95_pf": round(float(np.percentile(pfs, 95)), 4),
        "median_pnl": round(float(np.median(final_pnls)), 2),
        "p5_pnl": round(float(np.percentile(final_pnls, 5)), 2),
        "pct_profitable": round(float(np.mean(final_pnls > 0) * 100), 1),
        "pass": bool(np.percentile(pfs, 5) >= 0.85 and np.mean(final_pnls > 0) >= 0.80),
    }


def phase4_analysis(results: dict, n_coins: int, bars_counts: list):
    """Full analysis suite."""
    print("\n" + "=" * 70)
    print("  PHASE 4: Analysis")
    print("=" * 70)

    analysis = {}

    # Load Kraken reference from v1 report
    kraken_ref = {"pf": 1.4058, "trades": 216, "dd": 36.37,
                  "pnl": 3349.79, "wr": 54.63}
    try:
        ref_path = REPORT_DIR / "mexc_041_portability_001.json"
        if ref_path.exists():
            with open(ref_path) as f:
                v1_report = json.load(f)
            if "kraken_reference" in v1_report:
                kraken_ref = v1_report["kraken_reference"]
    except Exception:
        pass

    for label, key in [("MEXC 10bps", "mexc_10bps"), ("MEXC 26bps", "mexc_26bps")]:
        r = results[key]
        print(f"\n  --- {label} ---")

        # Window split
        ws = _window_split(r)
        analysis[f"window_split_{key}"] = ws
        print(f"  Window split: {ws['windows_profitable']}/3 profitable ({'PASS' if ws['pass'] else 'FAIL'})")

        # Exit attribution
        ea = _exit_attribution(r)
        analysis[f"exit_attribution_{key}"] = ea
        for reason, stats in sorted(ea.items(), key=lambda x: x[1]["pnl"], reverse=True):
            print(f"    {reason}: {stats['count']}x, ${stats['pnl']:+.0f}, WR={stats['wr']:.0f}%")

        # Top 10
        t10 = _top10(r)
        analysis[f"top10_{key}"] = t10
        print(f"  Top10 share: {t10['top10_pnl_share']:.1%} ({t10['top10_coins']} coins / {t10['total_coins']} total)")

        # Bootstrap
        bs = _bootstrap(r)
        analysis[f"bootstrap_{key}"] = bs
        print(f"  Bootstrap: P5_PF={bs.get('p5_pf', 0):.2f}, {bs.get('pct_profitable', 0):.1f}% profitable ({'PASS' if bs.get('pass') else 'FAIL'})")

    # Fee delta
    r1s = results["mexc_10bps"]["summary"]
    r2s = results["mexc_26bps"]["summary"]
    analysis["fee_delta"] = {
        "pf_diff": round(r1s["pf"] - r2s["pf"], 4),
        "pnl_diff": round(r1s["pnl"] - r2s["pnl"], 2),
        "dd_diff": round(r1s["dd_pct"] - r2s["dd_pct"], 2),
        "wr_diff": round(r1s.get("wr", 0) - r2s.get("wr", 0), 2),
    }

    # Kraken delta
    analysis["kraken_delta"] = {
        "mexc_pf": r1s["pf"],
        "kraken_pf": kraken_ref["pf"],
        "pf_diff": round(r1s["pf"] - kraken_ref["pf"], 4),
        "mexc_trades": r1s["trades"],
        "kraken_trades": kraken_ref["trades"],
        "mexc_dd": r1s["dd_pct"],
        "kraken_dd": kraken_ref["dd"],
        "mexc_coins": n_coins,
        "kraken_coins": 487,
        "note": f"MEXC: {n_coins} USDT coins, 10bps. Kraken: 487 USD coins, 26bps."
    }

    # V1 vs V2 comparison
    try:
        v1_path = REPORT_DIR / "mexc_041_portability_001.json"
        if v1_path.exists():
            with open(v1_path) as f:
                v1 = json.load(f)
            v1_10 = v1["runs"]["mexc_10bps"]
            analysis["v1_vs_v2"] = {
                "v1_coins": v1.get("n_coins", 145),
                "v2_coins": n_coins,
                "v1_pf": v1_10["pf"],
                "v2_pf": r1s["pf"],
                "v1_trades": v1_10["trades"],
                "v2_trades": r1s["trades"],
                "v1_dd": v1_10["dd"],
                "v2_dd": r1s["dd_pct"],
                "v1_trades_per_day": v1_10["trades_per_day"],
                "v2_trades_per_day": round(r1s["trades"] / ((MAX_BARS_COMPARE - START_BAR) * 4 / 24), 2),
            }
            print(f"\n  --- V1 vs V2 ---")
            d = analysis["v1_vs_v2"]
            print(f"  Coins: {d['v1_coins']} → {d['v2_coins']}")
            print(f"  PF: {d['v1_pf']:.2f} → {d['v2_pf']:.2f}")
            print(f"  Trades: {d['v1_trades']} → {d['v2_trades']}")
            print(f"  DD: {d['v1_dd']:.1f}% → {d['v2_dd']:.1f}%")
    except Exception as e:
        print(f"  V1 comparison skipped: {e}")

    return analysis


# ===========================================================================
# Phase 5: Report
# ===========================================================================

def phase5_report(results: dict, analysis: dict, n_coins: int, bars_counts: list, universe: dict):
    """Write JSON + MD reports."""
    print("\n" + "=" * 70)
    print("  PHASE 5: Reports")
    print("=" * 70)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    git = _git_hash()

    r1s = results["mexc_10bps"]["summary"]
    r2s = results["mexc_26bps"]["summary"]
    r3s = results["full_range_10bps"]["summary"]
    n_days = (MAX_BARS_COMPARE - START_BAR) * 4 / 24

    max_bar_full = max(bars_counts) if bars_counts else MAX_BARS_COMPARE
    n_days_full = (max_bar_full - START_BAR) * 4 / 24

    # JSON report
    report = {
        "config_id": "sprint4_041_h4s4g05_vol3x_bblow_rsi40",
        "experiment": "mexc_portability_041_v2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe_id": f"mexc_4h_v2_{n_coins}",
        "n_coins": n_coins,
        "max_bars": MAX_BARS_COMPARE,
        "bars_stats": {
            "min": min(bars_counts),
            "max": max(bars_counts),
            "median": int(median(bars_counts)),
        },
        "runs": {
            "mexc_10bps": {
                "fee_model": "mexc_spot_10bps", "fee": MEXC_FEE,
                "trades": r1s["trades"], "pf": round(r1s["pf"], 4),
                "pnl": round(r1s["pnl"], 2),
                "wr": round(r1s.get("wr", 0), 2),
                "dd": round(r1s["dd_pct"], 2),
                "ev_per_trade": round(r1s["pnl"] / max(1, r1s["trades"]), 2),
                "trades_per_day": round(r1s["trades"] / n_days, 2),
                "n_days": round(n_days, 1),
                "n_coins": n_coins,
            },
            "mexc_26bps": {
                "fee_model": "kraken_spot_26bps", "fee": KRAKEN_FEE,
                "trades": r2s["trades"], "pf": round(r2s["pf"], 4),
                "pnl": round(r2s["pnl"], 2),
                "wr": round(r2s.get("wr", 0), 2),
                "dd": round(r2s["dd_pct"], 2),
                "ev_per_trade": round(r2s["pnl"] / max(1, r2s["trades"]), 2),
                "trades_per_day": round(r2s["trades"] / n_days, 2),
                "n_days": round(n_days, 1),
                "n_coins": n_coins,
            },
        },
        "full_range_10bps": {
            "max_bars": max_bar_full,
            "n_days": round(n_days_full, 1),
            "trades": r3s["trades"],
            "pf": round(r3s["pf"], 4),
            "dd": round(r3s["dd_pct"], 2),
            "trades_per_day": round(r3s["trades"] / max(1, n_days_full), 2),
        },
        "analysis": analysis,
        "kraken_reference": {
            "pf": 1.4058, "trades": 216, "dd": 36.37,
            "pnl": 3349.79, "wr": 54.63,
        },
    }

    json_path = REPORT_DIR / "mexc_041_portability_002.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  JSON: {json_path}")

    # MD report
    md = _build_md_report(report, analysis, n_coins)
    md_path = REPORT_DIR / "mexc_041_portability_002.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  MD: {md_path}")

    # Scoreboard
    scoreboard = _build_scoreboard(report)
    sb_json = REPORT_DIR / "mexc_041_portability_scoreboard_002.json"
    with open(sb_json, "w") as f:
        json.dump(scoreboard, f, indent=2)
    print(f"  Scoreboard JSON: {sb_json}")

    sb_md = _build_scoreboard_md(scoreboard)
    sb_md_path = REPORT_DIR / "mexc_041_portability_scoreboard_002.md"
    with open(sb_md_path, "w") as f:
        f.write(sb_md)
    print(f"  Scoreboard MD: {sb_md_path}")

    return json_path


def _build_md_report(report: dict, analysis: dict, n_coins: int) -> str:
    r1 = report["runs"]["mexc_10bps"]
    r2 = report["runs"]["mexc_26bps"]
    fr = report["full_range_10bps"]
    kr = report["kraken_reference"]

    lines = [
        "# MEXC Portability Report v2 — Config 041",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{report['git_hash']}`",
        f"**Dataset**: `{report['dataset_id']}` ({n_coins} coins)",
        f"**Universe**: `{report['universe_id']}`",
        f"**Config**: sprint4_041 (Vol Capitulation 3x BBlow RSI40, DC hybrid_notrl)",
        "",
        "## Results Summary",
        "",
        "| Metric | MEXC 10bps | MEXC 26bps | Kraken 26bps (ref) |",
        "|--------|-----------|-----------|-------------------|",
        f"| Trades | {r1['trades']} | {r2['trades']} | {kr['trades']} |",
        f"| PF | {r1['pf']:.2f} | {r2['pf']:.2f} | {kr['pf']:.2f} |",
        f"| P&L | ${r1['pnl']:+,.0f} | ${r2['pnl']:+,.0f} | ${kr['pnl']:+,.0f} |",
        f"| WR | {r1['wr']:.1f}% | {r2['wr']:.1f}% | {kr['wr']:.1f}% |",
        f"| DD | {r1['dd']:.1f}% | {r2['dd']:.1f}% | {kr['dd']:.1f}% |",
        f"| EV/trade | ${r1['ev_per_trade']:.2f} | ${r2['ev_per_trade']:.2f} | ${kr['pnl']/kr['trades']:.2f} |",
        f"| Trades/day | {r1['trades_per_day']:.2f} | {r2['trades_per_day']:.2f} | {kr['trades']/111.8:.2f} |",
        f"| Coins | {n_coins} | {n_coins} | 487 |",
        "",
        f"Full range (MEXC 10bps, {fr['n_days']:.0f}d): PF={fr['pf']:.2f}, {fr['trades']} trades, DD={fr['dd']:.1f}%",
        "",
    ]

    # V1 vs V2
    v1v2 = analysis.get("v1_vs_v2", {})
    if v1v2:
        lines.extend([
            "## V1 vs V2 Comparison",
            "",
            "| Metric | V1 (145 coins) | V2 ({} coins) | Delta |".format(v1v2.get("v2_coins", n_coins)),
            "|--------|:-:|:-:|:-:|",
            f"| PF | {v1v2['v1_pf']:.2f} | {v1v2['v2_pf']:.2f} | {v1v2['v2_pf']-v1v2['v1_pf']:+.2f} |",
            f"| Trades | {v1v2['v1_trades']} | {v1v2['v2_trades']} | {v1v2['v2_trades']-v1v2['v1_trades']:+d} |",
            f"| DD | {v1v2['v1_dd']:.1f}% | {v1v2['v2_dd']:.1f}% | {v1v2['v2_dd']-v1v2['v1_dd']:+.1f}pp |",
            f"| Trades/day | {v1v2['v1_trades_per_day']:.2f} | {v1v2['v2_trades_per_day']:.2f} | {v1v2['v2_trades_per_day']-v1v2['v1_trades_per_day']:+.2f} |",
            "",
        ])

    # Window split
    ws1 = analysis.get("window_split_mexc_10bps", {}).get("windows", {})
    if ws1:
        lines.extend([
            "## Window Split (MEXC 10bps)",
            "",
            "| Window | Trades | PF | P&L |",
            "|--------|-------:|---:|----:|",
        ])
        for name in ["early", "mid", "late"]:
            w = ws1.get(name, {})
            lines.append(f"| {name.capitalize()} | {w.get('trades', 0)} | {w.get('pf', 0):.2f} | ${w.get('pnl', 0):+,.0f} |")
        ws_pass = analysis.get("window_split_mexc_10bps", {}).get("pass", False)
        lines.append(f"\n**{analysis.get('window_split_mexc_10bps', {}).get('windows_profitable', 0)}/3 profitable {'PASS' if ws_pass else 'FAIL'}**")
        lines.append("")

    # Exit attribution
    ea1 = analysis.get("exit_attribution_mexc_10bps", {})
    if ea1:
        lines.extend([
            "## Exit Attribution (MEXC 10bps)",
            "",
            "| Exit | Class | Count | P&L | WR |",
            "|------|-------|------:|----:|---:|",
        ])
        for reason in sorted(ea1.keys(), key=lambda r: ea1[r]["pnl"], reverse=True):
            s = ea1[reason]
            lines.append(f"| {reason} | {s['class']} | {s['count']} | ${s['pnl']:+,.0f} | {s['wr']:.0f}% |")
        lines.append("")

    # Bootstrap
    bs1 = analysis.get("bootstrap_mexc_10bps", {})
    if bs1:
        lines.extend([
            "## Bootstrap (MEXC 10bps)",
            "",
            f"- Resamples: {bs1.get('n_resamples', 0)}",
            f"- Median PF: {bs1.get('median_pf', 0):.2f}",
            f"- P5 PF: {bs1.get('p5_pf', 0):.2f}",
            f"- P95 PF: {bs1.get('p95_pf', 0):.2f}",
            f"- % Profitable: {bs1.get('pct_profitable', 0):.1f}%",
            f"- **{'PASS' if bs1.get('pass') else 'FAIL'}**",
            "",
        ])

    # Fee delta
    fd = analysis.get("fee_delta", {})
    if fd:
        lines.extend([
            "## Fee Isolation",
            "",
            f"- PF diff (10bps vs 26bps): {fd.get('pf_diff', 0):+.4f}",
            f"- P&L diff: ${fd.get('pnl_diff', 0):+,.0f}",
            f"- DD diff: {fd.get('dd_diff', 0):+.2f}pp",
            "",
        ])

    return "\n".join(lines)


def _build_scoreboard(report: dict) -> dict:
    r1 = report["runs"]["mexc_10bps"]
    r2 = report["runs"]["mexc_26bps"]
    fr = report["full_range_10bps"]
    kr = report["kraken_reference"]

    entries = [
        {"label": f"MEXC 10bps v2 ({report['n_coins']}coins, {MAX_BARS_COMPARE}bars)",
         "fee": "10bps", **{k: r1[k] for k in ["trades", "pf", "pnl", "wr", "dd", "ev_per_trade", "trades_per_day"]}},
        {"label": f"MEXC 26bps v2 ({report['n_coins']}coins, {MAX_BARS_COMPARE}bars)",
         "fee": "26bps", **{k: r2[k] for k in ["trades", "pf", "pnl", "wr", "dd", "ev_per_trade", "trades_per_day"]}},
        {"label": f"MEXC 10bps FULL ({report['n_coins']}coins, {fr['max_bars']}bars)",
         "fee": "10bps", "trades": fr["trades"], "pf": fr["pf"], "dd": fr["dd"],
         "trades_per_day": fr["trades_per_day"]},
        {"label": "KRAKEN 26bps ref (487coins, 721bars)",
         "fee": "26bps", **{k: kr[k] for k in ["trades", "pf", "pnl", "dd", "wr"]}},
    ]

    return {"config": "sprint4_041", "entries": entries,
            "generated": report["timestamp"], "git": report["git_hash"]}


def _build_scoreboard_md(sb: dict) -> str:
    lines = [
        "# MEXC Portability Scoreboard v2 — Config 041",
        "",
        f"Generated: {sb['generated'][:10]} | Git: `{sb['git']}`",
        "",
        "| Run | Fee | Trades | PF | P&L | WR | DD | Trades/day |",
        "|-----|-----|-------:|---:|----:|---:|---:|-----------:|",
    ]
    for e in sb["entries"]:
        pnl = f"${e.get('pnl', 0):+,.0f}" if "pnl" in e else "—"
        wr = f"{e.get('wr', 0):.1f}%" if "wr" in e else "—"
        tpd = f"{e.get('trades_per_day', 0):.2f}" if "trades_per_day" in e else "—"
        lines.append(f"| {e['label']} | {e['fee']} | {e['trades']} | {e.get('pf', 0):.2f} | {pnl} | {wr} | {e.get('dd', 0):.1f}% | {tpd} |")
    return "\n".join(lines)


# ===========================================================================
# Phase 6: Registry
# ===========================================================================

def phase6_registry(n_coins: int):
    """Register v2 dataset in data lake registry."""
    print("\n" + "=" * 70)
    print("  PHASE 6: Registry")
    print("=" * 70)

    if not V2_DATA_FILE.exists():
        print("  SKIP: No v2 data file to register")
        return

    sha = _sha256(V2_DATA_FILE)
    size_mb = V2_DATA_FILE.stat().st_size / 1024 / 1024

    with open(REGISTRY_PATH) as f:
        registry = json.load(f)

    # Check if already registered
    ds_id = "ohlcv_4h_mexc_spot_usdt_v2"
    for ds in registry.get("datasets", []):
        if ds["id"] == ds_id:
            print(f"  Already registered: {ds_id}")
            return

    new_ds = {
        "id": ds_id,
        "description": f"MEXC SPOT USDT 4H candles via CryptoCompare ({n_coins} coins)",
        "source": "CryptoCompare histohour (e=MEXC)",
        "timeframe": "4h",
        "exchange": "mexc",
        "quote": "USDT",
        "coins": n_coins,
        "status": "canonical",
        "frozen": True,
        "canonical_path": str(V2_DATA_FILE.relative_to(DATA_ROOT)),
        "sha256": sha,
        "size_mb": round(size_mb, 1),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    registry["datasets"].append(new_ds)
    registry["version"] = registry.get("version", 3)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"  Registered: {ds_id} ({n_coins} coins, {size_mb:.1f} MB, SHA256: {sha[:16]}...)")


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="MEXC v2 Overnight Pipeline")
    parser.add_argument("--skip-universe", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-coins", type=int, default=MAX_COINS)
    args = parser.parse_args()

    t_total = time.time()
    print("\n" + "=" * 70)
    print("  MEXC v2 OVERNIGHT PIPELINE")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Phase 1: Universe
    universe = phase1_universe(skip=args.skip_universe)

    # Phase 2: Download
    data_path = phase2_download(universe, skip=args.skip_download)

    # Phase 3: Backtest
    results, n_coins, bars_counts = phase3_backtest(data_path, universe)

    # Phase 4: Analysis
    analysis = phase4_analysis(results, n_coins, bars_counts)

    # Phase 5: Report
    phase5_report(results, analysis, n_coins, bars_counts, universe)

    # Phase 6: Registry
    phase6_registry(n_coins)

    # Summary
    elapsed_min = (time.time() - t_total) / 60
    r1s = results["mexc_10bps"]["summary"]
    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETE")
    print("=" * 70)
    print(f"  Total time: {elapsed_min:.1f} min")
    print(f"  Coins: {n_coins}")
    print(f"  MEXC 10bps: PF={r1s['pf']:.2f}, {r1s['trades']} trades, DD={r1s['dd_pct']:.1f}%")
    print(f"  Reports: reports/4h/mexc_041_portability_002.{{json,md}}")
    print("=" * 70)


if __name__ == "__main__":
    main()
