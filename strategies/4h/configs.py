"""
Named config presets for the 4H DualConfirm strategy.

All configs are normalized through normalize_cfg() before use.
Source of truth: trading_bot/agent_team_v3.py BASELINE_CFG / BEST_KNOWN.

Usage:
    from strategies.4h.configs import get_config, list_configs
    cfg = get_config('BASELINE')
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure trading_bot is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / 'trading_bot') not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / 'trading_bot'))

from agent_team_v3 import normalize_cfg


# ---------------------------------------------------------------------------
# Named configs
# ---------------------------------------------------------------------------

# V5+VolSpk3 production winner (CLAUDE.md baseline)
BASELINE = {
    'exit_type': 'trail',
    'rsi_max': 40,
    'atr_mult': 2.0,
    'vol_spike_mult': 3.0,
    'vol_confirm': True,
    'breakeven': True,
    'be_trigger': 3.0,
    'time_max_bars': 10,
    'rsi_recovery': True,
    'rsi_rec_target': 45,
    'max_stop_pct': 15.0,
    'max_pos': 1,
}

# Agent Team V3 optimized (rsi_max=42, be_trigger=2.0, time_max_bars=6, max_stop_pct=12)
BEST_KNOWN = {
    'exit_type': 'trail',
    'rsi_max': 42,
    'atr_mult': 2.0,
    'vol_spike_mult': 3.0,
    'vol_confirm': True,
    'breakeven': True,
    'be_trigger': 2.0,
    'time_max_bars': 6,
    'rsi_recovery': True,
    'rsi_rec_target': 45,
    'max_stop_pct': 12.0,
    'max_pos': 1,
}

# Hybrid no-trail: won V3 7-gate pipeline (96% A-share, 3/3 WF)
# No ATR trail stop — uses DC/BB targets + RSI Recovery + time max only
HYBRID_NOTRL = {
    'exit_type': 'hybrid_notrl',
    'rsi_max': 42,
    'vol_spike_mult': 3.0,
    'vol_confirm': True,
    'breakeven': False,
    'rsi_recovery': True,
    'rsi_rec_target': 45,
    'time_max_bars': 20,
    'max_stop_pct': 15.0,
    'max_pos': 2,
}


# ---------------------------------------------------------------------------
# Config registry
# ---------------------------------------------------------------------------

CONFIGS = {
    'BASELINE': BASELINE,
    'BEST_KNOWN': BEST_KNOWN,
    'HYBRID_NOTRL': HYBRID_NOTRL,
}


def get_config(name: str) -> dict:
    """Return a normalized copy of a named config.

    Raises KeyError if name is not in CONFIGS.
    """
    if name.upper() not in CONFIGS:
        available = ', '.join(sorted(CONFIGS.keys()))
        raise KeyError(f"Unknown config '{name}'. Available: {available}")
    return normalize_cfg(dict(CONFIGS[name.upper()]))


def list_configs() -> list[str]:
    """Return sorted list of available config names."""
    return sorted(CONFIGS.keys())
