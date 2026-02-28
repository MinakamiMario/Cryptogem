"""Backtest runner — wraps agent_team_v3 for lab agents (READ-ONLY).

Provides safe access to the backtest engine without modifying any
trading_bot files. Loads data once, caches indicators.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

from lab.config import REPO_ROOT, TRADING_BOT_DIR

logger = logging.getLogger('lab.tools.backtest')

# ── Lazy imports from trading_bot ────────────────────────
_engine = None


def _load_engine():
    """Lazily import agent_team_v3 functions."""
    global _engine
    if _engine is not None:
        return _engine

    sys.path.insert(0, str(TRADING_BOT_DIR))
    try:
        from agent_team_v3 import (
            BASELINE_CFG,
            GRID_BEST,
            INITIAL_CAPITAL,
            KRAKEN_FEE,
            PARAMS_BY_EXIT,
            cfg_hash,
            monte_carlo_block,
            normalize_cfg,
            precompute_all,
            run_backtest,
        )
        _engine = {
            'precompute_all': precompute_all,
            'run_backtest': run_backtest,
            'monte_carlo_block': monte_carlo_block,
            'cfg_hash': cfg_hash,
            'normalize_cfg': normalize_cfg,
            'PARAMS_BY_EXIT': PARAMS_BY_EXIT,
            'BASELINE_CFG': BASELINE_CFG,
            'GRID_BEST': GRID_BEST,
            'INITIAL_CAPITAL': INITIAL_CAPITAL,
            'KRAKEN_FEE': KRAKEN_FEE,
        }
    except ImportError as e:
        logger.error(f"Cannot import agent_team_v3: {e}")
        raise
    return _engine


# ── Data cache ───────────────────────────────────────────
_data_cache: dict = {}
_indicators_cache: dict = {}

CACHE_FILE = TRADING_BOT_DIR / 'candle_cache_532.json'


def load_data(cache_file: Optional[Path] = None) -> tuple[dict, list[str]]:
    """Load candle data + coin list. Cached after first call."""
    path = cache_file or CACHE_FILE
    key = str(path)

    if key not in _data_cache:
        logger.info(f"Loading candle data from {path}...")
        with open(path) as f:
            data = json.load(f)
        coins = sorted([k for k in data if not k.startswith('_')])
        _data_cache[key] = (data, coins)
        logger.info(f"Loaded {len(coins)} coins")

    return _data_cache[key]


def get_indicators(cache_file: Optional[Path] = None,
                   end_bar: Optional[int] = None) -> tuple[dict, list[str]]:
    """Precompute indicators. Cached per (cache_file, end_bar)."""
    data, coins = load_data(cache_file)
    key = (str(cache_file or CACHE_FILE), end_bar)

    if key not in _indicators_cache:
        engine = _load_engine()
        logger.info(f"Precomputing indicators (end_bar={end_bar})...")
        indicators = engine['precompute_all'](data, coins, end_bar=end_bar)
        _indicators_cache[key] = (indicators, coins)

    return _indicators_cache[key]


# ── Public API ───────────────────────────────────────────

def backtest(cfg: dict, cache_file: Optional[Path] = None,
             end_bar: Optional[int] = None,
             early_stop_dd: Optional[float] = None) -> Optional[dict]:
    """Run a single backtest. Returns result dict or None on gate fail."""
    engine = _load_engine()
    indicators, coins = get_indicators(cache_file, end_bar)
    cfg = engine['normalize_cfg'](dict(cfg))
    return engine['run_backtest'](
        indicators, coins, cfg,
        end_bar=end_bar,
        early_stop_dd=early_stop_dd,
    )


def monte_carlo(trade_pnl_pcts: list[float],
                n_sims: int = 3000,
                block_size: int = 5,
                seed: int = 42) -> dict:
    """Run Monte Carlo block bootstrap."""
    engine = _load_engine()
    return engine['monte_carlo_block'](
        trade_pnl_pcts, n_sims=n_sims,
        block_size=block_size, seed=seed,
    )


def cfg_hash(cfg: dict) -> str:
    """Get deterministic config hash."""
    engine = _load_engine()
    return engine['cfg_hash'](cfg)


def normalize_cfg(cfg: dict) -> dict:
    """Normalize config (tm_bars → time_max_bars)."""
    engine = _load_engine()
    return engine['normalize_cfg'](dict(cfg))


def get_params_by_exit() -> dict:
    """Get PARAMS_BY_EXIT mapping."""
    return _load_engine()['PARAMS_BY_EXIT']


def get_baseline_cfg() -> dict:
    """Get BASELINE_CFG."""
    return dict(_load_engine()['BASELINE_CFG'])


def get_grid_best() -> dict:
    """Get GRID_BEST config."""
    return dict(_load_engine()['GRID_BEST'])


def get_champion() -> Optional[dict]:
    """Load champion.json if exists."""
    champion_file = TRADING_BOT_DIR / 'champion.json'
    if not champion_file.exists():
        return None
    with open(champion_file) as f:
        return json.load(f)


def get_initial_capital() -> float:
    """Get INITIAL_CAPITAL constant."""
    return _load_engine()['INITIAL_CAPITAL']


def get_fee() -> float:
    """Get KRAKEN_FEE constant."""
    return _load_engine()['KRAKEN_FEE']
