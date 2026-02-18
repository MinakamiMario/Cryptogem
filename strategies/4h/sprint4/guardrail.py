"""
Sprint 4 Guardrail & Provenance Verification Module.

Ensures deterministic replay, data provenance, accounting integrity,
and fee consistency for all Sprint 4 experiments.

Frozen provenance:
  dataset_id:  ohlcv_4h_kraken_spot_usd_526
  universe_id: universe_sprint1
  fee_model:   kraken_spot_26bps (KRAKEN_FEE = 0.0026 per side)
  git_hash:    9a606d9 (research freeze)
"""
from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Constants — frozen from Sprint 1/2/3
# ---------------------------------------------------------------------------

EXPECTED_DATASET_ID = "ohlcv_4h_kraken_spot_usd_526"
EXPECTED_UNIVERSE_ID = "universe_sprint1"
EXPECTED_FEE = 0.0026  # per-side Kraken spot
EXPECTED_COIN_COUNT = 487
EXPECTED_MIN_BARS = 360
INITIAL_CAPITAL = 2000.0

# All valid exit reasons across Sprint 1/2/3 engines
VALID_EXIT_REASONS = frozenset({
    "FIXED STOP", "HARD STOP",      # Class B stops
    "TIME MAX",                      # Class B time-out
    "END",                           # Class B end-of-data
    "PROFIT TARGET",                 # Class A fixed TP
    "RSI RECOVERY",                  # Class A smart exit
    "DC TARGET",                     # Class A Donchian midpoint
    "BB TARGET",                     # Class A Bollinger midpoint
})

# Class A reasons — parity with sprint3/engine.py and sprint3/exits.py
CLASS_A_REASONS = frozenset({"PROFIT TARGET", "RSI RECOVERY", "DC TARGET", "BB TARGET"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ProvenanceRecord:
    """Frozen provenance snapshot for a Sprint 4 experiment."""
    dataset_id: str
    universe_id: str
    fee_model: str
    git_hash: str
    n_coins: int
    n_bars_min: int
    timestamp: str
    engine_fee: float
    exit_mode: str


# ---------------------------------------------------------------------------
# 1. Provenance Checker
# ---------------------------------------------------------------------------

def _get_git_hash() -> str:
    """Get short git hash of current HEAD."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def verify_provenance(
    data: dict,
    coins: list[str],
    *,
    expected_dataset_id: str = EXPECTED_DATASET_ID,
    expected_universe_id: str = EXPECTED_UNIVERSE_ID,
    expected_fee: float = EXPECTED_FEE,
    expected_min_bars: int = EXPECTED_MIN_BARS,
) -> tuple[bool, list[str]]:
    """Verify data/universe provenance matches frozen specs.

    Returns (all_ok, list_of_violations).

    Checks:
    - len(coins) should be 487 (hard fail if different)
    - All coins must have >= expected_min_bars candles
    - Fee constant matches engine constant
    - All coins in list must exist in data dict
    """
    violations: list[str] = []

    # --- Coin count ---
    actual_count = len(coins)
    if actual_count != EXPECTED_COIN_COUNT:
        violations.append(
            f"COIN_COUNT: expected {EXPECTED_COIN_COUNT}, got {actual_count}"
        )

    # --- Coin presence in data ---
    missing_coins = [c for c in coins if c not in data]
    if missing_coins:
        violations.append(
            f"MISSING_DATA: {len(missing_coins)} coins in universe but not in data: "
            f"{missing_coins[:5]}{'...' if len(missing_coins) > 5 else ''}"
        )

    # --- Minimum bars ---
    short_coins: list[tuple[str, int]] = []
    for coin in coins:
        candles = data.get(coin, [])
        n = len(candles)
        if n < expected_min_bars:
            short_coins.append((coin, n))

    if short_coins:
        violations.append(
            f"MIN_BARS: {len(short_coins)} coins have < {expected_min_bars} bars. "
            f"Worst: {short_coins[:3]}"
        )

    # --- Fee parity with engine ---
    # Lazy import to verify engine constant matches expectation
    try:
        engine = importlib.import_module("strategies.4h.sprint3.engine")
        if abs(engine.KRAKEN_FEE - expected_fee) > 1e-10:
            violations.append(
                f"FEE_MISMATCH: engine KRAKEN_FEE={engine.KRAKEN_FEE}, "
                f"expected {expected_fee}"
            )
    except ImportError:
        violations.append("ENGINE_IMPORT: could not import strategies.4h.sprint3.engine")

    all_ok = len(violations) == 0
    return all_ok, violations


# ---------------------------------------------------------------------------
# 2. Deterministic Replay Test
# ---------------------------------------------------------------------------

def replay_test(
    data: dict,
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    *,
    exit_mode: str = "dc",
    n_runs: int = 3,
    fee: float = EXPECTED_FEE,
    initial_capital: float = INITIAL_CAPITAL,
) -> tuple[bool, dict]:
    """Run backtest N times, verify identical results each time.

    Returns (deterministic: bool, details: dict).
    Uses the Sprint 3 engine's run_backtest() function.
    Compares: trades, pnl, pf, dd across all N runs.
    """
    engine = importlib.import_module("strategies.4h.sprint3.engine")
    run_bt = engine.run_backtest

    results: list[dict] = []
    for i in range(n_runs):
        res = run_bt(
            data, coins, signal_fn, params, indicators,
            exit_mode=exit_mode,
            fee=fee,
            initial_capital=initial_capital,
        )
        results.append({
            "run": i + 1,
            "trades": res.trades,
            "pnl": res.pnl,
            "pf": res.pf,
            "dd": res.dd,
            "final_equity": res.final_equity,
        })

    # Compare all runs to run 0
    ref = results[0]
    mismatches: list[str] = []
    for r in results[1:]:
        for key in ("trades", "pnl", "pf", "dd", "final_equity"):
            ref_val = ref[key]
            run_val = r[key]
            # Use exact comparison for int, tolerance for float
            if isinstance(ref_val, int):
                if ref_val != run_val:
                    mismatches.append(
                        f"Run {r['run']} {key}: {run_val} != {ref_val} (run 1)"
                    )
            else:
                # Allow tiny floating point tolerance (1e-6 relative)
                if ref_val == 0.0:
                    if run_val != 0.0:
                        mismatches.append(
                            f"Run {r['run']} {key}: {run_val} != 0.0 (run 1)"
                        )
                elif abs(run_val - ref_val) / max(abs(ref_val), 1e-15) > 1e-6:
                    mismatches.append(
                        f"Run {r['run']} {key}: {run_val} != {ref_val} (run 1)"
                    )

    deterministic = len(mismatches) == 0
    details = {
        "n_runs": n_runs,
        "deterministic": deterministic,
        "reference": ref,
        "all_results": results,
        "mismatches": mismatches,
    }
    return deterministic, details


# ---------------------------------------------------------------------------
# 3. Accounting Validator
# ---------------------------------------------------------------------------

def validate_accounting(
    result,  # BacktestResult from engine
    initial_capital: float = INITIAL_CAPITAL,
) -> tuple[bool, list[str]]:
    """Validate internal consistency of backtest results.

    Checks:
    - final_equity = initial_capital + pnl
    - last trade's equity_after == final_equity
    - PF recomputation matches: sum(wins) / abs(sum(losses))
    - No NaN/Inf values in trade_list
    - All exit reasons are valid strings
    - Class A / Class B assignment matches exit reason
    """
    violations: list[str] = []

    # --- final_equity = initial + pnl ---
    expected_equity = initial_capital + result.pnl
    if abs(result.final_equity - expected_equity) > 0.02:
        violations.append(
            f"EQUITY_BALANCE: final_equity={result.final_equity:.2f} != "
            f"initial({initial_capital}) + pnl({result.pnl}) = {expected_equity:.2f}"
        )

    # --- Last trade equity_after ---
    if result.trade_list:
        last_eq = result.trade_list[-1].get("equity_after", None)
        if last_eq is not None:
            if abs(last_eq - result.final_equity) > 0.02:
                violations.append(
                    f"LAST_TRADE_EQUITY: last trade equity_after={last_eq:.2f} "
                    f"!= final_equity={result.final_equity:.2f}"
                )

    # --- PF recomputation ---
    wins = [t["pnl"] for t in result.trade_list if t["pnl"] > 0]
    losses = [t["pnl"] for t in result.trade_list if t["pnl"] <= 0]
    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    if sum_losses > 0:
        expected_pf = sum_wins / sum_losses
    elif sum_wins > 0:
        expected_pf = float("inf")
    else:
        expected_pf = 0.0

    # Handle inf comparison
    if math.isinf(expected_pf) and math.isinf(result.pf):
        pass  # both inf, OK
    elif math.isinf(expected_pf) or math.isinf(result.pf):
        violations.append(
            f"PF_MISMATCH: computed PF={expected_pf}, result PF={result.pf}"
        )
    elif abs(expected_pf - result.pf) > 0.01:
        violations.append(
            f"PF_MISMATCH: computed PF={expected_pf:.4f}, "
            f"result PF={result.pf:.4f} (delta={abs(expected_pf - result.pf):.4f})"
        )

    # --- NaN/Inf check in trade_list ---
    numeric_fields = ("entry", "exit", "pnl", "pnl_pct", "size", "equity_after")
    for i, t in enumerate(result.trade_list):
        for fld in numeric_fields:
            val = t.get(fld)
            if val is not None and isinstance(val, float):
                if math.isnan(val) or math.isinf(val):
                    violations.append(
                        f"NUMERIC_INVALID: trade[{i}] {fld}={val} "
                        f"(pair={t.get('pair', '?')})"
                    )

    # --- Valid exit reasons ---
    for i, t in enumerate(result.trade_list):
        reason = t.get("reason", None)
        if reason not in VALID_EXIT_REASONS:
            violations.append(
                f"INVALID_REASON: trade[{i}] reason={reason!r} "
                f"(pair={t.get('pair', '?')})"
            )

    # --- Class A/B assignment ---
    exit_classes = result.exit_classes
    for reason, stats in exit_classes.get("A", {}).items():
        if reason not in CLASS_A_REASONS:
            violations.append(
                f"CLASS_MISMATCH: reason={reason!r} in Class A but not in CLASS_A_REASONS"
            )
    for reason, stats in exit_classes.get("B", {}).items():
        if reason in CLASS_A_REASONS:
            violations.append(
                f"CLASS_MISMATCH: reason={reason!r} in Class B but IS a CLASS_A_REASON"
            )

    # --- Trade count vs exit_classes totals ---
    class_total = sum(
        s["count"]
        for cls_dict in exit_classes.values()
        for s in cls_dict.values()
    )
    if class_total != result.trades:
        violations.append(
            f"CLASS_COUNT: exit_classes total={class_total} != result.trades={result.trades}"
        )

    all_ok = len(violations) == 0
    return all_ok, violations


# ---------------------------------------------------------------------------
# 4. Fee Consistency Check
# ---------------------------------------------------------------------------

def verify_fee_consistency(
    trade_list: list[dict],
    fee_per_side: float = EXPECTED_FEE,
    tolerance: float = 0.01,  # 1% tolerance for floating point
) -> tuple[bool, list[str]]:
    """Verify each trade's P&L is consistent with stated fee.

    For each trade:
    - gross = size * (exit/entry - 1)
    - fees = size * fee + (size + gross) * fee
    - net = gross - fees
    - Check: abs(net - trade['pnl']) < tolerance * max(abs(net), 0.01)
    """
    violations: list[str] = []

    for i, t in enumerate(trade_list):
        entry = t.get("entry", 0.0)
        exit_ = t.get("exit", 0.0)
        size = t.get("size", 0.0)
        reported_pnl = t.get("pnl", 0.0)
        pair = t.get("pair", "?")

        if entry <= 0 or size <= 0:
            violations.append(
                f"INVALID_TRADE[{i}]: entry={entry}, size={size} (pair={pair})"
            )
            continue

        gross = size * (exit_ / entry - 1.0)
        fees = size * fee_per_side + (size + gross) * fee_per_side
        expected_net = gross - fees

        # Use absolute tolerance floor to avoid division-by-zero on tiny trades
        abs_tolerance = tolerance * max(abs(expected_net), 0.01)
        delta = abs(expected_net - reported_pnl)

        if delta > abs_tolerance:
            violations.append(
                f"FEE_INCONSISTENT[{i}]: pair={pair} "
                f"expected_net={expected_net:.4f} reported_pnl={reported_pnl:.4f} "
                f"delta={delta:.6f} > tol={abs_tolerance:.6f}"
            )

    all_ok = len(violations) == 0
    return all_ok, violations


# ---------------------------------------------------------------------------
# 5. Sprint 4 Freeze Record
# ---------------------------------------------------------------------------

def create_freeze_record(
    experiment_id: str = "sprint4",
    configs_run: int = 0,
    go_count: int = 0,
    research_leads: int = 0,
    best_pf: float = 0.0,
    notes: str = "",
) -> dict:
    """Create a frozen provenance record for Sprint 4.

    Returns dict with all provenance fields + results summary.
    Can be serialized to JSON for scoreboard.
    """
    git_hash = _get_git_hash()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    provenance = ProvenanceRecord(
        dataset_id=EXPECTED_DATASET_ID,
        universe_id=EXPECTED_UNIVERSE_ID,
        fee_model="kraken_spot_26bps",
        git_hash=git_hash,
        n_coins=EXPECTED_COIN_COUNT,
        n_bars_min=EXPECTED_MIN_BARS,
        timestamp=ts,
        engine_fee=EXPECTED_FEE,
        exit_mode="dc",
    )

    record = {
        "experiment_id": experiment_id,
        "provenance": asdict(provenance),
        "results": {
            "configs_run": configs_run,
            "go_count": go_count,
            "research_leads": research_leads,
            "best_pf": round(best_pf, 4),
        },
        "notes": notes,
    }
    return record


# ---------------------------------------------------------------------------
# 6. Combined Guardrail Check
# ---------------------------------------------------------------------------

def run_all_guardrails(
    data: dict,
    coins: list[str],
    result=None,  # Optional BacktestResult
    trade_list: Optional[list[dict]] = None,
    *,
    fee: float = EXPECTED_FEE,
    initial_capital: float = INITIAL_CAPITAL,
    verbose: bool = True,
) -> tuple[bool, dict[str, Any]]:
    """Run all guardrail checks and return combined report.

    Parameters
    ----------
    data : dict
        Candle data dict.
    coins : list[str]
        Universe coin list.
    result : BacktestResult, optional
        If provided, runs accounting validation.
    trade_list : list[dict], optional
        If provided (or extracted from result), runs fee consistency check.
    """
    report: dict[str, Any] = {}
    all_ok = True

    # 1. Provenance
    prov_ok, prov_violations = verify_provenance(data, coins)
    report["provenance"] = {"ok": prov_ok, "violations": prov_violations}
    if not prov_ok:
        all_ok = False

    # 2. Accounting (if result provided)
    if result is not None:
        acc_ok, acc_violations = validate_accounting(result, initial_capital)
        report["accounting"] = {"ok": acc_ok, "violations": acc_violations}
        if not acc_ok:
            all_ok = False

        # Extract trade_list from result if not provided separately
        if trade_list is None and hasattr(result, "trade_list"):
            trade_list = result.trade_list

    # 3. Fee consistency (if trade_list available)
    if trade_list is not None:
        fee_ok, fee_violations = verify_fee_consistency(trade_list, fee)
        report["fee_consistency"] = {"ok": fee_ok, "violations": fee_violations}
        if not fee_ok:
            all_ok = False

    report["all_ok"] = all_ok

    if verbose:
        _print_guardrail_report(report)

    return all_ok, report


def _print_guardrail_report(report: dict[str, Any]) -> None:
    """Pretty-print guardrail report to stdout."""
    width = 72
    print(f"\n{'=' * width}")
    print("  SPRINT 4 GUARDRAIL REPORT")
    print(f"{'=' * width}")

    for section_name in ("provenance", "accounting", "fee_consistency"):
        section = report.get(section_name)
        if section is None:
            continue
        ok = section["ok"]
        mark = "PASS" if ok else "FAIL"
        violations = section["violations"]
        print(f"  [{mark:4s}] {section_name.upper()}")
        if violations:
            for v in violations:
                print(f"         - {v}")

    overall = "ALL PASS" if report.get("all_ok", False) else "VIOLATIONS FOUND"
    print(f"{'~' * width}")
    print(f"  Overall: {overall}")
    print(f"{'=' * width}\n")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Guardrail self-test ===\n")
    passed = 0
    failed = 0

    def _check(name: str, condition: bool, detail: str = ""):
        global passed, failed
        if condition:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name}: {detail}")
            failed += 1

    # -----------------------------------------------------------------------
    # Test 1: Provenance with valid mock data (487 coins, 400 bars each)
    # -----------------------------------------------------------------------
    print("--- Test 1: Provenance (valid) ---")
    mock_data = {
        f"COIN{i}/USD": [
            {"close": 100, "high": 105, "low": 95, "open": 98, "volume": 1000}
        ] * 400
        for i in range(487)
    }
    mock_coins = list(mock_data.keys())

    ok, violations = verify_provenance(mock_data, mock_coins)
    _check("provenance_valid", ok, f"violations: {violations}")

    # -----------------------------------------------------------------------
    # Test 2: Provenance failure (wrong coin count)
    # -----------------------------------------------------------------------
    print("--- Test 2: Provenance (wrong coin count) ---")
    ok2, v2 = verify_provenance(mock_data, mock_coins[:100])
    _check(
        "provenance_wrong_count",
        not ok2,
        "should fail with 100 coins",
    )
    has_coin_count = any("COIN_COUNT" in v for v in v2)
    _check("provenance_violation_message", has_coin_count, f"violations: {v2}")

    # -----------------------------------------------------------------------
    # Test 3: Provenance failure (short bars)
    # -----------------------------------------------------------------------
    print("--- Test 3: Provenance (short bars) ---")
    short_data = dict(mock_data)
    short_data["SHORT/USD"] = [{"close": 100}] * 50
    short_coins = mock_coins + ["SHORT/USD"]
    # Coin count will also fail (488 != 487), so check for MIN_BARS specifically
    ok3, v3 = verify_provenance(short_data, short_coins)
    _check("provenance_short_bars", not ok3, "should fail")
    has_min_bars = any("MIN_BARS" in v for v in v3)
    _check("provenance_min_bars_violation", has_min_bars, f"violations: {v3}")

    # -----------------------------------------------------------------------
    # Test 4: Accounting validation with known values
    # -----------------------------------------------------------------------
    print("--- Test 4: Accounting validation ---")

    # Build a mock BacktestResult-like object
    class MockResult:
        pass

    mr = MockResult()
    # 2 trades: one win +$50, one loss -$20
    mr.trade_list = [
        {
            "pair": "BTC/USD", "entry": 100.0, "exit": 110.0,
            "pnl": 50.0, "pnl_pct": 2.5, "reason": "DC TARGET",
            "bars": 5, "entry_bar": 50, "exit_bar": 55,
            "size": 1000.0, "equity_after": 2050.0,
        },
        {
            "pair": "ETH/USD", "entry": 200.0, "exit": 190.0,
            "pnl": -20.0, "pnl_pct": -2.0, "reason": "FIXED STOP",
            "bars": 3, "entry_bar": 56, "exit_bar": 59,
            "size": 1000.0, "equity_after": 2030.0,
        },
    ]
    mr.trades = 2
    mr.pnl = 30.0  # 50 - 20
    mr.final_equity = 2030.0  # 2000 + 30
    mr.pf = round(50.0 / 20.0, 4)  # 2.5
    mr.wr = 50.0
    mr.dd = 1.0
    mr.broke = False
    mr.exit_classes = {
        "A": {"DC TARGET": {"count": 1, "pnl": 50.0, "wins": 1}},
        "B": {"FIXED STOP": {"count": 1, "pnl": -20.0, "wins": 0}},
    }

    ok4, v4 = validate_accounting(mr)
    _check("accounting_valid", ok4, f"violations: {v4}")

    # Test accounting with wrong PF
    mr_bad = MockResult()
    mr_bad.trade_list = mr.trade_list
    mr_bad.trades = 2
    mr_bad.pnl = 30.0
    mr_bad.final_equity = 2030.0
    mr_bad.pf = 5.0  # wrong! should be 2.5
    mr_bad.exit_classes = mr.exit_classes

    ok4b, v4b = validate_accounting(mr_bad)
    _check("accounting_bad_pf", not ok4b, "should fail with wrong PF")
    has_pf_mismatch = any("PF_MISMATCH" in v for v in v4b)
    _check("accounting_pf_violation", has_pf_mismatch, f"violations: {v4b}")

    # Test accounting with invalid exit reason
    mr_bad_reason = MockResult()
    mr_bad_reason.trade_list = [
        {
            "pair": "XYZ/USD", "entry": 100.0, "exit": 105.0,
            "pnl": 10.0, "pnl_pct": 1.0, "reason": "MAGIC_EXIT",
            "bars": 2, "entry_bar": 50, "exit_bar": 52,
            "size": 1000.0, "equity_after": 2010.0,
        },
    ]
    mr_bad_reason.trades = 1
    mr_bad_reason.pnl = 10.0
    mr_bad_reason.final_equity = 2010.0
    mr_bad_reason.pf = float("inf")  # only wins
    mr_bad_reason.exit_classes = {"A": {}, "B": {"MAGIC_EXIT": {"count": 1, "pnl": 10.0, "wins": 1}}}

    ok4c, v4c = validate_accounting(mr_bad_reason)
    _check("accounting_bad_reason", not ok4c, "should fail with invalid reason")
    has_invalid_reason = any("INVALID_REASON" in v for v in v4c)
    _check("accounting_reason_violation", has_invalid_reason, f"violations: {v4c}")

    # Test accounting with NaN
    mr_nan = MockResult()
    mr_nan.trade_list = [
        {
            "pair": "NAN/USD", "entry": float("nan"), "exit": 105.0,
            "pnl": 10.0, "pnl_pct": 1.0, "reason": "DC TARGET",
            "bars": 2, "entry_bar": 50, "exit_bar": 52,
            "size": 1000.0, "equity_after": 2010.0,
        },
    ]
    mr_nan.trades = 1
    mr_nan.pnl = 10.0
    mr_nan.final_equity = 2010.0
    mr_nan.pf = float("inf")
    mr_nan.exit_classes = {"A": {"DC TARGET": {"count": 1, "pnl": 10.0, "wins": 1}}, "B": {}}

    ok4d, v4d = validate_accounting(mr_nan)
    _check("accounting_nan", not ok4d, "should fail with NaN entry")
    has_numeric = any("NUMERIC_INVALID" in v for v in v4d)
    _check("accounting_nan_violation", has_numeric, f"violations: {v4d}")

    # -----------------------------------------------------------------------
    # Test 5: Fee consistency check
    # -----------------------------------------------------------------------
    print("--- Test 5: Fee consistency ---")

    fee = 0.0026
    # Construct a trade with correct fee math
    entry = 100.0
    exit_ = 108.0  # +8%
    size = 2000.0
    gross = size * (exit_ / entry - 1.0)       # 160.0
    fees = size * fee + (size + gross) * fee    # 5.20 + 5.616 = 10.816
    net = gross - fees                          # 149.184

    consistent_trade = {
        "pair": "TEST/USD", "entry": entry, "exit": exit_,
        "pnl": net, "size": size,
    }
    ok5, v5 = verify_fee_consistency([consistent_trade], fee)
    _check("fee_consistent", ok5, f"violations: {v5}")

    # Trade with wrong P&L (off by $10)
    bad_trade = dict(consistent_trade)
    bad_trade["pnl"] = net + 10.0
    ok5b, v5b = verify_fee_consistency([bad_trade], fee)
    _check("fee_inconsistent", not ok5b, "should fail with wrong pnl")
    has_fee_violation = any("FEE_INCONSISTENT" in v for v in v5b)
    _check("fee_violation_message", has_fee_violation, f"violations: {v5b}")

    # -----------------------------------------------------------------------
    # Test 6: Freeze record creation
    # -----------------------------------------------------------------------
    print("--- Test 6: Freeze record ---")
    record = create_freeze_record(
        experiment_id="sprint4_test",
        configs_run=18,
        go_count=0,
        best_pf=0.95,
        notes="Self-test freeze record",
    )
    _check("freeze_has_provenance", "provenance" in record)
    _check("freeze_has_results", "results" in record)
    _check(
        "freeze_dataset_id",
        record["provenance"]["dataset_id"] == EXPECTED_DATASET_ID,
    )
    _check("freeze_fee", record["provenance"]["engine_fee"] == EXPECTED_FEE)
    _check("freeze_configs", record["results"]["configs_run"] == 18)
    _check("freeze_serializable", json.dumps(record) is not None)

    # -----------------------------------------------------------------------
    # Test 7: Deterministic replay (with trivial signal_fn)
    # -----------------------------------------------------------------------
    print("--- Test 7: Deterministic replay ---")

    # Build minimal mock data for 5 coins with indicators
    replay_n = 100
    replay_coins = [f"REPLAY{i}/USD" for i in range(5)]
    replay_data: dict[str, list] = {}
    replay_indicators: dict[str, dict] = {}
    for coin in replay_coins:
        closes = [100.0 + (i % 20) - 10 for i in range(replay_n)]
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        volumes = [1000.0] * replay_n
        rsi = [30.0 + (i % 40) for i in range(replay_n)]

        replay_data[coin] = [
            {"close": closes[j], "high": highs[j], "low": lows[j],
             "open": closes[j] - 1, "volume": volumes[j]}
            for j in range(replay_n)
        ]
        replay_indicators[coin] = {
            "closes": closes, "highs": highs, "lows": lows,
            "volumes": volumes, "rsi": rsi,
            "dc_mid": [c + 5 for c in closes],
            "bb_mid": [c + 4 for c in closes],
            "n": replay_n,
        }

    # Simple signal_fn: buy when RSI < 35
    def _test_signal(candles, bar, ind, params):
        rsi_val = ind["rsi"][bar]
        if rsi_val is not None and rsi_val < 35:
            close = ind["closes"][bar]
            return {
                "stop_price": close * 0.90,
                "target_price": close * 1.10,
                "time_limit": 10,
                "strength": 100 - rsi_val,
            }
        return None

    det_ok, det_details = replay_test(
        replay_data, replay_coins, _test_signal, {},
        replay_indicators, exit_mode="dc", n_runs=3,
    )
    _check(
        "replay_deterministic",
        det_ok,
        f"mismatches: {det_details.get('mismatches', [])}",
    )
    _check("replay_n_runs", det_details["n_runs"] == 3)

    # -----------------------------------------------------------------------
    # Test 8: Class A/B mismatch detection
    # -----------------------------------------------------------------------
    print("--- Test 8: Class A/B mismatch ---")
    mr_class_mismatch = MockResult()
    mr_class_mismatch.trade_list = [
        {
            "pair": "BTC/USD", "entry": 100.0, "exit": 110.0,
            "pnl": 50.0, "pnl_pct": 5.0, "reason": "DC TARGET",
            "bars": 5, "entry_bar": 50, "exit_bar": 55,
            "size": 1000.0, "equity_after": 2050.0,
        },
    ]
    mr_class_mismatch.trades = 1
    mr_class_mismatch.pnl = 50.0
    mr_class_mismatch.final_equity = 2050.0
    mr_class_mismatch.pf = float("inf")
    # Intentionally put DC TARGET in class B (wrong!)
    mr_class_mismatch.exit_classes = {
        "A": {},
        "B": {"DC TARGET": {"count": 1, "pnl": 50.0, "wins": 1}},
    }

    ok8, v8 = validate_accounting(mr_class_mismatch)
    _check("class_mismatch_detected", not ok8, "should fail")
    has_class_mismatch = any("CLASS_MISMATCH" in v for v in v8)
    _check("class_mismatch_violation", has_class_mismatch, f"violations: {v8}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("ALL GUARDRAIL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        raise SystemExit(1)
