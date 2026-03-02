"""
SuperHF Indicators — 1H Support/Resistance zones for 15m entries.

Provides:
  - calc_pivots(): causal pivot lows with confirmed right candles (no lookahead)
  - find_support_zones(): zone stacking from pivots + DC + BB
  - precompute_1h_levels(): build 1H support array aligned to 15m bars
"""
from __future__ import annotations

from trading_bot.strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger


# ---------------------------------------------------------------------------
# Pivot Low detection (causal — no lookahead)
# ---------------------------------------------------------------------------

def calc_pivot_lows(
    lows: list[float],
    lookback_left: int = 5,
    lookback_right: int = 2,
) -> list[float | None]:
    """Find pivot lows: bar where low is the minimum of [bar-left, bar+right].

    CAUSAL: pivot at bar B is only confirmed at bar B+lookback_right.
    We return the pivot value at the bar where it becomes confirmed,
    NOT at bar B itself.

    Returns list of same length as lows.  Value is the pivot low price
    when a pivot is confirmed at that bar, else None.
    """
    n = len(lows)
    result: list[float | None] = [None] * n

    for confirm_bar in range(lookback_left + lookback_right, n):
        # The candidate pivot is at confirm_bar - lookback_right
        pivot_bar = confirm_bar - lookback_right
        pivot_low = lows[pivot_bar]

        # Check left: all bars in [pivot_bar - lookback_left, pivot_bar) must have higher lows
        is_pivot = True
        for j in range(pivot_bar - lookback_left, pivot_bar):
            if j < 0:
                is_pivot = False
                break
            if lows[j] <= pivot_low:
                is_pivot = False
                break

        if not is_pivot:
            continue

        # Check right: all bars in (pivot_bar, pivot_bar + lookback_right] must have higher lows
        for j in range(pivot_bar + 1, pivot_bar + lookback_right + 1):
            if j >= n:
                is_pivot = False
                break
            if lows[j] < pivot_low:
                is_pivot = False
                break

        if is_pivot:
            result[confirm_bar] = pivot_low

    return result


def get_recent_pivot_low(
    pivot_lows: list[float | None],
    bar: int,
    max_lookback: int = 40,
) -> float | None:
    """Return the most recent confirmed pivot low before `bar`."""
    for b in range(bar - 1, max(bar - max_lookback - 1, -1), -1):
        if b < 0:
            break
        if pivot_lows[b] is not None:
            return pivot_lows[b]
    return None


# ---------------------------------------------------------------------------
# Support zone stacking
# ---------------------------------------------------------------------------

def find_support_zone(
    bar: int,
    pivot_lows: list[float | None],
    dc_prev_low: list[float | None],
    bb_lower: list[float | None],
    zone_type: str = "dc_bb_stack",
    atr_val: float | None = None,
    tolerance_atr: float = 1.0,
    pivot_lookback: int = 40,
) -> float | None:
    """Determine the support zone price at `bar`.

    zone_type:
      - "pivot_only": use most recent pivot low
      - "dc_bb_stack": require at least 2 of (pivot, dc_low, bb_lower) to
        agree within tolerance_atr * ATR.  Return average of agreeing levels.

    Returns support zone price or None if no valid zone found.
    """
    if zone_type == "pivot_only":
        return get_recent_pivot_low(pivot_lows, bar, pivot_lookback)

    # Collect candidate levels
    levels: list[float] = []

    pivot = get_recent_pivot_low(pivot_lows, bar, pivot_lookback)
    if pivot is not None:
        levels.append(pivot)

    dc_low = dc_prev_low[bar] if bar < len(dc_prev_low) and dc_prev_low[bar] is not None else None
    if dc_low is not None:
        levels.append(dc_low)

    bb_lo = bb_lower[bar] if bar < len(bb_lower) and bb_lower[bar] is not None else None
    if bb_lo is not None:
        levels.append(bb_lo)

    if len(levels) < 2:
        return None

    # Check if at least 2 levels agree within tolerance
    tol = (atr_val * tolerance_atr) if atr_val else 0
    best_cluster: list[float] = []

    for i in range(len(levels)):
        cluster = [levels[i]]
        for j in range(len(levels)):
            if i == j:
                continue
            if abs(levels[i] - levels[j]) <= tol:
                cluster.append(levels[j])
        if len(cluster) >= 2 and len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) >= 2:
        return sum(best_cluster) / len(best_cluster)
    return None


# ---------------------------------------------------------------------------
# 1H indicator precomputation
# ---------------------------------------------------------------------------

def _vectorized_rsi(closes: list[float], period: int) -> list[float | None]:
    """Compute RSI for all bars in O(n). Returns list[float|None]."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result
    for bar in range(period, n):
        # Use last `period` changes ending at `bar`
        gains_sum = 0.0
        losses_sum = 0.0
        for j in range(bar - period + 1, bar + 1):
            diff = closes[j] - closes[j - 1]
            if diff > 0:
                gains_sum += diff
            else:
                losses_sum -= diff
        avg_gain = gains_sum / period
        avg_loss = losses_sum / period
        if avg_loss == 0:
            result[bar] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[bar] = 100 - (100 / (1 + rs))
    return result


def _vectorized_atr(highs: list[float], lows: list[float],
                     closes: list[float], period: int) -> list[float | None]:
    """Compute ATR for all bars in O(n). Returns list[float|None]."""
    n = len(highs)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result
    # Precompute true ranges
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
    # Rolling sum
    rolling_sum = sum(trs[1:period + 1])
    result[period] = rolling_sum / period
    for bar in range(period + 1, n):
        rolling_sum += trs[bar] - trs[bar - period]
        result[bar] = rolling_sum / period
    return result


def _vectorized_donchian_low(lows: list[float], period: int) -> list[float | None]:
    """Compute Donchian lowest low for all bars in O(n·period).
    Returns the PREVIOUS bar's donchian low (prev_low for entry signals)."""
    n = len(lows)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result
    for bar in range(period, n):
        # prev_low: donchian of bars [bar-period, bar-1] (excluding current bar)
        result[bar] = min(lows[bar - period:bar])
    return result


def _vectorized_donchian_mid(highs: list[float], lows: list[float],
                              period: int) -> list[float | None]:
    """Compute Donchian mid channel for all bars. O(n·period)."""
    n = len(highs)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    for bar in range(period - 1, n):
        hh = max(highs[bar - period + 1:bar + 1])
        ll = min(lows[bar - period + 1:bar + 1])
        result[bar] = (hh + ll) / 2
    return result


def _vectorized_bollinger(closes: list[float], period: int,
                           dev: float) -> tuple[list, list, list]:
    """Compute Bollinger Bands for all bars. O(n·period)."""
    n = len(closes)
    bb_mid: list[float | None] = [None] * n
    bb_upper: list[float | None] = [None] * n
    bb_lower: list[float | None] = [None] * n
    if n < period:
        return bb_mid, bb_upper, bb_lower
    # Rolling sum for mean
    rolling_sum = sum(closes[:period])
    for bar in range(period - 1, n):
        if bar > period - 1:
            rolling_sum += closes[bar] - closes[bar - period]
        mid = rolling_sum / period
        # Variance (must recompute, no shortcut without sq sum)
        var_sum = 0.0
        for j in range(bar - period + 1, bar + 1):
            var_sum += (closes[j] - mid) ** 2
        std = (var_sum / period) ** 0.5
        bb_mid[bar] = mid
        bb_upper[bar] = mid + dev * std
        bb_lower[bar] = mid - dev * std
    return bb_mid, bb_upper, bb_lower


def _vectorized_vol_avg(volumes: list[float], period: int = 20) -> list[float | None]:
    """Compute rolling volume average for all bars. O(n)."""
    n = len(volumes)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    rolling_sum = sum(volumes[:period])
    result[period - 1] = rolling_sum / period
    for bar in range(period, n):
        rolling_sum += volumes[bar] - volumes[bar - period]
        result[bar] = rolling_sum / period
    return result


def precompute_1h_indicators(candles_1h: list[dict]) -> dict:
    """Compute 1H-level indicators for support zone detection.

    OPTIMIZED: O(n) per indicator instead of O(n²).

    Returns dict with parallel arrays:
        closes, highs, lows, volumes, n,
        rsi, atr, dc_prev_low, dc_mid, bb_mid, bb_lower, bb_upper,
        vol_avg, pivot_lows
    """
    n = len(candles_1h)
    closes = [c['close'] for c in candles_1h]
    highs = [c['high'] for c in candles_1h]
    lows = [c['low'] for c in candles_1h]
    volumes = [c.get('volume', 0) for c in candles_1h]

    DC_PERIOD = 20
    BB_PERIOD = 20
    BB_DEV = 2.0
    RSI_PERIOD = 14
    ATR_PERIOD = 14

    # Vectorized computation — O(n) per indicator
    rsi_arr = _vectorized_rsi(closes, RSI_PERIOD)
    atr_arr = _vectorized_atr(highs, lows, closes, ATR_PERIOD)
    dc_prev_low_arr = _vectorized_donchian_low(lows, DC_PERIOD)
    dc_mid_arr = _vectorized_donchian_mid(highs, lows, DC_PERIOD)
    bb_mid_arr, bb_upper_arr, bb_lower_arr = _vectorized_bollinger(closes, BB_PERIOD, BB_DEV)
    vol_avg_arr = _vectorized_vol_avg(volumes, 20)

    ind: dict = {
        'closes': closes, 'highs': highs, 'lows': lows,
        'volumes': volumes, 'n': n,
        'rsi': rsi_arr, 'atr': atr_arr,
        'dc_prev_low': dc_prev_low_arr, 'dc_mid': dc_mid_arr,
        'bb_mid': bb_mid_arr, 'bb_lower': bb_lower_arr, 'bb_upper': bb_upper_arr,
        'vol_avg': vol_avg_arr,
    }

    # Pivots (causal, confirmed)
    ind['pivot_lows'] = calc_pivot_lows(lows, lookback_left=5, lookback_right=2)

    return ind


# ---------------------------------------------------------------------------
# Map 1H support zones to 15m bars
# ---------------------------------------------------------------------------

def map_1h_to_15m(
    candles_15m: list[dict],
    ind_1h: dict,
    candles_1h: list[dict],
    zone_type: str = "dc_bb_stack",
    pivot_lookback: int = 40,
) -> list[float | None]:
    """For each 15m bar, find the corresponding 1H support zone.

    Uses 1H candle timestamps to map: each 15m bar maps to the
    most recent completed 1H bar.  Returns list[float|None] of
    length len(candles_15m).
    """
    n_15m = len(candles_15m)
    zones: list[float | None] = [None] * n_15m

    # Build 1H timestamp -> bar index
    ts_1h = [c['time'] for c in candles_1h]
    n_1h = len(ts_1h)

    # For each 15m bar, binary search for the latest completed 1H bar
    import bisect

    for i in range(n_15m):
        ts = candles_15m[i]['time']
        # Find the latest 1H bar that completed BEFORE this 15m bar
        # 1H bar at ts_1h[j] covers [ts_1h[j], ts_1h[j]+3600)
        # It's completed when ts >= ts_1h[j] + 3600
        # So we find j where ts_1h[j] + 3600 <= ts  =>  ts_1h[j] <= ts - 3600
        completed_before = ts - 3600
        j = bisect.bisect_right(ts_1h, completed_before) - 1
        if j < 0 or j >= n_1h:
            continue

        # Get support zone from 1H indicators at bar j
        atr_val = ind_1h['atr'][j]
        zone = find_support_zone(
            bar=j,
            pivot_lows=ind_1h['pivot_lows'],
            dc_prev_low=ind_1h['dc_prev_low'],
            bb_lower=ind_1h['bb_lower'],
            zone_type=zone_type,
            atr_val=atr_val,
            pivot_lookback=pivot_lookback,
        )
        zones[i] = zone

    return zones


# ---------------------------------------------------------------------------
# 15m indicator precomputation (for signal evaluation)
# ---------------------------------------------------------------------------

def _vectorized_hlc3_vwap(
    highs: list[float], lows: list[float], closes: list[float],
    atr: list[float | None], period: int = 20, zscore_lookback: int = 50,
) -> tuple[list, list, list]:
    """Compute HLC3 VWAP proxy + ATR-normalized deviation + z-score.

    HLC3 = (high + low + close) / 3  — same proxy as HF candle_downloader.
    vwap_dev = (vwap - close) / ATR  — positive when price below VWAP.
    vwap_dev_zscore = z-score of vwap_dev over rolling window.

    Returns (vwap, vwap_dev, vwap_dev_zscore) — three parallel arrays.
    """
    n = len(closes)
    vwap = [0.0] * n
    vwap_dev: list[float | None] = [None] * n
    vwap_dev_zscore: list[float | None] = [None] * n

    # Pass 1: HLC3 + rolling VWAP average + deviation
    for i in range(n):
        vwap[i] = (highs[i] + lows[i] + closes[i]) / 3.0

    # Pass 2: ATR-normalized deviation
    for i in range(n):
        if atr[i] is not None and atr[i] > 0 and closes[i] > 0:
            vwap_dev[i] = (vwap[i] - closes[i]) / atr[i]

    # Pass 3: Z-score over rolling window (normalizes HLC3 structural cap)
    for bar in range(n):
        if vwap_dev[bar] is None:
            continue
        window = []
        for j in range(max(0, bar - zscore_lookback + 1), bar + 1):
            if vwap_dev[j] is not None:
                window.append(vwap_dev[j])
        if len(window) < 20:
            continue
        mean_dev = sum(window) / len(window)
        var_dev = sum((x - mean_dev) ** 2 for x in window) / len(window)
        std_dev = var_dev ** 0.5
        if std_dev > 1e-10:
            vwap_dev_zscore[bar] = (vwap_dev[bar] - mean_dev) / std_dev

    return vwap, vwap_dev, vwap_dev_zscore


def precompute_15m_indicators(candles_15m: list[dict]) -> dict:
    """Compute 15m-level indicators needed by signal functions.

    OPTIMIZED: O(n) per indicator instead of O(n²).

    Returns dict with parallel arrays:
        closes, highs, lows, opens, volumes, n,
        rsi, atr, vol_avg,
        dc_prev_low, dc_mid, bb_mid, bb_lower, bb_upper,
        vwap, vwap_dev, vwap_dev_zscore
    """
    n = len(candles_15m)
    closes = [c['close'] for c in candles_15m]
    highs = [c['high'] for c in candles_15m]
    lows = [c['low'] for c in candles_15m]
    opens = [c.get('open', c['close']) for c in candles_15m]
    volumes = [c.get('volume', 0) for c in candles_15m]

    DC_PERIOD = 20
    BB_PERIOD = 20
    BB_DEV = 2.0
    RSI_PERIOD = 14
    ATR_PERIOD = 14

    # Vectorized computation — O(n) per indicator
    rsi_arr = _vectorized_rsi(closes, RSI_PERIOD)
    atr_arr = _vectorized_atr(highs, lows, closes, ATR_PERIOD)
    vol_avg_arr = _vectorized_vol_avg(volumes, 20)

    # DC channels (needed for DC-geometry gate)
    dc_prev_low_arr = _vectorized_donchian_low(lows, DC_PERIOD)
    dc_mid_arr = _vectorized_donchian_mid(highs, lows, DC_PERIOD)

    # Bollinger Bands (needed for DC-geometry gate)
    bb_mid_arr, bb_upper_arr, bb_lower_arr = _vectorized_bollinger(
        closes, BB_PERIOD, BB_DEV,
    )

    # HLC3 VWAP proxy + deviation + z-score (for VWAP_DEV signals)
    vwap_arr, vwap_dev_arr, vwap_dev_zscore_arr = _vectorized_hlc3_vwap(
        highs, lows, closes, atr_arr,
    )

    ind: dict = {
        'closes': closes, 'highs': highs, 'lows': lows,
        'opens': opens, 'volumes': volumes, 'n': n,
        'rsi': rsi_arr, 'atr': atr_arr,
        'vol_avg': vol_avg_arr,
        # DC channels
        'dc_prev_low': dc_prev_low_arr, 'dc_mid': dc_mid_arr,
        # Bollinger Bands
        'bb_mid': bb_mid_arr, 'bb_lower': bb_lower_arr, 'bb_upper': bb_upper_arr,
        # HLC3 VWAP
        'vwap': vwap_arr, 'vwap_dev': vwap_dev_arr,
        'vwap_dev_zscore': vwap_dev_zscore_arr,
    }

    return ind


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    random.seed(42)

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

    print("=== SuperHF Indicators Self-Test ===\n")

    # Test 1: Pivot lows — no lookahead
    print("--- Pivot Lows ---")
    lows_test = [10, 9, 8, 7, 6, 5, 6, 7, 8, 9, 10, 11, 12]
    pivots = calc_pivot_lows(lows_test, lookback_left=3, lookback_right=2)
    # Pivot at bar 5 (low=5), confirmed at bar 7 (=5+2)
    check("pivot_confirmed_at_right_bar", pivots[7] == 5.0, f"got {pivots[7]}")
    # No pivot at bar 5 itself (lookahead would be needed)
    check("no_lookahead_at_pivot_bar", pivots[5] is None, f"got {pivots[5]}")

    # Test 2: Pivot with right=2 means we need 2 higher bars after pivot
    lows_test2 = [10, 8, 6, 4, 6, 8, 10, 12]
    pivots2 = calc_pivot_lows(lows_test2, lookback_left=2, lookback_right=2)
    check("pivot_at_bar3_confirmed_at_5", pivots2[5] == 4.0, f"got {pivots2}")

    # Test 3: get_recent_pivot_low
    pivot_arr = [None, None, None, None, None, None, None, 5.0, None, None, None, None, 8.0]
    recent = get_recent_pivot_low(pivot_arr, bar=10, max_lookback=10)
    check("recent_pivot_found", recent == 5.0, f"got {recent}")
    recent2 = get_recent_pivot_low(pivot_arr, bar=13, max_lookback=2)
    check("recent_pivot_close", recent2 == 8.0, f"got {recent2}")

    # Test 4: find_support_zone — dc_bb_stack requires 2 agreeing levels
    zone = find_support_zone(
        bar=0,
        pivot_lows=[100.0],
        dc_prev_low=[101.0],
        bb_lower=[99.5],
        zone_type="dc_bb_stack",
        atr_val=5.0,
        tolerance_atr=1.0,
    )
    check("zone_3_levels_agree", zone is not None and abs(zone - 100.17) < 0.5,
          f"got {zone}")

    # Test 5: zone with only 1 level → None
    zone_none = find_support_zone(
        bar=0,
        pivot_lows=[None],
        dc_prev_low=[100.0],
        bb_lower=[None],
        zone_type="dc_bb_stack",
        atr_val=5.0,
    )
    check("zone_1_level_none", zone_none is None, f"got {zone_none}")

    # Test 6: pivot_only zone type
    zone_pivot = find_support_zone(
        bar=1,
        pivot_lows=[None, None],
        dc_prev_low=[100.0, 100.0],
        bb_lower=[99.0, 99.0],
        zone_type="pivot_only",
        atr_val=5.0,
    )
    check("pivot_only_no_pivot", zone_pivot is None, f"got {zone_pivot}")

    # Test 7: 15m indicators computation (all indicators including new ones)
    candles_15m = [{'time': i * 900, 'open': 100 + random.gauss(0, 2),
                     'high': 102 + random.gauss(0, 2),
                     'low': 98 + random.gauss(0, 2),
                     'close': 100 + random.gauss(0, 2),
                     'volume': 1000 + random.gauss(0, 100)}
                    for i in range(200)]
    ind = precompute_15m_indicators(candles_15m)
    check("15m_ind_length", ind['n'] == 200)
    check("15m_rsi_computed", ind['rsi'][50] is not None, f"rsi[50]={ind['rsi'][50]}")
    check("15m_atr_computed", ind['atr'][50] is not None, f"atr[50]={ind['atr'][50]}")

    # Test 8: DC channels on 15m
    check("15m_dc_prev_low_computed", ind['dc_prev_low'][50] is not None,
          f"dc_prev_low[50]={ind['dc_prev_low'][50]}")
    check("15m_dc_mid_computed", ind['dc_mid'][50] is not None,
          f"dc_mid[50]={ind['dc_mid'][50]}")

    # Test 9: Bollinger Bands on 15m
    check("15m_bb_mid_computed", ind['bb_mid'][50] is not None,
          f"bb_mid[50]={ind['bb_mid'][50]}")
    check("15m_bb_lower_computed", ind['bb_lower'][50] is not None,
          f"bb_lower[50]={ind['bb_lower'][50]}")

    # Test 10: HLC3 VWAP proxy
    check("15m_vwap_computed", ind['vwap'][50] is not None and ind['vwap'][50] > 0,
          f"vwap[50]={ind['vwap'][50]}")
    # HLC3 = (H + L + C) / 3 — verify for bar 0
    expected_hlc3 = (candles_15m[0]['high'] + candles_15m[0]['low'] + candles_15m[0]['close']) / 3
    check("15m_vwap_is_hlc3", abs(ind['vwap'][0] - expected_hlc3) < 1e-10,
          f"vwap[0]={ind['vwap'][0]} != expected {expected_hlc3}")

    # Test 11: VWAP deviation
    check("15m_vwap_dev_computed", ind['vwap_dev'][50] is not None,
          f"vwap_dev[50]={ind['vwap_dev'][50]}")

    # Test 12: VWAP deviation z-score (needs ≥20 bars warmup after ATR warmup)
    check("15m_vwap_dev_zscore_computed", ind['vwap_dev_zscore'][100] is not None,
          f"vwap_dev_zscore[100]={ind['vwap_dev_zscore'][100]}")

    # Test 13: DC-geometry gate check — close < dc_mid AND close < bb_mid at bar 50
    # (values depend on random seed, just verify both are computable)
    dc_mid_val = ind['dc_mid'][50]
    bb_mid_val = ind['bb_mid'][50]
    close_val = ind['closes'][50]
    check("15m_geometry_computable",
          dc_mid_val is not None and bb_mid_val is not None and close_val > 0,
          f"dc_mid={dc_mid_val}, bb_mid={bb_mid_val}, close={close_val}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        exit(1)
    print("All tests passed!")
