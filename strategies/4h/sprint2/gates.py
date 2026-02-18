"""
Sprint 2 Gate Evaluator — Relaxed Stage 0 gates for entry-edge discovery.

Reuses Sprint 1 gate infrastructure with relaxed thresholds:

Stage 0 advancement gate (the key difference):
  G0: PF > 1.05 (relaxed from Sprint 1's PF >= 1.30)

Rationale: Sprint 1 showed fixed exits kill edge. PF > 1.05 with fixed exits
indicates *entry edge* that smart exits can amplify. DualConfirm has PF~0.9
with fixed exits but PF 3.2-3.8 with smart exits.

Full Sprint 1 gates (G1-G4 + S1-S2) are applied to truth-pass winners only.
"""
from __future__ import annotations

import importlib
from dataclasses import asdict

# Import Sprint 1 gates (reuse infrastructure)
_sprint1_gates = importlib.import_module("strategies.4h.sprint1.gates")

# Re-export Sprint 1 types and functions
GateResult = _sprint1_gates.GateResult
GateReport = _sprint1_gates.GateReport
gates_to_dict = _sprint1_gates.gates_to_dict
print_gate_report = _sprint1_gates.print_gate_report


# ---------------------------------------------------------------------------
# Sprint 2 relaxed thresholds
# ---------------------------------------------------------------------------
STAGE0_MIN_PF = 1.05      # Advancement threshold (not production)
STAGE0_MAX_DD = 25.0       # Relaxed DD (expect higher with simple exits)
STAGE0_MIN_TRADES = 10     # At least 10 trades for minimal significance


# ---------------------------------------------------------------------------
# Sprint 2 gate evaluator
# ---------------------------------------------------------------------------

def evaluate_sprint2_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate Sprint 2 Stage 0 gates (relaxed for entry-edge screening).

    Uses Sprint 1 gates with relaxed thresholds:
      - min_pf = 1.05 (from 1.30)
      - max_dd = 25% (from 15%)
      - window split requires 1/3 instead of 2/3

    Parameters
    ----------
    result_dict : dict
        Backtest result with at least: trades, pnl, pf, dd, trade_list.
    **kwargs
        Override thresholds.
    """
    # Apply relaxed thresholds (kwargs can still override)
    relaxed_kwargs = {
        "min_pf": STAGE0_MIN_PF,
        "max_dd": STAGE0_MAX_DD,
        "min_pass": 1,       # 1/3 windows (relaxed from 2/3)
        "target_trades": 50,  # Relaxed from 180
    }
    relaxed_kwargs.update(kwargs)

    return _sprint1_gates.evaluate_gates(result_dict, **relaxed_kwargs)


def evaluate_full_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate full Sprint 1 production gates (for truth-pass winners).

    Same thresholds as Sprint 1:
      - PF >= 1.30, DD <= 15%, window split 2/3, etc.
    """
    return _sprint1_gates.evaluate_gates(result_dict, **kwargs)


def print_sprint2_report(report: GateReport, label: str = "") -> None:
    """Print Sprint 2 gate report with custom header."""
    width = 72
    header = "  SPRINT 2 GATES (Stage 0 — relaxed)"
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
