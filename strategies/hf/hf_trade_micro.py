#!/usr/bin/env python3
"""
HF Trade Microstructure — 4H variant research.

Decomposes trade activity per config, per tier, per coin, per day/week.
Answers: where do trades come from, how consistent is throughput, and
how concentrated is trade activity?

Usage:
    python strategies/hf/hf_trade_micro.py
    python strategies/hf/hf_trade_micro.py --universe tradeable

Outputs:
    reports/hf/trade_micro_001.json  — full structured results
    reports/hf/trade_micro_001.md    — human-readable summary
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# --- Path setup ---
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

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"
TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# Tier fees (from hf_friction_v2.py / UNIVERSE_POLICY.md)
TIER_FEES = {
    "1": round(KRAKEN_FEE + 0.0005, 4),   # 31 bps
    "2": round(KRAKEN_FEE + 0.0030, 4),   # 56 bps
    "3": round(KRAKEN_FEE + 0.0075, 4),   # 101 bps
}

CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8,
    "time_max_bars": 15, "tp_pct": 12, "vol_confirm": True, "vol_spike_mult": 3.0,
})
GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10,
    "time_max_bars": 15, "tp_pct": 12, "vol_confirm": True, "vol_spike_mult": 2.5,
})

CONFIGS = {"Champion_H2": CHAMPION_H2, "GRID_BEST": GRID_BEST}


# ============================================================
# DATA LOADING
# ============================================================
def load_data(universe: str):
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def load_tiers():
    """Load tier assignments from universe_tiering report."""
    if not TIERING_PATH.exists():
        print(f"ERROR: {TIERING_PATH} not found. Run hf_universe_tiering.py first.")
        sys.exit(1)
    with open(TIERING_PATH) as f:
        d = json.load(f)
    tier_map = {}  # coin -> tier_id
    for tier_id, tier_info in d["tier_breakdown"].items():
        coins_list = tier_info.get("coins", [])
        for c in coins_list:
            if isinstance(c, str):
                tier_map[c] = tier_id
            elif isinstance(c, dict):
                tier_map[c.get("coin", c.get("symbol", ""))] = tier_id
    return tier_map


def bar_to_date(data, coins, bar_idx):
    """Convert bar index to datetime using first available coin's timestamp."""
    for coin in coins:
        candles = data.get(coin, [])
        if bar_idx < len(candles):
            ts = candles[bar_idx].get("time", 0)
            if ts:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def bar_to_ts(data, coins, bar_idx):
    """Convert bar index to unix timestamp."""
    for coin in coins:
        candles = data.get(coin, [])
        if bar_idx < len(candles):
            return candles[bar_idx].get("time", 0)
    return 0


# ============================================================
# BUILD BAR-TO-DATE MAP
# ============================================================
def build_bar_date_map(data, coins, n_bars):
    """Build mapping from bar index to (date_str, week_str, unix_ts)."""
    bar_map = {}
    ref_coin = coins[0]
    candles = data[ref_coin]
    for i in range(min(n_bars, len(candles))):
        ts = candles[i].get("time", 0)
        if ts:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            bar_map[i] = {
                "date": dt.strftime("%Y-%m-%d"),
                "week": dt.strftime("%Y-W%W"),
                "ts": ts,
                "dt": dt,
            }
    return bar_map


# ============================================================
# TRADE ANALYSIS
# ============================================================
def analyze_trades(trade_list, tier_map, bar_date_map, n_bars):
    """Full trade microstructure analysis."""

    total_trades = len(trade_list)

    # --- Per-tier breakdown ---
    tier_trades = defaultdict(list)
    for t in trade_list:
        tier_id = tier_map.get(t["pair"], "?")
        tier_trades[tier_id].append(t)

    tier_summary = {}
    for tier_id in sorted(tier_trades.keys()):
        trades = tier_trades[tier_id]
        pnl = sum(t["pnl"] for t in trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        tier_summary[tier_id] = {
            "trades": len(trades),
            "pnl": round(pnl, 2),
            "wr": round(wins / len(trades) * 100, 1) if trades else 0,
            "coins": len(set(t["pair"] for t in trades)),
            "pct_of_total": round(len(trades) / total_trades * 100, 1) if total_trades else 0,
        }

    # --- Per-coin breakdown ---
    coin_trades = defaultdict(list)
    for t in trade_list:
        coin_trades[t["pair"]].append(t)

    coin_summary = []
    for coin, trades in coin_trades.items():
        pnl = sum(t["pnl"] for t in trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        coin_summary.append({
            "coin": coin,
            "tier": tier_map.get(coin, "?"),
            "trades": len(trades),
            "pnl": round(pnl, 2),
            "wr": round(wins / len(trades) * 100, 1) if trades else 0,
            "avg_pnl": round(pnl / len(trades), 2) if trades else 0,
            "avg_bars": round(sum(t["bars"] for t in trades) / len(trades), 1),
        })
    coin_summary.sort(key=lambda x: -x["trades"])

    # --- Per-day breakdown ---
    day_trades = defaultdict(list)
    for t in trade_list:
        bar_info = bar_date_map.get(t["entry_bar"])
        if bar_info:
            day_trades[bar_info["date"]].append(t)

    # Build full calendar of trading days
    all_dates = sorted(set(
        bar_date_map[b]["date"] for b in bar_date_map
        if START_BAR <= b < n_bars
    ))

    day_summary = []
    for date_str in all_dates:
        trades = day_trades.get(date_str, [])
        pnl = sum(t["pnl"] for t in trades)
        day_summary.append({
            "date": date_str,
            "trades": len(trades),
            "pnl": round(pnl, 2),
        })

    total_days = len(all_dates)
    days_with_trades = sum(1 for d in day_summary if d["trades"] > 0)
    days_zero_trades = total_days - days_with_trades
    pct_zero = round(days_zero_trades / total_days * 100, 1) if total_days else 0

    # --- Per-week breakdown ---
    week_trades = defaultdict(list)
    for t in trade_list:
        bar_info = bar_date_map.get(t["entry_bar"])
        if bar_info:
            week_trades[bar_info["week"]].append(t)

    all_weeks = sorted(set(
        bar_date_map[b]["week"] for b in bar_date_map
        if START_BAR <= b < n_bars
    ))

    week_summary = []
    for week_str in all_weeks:
        trades = week_trades.get(week_str, [])
        pnl = sum(t["pnl"] for t in trades)
        week_summary.append({
            "week": week_str,
            "trades": len(trades),
            "pnl": round(pnl, 2),
        })

    total_weeks = len(all_weeks)
    weeks_with_trades = sum(1 for w in week_summary if w["trades"] > 0)
    weeks_zero = total_weeks - weeks_with_trades
    pct_zero_weeks = round(weeks_zero / total_weeks * 100, 1) if total_weeks else 0

    # Trades per week stats
    tpw = [w["trades"] for w in week_summary]
    tpw_sorted = sorted(tpw)
    mean_tpw = round(sum(tpw) / len(tpw), 2) if tpw else 0
    median_tpw = tpw_sorted[len(tpw_sorted) // 2] if tpw_sorted else 0
    max_tpw = max(tpw) if tpw else 0

    # --- Trade duration stats ---
    durations = [t["bars"] for t in trade_list]
    dur_sorted = sorted(durations)
    exit_reasons = defaultdict(int)
    for t in trade_list:
        exit_reasons[t["reason"]] += 1

    return {
        "total_trades": total_trades,
        "tier_summary": tier_summary,
        "coin_summary": coin_summary,
        "day_summary": {
            "total_days": total_days,
            "days_with_trades": days_with_trades,
            "days_zero_trades": days_zero_trades,
            "pct_zero_days": pct_zero,
            "daily_detail": day_summary,
        },
        "week_summary": {
            "total_weeks": total_weeks,
            "weeks_with_trades": weeks_with_trades,
            "weeks_zero_trades": weeks_zero,
            "pct_zero_weeks": pct_zero_weeks,
            "mean_trades_per_week": mean_tpw,
            "median_trades_per_week": median_tpw,
            "max_trades_per_week": max_tpw,
            "weekly_detail": week_summary,
        },
        "duration_stats": {
            "mean_bars": round(sum(durations) / len(durations), 1) if durations else 0,
            "median_bars": dur_sorted[len(dur_sorted) // 2] if dur_sorted else 0,
            "min_bars": min(durations) if durations else 0,
            "max_bars": max(durations) if durations else 0,
        },
        "exit_reasons": dict(exit_reasons),
    }


# ============================================================
# MARKDOWN REPORT
# ============================================================
def generate_markdown(all_results, meta):
    lines = [
        "# HF Trade Microstructure — 4H Variant Research",
        "",
        "> Where do trades come from, how consistent is throughput, how concentrated is activity?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Coins**: {meta['n_coins']}",
        f"**Bars**: {meta['n_bars']} (4H, ~{meta['n_bars'] * 4 // 24} days)",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    for cfg_name, result in all_results.items():
        cfg = result["cfg"]
        a = result["analysis"]

        lines.extend([
            "---",
            "",
            f"## {cfg_name}",
            "",
            f"**Config**: `{json.dumps(cfg, sort_keys=True)}`",
            f"**Total trades**: {a['total_trades']}",
            "",
        ])

        # --- 1. Per-tier ---
        lines.extend([
            "### 1. Trades per Tier",
            "",
            "| Tier | Trades | % of Total | Coins | P&L | WR |",
            "|------|--------|-----------|-------|-----|-----|",
        ])
        for tier_id in sorted(a["tier_summary"].keys()):
            ts = a["tier_summary"][tier_id]
            label = {"1": "Tier 1 (Liquid)", "2": "Tier 2 (Mid)", "3": "Tier 3 (Illiquid)"}.get(tier_id, f"Tier {tier_id}")
            lines.append(
                f"| {label} | {ts['trades']} | {ts['pct_of_total']}% "
                f"| {ts['coins']} | ${ts['pnl']:+,.0f} | {ts['wr']}% |"
            )
        lines.append("")

        # --- 2. Per-coin top 20 + bottom 20 ---
        coins_sorted_by_trades = sorted(a["coin_summary"], key=lambda x: -x["trades"])
        coins_sorted_by_pnl = sorted(a["coin_summary"], key=lambda x: -x["pnl"])

        lines.extend([
            "### 2. Trades per Coin",
            "",
            f"**Unique coins traded**: {len(a['coin_summary'])}",
            "",
            "**Top 20 by trade count**:",
            "",
            "| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |",
            "|---|------|------|--------|-----|-----|---------|----------|",
        ])
        for i, cs in enumerate(coins_sorted_by_trades[:20], 1):
            lines.append(
                f"| {i} | {cs['coin']} | T{cs['tier']} | {cs['trades']} "
                f"| ${cs['pnl']:+,.0f} | {cs['wr']}% | ${cs['avg_pnl']:+,.0f} | {cs['avg_bars']} |"
            )
        lines.append("")

        # Bottom 20 by P&L
        coins_worst = sorted(a["coin_summary"], key=lambda x: x["pnl"])[:20]
        lines.extend([
            "**Bottom 20 by P&L**:",
            "",
            "| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |",
            "|---|------|------|--------|-----|-----|---------|----------|",
        ])
        for i, cs in enumerate(coins_worst, 1):
            lines.append(
                f"| {i} | {cs['coin']} | T{cs['tier']} | {cs['trades']} "
                f"| ${cs['pnl']:+,.0f} | {cs['wr']}% | ${cs['avg_pnl']:+,.0f} | {cs['avg_bars']} |"
            )
        lines.append("")

        # --- 3. Throughput per week ---
        ws = a["week_summary"]
        lines.extend([
            "### 3. Throughput per Week",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total weeks | {ws['total_weeks']} |",
            f"| Weeks with ≥1 trade | {ws['weeks_with_trades']} |",
            f"| Weeks with 0 trades | {ws['weeks_zero_trades']} ({ws['pct_zero_weeks']}%) |",
            f"| Mean trades/week | {ws['mean_trades_per_week']} |",
            f"| Median trades/week | {ws['median_trades_per_week']} |",
            f"| Max trades/week | {ws['max_trades_per_week']} |",
            "",
        ])

        # Weekly detail table
        lines.extend([
            "**Weekly breakdown**:",
            "",
            "| Week | Trades | P&L |",
            "|------|--------|-----|",
        ])
        for w in ws["weekly_detail"]:
            marker = " ⚠️" if w["trades"] == 0 else ""
            lines.append(f"| {w['week']} | {w['trades']}{marker} | ${w['pnl']:+,.0f} |")
        lines.append("")

        # --- 4. Daily consistency ---
        ds = a["day_summary"]
        lines.extend([
            "### 4. Daily Consistency",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total calendar days | {ds['total_days']} |",
            f"| Days with ≥1 trade | {ds['days_with_trades']} |",
            f"| Days with 0 trades | {ds['days_zero_trades']} ({ds['pct_zero_days']}%) |",
            "",
        ])

        # --- 5. Trade duration + exit reasons ---
        dur = a["duration_stats"]
        lines.extend([
            "### 5. Trade Duration & Exit Reasons",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Mean duration | {dur['mean_bars']} bars ({dur['mean_bars'] * 4:.0f}h) |",
            f"| Median duration | {dur['median_bars']} bars ({dur['median_bars'] * 4}h) |",
            f"| Min duration | {dur['min_bars']} bars ({dur['min_bars'] * 4}h) |",
            f"| Max duration | {dur['max_bars']} bars ({dur['max_bars'] * 4}h) |",
            "",
            "**Exit reasons**:",
            "",
            "| Reason | Count | % |",
            "|--------|-------|---|",
        ])
        total_t = a["total_trades"]
        for reason, count in sorted(a["exit_reasons"].items(), key=lambda x: -x[1]):
            pct = round(count / total_t * 100, 1) if total_t else 0
            lines.append(f"| {reason} | {count} | {pct}% |")
        lines.append("")

    lines.extend([
        "---",
        "*Generated by hf_trade_micro.py — 4H variant research*",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="HF Trade Microstructure — 4H variant research")
    parser.add_argument("--universe", choices=["tradeable", "live"], default="tradeable")
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Trade Microstructure — 4H Variant Research")
    print("=" * 70)

    # Load data
    data, coins, data_path = load_data(args.universe)
    n_bars = len(data[coins[0]])
    print(f"  Loaded {len(coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # Load tiers
    tier_map = load_tiers()
    print(f"  Tier assignments loaded: {len(tier_map)} coins")

    # Build bar-to-date map
    bar_date_map = build_bar_date_map(data, coins, n_bars)
    print(f"  Bar-date map: {len(bar_date_map)} bars mapped")

    # Precompute indicators once
    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time() - t0:.1f}s")

    t_start = time.time()
    all_results = {}

    for cfg_name, cfg in CONFIGS.items():
        print(f"\n--- {cfg_name} ---")
        print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

        # Run backtest
        result = run_backtest(indicators, coins, cfg)
        trade_list = result.get("trade_list", [])
        print(f"  Trades: {result['trades']}, P&L=${result['pnl']:+,.2f}")

        # Analyze
        analysis = analyze_trades(trade_list, tier_map, bar_date_map, n_bars)

        # Print summary
        print(f"  Tier breakdown:")
        for tier_id in sorted(analysis["tier_summary"].keys()):
            ts = analysis["tier_summary"][tier_id]
            print(f"    T{tier_id}: {ts['trades']} trades ({ts['pct_of_total']}%), "
                  f"P&L=${ts['pnl']:+,.0f}, {ts['coins']} coins")

        ws = analysis["week_summary"]
        print(f"  Weekly: mean={ws['mean_trades_per_week']}/wk, "
              f"median={ws['median_trades_per_week']}/wk, "
              f"zero-weeks={ws['weeks_zero_trades']}/{ws['total_weeks']} "
              f"({ws['pct_zero_weeks']}%)")

        ds = analysis["day_summary"]
        print(f"  Daily: zero-days={ds['days_zero_trades']}/{ds['total_days']} "
              f"({ds['pct_zero_days']}%)")

        all_results[cfg_name] = {
            "cfg": cfg,
            "baseline": {
                "trades": result["trades"],
                "pnl": round(result["pnl"], 2),
                "pf": round(result["pf"], 2) if result["pf"] != float("inf") else 99.0,
                "wr": round(result["wr"], 1),
                "dd": round(result["dd"], 1),
            },
            "analysis": analysis,
        }

    total_time = time.time() - t_start

    # Meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "n_bars": n_bars,
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
    }

    # Write JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "trade_micro_001.json"
    with open(json_path, "w") as f:
        json.dump({"meta": meta, "results": all_results}, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown
    md_path = REPORTS_DIR / "trade_micro_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    print(f"\n  Done in {total_time:.1f}s")


if __name__ == "__main__":
    main()
