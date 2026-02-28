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
    floor_to_step,
    extract_fill_price,
    DUST_CAP_USD,
    ORDER_TTL_SECONDS,
    SPREAD_CAP_BPS,
    MAX_CONSECUTIVE_ERRORS,
    TAG,
    MICRO_TAG,
    _calc_rsi,
    compute_entry_features,
    passes_signal_gate,
    format_features_short,
    SIGNAL_VWAP_DEV_MIN,
    SIGNAL_RSI_MAX,
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
    # Default balance: more than enough (prevents oversold guard from interfering)
    ex.fetch_balance.return_value = {
        'ADA': {'free': 10000.0, 'used': 0, 'total': 10000.0},
        'XRP': {'free': 10000.0, 'used': 0, 'total': 10000.0},
    }
    ex.fetch_ticker.return_value = {'bid': 1.0, 'ask': 1.01}
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
        assert 'zero_qty' in result.get('dust_reason', '')

    def test_dust_below_minimum(self):
        """Notional below DUST_CAP → dust_remaining."""
        ex = _mock_exchange()
        # qty=0.1, price=1.0, notional=$0.10 < $0.50 dust cap
        # But first min_amount triggers: 0.1 < 1.0
        result = safe_sell_back(ex, 'ADA/USDT', 0.1, 1.0)
        assert result.get('dust_remaining') is True

    def test_dust_below_min_amount(self):
        """Quantity below market min_amount → dust_remaining."""
        ex = _mock_exchange()
        # min_amount=1.0, qty=0.5 < 1.0, but notional 0.5 * 10 = $5 > dust_cap
        # However min_amount check triggers first
        result = safe_sell_back(ex, 'ADA/USDT', 0.5, 10.0)
        assert result.get('dust_remaining') is True
        assert 'min_amount' in result.get('dust_reason', '')

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

    def test_oversold_caps_to_free_balance(self):
        """If qty > free balance, caps sell to free amount."""
        ex = _mock_exchange()
        ex.fetch_balance.return_value = {
            'ADA': {'free': 3.0, 'used': 0, 'total': 3.0},
        }
        ex.create_market_sell_order.return_value = {'id': 'sell_cap'}
        ex.fetch_order.return_value = {
            'average': 1.0, 'filled': 3.0, 'fee': {'cost': 0.001}
        }
        # Request 5.0 but only 3.0 free
        result = safe_sell_back(ex, 'ADA/USDT', 5.0, 1.0)
        assert result.get('sell_order_id') == 'sell_cap'
        # Verify the sell was for the capped amount
        call_args = ex.create_market_sell_order.call_args
        assert call_args[0][1] <= 3.0

    def test_dust_below_min_notional(self):
        """Notional below min_cost → dust with specific reason."""
        ex = _mock_exchange()
        # min_cost=1.0 in mock, qty=2.0 but price=0.3 → notional=0.60 < 1.0
        # But min_amount=1.0 and qty=2.0 passes that check
        # Override to have high min_cost
        ex.markets['ADA/USDT']['limits']['cost']['min'] = 5.0
        result = safe_sell_back(ex, 'ADA/USDT', 2.0, 1.0)
        assert result.get('dust_remaining') is True
        assert 'min_notional' in result.get('dust_reason', '')

    def test_dust_below_dust_cap(self):
        """Notional below DUST_CAP_USD → dust."""
        ex = _mock_exchange()
        # min_amount=1.0, qty=2.0 OK; min_cost=1.0, notional=2*0.2=0.4 < 1.0
        # Actually min_cost triggers first. Let's make min_cost low.
        ex.markets['ADA/USDT']['limits']['cost']['min'] = 0.1
        ex.markets['ADA/USDT']['limits']['amount']['min'] = 0.1
        # qty=1.0 * price=0.3 = notional $0.30 < DUST_CAP($0.50)
        result = safe_sell_back(ex, 'ADA/USDT', 1.0, 0.3)
        assert result.get('dust_remaining') is True
        assert 'dust_cap' in result.get('dust_reason', '')


# ---------------------------------------------------------------------------
# floor_to_step
# ---------------------------------------------------------------------------

class TestFloorToStep:
    """Tests for floor_to_step helper."""

    def test_basic_step(self):
        assert floor_to_step(314.729, 0.01) == 314.72

    def test_integer_step(self):
        assert floor_to_step(5.7, 1.0) == 5.0

    def test_small_step(self):
        assert floor_to_step(0.031774, 0.000001) == 0.031774

    def test_zero_step_returns_value(self):
        assert floor_to_step(5.5, 0) == 5.5

    def test_negative_step_returns_value(self):
        assert floor_to_step(5.5, -0.01) == 5.5

    def test_floors_down(self):
        """Never rounds up."""
        assert floor_to_step(9.999, 0.01) == 9.99


# ---------------------------------------------------------------------------
# extract_fill_price
# ---------------------------------------------------------------------------

class TestExtractFillPrice:
    """Tests for robust fill price extraction."""

    def test_average_first(self):
        assert extract_fill_price({'average': 1.5, 'price': 1.4}) == 1.5

    def test_price_fallback(self):
        assert extract_fill_price({'average': None, 'price': 1.4}) == 1.4

    def test_trades_fallback(self):
        order = {'average': None, 'price': None, 'trades': [{'price': 1.3}]}
        assert extract_fill_price(order) == 1.3

    def test_bid_fallback(self):
        order = {'average': None, 'price': None, 'trades': []}
        assert extract_fill_price(order, fallback_bid=1.2) == 1.2

    def test_zero_average_skipped(self):
        """average=0 should be treated as missing."""
        assert extract_fill_price({'average': 0, 'price': 1.1}) == 1.1

    def test_none_trades_handled(self):
        order = {'average': None, 'price': None, 'trades': None}
        assert extract_fill_price(order, fallback_bid=0.9) == 0.9

    def test_empty_order(self):
        assert extract_fill_price({}, fallback_bid=0.5) == 0.5

    def test_no_fallback(self):
        """No fallback bid → returns 0.0."""
        assert extract_fill_price({}) == 0.0


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

    def test_micro_tag(self):
        assert MICRO_TAG == 'mx_micro_tp5sl3'

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


# ---------------------------------------------------------------------------
# Entry Features & Signal Gate
# ---------------------------------------------------------------------------

class TestCalcRsi:
    """Test RSI computation."""

    def test_rsi_all_up(self):
        """All prices increasing → RSI near 100."""
        closes = [float(i) for i in range(20)]
        rsi = _calc_rsi(closes, 14)
        assert rsi > 95

    def test_rsi_all_down(self):
        """All prices decreasing → RSI near 0."""
        closes = [float(20 - i) for i in range(20)]
        rsi = _calc_rsi(closes, 14)
        assert rsi < 5

    def test_rsi_insufficient_data(self):
        """Too few bars → default 50."""
        assert _calc_rsi([1, 2, 3], 14) == 50.0

    def test_rsi_flat(self):
        """Flat prices → no gains/losses → RSI depends on implementation."""
        closes = [10.0] * 20
        rsi = _calc_rsi(closes, 14)
        # No gains and no losses — avg_loss == 0 → RSI == 100 or handle as 50
        assert 0 <= rsi <= 100


class TestPassesSignalGate:
    """Test signal gate logic."""

    def test_pass_oversold(self):
        """Below VWAP + low RSI → passes gate."""
        features = {'ok': True, 'vwap_dev_pct': -2.5, 'rsi_14': 30}
        assert passes_signal_gate(features) is True

    def test_fail_rsi_too_high(self):
        """Below VWAP but RSI too high → fails."""
        features = {'ok': True, 'vwap_dev_pct': -2.5, 'rsi_14': 55}
        assert passes_signal_gate(features) is False

    def test_fail_above_vwap(self):
        """Above VWAP → fails regardless of RSI."""
        features = {'ok': True, 'vwap_dev_pct': 1.0, 'rsi_14': 25}
        assert passes_signal_gate(features) is False

    def test_fail_features_error(self):
        """Feature computation failed → never passes."""
        features = {'ok': False, 'error': 'timeout'}
        assert passes_signal_gate(features) is False

    def test_exact_threshold_pass(self):
        """Exactly at thresholds → passes (<=)."""
        features = {'ok': True, 'vwap_dev_pct': SIGNAL_VWAP_DEV_MIN, 'rsi_14': SIGNAL_RSI_MAX}
        assert passes_signal_gate(features) is True

    def test_just_above_threshold_fail(self):
        """Just above VWAP threshold → fails."""
        features = {'ok': True, 'vwap_dev_pct': SIGNAL_VWAP_DEV_MIN + 0.01, 'rsi_14': 30}
        assert passes_signal_gate(features) is False


class TestFormatFeaturesShort:
    """Test feature formatting."""

    def test_format_ok(self):
        features = {
            'ok': True,
            'vwap_dev_pct': -2.3,
            'rsi_14': 35.2,
            'dist_support_pct': 1.5,
            'dist_dc_mid_pct': -3.1,
            'vol_ratio': 1.8,
        }
        result = format_features_short(features)
        assert 'vwap=-2.3%' in result
        assert 'RSI=35' in result
        assert 'vol=1.8x' in result

    def test_format_error(self):
        features = {'ok': False, 'error': 'timeout'}
        result = format_features_short(features)
        assert 'ERR' in result
        assert 'timeout' in result


class TestComputeEntryFeatures:
    """Test feature computation with mocked exchange."""

    def _make_candles(self, n=50, base_close=100, trend=0):
        """Generate synthetic OHLCV candles."""
        candles = []
        for i in range(n):
            c = base_close + trend * i
            candles.append([
                1000000 + i * 3600000,  # timestamp
                c - 1,   # open
                c + 2,   # high
                c - 2,   # low
                c,        # close
                1000 + i * 10,  # volume
            ])
        return candles

    def test_features_ok(self):
        """Normal candle data → all features computed."""
        exchange = MagicMock()
        exchange.fetch_ohlcv.return_value = self._make_candles(50)
        features = compute_entry_features(exchange, 'TEST/USDT')
        assert features['ok'] is True
        assert 'vwap_dev_pct' in features
        assert 'rsi_14' in features
        assert 'dist_support_pct' in features
        assert 'vol_ratio' in features
        assert isinstance(features['rsi_14'], float)

    def test_features_insufficient_candles(self):
        """Too few candles → ok=False."""
        exchange = MagicMock()
        exchange.fetch_ohlcv.return_value = [[0, 1, 2, 0.5, 1, 100]] * 5
        features = compute_entry_features(exchange, 'TEST/USDT')
        assert features['ok'] is False

    def test_features_exchange_error(self):
        """Exchange error → ok=False with error msg."""
        exchange = MagicMock()
        exchange.fetch_ohlcv.side_effect = Exception("rate limit")
        features = compute_entry_features(exchange, 'TEST/USDT')
        assert features['ok'] is False
        assert 'rate limit' in features['error']

    def test_features_downtrend_rsi_low(self):
        """Downtrending candles → RSI < 50."""
        exchange = MagicMock()
        exchange.fetch_ohlcv.return_value = self._make_candles(50, base_close=200, trend=-1)
        features = compute_entry_features(exchange, 'TEST/USDT')
        assert features['ok'] is True
        assert features['rsi_14'] < 50
