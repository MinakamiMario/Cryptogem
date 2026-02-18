"""DC-Compatibility Scorer — Sprint 4.

Scores entry bars for geometric compatibility with DualConfirm exits
(hybrid_notrl: FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET).

An entry is "DC-compatible" when:
  - Entry price << dc_mid  → room for DC TARGET to trigger profitably
  - Entry price << bb_mid  → room for BB TARGET to trigger profitably
  - RSI at entry < ~40     → room for RSI RECOVERY to trigger
  - Stop distance reasonable → FIXED STOP isn't too tight or too loose
  - Price at structural low → natural bounce toward midpoints

Sprint 3 proved: arbitrary entries + DC exits = 0 GO.
DualConfirm is indivisible — entry and exit are co-dependent.
This scorer quantifies HOW co-dependent, so we can pre-filter entries.

All indicator keys match Sprint 1 indicators.py:
  closes, highs, lows, volumes, rsi, atr, dc_prev_low, dc_mid,
  bb_mid, bb_lower, vol_avg, n
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Constants (parity with Sprint 1 engine)
# ---------------------------------------------------------------------------
KRAKEN_FEE = 0.0026  # per-side, must match engine
DC_PERIOD = 20       # Donchian lookback

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------
WEIGHTS = {
    "dc_distance":   0.20,   # Most important: dc_mid must be above
    "bb_distance":   0.15,   # BB target reachability
    "rsi_headroom":  0.15,   # RSI recovery exit viability
    "channel_pos":   0.20,   # Entry at bottom of range
    "atr_regime":    0.10,   # Volatility for target reach
    "wick_structure": 0.10,  # Bounce confirmation
    "volume_surge":  0.10,   # Buying power
}
# Sanity: weights sum to 1.0
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"Weights sum to {sum(WEIGHTS.values())}, expected 1.0"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class CompatScore:
    """Result of scoring one entry bar for DC-exit compatibility."""
    composite: float                   # 0-1 weighted composite
    features: dict[str, float]         # individual feature scores (0-1 each)
    hard_pass: bool                    # True if passes all hard filters
    disqualify_reason: Optional[str]   # Why hard filter failed, or None


# ---------------------------------------------------------------------------
# Feature scoring functions
# ---------------------------------------------------------------------------

def _f1_dc_distance(close: float, dc_mid: Optional[float]) -> float:
    """DC Distance Score: how far below dc_mid is the entry?

    0 if close >= dc_mid or dc_mid unavailable.
    Linear 0→1 as distance increases up to 15%.
    """
    if dc_mid is None or dc_mid <= 0 or close >= dc_mid:
        return 0.0
    dc_distance = (dc_mid - close) / close
    return min(1.0, max(0.0, dc_distance / 0.15))


def _f2_bb_distance(close: float, bb_mid: Optional[float]) -> float:
    """BB Distance Score: how far below bb_mid is the entry?

    0 if close >= bb_mid or bb_mid unavailable.
    Linear 0→1 as distance increases up to 10%.
    """
    if bb_mid is None or bb_mid <= 0 or close >= bb_mid:
        return 0.0
    bb_distance = (bb_mid - close) / close
    return min(1.0, max(0.0, bb_distance / 0.10))


def _f3_rsi_headroom(rsi: Optional[float]) -> float:
    """RSI Headroom Score: lower RSI = more room for RSI recovery exit.

    1.0 if RSI <= 25, 0.0 if RSI >= 50, linear between.
    0.0 if RSI unavailable.
    """
    if rsi is None:
        return 0.0
    return max(0.0, min(1.0, (50.0 - rsi) / 25.0))


def _f4_channel_position(
    close: float,
    low: float,
    high: float,
    highs_series: Optional[list[float]] = None,
    lows_series: Optional[list[float]] = None,
    bar: Optional[int] = None,
    dc_prev_low: Optional[float] = None,
) -> float:
    """Channel Position Score: where in the 20-bar range did entry happen?

    channel_pos = (close - dc_low) / (dc_high - dc_low)
    0 = at channel bottom, 1 = at channel top.
    Score: 1.0 at bottom, 0.0 at midpoint, clamped to [0, 1].

    Uses dc_prev_low from indicators when available. Computes dc_high from
    highs_series when available, otherwise falls back to the entry bar's high.
    """
    # Determine dc_low
    dc_low = dc_prev_low

    # Determine dc_high from highs series if possible
    dc_high = None
    if highs_series is not None and bar is not None and bar >= DC_PERIOD:
        window_h = highs_series[bar - DC_PERIOD: bar]
        if window_h:
            dc_high = max(window_h)

    # Fallback: use the bar's own high (weaker but acceptable)
    if dc_high is None:
        dc_high = high
    if dc_low is None:
        dc_low = low

    channel_range = dc_high - dc_low
    if channel_range <= 0:
        return 0.5  # flat channel, neutral score

    channel_pos = (close - dc_low) / channel_range
    score = max(0.0, 1.0 - channel_pos * 2.0)
    return min(1.0, score)


def _f5_atr_regime(close: float, atr: Optional[float]) -> float:
    """ATR Regime Score: higher ATR/price = more volatile = targets reachable.

    0 if atr_pct < 1%, linear to 1.0 at atr_pct >= 5%.
    0.0 if atr unavailable or close <= 0.
    """
    if atr is None or close <= 0:
        return 0.0
    atr_pct = atr / close * 100.0
    return min(1.0, max(0.0, (atr_pct - 1.0) / 4.0))


def _f6_wick_structure(close: float, low: float, high: float) -> float:
    """Wick Structure Score: lower wick shows rejection at lows.

    wick_ratio = (close - low) / (high - low)
    0 if no range, up to 1.0 for strong lower wick (>=60% of range).
    """
    bar_range = high - low
    if bar_range <= 0:
        return 0.0
    wick_ratio = (close - low) / bar_range
    return min(1.0, max(0.0, wick_ratio / 0.6))


def _f7_volume_surge(vol: float, vol_avg: Optional[float]) -> float:
    """Volume Surge Score: volume relative to average.

    0 if vol_ratio < 1, linear to 1.0 at vol_ratio >= 3.
    0.0 if vol_avg unavailable or <= 0.
    """
    if vol_avg is None or vol_avg <= 0:
        return 0.0
    vol_ratio = vol / vol_avg
    return min(1.0, max(0.0, (vol_ratio - 1.0) / 2.0))


# ---------------------------------------------------------------------------
# Hard filter checks
# ---------------------------------------------------------------------------

def _check_hard_filters(
    close: float,
    dc_mid: Optional[float],
    bb_mid: Optional[float],
    rsi: Optional[float],
) -> Optional[str]:
    """Check hard disqualification filters.

    Returns disqualify reason string, or None if all filters pass.
    """
    if dc_mid is not None and close >= dc_mid:
        return f"close ({close:.4f}) >= dc_mid ({dc_mid:.4f}): entry above DC target"
    if bb_mid is not None and close >= bb_mid:
        return f"close ({close:.4f}) >= bb_mid ({bb_mid:.4f}): entry above BB target"
    if rsi is not None and rsi >= 55.0:
        return f"RSI ({rsi:.1f}) >= 55: no RSI recovery headroom"
    return None


# ---------------------------------------------------------------------------
# Main scoring API
# ---------------------------------------------------------------------------

def score_entry(
    *,
    close: float,
    low: float,
    high: float,
    rsi: Optional[float],
    atr: Optional[float],
    dc_mid: Optional[float],
    dc_prev_low: Optional[float],
    bb_mid: Optional[float],
    vol: float,
    vol_avg: Optional[float],
    # Optional: for better channel position scoring
    highs_series: Optional[list[float]] = None,
    bar: Optional[int] = None,
) -> CompatScore:
    """Score a single entry bar for DC-exit compatibility.

    Parameters
    ----------
    close, low, high : float
        Entry bar OHLC (open not needed).
    rsi : float or None
        RSI(14) at entry bar.
    atr : float or None
        ATR(14) at entry bar.
    dc_mid : float or None
        Donchian channel midpoint at entry bar (exit target level).
    dc_prev_low : float or None
        Donchian previous-bar low (causal entry trigger level).
    bb_mid : float or None
        Bollinger Band midpoint at entry bar (exit target level).
    vol : float
        Volume of entry bar.
    vol_avg : float or None
        Average volume (20-bar) at entry bar.
    highs_series : list[float] or None
        Full highs array for the coin (for computing dc_high for channel pos).
    bar : int or None
        Bar index in the series (for computing dc_high window).

    Returns
    -------
    CompatScore
        Composite score, individual features, hard filter result.
    """
    # --- Hard filters ---
    disqualify = _check_hard_filters(close, dc_mid, bb_mid, rsi)
    if disqualify is not None:
        # All features still computed for diagnostics, but composite = 0
        features = {
            "dc_distance":   _f1_dc_distance(close, dc_mid),
            "bb_distance":   _f2_bb_distance(close, bb_mid),
            "rsi_headroom":  _f3_rsi_headroom(rsi),
            "channel_pos":   _f4_channel_position(close, low, high, highs_series, None, bar, dc_prev_low),
            "atr_regime":    _f5_atr_regime(close, atr),
            "wick_structure": _f6_wick_structure(close, low, high),
            "volume_surge":  _f7_volume_surge(vol, vol_avg),
        }
        return CompatScore(
            composite=0.0,
            features=features,
            hard_pass=False,
            disqualify_reason=disqualify,
        )

    # --- Feature scores ---
    features = {
        "dc_distance":   _f1_dc_distance(close, dc_mid),
        "bb_distance":   _f2_bb_distance(close, bb_mid),
        "rsi_headroom":  _f3_rsi_headroom(rsi),
        "channel_pos":   _f4_channel_position(close, low, high, highs_series, None, bar, dc_prev_low),
        "atr_regime":    _f5_atr_regime(close, atr),
        "wick_structure": _f6_wick_structure(close, low, high),
        "volume_surge":  _f7_volume_surge(vol, vol_avg),
    }

    # --- Composite ---
    composite = sum(WEIGHTS[k] * features[k] for k in WEIGHTS)

    return CompatScore(
        composite=composite,
        features=features,
        hard_pass=True,
        disqualify_reason=None,
    )


# ---------------------------------------------------------------------------
# Hypothesis-level scoring
# ---------------------------------------------------------------------------

def score_hypothesis_entries(
    data: dict,
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    *,
    start_bar: int = 50,
) -> dict:
    """Score ALL entries that a hypothesis would generate across all coins.

    Runs the signal_fn over every coin and bar, and for each triggered entry,
    computes its DC-compatibility score.

    Parameters
    ----------
    data : dict
        Candle cache: {pair: [candle_dicts]}.
    coins : list[str]
        Universe of coins to scan.
    signal_fn : callable
        (candles, bar, indicators, params) -> dict|None
        Same protocol as Sprint 1 engine.
    params : dict
        Hypothesis parameters.
    indicators : dict
        Precomputed indicators: {pair: {rsi, atr, dc_mid, dc_prev_low,
        bb_mid, vol_avg, closes, highs, lows, volumes, n, ...}}.
    start_bar : int
        First bar to evaluate (default 50, parity with engine).

    Returns
    -------
    dict with keys:
        total_entries: int
        passing_entries: int   (hard_pass = True)
        avg_composite: float
        avg_features: dict[str, float]
        median_composite: float
        top_quartile_composite: float
        entries: list[dict]    (per-entry details)
    """
    entries: list[dict] = []

    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue
        n = ind["n"]
        candles = data.get(pair, [])

        for bar in range(start_bar, n):
            sig = signal_fn(candles, bar, ind, params)
            if sig is None:
                continue

            close = ind["closes"][bar]
            low_val = ind["lows"][bar]
            high_val = ind["highs"][bar]

            rsi_val = ind["rsi"][bar] if "rsi" in ind else None
            atr_val = ind["atr"][bar] if "atr" in ind else None
            dc_mid_val = ind["dc_mid"][bar] if "dc_mid" in ind else None
            dc_prev_low_val = ind["dc_prev_low"][bar] if "dc_prev_low" in ind else None
            bb_mid_val = ind["bb_mid"][bar] if "bb_mid" in ind else None
            vol_val = ind["volumes"][bar] if "volumes" in ind else 0.0
            vol_avg_val = ind["vol_avg"][bar] if "vol_avg" in ind else None

            sc = score_entry(
                close=close,
                low=low_val,
                high=high_val,
                rsi=rsi_val,
                atr=atr_val,
                dc_mid=dc_mid_val,
                dc_prev_low=dc_prev_low_val,
                bb_mid=bb_mid_val,
                vol=vol_val,
                vol_avg=vol_avg_val,
                highs_series=ind.get("highs"),
                bar=bar,
            )

            entries.append({
                "pair": pair,
                "bar": bar,
                "close": close,
                "composite": sc.composite,
                "hard_pass": sc.hard_pass,
                "disqualify_reason": sc.disqualify_reason,
                "features": sc.features,
            })

    # --- Aggregate statistics ---
    total = len(entries)
    passing = [e for e in entries if e["hard_pass"]]
    n_passing = len(passing)

    if n_passing > 0:
        composites = [e["composite"] for e in passing]
        avg_composite = sum(composites) / len(composites)
        median_composite = median(composites)

        sorted_comp = sorted(composites, reverse=True)
        q1_idx = max(1, len(sorted_comp) // 4)
        top_quartile = sum(sorted_comp[:q1_idx]) / q1_idx

        # Average per-feature scores (passing entries only)
        avg_features = {}
        for key in WEIGHTS:
            vals = [e["features"][key] for e in passing]
            avg_features[key] = sum(vals) / len(vals)
    else:
        avg_composite = 0.0
        median_composite = 0.0
        top_quartile = 0.0
        avg_features = {k: 0.0 for k in WEIGHTS}

    return {
        "total_entries": total,
        "passing_entries": n_passing,
        "avg_composite": round(avg_composite, 4),
        "avg_features": {k: round(v, 4) for k, v in avg_features.items()},
        "median_composite": round(median_composite, 4),
        "top_quartile_composite": round(top_quartile, 4),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Running compat_scorer self-tests...\n")

    # ---- Test 1: Perfect DC-compatible entry ----
    s1 = score_entry(
        close=90, low=88, high=95, rsi=30, atr=5,
        dc_mid=100, dc_prev_low=89, bb_mid=98, vol=300, vol_avg=100,
    )
    assert s1.hard_pass, f"Expected hard_pass=True, got {s1.hard_pass}"
    assert s1.disqualify_reason is None
    assert s1.composite > 0.7, f"Expected composite > 0.7, got {s1.composite:.4f}"
    print(f"  Test 1 PASS: perfect entry → composite={s1.composite:.4f}, hard_pass={s1.hard_pass}")
    for k, v in s1.features.items():
        print(f"    {k}: {v:.4f}")

    # ---- Test 2: Incompatible entry (above dc_mid) ----
    s2 = score_entry(
        close=105, low=100, high=110, rsi=60, atr=3,
        dc_mid=100, dc_prev_low=95, bb_mid=102, vol=80, vol_avg=100,
    )
    assert not s2.hard_pass, f"Expected hard_pass=False, got {s2.hard_pass}"
    assert s2.composite == 0.0
    assert s2.disqualify_reason is not None
    print(f"  Test 2 PASS: above dc_mid → composite=0.0, reason={s2.disqualify_reason}")

    # ---- Test 3: Above bb_mid but below dc_mid ----
    s3 = score_entry(
        close=99, low=97, high=101, rsi=35, atr=4,
        dc_mid=110, dc_prev_low=95, bb_mid=98, vol=120, vol_avg=100,
    )
    assert not s3.hard_pass, f"Expected hard_pass=False (above bb_mid)"
    assert "bb_mid" in s3.disqualify_reason
    print(f"  Test 3 PASS: above bb_mid → composite=0.0, reason={s3.disqualify_reason}")

    # ---- Test 4: RSI too high ----
    s4 = score_entry(
        close=85, low=83, high=90, rsi=56, atr=5,
        dc_mid=100, dc_prev_low=82, bb_mid=95, vol=200, vol_avg=100,
    )
    assert not s4.hard_pass, f"Expected hard_pass=False (RSI >= 55)"
    assert "RSI" in s4.disqualify_reason
    print(f"  Test 4 PASS: RSI too high → composite=0.0, reason={s4.disqualify_reason}")

    # ---- Test 5: Marginal entry (just barely passing) ----
    s5 = score_entry(
        close=99, low=98, high=101, rsi=48, atr=1.5,
        dc_mid=100, dc_prev_low=97, bb_mid=100.5, vol=110, vol_avg=100,
    )
    assert s5.hard_pass, f"Expected hard_pass=True for marginal entry"
    assert s5.composite < 0.3, f"Expected low composite for marginal entry, got {s5.composite:.4f}"
    print(f"  Test 5 PASS: marginal entry → composite={s5.composite:.4f}")

    # ---- Test 6: None indicators (missing data) ----
    s6 = score_entry(
        close=90, low=88, high=95, rsi=None, atr=None,
        dc_mid=None, dc_prev_low=None, bb_mid=None, vol=100, vol_avg=None,
    )
    # No hard filters should trigger when indicators are None (can't prove incompatibility)
    assert s6.hard_pass, "None indicators should pass hard filters (can't disprove compatibility)"
    assert s6.composite >= 0.0
    print(f"  Test 6 PASS: None indicators → composite={s6.composite:.4f}, hard_pass={s6.hard_pass}")

    # ---- Test 7: Feature value ranges ----
    # All features should be in [0, 1]
    for test_name, sc in [("s1", s1), ("s2", s2), ("s3", s3), ("s4", s4), ("s5", s5), ("s6", s6)]:
        for k, v in sc.features.items():
            assert 0.0 <= v <= 1.0, f"{test_name}.features[{k}] = {v} out of [0,1]"
    print("  Test 7 PASS: all feature values in [0, 1]")

    # ---- Test 8: Composite is weighted sum ----
    expected = sum(WEIGHTS[k] * s1.features[k] for k in WEIGHTS)
    assert abs(s1.composite - expected) < 1e-9, f"Composite mismatch: {s1.composite} != {expected}"
    print(f"  Test 8 PASS: composite = weighted sum ({expected:.4f})")

    # ---- Test 9: Individual feature function spot checks ----
    # F1: dc_distance
    assert _f1_dc_distance(90, 100) > 0.7   # 11.1% distance
    assert _f1_dc_distance(100, 100) == 0.0  # at dc_mid
    assert _f1_dc_distance(110, 100) == 0.0  # above dc_mid
    assert _f1_dc_distance(90, None) == 0.0  # missing

    # F3: rsi_headroom
    assert _f3_rsi_headroom(25) == 1.0
    assert _f3_rsi_headroom(50) == 0.0
    assert abs(_f3_rsi_headroom(37.5) - 0.5) < 1e-9
    assert _f3_rsi_headroom(None) == 0.0

    # F5: atr_regime
    assert _f5_atr_regime(100, 5) == 1.0    # 5% atr
    assert _f5_atr_regime(100, 1) == 0.0    # 1% atr (boundary)
    assert _f5_atr_regime(100, 0.5) == 0.0  # below 1%

    # F7: volume_surge
    assert _f7_volume_surge(300, 100) == 1.0  # 3x = max
    assert _f7_volume_surge(100, 100) == 0.0  # 1x = no surge
    assert _f7_volume_surge(50, 100) == 0.0   # below avg
    assert _f7_volume_surge(200, 100) == 0.5  # 2x = midpoint
    print("  Test 9 PASS: individual feature spot checks")

    # ---- Test 10: score_hypothesis_entries with dummy data ----
    dummy_data = {
        "TEST/USD": [
            {"close": 100 - i * 0.5, "high": 102 - i * 0.3, "low": 98 - i * 0.6,
             "volume": 100 + i * 10}
            for i in range(100)
        ]
    }
    # Build minimal indicators
    import sys as _sys
    from pathlib import Path as _Path
    _repo = _Path(__file__).resolve().parent.parent.parent.parent
    _sprint1_dir = str(_repo / "strategies" / "4h" / "sprint1")
    if _sprint1_dir not in _sys.path:
        _sys.path.insert(0, _sprint1_dir)
    if str(_repo / "trading_bot") not in _sys.path:
        _sys.path.insert(0, str(_repo / "trading_bot"))
    from indicators import precompute_all
    dummy_indicators = precompute_all(dummy_data, ["TEST/USD"])

    # Dummy signal_fn: triggers at every bar where RSI < 40
    def _dummy_signal(candles, bar, ind, params):
        rsi_val = ind["rsi"][bar] if ind["rsi"][bar] is not None else 50
        if rsi_val < 40:
            close = ind["closes"][bar]
            return {
                "stop_price": close * 0.95,
                "target_price": close * 1.10,
                "time_limit": 15,
                "strength": 40 - rsi_val,
            }
        return None

    result = score_hypothesis_entries(
        data=dummy_data,
        coins=["TEST/USD"],
        signal_fn=_dummy_signal,
        params={},
        indicators=dummy_indicators,
        start_bar=50,
    )
    print(f"\n  Test 10: score_hypothesis_entries on dummy data:")
    print(f"    total_entries={result['total_entries']}")
    print(f"    passing_entries={result['passing_entries']}")
    print(f"    avg_composite={result['avg_composite']:.4f}")
    print(f"    median_composite={result['median_composite']:.4f}")
    print(f"    top_quartile_composite={result['top_quartile_composite']:.4f}")
    if result["avg_features"]:
        print(f"    avg_features:")
        for k, v in result["avg_features"].items():
            print(f"      {k}: {v:.4f}")

    print("\n  All compat_scorer tests passed")
