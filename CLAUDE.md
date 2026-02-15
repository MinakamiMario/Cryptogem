# Project: Cryptogem Trading Bot

## Permissions
- All bash commands related to running Python scripts, backtests, and analysis are pre-approved
- Creating, editing, and writing Python scripts in the trading_bot/ directory is pre-approved
- Running overnight optimization scripts that may take hours is pre-approved
- No manual confirmation needed for test runs, parameter sweeps, or Monte Carlo simulations

## Documentation Structure
- `docs/CONTEXT_CAPSULE.md` — schema, invariants, root causes, fixes, validation status
- `docs/PROJECT_MEMORY.md` — project knowledge, architecture, winning configs, learnings
- `docs/VALIDATION_SUMMARY.md` — all 6 robustness tests with commands + verdicts
- `docs/DECISIONS.md` — architectural decision records
- `docs/CHANGELOG_CONTEXT.md` — version changelog

## Agent Rules — Do / Don't

### Do
- Run `make check` before AND after any code change
- Run `make robustness` after changing config parameters or backtest logic
- Write all conclusions/results to repo artifacts (docs/, reports/), never only to chat
- Use `normalize_cfg()` for all config handling
- Treat `agent_team_v3.py` backtest engine as source of truth
- Commit meaningful changes with descriptive messages

### Don't
- Add toggles or OR-mode to validated strategy (DualConfirm = DC AND BB, always)
- Change GRID_BEST-critical files without running full suite (see `grid_best_files.txt`)
- Use `abs(total_pnl)` as denominator for share metrics (use positive profit attribution)
- Skip `make check` — 66 tests must stay green
- Commit data/*.json or candle_cache files (too large, use MD5 hashes in docs)

## Schema Invariants
- `time_max_bars` = canonical key, `tm_bars` = legacy alias
- `normalize_cfg()` at `run_backtest()` entry + `save/load_champion()`
- `PARAMS_BY_EXIT` = source of truth for exit-type param grids
