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

## HF Screening Research

### Documentation
- `strategies/hf/DECISIONS.md` -- 29 ADRs (HF-001 through HF-029), source of truth for all HF decisions
- `strategies/hf/GATES.md` -- 4H gate canon (5 hard + 1 informational)
- `strategies/hf/GATES_SCREENING.md` -- 1H screening gates (Layer 1 + Layer 2)
- `strategies/hf/GATES_MTF.md` -- Multi-timeframe gate scaling
- `strategies/hf/UNIVERSE_POLICY.md` -- Tier definitions and inclusion criteria
- `reports/hf/` -- all experiment reports (JSON + MD pairs)

### Agent Rules -- HF Specific

#### Do
- Read `strategies/hf/DECISIONS.md` before making any HF changes (29 ADRs document all decisions)
- Treat `harness.py` as READ-ONLY (engine fee parity with `agent_team_v3.py`)
- Use signal_fn protocol: `signal_fn(candles, bar, indicators, params) -> {stop_price, target_price, time_limit, strength}`
- Inject cross-coin context into `params['__market__']`, per-coin identity into `indicators['__coin__']`
- Run `pytest strategies/hf/screening/` after screening code changes
- Keep HF research separate from `trading_bot/` (4H DualConfirm) -- different projects

#### Don't
- Re-screen hypotheses already tested (25 families, 150+ configs -- exhaustively done)
- Modify `harness.py` -- it's the source of truth for screening backtests
- Use Kraken fees for 1H strategies -- structurally unprofitable (ADR-HF-027)
- Mix HF code with `trading_bot/` code
- Forget to include BTC/USD in market context coin list

### Current Baseline
- **Signal**: H20 VWAP_DEVIATION v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5)
- **Exchange**: MEXC (0% maker, 10bps taker)
- **Result**: PF=1.25, +$143/wk (market), survives P95 stress (PF=1.07)
- **Status**: CONDITIONAL GO (ADR-HF-029) -- needs paper trading validation
