"""Unit tests for fillability_classifier.py."""

import json
import tempfile
from pathlib import Path

import pytest

from strategies.hf.screening.fillability_classifier import (
    classify_coins,
    load_tier_a_coins,
    print_classification,
    save_classification,
    TIER_A_TOUCH_RATE,
    TIER_A_MIN_ACTIONABLE,
    TIER_B_TOUCH_RATE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(symbol: str, status: str, **kwargs) -> dict:
    """Create a minimal JSONL record."""
    rec = {"symbol": symbol, "status": status, "round": 1}
    rec.update(kwargs)
    return rec


def _write_jsonl(records: list) -> str:
    """Write records to a temp JSONL file, return path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    )
    for r in records:
        f.write(json.dumps(r) + "\n")
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Tier assignment tests
# ---------------------------------------------------------------------------

class TestTierAssignment:
    """Test tier A/B/C assignment logic."""

    def test_tier_a_assignment(self):
        """Coin with touch_rate >= 50% and n_actionable >= 30 → Tier A."""
        # VINE: 25 fills out of 33 actionable = 75.8%
        records = (
            [_make_record("VINE/USDT", "FILLED", wait_seconds=50.0)] * 25
            + [_make_record("VINE/USDT", "MISSED")] * 8
        )
        result = classify_coins(_write_jsonl(records))
        assert len(result["tier_a"]) == 1
        assert result["tier_a"][0]["symbol"] == "VINE/USDT"
        assert result["tier_a"][0]["touch_rate"] >= TIER_A_TOUCH_RATE
        assert result["tier_a"][0]["n_actionable"] >= TIER_A_MIN_ACTIONABLE

    def test_tier_b_assignment(self):
        """Coin with 25% <= touch_rate < 50% → Tier B."""
        # ES: 10 fills + 25 misses = 28.6% touch_rate
        records = (
            [_make_record("ES/USDT", "FILLED", wait_seconds=80.0)] * 10
            + [_make_record("ES/USDT", "MISSED")] * 25
        )
        result = classify_coins(_write_jsonl(records))
        assert len(result["tier_b"]) == 1
        assert result["tier_b"][0]["symbol"] == "ES/USDT"
        tr = result["tier_b"][0]["touch_rate"]
        assert TIER_B_TOUCH_RATE <= tr < TIER_A_TOUCH_RATE

    def test_tier_c_low_touch(self):
        """Coin with touch_rate < 25% → Tier C."""
        # SUKU: 5 fills + 30 misses = 14.3% touch_rate
        records = (
            [_make_record("SUKU/USDT", "FILLED", wait_seconds=90.0)] * 5
            + [_make_record("SUKU/USDT", "MISSED")] * 30
        )
        result = classify_coins(_write_jsonl(records))
        assert len(result["tier_c"]) == 1
        assert result["tier_c"][0]["symbol"] == "SUKU/USDT"
        assert result["tier_c"][0]["touch_rate"] < TIER_B_TOUCH_RATE

    def test_tier_c_low_n(self):
        """Coin with n_actionable < 30 → Tier C regardless of touch_rate."""
        # Coin with 100% touch_rate but only 5 actionable → Tier C
        records = [_make_record("RARE/USDT", "FILLED", wait_seconds=30.0)] * 5
        result = classify_coins(_write_jsonl(records))
        assert len(result["tier_c"]) == 1
        assert result["tier_c"][0]["symbol"] == "RARE/USDT"
        assert result["tier_c"][0]["touch_rate"] == 1.0
        assert result["tier_c"][0]["n_actionable"] < TIER_A_MIN_ACTIONABLE


# ---------------------------------------------------------------------------
# Error classification tests
# ---------------------------------------------------------------------------

class TestErrorClassification:
    """Test INVALID_SYMBOL vs TRANSIENT_ERROR distinction."""

    def test_invalid_symbol_excluded(self):
        """Coin with 100% ERROR_ORDERBOOK → INVALID_SYMBOL, not in any tier."""
        records = (
            # Bad coin: always ERROR_ORDERBOOK
            [_make_record("BADCOIN/USDT", "ERROR_ORDERBOOK")] * 5
            # Good coin: 25 fills + 8 misses = 33 actionable
            + [_make_record("GOOD/USDT", "FILLED", wait_seconds=50.0)] * 25
            + [_make_record("GOOD/USDT", "MISSED")] * 8
        )
        result = classify_coins(_write_jsonl(records))
        assert "BADCOIN/USDT" in result["invalid_symbols"]
        # Should not appear in any tier
        all_tier_symbols = (
            [m["symbol"] for m in result["tier_a"]]
            + [m["symbol"] for m in result["tier_b"]]
            + [m["symbol"] for m in result["tier_c"]]
        )
        assert "BADCOIN/USDT" not in all_tier_symbols
        assert result["summary"]["n_invalid"] == 1

    def test_transient_error_in_error_rate(self):
        """Sporadic ERROR_ORDERBOOK → transient, counted in error_rate."""
        records = (
            # Coin with 3 errors and 32 actionable (20F+12M)
            [_make_record("FLAKY/USDT", "FILLED", wait_seconds=50.0)] * 20
            + [_make_record("FLAKY/USDT", "MISSED")] * 12
            + [_make_record("FLAKY/USDT", "ERROR_ORDERBOOK")] * 3
        )
        result = classify_coins(_write_jsonl(records))
        # Should NOT be in invalid_symbols (not 100% error)
        assert "FLAKY/USDT" not in result["invalid_symbols"]
        # Should be in a tier with error_rate > 0
        all_coins = result["tier_a"] + result["tier_b"] + result["tier_c"]
        flaky = [m for m in all_coins if m["symbol"] == "FLAKY/USDT"]
        assert len(flaky) == 1
        assert flaky[0]["error_rate"] > 0
        # error_rate = 3 / 35 = 0.0857
        assert abs(flaky[0]["error_rate"] - 3 / 35) < 0.01


# ---------------------------------------------------------------------------
# Partial + touch_rate tests
# ---------------------------------------------------------------------------

class TestPartialHandling:
    """Test that PARTIAL counts in touch_rate."""

    def test_partial_counts_in_touch_rate(self):
        """PARTIAL orders should count as touches (fill + partial)."""
        records = (
            [_make_record("MIX/USDT", "FILLED", wait_seconds=40.0)] * 10
            + [_make_record("MIX/USDT", "PARTIAL", wait_seconds=60.0)] * 9
            + [_make_record("MIX/USDT", "MISSED")] * 13
        )
        result = classify_coins(_write_jsonl(records))
        all_coins = result["tier_a"] + result["tier_b"] + result["tier_c"]
        mix = [m for m in all_coins if m["symbol"] == "MIX/USDT"]
        assert len(mix) == 1
        # touch_rate = (10 + 9) / 32 = 0.5938
        assert abs(mix[0]["touch_rate"] - 19 / 32) < 0.01
        assert mix[0]["n_fills"] == 10
        assert mix[0]["n_partials"] == 9


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Test complete JSONL → classify → correct tiers pipeline."""

    def test_full_pipeline_from_jsonl(self):
        """End-to-end: mixed JSONL → correct tier assignments."""
        records = (
            # VINE: 25/35 filled = 71.4% → Tier A (n=35 ≥ 30)
            [_make_record("VINE/USDT", "FILLED", wait_seconds=50.0)] * 25
            + [_make_record("VINE/USDT", "MISSED")] * 10
            # AEVO: 12/34 filled = 35.3% → Tier B (n=34 ≥ 30)
            + [_make_record("AEVO/USDT", "FILLED", wait_seconds=60.0)] * 12
            + [_make_record("AEVO/USDT", "MISSED")] * 22
            # SUKU: 0/35 filled = 0% → Tier C
            + [_make_record("SUKU/USDT", "MISSED")] * 35
            # ALTHEA: always SKIPPED_SPREAD → not in any tier (no actionable)
            + [_make_record("ALTHEA/USDT", "SKIPPED_SPREAD", spread_bps=2000)] * 5
            # DEADCOIN: always ERROR_ORDERBOOK → INVALID_SYMBOL
            + [_make_record("DEADCOIN/USDT", "ERROR_ORDERBOOK")] * 3
        )
        result = classify_coins(_write_jsonl(records))

        # Check tier assignments
        tier_a_syms = [m["symbol"] for m in result["tier_a"]]
        tier_b_syms = [m["symbol"] for m in result["tier_b"]]
        tier_c_syms = [m["symbol"] for m in result["tier_c"]]

        assert "VINE/USDT" in tier_a_syms
        assert "AEVO/USDT" in tier_b_syms
        assert "SUKU/USDT" in tier_c_syms
        assert "DEADCOIN/USDT" in result["invalid_symbols"]

        # ALTHEA has 0 actionable → Tier C (low_n)
        assert "ALTHEA/USDT" in tier_c_syms

        # Summary checks
        s = result["summary"]
        assert s["n_a"] == 1  # VINE
        assert s["n_b"] == 1  # AEVO
        assert s["n_c"] == 2  # SUKU + ALTHEA
        assert s["n_invalid"] == 1  # DEADCOIN
        assert s["tier_a_touch_rate"] >= TIER_A_TOUCH_RATE
        assert s["total_rounds"] == 25 + 10 + 12 + 22 + 35 + 5 + 3  # 112

    def test_empty_log(self):
        """Empty JSONL → empty result with zero counts."""
        result = classify_coins(_write_jsonl([]))
        assert result["tier_a"] == []
        assert result["tier_b"] == []
        assert result["tier_c"] == []
        assert result["summary"]["total_rounds"] == 0


# ---------------------------------------------------------------------------
# save / load tests
# ---------------------------------------------------------------------------

class TestSaveLoad:
    """Test save_classification and load_tier_a_coins."""

    def test_save_and_load_roundtrip(self):
        """Save classification → load tier A coins → correct symbols."""
        records = (
            [_make_record("VINE/USDT", "FILLED", wait_seconds=50.0)] * 25
            + [_make_record("VINE/USDT", "MISSED")] * 8
            + [_make_record("SUKU/USDT", "MISSED")] * 35
        )
        result = classify_coins(_write_jsonl(records))

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            out_path = f.name

        save_classification(result, out_path)

        # Load tier A coins
        tier_a_coins = load_tier_a_coins(out_path)
        assert len(tier_a_coins) == 1
        assert tier_a_coins[0]["symbol"] == "VINE/USDT"
        assert tier_a_coins[0]["tier"] == "tier_a"

    def test_load_empty_tier_a(self):
        """No Tier A coins → empty list."""
        records = [_make_record("SUKU/USDT", "MISSED")] * 12
        result = classify_coins(_write_jsonl(records))

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            out_path = f.name

        save_classification(result, out_path)
        tier_a_coins = load_tier_a_coins(out_path)
        assert tier_a_coins == []
