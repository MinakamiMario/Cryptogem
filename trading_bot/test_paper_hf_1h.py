"""Unit tests for paper_hf_1h.py — pure logic tests, no API calls."""

import json
import math
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Import module under test
from trading_bot.paper_hf_1h import (
    compute_near_ask_price,
    compute_quantity,
    safe_sell_back,
    check_rollback,
    update_state,
    new_state,
    load_state,
    save_state,
    load_universe,
    print_report,
    DUST_CAP_USD,
    ORDER_TTL_SECONDS,
    SPREAD_CAP_BPS,
    MAX_CONSECUTIVE_ERRORS,
    TAG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_exchange(price_precision=8, amount_precision=8):
    """Create mock exchange with CCXT-like precision methods."""
    ex = MagicMock()
    ex.markets = {
        'ADA/USDT': {
            'precision': {'price': price_precision, 'amount': amount_precision},
            'limits': {
                'amount': {'min': 1.0},
                'cost': {'min': 1.0},
            },
        },
        'XRP/USDT': {
            'precision': {'price': 4, 'amount': 0},
            'limits': {
                'amount': {'min': 1.0},
                'cost': {'min': 1.0},
            },
        },
    }
    ex.price_to_precision.side_effect = lambda sym, p: str(round(p, price_precision))
    ex.amount_to_precision.side_effect = lambda sym, q: str(round(q, amount_precision))
    return ex


# ---------------------------------------------------------------------------
# compute_near_ask_price
# ---------------------------------------------------------------------------

class TestComputeNearAskPrice:
    """Tests for near_ask pricing logic."""

    def test_basic_near_ask(self):
        """Price should be ask - spread * 0.10."""
        ex = _mock_exchange()
        price = compute_near_ask_price(1.00, 1.01, ex, 'ADA/USDT')
        # spread = 0.01, raw_price = 1.01 - 0.001 = 1.009
        assert price is not None
        assert price < 1.01  # Below ask (maker safe)
        assert price > 1.00  # Above bid
        assert price == pytest.approx(1.009, abs=0.001)

    def test_zero_spread(self):
        """Zero spread should return None."""
        ex = _mock_exchange()
        price = compute_near_ask_price(1.00, 1.00, ex, 'ADA/USDT')
        assert price is None

    def test_negative_spread(self):
        """Negative spread (bid > ask, crossed book) should return None."""
        ex = _mock_exchange()
        price = compute_near_ask_price(1.01, 1.00, ex, 'ADA/USDT')
        assert price is None

    def test_maker_safety_fallback_to_bid(self):
        """If rounded price >= ask, should fallback to bid."""
        ex = _mock_exchange(price_precision=1)  # Round to 1 decimal
        # spread = 0.01, raw = 1.009, rounded to 1.0 (1 decimal) < 1.01
        price = compute_near_ask_price(1.00, 1.01, ex, 'ADA/USDT')
        assert price is not None
        assert price < 1.01  # Must be below ask

    def test_precision_fallback(self):
        """If price_to_precision raises, should use market precision."""
        ex = _mock_exchange()
        ex.price_to_precision.side_effect = Exception("API error")
        price = compute_near_ask_price(1.00, 1.02, ex, 'ADA/USDT')
        assert price is not None
        assert price < 1.02

    def test_wide_spread(self):
        """Wide spread — price should still be within [bid, ask)."""
        ex = _mock_exchange()
        price = compute_near_ask_price(0.50, 1.00, ex, 'ADA/USDT')
        assert price is not None
        assert 0.50 <= price < 1.00

    def test_tiny_spread(self):
        """Very tight spread — near_ask should still be maker-safe."""
        ex = _mock_exchange(price_precision=6)
        price = compute_near_ask_price(1.000000, 1.000001, ex, 'ADA/USDT')
        # spread = 0.000001, raw_price = 1.000001 - 0.0000001 = 1.0000009
        assert price is not None
        assert price <= 1.000001  # At most ask (but check maker guard)


# ---------------------------------------------------------------------------
# compute_quantity
# ---------------------------------------------------------------------------

class TestComputeQuantity:
    """Tests for quantity calculation with CCXT precision."""

    def test_basic_quantity(self):
        """$5 at price $1.00 = 5.0 units."""
        ex = _mock_exchange()
        qty = compute_quantity(5.0, 1.0, ex, 'ADA/USDT')
        assert qty == pytest.approx(5.0, abs=0.01)

    def test_fractional_price(self):
        """$5 at price $0.50 = 10.0 units."""
        ex = _mock_exchange()
        qty = compute_quantity(5.0, 0.50, ex, 'ADA/USDT')
        assert qty == pytest.approx(10.0, abs=0.01)

    def test_zero_price(self):
        """Zero price should return 0."""
        ex = _mock_exchange()
        qty = compute_quantity(5.0, 0.0, ex, 'ADA/USDT')
        assert qty == 0.0

    def test_negative_price(self):
        """Negative price should return 0."""
        ex = _mock_exchange()
        qty = compute_quantity(5.0, -1.0, ex, 'ADA/USDT')
        assert qty == 0.0

    def test_precision_fallback(self):
        """If amount_to_precision raises, should use market precision."""
        ex = _mock_exchange(amount_precision=2)
        ex.amount_to_precision.side_effect = Exception("API error")
        qty = compute_quantity(5.0, 0.33, ex, 'ADA/USDT')
        assert qty > 0
        # $5 / 0.33 = 15.15..., rounded to 2 decimals → 15.15
        assert qty == pytest.approx(15.15, abs=0.01)


# ---------------------------------------------------------------------------
# safe_sell_back
# ---------------------------------------------------------------------------

class TestSafeSellBack:
    """Tests for sell-back with dust handling and retries."""

    def test_dust_zero_qty(self):
        """Zero quantity → dust_remaining."""
        ex = _mock_exchange()
        result = safe_sell_back(ex, 'ADA/USDT', 0.0, 1.0)
        assert result.get('dust_remaining') is True
        assert result.get('dust_reason') == 'zero_qty'

    def test_dust_below_minimum(self):
        """Notional below DUST_CAP → dust_remaining."""
        ex = _mock_exchange()
        # qty=0.1, price=1.0, notional=$0.10 < $0.50 dust cap
        result = safe_sell_back(ex, 'ADA/USDT', 0.1, 1.0)
        assert result.get('dust_remaining') is True
        assert result.get('dust_reason') == 'below_minimum'

    def test_dust_below_min_amount(self):
        """Quantity below market min_amount → dust_remaining."""
        ex = _mock_exchange()
        # min_amount=1.0, qty=0.5 < 1.0, but notional 0.5 * 10 = $5 > dust_cap
        # However min_amount check triggers first
        result = safe_sell_back(ex, 'ADA/USDT', 0.5, 10.0)
        assert result.get('dust_remaining') is True

    def test_successful_sell(self):
        """Successful market sell → sell_order_id in result."""
        ex = _mock_exchange()
        ex.create_market_sell_order.return_value = {'id': 'sell_123'}
        ex.fetch_order.return_value = {
            'average': 1.01,
            'filled': 5.0,
            'fee': {'cost': 0.005},
        }
        result = safe_sell_back(ex, 'ADA/USDT', 5.0, 1.0)
        assert result.get('sell_order_id') == 'sell_123'
        assert result.get('sell_price') == 1.01
        assert result.get('sell_qty') == 5.0
        assert result.get('sell_fee_cost') == 0.005

    def test_sell_retry(self):
        """First sell fails, second succeeds → attempts=2."""
        ex = _mock_exchange()
        ex.create_market_sell_order.side_effect = [
            Exception("rate limit"),
            {'id': 'sell_456'},
        ]
        ex.fetch_order.return_value = {
            'average': 1.0, 'filled': 5.0, 'fee': {'cost': 0.0}
        }
        result = safe_sell_back(ex, 'ADA/USDT', 5.0, 1.0)
        assert result.get('sell_order_id') == 'sell_456'
        assert result.get('sell_attempts') == 2

    def test_sell_all_retries_fail(self):
        """All 3 sell attempts fail → WARNING."""
        ex = _mock_exchange()
        ex.create_market_sell_order.side_effect = Exception("always fail")
        result = safe_sell_back(ex, 'ADA/USDT', 5.0, 1.0)
        assert 'WARNING' in result
        assert 'POSITION OPEN' in result['WARNING']
        assert result.get('sell_attempts') == 3


# ---------------------------------------------------------------------------
# check_rollback
# ---------------------------------------------------------------------------

class TestCheckRollback:
    """Tests for rollback criteria checking."""

    def _base_state(self, **overrides):
        s = new_state()
        s.update(overrides)
        return s

    def test_clean_state_no_rollback(self):
        """Clean state → no rollback."""
        state = self._base_state(filled=10, missed=2, partial=1)
        logger = MagicMock()
        assert check_rollback(state, logger) is None

    def test_r1_stuck_position(self):
        """Stuck position → rollback."""
        state = self._base_state(stuck_positions=1)
        logger = MagicMock()
        assert check_rollback(state, logger) == 'stuck_position'

    def test_r2_taker_incident(self):
        """Taker incident → rollback."""
        state = self._base_state(taker_incidents=1)
        logger = MagicMock()
        assert check_rollback(state, logger) == 'taker_incident'

    def test_r3_high_flatten_fees_warns(self):
        """High flatten fees → warning (not stop)."""
        state = self._base_state(filled=10, total_flatten_fees=6.0)
        logger = MagicMock()
        result = check_rollback(state, logger)
        assert result is None  # Warning only, not stop
        logger.warning.assert_called()

    def test_r4_high_slippage_warns(self):
        """High slippage avg → warning (not stop)."""
        state = self._base_state(filled=10, slippages=[30.0] * 25)
        logger = MagicMock()
        result = check_rollback(state, logger)
        assert result is None  # Warning only
        logger.warning.assert_called()

    def test_r5_low_fill_rate_stop(self):
        """Fill rate < 50% after 50+ trades → stop."""
        state = self._base_state(filled=20, missed=35)
        logger = MagicMock()
        assert check_rollback(state, logger) == 'low_fill_rate'

    def test_r5_low_fill_rate_too_few_trades(self):
        """Fill rate < 50% but < 50 trades → no stop (too early)."""
        state = self._base_state(filled=5, missed=10)
        logger = MagicMock()
        assert check_rollback(state, logger) is None

    def test_r6_high_error_rate_warns(self):
        """Error rate > 10% → warning."""
        state = self._base_state(filled=15, missed=2, errors=3)
        logger = MagicMock()
        result = check_rollback(state, logger)
        assert result is None  # Warning only
        logger.warning.assert_called()

    def test_r6_high_error_rate_too_few(self):
        """Error rate high but < 20 total → no check."""
        state = self._base_state(filled=5, errors=3)
        logger = MagicMock()
        result = check_rollback(state, logger)
        assert result is None


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------

class TestUpdateState:
    """Tests for state update logic."""

    def test_filled_updates(self):
        """FILLED status increments filled counter."""
        state = new_state()
        result = {
            'ts': '2026-02-21T20:00:00+00:00',
            'symbol': 'ADA/USDT',
            'status': 'FILLED',
            'slippage_vs_mid_bps': 2.5,
            'roundtrip_pnl': -0.002,
            'sell_fee_cost': 0.005,
        }
        update_state(state, result)

        assert state['total_rounds'] == 1
        assert state['filled'] == 1
        assert state['consecutive_errors'] == 0
        assert len(state['slippages']) == 1
        assert state['slippages'][0] == 2.5
        assert state['total_rt_pnl'] == -0.002
        assert state['total_flatten_fees'] == 0.005

        # Coin stats
        cs = state['coin_stats']['ADA/USDT']
        assert cs['filled'] == 1
        assert cs['total_rt_pnl'] == -0.002

    def test_missed_updates(self):
        """MISSED status increments missed counter."""
        state = new_state()
        result = {'ts': 'now', 'symbol': 'XRP/USDT', 'status': 'MISSED'}
        update_state(state, result)
        assert state['missed'] == 1
        assert state['consecutive_errors'] == 0

    def test_error_updates(self):
        """ERROR status increments error + consecutive counters."""
        state = new_state()
        result = {'ts': 'now', 'symbol': 'XRP/USDT', 'status': 'ERROR_ORDERBOOK'}
        update_state(state, result)
        assert state['errors'] == 1
        assert state['consecutive_errors'] == 1

    def test_consecutive_errors_reset_on_fill(self):
        """Fill after errors resets consecutive counter."""
        state = new_state()
        state['consecutive_errors'] = 2
        result = {'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                  'slippage_vs_mid_bps': 1.0}
        update_state(state, result)
        assert state['consecutive_errors'] == 0

    def test_taker_incident_detection(self):
        """maker_safe=False → taker_incidents incremented."""
        state = new_state()
        result = {'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                  'maker_safe': False, 'slippage_vs_mid_bps': 1.0}
        update_state(state, result)
        assert state['taker_incidents'] == 1

    def test_stuck_position_detection(self):
        """POSITION OPEN warning (non-dust) → stuck_positions incremented."""
        state = new_state()
        result = {
            'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'FILLED',
            'WARNING': 'POSITION OPEN — manual close needed!',
            'slippage_vs_mid_bps': 1.0,
        }
        update_state(state, result)
        assert state['stuck_positions'] == 1

    def test_dust_not_stuck(self):
        """POSITION OPEN with dust_remaining → NOT stuck."""
        state = new_state()
        result = {
            'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'FILLED',
            'WARNING': 'POSITION OPEN — manual close needed!',
            'dust_remaining': True,
            'slippage_vs_mid_bps': 1.0,
        }
        update_state(state, result)
        assert state['stuck_positions'] == 0

    def test_slippage_capped_at_200(self):
        """Slippage list should be capped at 200 entries."""
        state = new_state()
        for i in range(250):
            result = {
                'ts': f't{i}', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                'slippage_vs_mid_bps': float(i),
            }
            update_state(state, result)
        assert len(state['slippages']) == 200

    def test_trade_log_capped_at_100(self):
        """Trade log should be capped at 100 entries."""
        state = new_state()
        for i in range(120):
            result = {'ts': f't{i}', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                      'slippage_vs_mid_bps': 1.0}
            update_state(state, result)
        assert len(state['trade_log']) == 100

    def test_partial_updates(self):
        """PARTIAL status increments partial counter."""
        state = new_state()
        result = {'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'PARTIAL',
                  'slippage_vs_mid_bps': 3.0}
        update_state(state, result)
        assert state['partial'] == 1
        assert state['consecutive_errors'] == 0


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    """Tests for state save/load."""

    def test_new_state_structure(self):
        """new_state() should have all required keys."""
        s = new_state()
        required = [
            'start_time', 'total_rounds', 'filled', 'partial', 'missed',
            'errors', 'taker_incidents', 'stuck_positions',
            'total_rt_pnl', 'total_flatten_fees', 'slippages',
            'consecutive_errors', 'last_cycle', 'coin_stats',
            'rollback_triggered', 'trade_log',
        ]
        for key in required:
            assert key in s, f"Missing key: {key}"

    def test_save_load_roundtrip(self, tmp_path):
        """State should survive save/load cycle."""
        state_file = tmp_path / 'test_state.json'
        state = new_state()
        state['filled'] = 42
        state['total_rt_pnl'] = -1.234

        with patch('trading_bot.paper_hf_1h.STATE_FILE', state_file):
            save_state(state)
            loaded = load_state()

        assert loaded['filled'] == 42
        assert loaded['total_rt_pnl'] == -1.234

    def test_load_missing_file(self, tmp_path):
        """Missing state file → fresh state."""
        missing = tmp_path / 'nonexistent.json'
        with patch('trading_bot.paper_hf_1h.STATE_FILE', missing):
            state = load_state()
        assert state['total_rounds'] == 0
        assert state['filled'] == 0


# ---------------------------------------------------------------------------
# load_universe
# ---------------------------------------------------------------------------

class TestLoadUniverse:
    """Tests for universe loading."""

    def test_load_valid_universe(self, tmp_path):
        """Valid universe JSON → list of symbols."""
        universe = {
            'coins': [
                {'symbol': 'ADA/USDT', 'fill_rate': 1.0},
                {'symbol': 'XRP/USDT', 'fill_rate': 1.0},
            ]
        }
        path = tmp_path / 'universe.json'
        path.write_text(json.dumps(universe))
        coins = load_universe(path)
        assert coins == ['ADA/USDT', 'XRP/USDT']

    def test_load_empty_universe(self, tmp_path):
        """Empty coins list → ValueError."""
        universe = {'coins': []}
        path = tmp_path / 'universe.json'
        path.write_text(json.dumps(universe))
        with pytest.raises(ValueError, match="No coins"):
            load_universe(path)

    def test_load_missing_coins_key(self, tmp_path):
        """Missing 'coins' key → ValueError."""
        universe = {'version': 1}
        path = tmp_path / 'universe.json'
        path.write_text(json.dumps(universe))
        with pytest.raises(ValueError, match="No coins"):
            load_universe(path)


# ---------------------------------------------------------------------------
# print_report (smoke test)
# ---------------------------------------------------------------------------

class TestPrintReport:
    """Smoke test for report printing."""

    def test_report_empty_state(self, capsys):
        """Report should run without error on empty state."""
        state = new_state()
        print_report(state)
        captured = capsys.readouterr()
        assert 'EXECUTION VALIDATION REPORT' in captured.out
        assert 'Total rounds: 0' in captured.out

    def test_report_with_data(self, capsys):
        """Report with data should show rates and per-coin stats."""
        state = new_state()
        for _ in range(5):
            update_state(state, {
                'ts': 'now', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                'slippage_vs_mid_bps': 2.0, 'roundtrip_pnl': -0.001,
                'sell_fee_cost': 0.005,
            })
        update_state(state, {
            'ts': 'now', 'symbol': 'XRP/USDT', 'status': 'MISSED',
        })

        print_report(state)
        captured = capsys.readouterr()
        assert 'Touch rate:' in captured.out
        assert 'Fill rate:' in captured.out
        assert 'ADA/USDT' in captured.out


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    """Verify safety-critical constants."""

    def test_tag(self):
        assert TAG == 'hf_1h_paper'

    def test_ttl(self):
        assert ORDER_TTL_SECONDS == 120

    def test_spread_cap(self):
        assert SPREAD_CAP_BPS == 75.0

    def test_dust_cap(self):
        assert DUST_CAP_USD == 0.50

    def test_max_consecutive_errors(self):
        assert MAX_CONSECUTIVE_ERRORS == 3


# ---------------------------------------------------------------------------
# Integration: multi-round state progression
# ---------------------------------------------------------------------------

class TestMultiRoundProgression:
    """Test state evolution over multiple rounds."""

    def test_mixed_results_progression(self):
        """State should correctly track mixed FILLED/MISSED/ERROR results."""
        state = new_state()

        results = [
            {'ts': 't1', 'symbol': 'ADA/USDT', 'status': 'FILLED',
             'slippage_vs_mid_bps': 2.0, 'roundtrip_pnl': -0.001,
             'sell_fee_cost': 0.005, 'maker_safe': True},
            {'ts': 't2', 'symbol': 'XRP/USDT', 'status': 'FILLED',
             'slippage_vs_mid_bps': 0.5, 'roundtrip_pnl': 0.002,
             'sell_fee_cost': 0.003, 'maker_safe': True},
            {'ts': 't3', 'symbol': 'SUI/USDT', 'status': 'MISSED'},
            {'ts': 't4', 'symbol': 'ADA/USDT', 'status': 'ERROR_ORDERBOOK',
             'error': 'timeout'},
            {'ts': 't5', 'symbol': 'XRP/USDT', 'status': 'PARTIAL',
             'slippage_vs_mid_bps': 1.5, 'roundtrip_pnl': -0.0005,
             'sell_fee_cost': 0.002},
        ]

        for r in results:
            update_state(state, r)

        assert state['total_rounds'] == 5
        assert state['filled'] == 2
        assert state['missed'] == 1
        assert state['partial'] == 1
        assert state['errors'] == 1
        assert state['total_rt_pnl'] == pytest.approx(0.0005, abs=0.0001)
        assert state['total_flatten_fees'] == pytest.approx(0.010, abs=0.001)
        assert len(state['slippages']) == 3  # FILLED + PARTIAL only
        assert len(state['trade_log']) == 5

        # Per-coin
        assert state['coin_stats']['ADA/USDT']['filled'] == 1
        assert state['coin_stats']['ADA/USDT']['errors'] == 1
        assert state['coin_stats']['XRP/USDT']['filled'] == 1
        assert state['coin_stats']['XRP/USDT']['partial'] == 1
        assert state['coin_stats']['SUI/USDT']['missed'] == 1

    def test_rollback_after_many_errors(self):
        """Consecutive errors should trigger rollback via main loop check."""
        state = new_state()
        for i in range(MAX_CONSECUTIVE_ERRORS):
            result = {'ts': f't{i}', 'symbol': 'ADA/USDT',
                      'status': 'ERROR_ORDERBOOK'}
            update_state(state, result)

        assert state['consecutive_errors'] == MAX_CONSECUTIVE_ERRORS

    def test_rollback_after_low_fill_rate(self):
        """50+ trades with < 50% fill → low_fill_rate rollback."""
        state = new_state()
        for i in range(20):
            update_state(state, {
                'ts': f't{i}', 'symbol': 'ADA/USDT', 'status': 'FILLED',
                'slippage_vs_mid_bps': 1.0,
            })
        for i in range(35):
            update_state(state, {
                'ts': f't{i+20}', 'symbol': 'ADA/USDT', 'status': 'MISSED',
            })

        logger = MagicMock()
        trigger = check_rollback(state, logger)
        assert trigger == 'low_fill_rate'
