"""
SuperHF Sprint 3 -- 10 Signal Configs (3 families: C/D/E).

KEY DIFFERENCE from Sprint 1+2: All entries are evaluated on 1H indicators, not 15m.

Family C: 1H Pivot Bounce (4 configs)
  Entry when 1H bar's low touches/goes below support zone, close reclaims above it.
  needs_15m_confirm = True (confirms with green 15m candle).

Family D: 1H DC Low Reclaim (3 configs)
  Previous 1H close below DC low, current 1H close reclaims above DC low.
  needs_15m_confirm = False (1H reclaim is sufficient).

Family E: 1H Volume Capitulation (3 configs)
  Adapted from 4H Sprint 4 config 041. Volume spike + close below BB level.
  needs_15m_confirm = True (wait for 15m green candle as reversal confirm).

Signal protocol (1H-based):
    signal_fn(candles_1h, bar, ind, params) -> dict | None
    Return: {'strength': float, 'needs_15m_confirm': bool} or None

Exits are handled by harness (hybrid_notrl: FIXED STOP -> TIME MAX -> DC TARGET -> BB TARGET).
RSI recovery is OFF for sub-4H (proven noise).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# Hypothesis dataclass (same as Sprint 1)
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str           # SHF-C01, SHF-D01, SHF-E01, ...
    name: str
    family: str       # "1h_pivot_bounce", "1h_dc_reclaim", "1h_vol_capitulation"
    description: str
    signal_fn: Callable
    params: dict


REGISTRY_S3: dict[str, Hypothesis] = {}


def register_s3(hyp: Hypothesis):
    REGISTRY_S3[hyp.id] = hyp


# ---------------------------------------------------------------------------
# Shared exit params for Sprint 3 (1H-based)
# ---------------------------------------------------------------------------

_BASE_EXIT_PARAMS_S3 = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,        # 15 x 1H = 15H
    "rsi_recovery": False,      # Proven noise on sub-4H
    "spread_cap_bps": 40,
    "pivot_lookback": 40,
}


# ---------------------------------------------------------------------------
# Family C: 1H Pivot Bounce
# ---------------------------------------------------------------------------

def signal_1h_pivot_bounce(
    candles_1h: list[dict],
    bar: int,
    ind: dict,
    params: dict,
) -> dict | None:
    """Entry when 1H bar's low touches/goes below support zone, close reclaims above.

    Conditions:
    1. bar >= 1, rsi not None
    2. rsi < rsi_max
    3. Support zone exists (from params["_support_zones_1h"][bar])
    4. low <= support (wick touches/goes below)
    5. close > support (reclaims above)
    6. Optional volume filter (vol >= vol_avg * vol_mult)

    Returns {'strength': ..., 'needs_15m_confirm': True} or None.
    """
    n = ind.get("n", 0)
    if bar < 1 or bar >= n:
        return None

    rsi = ind["rsi"][bar]
    if rsi is None:
        return None

    rsi_max = params.get("rsi_max", 40)
    if rsi >= rsi_max:
        return None

    # Support zone lookup
    support_zones = params.get("_support_zones_1h", {})
    support = support_zones.get(bar)
    if support is None or support <= 0:
        return None

    low = ind["lows"][bar]
    close = ind["closes"][bar]

    # Wick touches/goes below support
    if low > support:
        return None

    # Close reclaims above support
    if close <= support:
        return None

    # Optional volume filter
    vol_filter = params.get("vol_filter", False)
    if vol_filter:
        vol = ind["volumes"][bar]
        vol_avg = ind["vol_avg"][bar]
        vol_mult = params.get("vol_mult", 1.5)
        if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
            return None

    # Strength: depth below support + RSI oversold score
    depth = (support - low) / support if support > 0 else 0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, depth * 5 + rsi_score * 0.5)

    return {"strength": strength, "needs_15m_confirm": True}


# ---------------------------------------------------------------------------
# Family D: 1H DC Low Reclaim
# ---------------------------------------------------------------------------

def _compute_dc_low_inline(lows: list[float], bar: int, period: int) -> float | None:
    """Compute Donchian low (previous bar's period) inline for non-default periods."""
    if bar < period:
        return None
    return min(lows[bar - period:bar])


def signal_1h_dc_reclaim(
    candles_1h: list[dict],
    bar: int,
    ind: dict,
    params: dict,
) -> dict | None:
    """Entry when previous 1H close < DC low, current 1H close reclaims above DC low.

    Conditions:
    1. bar >= 2, rsi not None
    2. rsi < rsi_max
    3. Get dc_low: from ind['dc_prev_low'] if dc_lookback==20, else compute inline
    4. Previous close < dc_low at (bar-1)
    5. Current close > dc_low at bar (reclaim)
    6. Optional volume confirmation (vol >= vol_avg * vol_mult)

    Returns {'strength': ..., 'needs_15m_confirm': False} or None.
    """
    n = ind.get("n", 0)
    if bar < 2 or bar >= n:
        return None

    rsi = ind["rsi"][bar]
    if rsi is None:
        return None

    rsi_max = params.get("rsi_max", 40)
    if rsi >= rsi_max:
        return None

    dc_lookback = params.get("dc_lookback", 20)

    # Get DC low for current and previous bar
    if dc_lookback == 20:
        # Use precomputed dc_prev_low from indicators
        dc_low_cur = ind["dc_prev_low"][bar]
        dc_low_prev = ind["dc_prev_low"][bar - 1]
    else:
        # Compute inline for non-default period
        dc_low_cur = _compute_dc_low_inline(ind["lows"], bar, dc_lookback)
        dc_low_prev = _compute_dc_low_inline(ind["lows"], bar - 1, dc_lookback)

    if dc_low_cur is None or dc_low_prev is None:
        return None

    prev_close = ind["closes"][bar - 1]
    cur_close = ind["closes"][bar]

    # Previous close below DC low
    if prev_close >= dc_low_prev:
        return None

    # Current close reclaims above DC low
    if cur_close <= dc_low_cur:
        return None

    # Optional volume confirmation
    vol_confirm = params.get("vol_confirm", False)
    if vol_confirm:
        vol = ind["volumes"][bar]
        vol_avg = ind["vol_avg"][bar]
        vol_mult = params.get("vol_mult", 1.5)
        if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
            return None

    # Strength: reclaim magnitude + RSI oversold score
    reclaim_pct = (cur_close - dc_low_cur) / dc_low_cur if dc_low_cur > 0 else 0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, reclaim_pct * 10 + rsi_score * 0.5)

    return {"strength": strength, "needs_15m_confirm": False}


# ---------------------------------------------------------------------------
# Family E: 1H Volume Capitulation
# ---------------------------------------------------------------------------

def signal_1h_vol_capitulation(
    candles_1h: list[dict],
    bar: int,
    ind: dict,
    params: dict,
) -> dict | None:
    """Entry on volume capitulation: volume spike + close below BB level.

    Adapted from 4H Sprint 4 config 041 (Vol Capitulation 3x BBlow RSI40).

    Conditions:
    1. bar >= 1, rsi not None
    2. rsi < rsi_max
    3. Volume >= vol_mult * vol_avg
    4. close < bb_ref (bb_lower or bb_mid based on bb_condition param)
    5. Bonus strength if also close < dc_prev_low

    Returns {'strength': ..., 'needs_15m_confirm': True} or None.
    """
    n = ind.get("n", 0)
    if bar < 1 or bar >= n:
        return None

    rsi = ind["rsi"][bar]
    if rsi is None:
        return None

    rsi_max = params.get("rsi_max", 40)
    if rsi >= rsi_max:
        return None

    # Volume spike check
    vol = ind["volumes"][bar]
    vol_avg = ind["vol_avg"][bar]
    vol_mult = params.get("vol_mult", 2.0)
    if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
        return None

    close = ind["closes"][bar]

    # BB condition
    bb_condition = params.get("bb_condition", "bb_lower")
    if bb_condition == "bb_lower":
        bb_ref = ind["bb_lower"][bar]
    elif bb_condition == "bb_mid":
        bb_ref = ind["bb_mid"][bar]
    else:
        bb_ref = ind["bb_lower"][bar]

    if bb_ref is None:
        return None

    if close >= bb_ref:
        return None

    # Strength: volume magnitude + RSI oversold + bonus for DC breach
    vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, (vol_ratio / 6.0) * 0.4 + rsi_score * 0.4)

    # Bonus: close also below DC prev low
    dc_low = ind["dc_prev_low"][bar]
    if dc_low is not None and close < dc_low:
        strength = min(1.0, strength + 0.2)

    return {"strength": strength, "needs_15m_confirm": True}


# ---------------------------------------------------------------------------
# Config Grid -- Family C: 1H Pivot Bounce (4 configs)
# ---------------------------------------------------------------------------

_FAMILY_C_CONFIGS = [
    {"id": "SHF-C01", "rsi_max": 35, "zone_type": "pivot_only",   "vol_filter": False,
     "desc": "1H pivot bounce, RSI<35"},
    {"id": "SHF-C02", "rsi_max": 40, "zone_type": "pivot_only",   "vol_filter": False,
     "desc": "1H pivot bounce, RSI<40"},
    {"id": "SHF-C03", "rsi_max": 35, "zone_type": "dc_bb_stack",  "vol_filter": False,
     "desc": "1H stacked zone bounce, RSI<35"},
    {"id": "SHF-C04", "rsi_max": 40, "zone_type": "dc_bb_stack",  "vol_filter": False,
     "desc": "1H stacked zone bounce, RSI<40"},
]

# ---------------------------------------------------------------------------
# Config Grid -- Family D: 1H DC Low Reclaim (3 configs)
# ---------------------------------------------------------------------------

_FAMILY_D_CONFIGS = [
    {"id": "SHF-D01", "rsi_max": 40, "dc_lookback": 20, "vol_confirm": False,
     "desc": "1H DC low reclaim, DC20"},
    {"id": "SHF-D02", "rsi_max": 40, "dc_lookback": 20, "vol_confirm": True, "vol_mult": 1.5,
     "desc": "1H DC low reclaim, DC20, vol 1.5x"},
    {"id": "SHF-D03", "rsi_max": 40, "dc_lookback": 30, "vol_confirm": False,
     "desc": "1H DC low reclaim, DC30"},
]

# ---------------------------------------------------------------------------
# Config Grid -- Family E: 1H Volume Capitulation (3 configs)
# ---------------------------------------------------------------------------

_FAMILY_E_CONFIGS = [
    {"id": "SHF-E01", "rsi_max": 40, "vol_mult": 2.0, "bb_condition": "bb_lower",
     "desc": "1H vol cap 2x, close < BB lower"},
    {"id": "SHF-E02", "rsi_max": 40, "vol_mult": 3.0, "bb_condition": "bb_lower",
     "desc": "1H vol cap 3x, close < BB lower"},
    {"id": "SHF-E03", "rsi_max": 35, "vol_mult": 2.0, "bb_condition": "bb_mid",
     "desc": "1H vol cap 2x, close < BB mid, RSI<35"},
]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_all_configs_s3() -> list[Hypothesis]:
    """Build all 10 Sprint 3 hypothesis configs and register them."""
    hypotheses: list[Hypothesis] = []

    # Family C: 1H Pivot Bounce
    for cfg in _FAMILY_C_CONFIGS:
        params = {**_BASE_EXIT_PARAMS_S3}
        params["rsi_max"] = cfg["rsi_max"]
        params["zone_type"] = cfg["zone_type"]
        params["vol_filter"] = cfg["vol_filter"]
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"1H_PivotBounce_{cfg['zone_type']}_{cfg['rsi_max']}",
            family="1h_pivot_bounce",
            description=cfg["desc"],
            signal_fn=signal_1h_pivot_bounce,
            params=params,
        )
        register_s3(hyp)
        hypotheses.append(hyp)

    # Family D: 1H DC Low Reclaim
    for cfg in _FAMILY_D_CONFIGS:
        params = {**_BASE_EXIT_PARAMS_S3}
        params["rsi_max"] = cfg["rsi_max"]
        params["dc_lookback"] = cfg["dc_lookback"]
        params["vol_confirm"] = cfg["vol_confirm"]
        if "vol_mult" in cfg:
            params["vol_mult"] = cfg["vol_mult"]
        suffix = f"DC{cfg['dc_lookback']}"
        if cfg["vol_confirm"]:
            suffix += f"_vol{cfg.get('vol_mult', 1.5)}x"
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"1H_DCReclaim_{suffix}_{cfg['rsi_max']}",
            family="1h_dc_reclaim",
            description=cfg["desc"],
            signal_fn=signal_1h_dc_reclaim,
            params=params,
        )
        register_s3(hyp)
        hypotheses.append(hyp)

    # Family E: 1H Volume Capitulation
    for cfg in _FAMILY_E_CONFIGS:
        params = {**_BASE_EXIT_PARAMS_S3}
        params["rsi_max"] = cfg["rsi_max"]
        params["vol_mult"] = cfg["vol_mult"]
        params["bb_condition"] = cfg["bb_condition"]
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"1H_VolCap_{cfg['vol_mult']}x_{cfg['bb_condition']}_{cfg['rsi_max']}",
            family="1h_vol_capitulation",
            description=cfg["desc"],
            signal_fn=signal_1h_vol_capitulation,
            params=params,
        )
        register_s3(hyp)
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
            print(f"  FAIL  {name} -- {msg}")
            failed += 1

    print("=== SuperHF Sprint 3 Hypotheses Self-Test ===\n")

    # ----- Test 1: Build all configs -----
    configs = build_all_configs_s3()
    check("10_configs_built", len(configs) == 10, f"got {len(configs)}")
    check("registry_has_10", len(REGISTRY_S3) == 10, f"got {len(REGISTRY_S3)}")

    # Unique IDs
    ids = [h.id for h in configs]
    check("unique_ids", len(set(ids)) == 10, f"duplicates: {[x for x in ids if ids.count(x) > 1]}")

    # 3 families
    families = set(h.family for h in configs)
    check("3_families", len(families) == 3, f"got {families}")
    check("family_c_count", sum(1 for h in configs if h.family == "1h_pivot_bounce") == 4)
    check("family_d_count", sum(1 for h in configs if h.family == "1h_dc_reclaim") == 3)
    check("family_e_count", sum(1 for h in configs if h.family == "1h_vol_capitulation") == 3)

    # ----- Test 2: All params have rsi_recovery=False, time_max_bars=15 -----
    for h in configs:
        check(f"{h.id}_rsi_recovery_false",
              h.params.get("rsi_recovery") is False,
              f"rsi_recovery={h.params.get('rsi_recovery')}")
        check(f"{h.id}_tmb_15",
              h.params.get("time_max_bars") == 15,
              f"time_max_bars={h.params.get('time_max_bars')}")

    # ----- Test 3: Smoke test each signal function -----
    print("\n--- Signal smoke tests ---")

    # Mock 1H indicators (10 bars)
    mock_ind = {
        "n": 10,
        "closes": [100.0] * 10,
        "highs": [105.0] * 10,
        "lows": [95.0] * 10,
        "volumes": [1000.0] * 10,
        "rsi": [None] + [35.0] * 9,
        "atr": [None] + [2.0] * 9,
        "dc_prev_low": [None] + [96.0] * 9,
        "dc_mid": [None] + [102.0] * 9,
        "bb_mid": [None] + [101.0] * 9,
        "bb_lower": [None] + [97.0] * 9,
        "bb_upper": [None] + [103.0] * 9,
        "vol_avg": [None] + [500.0] * 9,
        "pivot_lows": [None] * 10,
    }

    # -- Family C: 1H Pivot Bounce --
    # Should trigger: low(95) <= support(98), close(100) > support(98), rsi(35) < 40
    params_c = {"rsi_max": 40, "vol_filter": False, "_support_zones_1h": {5: 98.0}}
    sig = signal_1h_pivot_bounce([], 5, mock_ind, params_c)
    check("C_triggers", sig is not None, f"got {sig}")
    check("C_needs_15m_confirm", sig is not None and sig.get("needs_15m_confirm") is True)

    # Should NOT trigger: no support zone
    params_c_no_zone = {"rsi_max": 40, "vol_filter": False, "_support_zones_1h": {}}
    sig2 = signal_1h_pivot_bounce([], 5, mock_ind, params_c_no_zone)
    check("C_no_zone_returns_none", sig2 is None, f"got {sig2}")

    # Should NOT trigger: low(95) > support(90) -- wick doesn't reach zone
    params_c_deep = {"rsi_max": 40, "vol_filter": False, "_support_zones_1h": {5: 90.0}}
    sig3 = signal_1h_pivot_bounce([], 5, mock_ind, params_c_deep)
    check("C_low_above_zone_none", sig3 is None, f"got {sig3}")

    # Should NOT trigger: close(100) <= support(101) -- no reclaim
    params_c_high = {"rsi_max": 40, "vol_filter": False, "_support_zones_1h": {5: 101.0}}
    sig4 = signal_1h_pivot_bounce([], 5, mock_ind, params_c_high)
    check("C_no_reclaim_none", sig4 is None, f"got {sig4}")

    # -- Family D: 1H DC Low Reclaim --
    # Setup: prev close < dc_low_prev, cur close > dc_low_cur
    mock_ind_d = {**mock_ind}
    mock_ind_d["closes"] = [100.0] * 10
    # bar 4 close = 94 (below dc_low=96), bar 5 close = 100 (above dc_low=96)
    mock_ind_d["closes"][4] = 94.0
    mock_ind_d["closes"][5] = 100.0
    params_d = {"rsi_max": 40, "dc_lookback": 20, "vol_confirm": False}
    sig5 = signal_1h_dc_reclaim([], 5, mock_ind_d, params_d)
    check("D_triggers", sig5 is not None, f"got {sig5}")
    check("D_needs_15m_confirm_false", sig5 is not None and sig5.get("needs_15m_confirm") is False)

    # Should NOT trigger: prev close(100) >= dc_low(96)
    mock_ind_d2 = {**mock_ind}
    sig6 = signal_1h_dc_reclaim([], 5, mock_ind_d2, params_d)
    check("D_no_prior_break_none", sig6 is None, f"got {sig6}")

    # DC30 inline computation: bar must be >= 30 (not enough bars in mock)
    params_d30 = {"rsi_max": 40, "dc_lookback": 30, "vol_confirm": False}
    sig7 = signal_1h_dc_reclaim([], 5, mock_ind, params_d30)
    check("D_dc30_insufficient_bars_none", sig7 is None, f"got {sig7}")

    # Vol confirm: vol(1000) >= vol_avg(500) * 1.5 = 750 -> passes
    mock_ind_d3 = {**mock_ind}
    mock_ind_d3["closes"] = [100.0] * 10
    mock_ind_d3["closes"][4] = 94.0
    mock_ind_d3["closes"][5] = 100.0
    params_d_vol = {"rsi_max": 40, "dc_lookback": 20, "vol_confirm": True, "vol_mult": 1.5}
    sig8 = signal_1h_dc_reclaim([], 5, mock_ind_d3, params_d_vol)
    check("D_vol_confirm_passes", sig8 is not None, f"got {sig8}")

    # -- Family E: 1H Volume Capitulation --
    # close(100) < bb_lower(97) is FALSE -> need close < bb_lower
    mock_ind_e = {**mock_ind}
    mock_ind_e["closes"] = [100.0] * 10
    mock_ind_e["closes"][5] = 96.0  # below bb_lower(97)
    params_e = {"rsi_max": 40, "vol_mult": 2.0, "bb_condition": "bb_lower"}
    sig9 = signal_1h_vol_capitulation([], 5, mock_ind_e, params_e)
    check("E_triggers", sig9 is not None, f"got {sig9}")
    check("E_needs_15m_confirm", sig9 is not None and sig9.get("needs_15m_confirm") is True)

    # Bonus strength: close also < dc_prev_low(96)
    mock_ind_e2 = {**mock_ind}
    mock_ind_e2["closes"] = [100.0] * 10
    mock_ind_e2["closes"][5] = 95.0  # below bb_lower(97) AND dc_prev_low(96)
    sig10 = signal_1h_vol_capitulation([], 5, mock_ind_e2, params_e)
    check("E_dc_bonus_higher_strength",
          sig10 is not None and sig9 is not None and sig10["strength"] > sig9["strength"],
          f"base={sig9}, bonus={sig10}")

    # Should NOT trigger: volume too low (vol_mult=3.0, need 1500, have 1000)
    params_e_high_vol = {"rsi_max": 40, "vol_mult": 3.0, "bb_condition": "bb_lower"}
    sig11 = signal_1h_vol_capitulation([], 5, mock_ind_e, params_e_high_vol)
    check("E_low_vol_none", sig11 is None, f"got {sig11}")

    # Should NOT trigger: close(100) >= bb_lower(97)
    sig12 = signal_1h_vol_capitulation([], 5, mock_ind, params_e)
    check("E_close_above_bb_none", sig12 is None, f"got {sig12}")

    # BB mid condition
    mock_ind_e3 = {**mock_ind}
    mock_ind_e3["closes"] = [100.0] * 10
    mock_ind_e3["closes"][5] = 101.5  # above bb_mid(101) -> should not trigger
    params_e_mid = {"rsi_max": 40, "vol_mult": 2.0, "bb_condition": "bb_mid"}
    sig13 = signal_1h_vol_capitulation([], 5, mock_ind_e3, params_e_mid)
    check("E_bb_mid_above_none", sig13 is None, f"got {sig13}")

    mock_ind_e4 = {**mock_ind}
    mock_ind_e4["closes"] = [100.0] * 10
    mock_ind_e4["closes"][5] = 99.0  # below bb_mid(101) -> should trigger
    sig14 = signal_1h_vol_capitulation([], 5, mock_ind_e4, params_e_mid)
    check("E_bb_mid_triggers", sig14 is not None, f"got {sig14}")

    # ----- Test 4: Print all configs -----
    print("\n--- All Sprint 3 Configs ---")
    for h in configs:
        print(f"  {h.id:8s}  {h.family:22s}  {h.description}")

    # ----- Summary -----
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        print("SOME TESTS FAILED")
        exit(1)
    print(f"All {passed} self-tests PASS")
