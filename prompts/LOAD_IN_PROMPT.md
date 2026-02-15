# Load-in Prompt — Cryptogem Trading Bot

Plak dit aan het begin van elke nieuwe chat-sessie.

---

## Context
Lees eerst: `docs/CONTEXT_CAPSULE.md` (v1.0, 2026-02-14).
Beslissingen: `docs/DECISIONS.md` (3 ADRs).
Tests: `trading_bot/test_param_sensitivity.py` (66 tests).

## Regels
1. `time_max_bars` = canonical key. `tm_bars` = legacy alias (auto-migrated door `normalize_cfg()`).
2. `PARAMS_BY_EXIT` in `agent_team_v3.py` = source of truth voor welke params elke exit_type leest.
3. Nieuwe params → toevoegen aan `PARAMS_BY_EXIT` + tests updaten (test 2, 7, 9).
4. Nieuwe exit_types → toevoegen aan `PARAMS_BY_EXIT` + `used_keys_for()` test.
5. Output = artifacts (patch/tests/metrics). Geen narratief.
6. Als context ontbreekt: antwoord met `CONTEXT_MISSING: [wat ontbreekt]`, geen aannames.

## Invariants (niet breken)
- `normalize_cfg()` wordt aangeroepen in `run_backtest()` entry + `save/load_champion()`
- Scout grids gefilterd door `PARAMS_BY_EXIT[exit_type]`
- 66 tests moeten groen blijven na elke wijziging

## Open items
- `round(score, 1)` → moet `round(score, 3)` worden
- `head_to_head.py` + `backtest_mega_vergelijk.py` L360: nog legacy `tm_bars`
- Re-run 5×2h multi-run met gefixte code
