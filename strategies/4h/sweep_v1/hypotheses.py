"""
Sweep v1 — New Edge Discovery: 30 candidate entries across 5 families.

Each signal_fn follows the protocol:
    signal_fn(candles, bar, indicators, params) -> dict | None
    Return: {stop_price, target_price, time_limit, strength} or None

ALL entries enforce DC-compatibility via _check_dc_geometry():
    1. close < dc_mid    (DC TARGET is above entry => profitable)
    2. close < bb_mid    (BB TARGET is above entry => profitable)
    3. rsi < threshold   (RSI RECOVERY exit is reachable)

Families:
    SV1-A: Swing Low Fractal Bounce             -- 6 variants
    SV1-B: Wick Sweep & Reclaim (⭐ top cand)   -- 6 variants
    SV1-C: Trend Pullback to Channel Bottom      -- 6 variants
    SV1-D: ATR Regime Exhaustion                 -- 6 variants
    SV1-E: Cross-Sectional RSI Extreme           -- 6 variants

Total: 30 configs.

Design principle: stop_price/target_price are PLACEHOLDER values in the return dict.
In DC exit mode the engine IGNORES them and uses max_stop_pct + DC/BB/RSI targets.
strength is used for ranking when multiple entries trigger on the same bar.
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reuse DC geometry + exit placeholder from Sprint 4
_sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")
_check_dc_geometry = _sprint4_hyp._check_dc_geometry
_dc_exit_placeholder = _sprint4_hyp._dc_exit_placeholder
Hypothesis = _sprint4_hyp.Hypothesis


# ---------------------------------------------------------------------------
# DC exit defaults (shared by all families)
# ---------------------------------------------------------------------------

_DC_DEFAULT = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45,
    "rsi_rec_min_bars": 2,
}


def _merge_dc(entry_params: dict, dc_exit: dict | None = None) -> dict:
    """Merge entry params with DC exit params."""
    merged = dict(entry_params)
    dc = dc_exit if dc_exit is not None else _DC_DEFAULT
    merged.update(dc)
    return merged


# ===================================================================
# Family A: Swing Low Fractal Bounce (SV1-A, 6 variants)
# ===================================================================

def signal_swing_fractal_bounce(candles, bar, indicators, params) -> dict | None:
    """Confirmed fractal pivot low nearby + DC geometry + volume floor.

    Logic: A confirmed pivot low exists within max_atr_dist ATRs of
    current close, signaling structural support. Entry when price
    bounces near this confirmed support.

    Params:
      rsi_max (float): RSI threshold (default 40)
      pivot_window (int): which pivot_lows key to use (5 or 8, default 5)
      max_atr_dist (float): max distance from pivot in ATR units (default 1.5)
      vol_floor (float): minimum vol/vol_avg ratio (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    # Get the right pivot key based on window param
    pivot_window = params.get("pivot_window", 5)
    pivot_key = f"pivot_lows_{pivot_window}"
    pivot_arr = indicators.get(pivot_key)
    if pivot_arr is None:
        return None

    pivot_price = pivot_arr[bar]
    if pivot_price is None:
        return None  # no confirmed pivot available yet

    # Distance check: close must be within max_atr_dist ATRs of pivot
    close = indicators["closes"][bar]
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    max_atr_dist = params.get("max_atr_dist", 1.5)
    distance = abs(close - pivot_price)
    if distance > atr * max_atr_dist:
        return None

    # Close should be AT or NEAR the pivot (not far above it)
    # Allow close up to max_atr_dist above pivot, but must not be too far below
    if close < pivot_price - atr * 0.5:
        return None  # too far below pivot = breakdown, not bounce

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor = params.get("vol_floor", 0.8)
    if cur_vol < vol_avg * vol_floor:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + proximity to pivot
    proximity = 1.0 - (distance / (atr * max_atr_dist)) if max_atr_dist > 0 else 0.5
    exits["strength"] = geo * 0.5 + proximity * 0.3 + 0.2
    return exits


# ===================================================================
# Family B: Wick Sweep & Reclaim (SV1-B, 6 variants) ⭐ TOP CANDIDATE
# ===================================================================

def signal_wick_sweep_reclaim(candles, bar, indicators, params) -> dict | None:
    """Low sweeps below support then close reclaims above it + DC geometry.

    This is a structural refinement of Vol Capitulation: instead of just
    requiring high volume at lows, it requires the bar to SWEEP below a
    known support level (dc_prev_low or pivot) and then CLOSE back above
    it. This captures liquidity grab patterns.

    Params:
      rsi_max (float): RSI threshold (default 40)
      support_source (str): "dc_low" | "pivot" | "both" (default "dc_low")
      min_sweep_depth (float): min distance below support in ATR (default 0.3)
      min_reclaim_ratio (float): how much of sweep must be reclaimed (default 0.3)
      vol_spike_mult (float): volume spike multiplier (default 1.5)
      pivot_window (int): pivot window for support_source="pivot" (default 5)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    closes = indicators["closes"]
    close = closes[bar]
    low = indicators["lows"][bar]
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    # Find support level
    support_source = params.get("support_source", "dc_low")
    support_price = None

    if support_source in ("dc_low", "both"):
        dc_prev_low = indicators["dc_prev_low"][bar]
        if dc_prev_low is not None:
            support_price = dc_prev_low

    if support_source in ("pivot", "both"):
        pivot_window = params.get("pivot_window", 5)
        pivot_key = f"pivot_lows_{pivot_window}"
        pivot_arr = indicators.get(pivot_key)
        if pivot_arr is not None and pivot_arr[bar] is not None:
            p = pivot_arr[bar]
            if support_price is None or p > support_price:
                # Use higher support (more relevant)
                support_price = p

    if support_price is None:
        return None

    # Sweep check: low must go BELOW support
    min_sweep_depth = params.get("min_sweep_depth", 0.3)
    sweep_depth = support_price - low  # positive if low < support
    if sweep_depth < atr * min_sweep_depth:
        return None  # didn't sweep deep enough

    # Reclaim check: close must be back ABOVE support (or near it)
    min_reclaim_ratio = params.get("min_reclaim_ratio", 0.3)
    total_move = close - low  # how much price recovered from the low
    if total_move <= 0:
        return None
    reclaim = (close - support_price) / total_move if total_move > 0 else 0
    # close > support means reclaim > some threshold of the sweep
    if close < support_price:
        # Close is still below support — check if enough was reclaimed
        recovery_pct = total_move / (support_price - low + total_move) if (support_price - low + total_move) > 0 else 0
        if recovery_pct < min_reclaim_ratio:
            return None
    # If close >= support, the sweep is fully reclaimed — pass

    # Volume check
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_spike_mult = params.get("vol_spike_mult", 1.5)
    if cur_vol < vol_avg * vol_spike_mult:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + sweep depth + volume
    sweep_strength = min(sweep_depth / (atr * 1.0), 1.0)
    vol_ratio = cur_vol / vol_avg
    vol_strength = min(vol_ratio / 5.0, 1.0)
    exits["strength"] = geo * 0.3 + sweep_strength * 0.4 + vol_strength * 0.3
    return exits


# ===================================================================
# Family C: Trend Pullback to Channel Bottom (SV1-C, 6 variants)
# ===================================================================

def signal_trend_pullback(candles, bar, indicators, params) -> dict | None:
    """HH/HL swing structure detected + price pulled back to DC/BB support.

    Logic: If swing structure shows an uptrend (consecutive HH+HL pairs),
    a pullback to the channel bottom is a buy-the-dip opportunity.
    DC geometry ensures we're buying at a discount.

    Params:
      rsi_max (float): RSI threshold (default 40)
      min_hh_hl (int): minimum HH+HL pairs for uptrend (default 1)
      swing_window (int): which swing key to use (5 or 8, default 5)
      pullback_tol (float): max ATR distance from dc_prev_low (default 1.5)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    # Swing structure check
    swing_window = params.get("swing_window", 5)
    swing_key = f"swing_{swing_window}"
    swing_arr = indicators.get(swing_key)
    if swing_arr is None:
        return None

    swing = swing_arr[bar]
    if swing is None:
        return None

    min_hh_hl = params.get("min_hh_hl", 1)
    if swing["hh_hl_count"] < min_hh_hl:
        return None  # not enough trend evidence

    # Only buy in uptrend or at least neutral
    if swing["trend"] == "down":
        return None

    # Pullback to channel bottom check
    close = indicators["closes"][bar]
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    pullback_tol = params.get("pullback_tol", 1.5)

    # Check proximity to dc_prev_low or last swing low
    at_support = False

    dc_prev_low = indicators["dc_prev_low"][bar]
    if dc_prev_low is not None:
        if abs(close - dc_prev_low) <= atr * pullback_tol:
            at_support = True

    # Also check proximity to last swing low
    last_sl_price = swing.get("last_swing_low_price")
    if last_sl_price is not None:
        if abs(close - last_sl_price) <= atr * pullback_tol:
            at_support = True

    if not at_support:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: trend strength + geo fit
    trend_strength = min(swing["hh_hl_count"] / 3.0, 1.0)
    exits["strength"] = geo * 0.4 + trend_strength * 0.4 + 0.2
    return exits


# ===================================================================
# Family D: ATR Regime Exhaustion (SV1-D, 6 variants)
# ===================================================================

def signal_atr_exhaustion(candles, bar, indicators, params) -> dict | None:
    """ATR at low percentile + BB squeeze + price at channel bottom.

    Logic: When ATR reaches historically low levels (contraction regime)
    AND the BB bands squeeze, a breakout is imminent. If price is at the
    bottom of the channel (DC geometry), the breakout should be upward.

    This is a refinement of Sprint 4's BB Squeeze (PF=0.90): adding
    ATR percentile + squeeze duration for more precision.

    Params:
      rsi_max (float): RSI threshold (default 40)
      max_atr_pctile (float): ATR must be below this percentile (default 30)
      min_squeeze_bars (int): minimum consecutive squeeze bars (default 3)
      require_expansion (bool): require BB starting to expand (default False)
      vol_floor (float): minimum vol/vol_avg ratio (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    # ATR percentile check
    atr_pctile = indicators.get("atr_percentile")
    if atr_pctile is None:
        return None
    cur_pctile = atr_pctile[bar]
    if cur_pctile is None:
        return None

    max_atr_pctile = params.get("max_atr_pctile", 30)
    if cur_pctile > max_atr_pctile:
        return None  # ATR not contracted enough

    # BB squeeze duration check
    squeeze_dur = indicators.get("bb_squeeze_dur")
    if squeeze_dur is None:
        return None
    cur_squeeze = squeeze_dur[bar]

    min_squeeze_bars = params.get("min_squeeze_bars", 3)
    if cur_squeeze < min_squeeze_bars:
        return None  # not in squeeze long enough

    # Optional: require expansion starting (squeeze breaking)
    if params.get("require_expansion", False):
        # Squeeze duration should be DECREASING (was higher recently)
        # Or current BB width > previous BB width
        bb_upper = indicators.get("bb_upper")
        bb_lower = indicators.get("bb_lower")
        if bb_upper is None or bb_lower is None:
            return None
        if bar < 2:
            return None
        cur_width = (bb_upper[bar] or 0) - (bb_lower[bar] or 0)
        prev_width = (bb_upper[bar - 1] or 0) - (bb_lower[bar - 1] or 0)
        if cur_width <= prev_width:
            return None  # not expanding yet

    # Volume floor
    close = indicators["closes"][bar]
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor = params.get("vol_floor", 0.8)
    if cur_vol < vol_avg * vol_floor:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: contraction depth + squeeze duration + geo
    contraction = 1.0 - cur_pctile / 100.0  # deeper contraction = stronger
    squeeze_str = min(cur_squeeze / 10.0, 1.0)  # 10+ bars = max
    exits["strength"] = geo * 0.3 + contraction * 0.4 + squeeze_str * 0.3
    return exits


# ===================================================================
# Family E: Cross-Sectional RSI Extreme (SV1-E, 6 variants)
# ===================================================================

def signal_cross_rsi_extreme(candles, bar, indicators, params) -> dict | None:
    """Coin in bottom N% RSI rank across all coins + DC geometry.

    Logic: When a coin's RSI is in the lowest percentile across the
    entire universe, it's relatively more oversold than peers. Combined
    with DC geometry, this selects the most beaten-down coins at
    structural support levels.

    Sprint 2's cross-sectional momentum failed (PF=0.81) but didn't use
    DC exits. With DC exit intelligence, the relative extreme signal
    may generate edge.

    Params:
      rsi_max (float): RSI threshold (default 40)
      max_rsi_pctile (float): coin must be in bottom N% (default 10)
      min_rsi_gap (float): RSI must be N points below median (default 10)
      vol_floor (float): minimum vol/vol_avg ratio (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    # Cross-sectional RSI rank check
    # These are injected into indicators by the sweep runner after
    # precompute_rsi_rank() runs
    rsi_pctile = indicators.get("__rsi_percentile__")
    rsi_median = indicators.get("__rsi_median__")
    if rsi_pctile is None or rsi_median is None:
        return None

    if bar >= len(rsi_pctile):
        return None

    coin_pctile = rsi_pctile[bar]
    if coin_pctile is None:
        return None

    max_rsi_pctile = params.get("max_rsi_pctile", 10)
    if coin_pctile > max_rsi_pctile:
        return None  # not extreme enough relative to peers

    # RSI gap from median
    cur_median = rsi_median[bar]
    if cur_median is None:
        return None
    cur_rsi = indicators["rsi"][bar]
    if cur_rsi is None:
        return None

    min_rsi_gap = params.get("min_rsi_gap", 10)
    gap = cur_median - cur_rsi
    if gap < min_rsi_gap:
        return None  # not enough gap from median

    # Volume floor
    close = indicators["closes"][bar]
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor = params.get("vol_floor", 0.8)
    if cur_vol < vol_avg * vol_floor:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + RSI extremeness + gap magnitude
    extremeness = 1.0 - coin_pctile / 100.0
    gap_strength = min(gap / 25.0, 1.0)  # 25+ point gap = max
    exits["strength"] = geo * 0.3 + extremeness * 0.4 + gap_strength * 0.3
    return exits


# ===================================================================
# Hypothesis Registry
# ===================================================================

ALL_HYPOTHESES: list[Hypothesis] = [

    # -------------------------------------------------------------------
    # Family A: Swing Low Fractal Bounce -- 6 variants
    # -------------------------------------------------------------------
    Hypothesis(
        id="SV1-A01",
        name="SwingFractal RSI35 Pivot5 ATR1.0",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi35_p5_atr1.0",
            "rsi_max": 35,
            "pivot_window": 5,
            "max_atr_dist": 1.0,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Tight RSI, narrow pivot window, close within 1 ATR of pivot.",
    ),
    Hypothesis(
        id="SV1-A02",
        name="SwingFractal RSI40 Pivot5 ATR1.5",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi40_p5_atr1.5",
            "rsi_max": 40,
            "pivot_window": 5,
            "max_atr_dist": 1.5,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Medium RSI, narrow pivot, 1.5 ATR tolerance.",
    ),
    Hypothesis(
        id="SV1-A03",
        name="SwingFractal RSI45 Pivot5 ATR2.0",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi45_p5_atr2.0",
            "rsi_max": 45,
            "pivot_window": 5,
            "max_atr_dist": 2.0,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Wide RSI, narrow pivot, 2 ATR tolerance (max trades).",
    ),
    Hypothesis(
        id="SV1-A04",
        name="SwingFractal RSI35 Pivot8 ATR1.5",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi35_p8_atr1.5",
            "rsi_max": 35,
            "pivot_window": 8,
            "max_atr_dist": 1.5,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Tight RSI, wide pivot window (stronger pivots).",
    ),
    Hypothesis(
        id="SV1-A05",
        name="SwingFractal RSI40 Pivot8 ATR1.0 VolHigh",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi40_p8_atr1.0_volhigh",
            "rsi_max": 40,
            "pivot_window": 8,
            "max_atr_dist": 1.0,
            "vol_floor": 1.5,
            "max_pos": 3,
        })],
        description="Wide pivot, tight distance, high volume floor.",
    ),
    Hypothesis(
        id="SV1-A06",
        name="SwingFractal RSI45 Pivot8 ATR2.0",
        family="SwingFractalBounce",
        category="mean_reversion",
        signal_fn=signal_swing_fractal_bounce,
        param_variants=[_merge_dc({
            "label": "rsi45_p8_atr2.0",
            "rsi_max": 45,
            "pivot_window": 8,
            "max_atr_dist": 2.0,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Wide RSI + wide pivot + wide tolerance (maximum coverage).",
    ),

    # -------------------------------------------------------------------
    # Family B: Wick Sweep & Reclaim -- 6 variants (⭐ top candidate)
    # -------------------------------------------------------------------
    Hypothesis(
        id="SV1-B01",
        name="WickSweep DClow RSI40 Vol1.5 Sweep0.3",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "dclow_rsi40_vol1.5_sw0.3",
            "rsi_max": 40,
            "support_source": "dc_low",
            "min_sweep_depth": 0.3,
            "min_reclaim_ratio": 0.3,
            "vol_spike_mult": 1.5,
            "pivot_window": 5,
            "max_pos": 3,
        })],
        description="Sweep below dc_low, shallow sweep OK, moderate volume.",
    ),
    Hypothesis(
        id="SV1-B02",
        name="WickSweep DClow RSI35 Vol2.0 Sweep0.5",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "dclow_rsi35_vol2.0_sw0.5",
            "rsi_max": 35,
            "support_source": "dc_low",
            "min_sweep_depth": 0.5,
            "min_reclaim_ratio": 0.5,
            "vol_spike_mult": 2.0,
            "pivot_window": 5,
            "max_pos": 3,
        })],
        description="Deep sweep below dc_low, strong volume, tight RSI.",
    ),
    Hypothesis(
        id="SV1-B03",
        name="WickSweep Pivot RSI40 Vol1.5 Sweep0.3",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "pivot_rsi40_vol1.5_sw0.3",
            "rsi_max": 40,
            "support_source": "pivot",
            "min_sweep_depth": 0.3,
            "min_reclaim_ratio": 0.3,
            "vol_spike_mult": 1.5,
            "pivot_window": 5,
            "max_pos": 3,
        })],
        description="Sweep below fractal pivot (not DC). Novel support source.",
    ),
    Hypothesis(
        id="SV1-B04",
        name="WickSweep Both RSI40 Vol2.0 Sweep0.5",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "both_rsi40_vol2.0_sw0.5",
            "rsi_max": 40,
            "support_source": "both",
            "min_sweep_depth": 0.5,
            "min_reclaim_ratio": 0.5,
            "vol_spike_mult": 2.0,
            "pivot_window": 5,
            "max_pos": 3,
        })],
        description="Both dc_low and pivot as support. Deep sweep, strong volume.",
    ),
    Hypothesis(
        id="SV1-B05",
        name="WickSweep DClow RSI45 Vol1.0 Sweep0.3",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "dclow_rsi45_vol1.0_sw0.3",
            "rsi_max": 45,
            "support_source": "dc_low",
            "min_sweep_depth": 0.3,
            "min_reclaim_ratio": 0.3,
            "vol_spike_mult": 1.0,
            "pivot_window": 5,
            "max_pos": 3,
        })],
        description="Wide RSI, low vol threshold — max trade count variant.",
    ),
    Hypothesis(
        id="SV1-B06",
        name="WickSweep Pivot8 RSI35 Vol3.0 Sweep0.5",
        family="WickSweepReclaim",
        category="mean_reversion",
        signal_fn=signal_wick_sweep_reclaim,
        param_variants=[_merge_dc({
            "label": "pivot8_rsi35_vol3.0_sw0.5",
            "rsi_max": 35,
            "support_source": "pivot",
            "min_sweep_depth": 0.5,
            "min_reclaim_ratio": 0.5,
            "vol_spike_mult": 3.0,
            "pivot_window": 8,
            "max_pos": 3,
        })],
        description="Strongest filter: wide pivot, deep sweep, extreme volume.",
    ),

    # -------------------------------------------------------------------
    # Family C: Trend Pullback to Channel Bottom -- 6 variants
    # -------------------------------------------------------------------
    Hypothesis(
        id="SV1-C01",
        name="TrendPullback HH1 Swing5 Tol1.0",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh1_sw5_tol1.0",
            "rsi_max": 40,
            "min_hh_hl": 1,
            "swing_window": 5,
            "pullback_tol": 1.0,
            "max_pos": 3,
        })],
        description="Minimal trend evidence (1 HH+HL), tight pullback tolerance.",
    ),
    Hypothesis(
        id="SV1-C02",
        name="TrendPullback HH2 Swing5 Tol1.5",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh2_sw5_tol1.5",
            "rsi_max": 40,
            "min_hh_hl": 2,
            "swing_window": 5,
            "pullback_tol": 1.5,
            "max_pos": 3,
        })],
        description="Moderate trend (2 HH+HL pairs), moderate pullback.",
    ),
    Hypothesis(
        id="SV1-C03",
        name="TrendPullback HH3 Swing5 Tol2.0",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh3_sw5_tol2.0",
            "rsi_max": 40,
            "min_hh_hl": 3,
            "swing_window": 5,
            "pullback_tol": 2.0,
            "max_pos": 3,
        })],
        description="Strong trend (3 HH+HL), wide pullback — strictest trend filter.",
    ),
    Hypothesis(
        id="SV1-C04",
        name="TrendPullback HH1 Swing8 Tol1.5",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh1_sw8_tol1.5",
            "rsi_max": 45,
            "min_hh_hl": 1,
            "swing_window": 8,
            "pullback_tol": 1.5,
            "max_pos": 3,
        })],
        description="Wide swing window (stronger structure), wide RSI.",
    ),
    Hypothesis(
        id="SV1-C05",
        name="TrendPullback HH2 Swing8 Tol1.0 RSI35",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh2_sw8_tol1.0_rsi35",
            "rsi_max": 35,
            "min_hh_hl": 2,
            "swing_window": 8,
            "pullback_tol": 1.0,
            "max_pos": 3,
        })],
        description="Tight RSI + wide swing + tight pullback = high conviction.",
    ),
    Hypothesis(
        id="SV1-C06",
        name="TrendPullback HH1 Swing5 Tol2.0 RSI45",
        family="TrendPullback",
        category="trend_following",
        signal_fn=signal_trend_pullback,
        param_variants=[_merge_dc({
            "label": "hh1_sw5_tol2.0_rsi45",
            "rsi_max": 45,
            "min_hh_hl": 1,
            "swing_window": 5,
            "pullback_tol": 2.0,
            "max_pos": 3,
        })],
        description="Wide RSI + wide pullback = max trade count.",
    ),

    # -------------------------------------------------------------------
    # Family D: ATR Regime Exhaustion -- 6 variants
    # -------------------------------------------------------------------
    Hypothesis(
        id="SV1-D01",
        name="ATRExhaust Pctile20 Squeeze3",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile20_sq3",
            "rsi_max": 40,
            "max_atr_pctile": 20,
            "min_squeeze_bars": 3,
            "require_expansion": False,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Strict contraction (bottom 20%), moderate squeeze.",
    ),
    Hypothesis(
        id="SV1-D02",
        name="ATRExhaust Pctile30 Squeeze5",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile30_sq5",
            "rsi_max": 40,
            "max_atr_pctile": 30,
            "min_squeeze_bars": 5,
            "require_expansion": False,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Moderate contraction, longer squeeze required.",
    ),
    Hypothesis(
        id="SV1-D03",
        name="ATRExhaust Pctile40 Squeeze3 Expand",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile40_sq3_expand",
            "rsi_max": 40,
            "max_atr_pctile": 40,
            "min_squeeze_bars": 3,
            "require_expansion": True,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Wider contraction, requires expansion starting.",
    ),
    Hypothesis(
        id="SV1-D04",
        name="ATRExhaust Pctile20 Squeeze8 RSI35",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile20_sq8_rsi35",
            "rsi_max": 35,
            "max_atr_pctile": 20,
            "min_squeeze_bars": 8,
            "require_expansion": False,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Extreme contraction + long squeeze + tight RSI.",
    ),
    Hypothesis(
        id="SV1-D05",
        name="ATRExhaust Pctile30 Squeeze5 Expand RSI45",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile30_sq5_expand_rsi45",
            "rsi_max": 45,
            "max_atr_pctile": 30,
            "min_squeeze_bars": 5,
            "require_expansion": True,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Expansion + wide RSI — timing the breakout start.",
    ),
    Hypothesis(
        id="SV1-D06",
        name="ATRExhaust Pctile30 Squeeze3 VolHigh",
        family="ATRExhaustion",
        category="mean_reversion",
        signal_fn=signal_atr_exhaustion,
        param_variants=[_merge_dc({
            "label": "pctile30_sq3_volhigh",
            "rsi_max": 40,
            "max_atr_pctile": 30,
            "min_squeeze_bars": 3,
            "require_expansion": False,
            "vol_floor": 1.5,
            "max_pos": 3,
        })],
        description="Volume surge during contraction — smart money positioning.",
    ),

    # -------------------------------------------------------------------
    # Family E: Cross-Sectional RSI Extreme -- 6 variants
    # -------------------------------------------------------------------
    Hypothesis(
        id="SV1-E01",
        name="CrossRSI Pctile5 Gap10",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile5_gap10",
            "rsi_max": 40,
            "max_rsi_pctile": 5,
            "min_rsi_gap": 10,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Bottom 5% RSI rank, 10pt gap from median.",
    ),
    Hypothesis(
        id="SV1-E02",
        name="CrossRSI Pctile10 Gap10",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile10_gap10",
            "rsi_max": 40,
            "max_rsi_pctile": 10,
            "min_rsi_gap": 10,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Bottom 10% RSI, moderate gap. Balance of trades/quality.",
    ),
    Hypothesis(
        id="SV1-E03",
        name="CrossRSI Pctile15 Gap15",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile15_gap15",
            "rsi_max": 45,
            "max_rsi_pctile": 15,
            "min_rsi_gap": 15,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Wider percentile + wider gap + wider RSI.",
    ),
    Hypothesis(
        id="SV1-E04",
        name="CrossRSI Pctile10 Gap5 RSI35",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile10_gap5_rsi35",
            "rsi_max": 35,
            "max_rsi_pctile": 10,
            "min_rsi_gap": 5,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Tight RSI, loose gap — rank-dominant variant.",
    ),
    Hypothesis(
        id="SV1-E05",
        name="CrossRSI Pctile20 Gap5 VolHigh",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile20_gap5_volhigh",
            "rsi_max": 40,
            "max_rsi_pctile": 20,
            "min_rsi_gap": 5,
            "vol_floor": 1.5,
            "max_pos": 3,
        })],
        description="Wide percentile but requires volume surge.",
    ),
    Hypothesis(
        id="SV1-E06",
        name="CrossRSI Pctile5 Gap15 RSI35",
        family="CrossRSIExtreme",
        category="mean_reversion",
        signal_fn=signal_cross_rsi_extreme,
        param_variants=[_merge_dc({
            "label": "pctile5_gap15_rsi35",
            "rsi_max": 35,
            "max_rsi_pctile": 5,
            "min_rsi_gap": 15,
            "vol_floor": 0.8,
            "max_pos": 3,
        })],
        description="Most extreme filter: bottom 5%, 15pt gap, tight RSI.",
    ),
]


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def build_sweep_configs() -> list[dict]:
    """Build all configs for Sweep v1 sweep runner.

    Each hypothesis has 1 param_variant (entry params already merged with DC exits).
    Total: 30 configs across 5 families.

    Returns list of dicts with keys:
      id, idx, label, hypothesis_id, hypothesis_name, family, category,
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
                "id": f"sweep_v1_{idx:03d}_{h.id.lower().replace('-', '')}_{label}",
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
# Quick validation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    configs = build_sweep_configs()
    print(f"Sweep v1 Hypotheses: {len(ALL_HYPOTHESES)} hypotheses, {len(configs)} configs")

    # Count per family
    from collections import Counter
    family_counts = Counter(c["family"] for c in configs)
    for fam, cnt in sorted(family_counts.items()):
        print(f"  {fam}: {cnt} configs")

    # Verify all have DC exit params
    for c in configs:
        p = c["params"]
        assert "max_stop_pct" in p, f"{c['id']} missing max_stop_pct"
        assert "time_max_bars" in p, f"{c['id']} missing time_max_bars"
        assert "rsi_recovery" in p, f"{c['id']} missing rsi_recovery"
        assert "rsi_rec_target" in p, f"{c['id']} missing rsi_rec_target"
        assert "rsi_rec_min_bars" in p, f"{c['id']} missing rsi_rec_min_bars"
        assert callable(c["signal_fn"]), f"{c['id']} signal_fn not callable"

    # Verify unique IDs
    ids = [c["id"] for c in configs]
    assert len(ids) == len(set(ids)), f"Duplicate config IDs found!"

    print(f"\n  All {len(configs)} configs validated: DC params present, unique IDs, callable signal_fn.")
