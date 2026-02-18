"""
Sprint 3 — DualConfirm Exit Intelligence (extracted from agent_team_v3.py).

Implements hybrid_notrl exit mode: fixed stop + smart exits (DC TARGET, RSI RECOVERY, BB TARGET).
No trailing stop — proven to generate Class B losses.

Exit priority (same as agent_team_v3.py hybrid_notrl):
  1. FIXED STOP   — low <= hard_stop
  2. TIME MAX     — bars_in >= time_max_bars
  3. RSI RECOVERY — rsi >= target AND bars_in >= min_bars
  4. DC TARGET    — close >= dc_mid
  5. BB TARGET    — close >= bb_mid
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExitSignal:
    """Result from exit evaluation."""
    price: float
    reason: str
    class_: str  # "A" or "B"


# Class A reasons (smart/profitable exits)
CLASS_A_REASONS = {"RSI RECOVERY", "DC TARGET", "BB TARGET", "PROFIT TARGET"}


def evaluate_exit_hybrid_notrl(
    *,
    entry_price: float,
    entry_bar: int,
    bar: int,
    low: float,
    high: float,
    close: float,
    rsi: Optional[float],
    dc_mid: Optional[float],
    bb_mid: Optional[float],
    max_stop_pct: float = 15.0,
    time_max_bars: int = 15,
    rsi_recovery: bool = True,
    rsi_rec_target: float = 45.0,
    rsi_rec_min_bars: int = 2,
) -> Optional[ExitSignal]:
    """Evaluate hybrid_notrl exit conditions for one position on one bar.

    Returns ExitSignal if exit triggered, None otherwise.
    Exact parity with agent_team_v3.py hybrid_notrl branch.
    """
    bars_in = bar - entry_bar
    hard_stop = entry_price * (1 - max_stop_pct / 100)

    # Priority 1: FIXED STOP — bar low touches/breaches hard stop
    if low <= hard_stop:
        return ExitSignal(price=hard_stop, reason="FIXED STOP", class_="B")

    # Priority 2: TIME MAX
    if bars_in >= time_max_bars:
        return ExitSignal(price=close, reason="TIME MAX", class_="B")

    # Priority 3: RSI RECOVERY — oversold bounce completed
    if rsi_recovery and rsi is not None and bars_in >= rsi_rec_min_bars:
        if rsi >= rsi_rec_target:
            return ExitSignal(price=close, reason="RSI RECOVERY", class_="A")

    # Priority 4: DC TARGET — price reached Donchian midpoint
    if dc_mid is not None and close >= dc_mid:
        return ExitSignal(price=close, reason="DC TARGET", class_="A")

    # Priority 5: BB TARGET — price reached Bollinger midpoint
    if bb_mid is not None and close >= bb_mid:
        return ExitSignal(price=close, reason="BB TARGET", class_="A")

    return None


# Default exit parameters (matching agent_team_v3.py winning config)
DEFAULT_DC_EXIT_PARAMS = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 2,
}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    passed = 0
    failed = 0

    def check(name: str, result: Optional[ExitSignal], expected_reason: Optional[str]):
        global passed, failed
        if expected_reason is None:
            if result is None:
                print(f"  PASS  {name}: no exit (expected)")
                passed += 1
            else:
                print(f"  FAIL  {name}: got {result.reason}, expected None")
                failed += 1
            return
        if result is None:
            print(f"  FAIL  {name}: got None, expected {expected_reason}")
            failed += 1
            return
        if result.reason != expected_reason:
            print(f"  FAIL  {name}: got {result.reason}, expected {expected_reason}")
            failed += 1
            return
        exp_class = "A" if expected_reason in CLASS_A_REASONS else "B"
        if result.class_ != exp_class:
            print(f"  FAIL  {name}: class={result.class_}, expected {exp_class}")
            failed += 1
            return
        print(f"  PASS  {name}: {result.reason} @ {result.price:.2f} (class {result.class_})")
        passed += 1

    print("=== Sprint 3 exits.py self-test ===\n")

    entry = 100.0
    entry_bar = 10

    # --- Test 1: FIXED STOP fires when low breaches hard stop ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=11,
        low=84.0, high=102.0, close=90.0,
        rsi=30.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
    )
    check("FIXED STOP (low=84 < hard_stop=85)", sig, "FIXED STOP")
    # Verify exit price is hard_stop, not close
    assert sig is not None and abs(sig.price - 85.0) < 0.01, \
        f"FIXED STOP price should be 85.0, got {sig.price}"

    # --- Test 2: TIME MAX fires at bars_in == time_max_bars ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=25,
        low=95.0, high=102.0, close=98.0,
        rsi=30.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
    )
    check("TIME MAX (bars_in=15 >= 15)", sig, "TIME MAX")

    # --- Test 3: RSI RECOVERY fires when rsi >= target and bars_in >= min_bars ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=95.0, high=102.0, close=99.0,
        rsi=46.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0, rsi_rec_min_bars=2,
    )
    check("RSI RECOVERY (rsi=46 >= 45, bars_in=3 >= 2)", sig, "RSI RECOVERY")

    # --- Test 4: RSI RECOVERY blocked when bars_in < min_bars ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=11,
        low=95.0, high=102.0, close=99.0,
        rsi=50.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0, rsi_rec_min_bars=2,
    )
    check("RSI RECOVERY blocked (bars_in=1 < 2)", sig, "DC TARGET" if 99.0 >= 105.0 else None)
    # close=99 < dc_mid=105, close=99 < bb_mid=106 → no exit expected
    # Re-check: bars_in=1 blocks RSI, close < dc_mid, close < bb_mid → None
    assert sig is None, "Should be None when RSI blocked and close < dc_mid/bb_mid"

    # --- Test 5: DC TARGET fires when close >= dc_mid ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=95.0, high=108.0, close=106.0,
        rsi=30.0, dc_mid=105.0, bb_mid=110.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0,
    )
    check("DC TARGET (close=106 >= dc_mid=105)", sig, "DC TARGET")

    # --- Test 6: BB TARGET fires when close >= bb_mid (dc_mid=None) ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=95.0, high=108.0, close=106.0,
        rsi=30.0, dc_mid=None, bb_mid=105.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0,
    )
    check("BB TARGET (close=106 >= bb_mid=105, dc_mid=None)", sig, "BB TARGET")

    # --- Test 7: No exit when nothing triggers ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=12,
        low=95.0, high=102.0, close=99.0,
        rsi=30.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0,
    )
    check("No exit (all conditions false)", sig, None)

    # --- Test 8: Priority — FIXED STOP beats RSI RECOVERY ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=80.0, high=102.0, close=99.0,
        rsi=50.0, dc_mid=95.0, bb_mid=95.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0,
    )
    check("Priority: FIXED STOP beats RSI/DC/BB", sig, "FIXED STOP")

    # --- Test 9: RSI None skips RSI RECOVERY, falls through to DC TARGET ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=95.0, high=108.0, close=106.0,
        rsi=None, dc_mid=105.0, bb_mid=110.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=True, rsi_rec_target=45.0,
    )
    check("RSI=None skips RSI RECOVERY -> DC TARGET", sig, "DC TARGET")

    # --- Test 10: rsi_recovery=False skips RSI RECOVERY ---
    sig = evaluate_exit_hybrid_notrl(
        entry_price=entry, entry_bar=entry_bar, bar=13,
        low=95.0, high=102.0, close=99.0,
        rsi=50.0, dc_mid=105.0, bb_mid=106.0,
        max_stop_pct=15.0, time_max_bars=15,
        rsi_recovery=False, rsi_rec_target=45.0,
    )
    check("rsi_recovery=False -> no exit (close < dc/bb)", sig, None)

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        raise SystemExit(1)
