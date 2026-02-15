# Context Capsule
<!-- Capsule-Version: v1.2 -->
<!-- Applies-to-commit: v0.1-validation-baseline -->
<!-- Last-updated: 2026-02-15 -->
<!-- Updated-by: Repo-artifacts + validation consolidation -->
**Scope**: trading_bot/ parameter sensitivity fix + search space optimization + validation baseline

---

## Project Goal
Crypto trading bot (Kraken, 526 coins, 4H candles). Agent Team V3 optimizes config parameters via multi-agent search (Scout/Auditor/Validator/Orchestrator). Bear market DualConfirm bounce strategy.

## Canonical Schema

| Key | Status | Notes |
|-----|--------|-------|
| `time_max_bars` | **CANONICAL** | Time-based exit: max bars in position |
| `tm_bars` | LEGACY ALIAS | Auto-migrated by `normalize_cfg()` → `time_max_bars` |

### Invariants
- `normalize_cfg()` is called at `run_backtest()` entry (line ~308) and `load_champion()`
- `save_champion()` normalizes before writing to disk
- `PARAMS_BY_EXIT` dict defines which params each exit_type reads (source of truth for grid filtering)
- Scout Phase 0 (Ablation) + Phase 1+2 grids are filtered by `PARAMS_BY_EXIT[exit_type]`

### PARAMS_BY_EXIT (module-level, agent_team_v3.py)
```
tp_sl:        entry=[rsi_max, vol_spike_mult]  exit=[tp_pct, sl_pct, time_max_bars]
trail:        entry=[rsi_max, vol_spike_mult]  exit=[atr_mult, be_trigger, max_stop_pct, time_max_bars, rsi_rec_target]
hybrid_notrl: entry=[rsi_max, vol_spike_mult]  exit=[max_stop_pct, time_max_bars, rsi_rec_target]
```

## Root Causes (proven)

### Bug 1: `tm_bars` vs `time_max_bars` naming conflict
- **Where**: tp_sl exit branch read `cfg.get('tm_bars', 15)` but Scout grid set `cfg['time_max_bars']`
- **Effect**: tp_sl never saw grid variations for time_max_bars
- **Proof**: `debug_identical_scores.py` — 19/19 trail-only param variations IDENTICAL for tp_sl
- **Fix**: `normalize_cfg()` + canonical `time_max_bars` everywhere

### Bug 2: Trail-only params in tp_sl grid (62.5% waste)
- **Where**: Scout grid contained all 9 params but tp_sl only reads 5
- **Effect**: `atr_mult`, `be_trigger`, `max_stop_pct`, `rsi_rec_target` produced no-op evaluations
- **Proof**: Metrics script — 24 evals, 9 unique sigs (37.5%) BEFORE vs 20 evals, 15 unique (75.0%) AFTER
- **Fix**: `PARAMS_BY_EXIT` dict + exit-type-aware grid filtering

### Issue 3: Score resolution hides real differences
- **Where**: `round(score, 1)` in `evaluate()`
- **Effect**: 60.532 vs 60.545 both become 60.5 → top-5 spread=0.0
- **Status**: KNOWN, not yet fixed. Recommendation: `round(score, 3)`

## Fixes Applied

| Fix | File | What |
|-----|------|------|
| `normalize_cfg()` | agent_team_v3.py L138-147 | Migrates tm_bars → time_max_bars |
| `PARAMS_BY_EXIT` | agent_team_v3.py L165-180 | Source of truth for exit-type params |
| `used_keys_for()` | agent_team_v3.py L182-184 | Returns valid keys for exit_type |
| `warn_unused_params()` | agent_team_v3.py L186-192 | Guardrail: logs unused cfg keys |
| tp_sl branch | agent_team_v3.py L365 | `cfg.get('time_max_bars', 15)` (was `tm_bars`) |
| save_champion | agent_team_v3.py L118 | `normalize_cfg(dict(entry['cfg']))` |
| load_champion | agent_team_v3.py | normalizes on load |
| Scout grids | agent_team_v3.py L1178+ | Filtered by PARAMS_BY_EXIT |
| overnight_optimizer | overnight_optimizer.py L199+ | Dual fallback + canonical keys |

## Tests (66/66 passing)

| Test | What it proves |
|------|---------------|
| 1-5 | Alias works, param effect, warn_unused, normalize, used_keys_for |
| 6 | Trail-only params IDENTICAL at tp_sl (8 assertions) |
| 7 | Scout grid filtering correct per exit_type (9 assertions) |
| 8 | Edge cases: empty cfg, unknown exit_type, garbage keys (5 assertions) |
| 9 | hybrid_notrl inclusions/exclusions correct (7 assertions) |
| 10 | save_champion writes canonical keys (3 assertions) |

## Metrics (reproducible, same seed + dataset)

| KPI | BEFORE | AFTER |
|-----|--------|-------|
| Evaluations | 24 | 20 |
| Unique backtest sigs | 9 | 15 |
| **Unique ratio** | **37.5%** | **75.0%** |
| No-op waste | 62.5% | 25.0% |

Definition: `unique_backtest_signatures / total_evaluations` where signature = `(trade_count, round(pnl, 2))`

## Open Risks / Next Steps

1. **Score precision**: `round(score, 1)` → should be `round(score, 3)` to prevent false plateau detection
2. **notop_s saturation**: cap at $2500 prevents differentiation among good configs
3. **head_to_head.py**: still reads `cfg.get('tm_bars', 15)` — needs migrate
4. **backtest_mega_vergelijk.py L360**: tp_sl branch still reads `tm_bars` — needs migrate
5. **champion.json on disk**: still has legacy `tm_bars` — auto-fixes on next save_champion()
6. **Re-run 5×2h multi-run**: previous 5-run used buggy grids, results invalid

## Validation Status

**Overall**: TRADEABLE + GRID_BEST = **GO** (2026-02-15)
**Details**: See `docs/VALIDATION_SUMMARY.md` for all 6 robustness tests + reproduction commands.

## PineScript

- **File**: `trading_bot/DualConfirm_GRID_BEST.pine` (PineScript v6)
- **Config**: GRID_BEST tp_sl (tp12/sl10/vs2.5/rsi45/tm15)
- **Rule**: Python backtest engine (`agent_team_v3.py`) is the source of truth. PineScript is derived — any discrepancy means PineScript is wrong.

## Code Pointers

| Function | File | Purpose |
|----------|------|---------|
| `normalize_cfg()` | agent_team_v3.py L138 | Key migration |
| `PARAMS_BY_EXIT` | agent_team_v3.py L165 | Exit-type param registry |
| `used_keys_for()` | agent_team_v3.py L182 | Key set lookup |
| `warn_unused_params()` | agent_team_v3.py L186 | Guardrail logger |
| `run_backtest()` | agent_team_v3.py L308 | Normalize entry point |
| `save_champion()` | agent_team_v3.py L118 | Persist + normalize |
| `load_champion()` | agent_team_v3.py L126 | Load + normalize |
| `test_param_sensitivity.py` | trading_bot/ | 66 regression tests |
