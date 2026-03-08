"""
MS Sprint 1 Gate Evaluator — Hard + Soft gates for market structure screening.

Hard gates (KILL):
  G0: TRADES >= 80
  G1: PNL > 0     (KILL — prevents false positives from DD=100% + PF>1.0, ADR-MS-009)
  G2: PF >= 1.0   (KILL — 0 pass → MS CLOSED)

Soft gates (advance / informational):
  G3: PF >= 1.10  (advance to truth-pass)
  S1: DD <= 50%
  S2: WF >= 2/3 folds PF >= 0.9
  S3: Concentration — top1 coin < 30% trades
  S4: DC-geometry — % entries DC-compatible (informational)

Reuses GateResult/GateReport pattern from strategies/4h/sprint1/gates.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses (same pattern as Sprint 1)
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    name: str
    description: str
    passed: bool
    value: float
    threshold: str
    detail: str
    hard: bool = True


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
        parts = []
        for g in self.gates:
            mark = "PASS" if g.passed else "FAIL"
            parts.append(f"{g.name}={mark}")
        soft_parts = []
        for g in self.soft_gates:
            mark = "OK" if g.passed else "LOW"
            soft_parts.append(f"{g.name}={mark}")
        s = f"[{self.verdict}] {self.n_hard_passed}/{self.n_hard_total} | " + " | ".join(parts)
        if soft_parts:
            s += " || " + " | ".join(soft_parts)
        return s


# ---------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------

def _gate_trades(bt: dict, *, min_trades: int = 80, **_kw) -> GateResult:
    n = bt.get("trades", 0)
    return GateResult(
        name="G0:TRADES",
        description="Minimum trade count",
        passed=n >= min_trades,
        value=float(n),
        threshold=f">= {min_trades}",
        detail=f"{n} trades ({'PASS' if n >= min_trades else f'below {min_trades}'})",
    )


def _gate_pnl(bt: dict, **_kw) -> GateResult:
    """Hard gate: total P&L must be positive.

    Prevents false positives where PF > 1.0 but equity curve hit zero
    (engine continues tracking hypothetical trades after account death,
    inflating PF while actual P&L is negative).  See ADR-MS-009.
    """
    pnl = bt.get("pnl", 0.0)
    return GateResult(
        name="G1:PNL",
        description="Total P&L must be positive",
        passed=pnl > 0,
        value=round(pnl, 2),
        threshold="> 0",
        detail=f"P&L ${pnl:,.2f} ({'PASS' if pnl > 0 else 'NEGATIVE — bankrupt'})",
    )


def _gate_pf(bt: dict, *, min_pf: float = 1.0, **_kw) -> GateResult:
    pf = bt.get("pf", 0.0)
    pf_display = min(pf, 99.9) if pf != float("inf") else 99.9
    return GateResult(
        name="G2:PF",
        description="Profit factor minimum",
        passed=pf >= min_pf,
        value=round(pf_display, 2),
        threshold=f">= {min_pf}",
        detail=f"PF {pf_display:.2f} ({'PASS' if pf >= min_pf else f'below {min_pf}'})",
    )


# ---------------------------------------------------------------------------
# Soft gates
# ---------------------------------------------------------------------------

def _soft_pf_advance(bt: dict, *, advance_pf: float = 1.10, **_kw) -> GateResult:
    pf = bt.get("pf", 0.0)
    return GateResult(
        name="G3:PF_ADVANCE",
        description="PF advance to truth-pass",
        passed=pf >= advance_pf,
        value=round(min(pf, 99.9), 2),
        threshold=f">= {advance_pf}",
        detail=f"PF {min(pf, 99.9):.2f} ({'advance' if pf >= advance_pf else 'no advance'})",
        hard=False,
    )


def _soft_dd(bt: dict, *, max_dd: float = 50.0, **_kw) -> GateResult:
    dd = bt.get("dd", 100.0)
    return GateResult(
        name="S1:DD",
        description="Max drawdown",
        passed=dd <= max_dd,
        value=round(dd, 1),
        threshold=f"<= {max_dd}%",
        detail=f"DD {dd:.1f}% ({'OK' if dd <= max_dd else f'high'})",
        hard=False,
    )


def _soft_window_fold(bt: dict, *, n_folds: int = 3, min_fold_pf: float = 0.9, min_pass: int = 2, **_kw) -> GateResult:
    """Window stability: 2/3 temporal folds PF >= 0.9."""
    trade_list = bt.get("trade_list", [])
    if len(trade_list) < n_folds * 2:
        return GateResult(
            name="S2:WF",
            description=f"Window fold ({min_pass}/{n_folds} PF>={min_fold_pf})",
            passed=False, value=0.0,
            threshold=f"{min_pass}/{n_folds} folds PF >= {min_fold_pf}",
            detail=f"Insufficient trades ({len(trade_list)})",
            hard=False,
        )

    sorted_trades = sorted(trade_list, key=lambda t: t.get("entry_bar", 0))
    min_bar = sorted_trades[0].get("entry_bar", 0)
    max_bar = sorted_trades[-1].get("entry_bar", 0)
    bar_range = max(max_bar - min_bar, 1)
    fold_size = bar_range / n_folds

    n_passed = 0
    fold_details = []
    for f in range(n_folds):
        f_start = min_bar + f * fold_size
        f_end = min_bar + (f + 1) * fold_size
        f_trades = [t for t in sorted_trades if f_start <= t.get("entry_bar", 0) < f_end]
        f_wins = sum(t["pnl"] for t in f_trades if t["pnl"] > 0)
        f_losses = abs(sum(t["pnl"] for t in f_trades if t["pnl"] <= 0))
        f_pf = f_wins / f_losses if f_losses > 0 else (float("inf") if f_wins > 0 else 0.0)
        passed = f_pf >= min_fold_pf
        if passed:
            n_passed += 1
        fold_details.append(f"F{f+1}:{min(f_pf,99.9):.2f}")

    return GateResult(
        name="S2:WF",
        description=f"Window fold ({min_pass}/{n_folds} PF>={min_fold_pf})",
        passed=n_passed >= min_pass,
        value=float(n_passed),
        threshold=f"{min_pass}/{n_folds} folds PF >= {min_fold_pf}",
        detail=f"{n_passed}/{n_folds} pass | {' '.join(fold_details)}",
        hard=False,
    )


def _soft_concentration(bt: dict, *, max_top1_pct: float = 30.0, **_kw) -> GateResult:
    """Top-1 coin should contribute < 30% of total trades."""
    trade_list = bt.get("trade_list", [])
    n_trades = len(trade_list)
    if n_trades == 0:
        return GateResult(
            name="S3:CONC",
            description="Top-1 coin concentration",
            passed=True, value=0.0,
            threshold=f"top1 < {max_top1_pct}%",
            detail="N/A — no trades",
            hard=False,
        )
    coin_counts: dict[str, int] = {}
    for t in trade_list:
        pair = t.get("pair", "UNKNOWN")
        coin_counts[pair] = coin_counts.get(pair, 0) + 1
    top1_count = max(coin_counts.values())
    top1_pct = top1_count / n_trades * 100
    return GateResult(
        name="S3:CONC",
        description="Top-1 coin concentration",
        passed=top1_pct < max_top1_pct,
        value=round(top1_pct, 1),
        threshold=f"top1 < {max_top1_pct}%",
        detail=f"Top1: {top1_pct:.1f}% ({'OK' if top1_pct < max_top1_pct else 'concentrated'})",
        hard=False,
    )


def _soft_dc_geometry(bt: dict, **_kw) -> GateResult:
    """DC-geometry compliance: % entries where close < dc_mid AND close < bb_mid AND rsi < 40."""
    dc_geometry_scores = bt.get("dc_geometry_scores", [])
    if not dc_geometry_scores:
        return GateResult(
            name="S4:DC_GEO",
            description="DC-geometry compliance",
            passed=True, value=0.0,
            threshold="informational",
            detail="N/A — no DC geometry data",
            hard=False,
        )
    avg_score = sum(dc_geometry_scores) / len(dc_geometry_scores)
    n_full = sum(1 for s in dc_geometry_scores if s >= 0.99)
    pct_full = n_full / len(dc_geometry_scores) * 100
    return GateResult(
        name="S4:DC_GEO",
        description="DC-geometry compliance",
        passed=True,  # always passes (informational)
        value=round(avg_score, 2),
        threshold="informational",
        detail=f"avg={avg_score:.2f}, {pct_full:.0f}% full compliance ({n_full}/{len(dc_geometry_scores)})",
        hard=False,
    )


# ---------------------------------------------------------------------------
# Gate registry
# ---------------------------------------------------------------------------

HARD_GATES = [
    ("G0:TRADES", _gate_trades),
    ("G1:PNL", _gate_pnl),
    ("G2:PF", _gate_pf),
]

SOFT_GATES = [
    ("G3:PF_ADVANCE", _soft_pf_advance),
    ("S1:DD", _soft_dd),
    ("S2:WF", _soft_window_fold),
    ("S3:CONC", _soft_concentration),
    ("S4:DC_GEO", _soft_dc_geometry),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_ms_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate all MS Sprint 1 gates.

    Parameters
    ----------
    result_dict : dict
        Backtest result with: trades, pnl, pf, dd, trade_list, dc_geometry_scores.
    """
    report = GateReport()

    for _name, gate_fn in HARD_GATES:
        result = gate_fn(result_dict, **kwargs)
        report.gates.append(result)

    report.n_hard_total = len(report.gates)
    report.n_hard_passed = sum(1 for g in report.gates if g.passed)
    report.passed_all_hard = report.n_hard_passed == report.n_hard_total

    if result_dict.get("trades", 0) == 0:
        report.verdict = "NO_TRADES"
    elif report.passed_all_hard:
        report.verdict = "GO"
    else:
        report.verdict = "NO-GO"

    for _name, gate_fn in SOFT_GATES:
        result = gate_fn(result_dict, **kwargs)
        report.soft_gates.append(result)

    return report


def print_gate_report(report: GateReport, label: str = "") -> None:
    width = 72
    header = "  MS SPRINT 1 GATES"
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
        print("  Soft gates:")
        for g in report.soft_gates:
            mark = " OK " if g.passed else "LOW "
            print(f"  [{mark:4s}] {g.name:<18s} {g.detail}")

    print(f"{'─' * width}")
    print(f"  Verdict: {report.verdict} ({report.n_hard_passed}/{report.n_hard_total} hard gates)")
    print(f"{'=' * width}\n")


def gates_to_dict(report: GateReport) -> dict[str, Any]:
    return {
        "verdict": report.verdict,
        "passed_all_hard": report.passed_all_hard,
        "n_hard_passed": report.n_hard_passed,
        "n_hard_total": report.n_hard_total,
        "summary": report.summary_str,
        "hard_gates": [asdict(g) for g in report.gates],
        "soft_gates": [asdict(g) for g in report.soft_gates],
    }
