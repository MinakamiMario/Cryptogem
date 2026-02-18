"""
Sprint 4 -- DC-Compatible Entry Mining: 42 candidate entries across 7 families.

Each signal_fn follows the protocol:
    signal_fn(candles, bar, indicators, params) -> dict | None
    Return: {stop_price, target_price, time_limit, strength} or None

ALL entries enforce DC-compatibility via _check_dc_geometry():
    1. close < dc_mid    (DC TARGET is above entry => profitable)
    2. close < bb_mid    (BB TARGET is above entry => profitable)
    3. rsi < threshold   (RSI RECOVERY exit is reachable)

Families:
    H4S4-A: DC-Lite (relaxed DualConfirm)           -- 7 variants
    H4S4-B: Wick Rejection at Channel Bottom         -- 6 variants
    H4S4-C: BB Squeeze->Expansion at Lows            -- 6 variants
    H4S4-D: Double Bottom / Retest Pattern            -- 6 variants
    H4S4-E: RSI Divergence at Lows                   -- 5 variants
    H4S4-F: Mean Reversion Extreme (z-score)         -- 6 variants
    H4S4-G: Volume Capitulation at Lows              -- 6 variants

Total: 42 configs.

Design principle: stop_price/target_price are PLACEHOLDER values in the return dict.
In DC exit mode the engine IGNORES them and uses max_stop_pct + DC/BB/RSI targets.
strength is used for ranking when multiple entries trigger on the same bar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# DC Geometry gate -- shared by ALL signal functions
# ---------------------------------------------------------------------------

def _check_dc_geometry(indicators: dict, bar: int, rsi_max: float) -> float | None:
    """Verify DC-compatibility: close < dc_mid, close < bb_mid, rsi < threshold.

    Returns geometric_fit score (0-1, higher = deeper in channel) or None if
    the geometry check fails.
    """
    closes = indicators["closes"]
    close = closes[bar]

    dc_mid = indicators["dc_mid"][bar]
    if dc_mid is None or close >= dc_mid:
        return None  # entry NOT below DC midpoint

    bb_mid = indicators["bb_mid"][bar]
    if bb_mid is None or close >= bb_mid:
        return None  # entry NOT below BB midpoint

    rsi = indicators["rsi"][bar]
    if rsi is None or rsi >= rsi_max:
        return None  # RSI not low enough for recovery exit

    # Geometric fit: how deep below dc_mid (0 = at dc_mid, 1 = very deep)
    dc_prev_low = indicators["dc_prev_low"][bar]
    if dc_prev_low is not None and dc_mid > dc_prev_low:
        fit = (dc_mid - close) / (dc_mid - dc_prev_low)
        fit = min(1.0, max(0.0, fit))
    else:
        fit = (dc_mid - close) / dc_mid if dc_mid > 0 else 0.0
        fit = min(1.0, max(0.0, fit))

    return fit


def _dc_exit_placeholder(entry_price: float, params: dict) -> dict:
    """Build placeholder exit dict for DC exit mode.

    stop_price/target_price are ignored by the DC engine but required
    by the signal_fn protocol.
    """
    max_stop_pct = params.get("max_stop_pct", 15.0)
    return {
        "stop_price": entry_price * (1 - max_stop_pct / 100),
        "target_price": entry_price * 1.10,  # placeholder, DC engine overrides
        "time_limit": params.get("time_max_bars", 15),
    }


# ---------------------------------------------------------------------------
# Family A: DC-Lite (Relaxed DualConfirm)
# ---------------------------------------------------------------------------

def signal_dc_lite(candles, bar, indicators, params) -> dict | None:
    """Relaxed DualConfirm entry: relax one or more original DC conditions.

    Original DC requires ALL of:
      dc_low touch, bb_lower touch, rsi<40, green bar, vol_spike>2x, vol_confirm
    DC-Lite keeps the geometry but relaxes individual filters.

    Params:
      rsi_max (float): RSI threshold (default 40)
      require_dc_low (bool): require close <= dc_prev_low (default False)
      require_bb_lower (bool): require close <= bb_lower (default False)
      require_green (bool): require close > prev_close (default True)
      vol_spike_mult (float): volume spike multiplier (default 1.5)
      require_vol_confirm (bool): require vol > prev_vol (default False)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    closes = indicators["closes"]
    close = closes[bar]

    # Optional: dc_low touch
    if params.get("require_dc_low", False):
        dc_prev_low = indicators["dc_prev_low"][bar]
        if dc_prev_low is None:
            return None
        lows = indicators["lows"]
        if lows[bar] > dc_prev_low:
            return None

    # Optional: bb_lower touch
    if params.get("require_bb_lower", False):
        bb_lower = indicators["bb_lower"][bar]
        if bb_lower is None:
            return None
        if close > bb_lower:
            return None

    # Optional: green bar
    if params.get("require_green", True):
        if close <= closes[bar - 1]:
            return None

    # Volume spike
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_spike_mult = params.get("vol_spike_mult", 1.5)
    if cur_vol < vol_avg * vol_spike_mult:
        return None

    # Optional: volume confirmation (vol > prev_vol)
    if params.get("require_vol_confirm", False):
        prev_vol = indicators["volumes"][bar - 1]
        if cur_vol <= prev_vol:
            return None

    exits = _dc_exit_placeholder(close, params)
    vol_ratio = cur_vol / vol_avg
    exits["strength"] = geo * 0.6 + min(vol_ratio / 5.0, 0.4)
    return exits


# ---------------------------------------------------------------------------
# Family B: Wick Rejection at Channel Bottom
# ---------------------------------------------------------------------------

def signal_wick_rejection(candles, bar, indicators, params) -> dict | None:
    """Lower wick rejection at dc_prev_low or bb_lower zone.

    A long lower wick shows buyers stepping in at support.
    No green bar required (the wick IS the rejection signal).

    Params:
      rsi_max (float): RSI threshold (default 40)
      wick_pct (float): minimum lower wick as % of bar range (default 40)
      zone (str): "dc_low" | "bb_lower" | "both" (default "dc_low")
      vol_floor_mult (float): minimum volume vs avg (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    if bar >= len(candles):
        return None
    c = candles[bar]
    o = c.get("open", 0)
    h = c.get("high", 0)
    lo = c.get("low", 0)
    cl = c.get("close", 0)

    bar_range = h - lo
    if bar_range <= 0:
        return None

    # Lower wick = distance from low to min(open, close)
    body_bottom = min(o, cl)
    lower_wick = body_bottom - lo
    wick_pct = params.get("wick_pct", 40)
    if (lower_wick / bar_range) * 100 < wick_pct:
        return None

    # Zone check: wick must reach into dc_low or bb_lower zone
    zone = params.get("zone", "dc_low")
    lows = indicators["lows"]
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    zone_ok = False
    if zone in ("dc_low", "both"):
        dc_prev_low = indicators["dc_prev_low"][bar]
        if dc_prev_low is not None:
            # Low must be within 1 ATR of dc_prev_low
            if lo <= dc_prev_low + atr:
                zone_ok = True
    if zone in ("bb_lower", "both"):
        bb_lower = indicators["bb_lower"][bar]
        if bb_lower is not None:
            if lo <= bb_lower + atr * 0.5:
                zone_ok = True

    if not zone_ok:
        return None

    # Volume floor (not spike -- wick rejection works at normal volume too)
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 0.8)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    close = indicators["closes"][bar]
    exits = _dc_exit_placeholder(close, params)
    wick_strength = lower_wick / bar_range  # 0-1
    exits["strength"] = geo * 0.5 + wick_strength * 0.5
    return exits


# ---------------------------------------------------------------------------
# Family C: BB Squeeze -> Expansion at Lows
# ---------------------------------------------------------------------------

def signal_bb_squeeze_low(candles, bar, indicators, params) -> dict | None:
    """BB width was compressed (squeeze), now expanding, price at lows.

    Squeeze at lows = volatility contraction before a potential reversal.
    Expansion signals the start of a new move; if price is below bb_mid,
    the move should be upward toward the mean.

    Params:
      rsi_max (float): RSI threshold (default 40)
      squeeze_percentile (int): BB width must have been below this percentile (default 30)
      expansion_bars (int): how many bars of expansion required (default 2)
      require_dc_low_zone (bool): require price near dc_prev_low (default False)
      vol_floor_mult (float): minimum volume (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    bb_width = indicators.get("bb_width")
    if bb_width is None or bb_width[bar] is None:
        return None

    squeeze_lookback = 30  # fixed lookback for percentile calculation
    if bar < squeeze_lookback + 5:
        return None

    expansion_bars = params.get("expansion_bars", 2)
    # Need enough history for expansion check
    if bar < expansion_bars + 1:
        return None

    # Check that BB width WAS in squeeze (recent minimum below percentile)
    recent_widths = [bb_width[i] for i in range(bar - squeeze_lookback, bar)
                     if bb_width[i] is not None]
    if len(recent_widths) < squeeze_lookback // 2:
        return None

    sorted_widths = sorted(recent_widths)
    squeeze_percentile = params.get("squeeze_percentile", 30)
    threshold_idx = max(0, int(len(sorted_widths) * squeeze_percentile / 100) - 1)
    squeeze_threshold = sorted_widths[threshold_idx]

    # The minimum width in recent bars must have been below squeeze threshold
    min_recent_width = min(recent_widths[-10:]) if len(recent_widths) >= 10 else min(recent_widths)
    if min_recent_width > squeeze_threshold:
        return None  # no squeeze detected

    # Current width must be EXPANDING (increasing for N bars)
    for i in range(1, expansion_bars + 1):
        prev_idx = bar - i
        if bb_width[prev_idx] is None:
            return None
    # Check expansion: current > bar-1 > bar-2 ...
    for i in range(expansion_bars):
        if bb_width[bar - i] is None or bb_width[bar - i - 1] is None:
            return None
        if bb_width[bar - i] <= bb_width[bar - i - 1]:
            return None  # not expanding

    # Optional: price near dc_prev_low
    if params.get("require_dc_low_zone", False):
        dc_prev_low = indicators["dc_prev_low"][bar]
        atr = indicators["atr"][bar]
        if dc_prev_low is None or atr is None:
            return None
        if indicators["closes"][bar] > dc_prev_low + atr * 1.5:
            return None

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 0.8)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    close = indicators["closes"][bar]
    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + squeeze intensity (lower min = tighter squeeze)
    squeeze_intensity = 1.0 - (min_recent_width / squeeze_threshold) if squeeze_threshold > 0 else 0.0
    squeeze_intensity = max(0.0, min(1.0, squeeze_intensity))
    exits["strength"] = geo * 0.5 + squeeze_intensity * 0.5
    return exits


# ---------------------------------------------------------------------------
# Family D: Double Bottom / Retest Pattern
# ---------------------------------------------------------------------------

def signal_double_bottom(candles, bar, indicators, params) -> dict | None:
    """Price retests a prior low near dc_prev_low (within tolerance ATR).

    Classic double bottom: price hits low, bounces, retests near same level.
    Second test at support with geometry = high-probability reversal.

    Params:
      rsi_max (float): RSI threshold (default 40)
      retest_atr_tolerance (float): max distance from prior low in ATR units (default 1.0)
      min_bars_between (int): minimum bars between first touch and retest (default 5)
      lookback (int): how far back to search for the first low (default 20)
      require_green (bool): require green bar on retest (default True)
      vol_floor_mult (float): minimum volume (default 0.8)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    lookback = params.get("lookback", 20)
    min_bars_between = params.get("min_bars_between", 5)
    if bar < lookback + min_bars_between:
        return None

    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    lows = indicators["lows"]
    closes = indicators["closes"]
    cur_low = lows[bar]

    # Find prior low in lookback window (excluding recent min_bars_between bars)
    search_start = bar - lookback
    search_end = bar - min_bars_between
    if search_start < 0:
        search_start = 0
    if search_end <= search_start:
        return None

    window_lows = lows[search_start:search_end]
    if not window_lows:
        return None
    prior_low = min(window_lows)

    # Retest: current low must be near the prior low
    retest_atr_tolerance = params.get("retest_atr_tolerance", 1.0)
    distance = abs(cur_low - prior_low)
    if distance > atr * retest_atr_tolerance:
        return None

    # Must be near dc_prev_low zone
    dc_prev_low = indicators["dc_prev_low"][bar]
    if dc_prev_low is None:
        return None
    if cur_low > dc_prev_low + atr * 1.5:
        return None  # not at channel bottom

    # Optional green bar
    if params.get("require_green", True):
        if closes[bar] <= closes[bar - 1]:
            return None

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 0.8)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    close = closes[bar]
    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + retest precision (closer retest = stronger)
    retest_precision = 1.0 - (distance / (atr * retest_atr_tolerance)) if atr > 0 else 0.0
    retest_precision = max(0.0, min(1.0, retest_precision))
    exits["strength"] = geo * 0.5 + retest_precision * 0.5
    return exits


# ---------------------------------------------------------------------------
# Family E: RSI Divergence at Lows
# ---------------------------------------------------------------------------

def signal_rsi_divergence(candles, bar, indicators, params) -> dict | None:
    """Bullish RSI divergence: price makes lower low, RSI makes higher low.

    Price must be near dc_prev_low or bb_lower (at channel bottom).
    Divergence signals fading selling pressure at support.

    Params:
      rsi_max (float): RSI threshold (default 40)
      div_lookback (int): how far back to find the prior low for divergence (default 8)
      require_dc_low_zone (bool): price must be near dc_prev_low (default True)
      vol_floor_mult (float): minimum volume (default 0.8)
    """
    if bar < 2:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    div_lookback = params.get("div_lookback", 8)
    if bar < div_lookback + 2:
        return None

    lows = indicators["lows"]
    rsi_arr = indicators["rsi"]
    closes = indicators["closes"]

    cur_low = lows[bar]
    cur_rsi = rsi_arr[bar]
    if cur_rsi is None:
        return None

    # Find a prior swing low in the lookback window
    # Look for bar where low was a local minimum
    search_start = max(0, bar - div_lookback)
    search_end = bar - 2  # at least 2 bars gap

    best_div_score = -1.0
    found_divergence = False

    for i in range(search_start, search_end + 1):
        if rsi_arr[i] is None:
            continue
        # Prior price low must be HIGHER than current low (price made lower low)
        if lows[i] <= cur_low:
            continue  # need price to make LOWER low at current bar
        # Actually: divergence = price lower low, RSI higher low
        # So we need: lows[bar] < lows[i] (current makes lower low)
        #          AND rsi[bar] > rsi[i]  (RSI makes higher low)

    # Re-check: we need price LOWER low + RSI HIGHER low
    for i in range(search_start, search_end + 1):
        if rsi_arr[i] is None:
            continue
        # Price: current low < prior low (lower low)
        if cur_low >= lows[i]:
            continue
        # RSI: current RSI > prior RSI (higher low in RSI)
        if cur_rsi <= rsi_arr[i]:
            continue
        # Found divergence!
        found_divergence = True
        # Score by RSI divergence magnitude
        rsi_div = cur_rsi - rsi_arr[i]
        if rsi_div > best_div_score:
            best_div_score = rsi_div

    if not found_divergence:
        return None

    # Zone check: price near dc_prev_low or bb_lower
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    if params.get("require_dc_low_zone", True):
        dc_prev_low = indicators["dc_prev_low"][bar]
        bb_lower = indicators["bb_lower"][bar]
        zone_ok = False
        if dc_prev_low is not None and cur_low <= dc_prev_low + atr:
            zone_ok = True
        if bb_lower is not None and closes[bar] <= bb_lower + atr * 0.5:
            zone_ok = True
        if not zone_ok:
            return None

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 0.8)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    close = closes[bar]
    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + divergence magnitude
    div_strength = min(best_div_score / 20.0, 1.0)  # normalize RSI div points
    exits["strength"] = geo * 0.5 + div_strength * 0.5
    return exits


# ---------------------------------------------------------------------------
# Family F: Mean Reversion Extreme (z-score based)
# ---------------------------------------------------------------------------

def signal_zscore_extreme(candles, bar, indicators, params) -> dict | None:
    """Extreme z-score entry: close far below SMA20 + below dc_prev_low + bb_lower.

    Pure statistical mean reversion at extreme levels. Z-score measures
    how many standard deviations below the mean the price is.

    Params:
      rsi_max (float): RSI threshold (default 45)
      zscore_threshold (float): minimum negative z-score magnitude (default 2.0)
      require_dc_low (bool): close must be <= dc_prev_low (default True)
      require_bb_lower (bool): close must be <= bb_lower (default False)
      vol_floor_mult (float): minimum volume (default 0.5)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 45)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    closes = indicators["closes"]
    close = closes[bar]

    # Compute z-score: (close - SMA20) / stdev20
    sma20_period = 20
    if bar < sma20_period:
        return None
    window = closes[bar - sma20_period + 1: bar + 1]
    if len(window) < sma20_period:
        return None
    mean = sum(window) / len(window)
    if mean <= 0:
        return None
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    stdev = variance ** 0.5
    if stdev <= 0:
        return None

    zscore = (close - mean) / stdev
    zscore_threshold = params.get("zscore_threshold", 2.0)
    if zscore > -zscore_threshold:
        return None  # not extreme enough

    # Optional: require close <= dc_prev_low
    if params.get("require_dc_low", True):
        dc_prev_low = indicators["dc_prev_low"][bar]
        if dc_prev_low is None:
            return None
        lows = indicators["lows"]
        if lows[bar] > dc_prev_low:
            return None

    # Optional: require close <= bb_lower
    if params.get("require_bb_lower", False):
        bb_lower = indicators["bb_lower"][bar]
        if bb_lower is None:
            return None
        if close > bb_lower:
            return None

    # Volume floor (extreme moves can happen on low volume too)
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 0.5)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + z-score extremeness
    zscore_strength = min(abs(zscore) / 4.0, 1.0)  # normalize: -4.0 = max strength
    exits["strength"] = geo * 0.4 + zscore_strength * 0.6
    return exits


# ---------------------------------------------------------------------------
# Family G: Volume Capitulation at Lows
# ---------------------------------------------------------------------------

def signal_vol_capitulation(candles, bar, indicators, params) -> dict | None:
    """Extreme volume spike at channel bottom (selling climax).

    Capitulation = panic selling with massive volume at support.
    The exhaustion of sellers at lows often precedes sharp reversals.
    Green bar NOT required (capitulation bar is often red; bounce follows).

    Params:
      rsi_max (float): RSI threshold (default 40)
      vol_mult (float): volume spike multiplier (default 3.0)
      require_dc_low_zone (bool): low must be near dc_prev_low (default True)
      require_green (bool): require close > open (default False)
      require_bb_lower (bool): close <= bb_lower (default False)
    """
    if bar < 1:
        return None

    rsi_max = params.get("rsi_max", 40)
    geo = _check_dc_geometry(indicators, bar, rsi_max)
    if geo is None:
        return None

    # Volume spike (extreme)
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 3.0)
    if cur_vol < vol_avg * vol_mult:
        return None

    # Zone check: at channel bottom
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    lows = indicators["lows"]
    closes = indicators["closes"]
    close = closes[bar]

    if params.get("require_dc_low_zone", True):
        dc_prev_low = indicators["dc_prev_low"][bar]
        if dc_prev_low is None:
            return None
        if lows[bar] > dc_prev_low + atr:
            return None

    # Optional: bb_lower check
    if params.get("require_bb_lower", False):
        bb_lower = indicators["bb_lower"][bar]
        if bb_lower is None:
            return None
        if close > bb_lower:
            return None

    # Optional: green bar
    if params.get("require_green", False):
        if bar >= len(candles):
            return None
        c = candles[bar]
        if c.get("close", 0) <= c.get("open", 0):
            return None

    exits = _dc_exit_placeholder(close, params)
    # Strength: geo fit + volume extremeness
    vol_ratio = cur_vol / vol_avg
    vol_strength = min(vol_ratio / 6.0, 1.0)  # normalize: 6x = max strength
    exits["strength"] = geo * 0.4 + vol_strength * 0.6
    return exits


# ---------------------------------------------------------------------------
# Hypothesis registry
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str
    name: str
    family: str
    category: str
    signal_fn: Callable
    param_variants: list[dict]
    description: str


# DC exit grid (shared by all families -- same as Sprint 3)
_DC_TIGHT = {
    "max_stop_pct": 12.0,
    "time_max_bars": 10,
    "rsi_recovery": True,
    "rsi_rec_target": 45,
    "rsi_rec_min_bars": 2,
}

_DC_MEDIUM = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45,
    "rsi_rec_min_bars": 2,
}

_DC_WIDE = {
    "max_stop_pct": 20.0,
    "time_max_bars": 20,
    "rsi_recovery": True,
    "rsi_rec_target": 42,
    "rsi_rec_min_bars": 2,
}

# Use medium as default for all variants (Sprint 3 showed medium balances well)
_DC_DEFAULT = _DC_MEDIUM


def _merge_dc(entry_params: dict, dc_exit: dict | None = None) -> dict:
    """Merge entry params with DC exit params."""
    merged = dict(entry_params)
    dc = dc_exit if dc_exit is not None else _DC_DEFAULT
    merged.update(dc)
    return merged


ALL_HYPOTHESES: list[Hypothesis] = [

    # ===================================================================
    # Family A: DC-Lite (Relaxed DualConfirm) -- 7 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-A01",
        name="DC-Lite RSI40 VolSpike1.5 GreenBar",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "rsi40_vol1.5_green",
            "rsi_max": 40,
            "require_dc_low": False,
            "require_bb_lower": False,
            "require_green": True,
            "vol_spike_mult": 1.5,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="DC geometry + green bar + vol 1.5x. No dc_low/bb_lower touch required.",
    ),
    Hypothesis(
        id="H4S4-A02",
        name="DC-Lite RSI35 VolSpike2.0 GreenBar",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "rsi35_vol2.0_green",
            "rsi_max": 35,
            "require_dc_low": False,
            "require_bb_lower": False,
            "require_green": True,
            "vol_spike_mult": 2.0,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="Tighter RSI + stronger volume, still no dc_low/bb_lower touch.",
    ),
    Hypothesis(
        id="H4S4-A03",
        name="DC-Lite RSI45 VolSpike1.5 NoGreen",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "rsi45_vol1.5_nogreen",
            "rsi_max": 45,
            "require_dc_low": False,
            "require_bb_lower": False,
            "require_green": False,
            "vol_spike_mult": 1.5,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="Wide RSI + no green bar. Maximum trade count, geometry only.",
    ),
    Hypothesis(
        id="H4S4-A04",
        name="DC-Lite DClow RSI40 VolSpike1.5",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "dclow_rsi40_vol1.5",
            "rsi_max": 40,
            "require_dc_low": True,
            "require_bb_lower": False,
            "require_green": True,
            "vol_spike_mult": 1.5,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="Requires dc_low touch (like original DC) but no BB lower touch.",
    ),
    Hypothesis(
        id="H4S4-A05",
        name="DC-Lite BBlow RSI40 VolSpike1.5",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "bblow_rsi40_vol1.5",
            "rsi_max": 40,
            "require_dc_low": False,
            "require_bb_lower": True,
            "require_green": True,
            "vol_spike_mult": 1.5,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="Requires bb_lower touch (like original DC) but no dc_low touch.",
    ),
    Hypothesis(
        id="H4S4-A06",
        name="DC-Lite RSI40 VolSpike2.5 VolConfirm",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "rsi40_vol2.5_volconfirm",
            "rsi_max": 40,
            "require_dc_low": False,
            "require_bb_lower": False,
            "require_green": True,
            "vol_spike_mult": 2.5,
            "require_vol_confirm": True,
            "max_pos": 3,
        })],
        description="Strong volume spike + volume confirmation (vol > prev_vol).",
    ),
    Hypothesis(
        id="H4S4-A07",
        name="DC-Lite DClow+BBlow RSI40 VolSpike1.5",
        family="DC-Lite",
        category="mean_reversion",
        signal_fn=signal_dc_lite,
        param_variants=[_merge_dc({
            "label": "dclow_bblow_rsi40_vol1.5",
            "rsi_max": 40,
            "require_dc_low": True,
            "require_bb_lower": True,
            "require_green": True,
            "vol_spike_mult": 1.5,
            "require_vol_confirm": False,
            "max_pos": 3,
        })],
        description="Both dc_low AND bb_lower touch required. Near-original DC but lower vol threshold.",
    ),

    # ===================================================================
    # Family B: Wick Rejection at Channel Bottom -- 6 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-B01",
        name="Wick Rejection DClow 40pct RSI40",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "dclow_wick40_rsi40",
            "rsi_max": 40,
            "wick_pct": 40,
            "zone": "dc_low",
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="40% lower wick at dc_prev_low zone, RSI<40.",
    ),
    Hypothesis(
        id="H4S4-B02",
        name="Wick Rejection DClow 50pct RSI35",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "dclow_wick50_rsi35",
            "rsi_max": 35,
            "wick_pct": 50,
            "zone": "dc_low",
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Strong 50% wick rejection at dc_low, tighter RSI.",
    ),
    Hypothesis(
        id="H4S4-B03",
        name="Wick Rejection BBlow 40pct RSI40",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "bblow_wick40_rsi40",
            "rsi_max": 40,
            "wick_pct": 40,
            "zone": "bb_lower",
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="40% wick rejection at bb_lower zone.",
    ),
    Hypothesis(
        id="H4S4-B04",
        name="Wick Rejection Both 30pct RSI45",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "both_wick30_rsi45",
            "rsi_max": 45,
            "wick_pct": 30,
            "zone": "both",
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Loose wick (30%) at either dc_low or bb_lower, wide RSI.",
    ),
    Hypothesis(
        id="H4S4-B05",
        name="Wick Rejection DClow 40pct RSI40 HighVol",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "dclow_wick40_rsi40_highvol",
            "rsi_max": 40,
            "wick_pct": 40,
            "zone": "dc_low",
            "vol_floor_mult": 1.5,
            "max_pos": 3,
        })],
        description="Wick rejection at dc_low WITH elevated volume (1.5x).",
    ),
    Hypothesis(
        id="H4S4-B06",
        name="Wick Rejection Both 50pct RSI35",
        family="Wick Rejection",
        category="mean_reversion",
        signal_fn=signal_wick_rejection,
        param_variants=[_merge_dc({
            "label": "both_wick50_rsi35",
            "rsi_max": 35,
            "wick_pct": 50,
            "zone": "both",
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Strong 50% wick at either zone, tight RSI. Maximum selectivity.",
    ),

    # ===================================================================
    # Family C: BB Squeeze -> Expansion at Lows -- 6 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-C01",
        name="BB Squeeze Low P30 Exp2 RSI40",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p30_exp2_rsi40",
            "rsi_max": 40,
            "squeeze_percentile": 30,
            "expansion_bars": 2,
            "require_dc_low_zone": False,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="30th percentile squeeze + 2-bar expansion, RSI<40.",
    ),
    Hypothesis(
        id="H4S4-C02",
        name="BB Squeeze Low P20 Exp3 RSI35",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p20_exp3_rsi35",
            "rsi_max": 35,
            "squeeze_percentile": 20,
            "expansion_bars": 3,
            "require_dc_low_zone": False,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Tight squeeze (20th pct) + 3-bar expansion. Very selective.",
    ),
    Hypothesis(
        id="H4S4-C03",
        name="BB Squeeze Low P40 Exp2 RSI45",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p40_exp2_rsi45",
            "rsi_max": 45,
            "squeeze_percentile": 40,
            "expansion_bars": 2,
            "require_dc_low_zone": False,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Looser squeeze (40th pct), wider RSI. More trades.",
    ),
    Hypothesis(
        id="H4S4-C04",
        name="BB Squeeze Low P30 Exp2 RSI40 DCzone",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p30_exp2_rsi40_dczone",
            "rsi_max": 40,
            "squeeze_percentile": 30,
            "expansion_bars": 2,
            "require_dc_low_zone": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Squeeze at lows + price near dc_prev_low. Tighter zone filter.",
    ),
    Hypothesis(
        id="H4S4-C05",
        name="BB Squeeze Low P30 Exp2 RSI40 HighVol",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p30_exp2_rsi40_highvol",
            "rsi_max": 40,
            "squeeze_percentile": 30,
            "expansion_bars": 2,
            "require_dc_low_zone": False,
            "vol_floor_mult": 1.5,
            "max_pos": 3,
        })],
        description="Squeeze + expansion with volume confirmation (1.5x).",
    ),
    Hypothesis(
        id="H4S4-C06",
        name="BB Squeeze Low P20 Exp2 RSI35 DCzone",
        family="BB Squeeze Low",
        category="mean_reversion",
        signal_fn=signal_bb_squeeze_low,
        param_variants=[_merge_dc({
            "label": "p20_exp2_rsi35_dczone",
            "rsi_max": 35,
            "squeeze_percentile": 20,
            "expansion_bars": 2,
            "require_dc_low_zone": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Tight squeeze + dc_low zone + tight RSI. Maximum selectivity.",
    ),

    # ===================================================================
    # Family D: Double Bottom / Retest -- 6 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-D01",
        name="Double Bottom ATR1.0 MinBars5 RSI40",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr1.0_mb5_rsi40_green",
            "rsi_max": 40,
            "retest_atr_tolerance": 1.0,
            "min_bars_between": 5,
            "lookback": 20,
            "require_green": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Classic double bottom: retest within 1 ATR, 5-bar gap, green bar.",
    ),
    Hypothesis(
        id="H4S4-D02",
        name="Double Bottom ATR0.5 MinBars3 RSI40",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr0.5_mb3_rsi40_green",
            "rsi_max": 40,
            "retest_atr_tolerance": 0.5,
            "min_bars_between": 3,
            "lookback": 15,
            "require_green": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Tight retest tolerance (0.5 ATR), shorter gap. More precise pattern.",
    ),
    Hypothesis(
        id="H4S4-D03",
        name="Double Bottom ATR1.5 MinBars8 RSI45",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr1.5_mb8_rsi45_green",
            "rsi_max": 45,
            "retest_atr_tolerance": 1.5,
            "min_bars_between": 8,
            "lookback": 30,
            "require_green": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Wide retest (1.5 ATR), longer separation. Catches broader patterns.",
    ),
    Hypothesis(
        id="H4S4-D04",
        name="Double Bottom ATR1.0 MinBars5 RSI35",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr1.0_mb5_rsi35_green",
            "rsi_max": 35,
            "retest_atr_tolerance": 1.0,
            "min_bars_between": 5,
            "lookback": 20,
            "require_green": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Same as D01 but tighter RSI. More selective.",
    ),
    Hypothesis(
        id="H4S4-D05",
        name="Double Bottom ATR1.0 MinBars5 RSI40 NoGreen",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr1.0_mb5_rsi40_nogreen",
            "rsi_max": 40,
            "retest_atr_tolerance": 1.0,
            "min_bars_between": 5,
            "lookback": 20,
            "require_green": False,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="No green bar required. Catches retests that close red but hold level.",
    ),
    Hypothesis(
        id="H4S4-D06",
        name="Double Bottom ATR1.0 MinBars5 RSI40 HighVol",
        family="Double Bottom",
        category="mean_reversion",
        signal_fn=signal_double_bottom,
        param_variants=[_merge_dc({
            "label": "atr1.0_mb5_rsi40_highvol",
            "rsi_max": 40,
            "retest_atr_tolerance": 1.0,
            "min_bars_between": 5,
            "lookback": 20,
            "require_green": True,
            "vol_floor_mult": 1.5,
            "max_pos": 3,
        })],
        description="Retest with elevated volume (1.5x) -- volume confirms buyer interest.",
    ),

    # ===================================================================
    # Family E: RSI Divergence at Lows -- 5 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-E01",
        name="RSI Divergence Lookback8 RSI40 DCzone",
        family="RSI Divergence",
        category="mean_reversion",
        signal_fn=signal_rsi_divergence,
        param_variants=[_merge_dc({
            "label": "lb8_rsi40_dczone",
            "rsi_max": 40,
            "div_lookback": 8,
            "require_dc_low_zone": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Bullish RSI divergence over 8 bars, price near dc_prev_low.",
    ),
    Hypothesis(
        id="H4S4-E02",
        name="RSI Divergence Lookback12 RSI35 DCzone",
        family="RSI Divergence",
        category="mean_reversion",
        signal_fn=signal_rsi_divergence,
        param_variants=[_merge_dc({
            "label": "lb12_rsi35_dczone",
            "rsi_max": 35,
            "div_lookback": 12,
            "require_dc_low_zone": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Wider lookback divergence (12 bars), tighter RSI.",
    ),
    Hypothesis(
        id="H4S4-E03",
        name="RSI Divergence Lookback5 RSI40 DCzone",
        family="RSI Divergence",
        category="mean_reversion",
        signal_fn=signal_rsi_divergence,
        param_variants=[_merge_dc({
            "label": "lb5_rsi40_dczone",
            "rsi_max": 40,
            "div_lookback": 5,
            "require_dc_low_zone": True,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Short divergence (5 bars). Fast divergence signal.",
    ),
    Hypothesis(
        id="H4S4-E04",
        name="RSI Divergence Lookback8 RSI45 NoZone",
        family="RSI Divergence",
        category="mean_reversion",
        signal_fn=signal_rsi_divergence,
        param_variants=[_merge_dc({
            "label": "lb8_rsi45_nozone",
            "rsi_max": 45,
            "div_lookback": 8,
            "require_dc_low_zone": False,
            "vol_floor_mult": 0.8,
            "max_pos": 3,
        })],
        description="Divergence without dc_low zone req. Wider RSI. More trades.",
    ),
    Hypothesis(
        id="H4S4-E05",
        name="RSI Divergence Lookback8 RSI40 DCzone HighVol",
        family="RSI Divergence",
        category="mean_reversion",
        signal_fn=signal_rsi_divergence,
        param_variants=[_merge_dc({
            "label": "lb8_rsi40_dczone_highvol",
            "rsi_max": 40,
            "div_lookback": 8,
            "require_dc_low_zone": True,
            "vol_floor_mult": 1.5,
            "max_pos": 3,
        })],
        description="Divergence at dc_low with elevated volume.",
    ),

    # ===================================================================
    # Family F: Mean Reversion Extreme (z-score) -- 6 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-F01",
        name="Z-Score -2.0 DClow RSI45",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z2.0_dclow_rsi45",
            "rsi_max": 45,
            "zscore_threshold": 2.0,
            "require_dc_low": True,
            "require_bb_lower": False,
            "vol_floor_mult": 0.5,
            "max_pos": 3,
        })],
        description="Z-score < -2.0 + dc_low touch. Wide RSI for more signals.",
    ),
    Hypothesis(
        id="H4S4-F02",
        name="Z-Score -2.5 DClow RSI40",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z2.5_dclow_rsi40",
            "rsi_max": 40,
            "zscore_threshold": 2.5,
            "require_dc_low": True,
            "require_bb_lower": False,
            "vol_floor_mult": 0.5,
            "max_pos": 3,
        })],
        description="Deeper z-score (-2.5) + dc_low. More extreme entries.",
    ),
    Hypothesis(
        id="H4S4-F03",
        name="Z-Score -3.0 RSI40",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z3.0_rsi40",
            "rsi_max": 40,
            "zscore_threshold": 3.0,
            "require_dc_low": False,
            "require_bb_lower": False,
            "vol_floor_mult": 0.5,
            "max_pos": 3,
        })],
        description="Extreme z-score (-3.0) only. Very rare, very extreme.",
    ),
    Hypothesis(
        id="H4S4-F04",
        name="Z-Score -2.0 DClow+BBlow RSI40",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z2.0_dclow_bblow_rsi40",
            "rsi_max": 40,
            "zscore_threshold": 2.0,
            "require_dc_low": True,
            "require_bb_lower": True,
            "vol_floor_mult": 0.5,
            "max_pos": 3,
        })],
        description="Z < -2.0 + dc_low + bb_lower. Triple confirmation.",
    ),
    Hypothesis(
        id="H4S4-F05",
        name="Z-Score -2.0 DClow RSI45 HighVol",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z2.0_dclow_rsi45_highvol",
            "rsi_max": 45,
            "zscore_threshold": 2.0,
            "require_dc_low": True,
            "require_bb_lower": False,
            "vol_floor_mult": 1.5,
            "max_pos": 3,
        })],
        description="Z < -2.0 + dc_low + volume spike. Capitulation at extreme.",
    ),
    Hypothesis(
        id="H4S4-F06",
        name="Z-Score -2.5 BBlow RSI40",
        family="Z-Score Extreme",
        category="mean_reversion",
        signal_fn=signal_zscore_extreme,
        param_variants=[_merge_dc({
            "label": "z2.5_bblow_rsi40",
            "rsi_max": 40,
            "zscore_threshold": 2.5,
            "require_dc_low": False,
            "require_bb_lower": True,
            "vol_floor_mult": 0.5,
            "max_pos": 3,
        })],
        description="Z < -2.5 + bb_lower. BB-anchored z-score extreme.",
    ),

    # ===================================================================
    # Family G: Volume Capitulation at Lows -- 6 variants
    # ===================================================================
    Hypothesis(
        id="H4S4-G01",
        name="Vol Capitulation 3x DCzone RSI40",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol3x_dczone_rsi40",
            "rsi_max": 40,
            "vol_mult": 3.0,
            "require_dc_low_zone": True,
            "require_green": False,
            "require_bb_lower": False,
            "max_pos": 3,
        })],
        description="3x volume spike at dc_low zone. No green bar required.",
    ),
    Hypothesis(
        id="H4S4-G02",
        name="Vol Capitulation 4x DCzone RSI40",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol4x_dczone_rsi40",
            "rsi_max": 40,
            "vol_mult": 4.0,
            "require_dc_low_zone": True,
            "require_green": False,
            "require_bb_lower": False,
            "max_pos": 3,
        })],
        description="4x volume spike. Extreme capitulation.",
    ),
    Hypothesis(
        id="H4S4-G03",
        name="Vol Capitulation 5x DCzone RSI35",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol5x_dczone_rsi35",
            "rsi_max": 35,
            "vol_mult": 5.0,
            "require_dc_low_zone": True,
            "require_green": False,
            "require_bb_lower": False,
            "max_pos": 3,
        })],
        description="5x volume spike + tight RSI. Maximum panic selling.",
    ),
    Hypothesis(
        id="H4S4-G04",
        name="Vol Capitulation 3x DCzone RSI40 GreenBar",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol3x_dczone_rsi40_green",
            "rsi_max": 40,
            "vol_mult": 3.0,
            "require_dc_low_zone": True,
            "require_green": True,
            "require_bb_lower": False,
            "max_pos": 3,
        })],
        description="3x vol at dc_low WITH green bar. Capitulation + immediate bounce.",
    ),
    Hypothesis(
        id="H4S4-G05",
        name="Vol Capitulation 3x BBlow RSI40",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol3x_bblow_rsi40",
            "rsi_max": 40,
            "vol_mult": 3.0,
            "require_dc_low_zone": False,
            "require_green": False,
            "require_bb_lower": True,
            "max_pos": 3,
        })],
        description="3x vol + close <= bb_lower. BB-anchored capitulation.",
    ),
    Hypothesis(
        id="H4S4-G06",
        name="Vol Capitulation 4x DCzone+BBlow RSI35",
        family="Volume Capitulation",
        category="mean_reversion",
        signal_fn=signal_vol_capitulation,
        param_variants=[_merge_dc({
            "label": "vol4x_dczone_bblow_rsi35",
            "rsi_max": 35,
            "vol_mult": 4.0,
            "require_dc_low_zone": True,
            "require_green": False,
            "require_bb_lower": True,
            "max_pos": 3,
        })],
        description="4x vol + dc_low + bb_lower. Maximum confirmation capitulation.",
    ),
]


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def get_hypothesis(hypothesis_id: str) -> Hypothesis:
    """Look up a hypothesis by ID."""
    for h in ALL_HYPOTHESES:
        if h.id == hypothesis_id:
            return h
    raise KeyError(f"Unknown hypothesis: {hypothesis_id}. Available: {[h.id for h in ALL_HYPOTHESES]}")


def build_sweep_configs() -> list[dict]:
    """Build all configs for Sprint 4 sweep runner.

    Each hypothesis has 1 param_variant (entry params already merged with DC exits).
    Total: 42 configs across 7 families.

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
                "id": f"sprint4_{idx:03d}_{h.id.lower().replace('-', '')}_{label}",
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

    print("=== Sprint 4 hypotheses.py self-test ===\n")

    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Count per family
    family_counts = Counter(c["family"] for c in configs)
    for fam, count in sorted(family_counts.items()):
        print(f"    {fam}: {count} variants")

    # Count per hypothesis
    hyp_counts = Counter(c["hypothesis_id"] for c in configs)
    print(f"\n  Hypotheses: {len(hyp_counts)}")

    # --- Check 1: target config count ---
    assert 30 <= len(configs) <= 60, f"Expected 30-60 configs, got {len(configs)}"
    print(f"\n  [PASS] {len(configs)} configs (within 30-60 range)")

    # --- Check 2: all IDs unique ---
    ids = [c["id"] for c in configs]
    dupes = [x for x in ids if ids.count(x) > 1]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {dupes}"
    print("  [PASS] All config IDs are unique")

    # --- Check 3: all signal_fn's are callable ---
    for c in configs:
        assert callable(c["signal_fn"]), f"signal_fn not callable in {c['id']}"
    print("  [PASS] All signal_fn's are callable")

    # --- Check 4: DC exit params present in every config ---
    required_dc_keys = {"max_stop_pct", "time_max_bars", "rsi_recovery",
                        "rsi_rec_target", "rsi_rec_min_bars"}
    for c in configs:
        missing = required_dc_keys - set(c["params"].keys())
        assert not missing, f"Missing DC exit keys {missing} in {c['id']}"
    print("  [PASS] All DC exit params present in every config")

    # --- Check 5: all configs have rsi_max ---
    for c in configs:
        assert "rsi_max" in c["params"], f"Missing rsi_max in {c['id']}"
    print("  [PASS] All configs have rsi_max")

    # --- Check 6: all configs have max_pos ---
    for c in configs:
        assert "max_pos" in c["params"], f"Missing max_pos in {c['id']}"
    print("  [PASS] All configs have max_pos")

    # --- Check 7: 7 families ---
    assert len(family_counts) == 7, f"Expected 7 families, got {len(family_counts)}"
    print("  [PASS] 7 families present")

    # --- Print sample ---
    print(f"\n  Sample config (first):")
    sample = configs[0]
    for k, v in sample.items():
        if k == "signal_fn":
            print(f"    {k}: {v.__name__}")
        elif k == "params":
            print(f"    {k}:")
            for pk, pv in sorted(v.items()):
                print(f"      {pk}: {pv}")
        else:
            print(f"    {k}: {v}")

    # --- Print family summary ---
    print(f"\n  Family summary:")
    for fam, count in sorted(family_counts.items()):
        print(f"    {fam}: {count} variants")

    print(f"\n{'='*55}")
    print(f"  ALL CHECKS PASSED ({len(configs)} configs, {len(family_counts)} families)")
