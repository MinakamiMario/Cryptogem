#!/usr/bin/env python3
"""
HF Alignment Tests — No-leak verification + MTF mapping tests.

Verifies causal correctness of indicators, signals, and walk-forward isolation.
Tests run on 4H data (always available), and optionally on 1H/15m when cached.

Tests:
  1. Indicator causality: precompute_all(end_bar=N) at bar K identical regardless of N
  2. Signal determinism: check_entry_at_bar() same result with 200 or 721 bars
  3. Walk-forward isolation: backtest on fold identical with truncated vs full indicators
  4. Cooldown semantics: log wall-clock interpretation at each TF
  5. Window scaling sanity: verify scaled fold/window sizes produce sensible day counts
  6. MTF data alignment: run tests 1-3 on 1H/15m data (when available)
  7. MTF mapping test: verify last_closed_4h_bar mapping (no look-ahead)

Usage:
    python strategies/hf/hf_alignment_tests.py
    python strategies/hf/hf_alignment_tests.py --include-mtf

Outputs:
    reports/hf/alignment_tests_001.json
    reports/hf/alignment_tests_001.md
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# --- Path setup ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg, check_entry_at_bar,
    CACHE_FILE, START_BAR, COOLDOWN_BARS, COOLDOWN_AFTER_STOP, INITIAL_CAPITAL,
)

DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

# Reference configs
GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
    "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12,
    "vol_confirm": True, "vol_spike_mult": 2.5,
})

CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
    "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12,
    "vol_confirm": True, "vol_spike_mult": 3.0,
})


# ---------------------------------------------------------------------------
# Test harness (same pattern as test_param_sensitivity.py)
# ---------------------------------------------------------------------------

passed = 0
failed = 0
results = []


def test(name, condition, detail=""):
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}: {detail}")
    results.append({"name": name, "status": status, "detail": detail})


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_cache(path: Path) -> tuple:
    """Load candle cache. Returns (data, coins) or (None, None) if missing."""
    if not path.exists():
        return None, None
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins


def pick_test_coins(coins: list, data: dict, min_bars: int = 200, n: int = 5) -> list:
    """Pick N coins with sufficient bars for testing."""
    candidates = []
    for c in coins:
        if c in data and len(data[c]) >= min_bars:
            candidates.append(c)
        if len(candidates) >= n:
            break
    return candidates


# ---------------------------------------------------------------------------
# Test 1: Indicator causality
# ---------------------------------------------------------------------------

def test_indicator_causality(data: dict, coins: list, label: str = "4H"):
    """precompute_all(end_bar=N) at bar K identical regardless of N."""
    print(f"\n{'='*70}")
    print(f"TEST 1 ({label}): Indicator causality — precompute_all end_bar independence")
    print(f"{'='*70}")

    test_coins = pick_test_coins(coins, data, min_bars=200, n=5)
    if not test_coins:
        test(f"{label}: indicator_causality — skip (no coins with ≥200 bars)", True, "skipped")
        return

    # Compute with end_bar=150 and end_bar=300
    ind_150 = precompute_all(data, test_coins, end_bar=150)
    ind_300 = precompute_all(data, test_coins, end_bar=300)

    for coin in test_coins:
        if coin not in ind_150 or coin not in ind_300:
            continue
        # Check bars 50..149 — must be identical
        match = True
        mismatch_detail = ""
        for bar in range(START_BAR, 150):
            for key in ["rsi", "atr", "dc_prev_low", "bb_lower", "vol_avg"]:
                v1 = ind_150[coin][key][bar]
                v2 = ind_300[coin][key][bar]
                if v1 is None and v2 is None:
                    continue
                if v1 is None or v2 is None:
                    match = False
                    mismatch_detail = f"bar={bar} key={key}: {v1} vs {v2}"
                    break
                if abs(v1 - v2) > 1e-10:
                    match = False
                    mismatch_detail = f"bar={bar} key={key}: {v1} vs {v2}"
                    break
            if not match:
                break

        test(f"{label}: {coin} indicators bar 50-149 identical (end_bar=150 vs 300)",
             match, mismatch_detail)


# ---------------------------------------------------------------------------
# Test 2: Signal determinism
# ---------------------------------------------------------------------------

def test_signal_determinism(data: dict, coins: list, label: str = "4H"):
    """check_entry_at_bar() same result with truncated vs full data."""
    print(f"\n{'='*70}")
    print(f"TEST 2 ({label}): Signal determinism — check_entry_at_bar consistency")
    print(f"{'='*70}")

    test_coins = pick_test_coins(coins, data, min_bars=300, n=5)
    if not test_coins:
        test(f"{label}: signal_determinism — skip (no coins with ≥300 bars)", True, "skipped")
        return

    ind_200 = precompute_all(data, test_coins, end_bar=200)
    ind_full = precompute_all(data, test_coins)

    for coin in test_coins:
        if coin not in ind_200 or coin not in ind_full:
            continue

        mismatch_count = 0
        total_checked = 0
        for bar in range(START_BAR, min(200, ind_200[coin]["n"])):
            sig_200, vol_200 = check_entry_at_bar(ind_200[coin], bar, GRID_BEST)
            sig_full, vol_full = check_entry_at_bar(ind_full[coin], bar, GRID_BEST)
            total_checked += 1
            if sig_200 != sig_full:
                mismatch_count += 1

        test(f"{label}: {coin} signals identical bar 50-199 (end_bar=200 vs full) [{total_checked} bars]",
             mismatch_count == 0,
             f"{mismatch_count}/{total_checked} mismatches")


# ---------------------------------------------------------------------------
# Test 3: Walk-forward isolation
# ---------------------------------------------------------------------------

def test_wf_isolation(data: dict, coins: list, label: str = "4H"):
    """Backtest on fold [100,200] identical with end_bar=200 vs end_bar=721."""
    print(f"\n{'='*70}")
    print(f"TEST 3 ({label}): Walk-forward isolation — fold result independence")
    print(f"{'='*70}")

    test_coins = pick_test_coins(coins, data, min_bars=300, n=10)
    if not test_coins:
        test(f"{label}: wf_isolation — skip (no coins with ≥300 bars)", True, "skipped")
        return

    ind_200 = precompute_all(data, test_coins, end_bar=200)
    ind_full = precompute_all(data, test_coins)

    bt_200 = run_backtest(ind_200, test_coins, GRID_BEST, start_bar=100, end_bar=200)
    bt_full = run_backtest(ind_full, test_coins, GRID_BEST, start_bar=100, end_bar=200)

    test(f"{label}: WF fold [100,200] trades identical (end_bar=200 vs full)",
         bt_200["trades"] == bt_full["trades"],
         f"trades: {bt_200['trades']} vs {bt_full['trades']}")

    test(f"{label}: WF fold [100,200] PnL identical (end_bar=200 vs full)",
         abs(bt_200["pnl"] - bt_full["pnl"]) < 0.01,
         f"pnl: {bt_200['pnl']:.2f} vs {bt_full['pnl']:.2f}")


# ---------------------------------------------------------------------------
# Test 4: Cooldown semantics documentation
# ---------------------------------------------------------------------------

def test_cooldown_semantics():
    """Document wall-clock interpretation of cooldown at each TF."""
    print(f"\n{'='*70}")
    print(f"TEST 4: Cooldown semantics — wall-clock documentation")
    print(f"{'='*70}")

    tf_hours = {"4h": 4, "1h": 1, "15m": 0.25}
    for tf, hours_per_bar in tf_hours.items():
        cd_hours = COOLDOWN_BARS * hours_per_bar
        cd_stop_hours = COOLDOWN_AFTER_STOP * hours_per_bar
        print(f"  {tf}: COOLDOWN_BARS={COOLDOWN_BARS} = {cd_hours}h, "
              f"COOLDOWN_AFTER_STOP={COOLDOWN_AFTER_STOP} = {cd_stop_hours}h")

    # Verify constants are what we expect (engine read-only)
    test("COOLDOWN_BARS == 4 (engine constant)", COOLDOWN_BARS == 4,
         f"got {COOLDOWN_BARS}")
    test("COOLDOWN_AFTER_STOP == 8 (engine constant)", COOLDOWN_AFTER_STOP == 8,
         f"got {COOLDOWN_AFTER_STOP}")


# ---------------------------------------------------------------------------
# Test 5: Window scaling sanity
# ---------------------------------------------------------------------------

def test_window_scaling_sanity():
    """Verify scaled fold/window sizes produce sensible day counts."""
    print(f"\n{'='*70}")
    print(f"TEST 5: Window scaling sanity — fold sizes in wall-clock days")
    print(f"{'='*70}")

    # Timeframe-scaled parameters from GATES_MTF plan
    tf_params = {
        "4h": {"rolling_window": 180, "wf_embargo": 2, "start_bar": 50, "bars_per_day": 6},
        "1h": {"rolling_window": 720, "wf_embargo": 2, "start_bar": 50, "bars_per_day": 24},
        "15m": {"rolling_window": 2880, "wf_embargo": 8, "start_bar": 200, "bars_per_day": 96},
    }

    for tf, params in tf_params.items():
        days = params["rolling_window"] / params["bars_per_day"]
        embargo_hours = params["wf_embargo"] * (24 / params["bars_per_day"])

        test(f"{tf}: rolling_window={params['rolling_window']} bars = {days:.0f} days (expect ~30)",
             25 <= days <= 35, f"got {days:.1f} days")

        test(f"{tf}: wf_embargo={params['wf_embargo']} bars = {embargo_hours:.1f}h",
             0.5 <= embargo_hours <= 12, f"got {embargo_hours:.1f}h")

    # Fold size sanity: (n_bars - start_bar) / 5
    for tf, params in tf_params.items():
        # Simulate with expected bar count
        expected_bars = {"4h": 720, "1h": 2880, "15m": 11520}[tf]
        fold_size = (expected_bars - params["start_bar"]) // 5
        fold_days = fold_size / params["bars_per_day"]

        test(f"{tf}: fold_size={fold_size} bars = {fold_days:.0f} days (expect 20-30)",
             15 <= fold_days <= 35, f"got {fold_days:.1f} days")


# ---------------------------------------------------------------------------
# Test 6: MTF data alignment (1H/15m when available)
# ---------------------------------------------------------------------------

def test_mtf_data_alignment(tf: str):
    """Run indicator causality + signal determinism + WF isolation on 1H/15m data."""
    cache_files = {
        "1h": DATA_DIR / "candle_cache_1h.json",
        "15m": DATA_DIR / "candle_cache_15m.json",
    }
    path = cache_files.get(tf)
    if path is None or not path.exists():
        print(f"\n  [SKIP] {tf} cache not available at {path}")
        test(f"{tf}: MTF alignment — skip (no data)", True, "skipped")
        return

    data, coins = load_cache(path)
    if not coins:
        test(f"{tf}: MTF alignment — skip (empty cache)", True, "skipped")
        return

    label = tf.upper()
    min_bars = 200 if tf == "1h" else 800

    test_indicator_causality(data, coins, label=label)
    test_signal_determinism(data, coins, label=label)
    test_wf_isolation(data, coins, label=label)


# ---------------------------------------------------------------------------
# Test 7: MTF mapping — last_closed_4h_bar
# ---------------------------------------------------------------------------

def last_closed_4h_bar(bar_1h: int) -> int:
    """
    Map a 1H bar index to the last fully closed 4H bar index.
    At 1H: 4 bars = 1 4H bar. Bar 0-3 → 4H bar 0, bar 4-7 → 4H bar 1, etc.
    The LAST CLOSED 4H bar at 1H bar K is: (K // 4) - 1 (if K % 4 == 0, the bar
    just closed; else we're mid-bar).

    Actually simpler: at 1H bar K, the last fully closed 4H bar ended at
    bar (K // 4) * 4 - 1. The 4H bar index is (K // 4) - 1 if K%4 == 0,
    else K // 4 - 1... No.

    Simplest correct mapping:
    - 4H bar N closes at 1H bar (N+1)*4 - 1.
    - At 1H bar K, last closed 4H bar is N where (N+1)*4 - 1 <= K, i.e. N <= (K+1)/4 - 1 = (K-3)/4.
    - N = (K - 3) // 4 when K >= 3, else -1 (no closed bar yet).
    """
    if bar_1h < 3:
        return -1  # No complete 4H bar yet
    return (bar_1h - 3) // 4


def last_closed_4h_bar_from_15m(bar_15m: int) -> int:
    """Map 15m bar to last fully closed 4H bar. 16 bars of 15m = 1 bar of 4H."""
    if bar_15m < 15:
        return -1
    return (bar_15m - 15) // 16


def test_mtf_mapping():
    """Verify last_closed_4h_bar mapping prevents look-ahead."""
    print(f"\n{'='*70}")
    print(f"TEST 7: MTF mapping — last_closed_4h_bar correctness")
    print(f"{'='*70}")

    # 1H → 4H mapping
    # 4H bar 0 covers 1H bars 0,1,2,3 (closes at end of bar 3)
    # At 1H bar 2: no complete 4H bar → -1
    # At 1H bar 3: 4H bar 0 just closed → last_closed = 0
    # At 1H bar 4: still only 4H bar 0 closed (bar 1 not done) → 0
    # At 1H bar 7: 4H bar 1 just closed → 1

    test("1H bar 0 → no closed 4H bar",
         last_closed_4h_bar(0) == -1, f"got {last_closed_4h_bar(0)}")
    test("1H bar 2 → no closed 4H bar",
         last_closed_4h_bar(2) == -1, f"got {last_closed_4h_bar(2)}")
    test("1H bar 3 → 4H bar 0 closed",
         last_closed_4h_bar(3) == 0, f"got {last_closed_4h_bar(3)}")
    test("1H bar 4 → 4H bar 0 still last closed",
         last_closed_4h_bar(4) == 0, f"got {last_closed_4h_bar(4)}")
    test("1H bar 7 → 4H bar 1 closed",
         last_closed_4h_bar(7) == 1, f"got {last_closed_4h_bar(7)}")
    test("1H bar 11 → 4H bar 2 closed",
         last_closed_4h_bar(11) == 2, f"got {last_closed_4h_bar(11)}")
    test("1H bar 100 → 4H bar 24 closed",
         last_closed_4h_bar(100) == 24, f"got {last_closed_4h_bar(100)}")

    # 15m → 4H mapping
    test("15m bar 0 → no closed 4H bar",
         last_closed_4h_bar_from_15m(0) == -1, f"got {last_closed_4h_bar_from_15m(0)}")
    test("15m bar 15 → 4H bar 0 closed",
         last_closed_4h_bar_from_15m(15) == 0, f"got {last_closed_4h_bar_from_15m(15)}")
    test("15m bar 31 → 4H bar 1 closed",
         last_closed_4h_bar_from_15m(31) == 1, f"got {last_closed_4h_bar_from_15m(31)}")

    # Monotonicity: mapping should be non-decreasing
    prev = -1
    monotonic = True
    for bar_1h in range(0, 500):
        cur = last_closed_4h_bar(bar_1h)
        if cur < prev:
            monotonic = False
            break
        prev = cur
    test("1H→4H mapping is monotonically non-decreasing (500 bars)", monotonic)

    # No look-ahead: at 1H bar K, closed 4H bar N means 4H bar N closed
    # BEFORE or AT 1H bar K. I.e., (N+1)*4 - 1 <= K.
    no_lookahead = True
    detail = ""
    for bar_1h in range(0, 500):
        n = last_closed_4h_bar(bar_1h)
        if n < 0:
            continue
        close_bar = (n + 1) * 4 - 1
        if close_bar > bar_1h:
            no_lookahead = False
            detail = f"bar_1h={bar_1h} maps to 4H bar {n} which closes at 1H bar {close_bar}"
            break
    test("1H→4H mapping has no look-ahead (500 bars)", no_lookahead, detail)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HF Alignment/No-Leak Tests")
    parser.add_argument("--include-mtf", action="store_true",
                        help="Also run tests on 1H/15m data (if available)")
    args = parser.parse_args()

    print("=== HF Alignment Tests ===")
    print(f"  Label: No-leak verification + MTF mapping")
    print()

    # Load 4H data (always available)
    print("Loading 4H dataset...")
    data_4h, coins_4h = load_cache(CACHE_FILE)
    if data_4h is None:
        print(f"ERROR: 4H cache not found at {CACHE_FILE}")
        sys.exit(1)
    print(f"  Loaded {len(coins_4h)} coins")

    # Run tests 1-3 on 4H
    test_indicator_causality(data_4h, coins_4h, label="4H")
    test_signal_determinism(data_4h, coins_4h, label="4H")
    test_wf_isolation(data_4h, coins_4h, label="4H")

    # Test 4: Cooldown semantics
    test_cooldown_semantics()

    # Test 5: Window scaling sanity
    test_window_scaling_sanity()

    # Test 6: MTF data alignment (optional)
    if args.include_mtf:
        print("\n--- Running MTF alignment tests ---")
        test_mtf_data_alignment("1h")
        test_mtf_data_alignment("15m")
    else:
        print("\n  [INFO] Skipping MTF alignment tests (use --include-mtf to enable)")

    # Test 7: MTF mapping (always runs, pure logic)
    test_mtf_mapping()

    # Write reports
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "label": "HF alignment / no-leak tests",
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "include_mtf": args.include_mtf,
        "tests": results,
    }

    json_path = REPORTS_DIR / "alignment_tests_001.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Wrote {json_path}")

    md_lines = [
        "# HF Alignment Tests — No-Leak Verification",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Passed**: {passed}",
        f"**Failed**: {failed}",
        f"**Total**: {passed + failed}",
        f"**MTF included**: {args.include_mtf}",
        "",
        "## Results",
        "",
        "| # | Test | Status | Detail |",
        "|---|------|--------|--------|",
    ]
    for i, r in enumerate(results, 1):
        status_icon = "✅" if r["status"] == "PASS" else "❌"
        detail = r["detail"][:80] if r["detail"] else ""
        md_lines.append(f"| {i} | {r['name']} | {status_icon} | {detail} |")

    md_lines.extend([
        "",
        "## Cooldown Wall-Clock Semantics",
        "",
        "| TF | COOLDOWN_BARS | Wall-Clock | COOLDOWN_AFTER_STOP | Wall-Clock |",
        "|----|--------------|------------|--------------------|-----------|\n",
    ])
    for tf, hpb in [("4H", 4), ("1H", 1), ("15m", 0.25)]:
        md_lines.append(
            f"| {tf} | {COOLDOWN_BARS} | {COOLDOWN_BARS * hpb}h "
            f"| {COOLDOWN_AFTER_STOP} | {COOLDOWN_AFTER_STOP * hpb}h |"
        )

    md_lines.extend(["", "---",
        f"*Generated by `hf_alignment_tests.py` at {datetime.now().strftime('%Y-%m-%d %H:%M')}*"])

    md_path = REPORTS_DIR / "alignment_tests_001.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  Wrote {md_path}")

    # Final summary
    print(f"\n{'='*70}")
    print(f"ALIGNMENT TESTS: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*70}")

    if failed > 0:
        print("\n⚠️  FAILURES DETECTED — investigate before proceeding")
        sys.exit(1)
    else:
        print("\n✅ All alignment tests passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
