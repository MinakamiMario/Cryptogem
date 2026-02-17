"""
HF Strategy — High-Frequency hypothesis testing using shared backtest engine.

Three hypotheses tested against the same DualConfirm engine with different
parameter regimes. All use the existing run_backtest() read-only.

Hypotheses:
  H1 - LTF Mean Reversion: Tight RSI oversold bounce (rsi<30, tp8/sl6)
  H2 - Momentum Burst: High vol spike (>4x) with loose RSI (rsi<55, tp15/sl8)
  H3 - Vol Breakout: BB squeeze + volume explosion (vs5.0, tp20/sl10)
"""

import sys
from pathlib import Path

# Shared engine import (read-only)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "trading_bot"))
from agent_team_v3 import normalize_cfg  # noqa: E402

# ---------------------------------------------------------------------------
# Hypothesis configs — all tp_sl exit type, varying entry/exit params
# ---------------------------------------------------------------------------

HYPOTHESES = {
    "H1_mean_reversion": {
        "label": "LTF Mean Reversion",
        "description": (
            "Tight RSI oversold bounce. Aggressive entry (RSI<30) with "
            "small TP/SL for quick mean-reversion captures."
        ),
        "cfg": normalize_cfg({
            "exit_type": "tp_sl",
            "max_pos": 1,
            "rsi_max": 30,
            "vol_spike_mult": 2.0,
            "vol_confirm": True,
            "tp_pct": 8,
            "sl_pct": 6,
            "time_max_bars": 8,
        }),
    },
    "H2_momentum_burst": {
        "label": "Momentum Burst",
        "description": (
            "High volume spike (>4x) with relaxed RSI. Captures strong "
            "momentum follow-through after extreme volume events."
        ),
        "cfg": normalize_cfg({
            "exit_type": "tp_sl",
            "max_pos": 1,
            "rsi_max": 55,
            "vol_spike_mult": 4.0,
            "vol_confirm": True,
            "tp_pct": 15,
            "sl_pct": 8,
            "time_max_bars": 12,
        }),
    },
    "H3_vol_breakout": {
        "label": "Vol Breakout",
        "description": (
            "Extreme volume filter (5x) with wide TP target. Bets on "
            "BB-lower touches with explosive volume being regime shifts."
        ),
        "cfg": normalize_cfg({
            "exit_type": "tp_sl",
            "max_pos": 1,
            "rsi_max": 45,
            "vol_spike_mult": 5.0,
            "vol_confirm": True,
            "tp_pct": 20,
            "sl_pct": 10,
            "time_max_bars": 20,
        }),
    },
}

# Reference: GRID_BEST baseline for comparison
GRID_BEST_REF = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 10,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 2.5,
})


def list_hypotheses():
    """Return list of (name, label, description, cfg) tuples."""
    return [
        (name, h["label"], h["description"], h["cfg"])
        for name, h in HYPOTHESES.items()
    ]
