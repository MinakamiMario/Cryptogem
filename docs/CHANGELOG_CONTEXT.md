# Changelog (Context-Relevant)

## v3.1.1 — Parameter Sensitivity Fix (2026-02-14)

### Fixed
- `tm_bars` vs `time_max_bars` naming conflict: tp_sl exit now reads canonical key
- Scout grid no longer sweeps trail-only params for tp_sl configs
- `save_champion()` normalizes cfg before writing to disk
- `overnight_optimizer.py` backward-compatible with canonical keys

### Added
- `normalize_cfg()` — auto-migrates legacy `tm_bars` → `time_max_bars`
- `PARAMS_BY_EXIT` — source of truth for exit-type param registry
- `used_keys_for()` / `warn_unused_params()` — guardrail functions
- 32 new regression tests (66 total, all passing)

### Metrics
- Unique ratio: 37.5% → 75.0% (2.0x improvement)
- No-op waste: 62.5% → 25.0% (-38 pp)

### Known Issues
- `round(score, 1)` hides 0.013 score differences → recommend `round(score, 3)`
- `head_to_head.py` and `backtest_mega_vergelijk.py` tp_sl branch still use legacy `tm_bars`

## HF Research -- Sprint 1 (2026-02-15)
### Added
- HF validation framework (hf_validate.py, hf_data_audit.py, hf_tail_risk.py)
- Red team attack checklist (hf_attack_checklist.md)
- 3 hypothesis families identified (hf_hypotheses.md)
- Gate canon: 5 hard + 1 informational (GATES.md)
### Result: GO for 4H DualConfirm. Data quality acceptable.

## HF Research -- Sprint 1.5 (2026-02-15)
### Added
- Volume ablation (MODERATE -- 58-65% edge on clean symbols)
- Latency stress MC (ROBUST -- 100% survival)
- Universe tiering (CRITICAL -- edge depends on Tier 2 mid-caps)
### Result: Tier 1 has ~0% alpha. Tier 2 is the edge.

## HF Research -- Sprint 2 (2026-02-15)
### Added
- Per-tier friction model v2 (T1=31bps, T2=56bps per side)
- Universe policy (UNIVERSE_POLICY.md -- T1+T2=316 coins, T3 excluded)
- Per-tier gate validation
### Result: MARGINAL -- 33-38% P&L retained under realistic friction.

## HF Research -- Sprint 2.5 (2026-02-15)
### Added
- Allocator experiment (max_pos>1 does NOT improve risk-adjusted returns)
### Result: Throughput path via allocator blocked. Need sub-4H pipeline.

## HF Research -- Sprint 3 (2026-02-15)
### Added
- 1H data pipeline (build_hf_cache.py -- paginated Kraken+MEXC fetcher)
- MTF validation framework (hf_validate_mtf.py, GATES_MTF.md)
- Alignment tests (35 tests, no-leak verification)
- 1H DualConfirm validation: FAIL (PF 0.43/0.36)
### Result: HALT -- DualConfirm has no edge at 1H. No 15m build.

## HF Research -- Sprint 4 (2026-02-15)
### Added
- Screening harness (harness.py -- signal-agnostic, engine fee parity)
- 15 hypotheses x 6 variants = 90 configs (hypotheses.py)
- Layer 1+2 screening pipeline (screener.py, promoter.py)
- 33 new tests (test_harness.py, test_hypotheses.py)
### Result: HALT -- 0/90 survivors. All 15 hypotheses negative at 1H Kraken fees.

## HF Research -- Sprint 5 (2026-02-15)
### Added
- Market context injection (market_context.py -- BTC regime, breadth, rankings)
- 10 hypotheses x 6 variants = 60 configs (hypotheses_s5.py)
- Cross-sectional signal support (strength + max_pos)
- 45 new tests (test_market_context.py, test_hypotheses_s5.py)
### Result: HALT -- 0/60 survivors. H20 VWAP_DEVIATION closest (PF=0.90).

## HF Research -- Reality Check Sprint (2026-02-15)
### Added
- MEXC cost model (mexc_costs_001 -- 60-92% cheaper than Kraken)
- 3-mode fill model (fill_model.py -- market/limit_optimistic/limit_realistic)
- H20 re-run under 4 cost regimes (run_reality_check.py)
### Result: CONDITIONAL GO -- H20 v5 PF=1.25, +$143/wk at MEXC market fees. First positive-expectancy result in 5 sprints.

## v3.1.0 — Agent Team V3.1 Upgrade (2026-02-14)

### Added
- Champion persistence (`save_champion` / `load_champion`)
- Scout Ablation Mode (Phase 0, 1-knob-per-keer sensitivity)
- Multi-run support (`--runs N` with coin subsampling + cross-run analysis)
- TG notification batching (auditor_status, holdout_batch)
