#!/usr/bin/env python3
"""
Subagent C: Regime Decomposition & Anti-Double-Count Proof

Verifies:
1. Component sum == total_per_side_bps for all 6 regimes x 2 tiers
2. No double-counting of spread (taker gets half-spread, not full)
3. Maker regime correctness (no fee, no spread, no slippage, only adverse_selection)
4. register_regime() accepts valid regimes and rejects bad ones
5. Comparison with v2 Kaiko baseline

Outputs:
- JSON decomposition to reports/hf/regime_decomposition_001.json
- Summary table to stdout
"""

import json
import os
import sys

sys.path.insert(0, "/Users/oussama/Cryptogem")

from strategies.hf.screening.orderbook_analysis import (
    load_snapshots,
    compute_distributions,
    build_measured_regimes,
)
from strategies.hf.screening.costs_mexc_v2 import (
    register_regime,
    COST_REGIMES,
    _COMPONENT_KEYS,
)


def main():
    # ---------------------------------------------------------------
    # Step 1: Load data and build regimes
    # ---------------------------------------------------------------
    print("=" * 80)
    print("STEP 1: Load data and build regimes")
    print("=" * 80)

    snapshots = load_snapshots(
        "/Users/oussama/Cryptogem/data/orderbook_snapshots/mexc_orderbook_001.jsonl"
    )
    distributions = compute_distributions(snapshots)
    regimes = build_measured_regimes(distributions)

    print(f"  Regimes built: {len(regimes)}")
    for name in sorted(regimes):
        print(f"    - {name}")

    # ---------------------------------------------------------------
    # Step 2: Dump regime components
    # ---------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 2: Regime component decomposition")
    print("=" * 80)

    decomposition = {}
    all_ok = True

    for name in sorted(regimes):
        regime = regimes[name]
        entry = {
            "regime_name": name,
            "execution_mode": regime["execution_mode"],
            "percentile": regime["percentile"],
        }

        for tier_key in ("tier1", "tier2"):
            t = regime[tier_key]
            fee = t.get("exchange_fee_bps", 0.0)
            spread = t.get("spread_bps", 0.0)
            slippage = t.get("slippage_bps", 0.0)
            adverse = t.get("adverse_selection_bps", 0.0)
            total = t["total_per_side_bps"]
            component_sum = round(fee + spread + slippage + adverse, 2)
            matches = abs(component_sum - total) < 0.15

            entry[tier_key] = {
                "exchange_fee_bps": fee,
                "spread_bps": spread,
                "slippage_bps": slippage,
                "adverse_selection_bps": adverse,
                "total_per_side_bps": total,
                "component_sum": component_sum,
                "sum_matches_total": matches,
                "delta": round(abs(component_sum - total), 3),
            }

            status = "PASS" if matches else "FAIL"
            if not matches:
                all_ok = False
            print(
                f"  {name}/{tier_key}: sum={component_sum:.2f} total={total:.1f} "
                f"delta={abs(component_sum - total):.3f} [{status}]"
            )

        decomposition[name] = entry

    print(f"\n  Component sum check: {'ALL PASS' if all_ok else 'FAILURES DETECTED'}")

    # ---------------------------------------------------------------
    # Step 3: Anti-double-count verification
    # ---------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 3: Anti-double-count verification")
    print("=" * 80)

    verification_results = {}
    taker_ok = True
    maker_ok = True

    for name in sorted(regimes):
        regime = regimes[name]
        mode = regime["execution_mode"]
        pct_key = regime["percentile"]
        checks = {}

        if mode == "taker_market":
            print(f"\n  TAKER regime: {name}")
            for tier_key in ("tier1", "tier2"):
                tier_dist = distributions.get(tier_key, {})
                raw_spread = tier_dist.get("spread_bps", {}).get(pct_key, 0.0)
                raw_slippage_200 = tier_dist.get("slippage_200_bps", {}).get(pct_key, 0.0)

                regime_spread = regime[tier_key]["spread_bps"]
                regime_slippage = regime[tier_key]["slippage_bps"]

                # Spread check: regime spread == raw_spread / 2 (half-spread per side)
                expected_half_spread = round(raw_spread / 2.0, 1)
                spread_ok = abs(regime_spread - expected_half_spread) < 0.15
                if not spread_ok:
                    taker_ok = False

                # Slippage check: regime slippage == raw slippage_200_bps (NOT doubled)
                expected_slippage = round(raw_slippage_200, 1)
                slippage_ok = abs(regime_slippage - expected_slippage) < 0.15
                if not slippage_ok:
                    taker_ok = False

                checks[tier_key] = {
                    "raw_spread_bps": raw_spread,
                    "expected_half_spread": expected_half_spread,
                    "regime_spread_bps": regime_spread,
                    "spread_is_half": spread_ok,
                    "raw_slippage_200_bps": raw_slippage_200,
                    "expected_slippage": expected_slippage,
                    "regime_slippage_bps": regime_slippage,
                    "slippage_not_doubled": slippage_ok,
                }

                print(
                    f"    {tier_key}: raw_spread={raw_spread:.2f} -> half={expected_half_spread:.1f} "
                    f"vs regime={regime_spread:.1f} [{'PASS' if spread_ok else 'FAIL'}]"
                )
                print(
                    f"    {tier_key}: raw_slip200={raw_slippage_200:.2f} "
                    f"vs regime={regime_slippage:.1f} [{'PASS' if slippage_ok else 'FAIL'}]"
                )

        elif mode == "maker_limit":
            print(f"\n  MAKER regime: {name}")
            for tier_key in ("tier1", "tier2"):
                t = regime[tier_key]
                tier_dist = distributions.get(tier_key, {})
                raw_spread = tier_dist.get("spread_bps", {}).get(pct_key, 0.0)

                fee_ok = t["exchange_fee_bps"] == 0.0
                spread_ok = t["spread_bps"] == 0.0
                slippage_ok = t["slippage_bps"] == 0.0

                # Adverse selection ~ spread_median * 0.3
                expected_adverse = round(raw_spread * 0.3, 1)
                adverse_ok = abs(t.get("adverse_selection_bps", 0.0) - expected_adverse) < 0.15

                if not (fee_ok and spread_ok and slippage_ok and adverse_ok):
                    maker_ok = False

                checks[tier_key] = {
                    "exchange_fee_is_zero": fee_ok,
                    "spread_is_zero": spread_ok,
                    "slippage_is_zero": slippage_ok,
                    "raw_spread_bps": raw_spread,
                    "expected_adverse_selection": expected_adverse,
                    "actual_adverse_selection": t.get("adverse_selection_bps", 0.0),
                    "adverse_selection_correct": adverse_ok,
                }

                print(
                    f"    {tier_key}: fee=0 [{_yesno(fee_ok)}] spread=0 [{_yesno(spread_ok)}] "
                    f"slip=0 [{_yesno(slippage_ok)}]"
                )
                print(
                    f"    {tier_key}: adverse_sel={t.get('adverse_selection_bps', 0.0):.1f} "
                    f"expected={expected_adverse:.1f} (spread={raw_spread:.2f}*0.3) "
                    f"[{_yesno(adverse_ok)}]"
                )

        verification_results[name] = checks

    print(f"\n  Taker double-count check: {'ALL PASS' if taker_ok else 'FAILURES DETECTED'}")
    print(f"  Maker structure check:    {'ALL PASS' if maker_ok else 'FAILURES DETECTED'}")

    # ---------------------------------------------------------------
    # Step 4: register_regime() assertion test
    # ---------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 4: register_regime() assertion tests")
    print("=" * 80)

    # Test 1: All valid regimes should register
    register_ok = True
    for name, regime in regimes.items():
        try:
            register_regime(name, regime)
            print(f"  OK: {name} registered successfully")
        except (AssertionError, Exception) as e:
            print(f"  FAIL: {name} threw {type(e).__name__}: {e}")
            register_ok = False

    # Test 2: Bad regime should throw AssertionError
    bad_regime = {
        "execution_mode": "maker_limit",
        "tier1": {
            "exchange_fee_bps": 0,
            "spread_bps": 0,
            "slippage_bps": 0,
            "adverse_selection_bps": 5.0,
            "total_per_side_bps": 999.0,  # WRONG total
        },
        "tier2": {
            "exchange_fee_bps": 0,
            "spread_bps": 0,
            "slippage_bps": 0,
            "adverse_selection_bps": 5.0,
            "total_per_side_bps": 5.0,
        },
    }
    bad_test_ok = False
    try:
        register_regime("bad_test", bad_regime)
        print("  FAIL: should have thrown AssertionError for bad_test")
    except AssertionError as e:
        print(f"  OK: AssertionError caught for bad_test: {e}")
        bad_test_ok = True
    except Exception as e:
        print(f"  FAIL: unexpected {type(e).__name__}: {e}")

    # Test 3: Missing execution_mode should throw
    missing_mode_ok = False
    try:
        register_regime("no_mode", {"tier1": {}, "tier2": {}})
        print("  FAIL: should have thrown for missing execution_mode")
    except AssertionError as e:
        print(f"  OK: AssertionError caught for missing execution_mode: {e}")
        missing_mode_ok = True

    # Test 4: Missing tier should throw
    missing_tier_ok = False
    try:
        register_regime("no_tier", {"execution_mode": "taker_market", "tier1": {"total_per_side_bps": 10}})
        print("  FAIL: should have thrown for missing tier2")
    except AssertionError as e:
        print(f"  OK: AssertionError caught for missing tier2: {e}")
        missing_tier_ok = True

    print(f"\n  Valid regime registration: {'PASS' if register_ok else 'FAIL'}")
    print(f"  Bad total rejection:      {'PASS' if bad_test_ok else 'FAIL'}")
    print(f"  Missing mode rejection:   {'PASS' if missing_mode_ok else 'FAIL'}")
    print(f"  Missing tier rejection:   {'PASS' if missing_tier_ok else 'FAIL'}")

    # Clean up bad_test if it leaked into COST_REGIMES
    COST_REGIMES.pop("bad_test", None)
    COST_REGIMES.pop("no_mode", None)
    COST_REGIMES.pop("no_tier", None)

    # ---------------------------------------------------------------
    # Step 5: v2 Kaiko comparison
    # ---------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 5: v2 Kaiko baseline comparison (taker P50)")
    print("=" * 80)

    v2_kaiko = COST_REGIMES.get("mexc_market", {})
    measured_taker_p50 = regimes.get("measured_ob_taker_p50", {})

    kaiko_comparison = {}
    for tier_key in ("tier1", "tier2"):
        v2_t = v2_kaiko.get(tier_key, {})
        m_t = measured_taker_p50.get(tier_key, {})

        v2_total = v2_t.get("total_per_side_bps", 0)
        m_total = m_t.get("total_per_side_bps", 0)
        delta = round(m_total - v2_total, 1)
        pct_change = round(delta / v2_total * 100, 1) if v2_total else 0

        kaiko_comparison[tier_key] = {
            "v2_kaiko_total_bps": v2_total,
            "measured_total_bps": m_total,
            "delta_bps": delta,
            "pct_change": pct_change,
            "v2_fee": v2_t.get("exchange_fee_bps", 0),
            "v2_spread": v2_t.get("spread_bps", 0),
            "v2_slippage": v2_t.get("slippage_bps", 0),
            "measured_fee": m_t.get("exchange_fee_bps", 0),
            "measured_spread": m_t.get("spread_bps", 0),
            "measured_slippage": m_t.get("slippage_bps", 0),
        }

        print(f"\n  {tier_key}:")
        print(f"    v2 Kaiko:  fee={v2_t.get('exchange_fee_bps', 0):.1f} "
              f"spread={v2_t.get('spread_bps', 0):.1f} "
              f"slip={v2_t.get('slippage_bps', 0):.1f} "
              f"total={v2_total:.1f} bps/side")
        print(f"    Measured:  fee={m_t.get('exchange_fee_bps', 0):.1f} "
              f"spread={m_t.get('spread_bps', 0):.1f} "
              f"slip={m_t.get('slippage_bps', 0):.1f} "
              f"total={m_total:.1f} bps/side")
        print(f"    Delta:     {delta:+.1f} bps ({pct_change:+.1f}%)")

    # ---------------------------------------------------------------
    # Summary table
    # ---------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SUMMARY TABLE: All 6 regimes x 2 tiers")
    print("=" * 80)

    header = (
        f"{'Regime':<35s} | {'Mode':<13s} | {'Tier':>4s} | "
        f"{'Fee':>5s} | {'Spread':>6s} | {'Slip':>5s} | {'AdvSel':>6s} | "
        f"{'Total':>6s} | {'Sum':>6s} | {'OK':>4s}"
    )
    print(header)
    print("-" * len(header))

    for name in sorted(regimes):
        regime = regimes[name]
        for tier_key in ("tier1", "tier2"):
            t = regime[tier_key]
            fee = t.get("exchange_fee_bps", 0.0)
            spread = t.get("spread_bps", 0.0)
            slippage = t.get("slippage_bps", 0.0)
            adverse = t.get("adverse_selection_bps", 0.0)
            total = t["total_per_side_bps"]
            csum = round(fee + spread + slippage + adverse, 2)
            ok = "PASS" if abs(csum - total) < 0.15 else "FAIL"

            print(
                f"{name:<35s} | {regime['execution_mode']:<13s} | {tier_key:>4s} | "
                f"{fee:5.1f} | {spread:6.1f} | {slippage:5.1f} | {adverse:6.1f} | "
                f"{total:6.1f} | {csum:6.1f} | {ok:>4s}"
            )

    # ---------------------------------------------------------------
    # Write JSON report
    # ---------------------------------------------------------------
    output_path = "/Users/oussama/Cryptogem/reports/hf/regime_decomposition_001.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    report = {
        "meta": {
            "description": "Regime decomposition & anti-double-count verification",
            "snapshot_count": len(snapshots),
            "regimes_tested": len(regimes),
        },
        "decomposition": decomposition,
        "anti_double_count": verification_results,
        "kaiko_comparison": kaiko_comparison,
        "verdicts": {
            "component_sum_check": "PASS" if all_ok else "FAIL",
            "taker_no_double_count": "PASS" if taker_ok else "FAIL",
            "maker_structure_correct": "PASS" if maker_ok else "FAIL",
            "register_valid_regimes": "PASS" if register_ok else "FAIL",
            "reject_bad_regime": "PASS" if bad_test_ok else "FAIL",
            "reject_missing_mode": "PASS" if missing_mode_ok else "FAIL",
            "reject_missing_tier": "PASS" if missing_tier_ok else "FAIL",
        },
        "overall_verdict": "PASS"
        if all([all_ok, taker_ok, maker_ok, register_ok, bad_test_ok, missing_mode_ok, missing_tier_ok])
        else "FAIL",
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  JSON report written to: {output_path}")

    # Final verdict
    overall = report["overall_verdict"]
    print(f"\n{'=' * 80}")
    print(f"OVERALL VERDICT: {overall}")
    print(f"{'=' * 80}")

    return 0 if overall == "PASS" else 1


def _yesno(b: bool) -> str:
    return "PASS" if b else "FAIL"


if __name__ == "__main__":
    sys.exit(main())
