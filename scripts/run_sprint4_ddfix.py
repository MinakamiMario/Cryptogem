#!/usr/bin/env python3
"""
Sprint 4 DD-Fix -- Risk wrappers for drawdown reduction.

Post-hoc equity simulation that applies risk wrappers to existing Sprint 4
trade lists WITHOUT changing entry/exit logic.

4 wrapper strategies:
  1. DD Throttle    -- reduce position size when in drawdown
  2. Vol Scaling    -- size inversely proportional to recent ATR
  3. Adaptive MaxPos -- reduce max concurrent positions based on DD
  4. Cooldown Ext   -- extend cooldown after consecutive stops

Output:
  reports/4h/sprint4_ddfix_scoreboard.json
  reports/4h/sprint4_ddfix_scoreboard.md

Usage:
    python3 scripts/run_sprint4_ddfix.py
    python3 scripts/run_sprint4_ddfix.py --only 041,032
    python3 scripts/run_sprint4_ddfix.py --strategy dd_throttle
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KRAKEN_FEE = 0.0026
INITIAL_CAPITAL = 2000
COOLDOWN_AFTER_STOP = 8  # engine default
GIT_HASH = "9a606d9"  # frozen Sprint 4 hash

DEFAULT_OUTPUT = REPO_ROOT / "reports" / "4h"
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"

# Top-5 configs from Sprint 4 (by PF, DD > 40%)
TOP5 = [
    "sprint4_041_h4s4g05_vol3x_bblow_rsi40",
    "sprint4_032_h4s4f02_z2.5_dclow_rsi40",
    "sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35",
    "sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5",
    "sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol",
]

# Wrapper grids
DD_THROTTLE_GRID = [
    {"dd_threshold": 0.10, "size_scale": 0.50},
    {"dd_threshold": 0.15, "size_scale": 0.50},
    {"dd_threshold": 0.20, "size_scale": 0.50},
    {"dd_threshold": 0.10, "size_scale": 0.25},
    {"dd_threshold": 0.15, "size_scale": 0.25},
]

VOL_SCALE_GRID = [
    {"atr_lookback": 14, "target_percentile": 25},
    {"atr_lookback": 14, "target_percentile": 50},
]

ADAPTIVE_MAXPOS_GRID = [
    {"dd_10": 3, "dd_20": 2, "dd_above": 1},  # single config
]

COOLDOWN_EXT_GRID = [
    {"cooldown_bars": 12},
    {"cooldown_bars": 16},
    {"cooldown_bars": 20},
]

STOP_REASONS = {"FIXED STOP", "HARD STOP"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _load_result(config_id: str) -> Optional[dict]:
    """Load pre-existing result from Sprint 4 sweep."""
    result_dir = DEFAULT_OUTPUT / f"{config_id}_{GIT_HASH}"
    results_path = result_dir / "results.json"
    if results_path.exists():
        with open(results_path) as f:
            return json.load(f)
    return None


def _compute_metrics(trades: list[dict], initial_capital: float = INITIAL_CAPITAL) -> dict:
    """Compute PF, DD, P&L, trade count from a list of (possibly modified) trades.

    Walks through trades chronologically (sorted by entry_bar, then exit_bar),
    tracking equity and drawdown.

    Each trade dict must have: pnl, entry_bar, exit_bar, size.
    """
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
    pf = wins_sum / losses_sum if losses_sum > 0 else (float("inf") if wins_sum > 0 else 0.0)
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


def _sort_trades(trades: list[dict]) -> list[dict]:
    """Sort trades chronologically by entry_bar, then exit_bar."""
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


# ---------------------------------------------------------------------------
# Wrapper 1: DD Throttle (size-based)
# ---------------------------------------------------------------------------

def apply_dd_throttle(
    trades: list[dict],
    dd_threshold: float,
    size_scale: float,
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict]:
    """Scale position size (and P&L proportionally) when in drawdown.

    Size-based: all trades are kept, but P&L is scaled down when equity
    is in drawdown beyond dd_threshold.
    """
    sorted_trades = _sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital

    for t in sorted_trades:
        # Compute current DD
        if peak_equity > 0:
            current_dd = (peak_equity - equity) / peak_equity
        else:
            current_dd = 0.0

        # Determine scale factor
        if current_dd >= dd_threshold:
            scale = size_scale
        else:
            scale = 1.0

        # Scale P&L proportionally
        adjusted_pnl = t["pnl"] * scale
        adjusted_size = t["size"] * scale

        new_trade = dict(t)
        new_trade["pnl"] = adjusted_pnl
        new_trade["size"] = adjusted_size
        new_trade["_scale"] = scale
        result.append(new_trade)

        # Update equity
        equity += adjusted_pnl
        if equity > peak_equity:
            peak_equity = equity

    return result


# ---------------------------------------------------------------------------
# Wrapper 2: Volatility Scaling (size-based, needs ATR data)
# ---------------------------------------------------------------------------

def apply_vol_scaling(
    trades: list[dict],
    atr_by_pair: dict,
    target_percentile: int = 50,
    atr_lookback: int = 14,
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict]:
    """Scale position size inversely proportional to recent ATR.

    size = base_size * (target_atr / current_atr), capped at [0.25, 2.0].

    atr_by_pair: {pair: [atr_value_per_bar, ...]}
    """
    # Compute target_atr as the given percentile of all ATR values across trades
    atr_at_entry = []
    for t in trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])
        if bar < len(atr_arr) and atr_arr[bar] is not None:
            atr_at_entry.append(atr_arr[bar])

    if not atr_at_entry:
        # No ATR data: return trades unchanged
        return list(trades)

    atr_at_entry_sorted = sorted(atr_at_entry)
    idx = max(0, int(len(atr_at_entry_sorted) * target_percentile / 100) - 1)
    target_atr = atr_at_entry_sorted[idx]

    if target_atr <= 0:
        return list(trades)

    sorted_trades = _sort_trades(trades)
    result = []

    for t in sorted_trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])

        if bar < len(atr_arr) and atr_arr[bar] is not None and atr_arr[bar] > 0:
            current_atr = atr_arr[bar]
            scale = target_atr / current_atr
            scale = max(0.25, min(2.0, scale))  # clamp
        else:
            scale = 1.0

        adjusted_pnl = t["pnl"] * scale
        adjusted_size = t["size"] * scale

        new_trade = dict(t)
        new_trade["pnl"] = adjusted_pnl
        new_trade["size"] = adjusted_size
        new_trade["_scale"] = scale
        result.append(new_trade)

    return result


# ---------------------------------------------------------------------------
# Wrapper 3: Adaptive MaxPos (trade-skipping)
# ---------------------------------------------------------------------------

def apply_adaptive_maxpos(
    trades: list[dict],
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict]:
    """Reduce max concurrent positions based on current drawdown.

    DD < 10%:  max_pos = 3
    DD 10-20%: max_pos = 2
    DD > 20%:  max_pos = 1

    Walks through trades chronologically, tracking simulated open positions
    by entry_bar/exit_bar. Skips trades that would exceed adaptive max_pos.
    """
    sorted_trades = _sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital
    # Track open positions as (entry_bar, exit_bar) intervals
    open_positions: list[tuple[int, int]] = []

    for t in sorted_trades:
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]

        # Close positions that have exited by this entry_bar
        open_positions = [(eb, xb) for eb, xb in open_positions if xb > entry_bar]

        # Compute current DD
        if peak_equity > 0:
            current_dd = (peak_equity - equity) / peak_equity
        else:
            current_dd = 0.0

        # Adaptive max_pos
        if current_dd < 0.10:
            max_pos = 3
        elif current_dd < 0.20:
            max_pos = 2
        else:
            max_pos = 1

        # Check if we can open this trade
        if len(open_positions) >= max_pos:
            continue  # skip this trade

        # Accept the trade
        open_positions.append((entry_bar, exit_bar))
        result.append(dict(t))

        # Update equity
        equity += t["pnl"]
        if equity > peak_equity:
            peak_equity = equity

    return result


# ---------------------------------------------------------------------------
# Wrapper 4: Extended Cooldown After Stop (trade-skipping)
# ---------------------------------------------------------------------------

def apply_cooldown_ext(
    trades: list[dict],
    cooldown_bars: int = 12,
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict]:
    """Extend cooldown after stopout. Default engine cooldown is 8 bars;
    this extends to 12, 16, or 20 bars.

    Tracks per-pair last stop exit_bar. Skips any trade that enters
    within cooldown_bars of the last stop for that pair.
    """
    sorted_trades = _sort_trades(trades)
    result = []
    # Track last stop bar per pair
    last_stop_bar: dict[str, int] = {}

    for t in sorted_trades:
        pair = t["pair"]
        entry_bar = t["entry_bar"]

        # Check cooldown (only extended cooldown matters, not normal cooldown)
        if pair in last_stop_bar:
            bars_since_stop = entry_bar - last_stop_bar[pair]
            if bars_since_stop < cooldown_bars:
                continue  # skip: still in extended cooldown

        result.append(dict(t))

        # Track if this trade was a stop
        if t["reason"] in STOP_REASONS:
            last_stop_bar[pair] = t["exit_bar"]

    return result


# ---------------------------------------------------------------------------
# Wrapper dispatcher
# ---------------------------------------------------------------------------

def run_wrapper(
    wrapper_name: str,
    trades: list[dict],
    params: dict,
    atr_by_pair: Optional[dict] = None,
    initial_capital: float = INITIAL_CAPITAL,
) -> list[dict]:
    """Apply a named wrapper with given params to a trade list."""
    if wrapper_name == "dd_throttle":
        return apply_dd_throttle(
            trades,
            dd_threshold=params["dd_threshold"],
            size_scale=params["size_scale"],
            initial_capital=initial_capital,
        )
    elif wrapper_name == "vol_scale":
        if atr_by_pair is None:
            raise ValueError("vol_scale requires atr_by_pair")
        return apply_vol_scaling(
            trades,
            atr_by_pair=atr_by_pair,
            target_percentile=params["target_percentile"],
            atr_lookback=params["atr_lookback"],
            initial_capital=initial_capital,
        )
    elif wrapper_name == "adaptive_maxpos":
        return apply_adaptive_maxpos(
            trades,
            initial_capital=initial_capital,
        )
    elif wrapper_name == "cooldown_ext":
        return apply_cooldown_ext(
            trades,
            cooldown_bars=params["cooldown_bars"],
            initial_capital=initial_capital,
        )
    else:
        raise ValueError(f"Unknown wrapper: {wrapper_name}")


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def classify_result(dd: float, pf: float) -> str:
    """Classify wrapped result by DD/PF thresholds."""
    if dd <= 20.0 and pf >= 1.15:
        return "DEPLOY_CANDIDATE"
    elif dd <= 25.0 and pf >= 1.10:
        return "INVESTIGATE"
    else:
        return "NOT_VIABLE"


# ---------------------------------------------------------------------------
# Load ATR data for vol_scale wrapper
# ---------------------------------------------------------------------------

def _load_atr_data(config_ids: list[str]) -> dict:
    """Load ATR data for all pairs that appear in trades.

    Requires loading the full dataset and precomputing indicators.
    Only called if vol_scale wrapper is needed.
    """
    import importlib

    _data_resolver = importlib.import_module("strategies.4h.data_resolver")
    _sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")

    resolve_dataset = _data_resolver.resolve_dataset
    precompute_all = _sprint2_indicators.precompute_all

    # Collect all unique pairs from trade lists
    all_pairs = set()
    for config_id in config_ids:
        result = _load_result(config_id)
        if result and "trades" in result:
            for t in result["trades"]:
                all_pairs.add(t["pair"])

    if not all_pairs:
        return {}

    print(f"  Loading ATR data for {len(all_pairs)} pairs...")
    t0 = time.time()

    # Load dataset
    dataset_path = resolve_dataset(DEFAULT_DATASET)
    with open(dataset_path) as f:
        data = json.load(f)

    # Filter to relevant pairs
    coins = sorted(all_pairs & set(data.keys()))
    print(f"  Found {len(coins)} pairs in dataset")

    # Precompute indicators
    indicators = precompute_all(data, coins)
    print(f"  Indicators precomputed in {time.time() - t0:.1f}s")

    # Extract ATR arrays
    atr_by_pair = {}
    for pair in coins:
        ind = indicators.get(pair)
        if ind and "atr" in ind:
            atr_by_pair[pair] = ind["atr"]

    return atr_by_pair


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def run_all_wrappers(
    config_ids: list[str],
    strategies: Optional[list[str]] = None,
) -> list[dict]:
    """Run all risk wrappers on all configs. Returns list of result dicts."""

    all_strategies = strategies or ["dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext"]

    # Pre-load ATR data if vol_scale is requested
    atr_by_pair = None
    if "vol_scale" in all_strategies:
        atr_by_pair = _load_atr_data(config_ids)

    results = []
    total = 0

    for config_id in config_ids:
        print(f"\n{'='*72}")
        print(f"  Config: {config_id}")
        print(f"{'='*72}")

        raw_result = _load_result(config_id)
        if raw_result is None:
            print(f"  SKIP: no result file found for {config_id}")
            continue

        trades = raw_result.get("trades", [])
        if not trades:
            print(f"  SKIP: no trades in {config_id}")
            continue

        # Compute original metrics
        sorted_trades = _sort_trades(trades)
        orig_metrics = _compute_metrics(sorted_trades)
        orig_summary = raw_result.get("summary", {})

        print(f"  Original: {orig_metrics['trades']} trades | "
              f"PF {orig_metrics['pf']:.2f} | DD {orig_metrics['dd']:.1f}% | "
              f"P&L ${orig_metrics['pnl']:+,.2f}")
        print(f"  (Stored): {orig_summary.get('trades', '?')} trades | "
              f"PF {orig_summary.get('pf', '?')} | DD {orig_summary.get('dd', '?')}% | "
              f"P&L ${orig_summary.get('pnl', '?'):+,.2f}")

        # Run each wrapper strategy
        for strategy in all_strategies:
            if strategy == "dd_throttle":
                grid = DD_THROTTLE_GRID
            elif strategy == "vol_scale":
                grid = VOL_SCALE_GRID
            elif strategy == "adaptive_maxpos":
                grid = ADAPTIVE_MAXPOS_GRID
            elif strategy == "cooldown_ext":
                grid = COOLDOWN_EXT_GRID
            else:
                continue

            for params in grid:
                total += 1
                try:
                    wrapped_trades = run_wrapper(
                        strategy, sorted_trades, params,
                        atr_by_pair=atr_by_pair,
                    )
                    wrapped_metrics = _compute_metrics(wrapped_trades)
                except Exception as e:
                    print(f"    ERROR [{strategy}] {params}: {e}")
                    continue

                # Compute deltas
                dd_reduction_pct = (
                    (orig_metrics["dd"] - wrapped_metrics["dd"]) / orig_metrics["dd"] * 100
                    if orig_metrics["dd"] > 0 else 0.0
                )
                pf_change_pct = (
                    (wrapped_metrics["pf"] - orig_metrics["pf"]) / orig_metrics["pf"] * 100
                    if orig_metrics["pf"] > 0 else 0.0
                )
                pnl_change_pct = (
                    (wrapped_metrics["pnl"] - orig_metrics["pnl"]) / abs(orig_metrics["pnl"]) * 100
                    if abs(orig_metrics["pnl"]) > 0 else 0.0
                )

                verdict = classify_result(wrapped_metrics["dd"], wrapped_metrics["pf"])

                entry = {
                    "config_id": config_id,
                    "wrapper": strategy,
                    "params": params,
                    "original": {
                        "trades": orig_metrics["trades"],
                        "pf": orig_metrics["pf"],
                        "pnl": orig_metrics["pnl"],
                        "dd": orig_metrics["dd"],
                        "wr": orig_metrics["wr"],
                    },
                    "wrapped": {
                        "trades": wrapped_metrics["trades"],
                        "pf": wrapped_metrics["pf"],
                        "pnl": wrapped_metrics["pnl"],
                        "dd": wrapped_metrics["dd"],
                        "wr": wrapped_metrics["wr"],
                    },
                    "dd_reduction_pct": round(dd_reduction_pct, 2),
                    "pf_change_pct": round(pf_change_pct, 2),
                    "pnl_change_pct": round(pnl_change_pct, 2),
                    "verdict": verdict,
                }
                results.append(entry)

                # Print result
                mark = verdict[:6]
                params_str = json.dumps(params, separators=(",", ":"))
                print(
                    f"  [{mark:>13s}] {strategy:<16s} {params_str:<45s} "
                    f"| DD {wrapped_metrics['dd']:5.1f}% ({dd_reduction_pct:+5.1f}%) "
                    f"| PF {wrapped_metrics['pf']:5.2f} ({pf_change_pct:+5.1f}%) "
                    f"| Tr {wrapped_metrics['trades']:3d} "
                    f"| P&L ${wrapped_metrics['pnl']:+8.2f}"
                )

    print(f"\n  Total combos evaluated: {total}")
    return results


# ---------------------------------------------------------------------------
# Scoreboard generation
# ---------------------------------------------------------------------------

def write_scoreboards(
    results: list[dict],
    output_dir: Path,
    git_hash: str,
    dataset_id: str,
):
    """Write JSON + MD scoreboards, sorted by dd_reduction (PF >= 1.10 filter)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sort: viable first (by dd_reduction desc), then not-viable
    viable = [r for r in results if r["wrapped"]["pf"] >= 1.10]
    non_viable = [r for r in results if r["wrapped"]["pf"] < 1.10]
    viable.sort(key=lambda r: -r["dd_reduction_pct"])
    non_viable.sort(key=lambda r: -r["dd_reduction_pct"])

    all_sorted = viable + non_viable

    # JSON scoreboard
    scoreboard = {
        "experiment_id": "sprint4_ddfix",
        "dataset_id": dataset_id,
        "git_hash": git_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "initial_capital": INITIAL_CAPITAL,
        "fee_bps": round(KRAKEN_FEE * 10000, 1),
        "total_combos": len(results),
        "deploy_candidates": sum(1 for r in results if r["verdict"] == "DEPLOY_CANDIDATE"),
        "investigate": sum(1 for r in results if r["verdict"] == "INVESTIGATE"),
        "not_viable": sum(1 for r in results if r["verdict"] == "NOT_VIABLE"),
        "entries": all_sorted,
    }
    json_path = output_dir / "sprint4_ddfix_scoreboard.json"
    with open(json_path, "w") as f:
        json.dump(scoreboard, f, indent=2, default=str)
    print(f"\n  Scoreboard JSON: {json_path}")

    # MD scoreboard
    md_lines = [
        "# Sprint 4 DD-Fix Scoreboard -- Risk Wrappers for Drawdown Reduction",
        "",
        f"- **Dataset**: {dataset_id}",
        f"- **Git**: {git_hash}",
        f"- **Generated**: {scoreboard['generated_at']}",
        f"- **Initial capital**: ${INITIAL_CAPITAL:,}",
        f"- **Fee**: {KRAKEN_FEE * 10000:.1f} bps per side",
        f"- **Total combos**: {len(results)}",
        f"- **DEPLOY_CANDIDATE** (DD <= 20%, PF >= 1.15): {scoreboard['deploy_candidates']}",
        f"- **INVESTIGATE** (DD <= 25%, PF >= 1.10): {scoreboard['investigate']}",
        f"- **NOT_VIABLE**: {scoreboard['not_viable']}",
        "",
        "## Methodology",
        "",
        "Post-hoc equity simulation applying risk wrappers to existing trade lists.",
        "Entry and exit logic are UNCHANGED. Only sizing or trade admission is modified.",
        "",
        "### Wrappers",
        "1. **DD Throttle**: Scale position size by factor when DD > threshold",
        "2. **Vol Scaling**: Size inversely proportional to ATR (capped 0.25x-2.0x)",
        "3. **Adaptive MaxPos**: Reduce max concurrent positions (3/2/1) by DD level",
        "4. **Cooldown Ext**: Extend post-stop cooldown beyond default 8 bars",
        "",
    ]

    # Deploy candidates section
    deploy = [r for r in all_sorted if r["verdict"] == "DEPLOY_CANDIDATE"]
    if deploy:
        md_lines.append("## DEPLOY CANDIDATES (DD <= 20%, PF >= 1.15)")
        md_lines.append("")
        md_lines.append(
            "| Config | Wrapper | Params | Orig DD | New DD | DD delta | "
            "Orig PF | New PF | PF delta | Trades | P&L |"
        )
        md_lines.append(
            "|--------|---------|--------|---------|--------|----------|"
            "---------|--------|----------|--------|-----|"
        )
        for r in deploy:
            params_str = _params_short(r["wrapper"], r["params"])
            md_lines.append(
                f"| {r['config_id']} | {r['wrapper']} | {params_str} "
                f"| {r['original']['dd']:.1f}% | {r['wrapped']['dd']:.1f}% "
                f"| {r['dd_reduction_pct']:+.1f}% "
                f"| {r['original']['pf']:.2f} | {r['wrapped']['pf']:.2f} "
                f"| {r['pf_change_pct']:+.1f}% "
                f"| {r['wrapped']['trades']} | ${r['wrapped']['pnl']:+,.2f} |"
            )
        md_lines.append("")

    # Investigate section
    investigate = [r for r in all_sorted if r["verdict"] == "INVESTIGATE"]
    if investigate:
        md_lines.append("## INVESTIGATE (DD <= 25%, PF >= 1.10)")
        md_lines.append("")
        md_lines.append(
            "| Config | Wrapper | Params | Orig DD | New DD | DD delta | "
            "Orig PF | New PF | PF delta | Trades | P&L |"
        )
        md_lines.append(
            "|--------|---------|--------|---------|--------|----------|"
            "---------|--------|----------|--------|-----|"
        )
        for r in investigate:
            params_str = _params_short(r["wrapper"], r["params"])
            md_lines.append(
                f"| {r['config_id']} | {r['wrapper']} | {params_str} "
                f"| {r['original']['dd']:.1f}% | {r['wrapped']['dd']:.1f}% "
                f"| {r['dd_reduction_pct']:+.1f}% "
                f"| {r['original']['pf']:.2f} | {r['wrapped']['pf']:.2f} "
                f"| {r['pf_change_pct']:+.1f}% "
                f"| {r['wrapped']['trades']} | ${r['wrapped']['pnl']:+,.2f} |"
            )
        md_lines.append("")

    # Full table
    md_lines.append("## All Combos (sorted by DD reduction, PF >= 1.10 first)")
    md_lines.append("")
    md_lines.append(
        "| # | Verdict | Config | Wrapper | Params | Orig DD | New DD | DD delta | "
        "Orig PF | New PF | Trades | P&L |"
    )
    md_lines.append(
        "|---|---------|--------|---------|--------|---------|--------|----------|"
        "---------|--------|--------|-----|"
    )
    for i, r in enumerate(all_sorted, 1):
        params_str = _params_short(r["wrapper"], r["params"])
        md_lines.append(
            f"| {i} | {r['verdict']} | {r['config_id']} | {r['wrapper']} | {params_str} "
            f"| {r['original']['dd']:.1f}% | {r['wrapped']['dd']:.1f}% "
            f"| {r['dd_reduction_pct']:+.1f}% "
            f"| {r['original']['pf']:.2f} | {r['wrapped']['pf']:.2f} "
            f"| {r['wrapped']['trades']} | ${r['wrapped']['pnl']:+,.2f} |"
        )

    # Strategy summary
    md_lines.append("")
    md_lines.append("## Strategy Summary")
    md_lines.append("")
    md_lines.append(
        "| Strategy | Combos | Deploy | Investigate | Avg DD Reduction | Avg PF Change |"
    )
    md_lines.append(
        "|----------|--------|--------|-------------|------------------|---------------|"
    )
    for strat in ["dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext"]:
        strat_results = [r for r in results if r["wrapper"] == strat]
        if not strat_results:
            continue
        n_deploy = sum(1 for r in strat_results if r["verdict"] == "DEPLOY_CANDIDATE")
        n_invest = sum(1 for r in strat_results if r["verdict"] == "INVESTIGATE")
        avg_dd_red = sum(r["dd_reduction_pct"] for r in strat_results) / len(strat_results)
        avg_pf_chg = sum(r["pf_change_pct"] for r in strat_results) / len(strat_results)
        md_lines.append(
            f"| {strat} | {len(strat_results)} | {n_deploy} | {n_invest} "
            f"| {avg_dd_red:+.1f}% | {avg_pf_chg:+.1f}% |"
        )

    md_path = output_dir / "sprint4_ddfix_scoreboard.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  Scoreboard MD:  {md_path}")


def _params_short(wrapper: str, params: dict) -> str:
    """Human-readable short param string."""
    if wrapper == "dd_throttle":
        return f"dd>{params['dd_threshold']*100:.0f}%,scale={params['size_scale']}"
    elif wrapper == "vol_scale":
        return f"atr{params['atr_lookback']},pctl={params['target_percentile']}"
    elif wrapper == "adaptive_maxpos":
        return "3/2/1 by DD"
    elif wrapper == "cooldown_ext":
        return f"cd={params['cooldown_bars']}bars"
    else:
        return json.dumps(params, separators=(",", ":"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sprint 4 DD-Fix: Risk wrappers for drawdown reduction"
    )
    parser.add_argument(
        "--only", default=None,
        help="Comma-separated config suffixes to run (e.g., 041,032)"
    )
    parser.add_argument(
        "--strategy", default=None,
        help="Run only one wrapper strategy (dd_throttle|vol_scale|adaptive_maxpos|cooldown_ext)"
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT),
        help="Output directory"
    )
    args = parser.parse_args()

    git_hash = _git_hash()
    output_dir = Path(args.output_dir)

    print(f"\n{'='*72}")
    print(f"  Sprint 4 DD-Fix -- Risk Wrappers for Drawdown Reduction")
    print(f"{'='*72}")
    print(f"  Git: {git_hash}")
    print(f"  Dataset: {DEFAULT_DATASET}")
    print(f"  Initial capital: ${INITIAL_CAPITAL:,}")
    print(f"  Fee: {KRAKEN_FEE * 10000:.1f} bps per side")

    # Determine configs to process
    config_ids = list(TOP5)
    if args.only:
        suffixes = [s.strip() for s in args.only.split(",")]
        config_ids = [
            c for c in TOP5
            if any(f"_{s}_" in c or c.endswith(f"_{s}") or c.split("_")[1] == s
                   for s in suffixes)
        ]
        # Also try matching by the 3-digit index (e.g., "041")
        if not config_ids:
            config_ids = [
                c for c in TOP5
                if any(c.split("_")[1] == s.zfill(3) for s in suffixes)
            ]
        print(f"  Filtered configs: {config_ids}")

    if not config_ids:
        print("  ERROR: No matching configs found")
        sys.exit(1)

    print(f"  Configs: {len(config_ids)}")
    for cid in config_ids:
        print(f"    - {cid}")

    # Determine strategies
    strategies = None
    if args.strategy:
        valid = {"dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext"}
        if args.strategy not in valid:
            print(f"  ERROR: Unknown strategy '{args.strategy}'. Valid: {valid}")
            sys.exit(1)
        strategies = [args.strategy]
        print(f"  Strategy filter: {args.strategy}")

    # Run
    t0 = time.time()
    results = run_all_wrappers(config_ids, strategies)
    elapsed = time.time() - t0

    if not results:
        print("\n  No results generated.")
        return

    # Write scoreboards
    write_scoreboards(results, output_dir, git_hash, DEFAULT_DATASET)

    # Summary
    n_deploy = sum(1 for r in results if r["verdict"] == "DEPLOY_CANDIDATE")
    n_invest = sum(1 for r in results if r["verdict"] == "INVESTIGATE")
    n_noviable = sum(1 for r in results if r["verdict"] == "NOT_VIABLE")

    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")
    print(f"  Total combos: {len(results)}")
    print(f"  DEPLOY_CANDIDATE: {n_deploy}")
    print(f"  INVESTIGATE:      {n_invest}")
    print(f"  NOT_VIABLE:       {n_noviable}")
    print(f"  Elapsed: {elapsed:.1f}s")

    # Best combo by DD reduction (with PF >= 1.10)
    viable = [r for r in results if r["wrapped"]["pf"] >= 1.10]
    if viable:
        best = max(viable, key=lambda r: r["dd_reduction_pct"])
        print(f"\n  Best DD reduction (PF >= 1.10):")
        print(f"    Config:  {best['config_id']}")
        print(f"    Wrapper: {best['wrapper']}")
        print(f"    Params:  {best['params']}")
        print(f"    DD:      {best['original']['dd']:.1f}% -> {best['wrapped']['dd']:.1f}% "
              f"({best['dd_reduction_pct']:+.1f}%)")
        print(f"    PF:      {best['original']['pf']:.2f} -> {best['wrapped']['pf']:.2f}")
        print(f"    P&L:     ${best['original']['pnl']:+,.2f} -> ${best['wrapped']['pnl']:+,.2f}")


if __name__ == "__main__":
    main()
