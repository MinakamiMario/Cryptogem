"""
Sprint 4 Edge Decomposition Analysis — deep profit-source analysis.

Goes beyond PF to understand WHERE profit comes from, enabling
"research lead" classification even when PF is only 1.0-1.2.

Decomposition dimensions:
  - Class A vs Class B exit attribution (positive profit attribution)
  - Exit reason breakdown with per-reason stats
  - Stopout analysis (cost, frequency, severity)
  - Fee sensitivity (breakeven fee, PF at multiple fee levels)
  - Time analysis (holding bars by winner/loser/class)
  - Research classification (STRONG_LEAD / WEAK_LEAD / NEGATIVE / INSUFFICIENT)

Parity: uses same CLASS_A_REASONS, fee model, and trade dict structure
as Sprint 1/3 engines and agent_team_v3.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — parity with Sprint 1 engine
# ---------------------------------------------------------------------------
CLASS_A_REASONS = {"PROFIT TARGET", "RSI RECOVERY", "DC TARGET", "BB TARGET"}
CLASS_B_REASONS = {"FIXED STOP", "TIME MAX", "END", "HARD STOP"}
DEFAULT_FEE_PER_SIDE = 0.0026  # Kraken 26bps per side

DEFAULT_FEE_LEVELS = [0.0, 0.001, 0.0015, 0.002, 0.0026, 0.003, 0.004, 0.005]

# Research lead thresholds
MIN_TRADES_SUFFICIENT = 20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EdgeDecomposition:
    """Full edge decomposition of a single backtest result."""
    config_id: str

    # Profit source breakdown
    class_a_pnl: float = 0.0          # P&L from Class A exits
    class_b_pnl: float = 0.0          # P&L from Class B exits
    class_a_count: int = 0
    class_b_count: int = 0
    class_a_wr: float = 0.0           # Win rate of Class A exits
    class_b_wr: float = 0.0           # Win rate of Class B exits
    class_a_share: float = 0.0        # class_a_profit / total_profit (positive attribution)

    # Exit reason breakdown
    exit_breakdown: dict = field(default_factory=dict)
    # {reason: {count, pnl, wr, avg_pnl, avg_bars}}

    # Stopout analysis
    stopout_ratio: float = 0.0        # FIXED STOP count / total trades
    stopout_cost: float = 0.0         # total loss from FIXED STOPs
    stopout_avg_loss: float = 0.0     # average loss per stopout

    # Fee sensitivity
    gross_pnl: float = 0.0            # P&L without fees
    fee_cost: float = 0.0             # Total fees paid
    fee_ratio: float = 0.0            # fees / gross_pnl (if gross_pnl > 0)
    breakeven_fee_bps: float = 0.0    # Max fee where PF >= 1.0

    # Time analysis
    avg_bars_winner: float = 0.0      # Average holding time for winners
    avg_bars_loser: float = 0.0       # Average holding time for losers
    avg_bars_class_a: float = 0.0     # Average bars for Class A exits

    # Research classification
    research_grade: str = "INSUFFICIENT"
    research_notes: list = field(default_factory=list)

    # Summary metrics (carried from input)
    total_trades: int = 0
    total_pnl: float = 0.0
    pf: float = 0.0
    wr: float = 0.0
    dd: float = 0.0


# ---------------------------------------------------------------------------
# Core decomposition
# ---------------------------------------------------------------------------

def decompose_edge(
    result_dict: dict,
    config_id: str,
    fee_per_side: float = DEFAULT_FEE_PER_SIDE,
) -> EdgeDecomposition:
    """Full edge decomposition from a backtest result.

    Parameters
    ----------
    result_dict : dict
        From engine's backtest result. Expected keys:
          summary: {trades, pnl, pf, wr, dd}
          exit_classes: {A: {reason: {count, pnl, wins}}, B: {...}}
          trades: [{pnl, reason, bars, entry, exit, size, pair, entry_bar, exit_bar, ...}]
    config_id : str
        Identifier for this config.
    fee_per_side : float
        Fee per side used in the backtest (default: 0.0026 = 26bps).

    Returns
    -------
    EdgeDecomposition
    """
    summary = result_dict.get("summary", {})
    exit_classes = result_dict.get("exit_classes", {"A": {}, "B": {}})
    trade_list = result_dict.get("trades", [])

    decomp = EdgeDecomposition(config_id=config_id)

    # --- Carry summary metrics ---
    decomp.total_trades = summary.get("trades", len(trade_list))
    decomp.total_pnl = summary.get("pnl", 0.0)
    decomp.pf = summary.get("pf", 0.0)
    decomp.wr = summary.get("wr", 0.0)
    decomp.dd = summary.get("dd", 0.0)

    # --- Class A/B from exit_classes ---
    class_a_data = exit_classes.get("A", {})
    class_b_data = exit_classes.get("B", {})

    decomp.class_a_pnl = sum(v.get("pnl", 0.0) for v in class_a_data.values())
    decomp.class_b_pnl = sum(v.get("pnl", 0.0) for v in class_b_data.values())
    decomp.class_a_count = sum(v.get("count", 0) for v in class_a_data.values())
    decomp.class_b_count = sum(v.get("count", 0) for v in class_b_data.values())

    # Class A win rate
    a_wins = sum(v.get("wins", 0) for v in class_a_data.values())
    decomp.class_a_wr = (a_wins / decomp.class_a_count * 100) if decomp.class_a_count > 0 else 0.0

    # Class B win rate
    b_wins = sum(v.get("wins", 0) for v in class_b_data.values())
    decomp.class_b_wr = (b_wins / decomp.class_b_count * 100) if decomp.class_b_count > 0 else 0.0

    # Positive profit attribution for class_a_share
    total_profit = sum(max(0, v.get("pnl", 0.0)) for v in class_a_data.values()) + \
                   sum(max(0, v.get("pnl", 0.0)) for v in class_b_data.values())
    class_a_profit = sum(max(0, v.get("pnl", 0.0)) for v in class_a_data.values())
    decomp.class_a_share = min(1.0, class_a_profit / total_profit) if total_profit > 0 else 0.0

    # --- Exit reason breakdown (from trade_list for per-trade granularity) ---
    reason_stats: dict[str, dict] = {}
    for t in trade_list:
        reason = t.get("reason", "UNKNOWN")
        if reason not in reason_stats:
            reason_stats[reason] = {
                "count": 0, "pnl": 0.0, "wins": 0,
                "total_bars": 0, "pnl_list": [],
            }
        rs = reason_stats[reason]
        rs["count"] += 1
        rs["pnl"] += t.get("pnl", 0.0)
        rs["pnl_list"].append(t.get("pnl", 0.0))
        if t.get("pnl", 0.0) > 0:
            rs["wins"] += 1
        rs["total_bars"] += t.get("bars", 0)

    decomp.exit_breakdown = {}
    for reason, rs in reason_stats.items():
        cnt = rs["count"]
        decomp.exit_breakdown[reason] = {
            "count": cnt,
            "pnl": round(rs["pnl"], 2),
            "wr": round(rs["wins"] / cnt * 100, 1) if cnt > 0 else 0.0,
            "avg_pnl": round(rs["pnl"] / cnt, 2) if cnt > 0 else 0.0,
            "avg_bars": round(rs["total_bars"] / cnt, 1) if cnt > 0 else 0.0,
        }

    # --- Stopout analysis ---
    stopout_trades = [t for t in trade_list if t.get("reason") == "FIXED STOP"]
    n_total = len(trade_list)
    decomp.stopout_ratio = len(stopout_trades) / n_total if n_total > 0 else 0.0
    decomp.stopout_cost = sum(t.get("pnl", 0.0) for t in stopout_trades)
    decomp.stopout_avg_loss = (
        decomp.stopout_cost / len(stopout_trades) if stopout_trades else 0.0
    )

    # --- Fee sensitivity ---
    # Estimate gross P&L and total fees from trade list
    total_fees = 0.0
    total_gross = 0.0
    for t in trade_list:
        size = t.get("size", 0.0)
        entry_p = t.get("entry", 0.0)
        exit_p = t.get("exit", 0.0)
        if entry_p > 0 and size > 0:
            gross = size * (exit_p / entry_p - 1.0)
            fees = size * fee_per_side + (size + gross) * fee_per_side
            total_gross += gross
            total_fees += fees

    decomp.gross_pnl = round(total_gross, 2)
    decomp.fee_cost = round(total_fees, 2)
    decomp.fee_ratio = round(total_fees / total_gross, 4) if total_gross > 0 else 0.0

    # Breakeven fee: find fee level where PF = 1.0
    fs = fee_sensitivity(trade_list, fee_levels=DEFAULT_FEE_LEVELS)
    decomp.breakeven_fee_bps = fs.get("breakeven_bps", 0.0)

    # --- Time analysis ---
    winners = [t for t in trade_list if t.get("pnl", 0.0) > 0]
    losers = [t for t in trade_list if t.get("pnl", 0.0) <= 0]
    class_a_trades = [t for t in trade_list if t.get("reason") in CLASS_A_REASONS]

    decomp.avg_bars_winner = (
        sum(t.get("bars", 0) for t in winners) / len(winners) if winners else 0.0
    )
    decomp.avg_bars_loser = (
        sum(t.get("bars", 0) for t in losers) / len(losers) if losers else 0.0
    )
    decomp.avg_bars_class_a = (
        sum(t.get("bars", 0) for t in class_a_trades) / len(class_a_trades)
        if class_a_trades else 0.0
    )

    # --- Research classification ---
    decomp.research_grade = classify_research_lead(decomp)
    decomp.research_notes = _generate_notes(decomp)

    return decomp


# ---------------------------------------------------------------------------
# Research lead classification
# ---------------------------------------------------------------------------

def classify_research_lead(decomp: EdgeDecomposition) -> str:
    """Classify a result as research lead based on multiple signals.

    STRONG_LEAD (worth investigating further):
      - PF >= 1.0 AND class_a_share > 60% AND stopout_ratio < 40%
      - OR PF >= 0.95 AND class_a_wr > 80% (exits working, entries need tuning)

    WEAK_LEAD (marginal, needs significant improvement):
      - PF >= 0.90 AND class_a_share > 40%
      - OR stopout_ratio < 30% (low stopout = entries have geometric merit)

    NEGATIVE (no edge signal):
      - PF < 0.90 OR class_a_share < 30% OR stopout_ratio > 60%

    INSUFFICIENT:
      - trades < 20 (not enough data)
    """
    if decomp.total_trades < MIN_TRADES_SUFFICIENT:
        return "INSUFFICIENT"

    pf = decomp.pf
    a_share = decomp.class_a_share
    a_wr = decomp.class_a_wr
    stopout = decomp.stopout_ratio

    # NEGATIVE checks first (hard disqualifiers)
    if pf < 0.90 or a_share < 0.30 or stopout > 0.60:
        return "NEGATIVE"

    # STRONG_LEAD
    if pf >= 1.0 and a_share > 0.60 and stopout < 0.40:
        return "STRONG_LEAD"
    if pf >= 0.95 and a_wr > 80.0:
        return "STRONG_LEAD"

    # WEAK_LEAD
    if pf >= 0.90 and a_share > 0.40:
        return "WEAK_LEAD"
    if stopout < 0.30:
        return "WEAK_LEAD"

    return "NEGATIVE"


def _generate_notes(decomp: EdgeDecomposition) -> list[str]:
    """Generate human-readable analysis notes for a decomposition."""
    notes: list[str] = []

    # Grade explanation
    if decomp.research_grade == "STRONG_LEAD":
        notes.append(
            f"STRONG LEAD: PF={decomp.pf:.2f}, Class A share={decomp.class_a_share:.0%}, "
            f"stopout ratio={decomp.stopout_ratio:.0%}"
        )
    elif decomp.research_grade == "WEAK_LEAD":
        notes.append(
            f"WEAK LEAD: PF={decomp.pf:.2f}, needs improvement "
            f"(A share={decomp.class_a_share:.0%}, stopout={decomp.stopout_ratio:.0%})"
        )
    elif decomp.research_grade == "NEGATIVE":
        reasons = []
        if decomp.pf < 0.90:
            reasons.append(f"PF={decomp.pf:.2f} < 0.90")
        if decomp.class_a_share < 0.30:
            reasons.append(f"A share={decomp.class_a_share:.0%} < 30%")
        if decomp.stopout_ratio > 0.60:
            reasons.append(f"stopout={decomp.stopout_ratio:.0%} > 60%")
        notes.append(f"NEGATIVE: {', '.join(reasons) if reasons else 'no edge signal'}")
    else:
        notes.append(f"INSUFFICIENT: only {decomp.total_trades} trades (need >= {MIN_TRADES_SUFFICIENT})")

    # Dominant exit reason
    if decomp.exit_breakdown:
        best_reason = max(
            decomp.exit_breakdown.items(),
            key=lambda x: x[1].get("pnl", 0.0),
        )
        worst_reason = min(
            decomp.exit_breakdown.items(),
            key=lambda x: x[1].get("pnl", 0.0),
        )
        notes.append(
            f"Best exit: {best_reason[0]} (${best_reason[1]['pnl']:.0f}, "
            f"{best_reason[1]['count']} trades, {best_reason[1]['wr']:.0f}% WR)"
        )
        if worst_reason[1]["pnl"] < 0:
            notes.append(
                f"Worst exit: {worst_reason[0]} (${worst_reason[1]['pnl']:.0f}, "
                f"{worst_reason[1]['count']} trades)"
            )

    # Fee insight
    if decomp.breakeven_fee_bps > 0:
        notes.append(f"Breakeven fee: {decomp.breakeven_fee_bps:.1f} bps per side")
        if decomp.breakeven_fee_bps < 26:
            notes.append("WARNING: unprofitable at Kraken fees (26 bps)")
        elif decomp.breakeven_fee_bps < 30:
            notes.append("TIGHT: barely profitable at Kraken fees, consider MEXC (10 bps)")

    # Stopout insight
    if decomp.stopout_ratio > 0.40:
        notes.append(
            f"HIGH STOPOUT: {decomp.stopout_ratio:.0%} of trades hit fixed stop "
            f"(avg loss ${decomp.stopout_avg_loss:.0f})"
        )
    elif decomp.stopout_ratio < 0.20 and decomp.total_trades >= MIN_TRADES_SUFFICIENT:
        notes.append(
            f"LOW STOPOUT: {decomp.stopout_ratio:.0%} -- entries have good geometric placement"
        )

    # Time insight
    if decomp.avg_bars_winner > 0 and decomp.avg_bars_loser > 0:
        ratio = decomp.avg_bars_winner / decomp.avg_bars_loser
        if ratio > 2.0:
            notes.append(
                f"Winners held {decomp.avg_bars_winner:.1f} bars vs losers "
                f"{decomp.avg_bars_loser:.1f} bars -- good patience/cut pattern"
            )

    return notes


# ---------------------------------------------------------------------------
# Fee sensitivity analysis
# ---------------------------------------------------------------------------

def fee_sensitivity(
    trade_list: list[dict],
    fee_levels: Optional[list[float]] = None,
) -> dict:
    """Recompute PF at different fee levels.

    For each fee level, recalculates every trade's net P&L using the
    engine's fee formula:
        gross = size * (exit / entry - 1)
        fees  = size * fee + (size + gross) * fee
        net   = gross - fees

    Parameters
    ----------
    trade_list : list[dict]
        List of trade dicts with: entry, exit, size (at minimum).
    fee_levels : list[float] or None
        Fee-per-side levels to test. Default: [0, 10, 15, 20, 26, 30, 40, 50] bps.

    Returns
    -------
    dict with keys:
        levels: list[float] -- fee per side values
        pfs: list[float] -- PF at each fee level
        pnls: list[float] -- total P&L at each fee level
        breakeven_bps: float -- fee where PF crosses 1.0 (0 if never profitable)
        current_pf: float -- PF at 26bps (DEFAULT_FEE_PER_SIDE)
    """
    if fee_levels is None:
        fee_levels = list(DEFAULT_FEE_LEVELS)

    levels_out: list[float] = []
    pfs_out: list[float] = []
    pnls_out: list[float] = []

    for fee in fee_levels:
        sum_wins = 0.0
        sum_losses = 0.0
        total_pnl = 0.0

        for t in trade_list:
            size = t.get("size", 0.0)
            entry_p = t.get("entry", 0.0)
            exit_p = t.get("exit", 0.0)
            if entry_p <= 0 or size <= 0:
                continue

            gross = size * (exit_p / entry_p - 1.0)
            fees = size * fee + (size + gross) * fee
            net = gross - fees

            if net > 0:
                sum_wins += net
            else:
                sum_losses += abs(net)
            total_pnl += net

        pf = sum_wins / sum_losses if sum_losses > 0 else (
            float("inf") if sum_wins > 0 else 0.0
        )

        levels_out.append(fee)
        pfs_out.append(round(pf, 4) if pf != float("inf") else 999.0)
        pnls_out.append(round(total_pnl, 2))

    # Find breakeven fee (linear interpolation where PF crosses 1.0)
    breakeven_bps = 0.0
    for i in range(len(pfs_out) - 1):
        pf_a = pfs_out[i]
        pf_b = pfs_out[i + 1]
        fee_a = levels_out[i]
        fee_b = levels_out[i + 1]

        if pf_a >= 1.0 and pf_b < 1.0:
            # Linear interpolation
            if pf_a != pf_b:
                frac = (pf_a - 1.0) / (pf_a - pf_b)
                breakeven_fee = fee_a + frac * (fee_b - fee_a)
                breakeven_bps = round(breakeven_fee * 10000, 1)  # convert to bps
            else:
                breakeven_bps = round(fee_a * 10000, 1)
            break
    else:
        # Check if profitable at all fee levels
        if all(pf >= 1.0 for pf in pfs_out):
            breakeven_bps = round(levels_out[-1] * 10000, 1)  # at least this high
        # else: stays 0.0 (never profitable)

    # Current PF (at default fee)
    current_pf = 0.0
    for i, fee in enumerate(levels_out):
        if abs(fee - DEFAULT_FEE_PER_SIDE) < 1e-6:
            current_pf = pfs_out[i]
            break

    return {
        "levels": levels_out,
        "pfs": pfs_out,
        "pnls": pnls_out,
        "breakeven_bps": breakeven_bps,
        "current_pf": current_pf,
    }


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

def batch_analysis(
    results: list[tuple[dict, dict]],
    compat_scores: Optional[dict] = None,
) -> dict:
    """Generate comprehensive batch analysis.

    Parameters
    ----------
    results : list[tuple[dict, dict]]
        List of (config, result_dict) tuples.
        config must have at least: "id" (str) and optionally "family" (str).
        result_dict: same format as decompose_edge expects.
    compat_scores : dict or None
        Optional compat scores {config_id: score} from compat_scorer.

    Returns
    -------
    dict with keys: summary, decompositions, fee_sensitivity,
    family_analysis, exit_intelligence, recommendations.
    """
    decompositions: dict[str, dict] = {}
    fee_results: dict[str, dict] = {}
    all_decomps: list[EdgeDecomposition] = []

    for config, result_dict in results:
        config_id = config.get("id", "unknown")
        decomp = decompose_edge(result_dict, config_id)
        decompositions[config_id] = asdict(decomp)
        all_decomps.append(decomp)

        trade_list = result_dict.get("trades", [])
        fee_results[config_id] = fee_sensitivity(trade_list)

    # --- Summary ---
    strong = [d.config_id for d in all_decomps if d.research_grade == "STRONG_LEAD"]
    weak = [d.config_id for d in all_decomps if d.research_grade == "WEAK_LEAD"]
    negative = [d.config_id for d in all_decomps if d.research_grade == "NEGATIVE"]
    insufficient = [d.config_id for d in all_decomps if d.research_grade == "INSUFFICIENT"]

    summary = {
        "total_configs": len(all_decomps),
        "strong_leads": strong,
        "weak_leads": weak,
        "negative": negative,
        "insufficient": insufficient,
    }

    # --- Family analysis ---
    family_map: dict[str, list[EdgeDecomposition]] = {}
    for (config, _result), decomp in zip(results, all_decomps):
        family = config.get("family", "unknown")
        if family not in family_map:
            family_map[family] = []
        family_map[family].append(decomp)

    family_analysis = {}
    for family, decomps in family_map.items():
        valid = [d for d in decomps if d.total_trades >= MIN_TRADES_SUFFICIENT]
        if not valid:
            family_analysis[family] = {
                "avg_pf": 0.0,
                "avg_stopout_ratio": 0.0,
                "avg_class_a_share": 0.0,
                "best_config": decomps[0].config_id if decomps else "none",
                "research_grade": "INSUFFICIENT",
                "n_configs": len(decomps),
            }
            continue

        avg_pf = sum(d.pf for d in valid) / len(valid)
        avg_stopout = sum(d.stopout_ratio for d in valid) / len(valid)
        avg_a_share = sum(d.class_a_share for d in valid) / len(valid)
        best = max(valid, key=lambda d: d.pf)

        # Family-level grade: best individual grade
        grade_priority = {"STRONG_LEAD": 3, "WEAK_LEAD": 2, "NEGATIVE": 1, "INSUFFICIENT": 0}
        family_grade = max(
            (d.research_grade for d in valid),
            key=lambda g: grade_priority.get(g, 0),
        )

        family_analysis[family] = {
            "avg_pf": round(avg_pf, 4),
            "avg_stopout_ratio": round(avg_stopout, 4),
            "avg_class_a_share": round(avg_a_share, 4),
            "best_config": best.config_id,
            "research_grade": family_grade,
            "n_configs": len(decomps),
        }

    # --- Exit intelligence ---
    # Aggregate exit breakdown across all configs
    global_exit_stats: dict[str, dict] = {}
    for decomp in all_decomps:
        for reason, stats in decomp.exit_breakdown.items():
            if reason not in global_exit_stats:
                global_exit_stats[reason] = {"total_pnl": 0.0, "total_count": 0, "total_wins": 0}
            global_exit_stats[reason]["total_pnl"] += stats.get("pnl", 0.0)
            global_exit_stats[reason]["total_count"] += stats.get("count", 0)
            cnt = stats.get("count", 0)
            wr = stats.get("wr", 0.0)
            global_exit_stats[reason]["total_wins"] += int(cnt * wr / 100) if cnt > 0 else 0

    best_exit = max(global_exit_stats.items(), key=lambda x: x[1]["total_pnl"]) \
        if global_exit_stats else ("NONE", {"total_pnl": 0})
    worst_exit = min(global_exit_stats.items(), key=lambda x: x[1]["total_pnl"]) \
        if global_exit_stats else ("NONE", {"total_pnl": 0})

    # Class A dominance: fraction of configs where class_a_pnl > class_b_pnl
    valid_decomps = [d for d in all_decomps if d.total_trades >= MIN_TRADES_SUFFICIENT]
    if valid_decomps:
        a_dominant = sum(1 for d in valid_decomps if d.class_a_pnl > d.class_b_pnl)
        class_a_dominance = a_dominant / len(valid_decomps)
    else:
        class_a_dominance = 0.0

    exit_intelligence = {
        "best_exit_reason": best_exit[0],
        "worst_exit_reason": worst_exit[0],
        "class_a_dominance": round(class_a_dominance, 4),
        "global_exit_stats": {
            reason: {
                "total_pnl": round(s["total_pnl"], 2),
                "total_count": s["total_count"],
            }
            for reason, s in global_exit_stats.items()
        },
    }

    # --- Recommendations ---
    recommendations = generate_recommendations({
        "summary": summary,
        "decompositions": decompositions,
        "fee_sensitivity": fee_results,
        "family_analysis": family_analysis,
        "exit_intelligence": exit_intelligence,
        "_decomps": all_decomps,  # internal, for recommendation engine
    })

    return {
        "summary": summary,
        "decompositions": decompositions,
        "fee_sensitivity": fee_results,
        "family_analysis": family_analysis,
        "exit_intelligence": exit_intelligence,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Recommendations engine
# ---------------------------------------------------------------------------

def generate_recommendations(batch: dict) -> list[str]:
    """Generate actionable recommendations from batch analysis.

    Parameters
    ----------
    batch : dict
        Partial or full batch analysis dict (must have summary, decompositions,
        fee_sensitivity, family_analysis, exit_intelligence).

    Returns
    -------
    list[str]
        Human-readable recommendation strings.
    """
    recs: list[str] = []
    summary = batch.get("summary", {})
    decompositions = batch.get("decompositions", {})
    fee_results = batch.get("fee_sensitivity", {})
    family_analysis = batch.get("family_analysis", {})
    exit_intel = batch.get("exit_intelligence", {})
    all_decomps: list[EdgeDecomposition] = batch.get("_decomps", [])

    # 1. Strong leads call-to-action
    strong = summary.get("strong_leads", [])
    if strong:
        ids = ", ".join(strong[:5])
        recs.append(
            f"{len(strong)} STRONG LEAD(s) found: {ids} -- advance to truth-pass "
            f"(agent_team_v3.py full validation)"
        )

    # 2. Weak leads with direction
    weak = summary.get("weak_leads", [])
    if weak and not strong:
        ids = ", ".join(weak[:5])
        recs.append(
            f"{len(weak)} WEAK LEAD(s) found: {ids} -- tune entry parameters "
            f"or relax stop distance before truth-pass"
        )

    # 3. Family-level insights
    if family_analysis:
        # Best family by avg PF
        best_fam = max(
            family_analysis.items(),
            key=lambda x: x[1].get("avg_pf", 0),
        )
        if best_fam[1].get("avg_pf", 0) > 0.85:
            recs.append(
                f"Family '{best_fam[0]}' has best avg PF ({best_fam[1]['avg_pf']:.2f}) "
                f"-- focus further tuning here"
            )

        # Lowest stopout family
        valid_fams = {k: v for k, v in family_analysis.items()
                      if v.get("avg_stopout_ratio", 1.0) > 0 and v.get("n_configs", 0) > 0}
        if valid_fams:
            low_stop = min(valid_fams.items(), key=lambda x: x[1]["avg_stopout_ratio"])
            if low_stop[1]["avg_stopout_ratio"] < 0.35:
                recs.append(
                    f"Family '{low_stop[0]}' has lowest stopout ratio "
                    f"({low_stop[1]['avg_stopout_ratio']:.0%}) -- entries have good geometric merit"
                )

    # 4. Exit intelligence
    best_exit = exit_intel.get("best_exit_reason", "")
    global_stats = exit_intel.get("global_exit_stats", {})
    if best_exit and best_exit in global_stats:
        stats = global_stats[best_exit]
        if stats.get("total_pnl", 0) > 0:
            recs.append(
                f"{best_exit} generates most profit across all configs "
                f"(${stats['total_pnl']:.0f} total, {stats['total_count']} exits) "
                f"-- entries should maximize probability of this exit firing"
            )

    a_dom = exit_intel.get("class_a_dominance", 0)
    if a_dom > 0.5:
        recs.append(
            f"Class A exits dominate in {a_dom:.0%} of configs -- "
            f"DC exit intelligence is working, focus on entry quality"
        )
    elif a_dom < 0.3 and summary.get("total_configs", 0) > 0:
        recs.append(
            "Class A exits underperform in majority of configs -- "
            "entries may not be geometrically compatible with DC exits"
        )

    # 5. Fee sensitivity insight
    fee_sensitive_configs = []
    for cid, fs in fee_results.items():
        be_bps = fs.get("breakeven_bps", 0)
        if 10 < be_bps < 26:
            fee_sensitive_configs.append((cid, be_bps))
    if fee_sensitive_configs:
        recs.append(
            f"{len(fee_sensitive_configs)} config(s) profitable at lower fees but not Kraken "
            f"(26 bps) -- consider MEXC (10 bps) for these"
        )

    # 6. If everything is negative
    total = summary.get("total_configs", 0)
    n_negative = len(summary.get("negative", []))
    n_insuff = len(summary.get("insufficient", []))
    if total > 0 and (n_negative + n_insuff) == total:
        recs.append(
            "ALL configs are NEGATIVE or INSUFFICIENT -- current entry families "
            "do not generate edge with DC exits. Consider new entry hypotheses "
            "or verify DC-compatibility scores."
        )

    if not recs:
        recs.append("No actionable recommendations -- review individual decompositions.")

    return recs


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def write_analysis_report(batch: dict, output_path: str) -> tuple[str, str]:
    """Write analysis report as JSON + MD files.

    Parameters
    ----------
    batch : dict
        Output from batch_analysis().
    output_path : str
        Base path (without extension). Will create .json and .md files.

    Returns
    -------
    tuple[str, str]
        (json_path, md_path)
    """
    output = Path(output_path)
    json_path = output.with_suffix(".json")
    md_path = output.with_suffix(".md")

    # --- JSON ---
    # Remove internal keys
    json_data = {k: v for k, v in batch.items() if not k.startswith("_")}
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)

    # --- Markdown ---
    lines: list[str] = []
    summary = batch.get("summary", {})
    decompositions = batch.get("decompositions", {})
    family_analysis = batch.get("family_analysis", {})
    exit_intel = batch.get("exit_intelligence", {})
    recommendations = batch.get("recommendations", [])

    lines.append("# Sprint 4 Edge Decomposition Report")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append(f"- Total configs: {summary.get('total_configs', 0)}")
    lines.append(f"- STRONG LEADs: {len(summary.get('strong_leads', []))}")
    lines.append(f"- WEAK LEADs: {len(summary.get('weak_leads', []))}")
    lines.append(f"- NEGATIVE: {len(summary.get('negative', []))}")
    lines.append(f"- INSUFFICIENT: {len(summary.get('insufficient', []))}")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    # Config scoreboard
    lines.append("## Config Scoreboard")
    lines.append("")
    lines.append(
        "| Config | PF | Trades | WR% | A Share | Stopout | Grade | BE Fee |"
    )
    lines.append(
        "|--------|-----|--------|------|---------|---------|-------|--------|"
    )

    # Sort by PF descending
    sorted_configs = sorted(
        decompositions.items(),
        key=lambda x: x[1].get("pf", 0),
        reverse=True,
    )
    for config_id, d in sorted_configs:
        pf_val = d.get("pf", 0)
        pf_str = f"{pf_val:.2f}" if pf_val < 999 else "inf"
        lines.append(
            f"| {config_id} | {pf_str} | {d.get('total_trades', 0)} | "
            f"{d.get('wr', 0):.1f} | {d.get('class_a_share', 0):.0%} | "
            f"{d.get('stopout_ratio', 0):.0%} | {d.get('research_grade', '?')} | "
            f"{d.get('breakeven_fee_bps', 0):.0f} bps |"
        )
    lines.append("")

    # Family analysis
    if family_analysis:
        lines.append("## Family Analysis")
        lines.append("")
        lines.append(
            "| Family | Configs | Avg PF | Avg Stopout | Avg A Share | Best Config | Grade |"
        )
        lines.append(
            "|--------|---------|--------|-------------|-------------|-------------|-------|"
        )
        for fam, fa in sorted(family_analysis.items(), key=lambda x: x[1].get("avg_pf", 0), reverse=True):
            lines.append(
                f"| {fam} | {fa.get('n_configs', 0)} | {fa.get('avg_pf', 0):.2f} | "
                f"{fa.get('avg_stopout_ratio', 0):.0%} | {fa.get('avg_class_a_share', 0):.0%} | "
                f"{fa.get('best_config', '?')} | {fa.get('research_grade', '?')} |"
            )
        lines.append("")

    # Exit intelligence
    lines.append("## Exit Intelligence")
    lines.append(f"- Best exit reason: {exit_intel.get('best_exit_reason', '?')}")
    lines.append(f"- Worst exit reason: {exit_intel.get('worst_exit_reason', '?')}")
    lines.append(f"- Class A dominance: {exit_intel.get('class_a_dominance', 0):.0%}")
    lines.append("")

    global_stats = exit_intel.get("global_exit_stats", {})
    if global_stats:
        lines.append("| Exit Reason | Total P&L | Total Count |")
        lines.append("|-------------|-----------|-------------|")
        for reason, s in sorted(global_stats.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True):
            lines.append(f"| {reason} | ${s.get('total_pnl', 0):.0f} | {s.get('total_count', 0)} |")
        lines.append("")

    # Per-config detail (top 5 by PF)
    lines.append("## Top Config Details")
    lines.append("")
    for config_id, d in sorted_configs[:5]:
        lines.append(f"### {config_id}")
        lines.append(f"- PF: {d.get('pf', 0):.2f} | Trades: {d.get('total_trades', 0)} | "
                      f"WR: {d.get('wr', 0):.1f}% | DD: {d.get('dd', 0):.1f}%")
        lines.append(f"- Class A: {d.get('class_a_count', 0)} trades, ${d.get('class_a_pnl', 0):.0f} P&L, "
                      f"{d.get('class_a_wr', 0):.0f}% WR")
        lines.append(f"- Class B: {d.get('class_b_count', 0)} trades, ${d.get('class_b_pnl', 0):.0f} P&L, "
                      f"{d.get('class_b_wr', 0):.0f}% WR")
        lines.append(f"- Stopout: {d.get('stopout_ratio', 0):.0%} ratio, "
                      f"${d.get('stopout_cost', 0):.0f} cost")
        lines.append(f"- Fee: gross ${d.get('gross_pnl', 0):.0f}, "
                      f"fees ${d.get('fee_cost', 0):.0f}, "
                      f"BE fee {d.get('breakeven_fee_bps', 0):.0f} bps")
        lines.append(f"- Bars: winners {d.get('avg_bars_winner', 0):.1f}, "
                      f"losers {d.get('avg_bars_loser', 0):.1f}, "
                      f"Class A {d.get('avg_bars_class_a', 0):.1f}")
        notes = d.get("research_notes", [])
        if notes:
            lines.append(f"- Notes:")
            for note in notes:
                lines.append(f"  - {note}")
        lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    return str(json_path), str(md_path)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Running analysis self-tests...\n")

    # ---- Mock trade list ----
    mock_trades = [
        {"pnl": 50.0, "reason": "DC TARGET", "entry": 100, "exit": 105,
         "size": 500, "bars": 5, "entry_bar": 10, "exit_bar": 15, "pair": "BTC/USD"},
        {"pnl": -30.0, "reason": "FIXED STOP", "entry": 100, "exit": 85,
         "size": 500, "bars": 3, "entry_bar": 20, "exit_bar": 23, "pair": "ETH/USD"},
        {"pnl": 80.0, "reason": "RSI RECOVERY", "entry": 100, "exit": 108,
         "size": 500, "bars": 7, "entry_bar": 30, "exit_bar": 37, "pair": "SOL/USD"},
    ]
    mock_exit_classes = {
        "A": {
            "DC TARGET": {"count": 1, "pnl": 50.0, "wins": 1},
            "RSI RECOVERY": {"count": 1, "pnl": 80.0, "wins": 1},
        },
        "B": {
            "FIXED STOP": {"count": 1, "pnl": -30.0, "wins": 0},
        },
    }
    mock_result = {
        "summary": {"trades": 3, "pnl": 100.0, "pf": 4.33, "wr": 66.7, "dd": 10.0},
        "exit_classes": mock_exit_classes,
        "trades": mock_trades,
    }

    # ---- Test 1: decompose_edge basic ----
    decomp = decompose_edge(mock_result, "test_001")
    assert decomp.class_a_pnl == 130.0, f"class_a_pnl: expected 130.0, got {decomp.class_a_pnl}"
    assert decomp.class_b_pnl == -30.0, f"class_b_pnl: expected -30.0, got {decomp.class_b_pnl}"
    assert abs(decomp.stopout_ratio - 1 / 3) < 1e-9, \
        f"stopout_ratio: expected {1/3:.6f}, got {decomp.stopout_ratio}"
    # Note: with only 3 trades, research_grade = INSUFFICIENT (< 20 trades)
    assert decomp.research_grade == "INSUFFICIENT", \
        f"research_grade: expected INSUFFICIENT (3 trades), got {decomp.research_grade}"
    print(f"  Test 1 PASS: decompose_edge basic (3 trades -> INSUFFICIENT)")
    print(f"    class_a_pnl={decomp.class_a_pnl}, class_b_pnl={decomp.class_b_pnl}")
    print(f"    stopout_ratio={decomp.stopout_ratio:.4f}")
    print(f"    research_grade={decomp.research_grade}")

    # ---- Test 2: Strong lead with enough trades ----
    # Build 30 trades: 20 Class A winners, 10 stopouts
    many_trades = []
    many_exit_classes = {"A": {}, "B": {}}
    for i in range(20):
        reason = "RSI RECOVERY" if i % 2 == 0 else "DC TARGET"
        many_trades.append({
            "pnl": 40.0, "reason": reason, "entry": 100, "exit": 108,
            "size": 500, "bars": 6, "entry_bar": i * 10, "exit_bar": i * 10 + 6,
            "pair": f"COIN{i}/USD",
        })
        if reason not in many_exit_classes["A"]:
            many_exit_classes["A"][reason] = {"count": 0, "pnl": 0.0, "wins": 0}
        many_exit_classes["A"][reason]["count"] += 1
        many_exit_classes["A"][reason]["pnl"] += 40.0
        many_exit_classes["A"][reason]["wins"] += 1

    for i in range(10):
        many_trades.append({
            "pnl": -25.0, "reason": "FIXED STOP", "entry": 100, "exit": 95,
            "size": 500, "bars": 3, "entry_bar": 200 + i * 10, "exit_bar": 203 + i * 10,
            "pair": f"LOSSCOIN{i}/USD",
        })
    many_exit_classes["B"]["FIXED STOP"] = {"count": 10, "pnl": -250.0, "wins": 0}

    total_pnl = 20 * 40 - 10 * 25  # 800 - 250 = 550
    sum_wins = 20 * 40.0  # 800
    sum_losses = 10 * 25.0  # 250
    pf = sum_wins / sum_losses  # 3.2

    many_result = {
        "summary": {"trades": 30, "pnl": total_pnl, "pf": pf, "wr": 66.7, "dd": 15.0},
        "exit_classes": many_exit_classes,
        "trades": many_trades,
    }

    decomp2 = decompose_edge(many_result, "test_002")
    assert decomp2.research_grade == "STRONG_LEAD", \
        f"research_grade: expected STRONG_LEAD, got {decomp2.research_grade}"
    assert decomp2.class_a_count == 20
    assert decomp2.class_b_count == 10
    assert decomp2.class_a_share == 1.0  # all profit from Class A
    assert abs(decomp2.stopout_ratio - 10 / 30) < 1e-9
    print(f"  Test 2 PASS: strong lead with 30 trades")
    print(f"    PF={decomp2.pf:.2f}, A share={decomp2.class_a_share:.0%}")
    print(f"    grade={decomp2.research_grade}")

    # ---- Test 3: Fee sensitivity ----
    # Use many_trades (profitable) for breakeven test; mock_trades has gross loss
    fs = fee_sensitivity(many_trades)
    assert fs["breakeven_bps"] > 0, f"breakeven_bps should be > 0, got {fs['breakeven_bps']}"
    assert len(fs["levels"]) == len(DEFAULT_FEE_LEVELS)
    assert len(fs["pfs"]) == len(DEFAULT_FEE_LEVELS)
    # At 0 fees, PF should be higher than at 26bps
    assert fs["pfs"][0] >= fs["current_pf"], \
        f"PF at 0 fee ({fs['pfs'][0]}) should be >= PF at 26bps ({fs['current_pf']})"
    print(f"  Test 3 PASS: fee sensitivity (profitable trades)")
    print(f"    breakeven_bps={fs['breakeven_bps']:.1f}")
    print(f"    PF at 0 fee={fs['pfs'][0]:.2f}, PF at 26bps={fs['current_pf']:.2f}")

    # Also verify unprofitable mock_trades: breakeven should be 0 (never profitable)
    fs_neg = fee_sensitivity(mock_trades)
    assert fs_neg["breakeven_bps"] == 0.0, \
        f"Unprofitable trades should have breakeven_bps=0, got {fs_neg['breakeven_bps']}"
    print(f"  Test 3b PASS: fee sensitivity (unprofitable trades -> breakeven=0)")

    # ---- Test 4: Classify research lead edge cases ----
    # Negative: low PF
    d_neg = EdgeDecomposition(config_id="neg", pf=0.5, total_trades=30,
                              class_a_share=0.5, stopout_ratio=0.3, class_a_wr=50.0)
    assert classify_research_lead(d_neg) == "NEGATIVE"

    # Negative: high stopout
    d_neg2 = EdgeDecomposition(config_id="neg2", pf=1.1, total_trades=30,
                               class_a_share=0.7, stopout_ratio=0.65, class_a_wr=80.0)
    assert classify_research_lead(d_neg2) == "NEGATIVE"

    # Weak: moderate PF, ok share
    d_weak = EdgeDecomposition(config_id="weak", pf=0.92, total_trades=30,
                               class_a_share=0.55, stopout_ratio=0.35, class_a_wr=60.0)
    assert classify_research_lead(d_weak) == "WEAK_LEAD"

    # Strong: high A WR
    d_strong2 = EdgeDecomposition(config_id="strong2", pf=0.96, total_trades=30,
                                  class_a_share=0.5, stopout_ratio=0.35, class_a_wr=85.0)
    assert classify_research_lead(d_strong2) == "STRONG_LEAD"

    print(f"  Test 4 PASS: classify edge cases (NEG/NEG/WEAK/STRONG)")

    # ---- Test 5: Batch analysis ----
    config1 = {"id": "cfg_001", "family": "wick_rejection"}
    config2 = {"id": "cfg_002", "family": "wick_rejection"}
    config3 = {"id": "cfg_003", "family": "volume_bounce"}

    batch = batch_analysis([
        (config1, many_result),
        (config2, mock_result),
        (config3, many_result),
    ])

    assert batch["summary"]["total_configs"] == 3
    assert len(batch["decompositions"]) == 3
    assert len(batch["fee_sensitivity"]) == 3
    assert len(batch["family_analysis"]) == 2  # 2 families
    assert len(batch["recommendations"]) > 0
    print(f"  Test 5 PASS: batch analysis")
    print(f"    {batch['summary']}")
    for rec in batch["recommendations"]:
        print(f"    REC: {rec}")

    # ---- Test 6: Report writer ----
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmpdir:
        base = os.path.join(tmpdir, "test_report")
        json_path, md_path = write_analysis_report(batch, base)
        assert os.path.exists(json_path), f"JSON not written: {json_path}"
        assert os.path.exists(md_path), f"MD not written: {md_path}"

        # Verify JSON is valid
        with open(json_path) as f:
            loaded = json.load(f)
        assert "summary" in loaded
        assert "decompositions" in loaded

        # Verify MD has content
        with open(md_path) as f:
            md_content = f.read()
        assert "Sprint 4 Edge Decomposition Report" in md_content
        assert "Config Scoreboard" in md_content

        print(f"  Test 6 PASS: report writer (JSON + MD)")
        print(f"    JSON: {os.path.getsize(json_path)} bytes")
        print(f"    MD: {os.path.getsize(md_path)} bytes")

    # ---- Test 7: class_a_share uses positive profit attribution ----
    # Scenario: Class A has +100, Class B has +20 and -50
    # total_profit = 100 + 20 = 120, class_a_profit = 100
    # class_a_share = 100/120 = 0.833
    mixed_exit_classes = {
        "A": {"DC TARGET": {"count": 2, "pnl": 100.0, "wins": 2}},
        "B": {
            "TIME MAX": {"count": 1, "pnl": 20.0, "wins": 1},
            "FIXED STOP": {"count": 2, "pnl": -50.0, "wins": 0},
        },
    }
    mixed_trades = [
        {"pnl": 50.0, "reason": "DC TARGET", "entry": 100, "exit": 110, "size": 500,
         "bars": 5, "entry_bar": 10, "exit_bar": 15, "pair": "A/USD"},
        {"pnl": 50.0, "reason": "DC TARGET", "entry": 100, "exit": 110, "size": 500,
         "bars": 5, "entry_bar": 20, "exit_bar": 25, "pair": "B/USD"},
        {"pnl": 20.0, "reason": "TIME MAX", "entry": 100, "exit": 104, "size": 500,
         "bars": 10, "entry_bar": 30, "exit_bar": 40, "pair": "C/USD"},
        {"pnl": -25.0, "reason": "FIXED STOP", "entry": 100, "exit": 95, "size": 500,
         "bars": 3, "entry_bar": 50, "exit_bar": 53, "pair": "D/USD"},
        {"pnl": -25.0, "reason": "FIXED STOP", "entry": 100, "exit": 95, "size": 500,
         "bars": 3, "entry_bar": 60, "exit_bar": 63, "pair": "E/USD"},
    ]
    mixed_result = {
        "summary": {"trades": 5, "pnl": 70.0, "pf": 2.4, "wr": 60.0, "dd": 8.0},
        "exit_classes": mixed_exit_classes,
        "trades": mixed_trades,
    }
    decomp_mixed = decompose_edge(mixed_result, "test_mixed")
    expected_share = 100.0 / 120.0  # ~0.8333
    assert abs(decomp_mixed.class_a_share - expected_share) < 0.01, \
        f"class_a_share: expected {expected_share:.4f}, got {decomp_mixed.class_a_share:.4f}"
    # Verify it's <= 1.0 (no abs-denominator bug)
    assert decomp_mixed.class_a_share <= 1.0, \
        f"class_a_share > 1.0: {decomp_mixed.class_a_share} (abs denominator bug!)"
    print(f"  Test 7 PASS: positive profit attribution")
    print(f"    class_a_share={decomp_mixed.class_a_share:.4f} "
          f"(expected {expected_share:.4f})")

    # ---- Test 8: Exit breakdown from trade_list ----
    assert "DC TARGET" in decomp_mixed.exit_breakdown
    assert "FIXED STOP" in decomp_mixed.exit_breakdown
    assert "TIME MAX" in decomp_mixed.exit_breakdown
    dc_stats = decomp_mixed.exit_breakdown["DC TARGET"]
    assert dc_stats["count"] == 2
    assert dc_stats["wr"] == 100.0
    assert dc_stats["avg_pnl"] == 50.0
    assert dc_stats["avg_bars"] == 5.0
    print(f"  Test 8 PASS: exit breakdown from trade_list")

    print("\n  All analysis tests passed")
