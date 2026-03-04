"""
Scalp MS Indicators — Market Structure + Technical indicators for 1m scalping.
===============================================================================

Combines:
  - Scalp technical indicators (RSI, ATR, BB, EMA, VWAP) from indicators.py
  - Market Structure detectors (swings, FVG, BoS, OB, LiqZones) from ms/indicators.py

Does NOT use precompute_ms_indicators() (which depends on 4H Sprint 2).
Instead, calls standalone detector functions directly.

precompute_fn protocol:
    precompute_scalp_ms_indicators(data, coins, **kwargs) → dict[str, dict]

Output per coin:
    Technical: closes, highs, lows, opens, volumes, rsi14, rsi5, atr14, atr (alias),
               bb_mid/upper/lower, bb_width, ema9, ema21, vwap60, vol_ratio, vol_avg
    Structural: swing_lows, swing_highs, fvg_snapshots, bos_events, ob_snapshots, liq_zones
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─── Scalp technical indicators (reuse) ───────────────────────
from strategies.scalp.indicators import (
    _calc_rsi,
    _calc_ema,
    _calc_atr,
    _calc_bollinger,
    _calc_vwap_rolling,
    _calc_volume_ratio,
    _calc_bb_width,
)

# ─── MS structural detectors (READ-ONLY imports) ──────────────
from strategies.ms.indicators import (
    calc_swing_lows,
    calc_swing_highs,
    calc_fair_value_gaps,
    calc_break_of_structure,
    calc_order_blocks,
    calc_liquidity_zones,
)


def _calc_sma(values: list[float], period: int) -> list[float | None]:
    """Simple Moving Average. Returns list aligned with input."""
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(values[i - period + 1: i + 1]) / period
    return result


def precompute_scalp_ms_indicators(
    data: dict[str, list[dict]],
    coins: list[str],
    swing_left: int = 3,
    swing_right: int = 1,
    min_gap_atr: float = 0.3,
    min_impulse_atr: float = 1.5,
    lookback_impulse: int = 3,
    tolerance_atr: float = 0.5,
    min_touches: int = 2,
    **kwargs,
) -> dict[str, dict]:
    """
    Compute all indicators for MS-based scalp strategies.

    Args:
        data: {'XRP/USDT': [candles], ...}
        coins: ['XRP/USDT']
        swing_left: fractal pivot left lookback (default 3 for 1m)
        swing_right: fractal pivot right lookback (default 1 for 1m)
        min_gap_atr: minimum FVG size in ATR units
        min_impulse_atr: minimum OB impulse in ATR units
        lookback_impulse: bars to look back for OB impulse
        tolerance_atr: liquidity zone clustering tolerance
        min_touches: minimum swing touches for liquidity zone

    Returns:
        {'XRP/USDT': {'n': int, 'closes': [...], 'swing_lows': [...], ...}}
    """
    result = {}

    for pair in coins:
        if pair not in data:
            continue

        candles = data[pair]
        n = len(candles)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        opens = [c['open'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        # ─── Technical indicators (from scalp/indicators.py) ───
        rsi14 = _calc_rsi(closes, 14)
        rsi5 = _calc_rsi(closes, 5)
        bb_mid, bb_upper, bb_lower = _calc_bollinger(closes, 20, 2.0)
        bb_width = _calc_bb_width(bb_upper, bb_lower, bb_mid)
        atr14 = _calc_atr(highs, lows, closes, 14)
        ema9 = _calc_ema(closes, 9)
        ema21 = _calc_ema(closes, 21)
        vwap60 = _calc_vwap_rolling(closes, volumes, 60)
        vol_ratio = _calc_volume_ratio(volumes, 20)
        vol_avg = _calc_sma(volumes, 20)

        # ─── Structural indicators (from ms/indicators.py) ────
        swing_low_arr = calc_swing_lows(lows, swing_left, swing_right)
        swing_high_arr = calc_swing_highs(highs, swing_left, swing_right)

        fvg_snapshots = calc_fair_value_gaps(
            highs, lows, closes, atr14, min_gap_atr=min_gap_atr,
        )

        bos_events = calc_break_of_structure(
            closes, swing_high_arr, swing_low_arr, atr14,
        )

        ob_snapshots = calc_order_blocks(
            opens, highs, lows, closes, atr14,
            min_impulse_atr=min_impulse_atr,
            lookback_impulse=lookback_impulse,
        )

        liq_zones = calc_liquidity_zones(
            swing_low_arr, swing_high_arr, atr14,
            tolerance_atr=tolerance_atr,
            min_touches=min_touches,
        )

        result[pair] = {
            'n': n,
            # Price arrays
            'closes': closes,
            'highs': highs,
            'lows': lows,
            'opens': opens,
            'volumes': volumes,
            # Technical indicators
            'rsi14': rsi14,
            'rsi5': rsi5,
            'bb_mid': bb_mid,
            'bb_upper': bb_upper,
            'bb_lower': bb_lower,
            'bb_width': bb_width,
            'atr14': atr14,
            'ema9': ema9,
            'ema21': ema21,
            'vwap60': vwap60,
            'vol_ratio': vol_ratio,
            'vol_avg': vol_avg,
            # Aliases (MS signal compatibility)
            'atr': atr14,
            'rsi': rsi14,
            # Structural indicators
            'swing_lows': swing_low_arr,
            'swing_highs': swing_high_arr,
            'fvg_snapshots': fvg_snapshots,
            'bos_events': bos_events,
            'ob_snapshots': ob_snapshots,
            'liq_zones': liq_zones,
        }

    return result
