"""
time_mapping.py -- Map 15m <-> 1H bar indices for SuperHF Sprint 3 harness.

Data format:
  - 1H candles: list[dict] with keys: time, open, high, low, close, volume
  - 15m candles: list[dict] with same keys
  - Each 1H bar covers [time, time+3600), containing up to 4 x 15m bars

O(n) two-pointer construction; O(1) lookups.
"""

from __future__ import annotations

SECONDS_PER_HOUR = 3600


def build_hour_to_15m_map(
    candles_1h: list[dict], candles_15m: list[dict]
) -> dict[int, list[int]]:
    """Map each 1H bar index to the sorted list of 15m bar indices that fall
    within that hour window [ts_1h, ts_1h + 3600).

    Both input lists MUST be sorted by ascending ``time``.  Uses a two-pointer
    sweep so the total cost is O(len(candles_1h) + len(candles_15m)).

    Edge cases handled:
      - Missing 15m bars (gaps): the hour simply gets fewer than 4 entries.
      - DST / timezone shifts: irrelevant because we operate on unix epoch
        seconds and use a fixed 3600-second window.
      - 15m bars that fall outside any 1H window are silently skipped.

    Returns
    -------
    dict[int, list[int]]
        Keys are 1H candle indices (0-based), values are sorted lists of
        matching 15m candle indices.
    """
    hour_map: dict[int, list[int]] = {}

    if not candles_1h:
        return hour_map

    n_1h = len(candles_1h)
    n_15m = len(candles_15m)

    # Two-pointer: j walks through 15m bars, i walks through 1H bars.
    j = 0
    for i in range(n_1h):
        ts_start = candles_1h[i]["time"]
        ts_end = ts_start + SECONDS_PER_HOUR
        indices: list[int] = []

        # Skip any 15m bars that fall before this hour window.
        while j < n_15m and candles_15m[j]["time"] < ts_start:
            j += 1

        # Collect all 15m bars inside [ts_start, ts_end).
        # Use a lookahead pointer so we don't consume bars that may also
        # belong to this window on re-entry (not possible with sorted,
        # non-overlapping 1H windows, but kept explicit for clarity).
        k = j
        while k < n_15m and candles_15m[k]["time"] < ts_end:
            indices.append(k)
            k += 1

        hour_map[i] = indices

        # Advance j to k -- all bars before k are either consumed or belong
        # to this hour (and therefore cannot belong to a later hour since 1H
        # windows are non-overlapping and sorted).
        j = k

    return hour_map


def get_15m_bars_for_hour(hour_map: dict[int, list[int]], hour_idx: int) -> list[int]:
    """Return the list of 15m bar indices for *hour_idx*.

    Returns an empty list when *hour_idx* is not present in the map.
    """
    return hour_map.get(hour_idx, [])


def get_15m_ohlcv_for_hour(
    candles_15m: list[dict],
    hour_map: dict[int, list[int]],
    hour_idx: int,
) -> dict:
    """Aggregate OHLCV data from the 15m bars that belong to *hour_idx*.

    Returns
    -------
    dict with keys:
        opens, highs, lows, closes, volumes : list[float]
        n           : int   -- number of 15m bars found
        last_close  : float -- close of last 15m bar (NaN if n == 0)
        last_is_green : bool -- last 15m close > last 15m open (False if n == 0)
        min_low     : float -- lowest low  (NaN if n == 0)
        max_high    : float -- highest high (NaN if n == 0)
    """
    indices = get_15m_bars_for_hour(hour_map, hour_idx)
    n = len(indices)

    if n == 0:
        return {
            "opens": [],
            "highs": [],
            "lows": [],
            "closes": [],
            "volumes": [],
            "n": 0,
            "last_close": float("nan"),
            "last_is_green": False,
            "min_low": float("nan"),
            "max_high": float("nan"),
        }

    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []

    for idx in indices:
        bar = candles_15m[idx]
        opens.append(float(bar["open"]))
        highs.append(float(bar["high"]))
        lows.append(float(bar["low"]))
        closes.append(float(bar["close"]))
        volumes.append(float(bar["volume"]))

    last_bar = candles_15m[indices[-1]]

    return {
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        "n": n,
        "last_close": float(last_bar["close"]),
        "last_is_green": float(last_bar["close"]) > float(last_bar["open"]),
        "min_low": min(lows),
        "max_high": max(highs),
    }


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import math
    import sys

    passed = 0
    failed = 0

    def _check(condition: bool, label: str) -> None:
        global passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {label}", file=sys.stderr)

    def _make_bar(ts: int, o: float = 1.0, h: float = 2.0,
                  l: float = 0.5, c: float = 1.5, v: float = 100.0) -> dict:
        return {"time": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}

    # ------------------------------------------------------------------
    # 1. Perfectly aligned data: 3 hours, 4 x 15m bars per hour
    # ------------------------------------------------------------------
    base = 1_700_000_000  # arbitrary epoch

    candles_1h = [
        _make_bar(base),
        _make_bar(base + 3600),
        _make_bar(base + 7200),
    ]
    candles_15m = []
    for h in range(3):
        for q in range(4):
            ts = base + h * 3600 + q * 900
            candles_15m.append(
                _make_bar(ts, o=1.0 + q * 0.1, h=2.0 + q * 0.1,
                          l=0.5 + q * 0.1, c=1.5 + q * 0.1, v=100.0 + q)
            )

    hmap = build_hour_to_15m_map(candles_1h, candles_15m)

    _check(len(hmap) == 3, "aligned: 3 hours in map")
    _check(hmap[0] == [0, 1, 2, 3], "aligned: hour 0 -> [0,1,2,3]")
    _check(hmap[1] == [4, 5, 6, 7], "aligned: hour 1 -> [4,5,6,7]")
    _check(hmap[2] == [8, 9, 10, 11], "aligned: hour 2 -> [8,9,10,11]")

    # get_15m_bars_for_hour accessor
    _check(get_15m_bars_for_hour(hmap, 0) == [0, 1, 2, 3], "accessor: hour 0")
    _check(get_15m_bars_for_hour(hmap, 1) == [4, 5, 6, 7], "accessor: hour 1")
    _check(get_15m_bars_for_hour(hmap, 99) == [], "accessor: missing hour returns []")

    # get_15m_ohlcv_for_hour -- check hour 0
    agg = get_15m_ohlcv_for_hour(candles_15m, hmap, 0)
    _check(agg["n"] == 4, "ohlcv aligned: n == 4")
    _check(len(agg["opens"]) == 4, "ohlcv aligned: 4 opens")
    _check(len(agg["closes"]) == 4, "ohlcv aligned: 4 closes")
    _check(abs(agg["last_close"] - 1.8) < 1e-9, "ohlcv aligned: last_close == 1.8")
    _check(agg["last_is_green"] is True, "ohlcv aligned: last bar green (1.8 > 1.3)")
    _check(abs(agg["min_low"] - 0.5) < 1e-9, "ohlcv aligned: min_low == 0.5")
    _check(abs(agg["max_high"] - 2.3) < 1e-9, "ohlcv aligned: max_high == 2.3")
    _check(abs(agg["volumes"][0] - 100.0) < 1e-9, "ohlcv aligned: first volume == 100")
    _check(abs(agg["volumes"][3] - 103.0) < 1e-9, "ohlcv aligned: last volume == 103")

    # ------------------------------------------------------------------
    # 2. Missing bars (gap): hour 1 only has 3 bars (second 15m bar missing)
    # ------------------------------------------------------------------
    candles_15m_gap = []
    # Hour 0: all 4
    for q in range(4):
        candles_15m_gap.append(_make_bar(base + q * 900))
    # Hour 1: skip q=1 (the 15-minute-mark bar)
    for q in [0, 2, 3]:
        candles_15m_gap.append(_make_bar(base + 3600 + q * 900))
    # Hour 2: all 4
    for q in range(4):
        candles_15m_gap.append(_make_bar(base + 7200 + q * 900))

    hmap_gap = build_hour_to_15m_map(candles_1h, candles_15m_gap)

    _check(len(hmap_gap[0]) == 4, "gap: hour 0 has 4 bars")
    _check(len(hmap_gap[1]) == 3, "gap: hour 1 has 3 bars (missing one)")
    _check(len(hmap_gap[2]) == 4, "gap: hour 2 has 4 bars")
    # Verify indices are correct
    _check(hmap_gap[0] == [0, 1, 2, 3], "gap: hour 0 indices")
    _check(hmap_gap[1] == [4, 5, 6], "gap: hour 1 indices (3 bars)")
    _check(hmap_gap[2] == [7, 8, 9, 10], "gap: hour 2 indices")

    agg_gap = get_15m_ohlcv_for_hour(candles_15m_gap, hmap_gap, 1)
    _check(agg_gap["n"] == 3, "ohlcv gap: n == 3")

    # ------------------------------------------------------------------
    # 3. Empty inputs
    # ------------------------------------------------------------------
    _check(build_hour_to_15m_map([], []) == {}, "empty: both empty")
    _check(build_hour_to_15m_map(candles_1h, []) == {0: [], 1: [], 2: []},
           "empty: no 15m bars -> all hours have []")
    _check(build_hour_to_15m_map([], candles_15m) == {}, "empty: no 1h bars -> {}")

    # ------------------------------------------------------------------
    # 4. Empty ohlcv aggregation (hour not in map)
    # ------------------------------------------------------------------
    agg_empty = get_15m_ohlcv_for_hour(candles_15m, hmap, 999)
    _check(agg_empty["n"] == 0, "ohlcv empty: n == 0")
    _check(agg_empty["opens"] == [], "ohlcv empty: opens == []")
    _check(math.isnan(agg_empty["last_close"]), "ohlcv empty: last_close is NaN")
    _check(agg_empty["last_is_green"] is False, "ohlcv empty: last_is_green is False")
    _check(math.isnan(agg_empty["min_low"]), "ohlcv empty: min_low is NaN")
    _check(math.isnan(agg_empty["max_high"]), "ohlcv empty: max_high is NaN")

    # ------------------------------------------------------------------
    # 5. last_is_green = False when last bar is red
    # ------------------------------------------------------------------
    candles_15m_red = [
        _make_bar(base, o=2.0, c=1.0),       # red
        _make_bar(base + 900, o=2.0, c=1.0),  # red
    ]
    candles_1h_single = [_make_bar(base)]
    hmap_red = build_hour_to_15m_map(candles_1h_single, candles_15m_red)
    agg_red = get_15m_ohlcv_for_hour(candles_15m_red, hmap_red, 0)
    _check(agg_red["last_is_green"] is False, "red bar: last_is_green is False")

    # ------------------------------------------------------------------
    # 6. last_is_green = False when last bar is doji (close == open)
    # ------------------------------------------------------------------
    candles_15m_doji = [_make_bar(base, o=1.5, c=1.5)]
    hmap_doji = build_hour_to_15m_map(candles_1h_single, candles_15m_doji)
    agg_doji = get_15m_ohlcv_for_hour(candles_15m_doji, hmap_doji, 0)
    _check(agg_doji["last_is_green"] is False, "doji bar: last_is_green is False")

    # ------------------------------------------------------------------
    # 7. 15m bars that fall outside any 1H window are skipped
    # ------------------------------------------------------------------
    candles_1h_narrow = [_make_bar(base + 3600)]  # only hour 1
    candles_15m_wide = [
        _make_bar(base),             # before hour 1
        _make_bar(base + 3600),      # inside hour 1
        _make_bar(base + 4500),      # inside hour 1
        _make_bar(base + 7200),      # after hour 1
    ]
    hmap_narrow = build_hour_to_15m_map(candles_1h_narrow, candles_15m_wide)
    _check(hmap_narrow[0] == [1, 2], "narrow: only 2 bars inside the single hour")

    # ------------------------------------------------------------------
    # 8. Large-scale correctness: 100 hours, 400 bars
    # ------------------------------------------------------------------
    n_hours = 100
    big_1h = [_make_bar(base + i * 3600) for i in range(n_hours)]
    big_15m = []
    for i in range(n_hours):
        for q in range(4):
            big_15m.append(_make_bar(base + i * 3600 + q * 900))

    hmap_big = build_hour_to_15m_map(big_1h, big_15m)
    _check(len(hmap_big) == n_hours, "big: 100 hours in map")
    all_four = all(len(hmap_big[i]) == 4 for i in range(n_hours))
    _check(all_four, "big: every hour has exactly 4 bars")
    # Verify index continuity
    expected_idx = 0
    idx_ok = True
    for i in range(n_hours):
        for actual in hmap_big[i]:
            if actual != expected_idx:
                idx_ok = False
                break
            expected_idx += 1
    _check(idx_ok, "big: indices are contiguous 0..399")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = passed + failed
    if failed == 0:
        print(f"All {total} self-tests PASS")
    else:
        print(f"{failed}/{total} self-tests FAILED", file=sys.stderr)
        sys.exit(1)
