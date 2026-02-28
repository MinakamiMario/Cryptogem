"""
Sweep v1 Gate Evaluator — Reuses Sprint 1 gate logic with relaxed thresholds.

Screening gates (Stage 0):
  G1: PF >= 1.05        (advancement, not production)
  G2: MAX_DD <= 25%     (relaxed for screening; truth-pass uses 15%)
  G3: TOP10_CONC        (unchanged from Sprint 1)
  G4: WINDOW_SPLIT 2/3  (unchanged from Sprint 1)
  S1: TRADE_FREQ >= 50  (SOFT for screening; truth-pass gate uses 80)
  S2: EV_TRADE > $0     (soft, unchanged)

User tweak: trade count is soft in screening (ranking only), hard in truth-pass.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_sprint1_gates = importlib.import_module("strategies.4h.sprint1.gates")
evaluate_gates_base = _sprint1_gates.evaluate_gates
GateReport = _sprint1_gates.GateReport
GateResult = _sprint1_gates.GateResult
gates_to_dict = _sprint1_gates.gates_to_dict
print_gate_report = _sprint1_gates.print_gate_report

# ---------------------------------------------------------------------------
# Sweep v1 screening thresholds (Stage 0)
# ---------------------------------------------------------------------------
SWEEP_V1_MIN_PF = 1.05
SWEEP_V1_MAX_DD = 25.0
SWEEP_V1_SOFT_MIN_TRADES = 50       # soft in screening
SWEEP_V1_TRUTHPASS_MIN_TRADES = 80  # hard in truth-pass


def evaluate_sweep_v1_gates(result_dict: dict, **kwargs) -> GateReport:
    """Evaluate gates with Sweep v1 screening thresholds.

    Trade count is SOFT (ranking only) at screening stage.
    """
    return evaluate_gates_base(
        result_dict,
        min_pf=kwargs.pop("min_pf", SWEEP_V1_MIN_PF),
        max_dd=kwargs.pop("max_dd", SWEEP_V1_MAX_DD),
        target_trades=kwargs.pop("target_trades", SWEEP_V1_SOFT_MIN_TRADES),
        **kwargs,
    )
