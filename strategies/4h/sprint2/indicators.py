"""
Sprint 2 Extended Indicator Library
====================================
Extends Sprint 1 indicators with:
  - dc_prev_high: Donchian previous high (causal, for breakout signals)
  - plus_di / minus_di: Directional indicators (from ADX computation)

Reuses all Sprint 1 indicators via precompute_all() extension.

All functions are pure: lists in, scalar or list out. No side effects.
All use causal data only (no look-ahead).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 4h is not a valid Python identifier → use importlib
_sprint1_ind = importlib.import_module("strategies.4h.sprint1.indicators")

# Re-export Sprint 1 indicator functions
calc_ema = _sprint1_ind.calc_ema
calc_sma = _sprint1_ind.calc_sma
calc_adx = _sprint1_ind.calc_adx
calc_obv = _sprint1_ind.calc_obv
calc_bb_width_ratio = _sprint1_ind.calc_bb_width_ratio

# Re-export Sprint 1 constants
DC_PERIOD = _sprint1_ind.DC_PERIOD
BB_PERIOD = _sprint1_ind.BB_PERIOD
BB_DEV = _sprint1_ind.BB_DEV
RSI_PERIOD = _sprint1_ind.RSI_PERIOD
ATR_PERIOD = _sprint1_ind.ATR_PERIOD
EMA_FAST = _sprint1_ind.EMA_FAST
EMA_SLOW = _sprint1_ind.EMA_SLOW
SMA_PERIOD = _sprint1_ind.SMA_PERIOD
ADX_PERIOD = _sprint1_ind.ADX_PERIOD
VOL_AVG_PERIOD = _sprint1_ind.VOL_AVG_PERIOD

from trading_bot.strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger


# ---------------------------------------------------------------------------
# New indicator functions
# ---------------------------------------------------------------------------

def calc_directional_indicators(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> tuple[list[float | None], list[float | None]]:
    """Compute +DI and -DI (Directional Indicators).

    Returns (plus_di, minus_di) — each a list same length as input.
    None until enough bars (period + 1).

    Uses Wilder smoothing (same as calc_adx but exposes DI values).
    """
    n = len(highs)
    plus_di_arr: list[float | None] = [None] * n
    minus_di_arr: list[float | None] = [None] * n

    if n < period + 1:
        return plus_di_arr, minus_di_arr

    # Step 1: +DM, -DM, TR series (from bar 1 onward)
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

    if len(tr_list) < period:
        return plus_di_arr, minus_di_arr

    # Step 2: Wilder smoothing — seed with sum of first period values
    smoothed_pdm = sum(plus_dm[:period])
    smoothed_mdm = sum(minus_dm[:period])
    smoothed_tr = sum(tr_list[:period])

    # First DI values at bar = period (index period in original series)
    if smoothed_tr > 0:
        plus_di_arr[period] = 100.0 * smoothed_pdm / smoothed_tr
        minus_di_arr[period] = 100.0 * smoothed_mdm / smoothed_tr

    for i in range(period, len(tr_list)):
        smoothed_pdm = smoothed_pdm - smoothed_pdm / period + plus_dm[i]
        smoothed_mdm = smoothed_mdm - smoothed_mdm / period + minus_dm[i]
        smoothed_tr = smoothed_tr - smoothed_tr / period + tr_list[i]

        idx = i + 1  # bar index in original series
        if idx < n and smoothed_tr > 0:
            plus_di_arr[idx] = 100.0 * smoothed_pdm / smoothed_tr
            minus_di_arr[idx] = 100.0 * smoothed_mdm / smoothed_tr

    return plus_di_arr, minus_di_arr


# ---------------------------------------------------------------------------
# Extended precompute_all for Sprint 2
# ---------------------------------------------------------------------------

def precompute_all(data: dict, coins: list[str]) -> dict:
    """Precompute all indicators for all coins (Sprint 2 extended).

    Extends Sprint 1 precompute_all with:
      - dc_prev_high: Donchian previous high (max of highs[bar-DC:bar])
      - plus_di, minus_di: Directional indicators
      - __coin__: pair name (for cross-sectional signal access)

    Returns {pair: {all Sprint 1 indicators + dc_prev_high + plus_di + minus_di + __coin__}}
    """
    # Start with Sprint 1 indicators
    indicators = _sprint1_ind.precompute_all(data, coins)

    # Extend each coin
    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue

        n = ind["n"]
        highs = ind["highs"]
        lows = ind["lows"]
        closes = ind["closes"]

        # dc_prev_high: Donchian previous high (causal: bar-DC_PERIOD to bar, exclusive)
        # Same pattern as existing dc_prev_low
        dc_prev_high = [None] * n
        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5
        for bar in range(min_bars, n):
            wh = highs[bar - DC_PERIOD: bar]  # excludes current bar
            if wh:
                dc_prev_high[bar] = max(wh)

        # Directional indicators (+DI, -DI)
        plus_di, minus_di = calc_directional_indicators(
            highs, lows, closes, ADX_PERIOD
        )

        # Extend the indicator dict
        ind["dc_prev_high"] = dc_prev_high
        ind["plus_di"] = plus_di
        ind["minus_di"] = minus_di
        ind["__coin__"] = pair

    return indicators


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick sanity checks on new indicator functions

    # Directional Indicators
    h = [10 + i * 0.5 + (i % 3) * 0.2 for i in range(60)]
    l = [9 + i * 0.5 - (i % 3) * 0.2 for i in range(60)]
    c = [9.5 + i * 0.5 for i in range(60)]

    pdi, mdi = calc_directional_indicators(h, l, c, 14)
    pdi_vals = [v for v in pdi if v is not None]
    mdi_vals = [v for v in mdi if v is not None]
    assert len(pdi_vals) > 0, "+DI should have some values with 60 bars"
    assert len(mdi_vals) > 0, "-DI should have some values with 60 bars"
    assert all(0 <= v <= 100 for v in pdi_vals), "+DI should be 0-100"
    assert all(0 <= v <= 100 for v in mdi_vals), "-DI should be 0-100"
    print(f"  +DI(14) OK: {len(pdi_vals)} values, range {min(pdi_vals):.1f}-{max(pdi_vals):.1f}")
    print(f"  -DI(14) OK: {len(mdi_vals)} values, range {min(mdi_vals):.1f}-{max(mdi_vals):.1f}")

    # dc_prev_high: simple check
    print("\n  Creating synthetic data for precompute_all test...")
    import random
    random.seed(42)
    test_data = {}
    test_coins = ["TEST/USD"]
    candles = []
    price = 100.0
    for i in range(100):
        o = price
        h = price + random.uniform(0, 5)
        l = price - random.uniform(0, 5)
        c = price + random.uniform(-3, 3)
        v = random.uniform(1000, 10000)
        candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    test_data["TEST/USD"] = candles

    result = precompute_all(test_data, test_coins)
    assert "TEST/USD" in result
    ind = result["TEST/USD"]
    assert "dc_prev_high" in ind
    assert "__coin__" in ind
    assert ind["__coin__"] == "TEST/USD"
    assert "plus_di" in ind
    assert "minus_di" in ind

    # Verify dc_prev_high causality: value at bar N uses bars [N-20:N)
    for bar in range(30, 80):
        if ind["dc_prev_high"][bar] is not None:
            expected = max(ind["highs"][bar - 20: bar])
            assert abs(ind["dc_prev_high"][bar] - expected) < 1e-10, \
                f"dc_prev_high causality violation at bar {bar}"

    print(f"  precompute_all OK: dc_prev_high causal, +DI/-DI present, __coin__ = TEST/USD")
    print("\n  All Sprint 2 indicator sanity checks passed")
