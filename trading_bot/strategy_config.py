"""
Strategy Config — Pluggable Strategy Framework
================================================
Lightweight dataclass that encapsulates everything strategy-specific.
The live trader is 100% generic — all strategy logic comes from config.

Usage:
    from trading_bot.strategy_config import load_strategy
    config = load_strategy('ms_018')
    # config.signal_fn, config.precompute_fn, config.entry_params, ...
"""
import importlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, Optional


@dataclass
class StrategyConfig:
    """Everything the live trader needs to know about a strategy."""

    # Identity
    name: str                              # "ms_018_shift_pb"
    timeframe: str                         # "4h"
    timeframe_minutes: int = 240           # interval in minutes

    # Signal functions
    signal_fn: Callable = None             # (candles, bar, indicators, params) → dict | None
    precompute_fn: Callable = None         # (data_dict, coins) → indicators_dict

    # Parameters
    entry_params: Dict[str, Any] = field(default_factory=dict)
    exit_params: Dict[str, Any] = field(default_factory=dict)

    # Sizing & risk
    capital_per_trade: float = 1400.0      # Half Kelly default
    max_positions: int = 2
    initial_equity: float = 10_000.0
    fee_rate: float = 0.0010               # 10bps per side

    # Liquidity gate
    min_volume_24h: float = 500_000.0      # USD quote volume

    # Warmup
    min_candles: int = 120                 # minimum bars for indicator warmup

    # Cooldown
    cooldown_bars: int = 4
    cooldown_after_stop: int = 8

    # Backtest baseline (drift detection)
    baseline: Dict[str, Any] = field(default_factory=dict)


# ─── Registry ──────────────────────────────────────────────────

_STRATEGY_MODULES = {
    'ms_018': 'trading_bot.strategies.ms_018',
    'ms_005': 'trading_bot.strategies.ms_005',
    'vol_cap_041': 'trading_bot.strategies.vol_cap_041',
}


def load_strategy(name: str) -> StrategyConfig:
    """Load a strategy config by name.

    Args:
        name: strategy identifier (e.g. 'ms_018')

    Returns:
        StrategyConfig instance

    Raises:
        ValueError if strategy not found
    """
    module_path = _STRATEGY_MODULES.get(name)
    if not module_path:
        available = ', '.join(sorted(_STRATEGY_MODULES.keys()))
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")

    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        raise ValueError(f"Cannot import strategy '{name}' from {module_path}: {e}")

    if not hasattr(mod, 'load'):
        raise ValueError(f"Strategy module {module_path} must define a load() function")

    config = mod.load()
    if not isinstance(config, StrategyConfig):
        raise ValueError(f"Strategy '{name}' load() must return StrategyConfig")

    return config


def list_strategies() -> list:
    """List all registered strategy names."""
    return sorted(_STRATEGY_MODULES.keys())
