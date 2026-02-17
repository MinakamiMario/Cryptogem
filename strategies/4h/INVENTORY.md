# 4H DualConfirm Strategy — File Inventory
Generated: 2026-02-17

Total: 50 active Python files (29,937 LOC) + 21 deprecated files (14,207 LOC) = 71 files, 44,144 LOC

## Active Files — CORE (Strategy Logic)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `strategy.py` | CORE | ACTIVE | 651 | `Signal`, `Position`, `calc_rsi`, `calc_atr`, `calc_donchian`, `calc_bollinger`, `DonchianBounceStrategy`, `MeanReversionStrategy`, `DualConfirmStrategy` | Central signal generation. Imported by nearly every file. GRID_BEST-critical. |
| `halal_filter.py` | CORE | ACTIVE | 631 | `HalalFilter` | Coin filtering for halal compliance. Used by robustness_harness. |
| `telegram_notifier.py` | CORE | ACTIVE | 270 | `TelegramNotifier` | Notification service. Used by agent_team_v3 and bot. |

## Active Files — ENGINE (Backtest / Optimizer)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `agent_team_v3.py` | ENGINE | ACTIVE | 2557 | `normalize_cfg`, `save_champion`, `load_champion`, `precompute_all`, `check_entry_at_bar`, `Pos`, `run_backtest`, `monte_carlo_block`, `monte_carlo_coin_subsample`, `evaluate`, `Blackboard`, `triage`, `agent_auditor`, `agent_scout`, `agent_validator`, `agent_meta_learner`, `apply_promotion_gates`, `orchestrator`, `multi_run`, `main` | **Primary engine.** 4-agent system with 7-gate promotion pipeline. GRID_BEST-critical. Constants: `KRAKEN_FEE=0.0026`, `START_BAR=50`, `INITIAL_CAPITAL=2000`, `PARAMS_BY_EXIT`. |
| `overnight_optimizer.py` | ENGINE | ACTIVE | 950 | `precompute_all`, `check_entry_at_bar`, `Pos`, `run_backtest_realistic`, `monte_carlo`, `evaluate_config`, `hill_climb`, `random_neighbor`, `main` | Realistic equity backtest + Monte Carlo + sweep + hill climb. GRID_BEST-critical. |
| `quant_researcher.py` | ENGINE | REFERENCE | 1325 | `ConfigurableStrategy`, `Pos`, `run_backtest`, `calc_metrics`, `walk_forward_analysis`, `monte_carlo_simulation`, `zeus_dependency_analysis`, `statistical_significance`, `compare_configs`, `main` | Walk-Forward + Monte Carlo framework. Older engine, still usable for reference. |
| `backtest_mega_vergelijk.py` | ENGINE | REFERENCE | 759 | `precompute_all`, `check_entry_at_bar`, `Pos`, `run_backtest`, `compute_metrics`, `walk_forward`, `main` | Definitive 14-config comparison (fixed size). Produced mega_vergelijk_report.json. |
| `backtest_mega_compare.py` | ENGINE | REFERENCE | 1068 | `ConfigurableStrategy`, `Pos`, `run_backtest`, `get_all_configs`, `main` | Extended comparison engine with ADX. Large config matrix. |
| `head_to_head.py` | ENGINE | REFERENCE | 654 | `precompute_all`, `run_backtest`, `walk_forward`, `mc_block_bootstrap`, `mc_coin_subsample`, `friction_stress`, `main` | Head-to-head config comparison with WF + MC + friction. |

## Active Files — VALIDATION (Testing / Gates / Robustness)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `robustness_harness.py` | VALIDATION | ACTIVE | 952 | `purged_walk_forward`, `friction_stress`, `monte_carlo_shuffle`, `param_jitter`, `universe_shift`, `run_candidate`, `write_artifacts`, `main` | Full GO/NO-GO validation harness with 5 robustness tests. GRID_BEST-critical. Imports from `agent_team_v3`. |
| `test_param_sensitivity.py` | VALIDATION | ACTIVE | 454 | 66 regression tests via `test()` | 66 regression tests. Run via `make tests`. GRID_BEST-critical. Imports from `agent_team_v3`. |
| `test_robustness_harness.py` | VALIDATION | ACTIVE | 290 | `test_purged_wf_structure`, `test_friction_matrix_completeness`, `test_mc_shuffle_structure`, `test_jitter_structure`, `test_universe_structure`, etc. | 10 robustness harness regression tests. GRID_BEST-critical. |
| `verify_baseline.py` | VALIDATION | ACTIVE | 378 | `md5_hash`, `bt_summary`, `run_for_cache`, `generate_markdown`, `main` | Baseline verification across caches. Imports from `agent_team_v3` + `robustness_harness`. |
| `leakage_check.py` | VALIDATION | ACTIVE | 316 | `md5_file`, `load_universe`, `run_wf_pair`, `format_fold_comparison`, `main` | Walk-forward leakage detection (purged vs unpurged). |
| `nested_holdout.py` | VALIDATION | ACTIVE | 531 | `build_grid`, `inner_wf_folds`, `passes_oos_gates`, `run_nested_holdout`, `generate_markdown` | Nested walk-forward holdout validation. Imports from `agent_team_v3`. |
| `test_last60d.py` | VALIDATION | ACTIVE | 181 | `test()`, `skip()`, `run()` | Last-60-day out-of-sample test suite. |
| `test_compare_universe.py` | VALIDATION | ACTIVE | 193 | `test()`, `skip()`, `run()` | Universe comparison (ALL vs HALAL) tests. |
| `test_compare_caches.py` | VALIDATION | ACTIVE | 131 | `test()`, `skip()`, `run()` | Cache comparison regression tests. |

## Active Files — LIVE (Bot / Paper Trading)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `bot.py` | LIVE | ACTIVE | 836 | `SafetyGuard`, `TradingBot`, `setup_logging`, `load_state`, `save_state`, `log_trade`, `send_notification`, `main` | Live Kraken trading bot. GRID_BEST-critical. Imports from `kraken_client`, `strategy`. |
| `paper_backfill_v4.py` | LIVE | ACTIVE | 1050 | `setup_logging`, `load_state`, `save_state`, `create_excel`, `make_v4_strategy`, `run_backfill`, `run_live`, `main` | Paper trader v4 with historical backfill + live loop. GRID_BEST-critical. Supports Kraken + Solana DEX. |
| `paper_trade.py` | LIVE | REFERENCE | 934 | `PaperTrader`, `setup_logging`, `load_state`, `save_state`, `create_excel`, `show_report`, `show_comparison`, `main` | Older paper trader (v3). Still functional but v4 preferred. |
| `kraken_client.py` | LIVE | ACTIVE | 757 | `KrakenClient` | Kraken API client (REST + WebSocket). Used by bot, paper traders. |
| `exchange_manager.py` | LIVE | ACTIVE | 469 | `ExchangeClient` (ABC), `KrakenExchangeClient`, `MEXCExchangeClient`, `ExchangeManager` | Multi-exchange abstraction layer (Kraken + MEXC). |
| `dex_manager.py` | LIVE | ACTIVE | 1095 | `GeckoTerminalClient`, `DexScreenerClient`, `RugCheckClient`, `DexManager` | Solana DEX integration (GeckoTerminal, DexScreener, RugCheck). |
| `coin_scanner.py` | LIVE | ACTIVE | 627 | `CoinScanner` | Coin discovery and scanning across exchanges. |
| `sell_positions.py` | LIVE | ACTIVE | 54 | (script) | Emergency position liquidation script. Uses `KrakenClient`. |

## Active Files — ANALYSIS (Research / One-off Scripts)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `drawdown_analysis.py` | ANALYSIS | REFERENCE | 559 | `analyze_equity_curve`, `monte_carlo_analysis`, `consecutive_loss_analysis`, `your_scenario_analysis`, `risk_perspective`, `main` | Comprehensive drawdown and risk analysis. Standalone. |
| `coin_attribution_analysis.py` | ANALYSIS | REFERENCE | 295 | `coin_stats`, `metrics`, `bt_subset`, `main` | Coin-level attribution (which coins contribute most). Imports `agent_team_v3`. |
| `backtest_portfolio_optimization.py` | ANALYSIS | HISTORICAL | 1222 | `load_cache`, `calc_coin_metrics`, `filter_coins`, `extract_all_signals`, `build_btc_regime`, `simulate_portfolio`, `test_*` (7 variants), `main` | Portfolio optimization experiments (position sizing, ranking, regime). |
| `backtest_entry_optimization.py` | ANALYSIS | HISTORICAL | 955 | `FlexibleEntryStrategy`, `extract_signals`, `simulate_portfolio`, `run_variant`, `main` | Entry filter experiments (EMA, ADX, momentum). |
| `backtest_exit_optimization.py` | ANALYSIS | HISTORICAL | 853 | `load_cache`, `precompute_indicators`, `find_entries`, `simulate_exits`, `calc_metrics`, `main` | Exit strategy experiments (trail, TP/SL, time-based). |
| `backtest_extra_filters.py` | ANALYSIS | HISTORICAL | 881 | `V3BaselineStrategy`, `run_portfolio_backtest`, `main` | Extra filter experiments (vol spike, momentum). |
| `backtest_stoploss.py` | ANALYSIS | HISTORICAL | 654 | `StoplossVariantStrategy`, `extract_signals_with_bar_tracking`, `analyze_exit_types`, `main` | Stop-loss variant experiments. |
| `backtest_improved.py` | ANALYSIS | HISTORICAL | 716 | `ImprovedDualConfirmStrategy`, `extract_all_signals`, `simulate_portfolio`, `main` | Improved backtest with multi-config comparison. |
| `backtest_timeframe_test.py` | ANALYSIS | HISTORICAL | 401 | `DualConfirmV2`, `TestPosition`, `run_backtest`, `main` | Multi-timeframe experiments (1H, 2H, 4H). |
| `backtest_all.py` | ANALYSIS | HISTORICAL | 357 | `calc_rsi`, `calc_atr`, `calc_donchian`, `backtest_coin`, `main` (implicit) | Simple single-coin backtest. Early prototype. |
| `backtest_compare.py` | ANALYSIS | HISTORICAL | 473 | `calc_rsi`, `calc_atr`, `calc_donchian`, `extract_all_signals`, `simulate_portfolio` | Strategy comparison (Donchian vs MeanReversion). |
| `backtest_universal.py` | ANALYSIS | HISTORICAL | 555 | `calc_rsi`, `calc_atr`, `calc_donchian`, `calc_bollinger`, `backtest_coin` | Universal backtest across all coins. |
| `backtest_universal_portfolio.py` | ANALYSIS | HISTORICAL | 464 | `calc_rsi`, `calc_atr`, `calc_donchian`, `calc_bollinger`, `extract_all_signals`, `simulate_portfolio` | Portfolio-level universal backtest. |
| `optimize_universal.py` | ANALYSIS | HISTORICAL | 604 | `calc_rsi`, `calc_atr`, `calc_donchian`, `calc_bollinger`, `calc_ema`, `extract_signals`, `simulate_portfolio` | Universal parameter optimizer with grid search. |
| `data_quality_audit.py` | ANALYSIS | REFERENCE | 203 | `venue_stats` | Data quality check across venues. |
| `debug_equity.py` | ANALYSIS | REFERENCE | 333 | `main` | Debug script for equity curve tracking. Traces trade-by-trade equity. |
| `debug_identical_scores.py` | ANALYSIS | REFERENCE | 173 | (script) | Debug why configs produce identical scores. Imports `agent_team_v3`. |
| `metrics_before_after.py` | ANALYSIS | REFERENCE | 234 | `generate_2param_configs`, `run_scenario`, `main` | Before/after metrics comparison for parameter changes. Imports `agent_team_v3`. |
| `search_space_metrics.py` | ANALYSIS | REFERENCE | 373 | (script) | Search space size and coverage analysis. |
| `agent3_tradeable.py` | ANALYSIS | ACTIVE | 113 | `build`, `harness`, `xm`, `save` | Builds tradeable config from agent_team_v3 output + robustness harness. |

## Active Files — ROBUSTNESS SUITE (Extended Tests)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `slippage_regimes.py` | VALIDATION | ACTIVE | 260 | `build_regimes`, `find_breakeven_bps`, `run_all`, `generate_markdown` | Slippage regime analysis. Imports `agent_team_v3`. |
| `rolling_regime_sweep.py` | VALIDATION | ACTIVE | 347 | `build_rolling_windows`, `run_window_regimes`, `calc_stability`, `generate_markdown`, `main` | Rolling window regime stability. Imports `agent_team_v3`. |
| `window_sweep.py` | VALIDATION | ACTIVE | 337 | `build_windows`, `run_window`, `calc_stability`, `generate_markdown`, `main` | Time-window stability sweep. Imports `agent_team_v3`. |
| `long_horizon_max.py` | VALIDATION | ACTIVE | 462 | `slippage_ladder`, `friction_2x_20`, `jitter_test`, `mc_ruin`, `top_shares`, `decide`, `generate_markdown`, `main` | Long-horizon maximum drawdown analysis. Imports `agent_team_v3` + `robustness_harness`. |

## Deprecated Files (trading_bot/deprecated/)

| File | Category | Status | LOC | Key Exports | Notes |
|------|----------|--------|-----|-------------|-------|
| `agent_team_v2.py` | ENGINE | DEPRECATED | 1423 | `Blackboard`, `agent_auditor`, `agent_combiner`, `agent_exit_architect`, `agent_validator`, `agent_meta_learner` | Previous agent version (5 agents). Superseded by v3. |
| `agent_team.py` | ENGINE | DEPRECATED | 1241 | `Scoreboard`, `agent_grid_search`, `agent_wide_explorer`, `agent_fine_tuner`, `agent_walk_forward` | First agent version (v1). Superseded by v2/v3. |
| `agent_search.py` | ENGINE | DEPRECATED | 554 | `agent_grid_search`, `agent_wide_explorer`, `agent_fine_tuner`, `agent_walk_forward`, `main` | Multi-agent search framework (4 strategies). Never fully run. |
| `backtest_v6_robust.py` | ANALYSIS | DEPRECATED | 1089 | `V6RobustStrategy`, `run_backtest`, `analyze_robustness`, `walk_forward_quick`, `main` | V6 price structure strategy experiments. |
| `backtest_v8_sweep.py` | ANALYSIS | DEPRECATED | 766 | `V8Strategy`, `Pos`, `run_backtest`, `walk_forward`, `generate_configs`, `main` | V8 sweep framework. |
| `backtest_v9_tpsl_sweep.py` | ANALYSIS | DEPRECATED | 614 | `precompute_indicators`, `Pos`, `run_backtest`, `main` | V9 TP/SL 64-combo sweep. |
| `backtest_v5_experiments.py` | ANALYSIS | DEPRECATED | 802 | `V5ExperimentStrategy`, `run_portfolio_backtest`, `main` | V5 74-config experiment suite. |
| `backtest_v5_deep_dive.py` | ANALYSIS | DEPRECATED | 569 | `V5Strategy`, `run_backtest`, `main` | V5 RSI Recovery + ADX deep analysis. |
| `backtest_v5_precision.py` | ANALYSIS | DEPRECATED | 408 | `V5Strategy`, `run_bt`, `main` | V5 fine-tuning sweep. |
| `backtest_v5_final_sweep.py` | ANALYSIS | DEPRECATED | 430 | `V5FinalStrategy`, `run_bt`, `main` | V5 final parameter sweep. |
| `backtest_v5_portfolio_compare.py` | ANALYSIS | DEPRECATED | 656 | `V4V5Strategy`, `run_portfolio_backtest`, `main` | V4 vs V5 portfolio comparison. |
| `backtest_v5_capital_sim.py` | ANALYSIS | DEPRECATED | 365 | `V5Strategy`, `run_sim`, `main` | V5 capital simulation. |
| `backtest_v6_price_structure.py` | ANALYSIS | DEPRECATED | 641 | `V6Strategy`, `run_backtest`, `main` | V6 price structure experiments. |
| `backtest_combined_winner.py` | ANALYSIS | DEPRECATED | 746 | `CombinedWinnerStrategy`, `run_portfolio_backtest`, `vol_filter_p50`, `main` | Combined winner comparison. Legacy main backtest engine. |
| `backtest_532_coins.py` | ANALYSIS | DEPRECATED | 634 | `V4Strategy`, `run_backtest`, `main` | 532-coin dataset backtest. Precursor to mega comparison. |
| `analyze_timemax_v9.py` | ANALYSIS | DEPRECATED | 519 | `find_entries`, `simulate_trade`, `simulate_no_timemax`, `main` | V9 TimeMax sweep analysis. |
| `analyze_timemax_trades.py` | ANALYSIS | DEPRECATED | 802 | `V9BStrategy`, `run_analysis` | TimeMax exit detail analysis. |
| `deep_trade_analysis.py` | ANALYSIS | DEPRECATED | 594 | `run_detailed_backtest`, `analyze_trades`, `propose_filters` | Per-trade deep dive analysis. |
| `filter_backtest.py` | ANALYSIS | DEPRECATED | 613 | `run_filtered_backtest`, 15+ `filter_*` functions | Entry/exit filter experiments. |
| `v4_sweep.py` | ANALYSIS | DEPRECATED | 407 | `run_test`, `TrailingTPStrategy`, `run_trailing_tp_test`, `main` | V4 parameter sweep + trailing TP. |
| `v4_sweep2.py` | ANALYSIS | DEPRECATED | 334 | `run_test`, `fmt`, `hdr` | V4 parameter sweep continuation. |

## Data Files (trading_bot/)

### Candle Caches
| File | Description |
|------|-------------|
| `candle_cache_532.json` | Primary dataset: 526 coins, ~660-721 bars, 4H candles (CURRENT) |
| `candle_cache_60d.json` | Older 285-coin dataset, 60 days |
| `candle_cache_30d.json` | 30-day candle cache |
| `candle_cache.json` | Original candle cache |
| `candle_cache_240m_60d.json` | 4H (240min) 60-day cache |
| `candle_cache_240m_30d_fresh.json` | Fresh 4H 30-day cache |
| `candle_cache_120m_30d.json` | 2H timeframe experiment cache |
| `candle_cache_60m_14d.json` | 1H timeframe experiment cache |

### Agent / Engine Results
| File | Description |
|------|-------------|
| `champion.json` | Persisted champion config (GRID_BEST-critical) |
| `agent_team_v3_results.json` | V3 agent run results |
| `agent_team_v3_blackboard.json` | V3 blackboard state |
| `agent_team_v2_results.json` | V2 agent results (legacy) |
| `agent_team_v2_blackboard.json` | V2 blackboard state (legacy) |
| `agent_team_results.json` | V1 agent results (legacy) |
| `agent_team_scoreboard.json` | V1 scoreboard (legacy) |
| `overnight_results.json` | Overnight optimizer results |

### Backtest Reports
| File | Description |
|------|-------------|
| `mega_vergelijk_report.json` | Definitive 14-config comparison |
| `robustness_report.json` | Robustness harness output |
| `quant_report_v5_prod.json` | Quant researcher V5 production report |
| `backtest_results.json` | Generic backtest results |
| `backtest_universal_results.json` | Universal backtest results |
| `backtest_universal_portfolio.json` | Universal portfolio results |
| `compare_results.json` | Strategy comparison results |
| `v6_report.json` | V6 experiment report |
| `v8_sweep_report.json` | V8 sweep report |
| `wf_results_30d.json` | Walk-forward 30-day results |

### Paper Trading State
| File | Description |
|------|-------------|
| `paper_state_v4_live.json` | V4 paper trader state (live) |
| `paper_trades_v4_live.xlsx` | V4 paper trades Excel log |
| `paper_state.json` | Original paper state |
| `paper_trades.xlsx` | Original paper trades |
| `paper_state_2x1000.json` | 2x$1000 variant state |
| `paper_trades_2x1000.xlsx` | 2x$1000 variant trades |
| `paper_state_3x700.json` | 3x$700 variant state |
| `paper_trades_3x700.xlsx` | 3x$700 variant trades |

### Bot State
| File | Description |
|------|-------------|
| `bot_state.json` | Live bot persistent state |
| `halal_review_queue.json` | Coins pending halal review |

### Markdown Reports
| File | Description |
|------|-------------|
| `V5_RAPPORT.md` | V5 findings report |
| `SESSION_SUMMARY.md` | Session summary notes |
| `portfolio_analysis.md` | Portfolio analysis writeup |

### PineScript
| File | Description |
|------|-------------|
| `DualConfirm_GRID_BEST.pine` | GRID_BEST PineScript indicator (GRID_BEST-critical) |
| `pinescript_dual_confirm_v5.pine` | V5 PineScript |
| `pinescript_dual_confirm_v4.pine` | V4 PineScript |
| `pinescript_dual_confirm_optimized.pine` | Optimized PineScript |

### Logs
| File | Description |
|------|-------------|
| `logs/bot_20260212.log` | Bot execution log |
| `logs/paper_v4_live_20260213_0030.log` | V4 paper trader log |
| `overnight_run.log` | Overnight optimizer log |
| Various `paper_trade_*.log` | Paper trading logs |
| `5run_output*.log` | Multi-run output logs |

### Other
| File | Description |
|------|-------------|
| `.env.example` | Environment variable template |
| `cache/gecko_pool_cache.json` | Gecko DEX pool cache |
| `trades/trades_202602.json` | Live trade records |

## Makefile Targets

| Target | Description | Key Script |
|--------|-------------|------------|
| `check` | Full validation (schema + tests + context + data-verify) | `scripts/check_cfg_schema.py` + `test_param_sensitivity.py` |
| `schema` | Schema guardrail (no legacy `tm_bars`) | `scripts/check_cfg_schema.py` |
| `tests` | 66 regression tests | `test_param_sensitivity.py` |
| `context` | Context drift sentinel | `scripts/check_cfg_schema.py --check-context` |
| `capsule` | Print context capsule info | `docs/CONTEXT_CAPSULE.md` |
| `robustness` | Full GO/NO-GO validation (all candidates) | `robustness_harness.py` |
| `robustness-tests` | 10 robustness regression tests | `test_robustness_harness.py` |
| `last60d` | Last 60 days out-of-sample evaluation | `robustness_harness.py` + `scripts/slice_candles.py` |
| `last60d-all` | Last 60 days (all candidates) | same |
| `last60d-tests` | Last 60 days regression tests | `test_last60d.py` |
| `compare-universe` | ALL vs HALAL on unfiltered cache | `scripts/compare_universe.py` |
| `compare-universe-all` | ALL vs HALAL (all candidates) | same |
| `compare-universe-tests` | Universe comparison tests | `test_compare_universe.py` |
| `build-unfiltered-cache` | Build unfiltered cache (886 coins) | `scripts/build_unfiltered_cache.py` |
| `build-research-cache` | Build research cache (resumable) | `scripts/build_research_cache.py` |
| `compare-caches` | Compare RESEARCH_ALL vs LIVE_CURRENT | `scripts/compare_universe.py` |
| `compare-caches-smoke` | Compare caches (200 coin sample) | same |
| `compare-caches-tests` | Cache comparison tests | `test_compare_caches.py` |
| `data-verify` | Dataset registry verification | `~/CryptogemData/dataset_verify.py` |
| `grid_best-check` | GRID_BEST full suite (check + robustness) | composite |
| `grid_best-robustness` | GRID_BEST robustness only | `robustness_harness.py` |
| `ci-guard` | Detect GRID_BEST-critical file changes | `scripts/ci_guard.sh` |
| `hf-check` | HF alignment tests (separate project) | `strategies/hf/hf_alignment_tests.py` |
| `hf-robustness` | HF robustness (placeholder) | N/A |

## GRID_BEST-Critical Files

These files require `make check && make robustness` after any change (per `grid_best_files.txt`):

1. `trading_bot/agent_team_v3.py`
2. `trading_bot/strategy.py`
3. `trading_bot/robustness_harness.py`
4. `trading_bot/bot.py`
5. `trading_bot/paper_backfill_v4.py`
6. `trading_bot/overnight_optimizer.py`
7. `trading_bot/champion.json`
8. `trading_bot/DualConfirm_GRID_BEST.pine`
9. `trading_bot/test_param_sensitivity.py`
10. `trading_bot/test_robustness_harness.py`

## Dependency Graph (simplified)

```
strategy.py (CORE — Signal, Position, calc_rsi/atr/donchian/bollinger)
  |
  +-- agent_team_v3.py (ENGINE — imports calc_rsi/atr/donchian/bollinger, TelegramNotifier)
  |     |
  |     +-- robustness_harness.py (imports precompute_all, run_backtest, normalize_cfg, etc.)
  |     |     +-- verify_baseline.py (imports from agent_team_v3 + robustness_harness)
  |     |     +-- long_horizon_max.py (imports from agent_team_v3 + robustness_harness)
  |     |     +-- test_robustness_harness.py (imports from agent_team_v3 + robustness_harness)
  |     |     +-- agent3_tradeable.py (imports from agent_team_v3 + robustness_harness)
  |     |
  |     +-- test_param_sensitivity.py (66 regression tests)
  |     +-- slippage_regimes.py
  |     +-- rolling_regime_sweep.py
  |     +-- window_sweep.py
  |     +-- nested_holdout.py
  |     +-- leakage_check.py (+ robustness_harness)
  |     +-- metrics_before_after.py
  |     +-- coin_attribution_analysis.py
  |     +-- debug_identical_scores.py
  |
  +-- overnight_optimizer.py (imports calc_rsi/atr/donchian/bollinger)
  |
  +-- quant_researcher.py (imports calc_rsi/atr/donchian/bollinger)
  |
  +-- bot.py (imports DonchianBounceStrategy, MeanReversionStrategy, DualConfirmStrategy)
  |     +-- kraken_client.py (KrakenClient)
  |
  +-- paper_backfill_v4.py (imports DualConfirmStrategy, Position, Signal)
  |     +-- kraken_client.py
  |
  +-- paper_trade.py (imports all strategy classes)
  |     +-- kraken_client.py
  |
  +-- backtest_mega_vergelijk.py (imports calc_rsi/atr/donchian/bollinger)
  +-- backtest_mega_compare.py (imports calc_rsi/atr/donchian/bollinger)
  +-- head_to_head.py (imports calc_rsi/donchian/bollinger/atr)
  +-- backtest_improved.py (imports DualConfirmStrategy, Position, Signal)
  +-- backtest_entry_optimization.py (imports Position, Signal, calc_*)
  +-- backtest_exit_optimization.py (imports calc_*)
  +-- backtest_portfolio_optimization.py (imports DualConfirmStrategy, Position, Signal, calc_*)
  +-- backtest_stoploss.py (imports DualConfirmStrategy, Position, Signal, calc_*)
  +-- backtest_extra_filters.py (imports Signal, calc_*)
  +-- backtest_timeframe_test.py (imports calc_*)
  +-- backtest_all.py (standalone calc_* implementations)
  +-- backtest_compare.py (standalone calc_* implementations)
  +-- backtest_universal.py (standalone calc_* implementations)
  +-- backtest_universal_portfolio.py (standalone calc_* implementations)
  +-- optimize_universal.py (standalone calc_* implementations)

kraken_client.py (LIVE — KrakenClient)
  +-- bot.py
  +-- paper_backfill_v4.py
  +-- paper_trade.py
  +-- sell_positions.py

exchange_manager.py (LIVE — ExchangeClient ABC, Kraken + MEXC)
  (standalone, used by newer multi-exchange code)

dex_manager.py (LIVE — GeckoTerminal, DexScreener, RugCheck)
  (standalone, used by paper_backfill_v4 for Solana DEX)

coin_scanner.py (LIVE — CoinScanner)
halal_filter.py (CORE — HalalFilter, used by robustness_harness)
telegram_notifier.py (CORE — TelegramNotifier, used by agent_team_v3)
```

## File Count Summary

| Category | Active | Reference | Historical | Deprecated | Total |
|----------|--------|-----------|------------|------------|-------|
| CORE | 3 | - | - | - | 3 |
| ENGINE | 1 | 3 | - | 3 | 7 |
| VALIDATION | 8 | - | - | - | 8 |
| LIVE | 7 | 1 | - | - | 8 |
| ANALYSIS | 1 | 5 | 14 | 18 | 38 |
| **Total** | **20** | **9** | **14** | **21** | **64** |

Note: Some files with dual roles (e.g., analysis + validation) are counted once by primary category.
Additional non-categorized Python files (drawdown_analysis, data_quality_audit, search_space_metrics) are included in ANALYSIS.
