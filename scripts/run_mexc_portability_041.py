#!/usr/bin/env python3
"""
MEXC Portability Test for Sprint4 Config 041 (Vol Capitulation 3x BBlow RSI40).

Full pipeline:
  Phase 1: Build MEXC universe v2 (top 800 by volume, ≥360 bars)
  Phase 2: Download 4H candles for all universe coins → ohlcv_4h_mexc_spot_usdt_v2
  Phase 3: Build universe_mexc_v2.json from downloaded data
  Phase 4: Run 041 backtest with mexc_spot_10bps fees
  Phase 5: Run 041 backtest with kraken_spot_26bps fees (fee isolation)
  Phase 6: Analysis (window split, top10, exit attribution, trades/day, delta)
  Phase 7: Write reports

Usage:
    python3 scripts/run_mexc_portability_041.py
    python3 scripts/run_mexc_portability_041.py --skip-download    # if data already exists
    python3 scripts/run_mexc_portability_041.py --skip-universe    # if universe already built
    python3 scripts/run_mexc_portability_041.py --max-coins 400    # smaller universe
"""
from __future__ import annotations

import sys
import json
import time
import hashlib
import argparse
import importlib
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

# Import modules
_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")
_sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

resolve_dataset = _data_resolver.resolve_dataset
precompute_all = _sprint2_indicators.precompute_all
precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
run_backtest = _sprint3_engine.run_backtest
build_sweep_configs = _sprint4_hyp.build_sweep_configs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_ROOT = Path.home() / "CryptogemData"
REGISTRY_PATH = DATA_ROOT / "manifests" / "registry.json"
V2_OUTPUT_DIR = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h"
V2_OUTPUT_FILE = V2_OUTPUT_DIR / "candle_cache_4h_mexc_v2.json"
V2_UNIVERSE_FILE = REPO_ROOT / "strategies" / "4h" / "universe_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

# Sprint4 config 041 identification
CONFIG_041_ID = "sprint4_041_h4s4g05_vol3x_bblow_rsi40"
CONFIG_041_HYP_ID = "H4S4-G05"

# Fee models
MEXC_FEE = 0.0010      # 10bps per side
KRAKEN_FEE = 0.0026     # 26bps per side

# Engine constants (match sprint3/engine.py)
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

# Universe building
# Note: user wants ≥360 days (2160 bars) but practical limit depends on CC availability.
# Universe builder uses min_bars for CC bar-count check (Phase 1).
# Phase 3 re-filters downloaded data with --min-bars (can be stricter).
# Use 720 bars (120d) for universe builder to cast a wider net, then filter stricter post-download.
DEFAULT_MIN_BARS_UNIVERSE = 720  # 120 days for universe builder (wider net)
DEFAULT_MIN_BARS_FILTER = 720    # 120 days for post-download filter (minimum viable)
DEFAULT_MAX_COINS = 800

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
    """Compute SHA256 of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ===========================================================================
# Phase 1: Build MEXC Universe v2
# ===========================================================================

def phase1_build_universe(max_coins: int = DEFAULT_MAX_COINS) -> Path:
    """Build MEXC universe v2 by calling build_mexc_universe.py with higher max_coins."""
    print("\n" + "=" * 70)
    print("  PHASE 1: Build MEXC Universe v2")
    print("=" * 70)

    # Use existing build_mexc_universe.py but with custom args
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "build_mexc_universe.py"),
        "--max-coins", str(max_coins),
        "--min-bars", str(DEFAULT_MIN_BARS_UNIVERSE),
    ]
    print(f"  Command: {' '.join(cmd)}")
    print(f"  This may take 30-60 minutes (API rate limits)...")
    print()

    # We need to patch the OUTPUT_PATH. Instead of modifying the script,
    # we'll run it and then copy/rename the output.
    # Actually, the script writes to a fixed path. We'll capture and move.
    # Better approach: run the universe building logic inline.

    # Import the build functions
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_mexc_universe as bmu

    # Override the output path
    original_output = bmu.OUTPUT_PATH
    bmu.OUTPUT_PATH = V2_UNIVERSE_FILE

    # Override save function to use v2 version tag
    original_save = bmu.save_universe

    def save_universe_v2(selected, min_bars, max_coins_arg):
        """Save with v2 version."""
        print(f"\n[5/5] Saving to {V2_UNIVERSE_FILE}...")
        coins = [f"{r['sym']}/USD" for r in selected]
        coin_stats = {}
        for r in selected:
            key = f"{r['sym']}/USD"
            coin_stats[key] = {"bars": r["bars"], "days": r["days"]}

        output = {
            "version": "v2",
            "exchange": "mexc",
            "quote_currency": "USDT",
            "internal_format": "SYM/USD",
            "n_coins": len(coins),
            "min_bars": min_bars,
            "min_days": bmu.bars_to_days(min_bars),
            "max_coins": max_coins_arg,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coins": coins,
            "coin_stats": coin_stats,
        }

        V2_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(V2_UNIVERSE_FILE, "w") as f:
            json.dump(output, f, indent=2)
        print(f"  Saved {len(coins)} coins to {V2_UNIVERSE_FILE.name}")

    bmu.save_universe = save_universe_v2

    try:
        # Run the pipeline
        pairs = bmu.fetch_mexc_pairs()
        ranked = bmu.fetch_mexc_volumes(pairs)
        results = bmu.check_all_bars(ranked, DEFAULT_MIN_BARS_UNIVERSE, max_coins)
        selected = bmu.filter_and_rank(results, DEFAULT_MIN_BARS_UNIVERSE, max_coins)
        if not selected:
            print("ERROR: No coins passed the filter.")
            sys.exit(1)
        save_universe_v2(selected, DEFAULT_MIN_BARS_UNIVERSE, max_coins)

        # Print summary
        bc = [r["bars"] for r in selected]
        print(f"\n  Universe v2: {len(selected)} coins")
        print(f"  Bar range: {min(bc)} - {max(bc)} bars")
        print(f"  Day range: {bmu.bars_to_days(min(bc))} - {bmu.bars_to_days(max(bc))} days")
    finally:
        bmu.OUTPUT_PATH = original_output
        bmu.save_universe = original_save

    return V2_UNIVERSE_FILE


# ===========================================================================
# Phase 2: Download MEXC 4H data to v2
# ===========================================================================

def phase2_download(universe_path: Path) -> Path:
    """Download MEXC 4H candles for universe v2 coins."""
    print("\n" + "=" * 70)
    print("  PHASE 2: Download MEXC 4H candles (v2)")
    print("=" * 70)

    # Use existing download_mexc_4h.py with --output and --universe overrides
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "download_mexc_4h.py"),
        "--days", "500",
        "--universe", str(universe_path),
        "--output", str(V2_OUTPUT_FILE),
        "--resume",
    ]
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Output: {V2_OUTPUT_FILE}")
    print()

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"ERROR: Download failed with exit code {result.returncode}")
        sys.exit(1)

    if not V2_OUTPUT_FILE.exists():
        print(f"ERROR: Output file not found: {V2_OUTPUT_FILE}")
        sys.exit(1)

    # Compute SHA256
    sha = _sha256(V2_OUTPUT_FILE)
    size_bytes = V2_OUTPUT_FILE.stat().st_size
    print(f"\n  SHA256: {sha}")
    print(f"  Size: {size_bytes / 1024 / 1024:.1f} MB")

    return V2_OUTPUT_FILE


# ===========================================================================
# Phase 3: Build final universe from downloaded data
# ===========================================================================

def phase3_build_universe_from_data(data_path: Path, min_bars: int = 360) -> tuple[list[str], dict]:
    """Filter downloaded data into final universe, log dropoffs."""
    print("\n" + "=" * 70)
    print("  PHASE 3: Build Universe from Downloaded Data")
    print("=" * 70)

    with open(data_path) as f:
        data = json.load(f)

    # Filter coins by bar count
    coin_bars = {}
    rejected_bars = 0
    total_coins = 0

    for pair in sorted(data.keys()):
        if pair.startswith("_"):
            continue
        total_coins += 1
        candles = data[pair]
        n = len(candles)
        coin_bars[pair] = n
        if n < min_bars:
            rejected_bars += 1

    passing = {p: b for p, b in coin_bars.items() if b >= min_bars}

    # Sort by bar count descending (proxy for data quality)
    sorted_coins = sorted(passing.keys(), key=lambda p: passing[p], reverse=True)

    # Bar statistics
    bar_counts = list(passing.values())
    all_bar_counts = list(coin_bars.values())

    stats = {
        "total_downloaded": total_coins,
        "passing": len(sorted_coins),
        "rejected_bars": rejected_bars,
        "min_bars_threshold": min_bars,
        "bars_min": min(bar_counts) if bar_counts else 0,
        "bars_max": max(bar_counts) if bar_counts else 0,
        "bars_median": int(median(bar_counts)) if bar_counts else 0,
    }

    print(f"  Total downloaded: {total_coins}")
    print(f"  Passing (≥{min_bars} bars): {len(sorted_coins)}")
    print(f"  Rejected (< {min_bars} bars): {rejected_bars}")
    if bar_counts:
        print(f"  Bars: min={stats['bars_min']}, max={stats['bars_max']}, median={stats['bars_median']}")

    # Save v2 universe
    universe_out = {
        "version": "v2",
        "exchange": "mexc",
        "quote_currency": "USDT",
        "internal_format": "SYM/USD",
        "n_coins": len(sorted_coins),
        "min_bars": min_bars,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "stats": stats,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_hash": _git_hash(),
        "coins": sorted_coins,
    }

    V2_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(V2_UNIVERSE_FILE, "w") as f:
        json.dump(universe_out, f, indent=2)
    print(f"  Saved universe: {V2_UNIVERSE_FILE}")

    return sorted_coins, stats


# ===========================================================================
# Phase 4+5: Run 041 backtest with configurable fees
# ===========================================================================

def _find_config_041():
    """Find and return config 041 (H4S4-G05) from hypotheses registry.

    build_sweep_configs() returns list of dicts with keys:
      idx, id, label, hypothesis_id, hypothesis_name, family, category,
      signal_fn, params, description.
    """
    all_configs = build_sweep_configs()
    for cfg in all_configs:
        if cfg["hypothesis_id"] == CONFIG_041_HYP_ID:
            return cfg
    raise ValueError(f"Config {CONFIG_041_HYP_ID} not found in sweep configs")


def phase4_run_backtest(
    data: dict,
    coins: list[str],
    fee: float,
    fee_label: str,
    max_bars: int | None = None,
) -> dict:
    """Run 041 backtest on MEXC data with specified fee model."""
    print(f"\n{'=' * 70}")
    print(f"  Running 041 backtest — {fee_label} ({fee*10000:.0f}bps/side)")
    print(f"{'=' * 70}")
    print(f"  Coins: {len(coins)}, Fee: {fee}, Start bar: {START_BAR}")

    cfg = _find_config_041()
    signal_fn = cfg["signal_fn"]
    params = cfg["params"]
    print(f"  Config: {cfg['hypothesis_id']} — {cfg['hypothesis_name']}")
    print(f"  Signal: {signal_fn.__name__}")
    print(f"  Params: vol_mult={params.get('vol_mult')}, rsi_max={params.get('rsi_max')}, "
          f"require_bb_lower={params.get('require_bb_lower')}, max_pos={params.get('max_pos')}")

    # Precompute indicators
    t0 = time.time()
    indicators = precompute_all(data, coins)
    t_ind = time.time() - t0
    print(f"  Indicators precomputed in {t_ind:.1f}s")

    # Determine bar range
    if max_bars is None:
        max_bars = max(ind["n"] for ind in indicators.values()) if indicators else 0
    print(f"  Max bars: {max_bars}")

    # Run full backtest
    t0 = time.time()
    result = run_backtest(
        data=data,
        coins=coins,
        signal_fn=signal_fn,
        params=params,
        indicators=indicators,
        exit_mode="dc",
        fee=fee,
        initial_capital=INITIAL_CAPITAL,
        start_bar=START_BAR,
        end_bar=max_bars,
        cooldown_bars=COOLDOWN_BARS,
        cooldown_after_stop=COOLDOWN_AFTER_STOP,
        max_pos=params.get("max_pos", 3),
    )
    t_bt = time.time() - t0

    print(f"  Backtest completed in {t_bt:.1f}s")
    print(f"  Trades: {result.trades}")
    print(f"  PF: {result.pf}")
    print(f"  PnL: ${result.pnl:+,.2f}")
    print(f"  WR: {result.wr:.1f}%")
    print(f"  DD: {result.dd:.1f}%")

    # Build run summary
    n_days = (max_bars - START_BAR) * 4 / 24
    trades_per_day = result.trades / n_days if n_days > 0 else 0.0
    ev_per_trade = result.pnl / result.trades if result.trades > 0 else 0.0

    summary = {
        "config_id": CONFIG_041_ID,
        "hypothesis_id": CONFIG_041_HYP_ID,
        "fee_model": fee_label,
        "fee_per_side": fee,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "n_coins": len(coins),
        "max_bars": max_bars,
        "start_bar": START_BAR,
        "n_days": round(n_days, 1),
        "trades": result.trades,
        "pf": result.pf,
        "pnl": result.pnl,
        "wr": result.wr,
        "dd": result.dd,
        "final_equity": result.final_equity,
        "ev_per_trade": round(ev_per_trade, 2),
        "trades_per_day": round(trades_per_day, 2),
        "exit_classes": result.exit_classes,
        "trade_list": result.trade_list,
        "backtest_time_s": round(t_bt, 1),
        "indicators_time_s": round(t_ind, 1),
    }

    return summary


# ===========================================================================
# Phase 6: Analysis
# ===========================================================================

def _window_split(trade_list: list, max_bars: int) -> dict:
    """3-way window split analysis."""
    if not trade_list:
        return {"pass": False, "error": "no trades"}

    third = (max_bars - START_BAR) // 3
    boundaries = {
        "early": (START_BAR, START_BAR + third),
        "mid": (START_BAR + third, START_BAR + 2 * third),
        "late": (START_BAR + 2 * third, max_bars),
    }

    windows = {}
    profitable_windows = 0

    for name, (start, end) in boundaries.items():
        window_trades = [t for t in trade_list if start <= t["entry_bar"] < end]
        if not window_trades:
            windows[name] = {"trades": 0, "pf": 0.0, "pnl": 0.0, "wr": 0.0}
            continue

        wins = [t["pnl"] for t in window_trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in window_trades if t["pnl"] <= 0]
        sw = sum(wins)
        sl = abs(sum(losses))
        pf = sw / sl if sl > 0 else (float("inf") if sw > 0 else 0.0)
        wr = len(wins) / len(window_trades) * 100

        windows[name] = {
            "start_bar": start,
            "end_bar": end,
            "trades": len(window_trades),
            "pf": round(pf, 4),
            "pnl": round(sum(t["pnl"] for t in window_trades), 2),
            "wr": round(wr, 2),
        }
        if pf >= 1.0:
            profitable_windows += 1

    return {
        "windows": windows,
        "windows_profitable": profitable_windows,
        "pass": profitable_windows >= 2,
    }


def _top10_concentration(trade_list: list) -> dict:
    """Top-10 trade concentration (by abs PnL)."""
    if not trade_list:
        return {}

    sorted_by_pnl = sorted(trade_list, key=lambda t: abs(t["pnl"]), reverse=True)
    top10 = sorted_by_pnl[:10]
    total_profit = sum(max(0, t["pnl"]) for t in trade_list)
    top10_profit = sum(max(0, t["pnl"]) for t in top10)

    # Unique coins
    all_coins = set(t["pair"] for t in trade_list)
    top10_coins = set(t["pair"] for t in top10)

    top10_pnl_share = top10_profit / total_profit if total_profit > 0 else 0.0

    return {
        "top10_profit": round(top10_profit, 2),
        "total_profit": round(total_profit, 2),
        "top10_pnl_share": round(min(1.0, top10_pnl_share), 4),
        "top10_coins": len(top10_coins),
        "total_coins": len(all_coins),
        "top10_coin_share": round(len(top10_coins) / max(1, len(all_coins)), 4),
        "top10_trades": [
            {"pair": t["pair"], "pnl": round(t["pnl"], 2), "reason": t["reason"]}
            for t in top10
        ],
    }


def _exit_attribution(exit_classes: dict) -> dict:
    """Exit reason breakdown."""
    result = {}
    for cls_name, reasons in exit_classes.items():
        for reason, stats in reasons.items():
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0.0
            result[reason] = {
                "class": cls_name,
                "count": stats["count"],
                "pnl": round(stats["pnl"], 2),
                "wins": stats["wins"],
                "wr": round(wr, 1),
            }
    return result


def _bootstrap(trade_list: list, n_resamples: int = N_RESAMPLES, seed: int = SEED) -> dict:
    """Bootstrap Monte Carlo: resample trade order."""
    if not trade_list or len(trade_list) < 10:
        return {"pass": False, "error": "too few trades"}

    rng = np.random.RandomState(seed)
    pnls = np.array([t["pnl"] for t in trade_list])
    n = len(pnls)

    pf_arr = []
    pnl_arr = []

    for _ in range(n_resamples):
        idx = rng.randint(0, n, size=n)
        sample = pnls[idx]
        wins = sample[sample > 0].sum()
        losses = abs(sample[sample <= 0].sum())
        pf = wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)
        pf_arr.append(pf)
        pnl_arr.append(sample.sum())

    pf_arr = np.array(pf_arr)
    pnl_arr = np.array(pnl_arr)

    return {
        "n_resamples": n_resamples,
        "seed": seed,
        "n_trades": n,
        "median_pf": round(float(np.median(pf_arr)), 4),
        "p5_pf": round(float(np.percentile(pf_arr, 5)), 4),
        "p95_pf": round(float(np.percentile(pf_arr, 95)), 4),
        "median_pnl": round(float(np.median(pnl_arr)), 2),
        "p5_pnl": round(float(np.percentile(pnl_arr, 5)), 2),
        "pct_profitable": round(float((pnl_arr > 0).mean() * 100), 1),
        "pass": bool(np.percentile(pf_arr, 5) >= 0.85 and (pnl_arr > 0).mean() >= 0.80),
    }


def phase6_analysis(run_mexc: dict, run_kraken_fee: dict, kraken_ref: dict | None = None) -> dict:
    """Full analysis of portability results."""
    print(f"\n{'=' * 70}")
    print(f"  PHASE 6: Analysis")
    print(f"{'=' * 70}")

    max_bars = run_mexc["max_bars"]

    # Window split
    ws_mexc = _window_split(run_mexc["trade_list"], max_bars)
    ws_kfee = _window_split(run_kraken_fee["trade_list"], max_bars)

    # Top-10 concentration
    top10_mexc = _top10_concentration(run_mexc["trade_list"])
    top10_kfee = _top10_concentration(run_kraken_fee["trade_list"])

    # Exit attribution
    exit_mexc = _exit_attribution(run_mexc["exit_classes"])
    exit_kfee = _exit_attribution(run_kraken_fee["exit_classes"])

    # Bootstrap
    boot_mexc = _bootstrap(run_mexc["trade_list"])
    boot_kfee = _bootstrap(run_kraken_fee["trade_list"])

    # Trade frequency
    print(f"\n  MEXC (10bps): {run_mexc['trades']} trades in {run_mexc['n_days']:.0f} days "
          f"= {run_mexc['trades_per_day']:.2f} trades/day")
    print(f"  MEXC (26bps): {run_kraken_fee['trades']} trades in {run_kraken_fee['n_days']:.0f} days "
          f"= {run_kraken_fee['trades_per_day']:.2f} trades/day")

    # Delta analysis (MEXC 10bps vs Kraken 26bps fee)
    delta = {
        "pf_diff": round(run_mexc["pf"] - run_kraken_fee["pf"], 4),
        "pnl_diff": round(run_mexc["pnl"] - run_kraken_fee["pnl"], 2),
        "dd_diff": round(run_mexc["dd"] - run_kraken_fee["dd"], 2),
        "wr_diff": round(run_mexc["wr"] - run_kraken_fee["wr"], 2),
        "trade_diff": run_mexc["trades"] - run_kraken_fee["trades"],
        "note": "Same MEXC data, different fee models. Trades should be identical (fee doesn't affect entries).",
    }

    print(f"\n  Fee Delta (10bps - 26bps):")
    print(f"    PF: {delta['pf_diff']:+.4f}")
    print(f"    PnL: ${delta['pnl_diff']:+,.2f}")
    print(f"    DD: {delta['dd_diff']:+.1f}%")

    # Kraken comparison (if reference data available)
    kraken_delta = None
    if kraken_ref:
        kraken_delta = {
            "mexc_pf": run_mexc["pf"],
            "kraken_pf": kraken_ref["pf"],
            "pf_diff": round(run_mexc["pf"] - kraken_ref["pf"], 4),
            "mexc_trades": run_mexc["trades"],
            "kraken_trades": kraken_ref["trades"],
            "mexc_dd": run_mexc["dd"],
            "kraken_dd": kraken_ref["dd"],
            "note": "MEXC USDT vs Kraken USD, different coin pools, different microstructure",
        }
        print(f"\n  MEXC vs Kraken (different data + different fee):")
        print(f"    PF: {kraken_delta['mexc_pf']:.4f} vs {kraken_delta['kraken_pf']:.4f} "
              f"(diff {kraken_delta['pf_diff']:+.4f})")
        print(f"    Trades: {kraken_delta['mexc_trades']} vs {kraken_delta['kraken_trades']}")

    analysis = {
        "window_split_mexc_10bps": ws_mexc,
        "window_split_mexc_26bps": ws_kfee,
        "top10_mexc_10bps": top10_mexc,
        "top10_mexc_26bps": top10_kfee,
        "exit_attribution_mexc_10bps": exit_mexc,
        "exit_attribution_mexc_26bps": exit_kfee,
        "bootstrap_mexc_10bps": boot_mexc,
        "bootstrap_mexc_26bps": boot_kfee,
        "fee_delta": delta,
        "kraken_delta": kraken_delta,
    }

    return analysis


# ===========================================================================
# Phase 7: Write reports
# ===========================================================================

def phase7_write_reports(
    run_mexc: dict,
    run_kraken_fee: dict,
    analysis: dict,
    universe_stats: dict,
    data_sha256: str,
    data_size_bytes: int,
) -> None:
    """Write JSON and MD reports."""
    print(f"\n{'=' * 70}")
    print(f"  PHASE 7: Write Reports")
    print(f"{'=' * 70}")

    git_hash = _git_hash()
    timestamp = datetime.now(timezone.utc).isoformat()

    # --- JSON Report ---
    report = {
        "config_id": CONFIG_041_ID,
        "experiment": "mexc_portability_041",
        "timestamp": timestamp,
        "git_hash": git_hash,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe_id": "universe_mexc_v2",
        "data_sha256": data_sha256,
        "data_size_bytes": data_size_bytes,
        "universe_stats": universe_stats,
        "runs": {
            "mexc_10bps": {
                "fee_model": "mexc_spot_10bps",
                "fee": MEXC_FEE,
                "trades": run_mexc["trades"],
                "pf": run_mexc["pf"],
                "pnl": run_mexc["pnl"],
                "wr": run_mexc["wr"],
                "dd": run_mexc["dd"],
                "ev_per_trade": run_mexc["ev_per_trade"],
                "trades_per_day": run_mexc["trades_per_day"],
                "n_days": run_mexc["n_days"],
                "n_coins": run_mexc["n_coins"],
            },
            "mexc_26bps": {
                "fee_model": "kraken_spot_26bps",
                "fee": KRAKEN_FEE,
                "trades": run_kraken_fee["trades"],
                "pf": run_kraken_fee["pf"],
                "pnl": run_kraken_fee["pnl"],
                "wr": run_kraken_fee["wr"],
                "dd": run_kraken_fee["dd"],
                "ev_per_trade": run_kraken_fee["ev_per_trade"],
                "trades_per_day": run_kraken_fee["trades_per_day"],
                "n_days": run_kraken_fee["n_days"],
                "n_coins": run_kraken_fee["n_coins"],
            },
        },
        "analysis": {
            "window_split_mexc_10bps": analysis["window_split_mexc_10bps"],
            "window_split_mexc_26bps": analysis["window_split_mexc_26bps"],
            "top10_mexc_10bps": analysis["top10_mexc_10bps"],
            "top10_mexc_26bps": analysis["top10_mexc_26bps"],
            "exit_attribution_mexc_10bps": analysis["exit_attribution_mexc_10bps"],
            "exit_attribution_mexc_26bps": analysis["exit_attribution_mexc_26bps"],
            "bootstrap_mexc_10bps": analysis["bootstrap_mexc_10bps"],
            "bootstrap_mexc_26bps": analysis["bootstrap_mexc_26bps"],
            "fee_delta": analysis["fee_delta"],
            "kraken_delta": analysis["kraken_delta"],
        },
    }

    # Write JSON
    json_path = REPORT_DIR / "mexc_041_portability_001.json"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  JSON: {json_path}")

    # --- Scoreboard JSON ---
    scoreboard = {
        "experiment": "mexc_portability_041",
        "timestamp": timestamp,
        "git_hash": git_hash,
        "configs": [
            {
                "label": "041 @ MEXC 10bps",
                "trades": run_mexc["trades"],
                "pf": run_mexc["pf"],
                "pnl": run_mexc["pnl"],
                "wr": run_mexc["wr"],
                "dd": run_mexc["dd"],
                "trades_per_day": run_mexc["trades_per_day"],
                "window_pass": analysis["window_split_mexc_10bps"]["pass"],
                "boot_pass": analysis["bootstrap_mexc_10bps"].get("pass", False),
            },
            {
                "label": "041 @ MEXC 26bps",
                "trades": run_kraken_fee["trades"],
                "pf": run_kraken_fee["pf"],
                "pnl": run_kraken_fee["pnl"],
                "wr": run_kraken_fee["wr"],
                "dd": run_kraken_fee["dd"],
                "trades_per_day": run_kraken_fee["trades_per_day"],
                "window_pass": analysis["window_split_mexc_26bps"]["pass"],
                "boot_pass": analysis["bootstrap_mexc_26bps"].get("pass", False),
            },
        ],
    }

    sb_json = REPORT_DIR / "mexc_041_portability_scoreboard_001.json"
    with open(sb_json, "w") as f:
        json.dump(scoreboard, f, indent=2)
    print(f"  Scoreboard JSON: {sb_json}")

    # --- MD Report ---
    md_lines = [
        f"# MEXC Portability Test — Config 041",
        f"",
        f"**Date**: {timestamp[:10]}",
        f"**Git**: {git_hash}",
        f"**Dataset**: ohlcv_4h_mexc_spot_usdt_v2 (SHA256: {data_sha256[:16]}...)",
        f"**Universe**: {universe_stats.get('passing', '?')} coins (MEXC SPOT USDT)",
        f"",
        f"## Results Summary",
        f"",
        f"| Metric | MEXC 10bps | MEXC 26bps | Delta |",
        f"|--------|-----------|-----------|-------|",
        f"| Trades | {run_mexc['trades']} | {run_kraken_fee['trades']} | {run_mexc['trades'] - run_kraken_fee['trades']} |",
        f"| PF | {run_mexc['pf']:.4f} | {run_kraken_fee['pf']:.4f} | {analysis['fee_delta']['pf_diff']:+.4f} |",
        f"| PnL | ${run_mexc['pnl']:+,.2f} | ${run_kraken_fee['pnl']:+,.2f} | ${analysis['fee_delta']['pnl_diff']:+,.2f} |",
        f"| WR | {run_mexc['wr']:.1f}% | {run_kraken_fee['wr']:.1f}% | {analysis['fee_delta']['wr_diff']:+.1f}% |",
        f"| DD | {run_mexc['dd']:.1f}% | {run_kraken_fee['dd']:.1f}% | {analysis['fee_delta']['dd_diff']:+.1f}% |",
        f"| EV/trade | ${run_mexc['ev_per_trade']:.2f} | ${run_kraken_fee['ev_per_trade']:.2f} | |",
        f"| Trades/day | {run_mexc['trades_per_day']:.2f} | {run_kraken_fee['trades_per_day']:.2f} | |",
        f"",
        f"## Window Split (MEXC 10bps)",
        f"",
    ]

    ws = analysis["window_split_mexc_10bps"]
    if "windows" in ws:
        md_lines.append("| Window | Trades | PF | PnL | WR |")
        md_lines.append("|--------|--------|----|-----|----|")
        for name in ["early", "mid", "late"]:
            w = ws["windows"].get(name, {})
            md_lines.append(
                f"| {name} | {w.get('trades', 0)} | {w.get('pf', 0):.4f} | "
                f"${w.get('pnl', 0):+,.2f} | {w.get('wr', 0):.1f}% |"
            )
        md_lines.append(f"")
        md_lines.append(f"**Windows profitable**: {ws['windows_profitable']}/3 — "
                        f"{'PASS' if ws['pass'] else 'FAIL'}")

    md_lines.extend([
        f"",
        f"## Exit Attribution (MEXC 10bps)",
        f"",
        f"| Reason | Class | Count | PnL | WR |",
        f"|--------|-------|-------|-----|----|",
    ])
    for reason, stats in sorted(analysis["exit_attribution_mexc_10bps"].items()):
        md_lines.append(
            f"| {reason} | {stats['class']} | {stats['count']} | "
            f"${stats['pnl']:+,.2f} | {stats['wr']:.1f}% |"
        )

    md_lines.extend([
        f"",
        f"## Bootstrap MC (MEXC 10bps)",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
    ])
    boot = analysis["bootstrap_mexc_10bps"]
    if "error" not in boot:
        md_lines.extend([
            f"| Resamples | {boot['n_resamples']} |",
            f"| Median PF | {boot['median_pf']:.4f} |",
            f"| P5 PF | {boot['p5_pf']:.4f} |",
            f"| P95 PF | {boot['p95_pf']:.4f} |",
            f"| % Profitable | {boot['pct_profitable']:.1f}% |",
            f"| Pass | {'YES' if boot['pass'] else 'NO'} |",
        ])

    md_lines.extend([
        f"",
        f"## Top-10 Concentration (MEXC 10bps)",
        f"",
    ])
    t10 = analysis["top10_mexc_10bps"]
    if t10:
        md_lines.extend([
            f"- Top-10 PnL share: {t10['top10_pnl_share']:.1%}",
            f"- Top-10 unique coins: {t10['top10_coins']} / {t10['total_coins']}",
        ])

    # Kraken delta
    kd = analysis.get("kraken_delta")
    if kd:
        md_lines.extend([
            f"",
            f"## MEXC vs Kraken Delta",
            f"",
            f"| Metric | MEXC (10bps) | Kraken (26bps) |",
            f"|--------|-------------|----------------|",
            f"| PF | {kd['mexc_pf']:.4f} | {kd['kraken_pf']:.4f} |",
            f"| Trades | {kd['mexc_trades']} | {kd['kraken_trades']} |",
            f"| DD | {kd['mexc_dd']:.1f}% | {kd['kraken_dd']:.1f}% |",
            f"",
            f"**Note**: {kd['note']}",
        ])

    md_path = REPORT_DIR / "mexc_041_portability_001.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  MD: {md_path}")

    # Scoreboard MD
    sb_md_lines = [
        f"# MEXC Portability Scoreboard — Config 041",
        f"",
        f"**Date**: {timestamp[:10]} | **Git**: {git_hash}",
        f"",
        f"| Run | Trades | PF | PnL | WR | DD | T/day | Window | Boot |",
        f"|-----|--------|----|-----|----|----|-------|--------|------|",
    ]
    for cfg in scoreboard["configs"]:
        wp = "PASS" if cfg["window_pass"] else "FAIL"
        bp = "PASS" if cfg["boot_pass"] else "FAIL"
        sb_md_lines.append(
            f"| {cfg['label']} | {cfg['trades']} | {cfg['pf']:.4f} | "
            f"${cfg['pnl']:+,.2f} | {cfg['wr']:.1f}% | {cfg['dd']:.1f}% | "
            f"{cfg['trades_per_day']:.2f} | {wp} | {bp} |"
        )

    sb_md = REPORT_DIR / "mexc_041_portability_scoreboard_001.md"
    with open(sb_md, "w") as f:
        f.write("\n".join(sb_md_lines) + "\n")
    print(f"  Scoreboard MD: {sb_md}")


# ===========================================================================
# Phase 8: Register dataset in registry.json
# ===========================================================================

def phase8_register_dataset(sha256: str, size_bytes: int, n_coins: int, stats: dict):
    """Register v2 dataset in registry.json."""
    print(f"\n{'=' * 70}")
    print(f"  PHASE 8: Register Dataset")
    print(f"{'=' * 70}")

    with open(REGISTRY_PATH) as f:
        registry = json.load(f)

    # Check if v2 already exists
    for entry in registry["datasets"]:
        if entry["id"] == "ohlcv_4h_mexc_spot_usdt_v2":
            print("  Dataset already registered, updating...")
            entry["sha256"] = sha256
            entry["size_bytes"] = size_bytes
            entry["coins"] = n_coins
            entry["bars_median"] = stats.get("bars_median", 0)
            break
    else:
        # Add new entry
        new_entry = {
            "id": "ohlcv_4h_mexc_spot_usdt_v2",
            "description": f"MEXC SPOT 4H candles via CryptoCompare v2 ({n_coins} coins, USDT pairs)",
            "exchange": "mexc",
            "timeframe": "4h",
            "source": "cryptocompare",
            "venue": "proxy",
            "path": None,
            "canonical_path": "derived/candle_cache/mexc/4h/candle_cache_4h_mexc_v2.json",
            "status": "canonical",
            "sha256": sha256,
            "size_bytes": size_bytes,
            "coins": n_coins,
            "bars_median": stats.get("bars_median", 0),
            "fee_model": "mexc_spot_10bps",
            "vwap_note": "VWAP approximated as (H+L+C)/3",
            "note": f"MEXC portability dataset. {stats.get('rejected_bars', 0)} coins rejected (< {stats.get('min_bars_threshold', 360)} bars).",
            "used_by": ["trading_bot_4h"],
            "downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        registry["datasets"].append(new_entry)

    # Also add universe entry
    existing_universe_ids = [u for u in registry.get("universes", {})]
    if "mexc_4h_v2" not in existing_universe_ids:
        registry.setdefault("universes", {})["mexc_4h_v2"] = {
            "description": f"MEXC 4H v2: {n_coins} coins, ≥{stats.get('min_bars_threshold', 360)} bars",
            "exchange": "mexc",
            "coins": n_coins,
            "min_bars": stats.get("min_bars_threshold", 360),
            "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        }

    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"  Registry updated: {REGISTRY_PATH}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="MEXC Portability Test — Config 041")
    parser.add_argument("--skip-universe", action="store_true",
                        help="Skip Phase 1 (universe already built)")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip Phase 2 (data already downloaded)")
    parser.add_argument("--max-coins", type=int, default=DEFAULT_MAX_COINS,
                        help=f"Max coins for universe (default: {DEFAULT_MAX_COINS})")
    parser.add_argument("--min-bars", type=int, default=DEFAULT_MIN_BARS_FILTER,
                        help=f"Min bars for post-download filtering (default: {DEFAULT_MIN_BARS_FILTER})")
    args = parser.parse_args()

    t_start = time.time()
    print("=" * 70)
    print("  MEXC PORTABILITY TEST — Config 041")
    print("  Vol Capitulation 3x BBlow RSI40 + DC hybrid_notrl exits")
    print(f"  Start: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    # Kraken reference (from Sprint 4 truth-pass)
    kraken_ref = {
        "pf": 1.4058,
        "trades": 216,
        "dd": 36.37,
        "pnl": 3349.79,
        "wr": 54.63,
    }

    # Phase 1: Universe
    if args.skip_universe and V2_UNIVERSE_FILE.exists():
        print(f"\n  [SKIP] Phase 1: Using existing universe {V2_UNIVERSE_FILE}")
    else:
        phase1_build_universe(max_coins=args.max_coins)

    # Phase 2: Download
    if args.skip_download and V2_OUTPUT_FILE.exists():
        print(f"\n  [SKIP] Phase 2: Using existing data {V2_OUTPUT_FILE}")
    else:
        if not V2_UNIVERSE_FILE.exists():
            print("ERROR: Universe file not found. Run without --skip-universe first.")
            sys.exit(1)
        phase2_download(V2_UNIVERSE_FILE)

    # Phase 3: Build universe from actual downloaded data
    coins, universe_stats = phase3_build_universe_from_data(
        V2_OUTPUT_FILE, min_bars=args.min_bars,
    )

    if not coins:
        print("ERROR: No coins in universe after filtering.")
        sys.exit(1)

    # Load data once
    print(f"\n  Loading dataset: {V2_OUTPUT_FILE}")
    with open(V2_OUTPUT_FILE) as f:
        data = json.load(f)

    # SHA256 + size
    data_sha256 = _sha256(V2_OUTPUT_FILE)
    data_size_bytes = V2_OUTPUT_FILE.stat().st_size

    # Phase 4: Run with MEXC fees
    run_mexc = phase4_run_backtest(data, coins, MEXC_FEE, "mexc_spot_10bps")

    # Phase 5: Run with Kraken fees (fee isolation)
    run_kraken_fee = phase4_run_backtest(data, coins, KRAKEN_FEE, "kraken_spot_26bps")

    # Phase 6: Analysis
    analysis = phase6_analysis(run_mexc, run_kraken_fee, kraken_ref=kraken_ref)

    # Phase 7: Reports
    phase7_write_reports(run_mexc, run_kraken_fee, analysis, universe_stats,
                         data_sha256, data_size_bytes)

    # Phase 8: Register dataset
    phase8_register_dataset(data_sha256, data_size_bytes, len(coins), universe_stats)

    # Final summary
    total_time = (time.time() - t_start) / 60
    print(f"\n{'=' * 70}")
    print(f"  PIPELINE COMPLETE — {total_time:.1f} min")
    print(f"{'=' * 70}")
    print(f"  MEXC 10bps: PF={run_mexc['pf']:.4f}, {run_mexc['trades']} trades, "
          f"${run_mexc['pnl']:+,.2f}, DD={run_mexc['dd']:.1f}%")
    print(f"  MEXC 26bps: PF={run_kraken_fee['pf']:.4f}, {run_kraken_fee['trades']} trades, "
          f"${run_kraken_fee['pnl']:+,.2f}, DD={run_kraken_fee['dd']:.1f}%")
    print(f"  Trades/day: {run_mexc['trades_per_day']:.2f}")
    print(f"  Window split (10bps): {'PASS' if analysis['window_split_mexc_10bps']['pass'] else 'FAIL'}")
    print(f"  Bootstrap (10bps): {'PASS' if analysis['bootstrap_mexc_10bps'].get('pass', False) else 'FAIL'}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
