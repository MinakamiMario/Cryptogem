# Cryptogem Trading Bot

**Validation status**: TRADEABLE + GRID_BEST = **GO** (2026-02-15)

## Start Here (New Chat / New Agent)

1. **Read context**: `docs/CONTEXT_CAPSULE.md` — schema, invariants, root causes, fixes, validation
2. **Project knowledge**: `docs/PROJECT_MEMORY.md` — architecture, configs, learnings, file map
3. **Validation**: `docs/VALIDATION_SUMMARY.md` — all 6 robustness tests + reproduction commands
4. **Validate code**: `make check` — schema guardrail + 66 regression tests in 1 command
5. **Decisions**: `docs/DECISIONS.md` — 3 ADRs (key migration, PARAMS_BY_EXIT, guardrails)
6. **Changelog**: `docs/CHANGELOG_CONTEXT.md` — v3.1.0 + v3.1.1
7. **Load prompt**: Plak `prompts/LOAD_IN_PROMPT.md` in nieuwe chat (of `_SHORT.md` voor 6-liner)

### Quick commands
```bash
make check              # Schema + tests (must pass before any change)
make robustness         # Full GO/NO-GO validation
make grid_best-check    # GRID_BEST frozen baseline suite
make hf-check           # HF strategy check (development)
make capsule            # Print capsule version + path
```

### Invariants (do not break)
- `time_max_bars` = canonical key, `tm_bars` = legacy alias
- `normalize_cfg()` at `run_backtest()` entry + `save/load_champion()`
- `PARAMS_BY_EXIT` = source of truth for exit-type param grids
- 66 tests must stay green
- Python backtest engine = source of truth (PineScript is derived)
