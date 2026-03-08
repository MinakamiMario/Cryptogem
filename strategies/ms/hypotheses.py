"""
MS Sprint 1 — Market Structure Signal Families: 5 families, 18 configs.

Each signal_fn follows the protocol:
    signal_fn(candles, bar, indicators, params) -> dict | None
    Return: {stop_price, target_price, time_limit, strength} or None

Families:
    MS-A: Liquidity Sweep + Reclaim (4 configs)
    MS-B: Fair Value Gap Fill (4 configs)
    MS-C: Order Block Touch (4 configs)
    MS-D: Swing Failure Pattern — SFP (3 configs)
    MS-E: Structure Shift + Pullback (3 configs)

Total: 18 configs.

Uses hybrid_notrl exits via _dc_exit_placeholder(). Stop/target in the return
dict are PLACEHOLDERS — the DC engine ignores them.

DC-geometry compliance is tracked as a soft metric per entry (not a hard gate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from strategies.ms.indicators import (
    get_recent_swing_low,
    get_recent_swing_high,
    get_active_bullish_fvgs,
    FVG,
    BoS,
    OrderBlock,
    LiquidityZone,
)


# ---------------------------------------------------------------------------
# DC exit placeholder — same as Sprint 4
# ---------------------------------------------------------------------------

def _dc_exit_placeholder(entry_price: float, params: dict) -> dict:
    """Build placeholder exit dict for DC exit mode."""
    max_stop_pct = params.get("max_stop_pct", 15.0)
    return {
        "stop_price": entry_price * (1 - max_stop_pct / 100),
        "target_price": entry_price * 1.10,  # placeholder
        "time_limit": params.get("time_max_bars", 15),
    }


def _check_dc_geometry(indicators: dict, bar: int) -> float:
    """Compute DC-geometry compliance score (0.0 = non-compliant, 1.0 = perfect).

    Checks: close < dc_mid, close < bb_mid, rsi < 40.
    Returns score 0.0-1.0 (soft metric, NOT a gate).
    """
    close = indicators["closes"][bar]
    dc_mid = indicators["dc_mid"][bar]
    bb_mid = indicators["bb_mid"][bar]
    rsi = indicators["rsi"][bar]

    if dc_mid is None or bb_mid is None or rsi is None:
        return 0.0

    score = 0.0
    if close < dc_mid:
        score += 0.33
    if close < bb_mid:
        score += 0.33
    if rsi < 40:
        score += 0.34
    return score


# ---------------------------------------------------------------------------
# Family A: Liquidity Sweep + Reclaim (4 configs)
# ---------------------------------------------------------------------------

def signal_liq_sweep_reclaim(candles, bar, indicators, params) -> dict | None:
    """Liquidity Sweep + Reclaim.

    Concept: Price wicks below recent swing low (sweep), then closes
    back above it (reclaim). Stop hunt → reversal.

    Params:
      swing_lookback (int): max bars to search for swing low (default 40)
      min_wick_atr (float): min sweep depth in ATR (default 0.3)
      require_green (bool): require close > open (default True)
      vol_mult (float): volume spike filter (default 1.0 = off)
    """
    swing_lookback = params.get("swing_lookback", 40)
    min_wick_atr = params.get("min_wick_atr", 0.3)
    require_green = params.get("require_green", True)
    vol_mult = params.get("vol_mult", 1.0)

    swing_lows = indicators["swing_lows"]
    lows = indicators["lows"]
    highs = indicators["highs"]
    closes = indicators["closes"]
    atr = indicators["atr"]

    # Need ATR
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Find recent swing low
    price, swing_bar = get_recent_swing_low(swing_lows, bar, max_lookback=swing_lookback)
    if price is None:
        return None

    low = lows[bar]
    close = closes[bar]

    # 1. Sweep: low wicks below swing low
    if low >= price:
        return None

    # 2. Reclaim: close above swing low
    if close <= price:
        return None

    # 3. Min wick depth
    wick_depth = price - low
    if wick_depth < min_wick_atr * cur_atr:
        return None

    # 4. Green bar filter
    if require_green:
        opens = indicators["opens"]
        if close <= opens[bar]:
            return None

    # 5. Volume filter
    if vol_mult > 1.0:
        vol_avg = indicators["vol_avg"]
        volumes = indicators["volumes"]
        if vol_avg[bar] is None or vol_avg[bar] <= 0:
            return None
        if volumes[bar] < vol_mult * vol_avg[bar]:
            return None

    # Strength: wick depth normalized by ATR
    strength = min(wick_depth / cur_atr, 3.0)

    # DC-geometry compliance (soft metric)
    dc_fit = _check_dc_geometry(indicators, bar)

    result = _dc_exit_placeholder(close, params)
    result["strength"] = strength
    result["dc_geometry"] = dc_fit
    return result


# ---------------------------------------------------------------------------
# Family B: Fair Value Gap Fill (4 configs)
# ---------------------------------------------------------------------------

def signal_fvg_fill(candles, bar, indicators, params) -> dict | None:
    """Fair Value Gap Fill.

    Concept: Price fills an unfilled bullish FVG zone.
    Imbalance → rebalance → continuation.

    Params:
      max_fvg_age (int): max bars since FVG creation (default 20)
      fill_depth (float): how deep into gap (0.25=top, 0.75=deep) (default 0.50)
      min_gap_atr (float): min gap size in ATR (default 0.3)
      rsi_max (float): RSI filter (0 = off) (default 50)
    """
    max_fvg_age = params.get("max_fvg_age", 20)
    fill_depth = params.get("fill_depth", 0.50)
    rsi_max = params.get("rsi_max", 50)

    closes = indicators["closes"]
    lows = indicators["lows"]
    atr = indicators["atr"]

    close = closes[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Get active bullish FVGs
    fvg_snapshots = indicators["fvg_snapshots"]
    active_fvgs = get_active_bullish_fvgs(fvg_snapshots, bar, max_age=max_fvg_age)
    if not active_fvgs:
        return None

    # Find the FVG being filled
    best_fvg = None
    best_depth = 0.0
    for fvg in active_fvgs:
        gap_range = fvg.gap_high - fvg.gap_low
        if gap_range <= 0:
            continue

        # Check if close is entering the gap from above
        if close <= fvg.gap_high:
            # How deep? 0 = at gap_high, 1 = at gap_low
            depth = (fvg.gap_high - close) / gap_range
            depth = min(1.0, max(0.0, depth))
            if depth >= fill_depth and depth > best_depth:
                best_fvg = fvg
                best_depth = depth

    if best_fvg is None:
        return None

    # RSI filter
    if rsi_max > 0:
        rsi = indicators["rsi"][bar]
        if rsi is None or rsi >= rsi_max:
            return None

    # Strength: fill depth * gap size in ATR
    gap_atr = (best_fvg.gap_high - best_fvg.gap_low) / cur_atr
    strength = min(best_depth * gap_atr, 3.0)

    dc_fit = _check_dc_geometry(indicators, bar)

    result = _dc_exit_placeholder(close, params)
    result["strength"] = strength
    result["dc_geometry"] = dc_fit
    return result


# ---------------------------------------------------------------------------
# Family C: Order Block Touch (4 configs)
# ---------------------------------------------------------------------------

def signal_ob_touch(candles, bar, indicators, params) -> dict | None:
    """Order Block Touch.

    Concept: Price touches a bullish order block zone (last bearish candle
    before impulse move). Institutional demand zone → bounce.

    Params:
      max_ob_age (int): max bars since OB creation (default 30)
      min_impulse_atr (float): min impulse size in ATR (default 1.5)
      require_close_in_zone (bool): close must be within OB zone (default True)
      vol_mult (float): volume spike filter (default 1.0 = off)
    """
    max_ob_age = params.get("max_ob_age", 30)
    require_close_in_zone = params.get("require_close_in_zone", True)
    vol_mult = params.get("vol_mult", 1.0)

    lows = indicators["lows"]
    closes = indicators["closes"]
    atr = indicators["atr"]

    close = closes[bar]
    low = lows[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Get active (unmitigated) bullish OBs
    ob_snapshots = indicators["ob_snapshots"]
    if bar >= len(ob_snapshots):
        return None
    active_obs = ob_snapshots[bar]

    best_ob = None
    best_strength = 0.0
    for ob in active_obs:
        if ob.direction != "bullish":
            continue
        if bar - ob.bar_created > max_ob_age:
            continue

        # Touch: low touches or enters the OB zone
        if low > ob.zone_high:
            continue  # price above OB zone, no touch

        # Close in zone check
        if require_close_in_zone:
            if close < ob.zone_low:
                continue  # broken through the OB

        # Strength: impulse_size_atr of the OB
        if ob.impulse_size_atr > best_strength:
            best_ob = ob
            best_strength = ob.impulse_size_atr

    if best_ob is None:
        return None

    # Volume filter
    if vol_mult > 1.0:
        vol_avg = indicators["vol_avg"]
        volumes = indicators["volumes"]
        if vol_avg[bar] is None or vol_avg[bar] <= 0:
            return None
        if volumes[bar] < vol_mult * vol_avg[bar]:
            return None

    strength = min(best_strength, 3.0)

    dc_fit = _check_dc_geometry(indicators, bar)

    result = _dc_exit_placeholder(close, params)
    result["strength"] = strength
    result["dc_geometry"] = dc_fit
    return result


# ---------------------------------------------------------------------------
# Family D: Swing Failure Pattern — SFP (3 configs)
# ---------------------------------------------------------------------------

def signal_sfp(candles, bar, indicators, params) -> dict | None:
    """Swing Failure Pattern (SFP).

    Concept: Price breaks below swing low but closes above it
    in the SAME bar. False breakout → trapped sellers → reversal.

    Very similar to Family A but requires same-bar reclaim AND
    measures close strength (position within the bar's range).

    Params:
      swing_lookback (int): max bars to search for swing low (default 40)
      min_close_strength (float): min (close-low)/(high-low) (default 0.50)
      vol_mult (float): volume spike filter (default 1.0 = off)
    """
    swing_lookback = params.get("swing_lookback", 40)
    min_close_strength = params.get("min_close_strength", 0.50)
    vol_mult = params.get("vol_mult", 1.0)

    swing_lows = indicators["swing_lows"]
    highs = indicators["highs"]
    lows = indicators["lows"]
    closes = indicators["closes"]
    atr = indicators["atr"]

    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Find recent swing low
    price, swing_bar = get_recent_swing_low(swing_lows, bar, max_lookback=swing_lookback)
    if price is None:
        return None

    high = highs[bar]
    low = lows[bar]
    close = closes[bar]

    # 1. Break: low below swing low (same bar)
    if low >= price:
        return None

    # 2. Reclaim: close above swing low (same bar)
    if close <= price:
        return None

    # 3. Close strength: position within bar range
    bar_range = high - low
    if bar_range <= 0:
        return None
    close_strength = (close - low) / bar_range
    if close_strength < min_close_strength:
        return None

    # Volume filter
    if vol_mult > 1.0:
        vol_avg = indicators["vol_avg"]
        volumes = indicators["volumes"]
        if vol_avg[bar] is None or vol_avg[bar] <= 0:
            return None
        if volumes[bar] < vol_mult * vol_avg[bar]:
            return None

    # Strength: close_strength * sweep_depth_atr
    sweep_depth = (price - low) / cur_atr
    strength = min(close_strength * sweep_depth, 3.0)

    dc_fit = _check_dc_geometry(indicators, bar)

    result = _dc_exit_placeholder(close, params)
    result["strength"] = strength
    result["dc_geometry"] = dc_fit
    return result


# ---------------------------------------------------------------------------
# Family E: Structure Shift + Pullback (3 configs)
# ---------------------------------------------------------------------------

def signal_structure_shift_pullback(candles, bar, indicators, params) -> dict | None:
    """Structure Shift + Pullback.

    Concept: After bullish BoS (higher high), wait for pullback
    towards the swing low zone. Trend change confirmed → buy pullback.

    Params:
      max_bos_age (int): max bars since BoS event (default 15)
      pullback_pct (float): depth into BoS→swing range (default 0.50)
      max_pullback_bars (int): max bars for pullback to arrive (default 8)
    """
    max_bos_age = params.get("max_bos_age", 15)
    pullback_pct = params.get("pullback_pct", 0.50)
    max_pullback_bars = params.get("max_pullback_bars", 8)

    bos_events = indicators["bos_events"]
    closes = indicators["closes"]
    swing_lows = indicators["swing_lows"]
    atr = indicators["atr"]

    close = closes[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Search backward for recent bullish BoS
    recent_bos = None
    for b in range(bar - 1, max(bar - max_bos_age - 1, -1), -1):
        if b < 0:
            break
        event = bos_events[b]
        if event is not None and event.direction == "bullish":
            recent_bos = event
            break

    if recent_bos is None:
        return None

    # BoS age check
    bos_age = bar - recent_bos.bar
    if bos_age > max_bos_age or bos_age > max_pullback_bars:
        return None

    # Find the swing low that the BoS broke above
    # Search backward from the BoS bar for the nearest swing low
    swing_price, swing_bar_idx = get_recent_swing_low(
        swing_lows, recent_bos.bar, max_lookback=60
    )
    if swing_price is None:
        return None

    # Check structure intact: no new low below swing low since BoS
    for b in range(recent_bos.bar, bar + 1):
        if indicators["lows"][b] < swing_price:
            return None  # structure broken

    # Pullback depth: how close is current close to the swing low zone?
    # Range: BoS broken level → swing low
    range_size = recent_bos.broken_level - swing_price
    if range_size <= 0:
        return None

    # Pullback = how far from the BoS level towards the swing low
    pullback = (recent_bos.broken_level - close) / range_size
    pullback = min(1.0, max(0.0, pullback))

    if pullback < pullback_pct:
        return None  # hasn't pulled back enough

    # Strength: pullback depth * BoS break strength
    strength = min(pullback * recent_bos.break_strength, 3.0)

    dc_fit = _check_dc_geometry(indicators, bar)

    result = _dc_exit_placeholder(close, params)
    result["strength"] = strength
    result["dc_geometry"] = dc_fit
    return result


# ---------------------------------------------------------------------------
# DC Exit Grid — shared across all MS families
# ---------------------------------------------------------------------------

_DC_EXIT_GRID = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 2,
}


# ---------------------------------------------------------------------------
# Hypothesis Dataclass + Registry
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    """A testable trading hypothesis."""
    id: str
    name: str
    family: str
    category: str
    signal_fn: Callable
    param_variants: list[dict]
    description: str


ALL_HYPOTHESES: list[Hypothesis] = [
    # --- Family A: Liquidity Sweep + Reclaim (4 configs) ---
    Hypothesis(
        id="MS-A",
        name="Liquidity Sweep + Reclaim",
        family="liq_sweep",
        category="market_structure",
        signal_fn=signal_liq_sweep_reclaim,
        param_variants=[
            {"label": "base", "swing_lookback": 40, "min_wick_atr": 0.3, "require_green": True, "vol_mult": 1.0, **_DC_EXIT_GRID},
            {"label": "wide", "swing_lookback": 60, "min_wick_atr": 0.5, "require_green": True, "vol_mult": 1.0, **_DC_EXIT_GRID},
            {"label": "vol", "swing_lookback": 40, "min_wick_atr": 0.3, "require_green": True, "vol_mult": 1.5, **_DC_EXIT_GRID},
            {"label": "relax", "swing_lookback": 60, "min_wick_atr": 0.3, "require_green": False, "vol_mult": 1.0, **_DC_EXIT_GRID},
        ],
        description="Price sweeps below swing low then reclaims (stop hunt reversal)",
    ),

    # --- Family B: Fair Value Gap Fill (4 configs) ---
    Hypothesis(
        id="MS-B",
        name="Fair Value Gap Fill",
        family="fvg_fill",
        category="market_structure",
        signal_fn=signal_fvg_fill,
        param_variants=[
            {"label": "base", "max_fvg_age": 20, "fill_depth": 0.50, "rsi_max": 50, **_DC_EXIT_GRID},
            {"label": "norsi", "max_fvg_age": 30, "fill_depth": 0.25, "rsi_max": 0, **_DC_EXIT_GRID},
            {"label": "deep", "max_fvg_age": 20, "fill_depth": 0.75, "rsi_max": 45, **_DC_EXIT_GRID},
            {"label": "wide", "max_fvg_age": 40, "fill_depth": 0.50, "rsi_max": 40, **_DC_EXIT_GRID},
        ],
        description="Price fills unfilled bullish FVG zone (imbalance rebalance)",
    ),

    # --- Family C: Order Block Touch (4 configs) ---
    Hypothesis(
        id="MS-C",
        name="Order Block Touch",
        family="ob_touch",
        category="market_structure",
        signal_fn=signal_ob_touch,
        param_variants=[
            {"label": "base", "max_ob_age": 30, "require_close_in_zone": True, "vol_mult": 1.0, **_DC_EXIT_GRID},
            {"label": "strict", "max_ob_age": 40, "require_close_in_zone": True, "vol_mult": 1.0, **_DC_EXIT_GRID},
            {"label": "vol", "max_ob_age": 30, "require_close_in_zone": False, "vol_mult": 1.5, **_DC_EXIT_GRID},
            {"label": "tight", "max_ob_age": 20, "require_close_in_zone": True, "vol_mult": 1.0, **_DC_EXIT_GRID},
        ],
        description="Price touches bullish order block (institutional demand zone)",
    ),

    # --- Family D: Swing Failure Pattern (3 configs) ---
    Hypothesis(
        id="MS-D",
        name="Swing Failure Pattern",
        family="sfp",
        category="market_structure",
        signal_fn=signal_sfp,
        param_variants=[
            {"label": "base", "swing_lookback": 40, "min_close_strength": 0.50, "vol_mult": 1.0, **_DC_EXIT_GRID},
            {"label": "strict", "swing_lookback": 60, "min_close_strength": 0.60, "vol_mult": 1.5, **_DC_EXIT_GRID},
            {"label": "relax", "swing_lookback": 40, "min_close_strength": 0.40, "vol_mult": 1.0, **_DC_EXIT_GRID},
        ],
        description="False break below swing low with same-bar reclaim (trapped sellers)",
    ),

    # --- Family E: Structure Shift + Pullback (3 configs) ---
    Hypothesis(
        id="MS-E",
        name="Structure Shift + Pullback",
        family="shift_pb",
        category="market_structure",
        signal_fn=signal_structure_shift_pullback,
        param_variants=[
            {"label": "base", "max_bos_age": 15, "pullback_pct": 0.50, "max_pullback_bars": 8, **_DC_EXIT_GRID},
            {"label": "fib618", "max_bos_age": 20, "pullback_pct": 0.618, "max_pullback_bars": 10, **_DC_EXIT_GRID},
            {"label": "shallow", "max_bos_age": 15, "pullback_pct": 0.382, "max_pullback_bars": 6, **_DC_EXIT_GRID},
        ],
        description="Pullback to swing low zone after bullish break of structure",
    ),
]


def get_hypothesis(hypothesis_id: str) -> Hypothesis:
    """Look up a hypothesis by ID."""
    for h in ALL_HYPOTHESES:
        if h.id == hypothesis_id:
            return h
    raise KeyError(f"Unknown hypothesis: {hypothesis_id}")


def build_sweep_configs() -> list[dict]:
    """Build all 18 configs for MS Sprint 1 sweep runner.

    Returns list of dicts with keys:
      idx, id, label, hypothesis_id, hypothesis_name, family, category,
      signal_fn, params, description.
    """
    configs = []
    idx = 0
    for h in ALL_HYPOTHESES:
        for pv in h.param_variants:
            idx += 1
            label = pv.get("label", f"v{idx}")
            configs.append({
                "idx": idx,
                "id": f"ms_{idx:03d}_{h.id.lower().replace('-', '')}_{label}",
                "label": label,
                "hypothesis_id": h.id,
                "hypothesis_name": h.name,
                "family": h.family,
                "category": h.category,
                "signal_fn": h.signal_fn,
                "params": {k: v for k, v in pv.items() if k != "label"},
                "description": f"{h.name} -- {h.description}",
            })
    return configs


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from collections import Counter

    print("=== MS Sprint 1 hypotheses.py self-test ===\n")

    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Count per family
    family_counts = Counter(c["family"] for c in configs)
    for fam, count in sorted(family_counts.items()):
        print(f"    {fam}: {count} variants")

    # --- Check 1: total count ---
    assert len(configs) == 18, f"Expected 18 configs, got {len(configs)}"
    print(f"\n  Check 1: config count = 18 — PASS")

    # --- Check 2: unique IDs ---
    ids = [c["id"] for c in configs]
    assert len(ids) == len(set(ids)), "Duplicate config IDs"
    print(f"  Check 2: unique IDs — PASS")

    # --- Check 3: all signal_fns are callable ---
    for c in configs:
        assert callable(c["signal_fn"]), f"signal_fn not callable for {c['id']}"
    print(f"  Check 3: all signal_fns callable — PASS")

    # --- Check 4: family counts ---
    assert family_counts["liq_sweep"] == 4, "Family A should have 4 configs"
    assert family_counts["fvg_fill"] == 4, "Family B should have 4 configs"
    assert family_counts["ob_touch"] == 4, "Family C should have 4 configs"
    assert family_counts["sfp"] == 3, "Family D should have 3 configs"
    assert family_counts["shift_pb"] == 3, "Family E should have 3 configs"
    print(f"  Check 4: family counts correct — PASS")

    # --- Check 5: all params include DC exit grid ---
    for c in configs:
        p = c["params"]
        assert "max_stop_pct" in p, f"Missing max_stop_pct in {c['id']}"
        assert "time_max_bars" in p, f"Missing time_max_bars in {c['id']}"
        assert "rsi_recovery" in p, f"Missing rsi_recovery in {c['id']}"
    print(f"  Check 5: DC exit grid in all params — PASS")

    # --- Check 6: signal_fn returns None on synthetic empty bar ---
    # All functions should handle missing indicators gracefully
    dummy_ind = {
        "closes": [100.0], "highs": [101.0], "lows": [99.0],
        "opens": [100.0], "volumes": [1000.0],
        "atr": [None], "rsi": [None],
        "dc_mid": [None], "bb_mid": [None],
        "dc_prev_low": [None], "vol_avg": [None],
        "swing_lows": [None], "swing_highs": [None],
        "fvg_snapshots": [[]], "bos_events": [None],
        "ob_snapshots": [[]], "liq_zones": [[]],
    }
    for c in configs:
        result = c["signal_fn"](None, 0, dummy_ind, c["params"])
        assert result is None, f"{c['id']} should return None with empty indicators"
    print(f"  Check 6: all signal_fns return None on empty data — PASS")

    print(f"\n  All 6 self-tests PASSED")
