"""
Scalp Indicators — 1-minute technical indicators for XRP/USDT scalping.
======================================================================

Computes: RSI(14), RSI(5), BB(20,2), ATR(14), EMA(9), EMA(21),
          VWAP(60-bar rolling), volume ratio.

Follows precompute_fn protocol:
    precompute_scalp_indicators(data, coins, **kwargs) → dict

Output per coin:
    {'n': int, 'closes': [...], 'rsi14': [...], 'bb_upper': [...], ...}
    All lists length = n. Early bars = None.

Reuses: calc_rsi, calc_bollinger from trading_bot/strategy.py (utility functions only)
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _calc_rsi(closes: list[float], period: int) -> list[float | None]:
    """Rolling RSI computation. Returns list aligned with closes."""
    n = len(closes)
    result = [None] * n
    if n < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    # Initial average
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss > 0:
        rs = avg_gain / avg_loss
        result[period] = 100 - (100 / (1 + rs))
    else:
        result[period] = 100.0

    # Smoothed RSI
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            result[i + 1] = 100 - (100 / (1 + rs))
        else:
            result[i + 1] = 100.0

    return result


def _calc_ema(values: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average. Returns list aligned with input."""
    n = len(values)
    result = [None] * n
    if n < period:
        return result

    # SMA seed
    sma = sum(values[:period]) / period
    result[period - 1] = sma

    mult = 2.0 / (period + 1)
    for i in range(period, n):
        result[i] = (values[i] - result[i - 1]) * mult + result[i - 1]

    return result


def _calc_atr(highs: list[float], lows: list[float], closes: list[float],
              period: int = 14) -> list[float | None]:
    """Rolling ATR. Returns list aligned with input."""
    n = len(highs)
    result = [None] * n
    if n < period + 1:
        return result

    trs = [0.0]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    # SMA seed
    result[period] = sum(trs[1:period + 1]) / period
    # Smoothed ATR (Wilder)
    for i in range(period + 1, n):
        result[i] = (result[i - 1] * (period - 1) + trs[i]) / period

    return result


def _calc_bollinger(closes: list[float], period: int = 20,
                    num_std: float = 2.0) -> tuple[list, list, list]:
    """Bollinger Bands. Returns (mid, upper, lower) lists."""
    n = len(closes)
    mid = [None] * n
    upper = [None] * n
    lower = [None] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = variance ** 0.5
        mid[i] = sma
        upper[i] = sma + num_std * std
        lower[i] = sma - num_std * std

    return mid, upper, lower


def _calc_vwap_rolling(closes: list[float], volumes: list[float],
                       window: int = 60) -> list[float | None]:
    """Rolling VWAP approximation over `window` bars."""
    n = len(closes)
    result = [None] * n

    for i in range(window - 1, n):
        pv_sum = 0.0
        v_sum = 0.0
        for j in range(i - window + 1, i + 1):
            pv_sum += closes[j] * volumes[j]
            v_sum += volumes[j]
        result[i] = pv_sum / v_sum if v_sum > 0 else closes[i]

    return result


def _calc_volume_ratio(volumes: list[float], period: int = 20) -> list[float | None]:
    """Volume relative to its SMA. ratio > 1 = above average."""
    n = len(volumes)
    result = [None] * n

    for i in range(period - 1, n):
        avg = sum(volumes[i - period + 1: i + 1]) / period
        result[i] = volumes[i] / avg if avg > 0 else 1.0

    return result


def _calc_bb_width(upper: list, lower: list, mid: list) -> list[float | None]:
    """Bollinger Band width as fraction of mid (squeeze detector)."""
    n = len(upper)
    result = [None] * n
    for i in range(n):
        if upper[i] is not None and lower[i] is not None and mid[i] and mid[i] > 0:
            result[i] = (upper[i] - lower[i]) / mid[i]
    return result


def precompute_scalp_indicators(
    data: dict[str, list[dict]],
    coins: list[str],
    **kwargs,
) -> dict[str, dict]:
    """
    Compute all indicators for scalp strategies.

    Args:
        data: {'XRP/USDT': [candles], ...}
        coins: ['XRP/USDT']

    Returns:
        {'XRP/USDT': {'n': int, 'closes': [...], 'rsi14': [...], ...}}
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
        volumes = [c.get('volume', 0) for c in candles]

        # RSI
        rsi14 = _calc_rsi(closes, 14)
        rsi5 = _calc_rsi(closes, 5)

        # Bollinger Bands
        bb_mid, bb_upper, bb_lower = _calc_bollinger(closes, 20, 2.0)
        bb_width = _calc_bb_width(bb_upper, bb_lower, bb_mid)

        # ATR
        atr14 = _calc_atr(highs, lows, closes, 14)

        # EMAs
        ema9 = _calc_ema(closes, 9)
        ema21 = _calc_ema(closes, 21)

        # VWAP (rolling 60-bar)
        vwap60 = _calc_vwap_rolling(closes, volumes, 60)

        # Volume ratio
        vol_ratio = _calc_volume_ratio(volumes, 20)

        result[pair] = {
            'n': n,
            'closes': closes,
            'highs': highs,
            'lows': lows,
            'volumes': volumes,
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
        }

    return result
