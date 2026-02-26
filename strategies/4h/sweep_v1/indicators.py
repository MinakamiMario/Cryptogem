"""
Sweep v1 Extended Indicator Library
====================================
Extends Sprint 2 indicators with 5 new computations for Sweep v1 families:

  1. calc_pivot_lows       — Confirmed fractal pivot lows (causal)
  2. calc_atr_percentile   — ATR percentile rank in rolling window
  3. calc_bb_squeeze_dur   — Consecutive bars in BB squeeze
  4. calc_swing_structure  — HH/HL trend detection
  5. precompute_rsi_rank   — Cross-sectional RSI ranking

All functions are pure: lists in, list/dict out. No side effects.
All use causal data only (no look-ahead).
"""
from __future__ import annotations

import sys
import importlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading_bot"))

# Import Sprint 2 indicators (reuse everything)
_sprint2_ind = importlib.import_module("strategies.4h.sprint2.indicators")

# Re-export Sprint 2 constants
DC_PERIOD = _sprint2_ind.DC_PERIOD
BB_PERIOD = _sprint2_ind.BB_PERIOD
BB_DEV = _sprint2_ind.BB_DEV
RSI_PERIOD = _sprint2_ind.RSI_PERIOD
ATR_PERIOD = _sprint2_ind.ATR_PERIOD
VOL_AVG_PERIOD = _sprint2_ind.VOL_AVG_PERIOD

# Minimum bars before indicators are valid
MIN_WARMUP = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5


# ---------------------------------------------------------------------------
# 1. Fractal Pivot Lows (causal)
# ---------------------------------------------------------------------------

def calc_pivot_lows(
    lows: list[float],
    window: int = 5,
) -> list[float | None]:
    """Confirmed fractal pivot lows.

    A pivot low at bar i requires: lows[i] <= lows[j] for all j in
    [i-window, i+window]. This pivot is CONFIRMED only at bar i+window
    (when all future bars in the window are known).

    At bar b, the returned value is the PRICE of the most recent
    confirmed pivot low (confirmed at or before bar b). None until
    first confirmed pivot.

    Causal invariant: at bar b, we only use data up to bar b.
    """
    n = len(lows)
    result: list[float | None] = [None] * n

    last_pivot_price: float | None = None

    for confirm_bar in range(2 * window, n):
        # The candidate pivot is at bar (confirm_bar - window)
        cand = confirm_bar - window
        cand_low = lows[cand]

        # Check if candidate is the minimum in [cand-window, cand+window]
        is_pivot = True
        for j in range(cand - window, cand + window + 1):
            if j == cand:
                continue
            if 0 <= j < n and lows[j] < cand_low:
                is_pivot = False
                break

        if is_pivot:
            last_pivot_price = cand_low

        # At confirm_bar, the last confirmed pivot is available
        if last_pivot_price is not None:
            result[confirm_bar] = last_pivot_price

    # Forward-fill: once a pivot is confirmed, it stays available
    # (already handled by last_pivot_price accumulator above)

    return result


# ---------------------------------------------------------------------------
# 2. ATR Percentile Rank
# ---------------------------------------------------------------------------

def calc_atr_percentile(
    atr: list[float | None],
    lookback: int = 50,
) -> list[float | None]:
    """Percentile rank of current ATR within rolling lookback window.

    Returns 0-100. Low values = volatility contraction.
    None until enough non-None ATR values.
    """
    n = len(atr)
    result: list[float | None] = [None] * n

    for i in range(n):
        cur = atr[i]
        if cur is None:
            continue

        # Collect valid ATR values in lookback window
        window_vals = []
        for j in range(max(0, i - lookback), i + 1):
            if atr[j] is not None:
                window_vals.append(atr[j])

        if len(window_vals) < 10:  # need minimum sample
            continue

        # Percentile: fraction of window values <= current
        count_below = sum(1 for v in window_vals if v <= cur)
        result[i] = count_below / len(window_vals) * 100.0

    return result


# ---------------------------------------------------------------------------
# 3. Bollinger Band Squeeze Duration
# ---------------------------------------------------------------------------

def calc_bb_squeeze_dur(
    bb_upper: list[float | None],
    bb_lower: list[float | None],
    closes: list[float],
    lookback: int = 30,
    pctile: int = 30,
) -> list[int]:
    """Consecutive bars that BB width is in squeeze territory.

    Squeeze = current BB width (upper - lower) is below the pctile-th
    percentile of BB widths over the past lookback bars.

    Returns integer count at each bar. 0 = not in squeeze.
    """
    n = len(closes)
    result = [0] * n

    # First compute BB width array
    bb_width: list[float | None] = [None] * n
    for i in range(n):
        if bb_upper[i] is not None and bb_lower[i] is not None:
            mid = closes[i] if closes[i] > 0 else 1.0
            bb_width[i] = (bb_upper[i] - bb_lower[i]) / mid

    consec = 0
    for i in range(n):
        if bb_width[i] is None:
            consec = 0
            continue

        # Compute threshold from rolling window
        window_widths = []
        for j in range(max(0, i - lookback), i + 1):
            if bb_width[j] is not None:
                window_widths.append(bb_width[j])

        if len(window_widths) < 10:
            consec = 0
            continue

        sorted_widths = sorted(window_widths)
        threshold_idx = max(0, int(len(sorted_widths) * pctile / 100) - 1)
        threshold = sorted_widths[threshold_idx]

        if bb_width[i] <= threshold:
            consec += 1
        else:
            consec = 0

        result[i] = consec

    return result


# ---------------------------------------------------------------------------
# 4. Swing Structure (HH/HL detection)
# ---------------------------------------------------------------------------

def calc_swing_structure(
    highs: list[float],
    lows: list[float],
    window: int = 5,
) -> list[dict | None]:
    """Detect swing structure for trend identification.

    Swing high at bar i: highs[i] >= all highs in [i-window, i+window].
    Swing low at bar i: lows[i] <= all lows in [i-window, i+window].
    Confirmed causally at bar i + window.

    Returns list of dicts at each bar:
        {
            "hh_hl_count": int,           # consecutive HH+HL pairs (trend strength)
            "last_swing_low_price": float, # price of last confirmed swing low
            "last_swing_low_bar": int,     # bar index of last swing low
            "trend": str,                  # "up" | "down" | "none"
        }
    """
    n = len(highs)
    result: list[dict | None] = [None] * n

    # Collect confirmed swing points
    swing_highs: list[tuple[int, float]] = []  # (bar, price)
    swing_lows: list[tuple[int, float]] = []   # (bar, price)

    for confirm_bar in range(2 * window, n):
        cand = confirm_bar - window

        # Check swing high
        cand_high = highs[cand]
        is_sh = True
        for j in range(cand - window, cand + window + 1):
            if j == cand:
                continue
            if 0 <= j < n and highs[j] > cand_high:
                is_sh = False
                break
        if is_sh:
            swing_highs.append((cand, cand_high))

        # Check swing low
        cand_low = lows[cand]
        is_sl = True
        for j in range(cand - window, cand + window + 1):
            if j == cand:
                continue
            if 0 <= j < n and lows[j] < cand_low:
                is_sl = False
                break
        if is_sl:
            swing_lows.append((cand, cand_low))

        # Build structure from confirmed swings so far
        # Count HH+HL pairs (consecutive higher highs AND higher lows)
        hh_hl = 0
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            # Check from most recent backwards
            recent_shs = swing_highs[-6:]  # last 6 swing highs
            recent_sls = swing_lows[-6:]   # last 6 swing lows

            # Count consecutive HH from end
            hh_count = 0
            for k in range(len(recent_shs) - 1, 0, -1):
                if recent_shs[k][1] > recent_shs[k - 1][1]:
                    hh_count += 1
                else:
                    break

            # Count consecutive HL from end
            hl_count = 0
            for k in range(len(recent_sls) - 1, 0, -1):
                if recent_sls[k][1] > recent_sls[k - 1][1]:
                    hl_count += 1
                else:
                    break

            hh_hl = min(hh_count, hl_count)

        # Determine trend
        if hh_hl >= 2:
            trend = "up"
        elif len(swing_highs) >= 2 and len(swing_lows) >= 2:
            # Check for lower highs + lower lows
            if (swing_highs[-1][1] < swing_highs[-2][1] and
                    swing_lows[-1][1] < swing_lows[-2][1]):
                trend = "down"
            else:
                trend = "none"
        else:
            trend = "none"

        last_sl_price = swing_lows[-1][1] if swing_lows else None
        last_sl_bar = swing_lows[-1][0] if swing_lows else None

        result[confirm_bar] = {
            "hh_hl_count": hh_hl,
            "last_swing_low_price": last_sl_price,
            "last_swing_low_bar": last_sl_bar,
            "trend": trend,
        }

    return result


# ---------------------------------------------------------------------------
# 5. Cross-Sectional RSI Rank
# ---------------------------------------------------------------------------

def precompute_rsi_rank(
    indicators: dict,
    coins: list[str],
    n_bars: int,
) -> dict:
    """Cross-sectional RSI ranking per bar.

    For each bar, ranks all coins by RSI value. Rank 1 = lowest RSI
    (most oversold). Only computed for bars where the coin passes
    DC geometry (rsi < 50 as broad pre-filter for efficiency).

    Returns:
        {
            "rsi_percentile": {coin: [percentile_at_bar_0, ...]},
            "rsi_median": [median_rsi_at_bar_0, ...],
        }
    """
    rsi_pctile: dict[str, list[float | None]] = {}
    rsi_median: list[float | None] = [None] * n_bars

    for coin in coins:
        rsi_pctile[coin] = [None] * n_bars

    for bar in range(MIN_WARMUP, n_bars):
        # Collect valid RSI values across all coins at this bar
        bar_rsi: list[tuple[str, float]] = []
        for coin in coins:
            ind = indicators.get(coin)
            if ind is None or bar >= ind["n"]:
                continue
            rsi = ind["rsi"][bar]
            if rsi is not None:
                bar_rsi.append((coin, rsi))

        if len(bar_rsi) < 10:  # need minimum sample
            continue

        # Sort by RSI (ascending = most oversold first)
        bar_rsi.sort(key=lambda x: x[1])
        n_coins = len(bar_rsi)

        # Compute median
        mid = n_coins // 2
        if n_coins % 2 == 0:
            rsi_median[bar] = (bar_rsi[mid - 1][1] + bar_rsi[mid][1]) / 2
        else:
            rsi_median[bar] = bar_rsi[mid][1]

        # Assign percentile to each coin
        for rank_idx, (coin, _rsi_val) in enumerate(bar_rsi):
            pctile = (rank_idx + 1) / n_coins * 100.0
            rsi_pctile[coin][bar] = pctile

    return {
        "rsi_percentile": rsi_pctile,
        "rsi_median": rsi_median,
    }


# ---------------------------------------------------------------------------
# Extended precompute_all for Sweep v1
# ---------------------------------------------------------------------------

def precompute_all(data: dict, coins: list[str]) -> dict:
    """Precompute all indicators for all coins (Sweep v1 extended).

    Extends Sprint 2 precompute_all with:
      - pivot_lows_5, pivot_lows_8: fractal pivot lows (window 5, 8)
      - atr_percentile: ATR percentile rank (lookback 50)
      - bb_squeeze_dur: BB squeeze duration
      - swing_5: swing structure (window 5)
      - swing_8: swing structure (window 8)

    Note: RSI rank is cross-sectional and computed separately via
    precompute_rsi_rank() after this returns.

    Returns {pair: {all Sprint 2 indicators + new indicators}}
    """
    # Start with Sprint 2 indicators
    indicators = _sprint2_ind.precompute_all(data, coins)

    # Extend each coin
    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue

        lows = ind["lows"]
        highs = ind["highs"]
        closes = ind["closes"]

        # Fractal pivot lows (two window sizes)
        ind["pivot_lows_5"] = calc_pivot_lows(lows, window=5)
        ind["pivot_lows_8"] = calc_pivot_lows(lows, window=8)

        # ATR percentile (lookback 50)
        ind["atr_percentile"] = calc_atr_percentile(ind["atr"], lookback=50)

        # Derive bb_upper from bb_mid and bb_lower (symmetric Bollinger Bands)
        # bb_upper = bb_mid + (bb_mid - bb_lower)
        n = ind["n"]
        bb_mid = ind["bb_mid"]
        bb_lower = ind["bb_lower"]
        bb_upper = [None] * n
        for i in range(n):
            if bb_mid[i] is not None and bb_lower[i] is not None:
                bb_upper[i] = bb_mid[i] + (bb_mid[i] - bb_lower[i])
        ind["bb_upper"] = bb_upper

        # BB squeeze duration
        ind["bb_squeeze_dur"] = calc_bb_squeeze_dur(
            bb_upper, bb_lower, closes,
            lookback=30, pctile=30,
        )

        # Swing structure (two window sizes)
        ind["swing_5"] = calc_swing_structure(highs, lows, window=5)
        ind["swing_8"] = calc_swing_structure(highs, lows, window=8)

    return indicators


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    random.seed(42)

    print("Sweep v1 Indicator Self-Test")
    print("=" * 60)

    # Synthetic data
    n_bars = 200
    price = 100.0
    lows_arr, highs_arr, closes_arr = [], [], []
    for i in range(n_bars):
        change = random.gauss(0, 2)
        c = price + change
        h = max(c, price) + random.uniform(0, 1)
        lo = min(c, price) - random.uniform(0, 1)
        lows_arr.append(lo)
        highs_arr.append(h)
        closes_arr.append(c)
        price = c

    # 1. Pivot lows
    pivots = calc_pivot_lows(lows_arr, window=5)
    pivot_vals = [v for v in pivots if v is not None]
    assert len(pivot_vals) > 0, "Should have some pivot lows"
    # Causality check: no pivot confirmed before bar 2*window
    for i in range(10):
        assert pivots[i] is None, f"Pivot at bar {i} should be None (causality)"
    print(f"  1. Pivot lows (w=5): {len(pivot_vals)} confirmed, first at bar "
          f"{next(i for i, v in enumerate(pivots) if v is not None)}")

    # 2. ATR percentile
    # Fake ATR
    atr_arr = [None] * 15 + [random.uniform(1, 5) for _ in range(n_bars - 15)]
    atr_pctile = calc_atr_percentile(atr_arr, lookback=50)
    pctile_vals = [v for v in atr_pctile if v is not None]
    assert len(pctile_vals) > 0
    assert all(0 <= v <= 100 for v in pctile_vals), "Percentile must be 0-100"
    print(f"  2. ATR percentile: {len(pctile_vals)} values, "
          f"range {min(pctile_vals):.1f}-{max(pctile_vals):.1f}")

    # 3. BB squeeze duration
    bb_u = [None] * 20 + [c + random.uniform(1, 3) for c in closes_arr[20:]]
    bb_l = [None] * 20 + [c - random.uniform(1, 3) for c in closes_arr[20:]]
    squeeze = calc_bb_squeeze_dur(bb_u, bb_l, closes_arr, lookback=30, pctile=30)
    max_squeeze = max(squeeze)
    print(f"  3. BB squeeze dur: max consecutive = {max_squeeze}, "
          f"non-zero bars = {sum(1 for s in squeeze if s > 0)}")

    # 4. Swing structure
    swings = calc_swing_structure(highs_arr, lows_arr, window=5)
    swing_vals = [s for s in swings if s is not None]
    trends = [s["trend"] for s in swing_vals]
    print(f"  4. Swing structure (w=5): {len(swing_vals)} bars, "
          f"up={trends.count('up')}, down={trends.count('down')}, "
          f"none={trends.count('none')}")

    print("\n  All self-tests passed!")
