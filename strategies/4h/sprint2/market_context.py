"""
Sprint 2 Market Context — Cross-Sectional Signals
===================================================
Simplified market context for 4H entry-edge discovery.

Computes per-bar:
  - momentum_rank: vol-adjusted N-bar return ranking (rank 1 = best)
  - momentum_return: raw N-bar return per coin
  - breadth_up: fraction of coins up
  - n_ranked: number of coins with data at each bar

CAUSALITY RULE: All context at bar N uses data up to bar N-1 ONLY.

Pattern matches HF screening/market_context.py (ADR-HF-017) but simplified:
  - No BTC ATR ratio (not needed for entry screening)
  - No mean-revert rank (not needed; Family 4 handles this differently)
  - Configurable momentum_period (HF uses fixed 10)
"""
from __future__ import annotations

from statistics import stdev


def precompute_sprint2_context(
    data: dict,
    coins: list[str],
    momentum_period: int = 10,
) -> dict:
    """Precompute cross-sectional context arrays for Sprint 2.

    Parameters
    ----------
    data : dict[str, list[dict]]
        Candle cache: {pair: [candle_dicts]}.
    coins : list[str]
        Coins to include in ranking.
    momentum_period : int
        Lookback period for momentum (bar returns). Default 10.

    Returns
    -------
    dict with keys:
        momentum_rank   : {coin: [rank_at_bar_0, ...]}  (1 = best)
        momentum_return : {coin: [return_at_bar_0, ...]} (raw return)
        breadth_up      : [fraction_up_at_bar_0, ...]
        n_ranked        : [n_coins_with_data_at_bar_0, ...]
        momentum_period : int (for provenance)
    """
    if not coins or not data:
        return {
            "momentum_rank": {},
            "momentum_return": {},
            "breadth_up": [],
            "n_ranked": [],
            "momentum_period": momentum_period,
        }

    n_bars = max(len(data.get(c, [])) for c in coins)
    if n_bars == 0:
        return {
            "momentum_rank": {c: [] for c in coins},
            "momentum_return": {c: [] for c in coins},
            "breadth_up": [],
            "n_ranked": [],
            "momentum_period": momentum_period,
        }

    # Pre-extract closes for efficiency
    coin_closes: dict[str, list[float]] = {}
    for coin in coins:
        candles = data.get(coin, [])
        coin_closes[coin] = [c["close"] for c in candles]

    # ------------------------------------------------------------------
    # Breadth: fraction of coins where close[N-1] > close[N-2]
    # ------------------------------------------------------------------
    breadth_up = _compute_breadth(coin_closes, coins, n_bars)

    # ------------------------------------------------------------------
    # Momentum rank + return
    # ------------------------------------------------------------------
    momentum_rank, momentum_return, n_ranked = _compute_momentum(
        coin_closes, coins, n_bars, momentum_period,
    )

    return {
        "momentum_rank": momentum_rank,
        "momentum_return": momentum_return,
        "breadth_up": breadth_up,
        "n_ranked": n_ranked,
        "momentum_period": momentum_period,
    }


# ------------------------------------------------------------------
# Component computations
# ------------------------------------------------------------------

def _compute_breadth(
    coin_closes: dict[str, list[float]],
    coins: list[str],
    n_bars: int,
) -> list[float]:
    """Fraction of coins where close[N-1] > close[N-2]."""
    result = []
    for n in range(n_bars):
        if n < 2:
            result.append(0.5)  # neutral
            continue
        up = 0
        total = 0
        for coin in coins:
            closes = coin_closes.get(coin, [])
            if len(closes) < n:
                continue
            total += 1
            if closes[n - 1] > closes[n - 2]:
                up += 1
        if total == 0:
            result.append(0.5)
        else:
            result.append(up / total)
    return result


def _compute_momentum(
    coin_closes: dict[str, list[float]],
    coins: list[str],
    n_bars: int,
    period: int,
) -> tuple[dict, dict, list[int]]:
    """Vol-adjusted momentum rank + raw return.

    At bar N, uses closes[N-period-1 .. N-1] (period+1 values).
    Rank 1 = highest vol-adjusted return.
    """
    min_bars_needed = period + 2  # need period+1 closes plus at least 2 bar returns
    neutral_rank = max(1, len(coins) // 2)

    ranks: dict[str, list[int]] = {c: [0] * n_bars for c in coins}
    returns: dict[str, list[float]] = {c: [0.0] * n_bars for c in coins}
    n_ranked_list: list[int] = [0] * n_bars

    for n in range(n_bars):
        if n < min_bars_needed:
            for c in coins:
                ranks[c][n] = neutral_rank
            continue

        scores: dict[str, float] = {}
        raw_rets: dict[str, float] = {}
        n_with_data = 0

        for coin in coins:
            closes = coin_closes.get(coin, [])
            if len(closes) < n:
                scores[coin] = 0.0
                raw_rets[coin] = 0.0
                continue

            # Closes from bar (n-period-1) to bar (n-1), inclusive
            # That's (period+1) values
            start_idx = n - period - 1
            if start_idx < 0:
                scores[coin] = 0.0
                raw_rets[coin] = 0.0
                continue

            c_start = closes[start_idx]
            c_end = closes[n - 1]

            if c_start == 0:
                scores[coin] = 0.0
                raw_rets[coin] = 0.0
                continue

            n_with_data += 1
            ret = (c_end - c_start) / c_start
            raw_rets[coin] = ret

            # Vol-adjusted: ret / stdev(bar-to-bar returns)
            bar_rets = []
            for i in range(start_idx + 1, n):
                if closes[i - 1] != 0:
                    bar_rets.append((closes[i] - closes[i - 1]) / closes[i - 1])

            if len(bar_rets) >= 2:
                vol = stdev(bar_rets)
                scores[coin] = ret / vol if vol > 0 else 0.0
            else:
                scores[coin] = 0.0

        n_ranked_list[n] = n_with_data

        # Rank descending (highest vol-adj return = rank 1)
        sorted_coins = sorted(scores.keys(), key=lambda c: scores[c], reverse=True)
        for rank_idx, coin in enumerate(sorted_coins):
            ranks[coin][n] = rank_idx + 1
            returns[coin][n] = raw_rets.get(coin, 0.0)

    return ranks, returns, n_ranked_list


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    random.seed(42)

    # Create synthetic data: 10 coins, 100 bars
    n_coins = 10
    n_bars = 100
    test_coins = [f"COIN{i}/USD" for i in range(n_coins)]
    test_data = {}

    for coin in test_coins:
        candles = []
        price = 100 + random.uniform(-20, 20)
        for _ in range(n_bars):
            o = price
            c = price * (1 + random.gauss(0, 0.03))
            h = max(o, c) * (1 + random.uniform(0, 0.02))
            l = min(o, c) * (1 - random.uniform(0, 0.02))
            v = random.uniform(1000, 10000)
            candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
            price = c
        test_data[coin] = candles

    # Compute context
    ctx = precompute_sprint2_context(test_data, test_coins, momentum_period=10)

    # Basic structure checks
    assert len(ctx["breadth_up"]) == n_bars
    assert len(ctx["n_ranked"]) == n_bars
    assert ctx["momentum_period"] == 10
    assert len(ctx["momentum_rank"]) == n_coins
    assert len(ctx["momentum_return"]) == n_coins

    # Breadth should be between 0 and 1
    for b in ctx["breadth_up"]:
        assert 0.0 <= b <= 1.0, f"breadth_up out of range: {b}"

    # Ranks should be 1..n_coins after warmup
    for bar in range(20, n_bars):
        rank_vals = [ctx["momentum_rank"][c][bar] for c in test_coins]
        assert min(rank_vals) >= 1, f"Rank < 1 at bar {bar}"
        assert max(rank_vals) <= n_coins, f"Rank > n_coins at bar {bar}"
        # Should be a permutation
        assert sorted(rank_vals) == list(range(1, n_coins + 1)), \
            f"Ranks not a permutation at bar {bar}: {sorted(rank_vals)}"

    # CAUSALITY CHECK: rank at bar N should not change if we modify bar N data
    # Modify last bar and verify ranks at last bar are unchanged
    # (because ranks at bar N use data up to bar N-1)
    ctx_before = precompute_sprint2_context(test_data, test_coins, momentum_period=10)
    rank_at_last = {c: ctx_before["momentum_rank"][c][n_bars - 1] for c in test_coins}

    # Modify the LAST bar's close for all coins
    modified_data = {}
    for coin in test_coins:
        candles_copy = [dict(c) for c in test_data[coin]]
        candles_copy[-1]["close"] *= 2.0  # double the last close
        modified_data[coin] = candles_copy

    ctx_after = precompute_sprint2_context(modified_data, test_coins, momentum_period=10)
    rank_at_last_after = {c: ctx_after["momentum_rank"][c][n_bars - 1] for c in test_coins}

    # Ranks at bar N-1 should be identical (causality: uses data up to bar N-2)
    for c in test_coins:
        assert ctx_before["momentum_rank"][c][n_bars - 1] == ctx_after["momentum_rank"][c][n_bars - 1], \
            f"CAUSALITY VIOLATION at bar {n_bars-1} for {c}"

    print(f"  Context OK: {n_coins} coins, {n_bars} bars")
    print(f"  Breadth range: {min(ctx['breadth_up']):.3f} - {max(ctx['breadth_up']):.3f}")
    print(f"  n_ranked range: {min(ctx['n_ranked'])} - {max(ctx['n_ranked'])}")
    print(f"  Causality test: PASSED (modifying bar N doesn't affect rank at bar N)")
    print("\n  All Sprint 2 market context sanity checks passed")
