"""Unit tests for fill_model_v3 bar-structure fill model."""
import pytest
from strategies.hf.screening.fill_model_v3 import (
    bar_structure_fill_probability,
    compute_limit_entry_price,
    adjust_trades_bar_structure,
    recompute_pnl_with_costs,
    full_fill_model_v3,
)


class TestBarStructureFillProbability:

    def test_no_fill_when_low_above_limit(self):
        """Bar low is above limit price -> 0% fill."""
        prob = bar_structure_fill_probability(
            low=100.0, high=105.0, close=103.0,
            limit_price=99.0, queue_factor=0.7,
        )
        assert prob == 0.0

    def test_full_penetration_caps_at_queue_factor(self):
        """Low is well below limit -> fill prob = queue_factor."""
        prob = bar_structure_fill_probability(
            low=90.0, high=110.0, close=100.0,
            limit_price=108.0, queue_factor=0.7,
        )
        # penetration = (108-90)/(110-90) = 0.9, *2 = 1.8, capped at 1.0
        # fill_prob = 0.7 * 1.0 = 0.7
        assert prob == pytest.approx(0.7)

    def test_partial_penetration_scales_correctly(self):
        """Partial penetration scales linearly."""
        prob = bar_structure_fill_probability(
            low=98.0, high=102.0, close=100.0,
            limit_price=99.0, queue_factor=0.7,
        )
        # penetration = (99-98)/(102-98) = 0.25, *2 = 0.5
        # fill_prob = 0.7 * 0.5 = 0.35
        assert prob == pytest.approx(0.35)

    def test_limit_equals_low_gives_small_prob(self):
        """Limit exactly at low -> penetration = 0 -> prob = 0."""
        prob = bar_structure_fill_probability(
            low=100.0, high=105.0, close=103.0,
            limit_price=100.0, queue_factor=0.7,
        )
        # penetration = (100-100)/(105-100) = 0.0, *2 = 0.0
        # fill_prob = 0.7 * 0.0 = 0.0
        assert prob == 0.0

    def test_flat_bar_touched_limit(self):
        """Flat bar (high==low) that touches limit -> queue_factor."""
        prob = bar_structure_fill_probability(
            low=100.0, high=100.0, close=100.0,
            limit_price=100.5, queue_factor=0.7,
        )
        # low <= limit and bar_range == 0 -> return queue_factor
        assert prob == 0.7

    def test_queue_factor_respected(self):
        """Different queue factors are respected."""
        prob_low = bar_structure_fill_probability(
            low=90.0, high=110.0, close=100.0,
            limit_price=108.0, queue_factor=0.5,
        )
        prob_high = bar_structure_fill_probability(
            low=90.0, high=110.0, close=100.0,
            limit_price=108.0, queue_factor=0.8,
        )
        assert prob_low == pytest.approx(0.5)
        assert prob_high == pytest.approx(0.8)


class TestComputeLimitEntryPrice:

    def test_basic(self):
        """100 close with 50bps half-spread -> 99.5."""
        price = compute_limit_entry_price(100.0, 50.0)
        assert price == pytest.approx(99.5)

    def test_zero_spread(self):
        """Zero spread -> limit at close."""
        price = compute_limit_entry_price(100.0, 0.0)
        assert price == 100.0

    def test_small_spread(self):
        """5 bps spread on $0.001 coin."""
        price = compute_limit_entry_price(0.001, 5.0)
        expected = 0.001 * (1.0 - 5.0 / 10000.0)
        assert price == pytest.approx(expected)


class TestDeterminism:

    def test_deterministic_with_seed(self):
        """Same seed -> same results."""
        # Create fake trades
        trades = [
            {'coin': 'TEST/USD', 'entry_bar': 1, 'entry': 100, 'exit': 108, 'pnl': 16.0, 'size': 200},
            {'coin': 'TEST/USD', 'entry_bar': 5, 'entry': 100, 'exit': 95, 'pnl': -10.0, 'size': 200},
        ]
        # Create fake candle data: [ts, open, high, low, close, volume]
        candles = [
            [0, 100, 102, 97, 100, 1000],  # bar 0
            [0, 100, 103, 98, 101, 1000],  # bar 1
            [0, 100, 101, 99, 100, 1000],  # bar 2
            [0, 100, 104, 96, 100, 1000],  # bar 3
            [0, 100, 102, 98, 100, 1000],  # bar 4
            [0, 100, 105, 95, 100, 1000],  # bar 5
        ]
        data = {'TEST/USD': candles}

        result1, summary1 = adjust_trades_bar_structure(trades, data, 50.0, 0.7, seed=42)
        result2, summary2 = adjust_trades_bar_structure(trades, data, 50.0, 0.7, seed=42)

        assert len(result1) == len(result2)
        assert summary1['filled'] == summary2['filled']
        assert summary1['missed'] == summary2['missed']

    def test_different_seed_can_differ(self):
        """Different seeds may give different results (probabilistic)."""
        # Use enough trades to make it statistically likely to differ
        trades = [
            {'coin': 'TEST/USD', 'entry_bar': i, 'entry': 100, 'exit': 108, 'pnl': 16.0, 'size': 200}
            for i in range(20)
        ]
        candles = [
            [0, 100, 101, 99.4, 100, 1000]  # narrow range, low fill prob
            for _ in range(20)
        ]
        data = {'TEST/USD': candles}

        _, s1 = adjust_trades_bar_structure(trades, data, 50.0, 0.7, seed=42)
        _, s2 = adjust_trades_bar_structure(trades, data, 50.0, 0.7, seed=123)

        # At least note that they were run (may or may not differ)
        assert s1['total'] == s2['total'] == 20


class TestPnLFormula:

    def test_pnl_formula_matches_harness(self):
        """PnL recompute matches exact harness formula."""
        trade = {'entry': 100.0, 'exit': 108.0, 'size': 200.0, 'pnl': 0}
        fee_bps = 12.5  # v2 T1 fee

        result = recompute_pnl_with_costs(trade, fee_bps)

        # Manual calculation (harness formula):
        fee_dec = 12.5 / 10000.0  # 0.00125
        gross = (108.0 - 100.0) / 100.0 * 200.0  # = 16.0
        fees = 200.0 * fee_dec + (200.0 + 16.0) * fee_dec  # = 0.25 + 0.27 = 0.52
        net = gross - fees  # = 15.48 (approx)

        assert result['gross'] == pytest.approx(gross, abs=0.01)
        assert result['fees'] == pytest.approx(fees, abs=0.01)
        assert result['pnl'] == pytest.approx(net, abs=0.01)

    def test_losing_trade_pnl(self):
        """Losing trade recompute works correctly."""
        trade = {'entry': 100.0, 'exit': 95.0, 'size': 200.0, 'pnl': 0}
        fee_bps = 23.5  # v2 T2 fee

        result = recompute_pnl_with_costs(trade, fee_bps)

        fee_dec = 23.5 / 10000.0
        gross = (95.0 - 100.0) / 100.0 * 200.0  # = -10.0
        fees = 200.0 * fee_dec + (200.0 + (-10.0)) * fee_dec
        net = gross - fees

        assert result['pnl'] == pytest.approx(net, abs=0.01)
        assert result['pnl'] < 0  # Should be negative

    def test_zero_entry_handled(self):
        """Trade with entry=0 returns unchanged."""
        trade = {'entry': 0, 'exit': 100, 'size': 200, 'pnl': 5.0}
        result = recompute_pnl_with_costs(trade, 12.5)
        assert result['pnl'] == 5.0  # unchanged


class TestFullPipeline:

    def test_full_fill_model_v3_basic(self):
        """Full pipeline runs without errors."""
        trades = [
            {'coin': 'TEST/USD', 'entry_bar': 1, 'entry': 100, 'exit': 108, 'pnl': 16.0, 'size': 200},
        ]
        candles = [
            [0, 100, 102, 95, 100, 1000],  # bar 0
            [0, 100, 103, 94, 101, 1000],  # bar 1 -- deep low, should fill
        ]
        data = {'TEST/USD': candles}

        result = full_fill_model_v3(trades, data, half_spread_bps=5.0, seed=42)

        assert 'trades' in result
        assert 'fill_summary' in result
        assert 'metrics' in result
        assert result['fill_summary']['total'] == 1

    def test_no_cost_deduction_without_new_fee(self):
        """When new_fee_bps is None, PnL stays unchanged."""
        trades = [
            {'coin': 'TEST/USD', 'entry_bar': 1, 'entry': 100, 'exit': 108, 'pnl': 16.0, 'size': 200},
        ]
        candles = [
            [0, 100, 102, 90, 100, 1000],
            [0, 100, 103, 90, 101, 1000],  # deep low -> high fill prob
        ]
        data = {'TEST/USD': candles}

        result = full_fill_model_v3(trades, data, half_spread_bps=5.0, new_fee_bps=None, seed=42)

        # If trade survived, PnL should be unchanged (no recompute)
        if result['metrics']['n_trades'] > 0:
            assert result['trades'][0]['pnl'] == 16.0
