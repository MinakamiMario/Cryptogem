#!/usr/bin/env python3
"""
HF Multi-Timeframe Per-Tier Friction Model (v3) -- MTF variant research.

Sprint 2 extension: builds on hf_friction_v2.py per-tier composite backtests
with multi-timeframe support and additional capacity/fee-drag metrics.

Enhancements over v2:
  1. Multi-timeframe: accepts --timeframe 4h (default), 1h, 15m
  2. NEW metric: fee_drag_pct = total_estimated_fees / gross_profit
     Measures how much fees eat into the gross winning P&L.
  3. NEW metric: trades_below_breakeven = count of trades where
     |pnl| < round_trip_fee (fee * 2 * trade_size)
  4. NEW metric: capacity_proxy = avg_trade_size / avg_daily_volume per tier
     Measures how much of daily volume each trade consumes.

Per-tier fee model (per side):
  - Tier 1: KRAKEN_FEE + 5bps  = 0.0031  (liquid, tight spreads)
  - Tier 2: KRAKEN_FEE + 30bps = 0.0056  (mid-cap, wider spreads)

Universe policy: T1+T2 only (Tier 3 excluded per UNIVERSE_POLICY.md).

Usage:
    python strategies/hf/hf_friction_v3.py
    python strategies/hf/hf_friction_v3.py --timeframe 1h
    python strategies/hf/hf_friction_v3.py --timeframe 15m
    python strategies/hf/hf_friction_v3.py --timeframe 4h --universe live

Outputs:
    reports/hf/friction_v3_{tf}_001.json  -- structured results
    reports/hf/friction_v3_{tf}_001.md    -- human-readable report
"""

import sys
import json
import time
import argparse
import statistics
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Path setup (read-only import from trading_bot/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    run_backtest,
    normalize_cfg,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

# Timeframe-aware data files
TF_DATA_FILES = {
    "4h": {
        "tradeable": DATA_DIR / "candle_cache_tradeable.json",
        "live": DATA_DIR / "candle_cache_532.json",
    },
    "1h": {
        "tradeable": DATA_DIR / "candle_cache_1h.json",
        "live": DATA_DIR / "candle_cache_1h.json",
    },
    "15m": {
        "tradeable": DATA_DIR / "candle_cache_15m.json",
        "live": DATA_DIR / "candle_cache_15m.json",
    },
}

TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

# --- Per-tier fee model (per side) ---
# Slippage components (added to KRAKEN_FEE)
SLIPPAGE_TIER1 = 0.0005    # 5 bps
SLIPPAGE_TIER2 = 0.0030    # 30 bps
SLIPPAGE_FLAT  = 0.0020    # 20 bps (Sprint 1 model)

FEE_TIER1 = KRAKEN_FEE + SLIPPAGE_TIER1   # 0.0031
FEE_TIER2 = KRAKEN_FEE + SLIPPAGE_TIER2   # 0.0056
FEE_FLAT  = KRAKEN_FEE + SLIPPAGE_FLAT    # 0.0046

# 2x stress: double the slippage component only
FEE_TIER1_2X = KRAKEN_FEE + SLIPPAGE_TIER1 * 2   # 0.0036
FEE_TIER2_2X = KRAKEN_FEE + SLIPPAGE_TIER2 * 2   # 0.0086

TIER_FEES = {1: FEE_TIER1, 2: FEE_TIER2}
TIER_FEES_2X = {1: FEE_TIER1_2X, 2: FEE_TIER2_2X}
TIER_SLIPPAGE = {1: SLIPPAGE_TIER1, 2: SLIPPAGE_TIER2}
TIER_LABELS = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)"}

# Configs under test
CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 8,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 3.0,
})

GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 10,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 2.5,
})

CONFIGS = {
    "Champion_H2": CHAMPION_H2,
    "GRID_BEST": GRID_BEST,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(timeframe: str, universe: str):
    """Load candle data for given timeframe and return (data_dict, sorted_coins, path_str)."""
    tf_files = TF_DATA_FILES.get(timeframe, TF_DATA_FILES["4h"])
    path = tf_files.get(universe)
    if path is None or not path.exists():
        # Fallback for 4h: try trading_bot cache
        if timeframe == "4h":
            path = TRADING_BOT / "candle_cache_532.json"
        else:
            print(f"ERROR: No data file found for timeframe={timeframe}, universe={universe}")
            print(f"  Expected: {tf_files.get(universe, 'N/A')}")
            print(f"  Run the data downloader for {timeframe} candles first.")
            sys.exit(1)
    if not path.exists():
        print(f"ERROR: Data file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def load_tier_assignments():
    """Load tier coin lists from universe_tiering_001.json.

    Returns tiers dict with keys 1 and 2 only (T3 excluded per UNIVERSE_POLICY).
    """
    if not TIERING_PATH.exists():
        print(f"ERROR: Tiering file not found: {TIERING_PATH}")
        print("  Run: python strategies/hf/hf_universe_tiering.py first")
        sys.exit(1)
    with open(TIERING_PATH) as f:
        tiering = json.load(f)
    tiers = {}
    tb = tiering.get("tier_breakdown", {})
    # T1+T2 only — Tier 3 excluded per UNIVERSE_POLICY.md
    for tier_key in ("1", "2"):
        tiers[int(tier_key)] = tb.get(tier_key, {}).get("coins", [])
    return tiers


def compute_avg_daily_volume(data, coins, timeframe):
    """Compute average daily volume per coin in quote currency.

    Returns dict: {coin: avg_daily_vol}.
    """
    # Bars per day by timeframe
    bars_per_day = {"4h": 6, "1h": 24, "15m": 96}.get(timeframe, 6)

    avg_vols = {}
    for coin in coins:
        candles = data.get(coin, [])
        if not candles:
            avg_vols[coin] = 0.0
            continue
        volumes = [c.get("volume", 0) for c in candles]
        total_vol = sum(volumes)
        n_days = max(1, len(candles) / bars_per_day)
        avg_vols[coin] = total_vol / n_days
    return avg_vols


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_pf(pf):
    """Cap infinite PF at 99.0."""
    if pf == float("inf"):
        return 99.0
    return round(min(pf, 99.0), 2)


def replay_equity_curve(trade_list, initial_capital):
    """
    Replay equity curve from a merged trade_list sorted by entry_bar.

    This correctly computes drawdown and profit factor from aggregated
    per-tier trades by replaying the equity curve chronologically.

    Returns dict: {pnl, pf, dd, trades, wr, final_equity}
    """
    if not trade_list:
        return {
            "pnl": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "trades": 0,
            "wr": 0.0,
            "final_equity": initial_capital,
        }

    # Sort by entry_bar for chronological replay
    sorted_trades = sorted(trade_list, key=lambda t: (t["entry_bar"], t.get("exit_bar", 0)))

    equity = float(initial_capital)
    peak_eq = equity
    max_dd = 0.0

    total_win_pnl = 0.0
    total_loss_pnl = 0.0
    n_wins = 0

    for t in sorted_trades:
        pnl = t["pnl"]
        equity += pnl

        if pnl > 0:
            total_win_pnl += pnl
            n_wins += 1
        else:
            total_loss_pnl += pnl  # negative

        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    n_trades = len(sorted_trades)
    wr = (n_wins / n_trades * 100) if n_trades > 0 else 0.0
    abs_loss = abs(total_loss_pnl)
    pf = (total_win_pnl / abs_loss) if abs_loss > 0 else float("inf")

    return {
        "pnl": round(equity - initial_capital, 2),
        "pf": safe_pf(pf),
        "dd": round(max_dd, 1),
        "trades": n_trades,
        "wr": round(wr, 1),
        "final_equity": round(equity, 2),
    }


# ---------------------------------------------------------------------------
# Capacity & fee-drag metrics (new in v3)
# ---------------------------------------------------------------------------
def compute_fee_drag(trade_list, tier_fee):
    """
    Compute fee drag percentage: total_estimated_fees / gross_profit.

    Since run_backtest already applies fees to the pnl, we estimate the
    total fees that were charged. Each trade uses size_usd (from trade['size']),
    fee per side = tier_fee, round_trip = 2 * tier_fee * size.

    Returns (fee_drag_pct, total_estimated_fees, gross_profit).
    """
    if not trade_list:
        return 0.0, 0.0, 0.0

    gross_profit = sum(t["pnl"] for t in trade_list if t["pnl"] > 0)
    total_estimated_fees = 0.0

    for t in trade_list:
        trade_size = t.get("size", INITIAL_CAPITAL)
        fee = t.get("_tier_fee", tier_fee)
        # Round trip fee: entry fee + exit fee
        # Entry: fee * size, Exit: fee * (size + gross_pnl) ~ fee * size for estimation
        round_trip = 2 * fee * trade_size
        total_estimated_fees += round_trip

    if gross_profit > 0:
        fee_drag_pct = (total_estimated_fees / gross_profit) * 100
    else:
        fee_drag_pct = 0.0

    return round(fee_drag_pct, 2), round(total_estimated_fees, 2), round(gross_profit, 2)


def compute_trades_below_breakeven(trade_list, tier_fee):
    """
    Count trades where |pnl| < round_trip_cost.

    These are trades that were effectively "eaten" by fees -- their gross
    P&L was smaller than the fee cost, making them net losers or marginal.

    Returns (count, pct_of_total).
    """
    if not trade_list:
        return 0, 0.0

    n_below = 0
    for t in trade_list:
        trade_size = t.get("size", INITIAL_CAPITAL)
        fee = t.get("_tier_fee", tier_fee)
        round_trip_cost = 2 * fee * trade_size
        if abs(t["pnl"]) < round_trip_cost:
            n_below += 1

    pct = (n_below / len(trade_list) * 100) if trade_list else 0.0
    return n_below, round(pct, 1)


def compute_capacity_proxy(trade_list, avg_daily_volumes, tier_fee):
    """
    Compute capacity proxy: avg_trade_size / avg_daily_volume.

    This measures how much of daily volume each trade consumes on average.
    Low values (< 1%) mean the strategy is unlikely to move the market.

    Returns dict: {capacity_proxy_pct, avg_trade_size, avg_daily_vol, n_coins_traded}.
    """
    if not trade_list:
        return {
            "capacity_proxy_pct": 0.0,
            "avg_trade_size": 0.0,
            "avg_daily_vol": 0.0,
            "n_coins_traded": 0,
        }

    # Average trade size
    sizes = [t.get("size", INITIAL_CAPITAL) for t in trade_list]
    avg_size = statistics.mean(sizes) if sizes else 0.0

    # Average daily volume across coins that were actually traded
    traded_coins = set(t["pair"] for t in trade_list)
    coin_vols = [avg_daily_volumes.get(c, 0.0) for c in traded_coins]
    coin_vols_nonzero = [v for v in coin_vols if v > 0]
    avg_vol = statistics.mean(coin_vols_nonzero) if coin_vols_nonzero else 0.0

    if avg_vol > 0:
        capacity_pct = (avg_size / avg_vol) * 100
    else:
        capacity_pct = 0.0

    return {
        "capacity_proxy_pct": round(capacity_pct, 4),
        "avg_trade_size": round(avg_size, 2),
        "avg_daily_vol": round(avg_vol, 2),
        "n_coins_traded": len(traded_coins),
    }


# ---------------------------------------------------------------------------
# Single-fee backtest (flat models)
# ---------------------------------------------------------------------------
def run_flat_backtest(data, coins, cfg, fee_override=None, label=""):
    """Run backtest on full universe with a single fee."""
    if not coins:
        return {
            "trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
            "final_equity": INITIAL_CAPITAL, "broke": False, "trade_list": [],
        }

    indicators = precompute_all(data, coins)
    kwargs = {"fee_override": fee_override} if fee_override is not None else {}
    result = run_backtest(indicators, coins, cfg, **kwargs)

    return {
        "trades": result["trades"],
        "pnl": round(result["pnl"], 2),
        "pf": safe_pf(result["pf"]),
        "wr": round(result["wr"], 1),
        "dd": round(result["dd"], 1),
        "final_equity": round(result["final_equity"], 2),
        "broke": result["broke"],
        "trade_list": result.get("trade_list", []),
    }


# ---------------------------------------------------------------------------
# Per-tier composite backtest
# ---------------------------------------------------------------------------
def run_per_tier_composite(data, tiers, cfg, tier_fees, avg_daily_volumes,
                           label=""):
    """
    Run backtest per tier with tier-specific fees, then aggregate.

    For each tier (T1, T2 only -- T3 excluded per UNIVERSE_POLICY):
      1. precompute_all(data, tier_coins)
      2. run_backtest(indicators, tier_coins, cfg, fee_override=tier_fee)
      3. Collect trade_list, tag with tier and tier_fee

    Aggregate:
      - Merge all trade_lists, sort by entry_bar
      - Replay equity curve from INITIAL_CAPITAL for correct DD
      - PF = sum(winning_pnl) / abs(sum(losing_pnl))
      - Compute v3 metrics: fee_drag, trades_below_breakeven, capacity_proxy

    Returns (composite_result, per_tier_results)
    """
    all_trade_lists = []
    per_tier = {}

    for tier_id in sorted(tiers.keys()):
        tier_coins = tiers[tier_id]
        fee = tier_fees.get(tier_id)
        if fee is None:
            continue
        tier_label = TIER_LABELS.get(tier_id, f"Tier {tier_id}")

        if not tier_coins:
            per_tier[tier_id] = {
                "trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
                "final_equity": INITIAL_CAPITAL, "fee": round(fee, 6),
                "fee_bps": round(fee * 10000, 1), "n_coins": 0,
                "fee_drag_pct": 0.0, "trades_below_breakeven": 0,
                "trades_below_be_pct": 0.0,
                "capacity": {"capacity_proxy_pct": 0.0, "avg_trade_size": 0.0,
                              "avg_daily_vol": 0.0, "n_coins_traded": 0},
            }
            continue

        indicators = precompute_all(data, tier_coins)
        result = run_backtest(indicators, tier_coins, cfg, fee_override=fee)

        trade_list = result.get("trade_list", [])

        # Tag each trade with its tier and tier fee for later analysis
        for t in trade_list:
            t["_tier"] = tier_id
            t["_tier_fee"] = fee

        # Compute v3 metrics for this tier
        fee_drag_pct, total_fees, gross_profit = compute_fee_drag(trade_list, fee)
        n_below_be, pct_below_be = compute_trades_below_breakeven(trade_list, fee)
        capacity = compute_capacity_proxy(trade_list, avg_daily_volumes, fee)

        all_trade_lists.extend(trade_list)

        per_tier[tier_id] = {
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": safe_pf(result["pf"]),
            "wr": round(result["wr"], 1),
            "dd": round(result["dd"], 1),
            "final_equity": round(result["final_equity"], 2),
            "fee": round(fee, 6),
            "fee_bps": round(fee * 10000, 1),
            "n_coins": len(tier_coins),
            # v3 metrics
            "fee_drag_pct": fee_drag_pct,
            "total_estimated_fees": total_fees,
            "gross_profit": gross_profit,
            "trades_below_breakeven": n_below_be,
            "trades_below_be_pct": pct_below_be,
            "capacity": capacity,
        }

        print(f"      {tier_label}: {result['trades']} trades, "
              f"P&L=${result['pnl']:+,.2f}, PF={safe_pf(result['pf'])}, "
              f"fee={fee*10000:.1f}bps, "
              f"fee_drag={fee_drag_pct:.1f}%, "
              f"below_be={n_below_be} ({pct_below_be:.1f}%)")

    # Replay equity curve from merged trades
    composite = replay_equity_curve(all_trade_lists, INITIAL_CAPITAL)

    # Composite-level v3 metrics (use T2 fee as conservative estimate)
    composite_fee = FEE_TIER2  # conservative for composite
    comp_fee_drag, comp_total_fees, comp_gross_profit = compute_fee_drag(
        all_trade_lists, composite_fee
    )
    comp_n_below, comp_pct_below = compute_trades_below_breakeven(
        all_trade_lists, composite_fee
    )
    comp_capacity = compute_capacity_proxy(
        all_trade_lists, avg_daily_volumes, composite_fee
    )

    composite["fee_drag_pct"] = comp_fee_drag
    composite["total_estimated_fees"] = comp_total_fees
    composite["gross_profit"] = comp_gross_profit
    composite["trades_below_breakeven"] = comp_n_below
    composite["trades_below_be_pct"] = comp_pct_below
    composite["capacity"] = comp_capacity

    return composite, per_tier


# ---------------------------------------------------------------------------
# Full analysis for one config
# ---------------------------------------------------------------------------
def analyze_config(cfg_name, cfg, data, all_coins, tiers, avg_daily_volumes,
                   timeframe):
    """Run all friction models for a single config."""
    print(f"\n--- Friction v3 [{timeframe}]: {cfg_name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0_total = time.time()

    # (a) Flat baseline: KRAKEN_FEE only (reference)
    print(f"  [a] Flat baseline (KRAKEN_FEE={KRAKEN_FEE*10000:.1f}bps)...")
    t0 = time.time()
    flat_baseline = run_flat_backtest(data, all_coins, cfg, fee_override=None,
                                     label="flat_baseline")
    t_a = time.time() - t0
    print(f"      {flat_baseline['trades']} trades, P&L=${flat_baseline['pnl']:+,.2f}, "
          f"PF={flat_baseline['pf']}, DD={flat_baseline['dd']}% ({t_a:.1f}s)")

    # (b) Flat 20bps: KRAKEN_FEE + 20bps slippage
    print(f"  [b] Flat 20bps (fee={FEE_FLAT*10000:.1f}bps)...")
    t0 = time.time()
    flat_20bps = run_flat_backtest(data, all_coins, cfg, fee_override=FEE_FLAT,
                                  label="flat_20bps")
    t_b = time.time() - t0
    print(f"      {flat_20bps['trades']} trades, P&L=${flat_20bps['pnl']:+,.2f}, "
          f"PF={flat_20bps['pf']}, DD={flat_20bps['dd']}% ({t_b:.1f}s)")

    # (c) Per-tier composite (T1+T2 only)
    print(f"  [c] Per-tier composite (T1+T2, T3 excluded)...")
    t0 = time.time()
    composite, per_tier = run_per_tier_composite(
        data, tiers, cfg, TIER_FEES, avg_daily_volumes, label="per_tier"
    )
    t_c = time.time() - t0
    print(f"      COMPOSITE: {composite['trades']} trades, "
          f"P&L=${composite['pnl']:+,.2f}, PF={composite['pf']}, "
          f"DD={composite['dd']}% ({t_c:.1f}s)")

    # (d) Per-tier 2x stress (T1+T2 only)
    print(f"  [d] Per-tier 2x stress (T1+T2, T3 excluded)...")
    t0 = time.time()
    composite_2x, per_tier_2x = run_per_tier_composite(
        data, tiers, cfg, TIER_FEES_2X, avg_daily_volumes, label="per_tier_2x"
    )
    t_d = time.time() - t0
    print(f"      COMPOSITE 2x: {composite_2x['trades']} trades, "
          f"P&L=${composite_2x['pnl']:+,.2f}, PF={composite_2x['pf']}, "
          f"DD={composite_2x['dd']}% ({t_d:.1f}s)")

    total_elapsed = time.time() - t0_total

    # --- Verdict logic ---
    baseline_pnl = flat_baseline["pnl"]
    composite_pnl = composite["pnl"]

    if baseline_pnl <= 0:
        verdict = "BASELINE_NEGATIVE"
        verdict_detail = (
            "Flat baseline P&L is non-positive; friction analysis not meaningful."
        )
    elif composite_pnl > 0 and composite_pnl >= baseline_pnl * 0.50:
        pct_retained = composite_pnl / baseline_pnl * 100
        verdict = "VIABLE"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} retains "
            f"{pct_retained:.1f}% of flat baseline. Strategy is VIABLE "
            f"under realistic per-tier friction at {timeframe}."
        )
    elif composite_pnl > 0:
        pct_retained = composite_pnl / baseline_pnl * 100
        verdict = "MARGINAL"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} retains only "
            f"{pct_retained:.1f}% of flat baseline (< 50%). Strategy is "
            f"MARGINAL at {timeframe} -- friction substantially erodes edge."
        )
    else:
        verdict = "NOT_VIABLE"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} is non-positive. "
            f"Strategy is NOT VIABLE under realistic per-tier friction at {timeframe}."
        )

    # --- Tier 2 alpha survival check ---
    tier2_per_tier_pnl = per_tier.get(2, {}).get("pnl", 0.0)
    tier2_per_tier_trades = per_tier.get(2, {}).get("trades", 0)
    tier2_fee_drag = per_tier.get(2, {}).get("fee_drag_pct", 0.0)
    tier2_is_best_alpha = (
        tier2_per_tier_pnl > 0
        and tier2_per_tier_pnl >= per_tier.get(1, {}).get("pnl", 0.0)
    )

    print(f"\n  VERDICT: {verdict}")
    print(f"  {verdict_detail}")

    # Strip trade_list from serialized flat results
    flat_baseline_out = {k: v for k, v in flat_baseline.items() if k != "trade_list"}
    flat_20bps_out = {k: v for k, v in flat_20bps.items() if k != "trade_list"}

    return {
        "config_name": cfg_name,
        "cfg": cfg,
        "timeframe": timeframe,
        "flat_baseline": flat_baseline_out,
        "flat_20bps": flat_20bps_out,
        "per_tier_composite": composite,
        "per_tier_breakdown": per_tier,
        "per_tier_2x_composite": composite_2x,
        "per_tier_2x_breakdown": per_tier_2x,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "tier2_alpha_survives": tier2_is_best_alpha,
        "tier2_pnl_after_friction": tier2_per_tier_pnl,
        "tier2_trades_after_friction": tier2_per_tier_trades,
        "tier2_fee_drag_pct": tier2_fee_drag,
        "timing_s": {
            "flat_baseline": round(t_a, 1),
            "flat_20bps": round(t_b, 1),
            "per_tier": round(t_c, 1),
            "per_tier_2x": round(t_d, 1),
            "total": round(total_elapsed, 1),
        },
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta, tiers, timeframe):
    """Generate human-readable per-tier friction report (v3, multi-timeframe)."""
    lines = [
        f"# HF Multi-Timeframe Per-Tier Friction Report (v3) -- {timeframe.upper()}",
        "",
        "> **Key question**: How much P&L evaporates under realistic per-tier friction",
        f"> at the **{timeframe}** timeframe? What is the fee drag and capacity profile?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Timeframe**: {timeframe}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins']}",
        f"**Tier source**: `universe_tiering_001.json`",
        f"**Universe policy**: T1+T2 only (Tier 3 excluded per UNIVERSE_POLICY.md)",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Fee model table
    lines.extend([
        "## 1. Fee Model (T1+T2 Only)",
        "",
        "| Tier | Base Fee (bps) | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |",
        "|------|---------------|----------------|---------------------|-----------------|",
    ])
    for tier_id in (1, 2):
        base_bps = KRAKEN_FEE * 10000
        slip_bps = TIER_SLIPPAGE[tier_id] * 10000
        total_bps = TIER_FEES[tier_id] * 10000
        rt_bps = total_bps * 2
        lines.append(
            f"| {TIER_LABELS[tier_id]} | {base_bps:.1f} | {slip_bps:.1f} "
            f"| {total_bps:.1f} | {rt_bps:.1f} |"
        )
    # Flat model rows
    flat_bps = FEE_FLAT * 10000
    lines.append(
        f"| Flat (Sprint 1) | {KRAKEN_FEE*10000:.1f} | {SLIPPAGE_FLAT*10000:.1f} "
        f"| {flat_bps:.1f} | {flat_bps*2:.1f} |"
    )
    base_bps = KRAKEN_FEE * 10000
    lines.append(
        f"| Flat baseline | {base_bps:.1f} | 0.0 "
        f"| {base_bps:.1f} | {base_bps*2:.1f} |"
    )
    lines.append("")

    # 2x stress table
    lines.extend([
        "### 2x Stress Fees (double slippage)",
        "",
        "| Tier | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |",
        "|------|----------------|---------------------|-----------------|",
    ])
    for tier_id in (1, 2):
        slip_2x_bps = TIER_SLIPPAGE[tier_id] * 2 * 10000
        total_2x_bps = TIER_FEES_2X[tier_id] * 10000
        rt_2x_bps = total_2x_bps * 2
        lines.append(
            f"| {TIER_LABELS[tier_id]} | {slip_2x_bps:.1f} "
            f"| {total_2x_bps:.1f} | {rt_2x_bps:.1f} |"
        )
    lines.extend([
        "",
        f"**Tier coin counts (in data)**: "
        f"T1={len(tiers.get(1, []))}, "
        f"T2={len(tiers.get(2, []))}",
        f"**Tier 3**: Excluded per UNIVERSE_POLICY.md",
        "",
    ])

    # Section 2: Results per config
    for r in all_results:
        fb = r["flat_baseline"]
        f20 = r["flat_20bps"]
        comp = r["per_tier_composite"]
        comp2x = r["per_tier_2x_composite"]
        ptb = r["per_tier_breakdown"]
        ptb2x = r["per_tier_2x_breakdown"]

        lines.extend([
            "---",
            "",
            f"## 2. Results: {r['config_name']} ({timeframe})",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
            "### Overall Comparison",
            "",
            "| Model | Trades | P&L | PF | WR% | DD% |",
            "|-------|--------|-----|----|-----|-----|",
        ])

        for label, res in [
            ("Flat baseline (KRAKEN_FEE)", fb),
            ("Flat 20bps (Sprint 1)", f20),
            ("Per-tier composite (T1+T2)", comp),
            ("Per-tier 2x stress (T1+T2)", comp2x),
        ]:
            lines.append(
                f"| {label} | {res['trades']} | ${res['pnl']:+,.2f} "
                f"| {res['pf']} | {res['wr']}% | {res['dd']}% |"
            )
        lines.append("")

        # P&L deltas relative to flat baseline
        baseline_pnl = fb["pnl"]
        lines.extend([
            "### P&L Delta vs Flat Baseline",
            "",
            "| Model | P&L | Delta | Delta % |",
            "|-------|-----|-------|---------|",
        ])
        for label, res in [
            ("Flat baseline", fb),
            ("Flat 20bps", f20),
            ("Per-tier composite", comp),
            ("Per-tier 2x stress", comp2x),
        ]:
            delta = res["pnl"] - baseline_pnl
            delta_pct = (delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0.0
            lines.append(
                f"| {label} | ${res['pnl']:+,.2f} | ${delta:+,.2f} | {delta_pct:+.1f}% |"
            )
        lines.append("")

        # Per-tier breakdown within composite
        lines.extend([
            "### Per-Tier Breakdown (composite model)",
            "",
            "| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |",
            "|------|-------|-----------|--------|-----|----|-----|-----|",
        ])
        for tier_id in sorted(ptb.keys()):
            tr = ptb[tier_id]
            lines.append(
                f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
                f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
                f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
                f"| {tr['pf']} | {tr['wr']}% | {tr['dd']}% |"
            )
        lines.append("")

        # NEW in v3: Fee drag and capacity metrics
        lines.extend([
            "### Fee Drag & Capacity (v3 metrics)",
            "",
            "| Tier | Fee Drag % | Est. Fees | Gross Profit | Below BE | Below BE % | Capacity % |",
            "|------|-----------|-----------|-------------|----------|-----------|-----------|",
        ])
        for tier_id in sorted(ptb.keys()):
            tr = ptb[tier_id]
            cap = tr.get("capacity", {})
            lines.append(
                f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
                f"| {tr.get('fee_drag_pct', 0):.1f}% "
                f"| ${tr.get('total_estimated_fees', 0):,.2f} "
                f"| ${tr.get('gross_profit', 0):,.2f} "
                f"| {tr.get('trades_below_breakeven', 0)} "
                f"| {tr.get('trades_below_be_pct', 0):.1f}% "
                f"| {cap.get('capacity_proxy_pct', 0):.4f}% |"
            )
        # Composite row
        cap_c = comp.get("capacity", {})
        lines.append(
            f"| **Composite** "
            f"| {comp.get('fee_drag_pct', 0):.1f}% "
            f"| ${comp.get('total_estimated_fees', 0):,.2f} "
            f"| ${comp.get('gross_profit', 0):,.2f} "
            f"| {comp.get('trades_below_breakeven', 0)} "
            f"| {comp.get('trades_below_be_pct', 0):.1f}% "
            f"| {cap_c.get('capacity_proxy_pct', 0):.4f}% |"
        )
        lines.append("")

        lines.extend([
            "> **Fee Drag %**: Total estimated round-trip fees / gross winning P&L. "
            "Lower is better.",
            "> **Below BE**: Trades where |pnl| < round-trip fee cost. "
            "These are effectively fee-dominated.",
            "> **Capacity %**: avg_trade_size / avg_daily_volume. "
            "Below 1% means negligible market impact.",
            "",
        ])

        # Per-tier breakdown for 2x stress
        lines.extend([
            "### Per-Tier Breakdown (2x stress)",
            "",
            "| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |",
            "|------|-------|-----------|--------|-----|----|-----|-----|",
        ])
        for tier_id in sorted(ptb2x.keys()):
            tr = ptb2x[tier_id]
            lines.append(
                f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
                f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
                f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
                f"| {tr['pf']} | {tr['wr']}% | {tr['dd']}% |"
            )
        lines.append("")

    # Section 3: Tier 2 alpha survival
    lines.extend([
        "---",
        "",
        "## 3. Tier 2 Alpha Survival Under Friction",
        "",
        "> From Sprint 1.5 (universe tiering), Tier 2 (Mid) was identified as the",
        "> primary alpha source. Does this survive per-tier friction?",
        "",
        "| Config | T2 P&L | T2 Trades | T2 Best Alpha? | T2 Fee Drag % | Survives? |",
        "|--------|--------|-----------|----------------|--------------|-----------|",
    ])
    for r in all_results:
        t2_pnl = r["tier2_pnl_after_friction"]
        t2_trades = r["tier2_trades_after_friction"]
        t2_best = r["tier2_alpha_survives"]
        t2_drag = r["tier2_fee_drag_pct"]
        survives = "YES" if t2_pnl > 0 else "NO"
        lines.append(
            f"| {r['config_name']} | ${t2_pnl:+,.2f} | {t2_trades} "
            f"| {'YES' if t2_best else 'NO'} | {t2_drag:.1f}% | {survives} |"
        )
    lines.append("")

    # Section 4: Verdicts
    lines.extend([
        "---",
        "",
        "## 4. Verdicts",
        "",
        "### Verdict Logic",
        "",
        "- **VIABLE**: Per-tier composite P&L > $0 AND >= 50% of flat baseline",
        "- **MARGINAL**: Per-tier composite P&L > $0 but < 50% of flat baseline",
        "- **NOT_VIABLE**: Per-tier composite P&L <= $0",
        "",
        "### Per-Config Verdicts",
        "",
        "| Config | Verdict | Composite P&L | Baseline P&L | Retained % |",
        "|--------|---------|--------------|-------------|------------|",
    ])
    for r in all_results:
        comp_pnl = r["per_tier_composite"]["pnl"]
        base_pnl = r["flat_baseline"]["pnl"]
        retained = (comp_pnl / base_pnl * 100) if base_pnl != 0 else 0.0
        lines.append(
            f"| {r['config_name']} | **{r['verdict']}** "
            f"| ${comp_pnl:+,.2f} | ${base_pnl:+,.2f} | {retained:+.1f}% |"
        )
    lines.append("")

    for r in all_results:
        lines.extend([
            f"**{r['config_name']}**: {r['verdict_detail']}",
            "",
        ])

    # Section 5: Overall assessment
    lines.extend([
        "---",
        "",
        f"## 5. Overall Assessment ({timeframe})",
        "",
    ])

    all_viable = all(r["verdict"] == "VIABLE" for r in all_results)
    any_not_viable = any(r["verdict"] == "NOT_VIABLE" for r in all_results)
    all_t2_survive = all(r["tier2_pnl_after_friction"] > 0 for r in all_results)

    if all_viable:
        lines.extend([
            f"**Strategy is VIABLE under realistic per-tier friction at {timeframe}.** Both configs ",
            "retain meaningful profitability when accounting for tier-specific ",
            "slippage and spread costs (T1+T2 only, T3 excluded).",
            "",
        ])
    elif any_not_viable:
        lines.extend([
            f"**Strategy is NOT VIABLE under realistic per-tier friction at {timeframe}.** At least ",
            "one config becomes unprofitable when per-tier friction is applied. ",
            "The flat fee model was overly optimistic.",
            "",
        ])
    else:
        lines.extend([
            f"**Strategy viability is MARGINAL under per-tier friction at {timeframe}.** Edge ",
            "survives but is substantially reduced. Consider restricting to ",
            "more liquid tiers or optimizing for lower turnover.",
            "",
        ])

    if all_t2_survive:
        lines.extend([
            "**Tier 2 alpha finding SURVIVES per-tier friction.** The Tier 2 (Mid) ",
            "universe remains profitable even with 30bps slippage.",
        ])
    else:
        lines.extend([
            "**Tier 2 alpha finding does NOT survive per-tier friction.** Higher ",
            "slippage costs for mid-cap coins erode the edge identified in Sprint 1.5.",
        ])

    # Fee drag assessment
    max_drag = max(
        (r["per_tier_composite"].get("fee_drag_pct", 0) for r in all_results),
        default=0
    )
    lines.extend([
        "",
        f"**Fee drag**: Max composite fee drag = {max_drag:.1f}%. ",
    ])
    if max_drag < 30:
        lines.append("Fee drag is LOW -- fees consume <30% of gross profits.")
    elif max_drag < 60:
        lines.append("Fee drag is MODERATE -- fees consume 30-60% of gross profits.")
    else:
        lines.append("Fee drag is HIGH -- fees consume >60% of gross profits. "
                      "Consider reducing trade frequency or targeting higher-margin setups.")

    lines.extend([
        "",
        "---",
        f"*Generated by hf_friction_v3.py -- {timeframe} MTF variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Multi-Timeframe Per-Tier Friction Model (v3)"
    )
    parser.add_argument(
        "--timeframe",
        choices=["4h", "1h", "15m"],
        default="4h",
        help="Candle timeframe (default: 4h)",
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    tf = args.timeframe

    print("=" * 70)
    print(f"  HF Multi-Timeframe Per-Tier Friction Model (v3) -- {tf.upper()}")
    print("  Key question: How much P&L evaporates under realistic friction?")
    print("  Universe policy: T1+T2 only (Tier 3 excluded)")
    print("=" * 70)
    print(f"  Timeframe: {tf}")
    print(f"  Universe:  {args.universe}")

    # 1. Load tier assignments (T1+T2 only)
    tiers = load_tier_assignments()
    for tier_id in sorted(tiers.keys()):
        print(f"  {TIER_LABELS[tier_id]}: {len(tiers[tier_id])} coins")

    # 2. Load candle data
    data, all_coins, data_path = load_data(tf, args.universe)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # Filter tier coins to only those present in data
    for tier_id in list(tiers.keys()):
        data_coins_set = set(all_coins)
        tiers[tier_id] = [c for c in tiers[tier_id] if c in data_coins_set]

    total_tiered = sum(len(v) for v in tiers.values())
    print(f"  Tier coins in data: {total_tiered} / {len(all_coins)}")

    # Build T1+T2 coin list for flat backtests (universe policy: exclude T3)
    t1t2_coins = sorted(set(tiers.get(1, []) + tiers.get(2, [])))
    print(f"  T1+T2 coins (live universe): {len(t1t2_coins)}")

    # 3. Compute average daily volumes for capacity proxy
    print("\n  Computing average daily volumes...")
    avg_daily_volumes = compute_avg_daily_volume(data, all_coins, tf)

    # Print fee model summary
    print("\n  Fee model (per side, T1+T2 only):")
    for tier_id in (1, 2):
        print(f"    {TIER_LABELS[tier_id]}: {TIER_FEES[tier_id]*10000:.1f}bps "
              f"(2x stress: {TIER_FEES_2X[tier_id]*10000:.1f}bps)")
    print(f"    Flat (Sprint 1): {FEE_FLAT*10000:.1f}bps")
    print(f"    Flat baseline:   {KRAKEN_FEE*10000:.1f}bps")

    t_start = time.time()

    # 4. Run analysis for each config
    # Flat backtests use T1+T2 coins only (per UNIVERSE_POLICY)
    all_results = []
    for cfg_name, cfg in CONFIGS.items():
        result = analyze_config(
            cfg_name, cfg, data, t1t2_coins, tiers, avg_daily_volumes, tf
        )
        all_results.append(result)

    total_time = time.time() - t_start

    # 5. Build meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timeframe": tf,
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(t1t2_coins),
        "n_coins_total": len(all_coins),
        "n_bars": n_bars,
        "tier_source": str(TIERING_PATH),
        "tier_counts": {str(k): len(v) for k, v in tiers.items()},
        "universe_policy": "T1+T2 only, Tier 3 excluded",
        "fee_model": {
            "kraken_fee": KRAKEN_FEE,
            "tier1_fee": FEE_TIER1,
            "tier2_fee": FEE_TIER2,
            "flat_fee": FEE_FLAT,
            "tier1_fee_2x": FEE_TIER1_2X,
            "tier2_fee_2x": FEE_TIER2_2X,
        },
        "total_time_s": round(total_time, 2),
        "label": f"{tf} MTF variant research",
        "configs_tested": list(CONFIGS.keys()),
    }

    # 6. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"friction_v3_{tf}_001.json"

    json_output = {
        "meta": meta,
        "results": {r["config_name"]: r for r in all_results},
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 7. Write markdown report
    md_path = REPORTS_DIR / f"friction_v3_{tf}_001.md"
    md = generate_markdown(all_results, meta, tiers, tf)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 8. Final summary
    print("\n" + "=" * 70)
    print(f"  PER-TIER FRICTION SUMMARY (v3, {tf.upper()}, T1+T2 only)")
    print("=" * 70)

    print(f"\n  {'Model':<28} {'Trades':>7} {'P&L':>12} {'PF':>6} {'DD%':>6} {'FeeDrag':>8}")
    print("  " + "-" * 72)
    for r in all_results:
        print(f"\n  {r['config_name']}:")
        for label, res in [
            ("Flat baseline", r["flat_baseline"]),
            ("Flat 20bps", r["flat_20bps"]),
            ("Per-tier composite", r["per_tier_composite"]),
            ("Per-tier 2x stress", r["per_tier_2x_composite"]),
        ]:
            drag_str = f"{res.get('fee_drag_pct', 'N/A')}"
            if isinstance(res.get('fee_drag_pct'), (int, float)):
                drag_str = f"{res['fee_drag_pct']:.1f}%"
            else:
                drag_str = "   N/A"
            print(f"    {label:<26} {res['trades']:>7} "
                  f"${res['pnl']:>+10,.2f} {res['pf']:>6} {res['dd']:>5}% {drag_str:>8}")

    print(f"\n  {'Config':<20} {'Verdict':<14} {'Retained%':>10} {'T2 Surv':>8} {'T2 Drag':>8}")
    print("  " + "-" * 64)
    for r in all_results:
        base_pnl = r["flat_baseline"]["pnl"]
        comp_pnl = r["per_tier_composite"]["pnl"]
        retained = (comp_pnl / base_pnl * 100) if base_pnl != 0 else 0.0
        t2_surv = "YES" if r["tier2_pnl_after_friction"] > 0 else "NO"
        t2_drag = f"{r['tier2_fee_drag_pct']:.1f}%"
        print(f"  {r['config_name']:<20} {r['verdict']:<14} "
              f"{retained:>9.1f}% {t2_surv:>8} {t2_drag:>8}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()
