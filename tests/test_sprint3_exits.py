"""Microtests for Sprint 3 DualConfirm exit logic."""
import sys
sys.path.insert(0, '/Users/oussama/Cryptogem')

import importlib
import pytest

exits_mod = importlib.import_module('strategies.4h.sprint3.exits')
evaluate_exit = exits_mod.evaluate_exit_hybrid_notrl
ExitSignal = exits_mod.ExitSignal
CLASS_A_REASONS = exits_mod.CLASS_A_REASONS


class TestExitPriority:
    """Verify exit priority order matches agent_team_v3.py hybrid_notrl."""

    def test_fixed_stop_fires_first(self):
        """FIXED STOP has highest priority -- fires even if RSI recovered."""
        # entry=100, max_stop_pct=15 -> hard_stop=85
        # low=84 (below stop), rsi=50 (above recovery target)
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=84.0, high=95.0, close=90.0,
            rsi=50.0, dc_mid=95.0, bb_mid=93.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "FIXED STOP"
        assert result.price == 85.0  # hard_stop, not close
        assert result.class_ == "B"

    def test_time_max_before_smart_exits(self):
        """TIME MAX fires before RSI RECOVERY and DC TARGET."""
        # bars_in = 15 (= time_max), rsi=50, close>=dc_mid
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=15,
            low=95.0, high=105.0, close=103.0,
            rsi=50.0, dc_mid=102.0, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=15,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "TIME MAX"
        assert result.price == 103.0  # close
        assert result.class_ == "B"

    def test_rsi_recovery_before_dc_target(self):
        """RSI RECOVERY fires before DC TARGET when both conditions met."""
        # rsi=50 (>= 45 target), close=103 (>= dc_mid=102)
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=95.0, high=105.0, close=103.0,
            rsi=50.0, dc_mid=102.0, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "RSI RECOVERY"
        assert result.class_ == "A"

    def test_dc_target_before_bb_target(self):
        """DC TARGET fires before BB TARGET when RSI hasn't recovered."""
        # rsi=40 (< 45 target), close=103 (>= dc_mid=102 and >= bb_mid=101)
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=95.0, high=105.0, close=103.0,
            rsi=40.0, dc_mid=102.0, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "DC TARGET"
        assert result.class_ == "A"

    def test_bb_target_when_dc_not_reached(self):
        """BB TARGET fires when DC not reached but BB mid breached."""
        # close=101.5, dc_mid=103 (not reached), bb_mid=101 (reached)
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=95.0, high=102.0, close=101.5,
            rsi=40.0, dc_mid=103.0, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "BB TARGET"
        assert result.class_ == "A"


class TestNoExit:
    """Verify no exit when conditions aren't met."""

    def test_no_exit_normal_bar(self):
        """No exit when price is between stop and targets."""
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=3,
            low=96.0, high=102.0, close=99.0,
            rsi=35.0, dc_mid=105.0, bb_mid=103.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is None

    def test_rsi_recovery_blocked_by_min_bars(self):
        """RSI RECOVERY doesn't fire before min_bars reached."""
        # bar=1 (bars_in=1 < min_bars=2), rsi=50 (above target)
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=1,
            low=96.0, high=102.0, close=101.0,
            rsi=50.0, dc_mid=105.0, bb_mid=103.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0, rsi_rec_min_bars=2,
        )
        assert result is None

    def test_rsi_recovery_disabled(self):
        """RSI RECOVERY doesn't fire when disabled."""
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=96.0, high=102.0, close=101.0,
            rsi=50.0, dc_mid=105.0, bb_mid=103.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_recovery=False,
            rsi_rec_target=45.0,
        )
        assert result is None  # Only DC/BB could fire, but not reached


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_none_rsi_skips_recovery(self):
        """RSI=None skips RSI RECOVERY, falls through to DC TARGET."""
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=96.0, high=105.0, close=103.0,
            rsi=None, dc_mid=102.0, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=20,
        )
        assert result is not None
        assert result.reason == "DC TARGET"

    def test_none_dc_mid_skips_to_bb(self):
        """dc_mid=None skips DC TARGET, fires BB TARGET."""
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=5,
            low=96.0, high=105.0, close=103.0,
            rsi=40.0, dc_mid=None, bb_mid=101.0,
            max_stop_pct=15.0, time_max_bars=20,
            rsi_rec_target=45.0,
        )
        assert result is not None
        assert result.reason == "BB TARGET"

    def test_stop_price_exact_boundary(self):
        """low == hard_stop triggers FIXED STOP."""
        # entry=100, max_stop=10% -> hard_stop=90, low=90 exactly
        result = evaluate_exit(
            entry_price=100.0, entry_bar=0, bar=3,
            low=90.0, high=95.0, close=92.0,
            rsi=35.0, dc_mid=105.0, bb_mid=103.0,
            max_stop_pct=10.0, time_max_bars=20,
        )
        assert result is not None
        assert result.reason == "FIXED STOP"
        assert result.price == 90.0

    def test_class_a_reasons_set(self):
        """Verify CLASS_A_REASONS contains expected exit types."""
        assert "RSI RECOVERY" in CLASS_A_REASONS
        assert "DC TARGET" in CLASS_A_REASONS
        assert "BB TARGET" in CLASS_A_REASONS
        assert "FIXED STOP" not in CLASS_A_REASONS
        assert "TIME MAX" not in CLASS_A_REASONS


class TestExitSignalDataclass:
    """Verify ExitSignal dataclass structure."""

    def test_exit_signal_fields(self):
        sig = ExitSignal(price=100.0, reason="TEST", class_="A")
        assert sig.price == 100.0
        assert sig.reason == "TEST"
        assert sig.class_ == "A"
