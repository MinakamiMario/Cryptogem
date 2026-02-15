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

## v3.1.0 — Agent Team V3.1 Upgrade (2026-02-14)

### Added
- Champion persistence (`save_champion` / `load_champion`)
- Scout Ablation Mode (Phase 0, 1-knob-per-keer sensitivity)
- Multi-run support (`--runs N` with coin subsampling + cross-run analysis)
- TG notification batching (auditor_status, holdout_batch)
