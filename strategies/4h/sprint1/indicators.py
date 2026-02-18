"""
Extended indicator library for Sprint 1 screening.

Reuses calc_rsi, calc_atr, calc_donchian, calc_bollinger from trading_bot/strategy.py.
Adds: EMA, SMA, ADX, OBV, BB width ratio.

All functions are pure: lists in, scalar or list out. No side effects.
All use causal data only (no look-ahead).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading_bot"))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger


# ---------------------------------------------------------------------------
# New indicator functions
# ---------------------------------------------------------------------------

def calc_ema(values: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average. Returns list same length as values.

    First `period - 1` entries are None (insufficient data).
    EMA seed = SMA of first `period` values.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    # Seed with SMA
    sma = sum(values[:period]) / period
    result[period - 1] = sma
    mult = 2.0 / (period + 1)

    for i in range(period, n):
        prev = result[i - 1]
        result[i] = values[i] * mult + prev * (1.0 - mult)

    return result


def calc_sma(values: list[float], period: int) -> list[float | None]:
    """Simple Moving Average. Returns list same length as values.

    First `period - 1` entries are None.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period
    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period

    return result


def calc_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """Average Directional Index (Wilder smoothing).

    Returns list same length as input. None until enough bars.
    """
    n = len(highs)
    result: list[float | None] = [None] * n
    if n < period * 2 + 1:
        return result

    # Step 1: +DM, -DM, TR series
    plus_dm = []
    minus_dm = []
    tr_list = []
    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]

        pdm = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
        mdm = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        plus_dm.append(pdm)
        minus_dm.append(mdm)
        tr_list.append(tr)

    # Step 2: Wilder smoothing (first period values, then exponential)
    if len(tr_list) < period:
        return result

    smoothed_pdm = sum(plus_dm[:period])
    smoothed_mdm = sum(minus_dm[:period])
    smoothed_tr = sum(tr_list[:period])

    dx_values = []

    for i in range(period, len(tr_list)):
        smoothed_pdm = smoothed_pdm - smoothed_pdm / period + plus_dm[i]
        smoothed_mdm = smoothed_mdm - smoothed_mdm / period + minus_dm[i]
        smoothed_tr = smoothed_tr - smoothed_tr / period + tr_list[i]

        if smoothed_tr == 0:
            dx_values.append(0.0)
            continue

        plus_di = 100.0 * smoothed_pdm / smoothed_tr
        minus_di = 100.0 * smoothed_mdm / smoothed_tr
        di_sum = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0.0
        dx_values.append(dx)

    # Step 3: ADX = SMA of DX over period
    if len(dx_values) < period:
        return result

    adx = sum(dx_values[:period]) / period
    # Map back to original bar index
    # tr_list starts at bar 1, smoothed values start at bar period+1,
    # DX values start at bar period+1. ADX starts at bar 2*period+1.
    start_idx = 2 * period
    if start_idx < n:
        result[start_idx] = adx

    for j in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[j]) / period
        idx = period + 1 + j  # bar index in original series
        if idx < n:
            result[idx] = adx

    return result


def calc_obv(closes: list[float], volumes: list[float]) -> list[float]:
    """On-Balance Volume. Returns list same length as input.

    Always has a value (starts at 0 for bar 0).
    """
    n = len(closes)
    if n == 0:
        return []
    result = [0.0] * n
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            result[i] = result[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            result[i] = result[i - 1] - volumes[i]
        else:
            result[i] = result[i - 1]
    return result


def calc_bb_width_ratio(closes: list[float], period: int = 20, dev: float = 2.0) -> list[float | None]:
    """Bollinger Band width as ratio of mid (squeeze indicator).

    BB width = (upper - lower) / mid
    Lower values = tighter squeeze.
    Returns list same length as closes, None where BB is not available.
    """
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mid = sum(window) / period
        if mid == 0:
            continue
        variance = sum((x - mid) ** 2 for x in window) / period
        std = variance ** 0.5
        upper = mid + dev * std
        lower = mid - dev * std
        result[i] = (upper - lower) / mid

    return result


# ---------------------------------------------------------------------------
# Precompute all indicators for a coin set
# ---------------------------------------------------------------------------

# Indicator periods — match agent_team_v3 constants
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
SMA_PERIOD = 50
ADX_PERIOD = 14
VOL_AVG_PERIOD = 20


def precompute_all(data: dict, coins: list[str]) -> dict:
    """Precompute all indicators for all coins.

    Returns {pair: {rsi, atr, dc_prev_low, dc_mid, bb_mid, bb_lower, bb_width,
                    vol_avg, ema20, ema50, sma50, adx, obv, closes, highs, lows,
                    volumes, n}}
    """
    indicators = {}

    for pair in coins:
        candles = data.get(pair, [])
        n = len(candles)
        if n == 0:
            continue

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c.get("volume", 0) for c in candles]

        # Base indicators (from strategy.py)
        rsi = [None] * n
        atr_arr = [None] * n
        dc_prev_low = [None] * n
        dc_mid = [None] * n
        bb_mid = [None] * n
        bb_lower = [None] * n
        vol_avg = [None] * n

        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5

        for bar in range(min_bars, n):
            rsi[bar] = calc_rsi(closes[: bar + 1], RSI_PERIOD)
            atr_arr[bar] = calc_atr(
                highs[: bar + 1], lows[: bar + 1], closes[: bar + 1], ATR_PERIOD
            )

            # Donchian — causal: use [:-1] for entry (prev bar's channel)
            wh = highs[bar - DC_PERIOD : bar]  # excludes current bar
            wl = lows[bar - DC_PERIOD : bar]
            if wh and wl:
                dc_prev_low[bar] = min(wl)

            # Donchian mid — includes current bar (for exit targets)
            wh_full = highs[bar - DC_PERIOD + 1 : bar + 1]
            wl_full = lows[bar - DC_PERIOD + 1 : bar + 1]
            if wh_full and wl_full:
                dc_mid[bar] = (max(wh_full) + min(wl_full)) / 2

            # Bollinger Bands
            bb = calc_bollinger(closes[: bar + 1], BB_PERIOD, BB_DEV)
            if bb[0] is not None:
                bb_mid[bar] = bb[0]
                bb_lower[bar] = bb[2]

            # Volume average
            vol_window = volumes[max(0, bar - VOL_AVG_PERIOD + 1) : bar + 1]
            if len(vol_window) >= VOL_AVG_PERIOD:
                vol_avg[bar] = sum(vol_window) / len(vol_window)

        # Extended indicators
        ema20 = calc_ema(closes, EMA_FAST)
        ema50 = calc_ema(closes, EMA_SLOW)
        sma50 = calc_sma(closes, SMA_PERIOD)
        adx = calc_adx(highs, lows, closes, ADX_PERIOD)
        obv = calc_obv(closes, volumes)
        bb_width = calc_bb_width_ratio(closes, BB_PERIOD, BB_DEV)

        indicators[pair] = {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "n": n,
            "rsi": rsi,
            "atr": atr_arr,
            "dc_prev_low": dc_prev_low,
            "dc_mid": dc_mid,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "bb_width": bb_width,
            "vol_avg": vol_avg,
            "ema20": ema20,
            "ema50": ema50,
            "sma50": sma50,
            "adx": adx,
            "obv": obv,
        }

    return indicators


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick sanity checks on indicator functions
    import math

    # EMA
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    ema3 = calc_ema(vals, 3)
    assert ema3[0] is None
    assert ema3[1] is None
    assert ema3[2] == 2.0  # SMA seed
    assert ema3[3] is not None
    print(f"  EMA(3) OK: {ema3}")

    # SMA
    sma3 = calc_sma(vals, 3)
    assert sma3[0] is None
    assert sma3[1] is None
    assert sma3[2] == 2.0
    assert sma3[3] == 3.0
    print(f"  SMA(3) OK: {sma3}")

    # ADX — need enough data
    h = [10 + i * 0.5 + (i % 3) * 0.2 for i in range(60)]
    l = [9 + i * 0.5 - (i % 3) * 0.2 for i in range(60)]
    c = [9.5 + i * 0.5 for i in range(60)]
    adx_vals = calc_adx(h, l, c, 14)
    non_none = [v for v in adx_vals if v is not None]
    assert len(non_none) > 0, "ADX should have some values with 60 bars"
    assert all(0 <= v <= 100 for v in non_none), "ADX values should be 0-100"
    print(f"  ADX(14) OK: {len(non_none)} values, range {min(non_none):.1f}-{max(non_none):.1f}")

    # OBV
    c2 = [1.0, 2.0, 1.5, 3.0, 2.5]
    v2 = [100, 200, 150, 300, 250]
    obv_vals = calc_obv(c2, v2)
    assert obv_vals[0] == 0
    assert obv_vals[1] == 200  # up
    assert obv_vals[2] == 50   # down
    assert obv_vals[3] == 350  # up
    assert obv_vals[4] == 100  # down
    print(f"  OBV OK: {obv_vals}")

    # BB width ratio
    c3 = [100 + (i % 5) * 2 - 4 for i in range(30)]
    bw = calc_bb_width_ratio(c3, 20, 2.0)
    non_none_bw = [v for v in bw if v is not None]
    assert len(non_none_bw) > 0
    assert all(v > 0 for v in non_none_bw)
    print(f"  BB Width OK: {len(non_none_bw)} values")

    print("\n  All indicator sanity checks passed")
