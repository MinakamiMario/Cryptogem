#!/usr/bin/env python3
"""
Market Context — Sprint 5
==========================
Precomputes per-bar cross-coin context for hypothesis screening.
Injected into params['__market__'] before backtesting.

CAUSALITY RULE: All context at bar N uses data up to bar N-1 ONLY.
"""
import math
from statistics import stdev

# ---------------------------------------------------------------------------
# BTC key auto-detection
# ---------------------------------------------------------------------------
_BTC_CANDIDATES = ("BTC/USD", "XBT/USD", "BTC/USDT")


def _find_btc_key(coins, btc_key=None):
    """Return the BTC key present in *coins*, or None."""
    if btc_key and btc_key in coins:
        return btc_key
    for candidate in _BTC_CANDIDATES:
        if candidate in coins:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract(candles, field):
    """Extract a list of one OHLCV field from candle dicts."""
    return [c[field] for c in candles]


def _true_ranges(highs, lows, closes):
    """Return list of true-range values (length = len(highs) - 1)."""
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return trs


def _rolling_atr(trs, period=14):
    """Return per-bar ATR from pre-computed true-range list.

    atr[i] = mean(trs[max(0, i-period+1) : i+1]).
    Index i in *trs* corresponds to bar i+1 in OHLCV (because trs starts at bar 1).
    """
    out = []
    for i in range(len(trs)):
        start = max(0, i - period + 1)
        window = trs[start : i + 1]
        out.append(sum(window) / len(window))
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def precompute_market_context(data, coins, btc_key=None):
    """Precompute per-bar cross-coin context arrays.

    Parameters
    ----------
    data : dict[str, list[dict]]
        Mapping coin -> list of OHLCV candle dicts.
    coins : list[str]
        Coin symbols to include.
    btc_key : str | None
        Explicit BTC key. Auto-detected if None.

    Returns
    -------
    dict with keys:
        btc_atr_ratio  : list[float]  — BTC ATR / SMA(ATR,50), length n_bars
        breadth_up     : list[float]  — fraction of coins up, length n_bars
        momentum_rank  : dict[str, list[int]] — per-coin rank (1=best)
        mean_revert_rank : dict[str, list[int]] — per-coin rank (1=most oversold)
    """
    if not coins or not data:
        return {
            "btc_atr_ratio": [],
            "breadth_up": [],
            "momentum_rank": {},
            "mean_revert_rank": {},
        }

    n_bars = max(len(data.get(c, [])) for c in coins)
    if n_bars == 0:
        return {
            "btc_atr_ratio": [],
            "breadth_up": [],
            "momentum_rank": {c: [] for c in coins},
            "mean_revert_rank": {c: [] for c in coins},
        }

    # ------------------------------------------------------------------
    # 1. BTC ATR ratio
    # ------------------------------------------------------------------
    btc = _find_btc_key(coins, btc_key)
    btc_atr_ratio = _compute_btc_atr_ratio(data, btc, n_bars)

    # ------------------------------------------------------------------
    # 2. Breadth (fraction of coins up)
    # ------------------------------------------------------------------
    breadth_up = _compute_breadth_up(data, coins, n_bars)

    # ------------------------------------------------------------------
    # 3. Momentum rank  (vol-adjusted 10-bar return, rank 1 = best)
    # ------------------------------------------------------------------
    momentum_rank = _compute_momentum_rank(data, coins, n_bars)

    # ------------------------------------------------------------------
    # 4. Mean-revert rank  (z-score oversold, rank 1 = most oversold)
    # ------------------------------------------------------------------
    mean_revert_rank = _compute_mean_revert_rank(data, coins, n_bars)

    return {
        "btc_atr_ratio": btc_atr_ratio,
        "breadth_up": breadth_up,
        "momentum_rank": momentum_rank,
        "mean_revert_rank": mean_revert_rank,
    }


# ------------------------------------------------------------------
# Component computations
# ------------------------------------------------------------------

def _compute_btc_atr_ratio(data, btc, n_bars):
    """BTC ATR / SMA(ATR, 50).  Neutral 1.0 when insufficient data."""
    MIN_BARS = 65  # need ~14 TR + 50 SMA window

    if btc is None or btc not in data or len(data[btc]) == 0:
        return [1.0] * n_bars

    candles = data[btc]
    highs = _extract(candles, "high")
    lows = _extract(candles, "low")
    closes = _extract(candles, "close")
    trs = _true_ranges(highs, lows, closes)  # length = len(candles) - 1
    atrs = _rolling_atr(trs, period=14)       # same length as trs

    # atrs[i] uses TRs up to index i, which corresponds to OHLCV bar i+1.
    # So atr "at bar N" (using data up to N-1) means atrs[N-2] (TR index N-2
    # covers bar pair N-2..N-1 in OHLCV, but rolling already uses up to that).
    # More precisely: atrs[k] uses bars 0..k+1 of OHLCV.
    # For context at bar N (using up to bar N-1): we want atrs up to index N-2.

    result = []
    for n in range(n_bars):
        # atr index corresponding to "up to bar n-1":
        # trs[i] uses OHLCV bars i and i+1 -> trs index for bar n-1 is n-2
        atr_idx = n - 2
        if n < MIN_BARS or atr_idx < 13:
            result.append(1.0)
            continue

        current_atr = atrs[atr_idx]

        # SMA of last 50 ATR values ending at atr_idx
        sma_start = max(0, atr_idx - 49)
        sma_window = atrs[sma_start : atr_idx + 1]
        sma_atr = sum(sma_window) / len(sma_window)

        if sma_atr == 0:
            result.append(1.0)
        else:
            result.append(current_atr / sma_atr)

    return result


def _compute_breadth_up(data, coins, n_bars):
    """Fraction of coins where close[N-1] > close[N-2]."""
    result = []
    for n in range(n_bars):
        if n < 2:
            result.append(0.5)
            continue
        up = 0
        total = 0
        for coin in coins:
            candles = data.get(coin, [])
            if len(candles) < n:
                continue
            # close at bar n-1 and n-2
            c_prev = candles[n - 1]["close"]
            c_prev2 = candles[n - 2]["close"]
            total += 1
            if c_prev > c_prev2:
                up += 1
        if total == 0:
            result.append(0.5)
        else:
            result.append(up / total)
    return result


def _compute_momentum_rank(data, coins, n_bars):
    """Rank coins by vol-adjusted 10-bar return. 1 = best momentum."""
    MIN_BARS_NEEDED = 12  # need 11 closes (indices n-11 .. n-1) plus room
    neutral_rank = max(1, len(coins) // 2)

    ranks = {c: [0] * n_bars for c in coins}

    for n in range(n_bars):
        if n < MIN_BARS_NEEDED:
            for c in coins:
                ranks[c][n] = neutral_rank
            continue

        scores = {}
        for coin in coins:
            candles = data.get(coin, [])
            if len(candles) < n:
                scores[coin] = 0.0
                continue
            # closes from bar n-11 to bar n-1 (11 values)
            closes = [candles[i]["close"] for i in range(n - 11, n)]
            if closes[0] == 0:
                scores[coin] = 0.0
                continue
            ret = (closes[-1] - closes[0]) / closes[0]
            # bar-to-bar returns for vol
            bar_rets = []
            for i in range(1, len(closes)):
                if closes[i - 1] != 0:
                    bar_rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
            if len(bar_rets) >= 2:
                vol = stdev(bar_rets)
            else:
                vol = 0.0
            scores[coin] = ret / vol if vol > 0 else 0.0

        # Rank descending (highest score = rank 1)
        sorted_coins = sorted(scores.keys(), key=lambda c: scores[c], reverse=True)
        for rank_idx, coin in enumerate(sorted_coins):
            ranks[coin][n] = rank_idx + 1

    return ranks


def _compute_mean_revert_rank(data, coins, n_bars):
    """Rank coins by z-score oversold measure. 1 = most oversold."""
    MIN_BARS_NEEDED = 22  # need 20-bar window ending at n-1
    neutral_rank = max(1, len(coins) // 2)

    ranks = {c: [0] * n_bars for c in coins}

    for n in range(n_bars):
        if n < MIN_BARS_NEEDED:
            for c in coins:
                ranks[c][n] = neutral_rank
            continue

        scores = {}
        for coin in coins:
            candles = data.get(coin, [])
            if len(candles) < n:
                scores[coin] = 0.0
                continue
            # 20-bar window of closes: bars n-21 .. n-2, then current = bar n-1
            window_closes = [candles[i]["close"] for i in range(n - 21, n - 1)]
            current_close = candles[n - 1]["close"]

            if len(window_closes) < 2:
                scores[coin] = 0.0
                continue

            mean_c = sum(window_closes) / len(window_closes)
            try:
                std_c = stdev(window_closes)
            except Exception:
                std_c = 0.0

            if std_c > 0:
                # Negative z-score means oversold -> we negate so higher = more oversold
                zscore = -(current_close - mean_c) / std_c
            else:
                zscore = 0.0

            scores[coin] = zscore

        # Rank descending (highest oversold score = rank 1)
        sorted_coins = sorted(scores.keys(), key=lambda c: scores[c], reverse=True)
        for rank_idx, coin in enumerate(sorted_coins):
            ranks[coin][n] = rank_idx + 1

    return ranks
