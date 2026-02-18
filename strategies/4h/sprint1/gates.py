"""
Sprint 1 Gate Evaluator — Hard + Soft gates for all-weather screening.

Hard gates (kill):
  G1: PF >= 1.30
  G2: MAX_DD <= 15%
  G3: TOP10_CONC (trades <= 50%, P&L <= 60% from top 10 coins)
  G4: WINDOW_SPLIT (3-way temporal, 2/3 windows PF >= 1.0)

Soft gates (ranking, no kill):
  S1: TRADE_FREQ >= 180 trades (target for all-weather)
  S2: EV_TRADE > $0
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------
DEFAULT_MIN_PF = 1.30
DEFAULT_MAX_DD = 15.0
DEFAULT_MAX_TOP10_TRADE_CONC = 50.0  # percent
DEFAULT_MAX_TOP10_PNL_CONC = 60.0    # percent
DEFAULT_TARGET_TRADES = 180
DEFAULT_WINDOW_COUNT = 3
DEFAULT_WINDOW_MIN_PF = 1.0
DEFAULT_WINDOW_PASS_COUNT = 2        # 2 of 3 must pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    name: str
    description: str
    passed: bool
    value: float
    threshold: str
    detail: str
    hard: bool = True  # hard gates kill, soft gates rank


@dataclass
class GateReport:
    gates: list[GateResult] = field(default_factory=list)
    soft_gates: list[GateResult] = field(default_factory=list)
    passed_all_hard: bool = False
    n_hard_passed: int = 0
    n_hard_total: int = 0
    verdict: str = "NO-GO"

    @property
    def summary_str(self) -> str:
        status = self.verdict
        parts = []
        for g in self.gates:
            mark = "PASS" if g.passed else "FAIL"
            parts.append(f"{g.name}={mark}")
        soft_parts = []
        for g in self.soft_gates:
            mark = "OK" if g.passed else "LOW"
            soft_parts.append(f"{g.name}={mark}")
        s = f"[{status}] {self.n_hard_passed}/{self.n_hard_total} | " + " | ".join(parts)
        if soft_parts:
            s += " || " + " | ".join(soft_parts)
        return s


# ---------------------------------------------------------------------------
# Hard gate functions
# ---------------------------------------------------------------------------

def _gate_profit_factor(bt: dict, *, min_pf: float = DEFAULT_MIN_PF, **_kw) -> GateResult:
    pf = bt.get("pf", 0.0)
    pf_display = min(pf, 99.9) if pf != float("inf") else 99.9
    return GateResult(
        name="G1:PF",
        description="Profit factor minimum",
        passed=pf >= min_pf,
        value=round(pf_display, 2),
        threshold=f">= {min_pf}",
        detail=f"PF {pf_display:.2f} ({'PASS' if pf >= min_pf else f'below {min_pf}'})",
    )


def _gate_max_drawdown(bt: dict, *, max_dd: float = DEFAULT_MAX_DD, **_kw) -> GateResult:
    dd = bt.get("dd", 100.0)
    return GateResult(
        name="G2:MAX_DD",
        description="Maximum drawdown",
        passed=dd <= max_dd,
        value=round(dd, 2),
        threshold=f"<= {max_dd}%",
        detail=f"DD {dd:.1f}% ({'PASS' if dd <= max_dd else f'exceeds {max_dd}%'})",
    )


def _gate_top10_concentration(
    bt: dict,
    *,
    max_trade_conc: float = DEFAULT_MAX_TOP10_TRADE_CONC,
    max_pnl_conc: float = DEFAULT_MAX_TOP10_PNL_CONC,
    **_kw,
) -> GateResult:
    """Top-10 coin concentration: both trade share and P&L share must be below threshold."""
    trade_list = bt.get("trade_list", [])
    n_trades = len(trade_list)

    if n_trades == 0:
        return GateResult(
            name="G3:TOP10_CONC", description="Top-10 coin concentration",
            passed=True, value=0.0, threshold=f"trades<={max_trade_conc}% & pnl<={max_pnl_conc}%",
            detail="N/A — no trades",
        )

    # Aggregate by coin
    coin_trades: dict[str, int] = {}
    coin_pnl: dict[str, float] = {}
    for t in trade_list:
        pair = t.get("pair", "UNKNOWN")
        coin_trades[pair] = coin_trades.get(pair, 0) + 1
        coin_pnl[pair] = coin_pnl.get(pair, 0.0) + t.get("pnl", 0.0)

    # Top 10 by trade count
    sorted_by_trades = sorted(coin_trades.items(), key=lambda x: x[1], reverse=True)
    top10_pairs = [p for p, _ in sorted_by_trades[:10]]

    top10_trade_count = sum(coin_trades[p] for p in top10_pairs)
    top10_trade_pct = top10_trade_count / n_trades * 100

    # Top 10 P&L share (using positive profit attribution)
    total_positive_pnl = sum(max(0, coin_pnl[p]) for p in coin_pnl)
    if total_positive_pnl > 0:
        # Use same top10 set (by trade count) for P&L share
        top10_positive_pnl = sum(max(0, coin_pnl.get(p, 0)) for p in top10_pairs)
        top10_pnl_pct = top10_positive_pnl / total_positive_pnl * 100
    else:
        top10_pnl_pct = 0.0

    passed = top10_trade_pct <= max_trade_conc and top10_pnl_pct <= max_pnl_conc

    return GateResult(
        name="G3:TOP10_CONC",
        description="Top-10 coin concentration (trades + P&L)",
        passed=passed,
        value=round(max(top10_trade_pct, top10_pnl_pct), 1),
        threshold=f"trades<={max_trade_conc}% & pnl<={max_pnl_conc}%",
        detail=(
            f"Top10: {top10_trade_pct:.1f}% trades, {top10_pnl_pct:.1f}% P&L "
            f"({'PASS' if passed else 'FAIL'})"
        ),
    )


def _gate_window_split(
    bt: dict,
    *,
    n_windows: int = DEFAULT_WINDOW_COUNT,
    min_pf: float = DEFAULT_WINDOW_MIN_PF,
    min_pass: int = DEFAULT_WINDOW_PASS_COUNT,
    total_bars: int = 720,
    **_kw,
) -> GateResult:
    """3-way temporal window split: 2/3 windows must have PF >= 1.0."""
    trade_list = bt.get("trade_list", [])

    if len(trade_list) < n_windows * 2:
        return GateResult(
            name="G4:WINDOW_SPLIT",
            description=f"{n_windows}-way temporal split",
            passed=False,
            value=0.0,
            threshold=f"{min_pass}/{n_windows} windows PF >= {min_pf}",
            detail=f"Insufficient trades ({len(trade_list)}) for {n_windows}-way split",
        )

    # Determine bar range from trades
    sorted_trades = sorted(trade_list, key=lambda t: t.get("entry_bar", 0))
    min_bar = sorted_trades[0].get("entry_bar", 0)
    max_bar = sorted_trades[-1].get("entry_bar", 0)
    bar_range = max_bar - min_bar
    if bar_range <= 0:
        bar_range = total_bars

    window_size = bar_range / n_windows
    window_results = []

    for w in range(n_windows):
        w_start = min_bar + w * window_size
        w_end = min_bar + (w + 1) * window_size
        w_trades = [t for t in sorted_trades if w_start <= t.get("entry_bar", 0) < w_end]

        w_wins = sum(t["pnl"] for t in w_trades if t["pnl"] > 0)
        w_losses = abs(sum(t["pnl"] for t in w_trades if t["pnl"] <= 0))
        w_pf = w_wins / w_losses if w_losses > 0 else (float("inf") if w_wins > 0 else 0.0)
        w_pass = w_pf >= min_pf

        window_results.append({
            "window": w + 1,
            "trades": len(w_trades),
            "pf": round(w_pf, 2),
            "passed": w_pass,
        })

    n_passed = sum(1 for w in window_results if w["passed"])
    overall_pass = n_passed >= min_pass

    detail_parts = []
    for w in window_results:
        mark = "PASS" if w["passed"] else "FAIL"
        detail_parts.append(f"W{w['window']}: {w['trades']}tr PF={w['pf']:.2f} [{mark}]")

    return GateResult(
        name="G4:WINDOW_SPLIT",
        description=f"{n_windows}-way temporal split ({min_pass}/{n_windows} must pass)",
        passed=overall_pass,
        value=float(n_passed),
        threshold=f"{min_pass}/{n_windows} windows PF >= {min_pf}",
        detail=" | ".join(detail_parts),
    )


# ---------------------------------------------------------------------------
# Soft gate functions (ranking only)
# ---------------------------------------------------------------------------

def _soft_trade_frequency(bt: dict, *, target_trades: int = DEFAULT_TARGET_TRADES, **_kw) -> GateResult:
    n = bt.get("trades", 0)
    return GateResult(
        name="S1:TRADE_FREQ",
        description="Trade frequency target (ranking)",
        passed=n >= target_trades,
        value=float(n),
        threshold=f">= {target_trades} (target)",
        detail=f"{n} trades ({'meets target' if n >= target_trades else f'below {target_trades}'})",
        hard=False,
    )


def _soft_ev_trade(bt: dict, **_kw) -> GateResult:
    n = bt.get("trades", 0)
    pnl = bt.get("pnl", 0.0)
    ev = pnl / n if n > 0 else 0.0
    return GateResult(
        name="S2:EV_TRADE",
        description="Expected value per trade (ranking)",
        passed=ev > 0,
        value=round(ev, 2),
        threshold="> $0",
        detail=f"EV/trade ${ev:.2f} ({'positive' if ev > 0 else 'negative or zero'})",
        hard=False,
    )


# ---------------------------------------------------------------------------
# Gate registry
# ---------------------------------------------------------------------------

HARD_GATES = [
    ("G1:PF", _gate_profit_factor),
    ("G2:MAX_DD", _gate_max_drawdown),
    ("G3:TOP10_CONC", _gate_top10_concentration),
    ("G4:WINDOW_SPLIT", _gate_window_split),
]

SOFT_GATES = [
    ("S1:TRADE_FREQ", _soft_trade_frequency),
    ("S2:EV_TRADE", _soft_ev_trade),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate all Sprint 1 gates.

    Parameters
    ----------
    result_dict : dict
        Backtest result with at least: trades, pnl, pf, dd, trade_list.
    **kwargs
        Override thresholds: min_pf, max_dd, max_trade_conc, max_pnl_conc,
        n_windows, min_pass, target_trades, total_bars.
    """
    report = GateReport()

    for _name, gate_fn in HARD_GATES:
        result = gate_fn(result_dict, **kwargs)
        report.gates.append(result)

    report.n_hard_total = len(report.gates)
    report.n_hard_passed = sum(1 for g in report.gates if g.passed)
    report.passed_all_hard = report.n_hard_passed == report.n_hard_total

    # Verdict
    if result_dict.get("trades", 0) == 0:
        report.verdict = "NO_TRADES"
    elif report.passed_all_hard:
        report.verdict = "GO"
    else:
        report.verdict = "NO-GO"

    # Soft gates
    for _name, gate_fn in SOFT_GATES:
        result = gate_fn(result_dict, **kwargs)
        report.soft_gates.append(result)

    return report


def print_gate_report(report: GateReport, label: str = "") -> None:
    width = 72
    header = "  SPRINT 1 GATES"
    if label:
        header += f" — {label}"
    print(f"\n{'=' * width}")
    print(header)
    print(f"{'=' * width}")

    for g in report.gates:
        mark = "PASS" if g.passed else "FAIL"
        print(f"  [{mark:4s}] {g.name:<18s} {g.detail}")

    if report.soft_gates:
        print(f"{'─' * width}")
        print("  Soft gates (ranking only):")
        for g in report.soft_gates:
            mark = " OK " if g.passed else "LOW "
            print(f"  [{mark:4s}] {g.name:<18s} {g.detail}")

    print(f"{'─' * width}")
    print(f"  Verdict: {report.verdict} ({report.n_hard_passed}/{report.n_hard_total} hard gates)")
    print(f"{'=' * width}\n")


def gates_to_dict(report: GateReport) -> dict[str, Any]:
    d: dict[str, Any] = {
        "verdict": report.verdict,
        "passed_all_hard": report.passed_all_hard,
        "n_hard_passed": report.n_hard_passed,
        "n_hard_total": report.n_hard_total,
        "summary": report.summary_str,
        "hard_gates": [asdict(g) for g in report.gates],
        "soft_gates": [asdict(g) for g in report.soft_gates],
    }
    return d
