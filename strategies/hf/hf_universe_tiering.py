#!/usr/bin/env python3
"""
HF Universe Tiering -- 4H variant research.

Defines and tests tradability tiers based on volume/liquidity characteristics.

Background: The worst coin (COQ/USD) appears to be a microcap/low-liquidity
symbol. We need inclusion filters to understand if the strategy edge depends
on illiquid coins.

Methodology:
  1. Load candle data (tradeable universe, 425 coins)
  2. For each coin, compute:
     - median_daily_volume: median of all non-zero volume candles (quote ccy)
     - zero_vol_pct: percentage of candles with zero volume
     - max_wick_ratio: max((high-max(open,close))/close,
                           (min(open,close)-low)/close) across all candles
     - bar_coverage: len(candles) / max_bars -- data completeness
  3. Define 3 tiers:
     - Tier 1 (Liquid):   median_daily_volume >= P75 AND
                           zero_vol_pct < 5% AND bar_coverage >= 0.99
     - Tier 2 (Mid):      median_daily_volume >= P25 AND
                           zero_vol_pct < 20% AND bar_coverage >= 0.95
     - Tier 3 (Illiquid): everything else (below Tier 2 thresholds)
  4. Run backtest on each tier separately for Champion_H2 and GRID_BEST
  5. Also run the full universe as baseline
  6. Report per-tier symbol count, characteristics, backtest results,
     alpha contribution, and whether the edge survives on Tier 1 only

Usage:
    python strategies/hf/hf_universe_tiering.py
    python strategies/hf/hf_universe_tiering.py --universe tradeable
    python strategies/hf/hf_universe_tiering.py --universe live

Outputs:
    reports/hf/universe_tiering_001.json  -- full structured results
    reports/hf/universe_tiering_001.md    -- human-readable summary
"""

import sys
import json
import time
import argparse
import statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict

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

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# Tier thresholds
TIER1_ZERO_VOL_MAX = 5.0       # < 5% zero-volume candles
TIER1_BAR_COVERAGE_MIN = 0.99  # >= 99% data completeness
TIER2_ZERO_VOL_MAX = 20.0      # < 20% zero-volume candles
TIER2_BAR_COVERAGE_MIN = 0.95  # >= 95% data completeness

# Configs under test (same as hf_validate.py)
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
def load_data(universe: str):
    """Load candle data and return (data_dict, sorted_coins, path_str)."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        print(f"  Tried: {DATA_FILES.get(universe, 'N/A')}")
        print(f"  Tried: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ---------------------------------------------------------------------------
# Per-coin liquidity metrics
# ---------------------------------------------------------------------------
def compute_coin_metrics(data, coins):
    """
    Compute liquidity/quality metrics for each coin.

    Returns dict: coin -> {
        median_daily_volume, zero_vol_pct, max_wick_ratio, bar_coverage,
        n_bars, n_nonzero_vol
    }
    """
    # Find the maximum bar count across all coins (reference for coverage)
    max_bars = max(len(data[c]) for c in coins) if coins else 0

    metrics = {}
    for coin in coins:
        candles = data[coin]
        n_bars_coin = len(candles)

        # Volume metrics
        volumes = [c.get("volume", 0) for c in candles]
        nonzero_vols = [v for v in volumes if v > 0]
        n_zero = sum(1 for v in volumes if v == 0)
        zero_vol_pct = (n_zero / n_bars_coin * 100.0) if n_bars_coin > 0 else 100.0
        median_vol = statistics.median(nonzero_vols) if nonzero_vols else 0.0

        # Wick ratio: measures extreme wicks / outlier bars
        max_wick = 0.0
        for c in candles:
            o = c.get("open", 0)
            h = c.get("high", 0)
            lo = c.get("low", 0)
            cl = c.get("close", 0)
            if cl <= 0:
                continue
            upper_wick = (h - max(o, cl)) / cl
            lower_wick = (min(o, cl) - lo) / cl
            wick = max(upper_wick, lower_wick)
            if wick > max_wick:
                max_wick = wick

        # Bar coverage
        bar_coverage = (n_bars_coin / max_bars) if max_bars > 0 else 0.0

        metrics[coin] = {
            "median_daily_volume": round(median_vol, 2),
            "zero_vol_pct": round(zero_vol_pct, 2),
            "max_wick_ratio": round(max_wick, 4),
            "bar_coverage": round(bar_coverage, 4),
            "n_bars": n_bars_coin,
            "n_nonzero_vol": len(nonzero_vols),
        }

    return metrics, max_bars


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------
def assign_tiers(metrics, coins):
    """
    Assign coins to tiers based on volume/liquidity characteristics.

    Tier 1 (Liquid):   median_daily_volume >= P75 AND zero_vol_pct < 5%
                        AND bar_coverage >= 0.99
    Tier 2 (Mid):      median_daily_volume >= P25 AND zero_vol_pct < 20%
                        AND bar_coverage >= 0.95
    Tier 3 (Illiquid): everything else

    Returns (tiers_dict, percentiles_dict)
      tiers_dict: {1: [coins], 2: [coins], 3: [coins]}
      percentiles_dict: {p25_vol, p75_vol, ...}
    """
    # Compute volume percentiles across the universe
    all_median_vols = [metrics[c]["median_daily_volume"] for c in coins]
    all_median_vols_sorted = sorted(all_median_vols)
    n = len(all_median_vols_sorted)

    if n == 0:
        return {1: [], 2: [], 3: []}, {}

    p25_vol = all_median_vols_sorted[int(n * 0.25)]
    p50_vol = all_median_vols_sorted[int(n * 0.50)]
    p75_vol = all_median_vols_sorted[int(n * 0.75)]

    percentiles = {
        "p25_volume": round(p25_vol, 2),
        "p50_volume": round(p50_vol, 2),
        "p75_volume": round(p75_vol, 2),
    }

    tiers = {1: [], 2: [], 3: []}

    for coin in coins:
        m = metrics[coin]
        vol = m["median_daily_volume"]
        zvp = m["zero_vol_pct"]
        cov = m["bar_coverage"]

        # Tier 1: most liquid and complete
        if vol >= p75_vol and zvp < TIER1_ZERO_VOL_MAX and cov >= TIER1_BAR_COVERAGE_MIN:
            tiers[1].append(coin)
        # Tier 2: mid-range
        elif vol >= p25_vol and zvp < TIER2_ZERO_VOL_MAX and cov >= TIER2_BAR_COVERAGE_MIN:
            tiers[2].append(coin)
        # Tier 3: everything else
        else:
            tiers[3].append(coin)

    return tiers, percentiles


# ---------------------------------------------------------------------------
# Tier statistics
# ---------------------------------------------------------------------------
def compute_tier_stats(tiers, metrics):
    """Compute aggregate statistics for each tier."""
    tier_stats = {}
    for tier_id in sorted(tiers.keys()):
        tier_coins = tiers[tier_id]
        if not tier_coins:
            tier_stats[tier_id] = {
                "count": 0,
                "median_volume": 0.0,
                "mean_zero_vol_pct": 0.0,
                "mean_bar_coverage": 0.0,
                "mean_max_wick": 0.0,
                "min_volume": 0.0,
                "max_volume": 0.0,
            }
            continue

        vols = [metrics[c]["median_daily_volume"] for c in tier_coins]
        zvps = [metrics[c]["zero_vol_pct"] for c in tier_coins]
        covs = [metrics[c]["bar_coverage"] for c in tier_coins]
        wicks = [metrics[c]["max_wick_ratio"] for c in tier_coins]

        tier_stats[tier_id] = {
            "count": len(tier_coins),
            "median_volume": round(statistics.median(vols), 2),
            "mean_zero_vol_pct": round(statistics.mean(zvps), 2),
            "mean_bar_coverage": round(statistics.mean(covs) * 100, 2),
            "mean_max_wick": round(statistics.mean(wicks), 4),
            "min_volume": round(min(vols), 2),
            "max_volume": round(max(vols), 2),
        }

    return tier_stats


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------
def run_tier_backtest(data, coins, cfg, label=""):
    """
    Precompute indicators and run backtest on given coin subset.
    Returns dict with trades, pnl, pf, wr, dd, trade_list.
    """
    if not coins:
        return {
            "trades": 0,
            "pnl": 0.0,
            "pf": 0.0,
            "wr": 0.0,
            "dd": 0.0,
            "final_equity": INITIAL_CAPITAL,
            "broke": False,
            "trade_list": [],
        }

    indicators = precompute_all(data, coins)
    result = run_backtest(indicators, coins, cfg)

    pf = result["pf"]
    if pf == float("inf"):
        pf = 99.0

    return {
        "trades": result["trades"],
        "pnl": round(result["pnl"], 2),
        "pf": round(min(pf, 99.0), 2),
        "wr": round(result["wr"], 1),
        "dd": round(result["dd"], 1),
        "final_equity": round(result["final_equity"], 2),
        "broke": result["broke"],
        "trade_list": result.get("trade_list", []),
    }


# ---------------------------------------------------------------------------
# P&L contribution analysis
# ---------------------------------------------------------------------------
def compute_pnl_contribution(tier_results, baseline_pnl):
    """
    Compute per-tier P&L contribution as a fraction of baseline.

    Returns dict: tier_id -> {pnl, pnl_share_pct, trades, trades_share_pct}
    """
    contributions = {}
    total_trades = sum(r["trades"] for r in tier_results.values())

    for tier_id, result in sorted(tier_results.items()):
        pnl = result["pnl"]
        trades = result["trades"]

        if baseline_pnl != 0:
            pnl_share = pnl / abs(baseline_pnl) * 100.0
        else:
            pnl_share = 0.0

        trades_share = (trades / total_trades * 100.0) if total_trades > 0 else 0.0

        contributions[tier_id] = {
            "pnl": round(pnl, 2),
            "pnl_share_pct": round(pnl_share, 1),
            "trades": trades,
            "trades_share_pct": round(trades_share, 1),
        }

    return contributions


# ---------------------------------------------------------------------------
# Run tiering analysis for one config
# ---------------------------------------------------------------------------
def run_tiering_analysis(cfg_name, cfg, data, all_coins, tiers):
    """Run backtest per tier + full universe baseline for one config."""
    print(f"\n--- Tiering Analysis: {cfg_name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0_total = time.time()

    # Baseline: full universe
    print(f"  [baseline] Running full universe ({len(all_coins)} coins)...")
    t0 = time.time()
    baseline = run_tier_backtest(data, all_coins, cfg, label="full")
    t_base = time.time() - t0
    print(f"    {baseline['trades']} trades, P&L=${baseline['pnl']:+,.2f}, "
          f"PF={baseline['pf']}, WR={baseline['wr']}%, DD={baseline['dd']}% "
          f"({t_base:.1f}s)")

    # Per-tier backtests
    tier_results = {}
    tier_timings = {}
    tier_names = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)", 3: "Tier 3 (Illiquid)"}

    for tier_id in sorted(tiers.keys()):
        tier_coins = tiers[tier_id]
        name = tier_names.get(tier_id, f"Tier {tier_id}")
        print(f"  [{name}] Running {len(tier_coins)} coins...")
        t0 = time.time()
        result = run_tier_backtest(data, tier_coins, cfg, label=name)
        elapsed = time.time() - t0
        tier_results[tier_id] = result
        tier_timings[tier_id] = round(elapsed, 1)
        print(f"    {result['trades']} trades, P&L=${result['pnl']:+,.2f}, "
              f"PF={result['pf']}, WR={result['wr']}%, DD={result['dd']}% "
              f"({elapsed:.1f}s)")

    # P&L contribution analysis
    contributions = compute_pnl_contribution(tier_results, baseline["pnl"])

    # Determine which tier contributes most alpha
    best_tier = max(contributions.keys(),
                    key=lambda t: contributions[t]["pnl"])
    best_tier_pnl = contributions[best_tier]["pnl"]
    best_tier_share = contributions[best_tier]["pnl_share_pct"]

    # Does the edge survive on Tier 1 only?
    tier1_result = tier_results.get(1, {"pnl": 0.0, "pf": 0.0})
    tier1_pnl = tier1_result["pnl"]
    tier1_pf = tier1_result["pf"]
    baseline_pnl = baseline["pnl"]

    if baseline_pnl > 0:
        tier1_retention = tier1_pnl / baseline_pnl * 100.0
    elif baseline_pnl == 0:
        tier1_retention = 100.0 if tier1_pnl >= 0 else 0.0
    else:
        tier1_retention = 0.0

    # Verdict
    if baseline_pnl <= 0:
        edge_verdict = "BASELINE_NEGATIVE"
        edge_detail = (
            "Baseline P&L is non-positive; tiering analysis is not meaningful. "
            "Strategy does not have positive edge on the full universe."
        )
    elif tier1_pnl > 0 and tier1_pf > 1.0 and tier1_retention >= 50.0:
        edge_verdict = "EDGE_SURVIVES_TIER1"
        edge_detail = (
            f"Edge survives on Tier 1 only: P&L=${tier1_pnl:+,.2f} "
            f"(PF={tier1_pf}, {tier1_retention:.1f}% of baseline retained). "
            f"Liquid-only universe is viable for live trading."
        )
    elif tier1_pnl > 0 and tier1_retention >= 20.0:
        edge_verdict = "EDGE_PARTIAL_TIER1"
        edge_detail = (
            f"Edge partially survives on Tier 1: P&L=${tier1_pnl:+,.2f} "
            f"({tier1_retention:.1f}% of baseline). "
            f"Consider including Tier 2 for more robust edge."
        )
    else:
        edge_verdict = "EDGE_DEPENDS_ON_ILLIQUID"
        edge_detail = (
            f"Edge depends on illiquid coins. Tier 1 P&L=${tier1_pnl:+,.2f} "
            f"({tier1_retention:.1f}% of baseline). "
            f"Live trading with liquid-only universe NOT recommended."
        )

    total_elapsed = time.time() - t0_total

    print(f"\n  VERDICT: {edge_verdict}")
    print(f"  {edge_detail}")

    # Strip trade_list from serialized output to keep JSON manageable
    baseline_out = {k: v for k, v in baseline.items() if k != "trade_list"}
    tier_results_out = {}
    for tid, r in tier_results.items():
        tier_results_out[tid] = {k: v for k, v in r.items() if k != "trade_list"}

    return {
        "config_name": cfg_name,
        "cfg": cfg,
        "baseline": baseline_out,
        "tier_results": tier_results_out,
        "contributions": contributions,
        "best_alpha_tier": best_tier,
        "best_alpha_tier_pnl": round(best_tier_pnl, 2),
        "best_alpha_tier_share_pct": round(best_tier_share, 1),
        "tier1_retention_pct": round(tier1_retention, 1),
        "edge_verdict": edge_verdict,
        "edge_detail": edge_detail,
        "timing_s": {
            "baseline": round(t_base, 1),
            "tiers": tier_timings,
            "total": round(total_elapsed, 1),
        },
    }


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta, tier_stats, percentiles, tiers):
    """Generate human-readable universe tiering report."""
    lines = [
        "# HF Universe Tiering Report -- 4H Variant Research",
        "",
        "> **Question**: Does the strategy edge depend on illiquid/low-quality coins?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins']}",
        f"**Max bars**: {meta['max_bars']}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Universe Breakdown
    lines.extend([
        "## 1. Universe Breakdown",
        "",
        "### Tier Definitions",
        "",
        "| Tier | Label | Volume Threshold | Zero-Vol% | Coverage% |",
        "|------|-------|-----------------|-----------|-----------|",
        f"| 1 | Liquid | >= P75 ({percentiles.get('p75_volume', 'N/A'):,.2f}) "
        f"| < {TIER1_ZERO_VOL_MAX}% | >= {TIER1_BAR_COVERAGE_MIN*100:.0f}% |",
        f"| 2 | Mid | >= P25 ({percentiles.get('p25_volume', 'N/A'):,.2f}) "
        f"| < {TIER2_ZERO_VOL_MAX}% | >= {TIER2_BAR_COVERAGE_MIN*100:.0f}% |",
        "| 3 | Illiquid | Below Tier 2 | any | any |",
        "",
        f"**Volume percentiles**: P25={percentiles.get('p25_volume', 0):,.2f}, "
        f"P50={percentiles.get('p50_volume', 0):,.2f}, "
        f"P75={percentiles.get('p75_volume', 0):,.2f}",
        "",
    ])

    # Tier characteristics table
    lines.extend([
        "### Tier Characteristics",
        "",
        "| Tier | Count | Median Vol | Avg Zero-Vol% | Avg Coverage% "
        "| Avg Max Wick | Vol Range |",
        "|------|-------|-----------|---------------|---------------"
        "|-------------|-----------|",
    ])

    for tier_id in sorted(tier_stats.keys()):
        ts = tier_stats[tier_id]
        tier_label = {1: "Liquid", 2: "Mid", 3: "Illiquid"}.get(tier_id, str(tier_id))
        lines.append(
            f"| {tier_id} ({tier_label}) | {ts['count']} "
            f"| {ts['median_volume']:,.2f} "
            f"| {ts['mean_zero_vol_pct']:.1f}% "
            f"| {ts['mean_bar_coverage']:.1f}% "
            f"| {ts['mean_max_wick']:.4f} "
            f"| {ts['min_volume']:,.2f} - {ts['max_volume']:,.2f} |"
        )
    lines.append("")

    # Section 2: Performance Per Tier Per Config
    lines.extend([
        "## 2. Performance Per Tier",
        "",
    ])

    for r in all_results:
        baseline = r["baseline"]
        lines.extend([
            f"### {r['config_name']}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
            "| Subset | Coins | Trades | P&L | PF | WR% | DD% |",
            "|--------|-------|--------|-----|----|-----|-----|",
        ])

        # Baseline row
        lines.append(
            f"| **Full Universe** | {meta['n_coins']} "
            f"| {baseline['trades']} | ${baseline['pnl']:+,.2f} "
            f"| {baseline['pf']} | {baseline['wr']}% | {baseline['dd']}% |"
        )

        # Per-tier rows
        tier_names = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)", 3: "Tier 3 (Illiquid)"}
        for tier_id in sorted(r["tier_results"].keys()):
            tr = r["tier_results"][tier_id]
            n_coins_tier = len(tiers.get(tier_id, []))
            name = tier_names.get(tier_id, f"Tier {tier_id}")
            lines.append(
                f"| {name} | {n_coins_tier} "
                f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
                f"| {tr['pf']} | {tr['wr']}% | {tr['dd']}% |"
            )
        lines.append("")

    # Section 3: P&L Contribution Analysis
    lines.extend([
        "## 3. P&L Contribution Analysis",
        "",
    ])

    for r in all_results:
        contribs = r["contributions"]
        lines.extend([
            f"### {r['config_name']}",
            "",
            "| Tier | P&L | P&L Share | Trades | Trades Share |",
            "|------|-----|-----------|--------|-------------|",
        ])

        for tier_id in sorted(contribs.keys()):
            c = contribs[tier_id]
            tier_label = {1: "Liquid", 2: "Mid", 3: "Illiquid"}.get(tier_id, str(tier_id))
            lines.append(
                f"| {tier_id} ({tier_label}) "
                f"| ${c['pnl']:+,.2f} | {c['pnl_share_pct']:+.1f}% "
                f"| {c['trades']} | {c['trades_share_pct']:.1f}% |"
            )

        lines.extend([
            "",
            f"**Best alpha tier**: Tier {r['best_alpha_tier']} "
            f"(P&L=${r['best_alpha_tier_pnl']:+,.2f}, "
            f"{r['best_alpha_tier_share_pct']:.1f}% of baseline)",
            f"**Tier 1 retention**: {r['tier1_retention_pct']:.1f}% of baseline P&L",
            "",
        ])

    # Section 4: Conclusion
    lines.extend([
        "## 4. Conclusion",
        "",
        "### Edge Survival Verdicts",
        "",
        "| Config | Verdict | Tier 1 Retention | Best Alpha Tier | Interpretation |",
        "|--------|---------|-----------------|-----------------|----------------|",
    ])

    for r in all_results:
        interp = r["edge_detail"]
        if len(interp) > 80:
            interp = interp[:77] + "..."
        lines.append(
            f"| {r['config_name']} | **{r['edge_verdict']}** "
            f"| {r['tier1_retention_pct']:.1f}% "
            f"| Tier {r['best_alpha_tier']} "
            f"| {interp} |"
        )
    lines.append("")

    # Detailed verdict per config
    for r in all_results:
        lines.extend([
            f"**{r['config_name']}**: {r['edge_detail']}",
            "",
        ])

    # Overall assessment
    all_survive = all(r["edge_verdict"] == "EDGE_SURVIVES_TIER1" for r in all_results)
    all_depend = all(r["edge_verdict"] == "EDGE_DEPENDS_ON_ILLIQUID" for r in all_results)

    lines.append("### Overall Assessment")
    lines.append("")

    if all_survive:
        lines.extend([
            "**Edge survives on Tier 1 (Liquid) only.** Both configs retain meaningful ",
            "profitability when restricted to the most liquid coins. The strategy does NOT ",
            "depend on illiquid/microcap symbols for its edge.",
        ])
    elif all_depend:
        lines.extend([
            "**Edge depends on illiquid coins.** Both configs lose most of their ",
            "profitability when restricted to liquid coins only. Live trading on a ",
            "liquid-only universe is NOT recommended without further research.",
        ])
    else:
        lines.extend([
            "**Mixed results.** Some configs survive on liquid coins while others ",
            "depend on illiquid symbols. See per-config verdicts above for details.",
        ])

    lines.append("")

    # Section 5: Recommended Universe Policy
    lines.extend([
        "## 5. Recommended Universe Policy",
        "",
    ])

    if all_survive:
        lines.extend([
            "| Policy | Recommendation |",
            "|--------|---------------|",
            "| Live trading | Tier 1 + Tier 2 (conservative: Tier 1 only) |",
            "| Paper trading | Full universe for research, Tier 1 for validation |",
            "| Monitoring | Track Tier 3 coins for data quality issues |",
            "| Rebalance | Re-tier monthly as liquidity profiles change |",
        ])
    elif all_depend:
        lines.extend([
            "| Policy | Recommendation |",
            "|--------|---------------|",
            "| Live trading | NOT recommended on Tier 1 only |",
            "| Paper trading | Full universe; investigate illiquid coin edge |",
            "| Monitoring | Closely monitor Tier 3 coins for execution risk |",
            "| Risk | Illiquid edge may not be executable at scale |",
        ])
    else:
        lines.extend([
            "| Policy | Recommendation |",
            "|--------|---------------|",
            "| Live trading | Use config with Tier 1 survival for liquid universe |",
            "| Paper trading | Test both configs across tiers |",
            "| Monitoring | Compare Tier 1 vs full universe P&L in paper |",
            "| Risk | Config-dependent; prefer the liquid-surviving config |",
        ])

    lines.extend([
        "",
        "## Tier Thresholds Reference",
        "",
        "| Parameter | Tier 1 (Liquid) | Tier 2 (Mid) | Tier 3 (Illiquid) |",
        "|-----------|----------------|-------------|-------------------|",
        f"| Volume | >= P75 | >= P25 | < P25 |",
        f"| Zero-vol% | < {TIER1_ZERO_VOL_MAX}% | < {TIER2_ZERO_VOL_MAX}% | any |",
        f"| Bar coverage | >= {TIER1_BAR_COVERAGE_MIN*100:.0f}% "
        f"| >= {TIER2_BAR_COVERAGE_MIN*100:.0f}% | any |",
        "",
        "### Verdict Logic",
        "",
        "- `EDGE_SURVIVES_TIER1`: Tier 1 P&L > 0, PF > 1.0, "
        "and retains >= 50% of baseline",
        "- `EDGE_PARTIAL_TIER1`: Tier 1 P&L > 0 and retains >= 20% of baseline",
        "- `EDGE_DEPENDS_ON_ILLIQUID`: Tier 1 retention < 20% or P&L <= 0",
        "- `BASELINE_NEGATIVE`: Full universe has no positive edge",
        "",
        "---",
        f"*Generated by hf_universe_tiering.py -- 4H variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Universe Tiering -- 4H variant research"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Universe Tiering -- 4H Variant Research")
    print("  Question: Does the strategy edge depend on illiquid coins?")
    print("=" * 70)
    print(f"  Universe: {args.universe}")

    # 1. Load candle data
    data, coins, data_path = load_data(args.universe)
    n_bars = len(data[coins[0]]) if coins else 0
    print(f"  Loaded {len(coins)} coins, {n_bars} bars from {Path(data_path).name}")

    t_start = time.time()

    # 2. Compute per-coin liquidity metrics
    print("\n  Computing per-coin liquidity metrics...")
    metrics, max_bars = compute_coin_metrics(data, coins)
    print(f"  Computed metrics for {len(metrics)} coins (max_bars={max_bars})")

    # 3. Assign tiers
    print("  Assigning tiers...")
    tiers, percentiles = assign_tiers(metrics, coins)
    for tier_id in sorted(tiers.keys()):
        tier_label = {1: "Liquid", 2: "Mid", 3: "Illiquid"}.get(tier_id, str(tier_id))
        print(f"    Tier {tier_id} ({tier_label}): {len(tiers[tier_id])} coins")

    # 4. Compute tier statistics
    tier_stats = compute_tier_stats(tiers, metrics)

    # 5. Run tiering analysis for each config
    all_results = []
    for cfg_name, cfg in CONFIGS.items():
        result = run_tiering_analysis(cfg_name, cfg, data, coins, tiers)
        all_results.append(result)

    total_time = time.time() - t_start

    # 6. Build meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "max_bars": max_bars,
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "configs_tested": list(CONFIGS.keys()),
        "tier_definitions": {
            "tier1": {
                "label": "Liquid",
                "volume_threshold": "P75",
                "zero_vol_max_pct": TIER1_ZERO_VOL_MAX,
                "bar_coverage_min": TIER1_BAR_COVERAGE_MIN,
            },
            "tier2": {
                "label": "Mid",
                "volume_threshold": "P25",
                "zero_vol_max_pct": TIER2_ZERO_VOL_MAX,
                "bar_coverage_min": TIER2_BAR_COVERAGE_MIN,
            },
            "tier3": {
                "label": "Illiquid",
                "volume_threshold": "Below P25",
                "zero_vol_max_pct": "any",
                "bar_coverage_min": "any",
            },
        },
        "volume_percentiles": percentiles,
    }

    # 7. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "universe_tiering_001.json"

    # Build per-tier coin lists for JSON (with metrics)
    tier_coins_detail = {}
    for tier_id in sorted(tiers.keys()):
        tier_coins_detail[str(tier_id)] = {
            "coins": tiers[tier_id],
            "count": len(tiers[tier_id]),
            "stats": tier_stats[tier_id],
        }

    json_output = {
        "meta": meta,
        "tier_breakdown": tier_coins_detail,
        "results": {r["config_name"]: r for r in all_results},
    }

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 8. Write markdown report
    md_path = REPORTS_DIR / "universe_tiering_001.md"
    md = generate_markdown(all_results, meta, tier_stats, percentiles, tiers)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 9. Final summary
    print("\n" + "=" * 70)
    print("  UNIVERSE TIERING SUMMARY (4H variant research)")
    print("=" * 70)

    print(f"\n  {'Tier':<22} {'Count':>6} {'Median Vol':>14} {'Zero-Vol%':>10} {'Coverage%':>10}")
    print("  " + "-" * 62)
    for tier_id in sorted(tier_stats.keys()):
        ts = tier_stats[tier_id]
        tier_label = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)", 3: "Tier 3 (Illiquid)"}.get(
            tier_id, f"Tier {tier_id}")
        print(f"  {tier_label:<22} {ts['count']:>6} {ts['median_volume']:>14,.2f} "
              f"{ts['mean_zero_vol_pct']:>9.1f}% {ts['mean_bar_coverage']:>9.1f}%")

    print(f"\n  {'Config':<20} {'Verdict':<28} {'T1 Retention':>12} {'Best Tier':>10}")
    print("  " + "-" * 70)
    for r in all_results:
        print(f"  {r['config_name']:<20} {r['edge_verdict']:<28} "
              f"{r['tier1_retention_pct']:>11.1f}% "
              f"{'Tier ' + str(r['best_alpha_tier']):>10}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()
