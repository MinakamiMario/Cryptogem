"""
4H DualConfirm Strategy Module
-------------------------------
Wrapper around trading_bot/ engine for the 4-hour DualConfirm bounce strategy.

Key components:
  configs.py  -- Named config presets (BASELINE, BEST_KNOWN, HYBRID_NOTRL)
  runner.py   -- CLI entrypoint for single-config backtests
  __main__.py -- Module runner (python -m strategies.4h)

Engine: trading_bot/agent_team_v3.py (run_backtest, precompute_all, normalize_cfg)
Strategy: trading_bot/strategy.py (calc_rsi, calc_atr, calc_donchian, calc_bollinger)
"""
