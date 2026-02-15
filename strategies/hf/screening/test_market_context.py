#!/usr/bin/env python3
"""
Market Context Unit Tests — Sprint 5
======================================
1. Basic shape / value-range checks.
2. No-lookahead proof: truncated data must produce identical context.
3. Edge cases: single coin, short data, empty data.

Usage:
    python -m pytest strategies/hf/screening/test_market_context.py -v
"""
import math
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.market_context import precompute_market_context


# ============================================================
# Helper: synthetic OHLCV data
# ============================================================

def make_data(n_coins=5, n_bars=300, pattern="volatile", include_btc=False):
    """Generate synthetic candle data for *n_coins* coins.

    Parameters
    ----------
    n_coins : int
        Number of test coins (symbols TEST0/USD .. TESTn/USD).
    n_bars : int
        Number of candles per coin.
    pattern : str
        'volatile', 'uptrend', or 'calm'.
    include_btc : bool
        If True, add a BTC/USD series as an extra coin.
    """
    data = {}
    for i in range(n_coins):
        symbol = f"TEST{i}/USD"
        candles = []
        price = 100 + i * 20
        for j in range(n_bars):
            if pattern == "volatile":
                delta = 0.02 * math.sin(j * 0.8)
            elif pattern == "uptrend":
                delta = 0.002
            else:
                delta = 0.001 * math.sin(j * 0.5)
            o = price
            c = price * (1 + delta)
            h = max(o, c) * (1 + abs(delta) * 0.5)
            l = min(o, c) * (1 - abs(delta) * 0.5)
            vol = 1000 + 500 * abs(math.sin(j * 0.3))
            candles.append({"open": o, "high": h, "low": l, "close": c, "volume": vol})
            price = c
        data[symbol] = candles

    if include_btc:
        btc_candles = []
        price = 30000.0
        for j in range(n_bars):
            delta = 0.015 * math.sin(j * 0.6)
            o = price
            c = price * (1 + delta)
            h = max(o, c) * (1 + abs(delta) * 0.5)
            l = min(o, c) * (1 - abs(delta) * 0.5)
            vol = 5000 + 2000 * abs(math.sin(j * 0.2))
            btc_candles.append({"open": o, "high": h, "low": l, "close": c, "volume": vol})
            price = c
        data["BTC/USD"] = btc_candles

    return data


# ============================================================
# 1. TestMarketContextBasic
# ============================================================

class TestMarketContextBasic:
    """Shape and range checks on precomputed market context."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = make_data(n_coins=5, n_bars=300, include_btc=True)
        self.coins = list(self.data.keys())
        self.ctx = precompute_market_context(self.data, self.coins)

    def test_returns_correct_keys(self):
        assert set(self.ctx.keys()) == {
            "btc_atr_ratio",
            "breadth_up",
            "momentum_rank",
            "mean_revert_rank",
        }

    def test_btc_atr_ratio_length(self):
        assert len(self.ctx["btc_atr_ratio"]) == 300

    def test_breadth_up_range(self):
        for v in self.ctx["breadth_up"]:
            assert 0.0 <= v <= 1.0, f"breadth_up value {v} out of [0,1]"

    def test_momentum_rank_range(self):
        n_coins = len(self.coins)
        for coin in self.coins:
            for r in self.ctx["momentum_rank"][coin]:
                assert 1 <= r <= n_coins, f"momentum rank {r} out of [1,{n_coins}]"

    def test_mean_revert_rank_range(self):
        n_coins = len(self.coins)
        for coin in self.coins:
            for r in self.ctx["mean_revert_rank"][coin]:
                assert 1 <= r <= n_coins, f"mean_revert rank {r} out of [1,{n_coins}]"

    def test_handles_missing_btc(self):
        data_no_btc = make_data(n_coins=3, n_bars=100, include_btc=False)
        coins_no_btc = list(data_no_btc.keys())
        ctx = precompute_market_context(data_no_btc, coins_no_btc)
        assert all(v == 1.0 for v in ctx["btc_atr_ratio"]), \
            "btc_atr_ratio must be all 1.0 when BTC is absent"


# ============================================================
# 2. TestNoLookahead (CRITICAL)
# ============================================================

class TestNoLookahead:
    """Prove that context at bar N uses ONLY data up to bar N-1.

    Method: compute context with N bars, then with N+K bars.
    All values at bars 0..N-1 must be identical.
    """

    N_SHORT = 100
    N_LONG = 200
    N_COINS = 4

    @pytest.fixture(autouse=True)
    def setup(self):
        # Build long dataset, then truncate for short version
        self.data_long = make_data(
            n_coins=self.N_COINS, n_bars=self.N_LONG, include_btc=True
        )
        self.coins = list(self.data_long.keys())

        # Truncate each coin to N_SHORT bars
        self.data_short = {
            coin: candles[: self.N_SHORT]
            for coin, candles in self.data_long.items()
        }

        self.ctx_short = precompute_market_context(self.data_short, self.coins)
        self.ctx_long = precompute_market_context(self.data_long, self.coins)

    def test_rank_at_bar_n_uses_only_data_before_n(self):
        """Momentum and mean-revert ranks at bar 0..N_SHORT-1 must match."""
        for coin in self.coins:
            for n in range(self.N_SHORT):
                assert self.ctx_short["momentum_rank"][coin][n] == \
                       self.ctx_long["momentum_rank"][coin][n], \
                    f"momentum_rank lookahead at bar {n} for {coin}"
                assert self.ctx_short["mean_revert_rank"][coin][n] == \
                       self.ctx_long["mean_revert_rank"][coin][n], \
                    f"mean_revert_rank lookahead at bar {n} for {coin}"

    def test_breadth_at_bar_n_uses_only_data_before_n(self):
        """breadth_up at bar 0..N_SHORT-1 must match."""
        for n in range(self.N_SHORT):
            assert abs(self.ctx_short["breadth_up"][n] -
                       self.ctx_long["breadth_up"][n]) < 1e-12, \
                f"breadth_up lookahead at bar {n}"

    def test_btc_atr_ratio_at_bar_n_uses_only_data_before_n(self):
        """btc_atr_ratio at bar 0..N_SHORT-1 must match."""
        for n in range(self.N_SHORT):
            assert abs(self.ctx_short["btc_atr_ratio"][n] -
                       self.ctx_long["btc_atr_ratio"][n]) < 1e-12, \
                f"btc_atr_ratio lookahead at bar {n}"


# ============================================================
# 3. TestEdgeCases
# ============================================================

class TestEdgeCases:
    """Single coin, short data, empty data."""

    def test_single_coin(self):
        data = make_data(n_coins=1, n_bars=100, include_btc=False)
        coins = list(data.keys())
        ctx = precompute_market_context(data, coins)
        assert len(ctx["btc_atr_ratio"]) == 100
        assert len(ctx["breadth_up"]) == 100
        # Single coin: rank always 1 (after warm-up, neutral rank = max(1, 1//2) = 1)
        for r in ctx["momentum_rank"][coins[0]]:
            assert r == 1
        for r in ctx["mean_revert_rank"][coins[0]]:
            assert r == 1

    def test_short_data(self):
        """With < 12 bars, momentum ranks are neutral.
        With < 22 bars, mean-revert ranks are neutral.
        btc_atr_ratio is 1.0 when no BTC present.
        """
        data = make_data(n_coins=3, n_bars=10, include_btc=False)
        coins = list(data.keys())
        ctx = precompute_market_context(data, coins)
        assert len(ctx["btc_atr_ratio"]) == 10
        # All btc_atr_ratio should be 1.0 (no BTC)
        assert all(v == 1.0 for v in ctx["btc_atr_ratio"])
        # All bars < 12 -> momentum neutral; all bars < 22 -> mean-revert neutral
        neutral = max(1, len(coins) // 2)
        for coin in coins:
            for r in ctx["momentum_rank"][coin]:
                assert r == neutral, f"momentum rank {r} != neutral {neutral}"
            for r in ctx["mean_revert_rank"][coin]:
                assert r == neutral, f"mean_revert rank {r} != neutral {neutral}"

    def test_empty_data(self):
        ctx = precompute_market_context({}, [])
        assert ctx["btc_atr_ratio"] == []
        assert ctx["breadth_up"] == []
        assert ctx["momentum_rank"] == {}
        assert ctx["mean_revert_rank"] == {}

    def test_empty_coins_with_data(self):
        data = make_data(n_coins=2, n_bars=50)
        ctx = precompute_market_context(data, [])
        assert ctx["btc_atr_ratio"] == []

    def test_coins_with_empty_candles(self):
        data = {"TEST0/USD": [], "TEST1/USD": []}
        coins = list(data.keys())
        ctx = precompute_market_context(data, coins)
        assert ctx["btc_atr_ratio"] == []
