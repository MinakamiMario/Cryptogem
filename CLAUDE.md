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

## HF Part 2 — CLOSED (2026-02-17)

### Documentation
- `strategies/hf/CONTEXT_HANDOFF.md` -- START HIER voor Part 2 context
- `strategies/hf/DECISIONS.md` -- ADR-HF-030 t/m HF-037 (Part 2 + Bybit validation)
- `reports/hf/part2_scoreboard.md` -- Gate status leaderboard
- `reports/hf/part2_backlog.md` -- Priority queue (Cycles 1-10 compleet)
- `reports/hf/part2_teamlog.md` -- Cycle-by-cycle execution log

### Part 2 Pipeline
- `orderbook_collector.py` -- Live snapshot daemon (CCXT, exchange-parametrisch)
- `orderbook_analysis.py` -- Distributions + regime builder (exchange-agnostisch)
- `fill_model_v3.py` -- Bar-structure fill model (16 tests, pure filtering)
- `run_part2_measured_cost_rerun.py` -- 24-combo backtest runner
- `costs_mexc_v2.py` -- MEXC cost model + register_regime() met anti-double-count asserts

### MEXC Status (ADR-HF-034, 2026-02-16)
- **Signal**: H20 VWAP_DEVIATION v5/sl7 on 295 coins
- **Exchange**: MEXC SPOT (code: 0%/10bps, werkelijk: 0%/4-5bps — conservatief)
- **Execution**: MAKER LIMIT — PF=2.86-3.38, DD≤9.5%, 14/24 combos pass 7/7 STRICT
- **Status**: CONDITIONAL GO — needs paper trading validation

### Bybit Status (ADR-HF-035/036/037) — NO-GO
- 0/24 combos pass. Real VWAP (37.8M 1m candles, 166 coins) = 3 triggers in 721h
- Root cause: low intra-hour volatility dispersion (92% coins never reach dev≥2.0)
- Signal is NOT portable — calibrated on MEXC retail microstructure

### Project Status: CLOSED
- Reason: MEXC validated; Bybit portability disproven
- Frozen tag: `hf-part2-closed-v1`
- Canon ADRs: HF-034 (MEXC GO), HF-035/036/037 (Bybit NO-GO)

### Fee Decompositie
- `exchange_fee_bps` = fee-only (naar exchange)
- `total_per_side_bps` = ALL-IN (fee + half-spread + slippage + adverse_selection) → dit gaat naar harness

### Agent Rules -- Part 2 Specific
#### Do
- Read `strategies/hf/CONTEXT_HANDOFF.md` before any Part 2 work
- Use measured OB costs (not v2 Kaiko analytical model)
- Run full 24-combo matrix when testing new exchanges
- Register regimes with anti-double-count asserts
- Verify exchange fee structure per VIP level before starting

#### Don't
- Modify harness.py (READ-ONLY)
- Use v2 Kaiko cost model (superseded by measured orderbook, ADR-HF-034)
- Mix Part 2 code with original HF screening or trading_bot/
- Assume MEXC fee structure applies to other exchanges
- Assume 10s sampling scales to >100 coins — use tiered sampling policy
- Reopen Part 2 — project CLOSED (see HF_PART2_FINAL.md)
