"""
Smoke tests for MS Sprint 1 hypotheses + gates.

Tests:
  - build_sweep_configs() returns 18 configs
  - Each signal_fn returns None on missing indicators
  - Each signal_fn returns valid dict on synthetic trigger data
  - Gates evaluate correctly on sample results
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from strategies.ms.hypotheses import (
    build_sweep_configs,
    signal_liq_sweep_reclaim,
    signal_fvg_fill,
    signal_ob_touch,
    signal_sfp,
    signal_structure_shift_pullback,
    _DC_EXIT_GRID,
)
from strategies.ms.indicators import FVG, BoS, OrderBlock, LiquidityZone
from strategies.ms.gates import evaluate_ms_gates, GateReport


# ═══════════════════════════════════════════════════════════════════
# Config structure tests
# ═══════════════════════════════════════════════════════════════════

class TestBuildSweepConfigs:

    def test_config_count(self):
        configs = build_sweep_configs()
        assert len(configs) == 18, f"Expected 18 configs, got {len(configs)}"

    def test_unique_ids(self):
        configs = build_sweep_configs()
        ids = [c["id"] for c in configs]
        assert len(ids) == len(set(ids))

    def test_all_callable(self):
        configs = build_sweep_configs()
        for c in configs:
            assert callable(c["signal_fn"]), f"Not callable: {c['id']}"

    def test_dc_exit_params_present(self):
        configs = build_sweep_configs()
        for c in configs:
            assert "max_stop_pct" in c["params"]
            assert "time_max_bars" in c["params"]
            assert "rsi_recovery" in c["params"]

    def test_family_distribution(self):
        from collections import Counter
        configs = build_sweep_configs()
        families = Counter(c["family"] for c in configs)
        assert families["liq_sweep"] == 4
        assert families["fvg_fill"] == 4
        assert families["ob_touch"] == 4
        assert families["sfp"] == 3
        assert families["shift_pb"] == 3


# ═══════════════════════════════════════════════════════════════════
# Signal function tests — None on empty data
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def empty_indicators():
    """Minimal indicators that should cause all signals to return None."""
    return {
        "closes": [100.0], "highs": [101.0], "lows": [99.0],
        "opens": [100.0], "volumes": [1000.0],
        "atr": [None], "rsi": [None],
        "dc_mid": [None], "bb_mid": [None],
        "dc_prev_low": [None], "vol_avg": [None],
        "swing_lows": [None], "swing_highs": [None],
        "fvg_snapshots": [[]], "bos_events": [None],
        "ob_snapshots": [[]], "liq_zones": [[]],
    }


class TestSignalNoneOnEmpty:

    def test_liq_sweep_none(self, empty_indicators):
        result = signal_liq_sweep_reclaim(None, 0, empty_indicators, _DC_EXIT_GRID)
        assert result is None

    def test_fvg_fill_none(self, empty_indicators):
        result = signal_fvg_fill(None, 0, empty_indicators, _DC_EXIT_GRID)
        assert result is None

    def test_ob_touch_none(self, empty_indicators):
        result = signal_ob_touch(None, 0, empty_indicators, _DC_EXIT_GRID)
        assert result is None

    def test_sfp_none(self, empty_indicators):
        result = signal_sfp(None, 0, empty_indicators, _DC_EXIT_GRID)
        assert result is None

    def test_structure_shift_none(self, empty_indicators):
        result = signal_structure_shift_pullback(None, 0, empty_indicators, _DC_EXIT_GRID)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# Signal function tests — valid returns on synthetic trigger data
# ═══════════════════════════════════════════════════════════════════

class TestSignalTriggers:

    def test_liq_sweep_triggers(self):
        """Liquidity sweep should trigger when low < swing low < close."""
        n = 15
        # Create data with a swing low at bar 5 (confirmed bar 7)
        lows = [15, 13, 11, 9, 7, 5, 7, 9, 11, 13, 15, 13, 4, 13, 15]
        closes = [14, 12, 10, 8, 6, 6, 8, 10, 12, 14, 14, 12, 6, 12, 14]
        highs = [16, 14, 12, 10, 8, 7, 9, 11, 13, 15, 16, 14, 14, 14, 16]
        opens = [15, 13, 11, 9, 7, 5.5, 7, 9, 11, 13, 15, 13, 10, 13, 15]
        swing_lows = [None] * n
        swing_lows[7] = 5  # Confirmed swing low at bar 7

        ind = {
            "closes": closes, "highs": highs, "lows": lows, "opens": opens,
            "volumes": [5000.0] * n, "atr": [2.0] * n,
            "rsi": [30.0] * n, "dc_mid": [12.0] * n,
            "bb_mid": [11.0] * n, "dc_prev_low": [5.0] * n,
            "vol_avg": [4000.0] * n, "swing_lows": swing_lows,
            "swing_highs": [None] * n,
        }
        # Bar 12: low=4 < swing=5 (sweep), close=6 > swing=5 (reclaim),
        # wick_depth=1, 1/2.0=0.5 >= 0.3 ATR, close=6 > open=10 is FALSE
        # But require_green is in params...
        params = {"swing_lookback": 40, "min_wick_atr": 0.3, "require_green": False, "vol_mult": 1.0, **_DC_EXIT_GRID}
        result = signal_liq_sweep_reclaim(None, 12, ind, params)
        assert result is not None
        assert "strength" in result
        assert "stop_price" in result
        assert "target_price" in result
        assert "time_limit" in result

    def test_fvg_fill_triggers(self):
        """FVG fill should trigger when close enters an active bullish FVG."""
        n = 10
        fvg = FVG(bar_created=3, direction="bullish", gap_high=12.0, gap_low=8.0)
        ind = {
            "closes": [10, 11, 12, 13, 14, 15, 14, 13, 10, 9],
            "highs": [11, 12, 13, 14, 15, 16, 15, 14, 11, 10],
            "lows": [9, 10, 11, 12, 13, 14, 13, 12, 9, 8],
            "atr": [2.0] * n, "rsi": [35.0] * n,
            "dc_mid": [13.0] * n, "bb_mid": [12.0] * n,
            "dc_prev_low": [8.0] * n,
            "fvg_snapshots": [[], [], [], [fvg], [fvg], [fvg], [fvg], [fvg], [fvg], [fvg]],
        }
        # Bar 8: close=10 <= gap_high=12 → fills gap, depth=(12-10)/4=0.5 >= 0.50
        params = {"max_fvg_age": 20, "fill_depth": 0.50, "rsi_max": 50, **_DC_EXIT_GRID}
        result = signal_fvg_fill(None, 8, ind, params)
        assert result is not None
        assert result["strength"] > 0

    def test_ob_touch_triggers(self):
        """OB touch should trigger when low touches bullish OB zone."""
        n = 10
        ob = OrderBlock(bar_created=2, direction="bullish", zone_high=11.0, zone_low=9.0,
                        impulse_size_atr=2.0)
        ind = {
            "closes": [10, 11, 12, 15, 18, 17, 16, 15, 10.5, 12],
            "highs": [11, 12, 13, 16, 19, 18, 17, 16, 12, 13],
            "lows": [9, 10, 11, 14, 17, 16, 15, 14, 9.5, 11],
            "atr": [2.0] * n, "rsi": [35.0] * n,
            "dc_mid": [14.0] * n, "bb_mid": [13.0] * n,
            "dc_prev_low": [9.0] * n,
            "vol_avg": [4000.0] * n, "volumes": [5000.0] * n,
            "ob_snapshots": [[], [], [ob], [ob], [ob], [ob], [ob], [ob], [ob], [ob]],
        }
        # Bar 8: low=9.5 <= zone_high=11.0, close=10.5 >= zone_low=9.0
        params = {"max_ob_age": 30, "require_close_in_zone": True, "vol_mult": 1.0, **_DC_EXIT_GRID}
        result = signal_ob_touch(None, 8, ind, params)
        assert result is not None
        assert result["strength"] > 0

    def test_sfp_triggers(self):
        """SFP should trigger when low < swing low, close > swing low, strong close."""
        n = 15
        swing_lows = [None] * n
        swing_lows[7] = 5  # Swing low confirmed at bar 7
        ind = {
            "closes": [14, 12, 10, 8, 6, 6, 8, 10, 12, 14, 14, 12, 8, 12, 14],
            "highs": [16, 14, 12, 10, 8, 7, 9, 11, 13, 15, 16, 14, 14, 14, 16],
            "lows": [13, 11, 9, 7, 5, 5, 7, 9, 11, 13, 13, 11, 3, 11, 13],
            "atr": [2.0] * n, "rsi": [30.0] * n,
            "dc_mid": [12.0] * n, "bb_mid": [11.0] * n,
            "dc_prev_low": [5.0] * n,
            "vol_avg": [4000.0] * n, "volumes": [5000.0] * n,
            "swing_lows": swing_lows,
        }
        # Bar 12: low=3 < swing=5, close=8 > swing=5,
        # close_strength = (8-3)/(14-3) = 5/11 ≈ 0.45
        params = {"swing_lookback": 40, "min_close_strength": 0.40, "vol_mult": 1.0, **_DC_EXIT_GRID}
        result = signal_sfp(None, 12, ind, params)
        assert result is not None
        assert result["strength"] > 0


# ═══════════════════════════════════════════════════════════════════
# Gates tests
# ═══════════════════════════════════════════════════════════════════

class TestMSGates:

    def test_go_verdict(self):
        """Config with PF >= 1.0 and trades >= 80 should get GO."""
        bt = {"trades": 100, "pf": 1.15, "pnl": 500.0, "dd": 30.0, "trade_list": []}
        report = evaluate_ms_gates(bt)
        assert report.verdict == "GO"
        assert report.passed_all_hard

    def test_nogo_low_pf(self):
        bt = {"trades": 100, "pf": 0.85, "pnl": -200.0, "dd": 40.0, "trade_list": []}
        report = evaluate_ms_gates(bt)
        assert report.verdict == "NO-GO"
        assert not report.passed_all_hard

    def test_nogo_low_trades(self):
        bt = {"trades": 30, "pf": 1.50, "pnl": 100.0, "dd": 10.0, "trade_list": []}
        report = evaluate_ms_gates(bt)
        assert report.verdict == "NO-GO"

    def test_no_trades(self):
        bt = {"trades": 0, "pf": 0.0, "pnl": 0.0, "dd": 0.0, "trade_list": []}
        report = evaluate_ms_gates(bt)
        assert report.verdict == "NO_TRADES"

    def test_soft_gates_present(self):
        bt = {"trades": 100, "pf": 1.15, "pnl": 500.0, "dd": 30.0, "trade_list": [],
              "dc_geometry_scores": [0.66, 1.0, 0.33]}
        report = evaluate_ms_gates(bt)
        assert len(report.soft_gates) == 5
        names = [g.name for g in report.soft_gates]
        assert "S4:DC_GEO" in names
