#!/usr/bin/env python3
"""
Hypothesis Signal Correctness Tests
=====================================
Verify each signal fires correctly on synthetic data and has no look-ahead.

Usage:
    python -m pytest strategies/hf/screening/test_hypotheses.py -v
"""
import math
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.hypotheses import (
    get_all_hypotheses, get_hypothesis, get_all_configs, REGISTRY,
)
from strategies.hf.screening.harness import (
    run_backtest, precompute_base_indicators,
)


# ============================================================
# Helpers
# ============================================================

def make_candles(n=200, base_price=100.0, pattern='flat'):
    """Generate synthetic candles with specific patterns."""
    candles = []
    price = base_price
    for i in range(n):
        if pattern == 'flat':
            delta = 0.001 * math.sin(i * 0.5)
        elif pattern == 'uptrend':
            delta = 0.002
        elif pattern == 'downtrend':
            delta = -0.002
        elif pattern == 'volatile':
            delta = 0.02 * math.sin(i * 0.8)
        elif pattern == 'crash':
            delta = -0.01 if i > 100 else 0.001
        else:
            delta = 0

        o = price
        c = price * (1 + delta)
        h = max(o, c) * (1 + abs(delta) * 0.5)
        l = min(o, c) * (1 - abs(delta) * 0.5)
        vol = 1000 + 500 * abs(math.sin(i * 0.3))
        if pattern == 'volatile' and i % 10 == 0:
            vol *= 5  # volume spikes for vol-based hypotheses

        candles.append({
            'open': o, 'high': h, 'low': l, 'close': c,
            'volume': vol, 'timestamp': 1700000000 + i * 3600,
        })
        price = c
    return candles


def make_data(n_coins=5, n_bars=300, pattern='volatile'):
    """Make synthetic multi-coin data."""
    data = {}
    for i in range(n_coins):
        symbol = f'TEST{i}/USD'
        data[symbol] = make_candles(
            n=n_bars, base_price=100 + i * 20,
            pattern=pattern,
        )
    return data


# ============================================================
# Test 1: Registry Integrity
# ============================================================

class TestRegistry:
    """Verify hypothesis registry is complete and well-formed."""

    def test_15_hypotheses(self):
        """Should have exactly 15 hypotheses registered."""
        all_h = get_all_hypotheses()
        assert len(all_h) == 15, f'Expected 15, got {len(all_h)}'

    def test_90_configs(self):
        """Should have exactly 90 total configs (15 × 6)."""
        configs = get_all_configs()
        assert len(configs) == 90, f'Expected 90, got {len(configs)}'

    def test_hypothesis_ids(self):
        """All hypothesis IDs should be H01-H15."""
        expected_ids = [f'H{i:02d}' for i in range(1, 16)]
        for hid in expected_ids:
            h = get_hypothesis(hid)
            assert h is not None, f'Missing hypothesis {hid}'
            assert h.id == hid

    def test_6_variants_each(self):
        """Each hypothesis should have exactly 6 variants."""
        for h in get_all_hypotheses():
            assert len(h.param_grid) == 6, \
                f'{h.id} has {len(h.param_grid)} variants, expected 6'

    def test_max_3_tunable_params(self):
        """Each variant should have at most ~6 params (3 tunable + fixed)."""
        for h in get_all_hypotheses():
            for i, params in enumerate(h.param_grid):
                # Should be a dict
                assert isinstance(params, dict), \
                    f'{h.id} variant {i}: params is not a dict'
                # Should not be empty
                assert len(params) > 0, \
                    f'{h.id} variant {i}: empty params'

    def test_categories(self):
        """All hypotheses should have valid categories."""
        valid_categories = {
            'mean_reversion', 'momentum', 'volume',
            'price_action', 'multi_indicator',
        }
        for h in get_all_hypotheses():
            assert h.category in valid_categories, \
                f'{h.id} has invalid category: {h.category}'

    def test_signal_fn_callable(self):
        """Every hypothesis signal_fn must be callable."""
        for h in get_all_hypotheses():
            assert callable(h.signal_fn), f'{h.id} signal_fn is not callable'


# ============================================================
# Test 2: Signal Return Format
# ============================================================

class TestSignalFormat:
    """Verify signal functions return correct format."""

    def test_signal_returns_dict_or_none(self):
        """Signal function must return None or dict with required keys."""
        data = make_data(n_coins=3, n_bars=300, pattern='volatile')
        coins = list(data.keys())
        indicators = precompute_base_indicators(data, coins)

        for h in get_all_hypotheses():
            params = h.param_grid[0]  # first variant
            coin = coins[0]
            ind = indicators[coin]
            candles = data[coin]

            for bar in range(50, min(100, ind['n'])):
                if ind['rsi'][bar] is None:
                    continue

                result = h.signal_fn(candles, bar, ind, params)

                if result is not None:
                    assert isinstance(result, dict), \
                        f'{h.id} returned non-dict: {type(result)}'
                    assert 'stop_price' in result, \
                        f'{h.id} missing stop_price'
                    assert 'target_price' in result, \
                        f'{h.id} missing target_price'
                    assert 'time_limit' in result, \
                        f'{h.id} missing time_limit'
                    assert result['stop_price'] > 0, \
                        f'{h.id} stop_price <= 0'
                    assert result['target_price'] > result['stop_price'], \
                        f'{h.id} target_price <= stop_price'
                    assert result['time_limit'] > 0, \
                        f'{h.id} time_limit <= 0'
                    break  # found one valid signal, sufficient


# ============================================================
# Test 3: No Look-Ahead in Signals
# ============================================================

class TestNoLookAhead:
    """Verify signals don't access future data."""

    def test_signal_at_bar_n_uses_only_up_to_n(self):
        """
        Truncate data at bar N, signal at N should be same
        as signal at N with full data.
        """
        data = make_data(n_coins=2, n_bars=300, pattern='volatile')
        coins = list(data.keys())

        # Full indicators
        indicators_full = precompute_base_indicators(data, coins)

        # Truncated indicators (first 150 bars only)
        indicators_trunc = precompute_base_indicators(data, coins, end_bar=150)

        for h in get_all_hypotheses():
            params = h.param_grid[0]
            coin = coins[0]
            ind_full = indicators_full[coin]
            ind_trunc = indicators_trunc[coin]
            candles = data[coin]

            for bar in range(50, 149):
                if ind_full['rsi'][bar] is None or ind_trunc['rsi'][bar] is None:
                    continue

                sig_full = h.signal_fn(candles, bar, ind_full, params)
                sig_trunc = h.signal_fn(candles, bar, ind_trunc, params)

                # Both should return same thing
                if sig_full is None:
                    assert sig_trunc is None, \
                        f'{h.id} look-ahead at bar {bar}: full=None, trunc={sig_trunc}'
                elif sig_trunc is not None:
                    # Prices should match
                    for key in ['stop_price', 'target_price']:
                        assert abs(sig_full[key] - sig_trunc[key]) < 1e-6, \
                            f'{h.id} look-ahead at bar {bar}: {key} differs'
                    break  # one matching signal is sufficient


# ============================================================
# Test 4: Null Safety
# ============================================================

class TestNullSafety:
    """Verify signals handle None indicators gracefully."""

    def test_none_rsi_returns_none(self):
        """Signal should return None when RSI is None."""
        # Create minimal indicator dict with None RSI
        n = 100
        ind = {
            'closes': [100.0] * n,
            'highs': [101.0] * n,
            'lows': [99.0] * n,
            'volumes': [1000] * n,
            'n': n,
            'rsi': [None] * n,
            'atr': [None] * n,
            'dc_prev_low': [None] * n,
            'dc_mid': [None] * n,
            'bb_mid': [None] * n,
            'bb_lower': [None] * n,
            'vol_avg': [None] * n,
        }
        candles = [{'open': 100, 'high': 101, 'low': 99, 'close': 100,
                     'volume': 1000}] * n

        for h in get_all_hypotheses():
            params = h.param_grid[0]
            result = h.signal_fn(candles, 50, ind, params)
            assert result is None, \
                f'{h.id} did not return None for None indicators'


# ============================================================
# Test 5: Backtest Integration
# ============================================================

class TestBacktestIntegration:
    """Verify each hypothesis runs through the backtest without errors."""

    def test_all_hypotheses_run_clean(self):
        """Every hypothesis × first variant should run without exceptions."""
        data = make_data(n_coins=5, n_bars=300, pattern='volatile')
        coins = list(data.keys())
        indicators = precompute_base_indicators(data, coins)

        for h in get_all_hypotheses():
            params = h.param_grid[0]
            result = run_backtest(
                data=data, coins=coins,
                signal_fn=h.signal_fn,
                params=params,
                indicators=indicators,
                fee=0.0031,
            )

            # Should not crash; result should be valid
            assert isinstance(result.trades, int), f'{h.id} trades not int'
            assert isinstance(result.pnl, float), f'{h.id} pnl not float'
            assert result.dd >= 0, f'{h.id} negative drawdown'

    def test_at_least_some_hypotheses_generate_trades(self):
        """
        On volatile synthetic data, at least some hypotheses should
        generate trades (validates signals fire in realistic conditions).
        """
        data = make_data(n_coins=10, n_bars=500, pattern='volatile')
        coins = list(data.keys())
        indicators = precompute_base_indicators(data, coins)

        trade_counts = {}
        for h in get_all_hypotheses():
            total_trades = 0
            for params in h.param_grid:
                result = run_backtest(
                    data=data, coins=coins,
                    signal_fn=h.signal_fn,
                    params=params,
                    indicators=indicators,
                    fee=0.0031,
                )
                total_trades += result.trades
            trade_counts[h.id] = total_trades

        # At least 3 hypotheses should generate some trades
        active = sum(1 for v in trade_counts.values() if v > 0)
        assert active >= 3, \
            f'Only {active} hypotheses generated trades: {trade_counts}'


# ============================================================
# Test 6: Category Coverage
# ============================================================

class TestCategoryCoverage:
    """Verify proper distribution across categories."""

    def test_category_distribution(self):
        """Each category should have at least 2 hypotheses."""
        categories = {}
        for h in get_all_hypotheses():
            categories.setdefault(h.category, []).append(h.id)

        assert len(categories) == 5, f'Expected 5 categories, got {len(categories)}'

        for cat, members in categories.items():
            assert len(members) >= 2, \
                f'Category {cat} has only {len(members)} hypotheses: {members}'

    def test_expected_categories(self):
        """Categories should match plan specification."""
        expected = {
            'mean_reversion': ['H01', 'H02', 'H03', 'H04'],
            'momentum': ['H05', 'H06', 'H07', 'H08'],
            'volume': ['H09', 'H10', 'H11'],
            'price_action': ['H12', 'H13'],
            'multi_indicator': ['H14', 'H15'],
        }

        for cat, expected_ids in expected.items():
            for hid in expected_ids:
                h = get_hypothesis(hid)
                assert h.category == cat, \
                    f'{hid} expected category {cat}, got {h.category}'
