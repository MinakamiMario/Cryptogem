"""
ms_018 — Structure Shift + Pullback (shift_pb shallow)
========================================================
VERIFIED 4/4 — PF=2.04, DD=20.4%, 447 trades (max_pos=2)
All robustness tests passed. ADR-MS-002/003/005.

Signal: Bullish BoS (structure shift) → pullback to swing low zone
Exits: hybrid_notrl (FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET)
"""
import sys
from pathlib import Path

# Ensure repo root is importable
_repo = Path(__file__).parent.parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import importlib
from trading_bot.strategy_config import StrategyConfig


def load() -> StrategyConfig:
    """Load ms_018 strategy configuration."""
    _hyps = importlib.import_module('strategies.ms.hypotheses')
    _ind = importlib.import_module('strategies.ms.indicators')

    return StrategyConfig(
        name='ms_018_shift_pb',
        timeframe='4h',
        timeframe_minutes=240,

        signal_fn=_hyps.signal_structure_shift_pullback,
        precompute_fn=_ind.precompute_ms_indicators,

        entry_params={
            'max_bos_age': 15,
            'pullback_pct': 0.382,
            'max_pullback_bars': 6,
            'max_stop_pct': 15.0,
            'time_max_bars': 15,
            'rsi_recovery': True,
            'rsi_rec_target': 45.0,
            'rsi_rec_min_bars': 2,
        },
        exit_params={
            'max_stop_pct': 15.0,
            'time_max_bars': 15,
            'rsi_recovery': True,
            'rsi_rec_target': 45.0,
            'rsi_rec_min_bars': 2,
        },

        capital_per_trade=1400.0,    # Half Kelly (ADR-MS-005 + portfolio_architect)
        max_positions=2,             # Optimal from sensitivity analysis
        initial_equity=10_000.0,
        fee_rate=0.0010,             # MEXC 10bps taker (conservative)

        min_volume_24h=500_000.0,    # Hard liquidity gate (USDT quote volume)
        min_candles=120,             # MS structural indicator warmup

        cooldown_bars=4,
        cooldown_after_stop=8,

        baseline={
            'pf': 2.04,
            'p5_pf': 1.48,
            'dd_max': 0.204,
            'trades_per_487coins_721bars': 447,
            'backtest_fee_bps': 26,
            'live_fee_bps': 10,
        },
    )
