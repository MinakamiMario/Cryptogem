# Architecture Decision Records (ADR-light)

## ADR-001: Canonical key migration tm_bars → time_max_bars
- **Date**: 2026-02-14
- **Context**: tp_sl exit branch read `cfg.get('tm_bars', 15)` but Scout grid set `cfg['time_max_bars']`. Two different keys for the same parameter caused 62.5% no-op waste in search space.
- **Decision**: `time_max_bars` is the canonical key. `tm_bars` is a legacy alias auto-migrated by `normalize_cfg()`. All new code MUST use `time_max_bars`.
- **Consequences**:
  - `normalize_cfg()` called at `run_backtest()` entry + `save/load_champion()`
  - Legacy configs (champion.json, overnight_optimizer starting configs) auto-migrate on read
  - 2 active scripts still need migration: `head_to_head.py`, `backtest_mega_vergelijk.py` (tp_sl branch)
  - 23+ deprecated scripts left as-is (not worth migrating)

## ADR-002: Exit-type-aware grids via PARAMS_BY_EXIT
- **Date**: 2026-02-14
- **Context**: Scout grid swept all 9 params for every exit_type, but tp_sl only reads 5, trail reads 7, hybrid_notrl reads 5. This caused 62.5% wasted evaluations.
- **Decision**: Module-level `PARAMS_BY_EXIT` dict defines which params each exit_type reads. Scout Phase 0/1/2 grids filtered by this dict.
- **Consequences**:
  - Unique ratio improved 37.5% → 75.0% (2.0x)
  - Any new exit_type MUST add an entry to `PARAMS_BY_EXIT`
  - Any new param MUST be added to the correct exit_type(s) in `PARAMS_BY_EXIT`
  - Ablation grid also filtered — only tests relevant params

## ADR-003: Guardrails & regression tests
- **Date**: 2026-02-14
- **Context**: The tm_bars bug went undetected because no test verified that grid params actually affect backtest output.
- **Decision**: Added `warn_unused_params()` guardrail + 66 regression tests covering alias migration, param sensitivity, grid filtering, edge cases, and canonical key persistence.
- **Consequences**:
  - `warn_unused_params()` logs at Scout grid start (shows skipped params)
  - Tests must pass before any config search code change
  - New params require updating tests 2, 7, and 9

## ADR-004: HF Research ADRs in Separate File
- **Date**: 2026-02-15
- **Context**: HF (1H screening) research produced 29 architecture decision records. These are domain-specific and separate from the core trading_bot/ ADRs.
- **Decision**: All HF ADRs live in `strategies/hf/DECISIONS.md` (ADR-HF-001 through ADR-HF-029). Root-level `docs/DECISIONS.md` contains only trading_bot/ ADRs.
- **Key HF findings**:
  - 25 hypothesis families tested, 150+ configs -- all negative at Kraken fees
  - H20 VWAP_DEVIATION is the only positive-expectancy signal (MEXC fees only)
  - 1H crypto at Kraken fees is structurally unprofitable (fee structure bottleneck)
  - See ADR-HF-029 for CONDITIONAL GO decision

## ADR-MX-001: MX-MICRO-TP5SL3 micro-live track (TP5/SL3/T24h)
- **Date**: 2026-02-26
- **Context**: MEXC micro-live alpha validation needs clear naming to separate from HF-P2-LIVE-FILL (fill-rate only) and MEXC-4H-PAPER (4H paper trader). Previous naming used "HF" prefix which conflated alpha validation with HF screening research.
- **Decision**: Track name is `MX-MICRO-TP5SL3`. All output artifacts use this prefix. Separate from HF-P2-LIVE-FILL.
- **Naming contract**:
  - Entrypoint: `trading_bot/paper_hf_1h.py --mode micro`
  - State file: `trading_bot/paper_state_mx_micro_tp5sl3.json`
  - Dashboard: `trading_bot/dashboard_mx_micro_tp5sl3.json`
  - Logs: `trading_bot/logs/mx_micro_tp5sl3_*.log`
  - Reports: `reports/mx_micro_tp5sl3/*`
  - Telegram: first line always contains `MX-MICRO-TP5SL3`
- **Config**: TP +5% / SL -3% / TIME 24h / MEXC SPOT / near_ask maker limit
- **Consequences**:
  - `MICRO_TAG = 'mx_micro_tp5sl3'` constant in `paper_hf_1h.py`
  - Paper mode (`--mode paper`) unchanged — still uses `hf_1h_paper` TAG for fill-rate validation
  - Old state files (`paper_state_hf_1h_paper_micro.json`, `dashboard_hf_micro.json`) are orphaned — not auto-migrated
  - New runs create new state under `mx_micro_tp5sl3` naming
