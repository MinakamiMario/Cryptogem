"""
SuperHF Sprint 1 — 12 Signal Configs (2 families × 6 variants).

Family A: Pivot Reclaim
  1H support = confirmed pivot low (fractal, no lookahead).
  15m entry = low touches/goes under support + close reclaims above support.

Family B: Sweep + Reclaim + Volume
  15m wick below 1H support + close back above + volume spike.

Signal protocol:
    signal_fn(candles, bar, indicators_15m, params, support_zone) -> dict | None
    Return: {'strength': float} or None

Exits are handled by harness.py (hybrid_notrl: FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Hypothesis dataclass
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str           # SHF-A01, SHF-B01, ...
    name: str
    family: str       # "pivot_reclaim" or "sweep_reclaim"
    signal_fn: Callable
    params: dict
    description: str


REGISTRY: dict[str, Hypothesis] = {}


def register(hyp: Hypothesis):
    REGISTRY[hyp.id] = hyp


# ---------------------------------------------------------------------------
# Family A: Pivot Reclaim
# ---------------------------------------------------------------------------

def signal_pivot_reclaim(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """Entry when 15m price touches/breaks 1H support zone then reclaims above.

    Conditions:
    1. support_zone exists (1H pivot or stacked zone)
    2. 15m low ≤ support_zone (touch/break into zone)
    3. 15m close > support_zone (reclaim — close above)
    4. RSI < rsi_max (oversold filter)
    5. Optional: volume ≥ vol_sma × vol_mult (volume confirmation)
    """
    if support_zone is None or support_zone <= 0:
        return None

    n = ind['n']
    if bar < 0 or bar >= n:
        return None

    close = ind['closes'][bar]
    low = ind['lows'][bar]
    rsi = ind['rsi'][bar]
    rsi_max = params.get("rsi_max", 40)

    if rsi is None:
        return None

    # Condition 1-2: low touches/breaks support
    if low > support_zone:
        return None

    # Condition 3: close reclaims above support
    if close <= support_zone:
        return None

    # Condition 4: RSI filter
    if rsi >= rsi_max:
        return None

    # Condition 5: optional volume filter
    vol_filter = params.get("vol_filter", False)
    if vol_filter:
        vol = ind['volumes'][bar]
        vol_avg = ind['vol_avg'][bar]
        vol_mult = params.get("vol_mult", 1.5)
        if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
            return None

    # Strength: how deep below zone the wick went (deeper = stronger signal)
    depth = (support_zone - low) / support_zone if support_zone > 0 else 0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, depth * 5 + rsi_score * 0.5)

    return {'strength': strength}


# ---------------------------------------------------------------------------
# Family B: Sweep + Reclaim + Volume
# ---------------------------------------------------------------------------

def signal_sweep_reclaim(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """Entry when 15m wick sweeps below 1H support, reclaims, with volume spike.

    Conditions:
    1. support_zone exists
    2. 15m low < support_zone (SWEEP — wick goes under, not just touches)
    3. 15m close > support_zone (RECLAIM — close above)
    4. volume ≥ vol_sma × vol_mult (capitulation volume)
    5. RSI < rsi_max
    6. Optional: follow-through (next bar condition deferred — checked in-bar only)
    """
    if support_zone is None or support_zone <= 0:
        return None

    n = ind['n']
    if bar < 0 or bar >= n:
        return None

    close = ind['closes'][bar]
    low = ind['lows'][bar]
    rsi = ind['rsi'][bar]

    if rsi is None:
        return None

    rsi_max = params.get("rsi_max", 40)
    vol_mult = params.get("vol_mult", 2.0)

    # Condition 2: SWEEP — wick goes UNDER support (strict <, not ≤)
    if low >= support_zone:
        return None

    # Condition 3: RECLAIM — close above support
    if close <= support_zone:
        return None

    # Condition 4: Volume spike
    vol = ind['volumes'][bar]
    vol_avg = ind['vol_avg'][bar]
    if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
        return None

    # Condition 5: RSI filter
    if rsi >= rsi_max:
        return None

    # Condition 6: Optional follow-through (close > open = green bar)
    follow_through = params.get("follow_through", False)
    if follow_through:
        open_price = ind['opens'][bar]
        if close <= open_price:
            return None

    # Strength: sweep depth + volume magnitude
    sweep_depth = (support_zone - low) / support_zone if support_zone > 0 else 0
    vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
    strength = min(1.0, sweep_depth * 5 + (vol_ratio / 6.0) * 0.5)

    return {'strength': strength}


# ---------------------------------------------------------------------------
# Config Grid — Family A: Pivot Reclaim (6 configs)
# rsi_max {35, 40} × zone_type {pivot_only, dc_bb_stack} × vol_filter {on, off}
# But 2×2×2 = 8 → user wants 6, so: drop 2 low-priority combos
# Keep: rsi35+pivot, rsi35+stack, rsi40+pivot, rsi40+stack (all without vol)
#        + rsi35+pivot+vol, rsi40+stack+vol (2 with vol)
# ---------------------------------------------------------------------------

_BASE_EXIT_PARAMS = {
    "max_stop_pct": 15.0,
    "time_max_bars": 60,       # 60 × 15m = 15H
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 8,     # 8 × 15m = 2H
    "spread_cap_bps": 40,
    "pivot_lookback": 40,
}

_FAMILY_A_CONFIGS = [
    {"id": "SHF-A01", "rsi_max": 35, "zone_type": "pivot_only",   "vol_filter": False,
     "desc": "Pivot reclaim, RSI<35, no vol filter"},
    {"id": "SHF-A02", "rsi_max": 35, "zone_type": "dc_bb_stack",  "vol_filter": False,
     "desc": "Stacked zone reclaim, RSI<35, no vol filter"},
    {"id": "SHF-A03", "rsi_max": 40, "zone_type": "pivot_only",   "vol_filter": False,
     "desc": "Pivot reclaim, RSI<40, no vol filter"},
    {"id": "SHF-A04", "rsi_max": 40, "zone_type": "dc_bb_stack",  "vol_filter": False,
     "desc": "Stacked zone reclaim, RSI<40, no vol filter"},
    {"id": "SHF-A05", "rsi_max": 35, "zone_type": "pivot_only",   "vol_filter": True, "vol_mult": 1.5,
     "desc": "Pivot reclaim, RSI<35, vol confirm 1.5x"},
    {"id": "SHF-A06", "rsi_max": 40, "zone_type": "dc_bb_stack",  "vol_filter": True, "vol_mult": 1.5,
     "desc": "Stacked zone reclaim, RSI<40, vol confirm 1.5x"},
]

# ---------------------------------------------------------------------------
# Config Grid — Family B: Sweep+Reclaim (6 configs)
# vol_mult {2.0, 3.0} × rsi_max {35, 40} × follow_through {on, off}
# 2×2×2 = 8 → keep 6: drop 2 extreme combos
# ---------------------------------------------------------------------------

_FAMILY_B_CONFIGS = [
    {"id": "SHF-B01", "vol_mult": 2.0, "rsi_max": 35, "follow_through": False,
     "desc": "Sweep+reclaim, vol 2x, RSI<35"},
    {"id": "SHF-B02", "vol_mult": 2.0, "rsi_max": 40, "follow_through": False,
     "desc": "Sweep+reclaim, vol 2x, RSI<40"},
    {"id": "SHF-B03", "vol_mult": 3.0, "rsi_max": 35, "follow_through": False,
     "desc": "Sweep+reclaim, vol 3x, RSI<35"},
    {"id": "SHF-B04", "vol_mult": 3.0, "rsi_max": 40, "follow_through": False,
     "desc": "Sweep+reclaim, vol 3x, RSI<40"},
    {"id": "SHF-B05", "vol_mult": 2.0, "rsi_max": 35, "follow_through": True,
     "desc": "Sweep+reclaim, vol 2x, RSI<35, follow-through"},
    {"id": "SHF-B06", "vol_mult": 3.0, "rsi_max": 40, "follow_through": True,
     "desc": "Sweep+reclaim, vol 3x, RSI<40, follow-through"},
]


def build_all_configs() -> list[Hypothesis]:
    """Build all 12 hypothesis configs and register them."""
    hypotheses = []

    for cfg in _FAMILY_A_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **cfg}
        params.pop("id")
        params.pop("desc")
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"PivotReclaim_{cfg['zone_type']}_{cfg['rsi_max']}",
            family="pivot_reclaim",
            signal_fn=signal_pivot_reclaim,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    for cfg in _FAMILY_B_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **cfg}
        params.pop("id")
        params.pop("desc")
        # Family B always uses pivot_only for zone detection
        params["zone_type"] = "pivot_only"
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"SweepReclaim_v{cfg['vol_mult']}_{cfg['rsi_max']}",
            family="sweep_reclaim",
            signal_fn=signal_sweep_reclaim,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    return hypotheses


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    passed = 0
    failed = 0

    def check(name, condition, msg=""):
        global passed, failed
        if condition:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name} — {msg}")
            failed += 1

    print("=== SuperHF Hypotheses Self-Test ===\n")

    # Build all configs
    configs = build_all_configs()
    check("12_configs_registered", len(configs) == 12, f"got {len(configs)}")
    check("registry_has_12", len(REGISTRY) == 12, f"got {len(REGISTRY)}")

    # Check families
    family_a = [h for h in configs if h.family == "pivot_reclaim"]
    family_b = [h for h in configs if h.family == "sweep_reclaim"]
    check("family_a_has_6", len(family_a) == 6, f"got {len(family_a)}")
    check("family_b_has_6", len(family_b) == 6, f"got {len(family_b)}")

    # Test signal_pivot_reclaim
    mock_ind = {
        'n': 10, 'closes': [100]*10, 'lows': [95]*10, 'opens': [98]*10,
        'highs': [105]*10, 'volumes': [1000]*10,
        'rsi': [35]*10, 'atr': [2.0]*10, 'vol_avg': [500]*10,
    }

    # Should trigger: low(95) < zone(98), close(100) > zone(98), rsi(35) < 40
    sig = signal_pivot_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_filter": False}, 98.0)
    check("pivot_reclaim_triggers", sig is not None, f"got {sig}")

    # Should NOT trigger: low(95) < zone(94) is FALSE
    sig2 = signal_pivot_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_filter": False}, 94.0)
    check("pivot_reclaim_no_trigger_low_above_zone", sig2 is None, f"got {sig2}")

    # Should NOT trigger: close(100) > zone(101) is FALSE
    sig3 = signal_pivot_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_filter": False}, 101.0)
    check("pivot_reclaim_no_trigger_no_reclaim", sig3 is None, f"got {sig3}")

    # Test signal_sweep_reclaim
    # low(95) < zone(98) ✓, close(100) > zone(98) ✓, vol(1000) >= vol_avg(500)*2 ✓, rsi(35) < 40 ✓
    sig4 = signal_sweep_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_mult": 2.0, "follow_through": False}, 98.0)
    check("sweep_reclaim_triggers", sig4 is not None, f"got {sig4}")

    # No trigger: vol(1000) < vol_avg(500)*3 = 1500
    sig5 = signal_sweep_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_mult": 3.0, "follow_through": False}, 98.0)
    check("sweep_reclaim_no_trigger_low_vol", sig5 is None, f"got {sig5}")

    # Follow-through: close(100) > open(98) ✓
    sig6 = signal_sweep_reclaim([], 5, mock_ind, {"rsi_max": 40, "vol_mult": 2.0, "follow_through": True}, 98.0)
    check("sweep_reclaim_follow_through_pass", sig6 is not None, f"got {sig6}")

    # Follow-through fail: set close < open
    mock_ind2 = {**mock_ind, 'closes': [97]*10, 'opens': [98]*10}
    sig7 = signal_sweep_reclaim([], 5, mock_ind2, {"rsi_max": 40, "vol_mult": 2.0, "follow_through": True}, 96.0)
    # low(95) < zone(96) ✓, close(97) > zone(96) ✓, but close(97) <= open(98) → no follow-through
    check("sweep_reclaim_follow_through_fail", sig7 is None, f"got {sig7}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        exit(1)
    print("All tests passed!")
