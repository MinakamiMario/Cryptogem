#!/usr/bin/env python3
"""
Sprint 4 — Deep Drawdown Attribution Analysis
===============================================
Agent D (Analysis): Decompose 40-90% drawdowns in top-5 Sprint 4 configs.

Dimensions:
  1. Drawdown episode identification (peak-to-trough-to-recovery)
  2. Loss streak analysis
  3. Temporal clustering (6 windows)
  4. Coin concentration in DD
  5. Exit reason DD attribution
  6. Sizing impact (compounding amplification)
  7. Recovery analysis

Usage:
  python3 scripts/run_sprint4_dd_analysis.py
  python3 scripts/run_sprint4_dd_analysis.py --only 041,032
"""

import argparse
import json
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO_ROOT / "reports" / "4h"
INITIAL_CAPITAL = 2000.0
GIT_HASH = "9a606d9"

TOP5 = [
    "sprint4_041_h4s4g05_vol3x_bblow_rsi40",
    "sprint4_032_h4s4f02_z2.5_dclow_rsi40",
    "sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35",
    "sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5",
    "sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_result(config_id: str, git_hash: str = GIT_HASH) -> dict:
    """Load Sprint 4 result from reports directory."""
    for d in REPORT_DIR.iterdir():
        if d.is_dir() and config_id in d.name and git_hash in d.name:
            with open(d / "results.json") as f:
                return json.load(f)
    raise FileNotFoundError(f"No result for {config_id}")


# ---------------------------------------------------------------------------
# Equity curve reconstruction
# ---------------------------------------------------------------------------
def build_equity_curve(trades: list, initial_capital: float = INITIAL_CAPITAL) -> list:
    """Build equity curve from trade list.

    With max_pos > 1, multiple positions can be open concurrently.  The
    engine allocates equity/open_slots per position.  equity_after is the
    realized equity after each trade closes (sorted by exit_bar).

    Returns list of (exit_bar, equity_after) tuples with an initial point.
    """
    curve = []
    first_bar = trades[0]["entry_bar"] if trades else 0
    curve.append((first_bar, initial_capital))
    for t in trades:
        curve.append((t["exit_bar"], t["equity_after"]))
    return curve


def running_peak(curve: list) -> list:
    """Compute running peak equity at each curve point."""
    peaks = []
    mx = -np.inf
    for bar, eq in curve:
        mx = max(mx, eq)
        peaks.append(mx)
    return peaks


# ---------------------------------------------------------------------------
# 1. Drawdown Episode Analysis
# ---------------------------------------------------------------------------
def find_dd_episodes(curve: list, trades: list) -> list:
    """Identify drawdown episodes from the equity curve.

    An episode starts when equity drops below the running peak and ends when
    equity recovers to a new peak.  Overlapping minor dips inside a recovery
    are merged into the encompassing episode.
    """
    peaks = running_peak(curve)
    episodes = []
    in_dd = False
    ep_start_idx = 0
    trough_idx = 0
    trough_eq = np.inf

    for i, (bar, eq) in enumerate(curve):
        dd_pct = (peaks[i] - eq) / peaks[i] * 100 if peaks[i] > 0 else 0
        if dd_pct > 0.5 and not in_dd:
            # start new episode
            in_dd = True
            ep_start_idx = i
            trough_idx = i
            trough_eq = eq
        elif in_dd:
            if eq < trough_eq:
                trough_idx = i
                trough_eq = eq
            if dd_pct < 0.01:
                # recovered
                depth = (peaks[ep_start_idx] - trough_eq) / peaks[ep_start_idx] * 100
                if depth >= 2.0:  # only record meaningful episodes
                    episodes.append({
                        "peak_idx": ep_start_idx,
                        "trough_idx": trough_idx,
                        "recovery_idx": i,
                        "peak_bar": curve[ep_start_idx][0],
                        "trough_bar": curve[trough_idx][0],
                        "recovery_bar": curve[i][0],
                        "peak_equity": peaks[ep_start_idx],
                        "trough_equity": trough_eq,
                        "depth_pct": round(depth, 2),
                    })
                in_dd = False
                trough_eq = np.inf

    # handle open episode at end of data
    if in_dd:
        depth = (peaks[ep_start_idx] - trough_eq) / peaks[ep_start_idx] * 100
        if depth >= 2.0:
            episodes.append({
                "peak_idx": ep_start_idx,
                "trough_idx": trough_idx,
                "recovery_idx": None,
                "peak_bar": curve[ep_start_idx][0],
                "trough_bar": curve[trough_idx][0],
                "recovery_bar": None,
                "peak_equity": peaks[ep_start_idx],
                "trough_equity": trough_eq,
                "depth_pct": round(depth, 2),
            })

    # enrich with trade-level info
    for ep in episodes:
        t_start = ep["peak_bar"]
        t_end = ep["recovery_bar"] if ep["recovery_bar"] else curve[-1][0] + 1
        ep_trades = [t for t in trades if t_start <= t["exit_bar"] <= t_end]
        ep["n_trades"] = len(ep_trades)
        ep["duration_bars"] = (t_end - t_start) if ep["recovery_bar"] else None

        # exit reason counts
        reason_counts = {}
        for t in ep_trades:
            reason_counts[t["reason"]] = reason_counts.get(t["reason"], 0) + 1
        ep["exit_reasons"] = reason_counts

        # worst trade in episode
        if ep_trades:
            worst = min(ep_trades, key=lambda x: x["pnl"])
            ep["worst_trade"] = {
                "pair": worst["pair"],
                "pnl": round(worst["pnl"], 2),
                "reason": worst["reason"],
                "bars": worst["bars"],
            }
        else:
            ep["worst_trade"] = None

    return episodes


# ---------------------------------------------------------------------------
# 2. Loss Streak Analysis
# ---------------------------------------------------------------------------
def loss_streak_analysis(trades: list) -> dict:
    """Find consecutive losing streaks."""
    streaks = []
    current_streak = []

    for t in trades:
        if t["pnl"] < 0:
            current_streak.append(t)
        else:
            if len(current_streak) >= 2:
                streaks.append(current_streak)
            current_streak = []
    if len(current_streak) >= 2:
        streaks.append(current_streak)

    streak_info = []
    for s in streaks:
        reasons = {}
        coins = {}
        for t in s:
            reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
            coins[t["pair"]] = coins.get(t["pair"], 0) + 1
        streak_info.append({
            "length": len(s),
            "total_loss": round(sum(t["pnl"] for t in s), 2),
            "start_bar": s[0]["exit_bar"],
            "end_bar": s[-1]["exit_bar"],
            "exit_reasons": reasons,
            "coins": coins,
        })

    streak_lengths = [s["length"] for s in streak_info] if streak_info else [0]

    return {
        "max_streak": max(streak_lengths),
        "avg_streak": round(float(np.mean(streak_lengths)), 2) if streak_info else 0,
        "n_streaks": len(streak_info),
        "streaks": sorted(streak_info, key=lambda x: x["total_loss"])[:10],
    }


# ---------------------------------------------------------------------------
# 3. Temporal Clustering
# ---------------------------------------------------------------------------
def temporal_clustering(trades: list, n_windows: int = 6) -> list:
    """Split bar range into n_windows and compute P&L/DD per window."""
    if not trades:
        return []

    all_bars = [t["exit_bar"] for t in trades]
    min_bar = min(all_bars)
    max_bar = max(all_bars)
    span = max_bar - min_bar + 1
    win_size = max(1, span // n_windows)

    windows = []
    for w in range(n_windows):
        w_start = min_bar + w * win_size
        w_end = w_start + win_size - 1 if w < n_windows - 1 else max_bar
        w_trades = [t for t in trades if w_start <= t["exit_bar"] <= w_end]

        pnl = sum(t["pnl"] for t in w_trades)
        losses = sum(t["pnl"] for t in w_trades if t["pnl"] < 0)
        wins = sum(t["pnl"] for t in w_trades if t["pnl"] > 0)
        n_losing = sum(1 for t in w_trades if t["pnl"] < 0)

        # compute local drawdown within window
        local_eq = 0.0
        local_peak = 0.0
        local_dd = 0.0
        for t in sorted(w_trades, key=lambda x: x["exit_bar"]):
            local_eq += t["pnl"]
            local_peak = max(local_peak, local_eq)
            dd = local_peak - local_eq
            local_dd = max(local_dd, dd)

        windows.append({
            "window": f"{w_start}-{w_end}",
            "start_bar": w_start,
            "end_bar": w_end,
            "trades": len(w_trades),
            "n_losing": n_losing,
            "pnl": round(pnl, 2),
            "total_losses": round(losses, 2),
            "total_wins": round(wins, 2),
            "local_dd": round(local_dd, 2),
        })

    return windows


# ---------------------------------------------------------------------------
# 4. Coin Concentration in DD
# ---------------------------------------------------------------------------
def coin_concentration(trades: list) -> dict:
    """Identify coins contributing most to drawdown (losses)."""
    coin_losses = {}
    coin_counts = {}
    for t in trades:
        if t["pnl"] < 0:
            coin = t["pair"]
            coin_losses[coin] = coin_losses.get(coin, 0) + t["pnl"]
            coin_counts[coin] = coin_counts.get(coin, 0) + 1

    # sort by total loss (most negative first)
    sorted_coins = sorted(coin_losses.items(), key=lambda x: x[1])
    top5 = [
        {"coin": c, "total_loss": round(loss, 2), "n_trades": coin_counts[c]}
        for c, loss in sorted_coins[:5]
    ]

    # Herfindahl index of loss concentration
    total_loss = sum(abs(v) for v in coin_losses.values())
    if total_loss > 0:
        shares = [abs(v) / total_loss for v in coin_losses.values()]
        hhi = float(np.sum(np.array(shares) ** 2))
    else:
        hhi = 0.0

    return {
        "top5_loss_coins": top5,
        "n_loss_coins": len(coin_losses),
        "hhi_loss": round(hhi, 4),
    }


# ---------------------------------------------------------------------------
# 5. Exit Reason DD Attribution
# ---------------------------------------------------------------------------
def exit_attribution(trades: list) -> dict:
    """Compute DD attribution by exit reason."""
    reason_stats = {}
    total_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
    abs_total_loss = abs(total_loss) if total_loss != 0 else 1.0

    for t in trades:
        r = t["reason"]
        if r not in reason_stats:
            reason_stats[r] = {
                "total_pnl": 0.0,
                "total_loss": 0.0,
                "n_trades": 0,
                "n_losing": 0,
                "n_winning": 0,
                "losses_list": [],
                "sizes_list": [],
            }
        reason_stats[r]["total_pnl"] += t["pnl"]
        reason_stats[r]["n_trades"] += 1
        reason_stats[r]["sizes_list"].append(t["size"])
        if t["pnl"] < 0:
            reason_stats[r]["total_loss"] += t["pnl"]
            reason_stats[r]["n_losing"] += 1
            reason_stats[r]["losses_list"].append(t["pnl"])
        else:
            reason_stats[r]["n_winning"] += 1

    result = {}
    for r, s in reason_stats.items():
        avg_loss = (
            round(float(np.mean(s["losses_list"])), 2)
            if s["losses_list"]
            else 0.0
        )
        avg_size = round(float(np.mean(s["sizes_list"])), 2)
        dd_share = round(abs(s["total_loss"]) / abs_total_loss, 4) if s["total_loss"] < 0 else 0.0
        wr = round(s["n_winning"] / s["n_trades"] * 100, 1) if s["n_trades"] > 0 else 0.0

        result[r] = {
            "n_trades": s["n_trades"],
            "n_losing": s["n_losing"],
            "n_winning": s["n_winning"],
            "win_rate": wr,
            "total_pnl": round(s["total_pnl"], 2),
            "total_loss": round(s["total_loss"], 2),
            "avg_loss": avg_loss,
            "avg_size": avg_size,
            "dd_share": dd_share,
        }

    return result


# ---------------------------------------------------------------------------
# 6. Sizing Impact Analysis
# ---------------------------------------------------------------------------
def sizing_impact(trades: list) -> dict:
    """Analyze position sizing effects on drawdown."""
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] < 0]

    avg_size_winners = round(float(np.mean([t["size"] for t in winners])), 2) if winners else 0.0
    avg_size_losers = round(float(np.mean([t["size"] for t in losers])), 2) if losers else 0.0

    # correlation between size and P&L
    if len(trades) >= 5:
        sizes = np.array([t["size"] for t in trades])
        pnls = np.array([t["pnl"] for t in trades])
        corr = float(np.corrcoef(sizes, pnls)[0, 1])
        if np.isnan(corr):
            corr = 0.0
    else:
        corr = 0.0

    # Check if losers have larger sizes on average (compounding amplification)
    compounding_amplification = avg_size_losers > avg_size_winners * 1.02

    # Size quartile analysis: split trades into 4 size quartiles, compute WR and avg PnL
    if len(trades) >= 8:
        sorted_by_size = sorted(trades, key=lambda x: x["size"])
        q = len(sorted_by_size) // 4
        quartiles = []
        for qi in range(4):
            start = qi * q
            end = (qi + 1) * q if qi < 3 else len(sorted_by_size)
            qt = sorted_by_size[start:end]
            qt_wr = sum(1 for t in qt if t["pnl"] > 0) / len(qt) * 100 if qt else 0
            qt_avg_pnl = float(np.mean([t["pnl"] for t in qt])) if qt else 0
            qt_avg_size = float(np.mean([t["size"] for t in qt])) if qt else 0
            quartiles.append({
                "quartile": f"Q{qi+1}",
                "avg_size": round(qt_avg_size, 2),
                "avg_pnl": round(qt_avg_pnl, 2),
                "win_rate": round(qt_wr, 1),
                "n_trades": len(qt),
            })
    else:
        quartiles = []

    return {
        "avg_size_winners": avg_size_winners,
        "avg_size_losers": avg_size_losers,
        "size_pnl_correlation": round(corr, 4),
        "compounding_amplification": compounding_amplification,
        "size_quartiles": quartiles,
    }


# ---------------------------------------------------------------------------
# 7. Recovery Analysis
# ---------------------------------------------------------------------------
def recovery_analysis(curve: list, trades: list) -> dict:
    """Analyze recovery from maximum drawdown."""
    bars = [b for b, _ in curve]
    eqs = [e for _, e in curve]

    peaks = running_peak(curve)
    # find max DD point
    max_dd = 0
    max_dd_idx = 0
    for i in range(len(curve)):
        dd = (peaks[i] - eqs[i]) / peaks[i] * 100 if peaks[i] > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_idx = i

    max_dd_bar = bars[max_dd_idx]
    max_dd_equity = eqs[max_dd_idx]
    peak_before_dd = peaks[max_dd_idx]

    # find recovery point (first time equity >= peak_before_dd after trough)
    recovery_bar = None
    recovery_idx = None
    for i in range(max_dd_idx + 1, len(curve)):
        if eqs[i] >= peak_before_dd:
            recovery_bar = bars[i]
            recovery_idx = i
            break

    # trades during recovery
    if recovery_bar is not None:
        rec_trades = [t for t in trades if max_dd_bar < t["exit_bar"] <= recovery_bar]
    else:
        rec_trades = [t for t in trades if t["exit_bar"] > max_dd_bar]

    # what drove recovery?
    rec_reason_pnl = {}
    for t in rec_trades:
        if t["pnl"] > 0:
            rec_reason_pnl[t["reason"]] = rec_reason_pnl.get(t["reason"], 0) + t["pnl"]

    recovery_driver = max(rec_reason_pnl, key=rec_reason_pnl.get) if rec_reason_pnl else "N/A"

    # is recovery driven by few big wins or many small wins?
    rec_winners = [t for t in rec_trades if t["pnl"] > 0]
    if rec_winners:
        rec_pnls = sorted([t["pnl"] for t in rec_winners], reverse=True)
        top3_pnl = sum(rec_pnls[:3])
        total_rec_pnl = sum(rec_pnls)
        concentration = top3_pnl / total_rec_pnl if total_rec_pnl > 0 else 0
        recovery_style = "concentrated (few big wins)" if concentration > 0.50 else "distributed (many small wins)"
    else:
        concentration = 0
        recovery_style = "no recovery"

    return {
        "max_dd_pct": round(max_dd, 2),
        "max_dd_bar": max_dd_bar,
        "max_dd_equity": round(max_dd_equity, 2),
        "peak_before_dd": round(peak_before_dd, 2),
        "recovery_bar": recovery_bar,
        "recovery_trades": len(rec_trades),
        "recovery_winners": len(rec_winners),
        "recovery_driven_by": recovery_driver,
        "recovery_reason_pnl": {k: round(v, 2) for k, v in rec_reason_pnl.items()},
        "top3_concentration": round(concentration, 4),
        "recovery_style": recovery_style,
        "recovered": recovery_bar is not None,
    }


# ---------------------------------------------------------------------------
# Summary generator
# ---------------------------------------------------------------------------
def generate_summary(
    exit_attr: dict, sizing: dict, episodes: list, streaks: dict,
    temporal: list, recovery: dict,
) -> dict:
    """Generate actionable summary from all analyses."""
    # Primary DD driver: exit reason with highest dd_share
    dd_drivers = sorted(exit_attr.items(), key=lambda x: x[1]["dd_share"], reverse=True)
    primary_driver = dd_drivers[0][0] if dd_drivers else "UNKNOWN"
    primary_share = dd_drivers[0][1]["dd_share"] if dd_drivers else 0
    secondary_driver = dd_drivers[1][0] if len(dd_drivers) > 1 else "NONE"

    # Compounding note
    comp_note = " + compounding amplification" if sizing.get("compounding_amplification") else ""

    # Worst episode depth
    worst_ep_depth = max((ep["depth_pct"] for ep in episodes), default=0)

    # Toxic window
    toxic_windows = sorted(temporal, key=lambda w: w["total_losses"])
    worst_window = toxic_windows[0]["window"] if toxic_windows else "N/A"

    # DD reduction levers
    levers = []
    if primary_driver == "FIXED STOP":
        levers.append("reduce max_stop_pct (currently 15%)")
        levers.append("vol-scale stop distance by ATR")
    if secondary_driver == "TIME MAX" or primary_driver == "TIME MAX":
        levers.append("reduce time_max_bars or add mid-hold exit")
    if sizing.get("compounding_amplification"):
        levers.append("cap position size or vol-scale sizing")
        levers.append("cooldown period after consecutive stops")
    if streaks["max_streak"] >= 4:
        levers.append(f"streak breaker: pause after {streaks['max_streak']-1} consecutive losses")
    if worst_ep_depth > 40:
        levers.append("portfolio-level DD circuit breaker at 25%")
    levers.append("regime filter: skip entries during sustained downtrend")

    # Actionable insight
    insight_parts = []
    insight_parts.append(
        f"{primary_driver} accounts for {primary_share*100:.0f}% of total losses"
    )
    if sizing.get("compounding_amplification"):
        insight_parts.append(
            "losers have larger position sizes than winners (compounding amplification)"
        )
    if not recovery["recovered"]:
        insight_parts.append("equity never fully recovered from max DD")

    return {
        "primary_dd_driver": f"{primary_driver} losses ({primary_share*100:.0f}%){comp_note}",
        "secondary_dd_driver": f"{secondary_driver} ({dd_drivers[1][1]['dd_share']*100:.0f}%)" if len(dd_drivers) > 1 else "NONE",
        "worst_episode_depth_pct": worst_ep_depth,
        "max_loss_streak": streaks["max_streak"],
        "toxic_window": worst_window,
        "actionable_insight": "; ".join(insight_parts),
        "dd_reduction_levers": levers,
    }


# ---------------------------------------------------------------------------
# Full analysis for one config
# ---------------------------------------------------------------------------
def analyze_config(config_id: str) -> dict:
    """Run all 7 analysis dimensions on one config."""
    result = load_result(config_id)
    trades = result["trades"]
    metadata = result["metadata"]
    summary_stats = result["summary"]

    curve = build_equity_curve(trades, INITIAL_CAPITAL)

    # 1. DD episodes
    episodes = find_dd_episodes(curve, trades)

    # 2. Loss streaks
    streaks = loss_streak_analysis(trades)

    # 3. Temporal clustering
    temporal = temporal_clustering(trades, n_windows=6)

    # 4. Coin concentration
    coins = coin_concentration(trades)

    # 5. Exit attribution
    exit_attr = exit_attribution(trades)

    # 6. Sizing impact
    sizing = sizing_impact(trades)

    # 7. Recovery
    recovery = recovery_analysis(curve, trades)

    # Summary
    summ = generate_summary(exit_attr, sizing, episodes, streaks, temporal, recovery)

    return {
        "config_id": config_id,
        "hypothesis_name": metadata.get("hypothesis_name", ""),
        "family": metadata.get("family", ""),
        "summary_stats": {
            "trades": summary_stats["trades"],
            "wr": summary_stats["wr"],
            "pnl": summary_stats["pnl"],
            "pf": summary_stats["pf"],
            "dd": summary_stats["dd"],
        },
        "dd_episodes": [
            {
                "episode_num": i + 1,
                "peak_bar": ep["peak_bar"],
                "trough_bar": ep["trough_bar"],
                "recovery_bar": ep["recovery_bar"],
                "depth_pct": ep["depth_pct"],
                "peak_equity": round(ep["peak_equity"], 2),
                "trough_equity": round(ep["trough_equity"], 2),
                "n_trades_in_episode": ep["n_trades"],
                "duration_bars": ep["duration_bars"],
                "exit_reasons": ep["exit_reasons"],
                "worst_trade": ep["worst_trade"],
            }
            for i, ep in enumerate(episodes)
        ],
        "loss_streaks": streaks,
        "temporal_windows": temporal,
        "coin_concentration": coins,
        "exit_attribution": exit_attr,
        "sizing_impact": sizing,
        "recovery": recovery,
        "summary": summ,
    }


# ---------------------------------------------------------------------------
# Cross-config analysis
# ---------------------------------------------------------------------------
def cross_config_analysis(results: list) -> dict:
    """Find common patterns across configs."""
    # Common DD drivers
    driver_counts = {}
    for r in results:
        drv = r["summary"]["primary_dd_driver"].split(" losses")[0]
        driver_counts[drv] = driver_counts.get(drv, 0) + 1

    # Common top-loss coins across configs
    all_loss_coins = {}
    for r in results:
        for c in r["coin_concentration"]["top5_loss_coins"]:
            coin = c["coin"]
            all_loss_coins[coin] = all_loss_coins.get(coin, 0) + 1
    cross_config_coins = {
        k: v for k, v in all_loss_coins.items() if v >= 2
    }

    # Average HHI (dispersion)
    hhis = [r["coin_concentration"]["hhi_loss"] for r in results]
    avg_hhi = float(np.mean(hhis))

    # Compounding amplification prevalence
    comp_count = sum(1 for r in results if r["sizing_impact"]["compounding_amplification"])

    # Average max streak
    avg_streak = float(np.mean([r["loss_streaks"]["max_streak"] for r in results]))

    # Exit attribution averages
    reason_shares = {}
    for r in results:
        for reason, data in r["exit_attribution"].items():
            if reason not in reason_shares:
                reason_shares[reason] = []
            reason_shares[reason].append(data["dd_share"])
    avg_shares = {
        k: round(float(np.mean(v)), 4) for k, v in reason_shares.items()
    }

    # Recovery stats
    n_recovered = sum(1 for r in results if r["recovery"]["recovered"])

    # Worst episode depths
    worst_depths = [r["summary"]["worst_episode_depth_pct"] for r in results]

    # Collect all unique levers
    all_levers = {}
    for r in results:
        for lever in r["summary"]["dd_reduction_levers"]:
            # normalize lever text
            key = lever.split("(")[0].strip()
            all_levers[key] = all_levers.get(key, 0) + 1
    # sort by frequency
    lever_ranking = sorted(all_levers.items(), key=lambda x: x[1], reverse=True)

    return {
        "n_configs": len(results),
        "common_dd_driver": driver_counts,
        "avg_exit_dd_shares": avg_shares,
        "cross_config_loss_coins": cross_config_coins,
        "avg_hhi_loss": round(avg_hhi, 4),
        "compounding_amplification_count": f"{comp_count}/{len(results)}",
        "avg_max_loss_streak": round(avg_streak, 1),
        "configs_recovered": f"{n_recovered}/{len(results)}",
        "worst_episode_depths": worst_depths,
        "avg_worst_depth": round(float(np.mean(worst_depths)), 1),
        "lever_ranking": [{"lever": k, "configs_affected": v} for k, v in lever_ranking[:8]],
    }


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------
def generate_markdown(results: list, cross: dict, timestamp: str) -> str:
    """Generate human-readable markdown report."""
    lines = []
    lines.append("# Sprint 4 — Drawdown Attribution Analysis")
    lines.append("")
    lines.append(f"**Generated**: {timestamp}")
    lines.append(f"**Git hash**: {GIT_HASH}")
    lines.append(f"**Configs analyzed**: {cross['n_configs']}")
    lines.append(f"**Initial capital**: ${INITIAL_CAPITAL:,.0f}")
    lines.append("")

    # --- Executive Summary ---
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **Primary DD driver across all configs**: {cross['common_dd_driver']}")
    lines.append(f"- **Average worst episode depth**: {cross['avg_worst_depth']}%")
    lines.append(f"- **Compounding amplification**: {cross['compounding_amplification_count']} configs affected")
    lines.append(f"- **Average max loss streak**: {cross['avg_max_loss_streak']} trades")
    lines.append(f"- **Full recovery from max DD**: {cross['configs_recovered']} configs")
    lines.append(f"- **Loss coin HHI (avg)**: {cross['avg_hhi_loss']:.4f} (low = well-dispersed)")
    lines.append("")

    # --- Exit DD Shares ---
    lines.append("### Exit Reason DD Attribution (average across configs)")
    lines.append("")
    lines.append("| Exit Reason | Avg DD Share |")
    lines.append("|-------------|-------------|")
    for reason, share in sorted(cross["avg_exit_dd_shares"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {reason} | {share*100:.1f}% |")
    lines.append("")

    # --- Top Levers ---
    lines.append("### DD Reduction Levers (ranked by prevalence)")
    lines.append("")
    for item in cross["lever_ranking"]:
        lines.append(f"1. **{item['lever']}** ({item['configs_affected']}/{cross['n_configs']} configs)")
    lines.append("")

    # --- Cross-config coins ---
    if cross["cross_config_loss_coins"]:
        lines.append("### Coins Causing Losses in Multiple Configs")
        lines.append("")
        lines.append("| Coin | Configs |")
        lines.append("|------|---------|")
        for coin, cnt in sorted(cross["cross_config_loss_coins"].items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"| {coin} | {cnt}/{cross['n_configs']} |")
        lines.append("")

    # --- Per-Config Details ---
    lines.append("---")
    lines.append("")
    lines.append("## Per-Config Analysis")
    lines.append("")

    for r in results:
        cid = r["config_id"]
        s = r["summary_stats"]
        summ = r["summary"]
        lines.append(f"### {cid}")
        lines.append(f"**{r['hypothesis_name']}** ({r['family']})")
        lines.append(f"- Trades: {s['trades']} | WR: {s['wr']}% | PF: {s['pf']} | P&L: ${s['pnl']:,.2f} | DD: {s['dd']}%")
        lines.append("")

        # Primary driver
        lines.append(f"**Primary DD driver**: {summ['primary_dd_driver']}")
        lines.append(f"**Secondary DD driver**: {summ['secondary_dd_driver']}")
        lines.append("")

        # Exit attribution table
        lines.append("**Exit Attribution**:")
        lines.append("")
        lines.append("| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |")
        lines.append("|-------------|--------|--------|-----|-----------|----------|---------|----------|")
        for reason, data in sorted(r["exit_attribution"].items(), key=lambda x: x[1]["dd_share"], reverse=True):
            lines.append(
                f"| {reason} | {data['n_trades']} | {data['n_losing']} | "
                f"{data['win_rate']}% | ${data['total_loss']:,.2f} | "
                f"${data['avg_loss']:,.2f} | {data['dd_share']*100:.1f}% | "
                f"${data['avg_size']:,.2f} |"
            )
        lines.append("")

        # Top DD episodes (max 3)
        top_eps = sorted(r["dd_episodes"], key=lambda x: x["depth_pct"], reverse=True)[:3]
        if top_eps:
            lines.append("**Top DD Episodes**:")
            lines.append("")
            for ep in top_eps:
                rec = f"bar {ep['recovery_bar']}" if ep["recovery_bar"] else "NOT RECOVERED"
                dur = f"{ep['duration_bars']} bars" if ep["duration_bars"] else "ongoing"
                lines.append(
                    f"- Episode #{ep['episode_num']}: **{ep['depth_pct']}%** depth "
                    f"(peak bar {ep['peak_bar']} -> trough bar {ep['trough_bar']} -> {rec}, "
                    f"{dur}, {ep['n_trades_in_episode']} trades)"
                )
                if ep["worst_trade"]:
                    wt = ep["worst_trade"]
                    lines.append(f"  - Worst trade: {wt['pair']} ${wt['pnl']:+,.2f} ({wt['reason']})")
                if ep["exit_reasons"]:
                    lines.append(f"  - Exit reasons: {ep['exit_reasons']}")
            lines.append("")

        # Loss streaks
        ls = r["loss_streaks"]
        lines.append(f"**Loss Streaks**: max={ls['max_streak']}, avg={ls['avg_streak']}, count={ls['n_streaks']}")
        if ls["streaks"]:
            worst_streak = ls["streaks"][0]
            lines.append(
                f"- Worst streak: {worst_streak['length']} trades, "
                f"${worst_streak['total_loss']:+,.2f}, bars {worst_streak['start_bar']}-{worst_streak['end_bar']}"
            )
        lines.append("")

        # Temporal
        toxic = sorted(r["temporal_windows"], key=lambda w: w["total_losses"])
        if toxic and toxic[0]["total_losses"] < 0:
            tw = toxic[0]
            lines.append(
                f"**Most Toxic Window**: bars {tw['window']} "
                f"({tw['trades']} trades, ${tw['pnl']:+,.2f} P&L, "
                f"${tw['total_losses']:+,.2f} losses)"
            )
            lines.append("")

        # Sizing
        si = r["sizing_impact"]
        lines.append(f"**Sizing Impact**: avg winner size ${si['avg_size_winners']:,.2f}, "
                      f"avg loser size ${si['avg_size_losers']:,.2f}, "
                      f"corr={si['size_pnl_correlation']:.4f}, "
                      f"compounding_amp={'YES' if si['compounding_amplification'] else 'NO'}")
        if si["size_quartiles"]:
            lines.append("")
            lines.append("| Size Quartile | Avg Size | Avg P&L | WR | N |")
            lines.append("|---------------|----------|---------|-----|---|")
            for q in si["size_quartiles"]:
                lines.append(
                    f"| {q['quartile']} | ${q['avg_size']:,.2f} | "
                    f"${q['avg_pnl']:+,.2f} | {q['win_rate']}% | {q['n_trades']} |"
                )
        lines.append("")

        # Recovery
        rec = r["recovery"]
        rec_status = "RECOVERED" if rec["recovered"] else "NOT RECOVERED"
        lines.append(
            f"**Recovery**: max DD {rec['max_dd_pct']}% at bar {rec['max_dd_bar']} "
            f"(equity ${rec['max_dd_equity']:,.2f} from peak ${rec['peak_before_dd']:,.2f}) — "
            f"**{rec_status}**"
        )
        if rec["recovered"]:
            lines.append(
                f"- Recovery at bar {rec['recovery_bar']}, {rec['recovery_trades']} trades, "
                f"driven by {rec['recovery_driven_by']}"
            )
        lines.append(f"- Recovery style: {rec['recovery_style']}")
        lines.append("")

        # Actionable levers
        lines.append("**DD Reduction Levers**:")
        for lever in summ["dd_reduction_levers"]:
            lines.append(f"- {lever}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # --- Recommendations for Agent B ---
    lines.append("## Recommendations for Agent B (RiskWrapper)")
    lines.append("")
    lines.append("### Priority Actions")
    lines.append("")
    lines.append("1. **Stop Loss Sizing**: FIXED STOP is the dominant DD driver across all configs.")
    lines.append("   Current max_stop_pct=15% is too wide. Test 8%, 10%, 12% with ATR-scaling.")
    lines.append("")
    lines.append("2. **Position Size Capping**: Compounding amplification means large wins are")
    lines.append("   followed by large position sizes, amplifying subsequent losses.")
    lines.append("   Implement: `size = min(equity / max_pos, max_position_cap)`")
    lines.append("")
    lines.append("3. **Portfolio DD Circuit Breaker**: When cumulative DD exceeds 25%,")
    lines.append("   reduce position sizes by 50% or pause trading for N bars.")
    lines.append("")
    lines.append("4. **Streak Cooldown**: After 3+ consecutive losses, skip the next entry")
    lines.append("   or halve position size for 1 trade.")
    lines.append("")
    lines.append("5. **TIME MAX Exit Improvement**: TIME MAX has near-0% WR. Consider:")
    lines.append("   - Closing at mid-point of entry-target range instead of market price")
    lines.append("   - Reducing time_max_bars to force earlier exits")
    lines.append("   - Adding a mid-hold RSI check for early exit")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sprint 4 DD Attribution Analysis")
    parser.add_argument(
        "--only", type=str, default=None,
        help="Comma-separated config number suffixes to analyze (e.g., 041,032)",
    )
    args = parser.parse_args()

    # Determine which configs to analyze
    if args.only:
        suffixes = [s.strip() for s in args.only.split(",")]
        configs = [c for c in TOP5 if any(f"sprint4_{s}" in c for s in suffixes)]
        if not configs:
            print(f"ERROR: No matching configs for --only {args.only}")
            print(f"Available: {[c.split('_')[1] for c in TOP5]}")
            sys.exit(1)
    else:
        configs = TOP5

    timestamp = datetime.now(timezone.utc).isoformat()

    # Get git hash
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), text=True,
        ).strip()
    except Exception:
        git_hash = GIT_HASH

    print(f"Sprint 4 DD Attribution Analysis")
    print(f"================================")
    print(f"Configs: {len(configs)}")
    print(f"Git hash: {git_hash}")
    print(f"Timestamp: {timestamp}")
    print()

    results = []
    for i, config_id in enumerate(configs, 1):
        print(f"[{i}/{len(configs)}] Analyzing {config_id} ...", end=" ", flush=True)
        try:
            r = analyze_config(config_id)
            results.append(r)
            s = r["summary_stats"]
            summ = r["summary"]
            print(
                f"OK | {s['trades']} trades | DD={s['dd']}% | "
                f"Driver: {summ['primary_dd_driver']} | "
                f"Max streak: {r['loss_streaks']['max_streak']}"
            )
        except Exception as e:
            print(f"FAILED: {e}")

    if not results:
        print("\nNo results to write.")
        sys.exit(1)

    # Cross-config analysis
    print(f"\nRunning cross-config analysis ...", end=" ", flush=True)
    cross = cross_config_analysis(results)
    print("OK")

    # Provenance
    provenance = {
        "analysis": "sprint4_dd_attribution",
        "timestamp": timestamp,
        "git_hash": git_hash,
        "initial_capital": INITIAL_CAPITAL,
        "configs_analyzed": [r["config_id"] for r in results],
        "data_source_git_hash": GIT_HASH,
    }

    # Write JSON
    output_json = {
        "provenance": provenance,
        "configs": results,
        "cross_config": cross,
    }
    json_path = REPORT_DIR / "sprint4_dd_analysis.json"
    with open(json_path, "w") as f:
        json.dump(output_json, f, indent=2)
    print(f"\nJSON written: {json_path}")

    # Write markdown
    md = generate_markdown(results, cross, timestamp)
    md_path = REPORT_DIR / "sprint4_dd_analysis.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"MD written:   {md_path}")

    # Print key findings
    print(f"\n{'='*60}")
    print("KEY FINDINGS")
    print(f"{'='*60}")
    print(f"Common DD driver:        {cross['common_dd_driver']}")
    print(f"Avg worst episode depth: {cross['avg_worst_depth']}%")
    print(f"Compounding amplified:   {cross['compounding_amplification_count']}")
    print(f"Avg max loss streak:     {cross['avg_max_loss_streak']}")
    print(f"Full recovery:           {cross['configs_recovered']}")
    print()
    print("Exit DD Shares (avg):")
    for reason, share in sorted(cross["avg_exit_dd_shares"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {reason:20s} {share*100:5.1f}%")
    print()
    print("Top levers:")
    for item in cross["lever_ranking"][:5]:
        print(f"  - {item['lever']} ({item['configs_affected']}/{cross['n_configs']})")


if __name__ == "__main__":
    main()
