"""Unit tests for live_fill_test.py — pure logic tests, no API calls."""

import json
import math
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Import module under test
from strategies.hf.screening.live_fill_test import (
    _compute_limit_price,
    _compute_quantity,
    _generate_summary,
    _validate_coins_against_markets,
    checkpoint_decision,
    checkpoint_report,
    theoretical_fill_prob,
    load_fill_test_coins,
    MAX_ORDER_USD,
    MAX_EXPOSURE_USD,
    MIN_ORDER_USD,
    ORDER_TTL_SECONDS,
    DAILY_MAX_ORDERS,
    MAX_CONSECUTIVE_ERRORS,
    MAX_CONSECUTIVE_PARTIALS,
)


# ---------------------------------------------------------------------------
# theoretical_fill_prob — must match fill_model_v3
# ---------------------------------------------------------------------------

class TestTheoreticalFillProb:
    """Ensure parity with fill_model_v3.bar_structure_fill_probability."""

    def test_price_never_reached(self):
        """Low > limit_price → 0.0 (price never dropped to limit)."""
        assert theoretical_fill_prob(low=100, high=110, limit_price=99) == 0.0

    def test_full_penetration(self):
        """Price went well below limit → queue_factor."""
        prob = theoretical_fill_prob(low=90, high=110, limit_price=105)
        # penetration = (105 - 90) / 20 = 0.75, * 2.0 = 1.5 → capped at 1.0
        assert prob == pytest.approx(0.7, abs=0.001)

    def test_half_penetration(self):
        """Price touched limit, 50% penetration → ~full queue_factor."""
        prob = theoretical_fill_prob(low=100, high=120, limit_price=110)
        # penetration = (110 - 100) / 20 = 0.5, * 2.0 = 1.0 → 0.7
        assert prob == pytest.approx(0.7, abs=0.001)

    def test_shallow_penetration(self):
        """Price barely touched limit → low probability."""
        prob = theoretical_fill_prob(low=99, high=110, limit_price=100)
        # penetration = (100 - 99) / 11 ≈ 0.091, * 2 = 0.182 → 0.127
        assert 0.1 < prob < 0.2

    def test_flat_bar(self):
        """Zero range bar that touched limit → queue_factor."""
        prob = theoretical_fill_prob(low=100, high=100, limit_price=100)
        assert prob == 0.7

    def test_custom_queue_factor(self):
        prob = theoretical_fill_prob(low=90, high=110, limit_price=105, queue_factor=0.5)
        assert prob == pytest.approx(0.5, abs=0.001)

    def test_parity_with_fill_model_v3(self):
        """Cross-check against fill_model_v3 implementation."""
        try:
            from strategies.hf.screening.fill_model_v3 import bar_structure_fill_probability
        except ImportError:
            pytest.skip("fill_model_v3 not importable")

        test_cases = [
            (90, 110, 100, 105, 0.7),
            (100, 110, 105, 99, 0.7),
            (95, 105, 100, 100, 0.7),
            (100, 100, 100, 100, 0.7),
        ]
        for low, high, close, limit, qf in test_cases:
            expected = bar_structure_fill_probability(low, high, close, limit, qf)
            actual = theoretical_fill_prob(low, high, limit, qf)
            assert actual == pytest.approx(expected, abs=1e-6), \
                f"Mismatch at low={low} high={high} limit={limit}: {actual} vs {expected}"


# ---------------------------------------------------------------------------
# _compute_limit_price
# ---------------------------------------------------------------------------

class TestComputeLimitPrice:

    def test_near_bid_strategy(self):
        """near_bid: bid + 10% of spread."""
        price = _compute_limit_price(100.0, 100.10, "near_bid")
        assert price == pytest.approx(100.01, abs=0.001)

    def test_mid_strategy(self):
        """mid: midpoint of bid/ask."""
        price = _compute_limit_price(100.0, 100.10, "mid")
        assert price == pytest.approx(100.05, abs=0.001)

    def test_below_bid_strategy(self):
        """below_bid: bid - 50% of spread."""
        price = _compute_limit_price(100.0, 100.10, "below_bid")
        assert price == pytest.approx(99.95, abs=0.001)

    def test_near_ask_strategy(self):
        """near_ask: ask - 10% of spread (most aggressive maker)."""
        # bid=100.0, ask=100.10, spread=0.10
        # near_ask = 100.10 - 0.10 * 0.10 = 100.09
        price = _compute_limit_price(100.0, 100.10, "near_ask")
        assert price == pytest.approx(100.09, abs=0.001)

    def test_default_strategy(self):
        """Unknown strategy defaults to bid."""
        price = _compute_limit_price(100.0, 100.10, "unknown")
        assert price == 100.0

    def test_always_below_ask(self):
        """All strategies produce price below ask (maker side)."""
        for strategy in ("near_bid", "mid", "below_bid", "near_ask"):
            price = _compute_limit_price(100.0, 100.50, strategy)
            assert price < 100.50, f"{strategy}: {price} >= ask"


# ---------------------------------------------------------------------------
# _compute_quantity
# ---------------------------------------------------------------------------

class TestComputeQuantity:

    def test_basic_quantity(self):
        """Simple quantity computation."""
        market = {"precision": {"amount": 2}, "limits": {"amount": {"min": 0.01}, "cost": {"min": 1.0}}}
        qty = _compute_quantity(100.0, 15.0, market)
        assert qty == 0.15

    def test_zero_price(self):
        qty = _compute_quantity(0.0, 15.0, {})
        assert qty is None

    def test_below_min_amount(self):
        market = {"precision": {"amount": 0}, "limits": {"amount": {"min": 100}, "cost": {"min": None}}}
        qty = _compute_quantity(100.0, 15.0, market)
        # 15/100 = 0.15, rounded to 0 decimals = 0, but 0 < 100 min
        assert qty is None

    def test_below_min_cost(self):
        market = {"precision": {"amount": 4}, "limits": {"amount": {"min": None}, "cost": {"min": 20.0}}}
        qty = _compute_quantity(100.0, 10.0, market)
        # 10/100 = 0.1, 0.1 * 100 = $10 < $20 min cost
        assert qty is None

    def test_no_precision_info(self):
        """Works even without precision/limits info."""
        qty = _compute_quantity(50.0, 15.0, {})
        assert qty == pytest.approx(0.3, abs=0.01)


# ---------------------------------------------------------------------------
# _generate_summary
# ---------------------------------------------------------------------------

class TestGenerateSummary:

    def _make_result(self, status, tier="tier1", spread=5.0, theo=0.7,
                     wait=30.0, rt_pnl=None, symbol="TEST/USDT",
                     slippage=None, cancelled=False):
        r = {
            "status": status,
            "tier": tier,
            "symbol": symbol,
            "spread_bps": spread,
            "theoretical_fill_prob": theo,
        }
        if cancelled:
            r["cancelled"] = True
        if status == "FILLED":
            r["wait_seconds"] = wait
            if rt_pnl is not None:
                r["roundtrip_pnl"] = rt_pnl
            if slippage is not None:
                r["slippage_vs_mid_bps"] = slippage
        return r

    def test_empty(self):
        summary = _generate_summary([])
        assert summary["total"] == 0

    def test_all_filled(self):
        results = [
            self._make_result("FILLED", rt_pnl=-0.01, wait=20),
            self._make_result("FILLED", rt_pnl=-0.02, wait=40),
        ]
        summary = _generate_summary(results)
        assert summary["filled"] == 2
        assert summary["fill_rate"] == 1.0
        assert summary["touch_rate"] == 1.0
        assert summary["partial_rate"] == 0.0
        assert summary["timeout_rate"] == 0.0
        assert summary["total_roundtrip_pnl"] == pytest.approx(-0.03, abs=0.001)
        assert summary["avg_fill_wait_seconds"] == 30.0

    def test_mixed_results(self):
        results = [
            self._make_result("FILLED", rt_pnl=-0.01, wait=15),
            self._make_result("MISSED"),
            self._make_result("SKIPPED_SPREAD"),
            self._make_result("ERROR_ORDERBOOK"),
        ]
        summary = _generate_summary(results)
        assert summary["total_rounds"] == 4
        assert summary["actionable"] == 2  # filled + missed
        assert summary["filled"] == 1
        assert summary["missed"] == 1
        assert summary["skipped"] == 1
        assert summary["errors"] == 1
        assert summary["fill_rate"] == 0.5
        assert summary["touch_rate"] == 0.5  # (1 filled + 0 partial) / 2
        assert summary["timeout_rate"] == 0.5  # 1 missed / 2 actionable

    def test_tier_breakdown(self):
        results = [
            self._make_result("FILLED", tier="tier1", rt_pnl=0, wait=10),
            self._make_result("MISSED", tier="tier1"),
            self._make_result("FILLED", tier="tier2", rt_pnl=0, wait=10),
        ]
        summary = _generate_summary(results)
        assert summary["tier_breakdown"]["tier1"]["fill_rate"] == 0.5
        assert summary["tier_breakdown"]["tier2"]["fill_rate"] == 1.0
        assert summary["tier_breakdown"]["tier1"]["partial"] == 0

    def test_theoretical_comparison(self):
        results = [
            self._make_result("FILLED", theo=0.7, rt_pnl=0, wait=10),
            self._make_result("MISSED", theo=0.7),
        ]
        summary = _generate_summary(results)
        assert summary["theoretical_avg_fill_prob"] == 0.7
        assert summary["model_vs_reality_delta"] == pytest.approx(-0.2, abs=0.01)
        # Reality: 50% fill, theory: 70% → delta = -20%

    def test_per_coin_breakdown(self):
        results = [
            self._make_result("FILLED", symbol="BTC/USDT", rt_pnl=0, wait=10, slippage=-2.0),
            self._make_result("FILLED", symbol="BTC/USDT", rt_pnl=0, wait=20, slippage=-3.0),
            self._make_result("MISSED", symbol="ETH/USDT"),
            self._make_result("FILLED", symbol="ETH/USDT", rt_pnl=0, wait=5, slippage=-1.0),
        ]
        summary = _generate_summary(results)
        coin_stats = summary["coin_breakdown"]
        assert "BTC/USDT" in coin_stats
        assert "ETH/USDT" in coin_stats
        assert coin_stats["BTC/USDT"]["filled"] == 2
        assert coin_stats["BTC/USDT"]["fill_rate"] == 1.0
        assert coin_stats["BTC/USDT"]["avg_slippage_bps"] == pytest.approx(-2.5, abs=0.01)
        assert coin_stats["ETH/USDT"]["filled"] == 1
        assert coin_stats["ETH/USDT"]["missed"] == 1
        assert coin_stats["ETH/USDT"]["fill_rate"] == 0.5

    def test_cancelled_tracking(self):
        results = [
            self._make_result("MISSED", cancelled=True),
            self._make_result("FILLED", rt_pnl=0, wait=10),
        ]
        summary = _generate_summary(results)
        assert summary["cancelled"] == 1
        assert summary["cancelled_rate"] == 0.5

    def test_slippage_aggregation(self):
        results = [
            self._make_result("FILLED", rt_pnl=0, wait=10, slippage=-5.0),
            self._make_result("FILLED", rt_pnl=0, wait=10, slippage=-3.0),
        ]
        summary = _generate_summary(results)
        assert summary["avg_slippage_vs_mid_bps"] == pytest.approx(-4.0, abs=0.01)

    def test_flatten_fees_labeled_as_overhead(self):
        """Flatten fees must be labeled as measurement overhead, not maker model."""
        results = [
            self._make_result("FILLED", rt_pnl=-0.01, wait=10),
        ]
        # Add sell_fee_cost to simulate real fill
        results[0]["sell_fee_cost"] = 0.005
        summary = _generate_summary(results)
        assert "total_flatten_fees_paid" in summary
        assert "total_fees_paid" not in summary  # Old key removed
        assert summary["total_flatten_fees_paid"] == pytest.approx(0.005, abs=0.0001)
        assert "measurement overhead" in summary["flatten_fees_note"].lower()


# ---------------------------------------------------------------------------
# load_fill_test_coins
# ---------------------------------------------------------------------------

class TestLoadFillTestCoins:

    def test_loads_coins(self):
        """Should load coins if universe file exists."""
        if not os.path.exists(str(_compute_universe_path())):
            pytest.skip("Universe tiering file not available")
        coins = load_fill_test_coins(n_coins=5)
        assert len(coins) >= 1  # At least some coins from universe
        assert all("symbol" in c and "tier" in c for c in coins)

    def test_coins_from_universe(self):
        """All coins come from T1/T2 universe (no hardcoded BTC/ETH)."""
        if not os.path.exists(str(_compute_universe_path())):
            pytest.skip("Universe tiering file not available")
        coins = load_fill_test_coins(n_coins=5)
        assert len(coins) == 5
        for c in coins:
            assert c["tier"] in ("tier1", "tier2")

    def test_deterministic_seed(self):
        if not os.path.exists(str(_compute_universe_path())):
            pytest.skip("Universe tiering file not available")
        coins_a = load_fill_test_coins(n_coins=10, seed=42)
        coins_b = load_fill_test_coins(n_coins=10, seed=42)
        assert coins_a == coins_b

    def test_different_seed_different_coins(self):
        if not os.path.exists(str(_compute_universe_path())):
            pytest.skip("Universe tiering file not available")
        coins_a = load_fill_test_coins(n_coins=10, seed=42)
        coins_b = load_fill_test_coins(n_coins=10, seed=99)
        syms_a = set(c["symbol"] for c in coins_a)
        syms_b = set(c["symbol"] for c in coins_b)
        assert syms_a != syms_b  # Different seeds → different coins


def _compute_universe_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[3] / "reports" / "hf" / "universe_tiering_001.json"


# ---------------------------------------------------------------------------
# Safety constants validation
# ---------------------------------------------------------------------------

class TestSafetyConstants:

    def test_max_order_cap(self):
        assert MAX_ORDER_USD == 50.0

    def test_max_exposure_cap(self):
        assert MAX_EXPOSURE_USD == 50.0

    def test_min_order_floor(self):
        assert MIN_ORDER_USD == 5.0

    def test_min_below_max(self):
        assert MIN_ORDER_USD < MAX_ORDER_USD

    def test_ttl_60s(self):
        assert ORDER_TTL_SECONDS == 60.0

    def test_daily_cap(self):
        assert DAILY_MAX_ORDERS == 50

    def test_kill_switch_thresholds(self):
        assert MAX_CONSECUTIVE_ERRORS == 3
        assert MAX_CONSECUTIVE_PARTIALS == 3


# ---------------------------------------------------------------------------
# Pre-flight market validation
# ---------------------------------------------------------------------------

class TestValidateCoinsAgainstMarkets:
    """Test _validate_coins_against_markets with mock exchange."""

    def test_filters_missing_symbol(self):
        """Coins not in exchange.markets are filtered out."""
        exchange = MagicMock()
        exchange.markets = {
            "SNEK/USDT": {"active": True},
            "VINE/USDT": {"active": True},
        }
        coins = [
            {"symbol": "SNEK/USDT", "tier": "tier1"},
            {"symbol": "PUPS/USDT", "tier": "tier2"},  # not in markets
            {"symbol": "VINE/USDT", "tier": "tier2"},
        ]
        valid, invalid = _validate_coins_against_markets(exchange, coins)
        assert len(valid) == 2
        assert len(invalid) == 1
        assert invalid[0]["symbol"] == "PUPS/USDT"

    def test_filters_inactive_symbol(self):
        """Coins with active=False are filtered out."""
        exchange = MagicMock()
        exchange.markets = {
            "SNEK/USDT": {"active": True},
            "DENT/USDT": {"active": False},
        }
        coins = [
            {"symbol": "SNEK/USDT", "tier": "tier1"},
            {"symbol": "DENT/USDT", "tier": "tier1"},
        ]
        valid, invalid = _validate_coins_against_markets(exchange, coins)
        assert len(valid) == 1
        assert len(invalid) == 1
        assert invalid[0]["symbol"] == "DENT/USDT"

    def test_all_valid(self):
        """All coins exist and are active → no invalids."""
        exchange = MagicMock()
        exchange.markets = {
            "SNEK/USDT": {"active": True},
            "VINE/USDT": {"active": True},
        }
        coins = [
            {"symbol": "SNEK/USDT", "tier": "tier1"},
            {"symbol": "VINE/USDT", "tier": "tier2"},
        ]
        valid, invalid = _validate_coins_against_markets(exchange, coins)
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_all_invalid(self):
        """All coins missing → valid list is empty."""
        exchange = MagicMock()
        exchange.markets = {}
        coins = [
            {"symbol": "PUPS/USDT", "tier": "tier2"},
            {"symbol": "DENT/USDT", "tier": "tier1"},
        ]
        valid, invalid = _validate_coins_against_markets(exchange, coins)
        assert len(valid) == 0
        assert len(invalid) == 2


# ---------------------------------------------------------------------------
# Checkpoint decision logic
# ---------------------------------------------------------------------------

class TestCheckpointDecision:

    def test_below_40_returns_reconfigure(self):
        """touch_rate < 40% → RECONFIGURE."""
        assert checkpoint_decision(0.0) == "RECONFIGURE"
        assert checkpoint_decision(0.10) == "RECONFIGURE"
        assert checkpoint_decision(0.39) == "RECONFIGURE"

    def test_40_to_50_returns_watch(self):
        """40% ≤ touch_rate < 50% → WATCH."""
        assert checkpoint_decision(0.40) == "WATCH"
        assert checkpoint_decision(0.45) == "WATCH"
        assert checkpoint_decision(0.49) == "WATCH"

    def test_above_50_returns_go(self):
        """touch_rate ≥ 50% → GO."""
        assert checkpoint_decision(0.50) == "GO"
        assert checkpoint_decision(0.75) == "GO"
        assert checkpoint_decision(1.00) == "GO"


# ---------------------------------------------------------------------------
# Checkpoint report (integration test with JSONL)
# ---------------------------------------------------------------------------

class TestCheckpointReport:

    def _write_jsonl(self, records):
        """Write records to a temp JSONL file, return path."""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.close()
        return f.name

    def test_reconfigure_on_low_fill(self):
        """1 fill out of 7 actionable → touch_rate 14.3% → RECONFIGURE."""
        records = [
            {"symbol": "SNEK/USDT", "status": "MISSED", "spread_bps": 12.5, "theoretical_fill_prob": 0.66},
            {"symbol": "VINE/USDT", "status": "FILLED", "spread_bps": 32.4, "theoretical_fill_prob": 0.36, "slippage_vs_mid_bps": -10.8},
            {"symbol": "AEVO/USDT", "status": "MISSED", "spread_bps": 11.2, "theoretical_fill_prob": 0.70},
            {"symbol": "FIDA/USDT", "status": "MISSED", "spread_bps": 15.9, "theoretical_fill_prob": 0.57},
            {"symbol": "ES/USDT", "status": "MISSED", "spread_bps": 4.5, "theoretical_fill_prob": 0.70},
            {"symbol": "PUPS/USDT", "status": "ERROR_ORDERBOOK"},
            {"symbol": "DENT/USDT", "status": "ERROR_ORDERBOOK"},
            {"symbol": "ALTHEA/USDT", "status": "SKIPPED_SPREAD", "spread_bps": 2767.0},
            {"symbol": "SUKU/USDT", "status": "MISSED", "spread_bps": 65.4, "theoretical_fill_prob": 0.20},
            {"symbol": "PHA/USDT", "status": "MISSED", "spread_bps": 12.4, "theoretical_fill_prob": 0.66},
        ]
        path = self._write_jsonl(records)
        try:
            result = checkpoint_report(path)
            assert result["decision"] == "RECONFIGURE"
            assert result["filled"] == 1
            assert result["actionable"] == 7  # 1 fill + 6 missed
            assert result["touch_rate"] < 0.40  # 1/7 = 14.3%
            assert result["fill_rate"] < 0.20
            assert "PUPS/USDT" in result["invalid_symbols"]
            assert "DENT/USDT" in result["invalid_symbols"]
            assert "ALTHEA/USDT" in result["extreme_spread_coins"]
        finally:
            os.unlink(path)

    def test_go_on_high_fill(self):
        """4 fills out of 5 actionable → touch_rate 80% → GO."""
        records = [
            {"symbol": "A/USDT", "status": "FILLED", "spread_bps": 10, "theoretical_fill_prob": 0.5},
            {"symbol": "B/USDT", "status": "FILLED", "spread_bps": 15, "theoretical_fill_prob": 0.5},
            {"symbol": "C/USDT", "status": "FILLED", "spread_bps": 20, "theoretical_fill_prob": 0.5},
            {"symbol": "D/USDT", "status": "FILLED", "spread_bps": 12, "theoretical_fill_prob": 0.5},
            {"symbol": "E/USDT", "status": "MISSED", "spread_bps": 8, "theoretical_fill_prob": 0.5},
        ]
        path = self._write_jsonl(records)
        try:
            result = checkpoint_report(path)
            assert result["decision"] == "GO"
            assert result["touch_rate"] == 0.8
            assert result["fill_rate"] == 0.8
        finally:
            os.unlink(path)

    def test_empty_log_returns_no_data(self):
        """Empty JSONL → NO_DATA decision."""
        path = self._write_jsonl([])
        try:
            result = checkpoint_report(path)
            assert result["decision"] == "NO_DATA"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# --classify and --coin-filter CLI flags
# ---------------------------------------------------------------------------

class TestClassifyCLI:
    """Test --classify CLI flag integration."""

    def test_classify_produces_output(self):
        """--classify reads JSONL and writes fillable_universe_v1.json."""
        records = [
            {"symbol": "VINE/USDT", "status": "FILLED", "wait_seconds": 50.0},
        ] * 25 + [
            {"symbol": "VINE/USDT", "status": "MISSED"},
        ] * 8 + [
            {"symbol": "SUKU/USDT", "status": "MISSED"},
        ] * 35

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "test.jsonl")
            with open(jsonl_path, "w") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            from strategies.hf.screening.fillability_classifier import (
                classify_coins,
                save_classification,
            )

            result = classify_coins(jsonl_path)
            universe_path = os.path.join(tmpdir, "fillable_universe_v1.json")
            save_classification(result, universe_path)

            assert os.path.exists(universe_path)
            with open(universe_path) as f:
                data = json.load(f)
            assert len(data["tier_a"]) == 1
            assert data["tier_a"][0]["symbol"] == "VINE/USDT"

    def test_coin_filter_loads_tier_a(self):
        """--coin-filter loads only Tier A coins from classification JSON."""
        classification = {
            "tier_a": [
                {"symbol": "VINE/USDT", "touch_rate": 0.84},
                {"symbol": "AEVO/USDT", "touch_rate": 0.55},
            ],
            "tier_b": [{"symbol": "ES/USDT", "touch_rate": 0.30}],
            "tier_c": [{"symbol": "SUKU/USDT", "touch_rate": 0.0}],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(classification, f)
            filter_path = f.name

        try:
            from strategies.hf.screening.fillability_classifier import (
                load_tier_a_coins,
            )

            coins = load_tier_a_coins(filter_path)
            assert len(coins) == 2
            symbols = [c["symbol"] for c in coins]
            assert "VINE/USDT" in symbols
            assert "AEVO/USDT" in symbols
            assert all(c["tier"] == "tier_a" for c in coins)
        finally:
            os.unlink(filter_path)
