"""
Gates-Lite: 4H DualConfirm Validation Gates

Simplified gate framework for quick GO/NO-GO decisions on 4H strategy configs.
Inspired by the 7-gate pipeline in agent_team_v3.py but lighter weight.

Usage:
    from strategies.4h.gates_4h import evaluate_gates, print_gate_report

    bt = run_backtest(indicators, coins, cfg)
    report = evaluate_gates(bt)
    print_gate_report(report)

Gates (required — affect verdict):
    G1: MIN_TRADES      -- minimum 15 trades (statistical significance)
    G2: MAX_DRAWDOWN    -- max drawdown <= 40% (capital preservation)
    G3: PROFIT_FACTOR   -- PF >= 1.3 (edge confirmation)
    G4: EXPECTANCY      -- EV/trade > $0 (positive expectancy)
    G5: ROBUSTNESS_SPLIT -- 2-split temporal validation (cheap walk-forward proxy)

Advisory gates (informational — do NOT affect verdict):
    G6: OUTLIER_CONC    -- top-1 trade < 70% of total profit
    G7: COIN_CONC       -- top-1 coin < 70% of total profit
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Default thresholds (overridable via kwargs)
# ---------------------------------------------------------------------------
DEFAULT_MIN_TRADES = 15
DEFAULT_MAX_DD = 40.0          # percent
DEFAULT_MIN_PF = 1.3
DEFAULT_MIN_EV = 0.0           # dollars per trade (strictly greater than)
DEFAULT_SPLIT_RATIO = 0.5      # chronological 50/50 split


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class GateResult:
    """Result for a single gate evaluation."""
    name: str
    description: str
    passed: bool
    value: float
    threshold: str
    detail: str
    advisory: bool = False  # Advisory gates don't affect verdict


@dataclass
class GateReport:
    """Aggregated result across all gates."""
    gates: list[GateResult] = field(default_factory=list)
    advisory_gates: list[GateResult] = field(default_factory=list)
    passed_all: bool = False
    n_passed: int = 0
    n_total: int = 0
    verdict: str = "NO-GO"

    @property
    def summary_str(self) -> str:
        status = "GO" if self.passed_all else "NO-GO"
        parts = []
        for g in self.gates:
            mark = "PASS" if g.passed else "FAIL"
            parts.append(f"{g.name}={mark}")
        adv_parts = []
        for g in self.advisory_gates:
            mark = "OK" if g.passed else "WARN"
            adv_parts.append(f"{g.name}={mark}")
        s = f"[{status}] {self.n_passed}/{self.n_total} | " + " | ".join(parts)
        if adv_parts:
            s += " || " + " | ".join(adv_parts)
        return s


# ---------------------------------------------------------------------------
# Individual gate functions
# ---------------------------------------------------------------------------
def _gate_min_trades(bt: dict, *, min_trades: int = DEFAULT_MIN_TRADES,
                     **_kw) -> GateResult:
    """G1: Minimum trade count for statistical significance."""
    n = bt.get("trades", 0)
    passed = n >= min_trades
    return GateResult(
        name="G1:MIN_TRADES",
        description="Minimum trade count for statistical significance",
        passed=passed,
        value=float(n),
        threshold=f">= {min_trades}",
        detail=f"{n} trades ({'sufficient' if passed else f'need >= {min_trades}'})",
    )


def _gate_max_drawdown(bt: dict, *, max_dd: float = DEFAULT_MAX_DD,
                       **_kw) -> GateResult:
    """G2: Maximum drawdown for capital preservation."""
    dd = bt.get("dd", 100.0)
    passed = dd <= max_dd
    return GateResult(
        name="G2:MAX_DRAWDOWN",
        description="Maximum drawdown for capital preservation",
        passed=passed,
        value=round(dd, 2),
        threshold=f"<= {max_dd}%",
        detail=f"DD {dd:.1f}% ({'within limit' if passed else f'exceeds {max_dd}%'})",
    )


def _gate_profit_factor(bt: dict, *, min_pf: float = DEFAULT_MIN_PF,
                        **_kw) -> GateResult:
    """G3: Profit factor for edge confirmation."""
    pf = bt.get("pf", 0.0)
    # Cap display at 99.9 for inf
    pf_display = min(pf, 99.9) if pf != float("inf") else 99.9
    passed = pf >= min_pf
    return GateResult(
        name="G3:PROFIT_FACTOR",
        description="Profit factor for edge confirmation",
        passed=passed,
        value=round(pf_display, 2),
        threshold=f">= {min_pf}",
        detail=f"PF {pf_display:.2f} ({'edge confirmed' if passed else f'below {min_pf}'})",
    )


def _gate_expectancy(bt: dict, *, min_ev: float = DEFAULT_MIN_EV,
                     **_kw) -> GateResult:
    """G4: Positive expectancy per trade."""
    n = bt.get("trades", 0)
    pnl = bt.get("pnl", 0.0)
    ev = pnl / n if n > 0 else 0.0
    passed = ev > min_ev
    return GateResult(
        name="G4:EXPECTANCY",
        description="Positive expected value per trade",
        passed=passed,
        value=round(ev, 2),
        threshold=f"> ${min_ev:.0f}",
        detail=f"EV/trade ${ev:.2f} ({'positive' if passed else 'negative or zero'})",
    )


def _gate_robustness_split(bt: dict, *,
                           split_ratio: float = DEFAULT_SPLIT_RATIO,
                           split_results: Optional[tuple[dict, dict]] = None,
                           **_kw) -> GateResult:
    """G5: 2-split temporal validation — both halves must be profitable.

    Works in two modes:
        1. Pre-split: caller provides split_results=(first_half_bt, second_half_bt)
        2. Trade-list split: splits bt['trade_list'] chronologically by entry_bar

    Mode 2 is a fast approximation (no re-run). Mode 1 is more accurate because
    each half gets its own equity curve and position management.
    """
    # Mode 1: pre-computed split results provided by caller
    if split_results is not None:
        pnl_1 = split_results[0].get("pnl", 0.0)
        pnl_2 = split_results[1].get("pnl", 0.0)
        n_1 = split_results[0].get("trades", 0)
        n_2 = split_results[1].get("trades", 0)
        both_profitable = pnl_1 > 0 and pnl_2 > 0
        return GateResult(
            name="G5:ROBUSTNESS_SPLIT",
            description="2-split temporal validation (both halves profitable)",
            passed=both_profitable,
            value=1.0 if both_profitable else 0.0,
            threshold="both halves P&L > $0",
            detail=(
                f"H1: {n_1}tr ${pnl_1:+.0f} | H2: {n_2}tr ${pnl_2:+.0f} "
                f"({'PASS' if both_profitable else 'FAIL'})"
            ),
        )

    # Mode 2: split trade_list by chronological midpoint
    trade_list = bt.get("trade_list", [])
    if len(trade_list) < 4:
        return GateResult(
            name="G5:ROBUSTNESS_SPLIT",
            description="2-split temporal validation (both halves profitable)",
            passed=False,
            value=0.0,
            threshold="both halves P&L > $0",
            detail=f"Insufficient trades ({len(trade_list)}) for split (need >= 4)",
        )

    # Find the chronological midpoint by entry_bar
    sorted_trades = sorted(trade_list, key=lambda t: t.get("entry_bar", 0))
    all_bars = [t.get("entry_bar", 0) for t in sorted_trades]
    min_bar = all_bars[0]
    max_bar = all_bars[-1]
    mid_bar = min_bar + (max_bar - min_bar) * split_ratio

    first_half = [t for t in sorted_trades if t.get("entry_bar", 0) < mid_bar]
    second_half = [t for t in sorted_trades if t.get("entry_bar", 0) >= mid_bar]

    # Edge case: if all trades fall in one half, fail the gate
    if not first_half or not second_half:
        return GateResult(
            name="G5:ROBUSTNESS_SPLIT",
            description="2-split temporal validation (both halves profitable)",
            passed=False,
            value=0.0,
            threshold="both halves P&L > $0",
            detail=f"Split produced empty half (H1={len(first_half)}, H2={len(second_half)})",
        )

    pnl_1 = sum(t.get("pnl", 0.0) for t in first_half)
    pnl_2 = sum(t.get("pnl", 0.0) for t in second_half)
    n_1 = len(first_half)
    n_2 = len(second_half)
    both_profitable = pnl_1 > 0 and pnl_2 > 0

    return GateResult(
        name="G5:ROBUSTNESS_SPLIT",
        description="2-split temporal validation (both halves profitable)",
        passed=both_profitable,
        value=1.0 if both_profitable else 0.0,
        threshold="both halves P&L > $0",
        detail=(
            f"H1: {n_1}tr ${pnl_1:+.0f} | H2: {n_2}tr ${pnl_2:+.0f} "
            f"({'PASS' if both_profitable else 'FAIL'})"
        ),
    )


# ---------------------------------------------------------------------------
# Advisory gate functions (G6, G7) — do NOT affect verdict
# ---------------------------------------------------------------------------
DEFAULT_MAX_OUTLIER_CONC = 70.0   # percent — top 1 trade < 70% of total profit
DEFAULT_MAX_COIN_CONC = 70.0      # percent — top 1 coin < 70% of total profit


def _gate_outlier_concentration(
    bt: dict,
    *,
    max_outlier_conc: float = DEFAULT_MAX_OUTLIER_CONC,
    **_kw,
) -> GateResult:
    """G6: Outlier concentration — top 1 trade should not dominate total profit.

    Prevents over-reliance on a single lucky trade (e.g. ZEUS in historical data).
    Calculation: max(trade.pnl for positive trades) / sum(trade.pnl for positive trades).
    """
    trade_list = bt.get("trade_list", [])
    positive_pnls = [t.get("pnl", 0.0) for t in trade_list if t.get("pnl", 0.0) > 0]

    if not positive_pnls:
        return GateResult(
            name="G6:OUTLIER_CONC",
            description="Top-1 trade share of total profit (advisory)",
            passed=True,  # N/A — no positive trades to judge
            value=0.0,
            threshold=f"< {max_outlier_conc}%",
            detail="N/A — no positive trades",
            advisory=True,
        )

    total_profit = sum(positive_pnls)
    top1_pnl = max(positive_pnls)
    top1_share = (top1_pnl / total_profit * 100.0) if total_profit > 0 else 0.0
    passed = top1_share < max_outlier_conc

    return GateResult(
        name="G6:OUTLIER_CONC",
        description="Top-1 trade share of total profit (advisory)",
        passed=passed,
        value=round(top1_share, 1),
        threshold=f"< {max_outlier_conc}%",
        detail=(
            f"Top-1 trade ${top1_pnl:+.0f} = {top1_share:.1f}% of "
            f"${total_profit:.0f} profit "
            f"({'OK' if passed else 'HIGH — scrutinize'})"
        ),
        advisory=True,
    )


def _gate_coin_concentration(
    bt: dict,
    *,
    max_coin_conc: float = DEFAULT_MAX_COIN_CONC,
    **_kw,
) -> GateResult:
    """G7: Coin concentration — top 1 coin should not dominate total profit.

    Prevents strategies that are effectively 1-coin wonders.
    Calculation: group trades by pair, sum P&L per coin, max(coin_pnl) / total_positive_pnl.
    """
    trade_list = bt.get("trade_list", [])

    # Aggregate P&L by coin pair
    coin_pnls: dict[str, float] = {}
    for t in trade_list:
        pair = t.get("pair", "UNKNOWN")
        coin_pnls[pair] = coin_pnls.get(pair, 0.0) + t.get("pnl", 0.0)

    # Only consider coins with positive aggregate P&L for concentration
    positive_coins = {k: v for k, v in coin_pnls.items() if v > 0}

    if not positive_coins:
        return GateResult(
            name="G7:COIN_CONC",
            description="Top-1 coin share of total profit (advisory)",
            passed=True,  # N/A — no profitable coins to judge
            value=0.0,
            threshold=f"< {max_coin_conc}%",
            detail="N/A — no coins with positive P&L",
            advisory=True,
        )

    total_positive = sum(positive_coins.values())
    top_coin = max(positive_coins, key=positive_coins.get)
    top_coin_pnl = positive_coins[top_coin]
    top_coin_share = (top_coin_pnl / total_positive * 100.0) if total_positive > 0 else 0.0
    passed = top_coin_share < max_coin_conc

    return GateResult(
        name="G7:COIN_CONC",
        description="Top-1 coin share of total profit (advisory)",
        passed=passed,
        value=round(top_coin_share, 1),
        threshold=f"< {max_coin_conc}%",
        detail=(
            f"Top coin {top_coin} ${top_coin_pnl:+.0f} = {top_coin_share:.1f}% of "
            f"${total_positive:.0f} profit "
            f"({'OK' if passed else 'HIGH — scrutinize'})"
        ),
        advisory=True,
    )


# ---------------------------------------------------------------------------
# Gate registry
# ---------------------------------------------------------------------------
GATE_FUNCTIONS: list[tuple[str, Callable]] = [
    ("G1:MIN_TRADES", _gate_min_trades),
    ("G2:MAX_DRAWDOWN", _gate_max_drawdown),
    ("G3:PROFIT_FACTOR", _gate_profit_factor),
    ("G4:EXPECTANCY", _gate_expectancy),
    ("G5:ROBUSTNESS_SPLIT", _gate_robustness_split),
]

ADVISORY_GATE_FUNCTIONS: list[tuple[str, Callable]] = [
    ("G6:OUTLIER_CONC", _gate_outlier_concentration),
    ("G7:COIN_CONC", _gate_coin_concentration),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def evaluate_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate all gates against a backtest result dict.

    Parameters
    ----------
    result_dict : dict
        Output of run_backtest() — must contain at least:
        trades, pnl, pf, dd, trade_list.
    **kwargs
        Override any gate threshold:
        min_trades, max_dd, min_pf, min_ev, split_ratio,
        split_results (tuple of two backtest result dicts for G5),
        max_outlier_conc, max_coin_conc (advisory gates).

    Returns
    -------
    GateReport with per-gate results, advisory gate results,
    overall pass/fail, and verdict string.

    Note: advisory gates (G6, G7) are always evaluated but do NOT
    affect passed_all or verdict. They are informational only.
    """
    report = GateReport()

    # --- Required gates (affect verdict) ---
    for _name, gate_fn in GATE_FUNCTIONS:
        result = gate_fn(result_dict, **kwargs)
        report.gates.append(result)

    report.n_total = len(report.gates)
    report.n_passed = sum(1 for g in report.gates if g.passed)
    report.passed_all = report.n_passed == report.n_total

    # Verdict logic: G1 failure is special (insufficient sample)
    g1 = report.gates[0]
    if not g1.passed:
        report.verdict = "INSUFFICIENT_SAMPLE"
    elif report.passed_all:
        report.verdict = "GO"
    else:
        report.verdict = "NO-GO"

    # --- Advisory gates (do NOT affect verdict) ---
    for _name, gate_fn in ADVISORY_GATE_FUNCTIONS:
        result = gate_fn(result_dict, **kwargs)
        report.advisory_gates.append(result)

    return report


def print_gate_report(report: GateReport, label: str = "") -> None:
    """Print a formatted gate report to console."""
    header = f"  GATES-LITE REPORT"
    if label:
        header += f" — {label}"
    width = 72
    print(f"\n{'=' * width}")
    print(header)
    print(f"{'=' * width}")

    for g in report.gates:
        mark = "PASS" if g.passed else "FAIL"
        print(f"  [{mark:4s}] {g.name:<22s} {g.detail}")

    if report.advisory_gates:
        print(f"{'─' * width}")
        print("  Advisory (do not affect verdict):")
        for g in report.advisory_gates:
            mark = " OK " if g.passed else "WARN"
            print(f"  [{mark:4s}] {g.name:<22s} {g.detail}")

    print(f"{'─' * width}")
    print(f"  Verdict: {report.verdict} ({report.n_passed}/{report.n_total} gates passed)")
    print(f"{'=' * width}\n")


def gates_to_dict(report: GateReport) -> dict[str, Any]:
    """Serialize a GateReport to a JSON-compatible dict."""
    d: dict[str, Any] = {
        "verdict": report.verdict,
        "passed_all": report.passed_all,
        "n_passed": report.n_passed,
        "n_total": report.n_total,
        "summary": report.summary_str,
        "gates": [asdict(g) for g in report.gates],
    }
    if report.advisory_gates:
        d["advisory_gates"] = [asdict(g) for g in report.advisory_gates]
    return d


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Mock backtest result that mimics run_backtest() output format
    mock_result = {
        "trades": 39,
        "wr": 56.4,
        "pnl": 3950.0,
        "final_equity": 5950.0,
        "pf": 3.2,
        "dd": 30.7,
        "broke": False,
        "early_stopped": False,
        "trade_list": [
            # Simulate 39 trades spread across bars 50-721
            # First half: 20 trades (bars 50-385), mixed results
            {"pair": f"COIN{i}/USD", "entry": 1.0, "exit": 1.05,
             "pnl": 80.0, "pnl_pct": 4.0, "reason": "DC TARGET",
             "bars": 5, "entry_bar": 50 + i * 16, "exit_bar": 55 + i * 16,
             "size": 2000.0, "equity_after": 2080.0}
            for i in range(12)
        ] + [
            {"pair": f"LOSS{i}/USD", "entry": 1.0, "exit": 0.96,
             "pnl": -60.0, "pnl_pct": -3.0, "reason": "TRAIL STOP",
             "bars": 8, "entry_bar": 250 + i * 10, "exit_bar": 258 + i * 10,
             "size": 2000.0, "equity_after": 1940.0}
            for i in range(8)
        ] + [
            # Second half: 19 trades (bars 386-721), mixed results
            {"pair": f"COIN{i}/USD", "entry": 1.0, "exit": 1.08,
             "pnl": 150.0, "pnl_pct": 7.5, "reason": "RSI RECOVERY",
             "bars": 4, "entry_bar": 390 + i * 18, "exit_bar": 394 + i * 18,
             "size": 2000.0, "equity_after": 2150.0}
            for i in range(12)
        ] + [
            {"pair": f"LOSS{i}/USD", "entry": 1.0, "exit": 0.94,
             "pnl": -90.0, "pnl_pct": -4.5, "reason": "HARD STOP",
             "bars": 10, "entry_bar": 600 + i * 15, "exit_bar": 610 + i * 15,
             "size": 2000.0, "equity_after": 1910.0}
            for i in range(7)
        ],
        "exit_classes": {
            "A": {"DC TARGET": {"count": 12, "pnl": 960.0, "wins": 12},
                  "RSI RECOVERY": {"count": 12, "pnl": 1800.0, "wins": 12}},
            "B": {"TRAIL STOP": {"count": 8, "pnl": -480.0, "wins": 0},
                  "HARD STOP": {"count": 7, "pnl": -630.0, "wins": 0}},
        },
    }

    print("=" * 72)
    print("  Gates-Lite Demo: Mock V5+VolSpk3 backtest result")
    print("=" * 72)

    report = evaluate_gates(mock_result)
    print_gate_report(report, label="V5+VolSpk3 (mock)")

    # Show JSON output
    print("JSON output:")
    print(json.dumps(gates_to_dict(report), indent=2))

    # --- Demo with custom thresholds ---
    print("\n" + "=" * 72)
    print("  Custom thresholds: stricter (min_trades=25, min_pf=2.0)")
    print("=" * 72)
    strict_report = evaluate_gates(mock_result, min_trades=25, min_pf=2.0)
    print_gate_report(strict_report, label="V5+VolSpk3 (strict)")

    # --- Demo with a failing result ---
    failing_result = {
        "trades": 8,
        "wr": 37.5,
        "pnl": -120.0,
        "final_equity": 1880.0,
        "pf": 0.6,
        "dd": 55.0,
        "broke": False,
        "early_stopped": False,
        "trade_list": [
            {"pair": f"X{i}/USD", "entry": 1.0, "exit": 0.97,
             "pnl": -40.0, "pnl_pct": -2.0, "reason": "TIME MAX",
             "bars": 10, "entry_bar": 100 + i * 80, "exit_bar": 110 + i * 80,
             "size": 2000.0, "equity_after": 1960.0}
            for i in range(8)
        ],
        "exit_classes": {"A": {}, "B": {"TIME MAX": {"count": 8, "pnl": -320.0, "wins": 0}}},
    }
    print("\n" + "=" * 72)
    print("  Failing config demo")
    print("=" * 72)
    fail_report = evaluate_gates(failing_result)
    print_gate_report(fail_report, label="Bad config")

    # --- Demo with high outlier/coin concentration (advisory warning) ---
    concentrated_result = {
        "trades": 20,
        "wr": 50.0,
        "pnl": 2000.0,
        "final_equity": 4000.0,
        "pf": 2.5,
        "dd": 25.0,
        "broke": False,
        "early_stopped": False,
        "trade_list": [
            # 1 huge ZEUS-like trade on a single coin
            {"pair": "ZEUS/USD", "entry": 1.0, "exit": 2.5,
             "pnl": 3000.0, "pnl_pct": 150.0, "reason": "RSI RECOVERY",
             "bars": 3, "entry_bar": 100, "exit_bar": 103,
             "size": 2000.0, "equity_after": 5000.0},
        ] + [
            # 9 small winners spread across different coins
            {"pair": f"ALT{i}/USD", "entry": 1.0, "exit": 1.02,
             "pnl": 40.0, "pnl_pct": 2.0, "reason": "DC TARGET",
             "bars": 5, "entry_bar": 200 + i * 30, "exit_bar": 205 + i * 30,
             "size": 2000.0, "equity_after": 2040.0}
            for i in range(9)
        ] + [
            # 10 losers
            {"pair": f"LOSS{i}/USD", "entry": 1.0, "exit": 0.94,
             "pnl": -136.0, "pnl_pct": -6.8, "reason": "TRAIL STOP",
             "bars": 8, "entry_bar": 400 + i * 30, "exit_bar": 408 + i * 30,
             "size": 2000.0, "equity_after": 1864.0}
            for i in range(10)
        ],
        "exit_classes": {
            "A": {"RSI RECOVERY": {"count": 1, "pnl": 3000.0, "wins": 1},
                  "DC TARGET": {"count": 9, "pnl": 360.0, "wins": 9}},
            "B": {"TRAIL STOP": {"count": 10, "pnl": -1360.0, "wins": 0}},
        },
    }
    print("\n" + "=" * 72)
    print("  High concentration demo (advisory warnings expected)")
    print("=" * 72)
    conc_report = evaluate_gates(concentrated_result)
    print_gate_report(conc_report, label="ZEUS-heavy config")
