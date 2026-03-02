# Cleanup Sprint — Maart 2026

## Doel

Repo "schoon" maken: inconsistenties wegwerken, half werk afronden,
technische schuld aflossen. Geen nieuwe features.

## Regels

- **Één thema per PR** — geen feature creep
- **Tests groen** — CI moet slagen voor en na
- **Strict scope** — alleen de bestanden die bij het thema horen
- **PR beschrijving** met scope / non-goals / test plan (zie CONTRIBUTING.md)

## PR's (in volgorde)

### PR 1: metric-key-alignment

**Scope**: metric keys consistent maken across agents, tools, en tests.

**Bestanden**: `lab/agents/`, `lab/tools/`, `tests/test_lab/`

**Acceptatiecriteria**:
- [ ] Alle agents gebruiken dezelfde metric key namen
- [ ] Tests valideren de juiste keys
- [ ] Geen broken imports of missing references
- [ ] CI groen

**Non-goals**: geen nieuwe metrics, geen nieuwe agents, geen refactoring

---

### PR 2: paper-bot-cleanup

**Scope**: `trading_bot/` opschonen — dode code, stale configs, ongebruikte imports.

**Bestanden**: `trading_bot/`

**Acceptatiecriteria**:
- [ ] Geen dode code of ongebruikte imports
- [ ] Config files consistent
- [ ] Bestaande functionaliteit ongewijzigd
- [ ] CI groen

**Non-goals**: geen strategie wijzigingen, geen nieuwe features, geen HF code

---

### PR 3: superhf sprint3

**Scope**: strategies + runner afwerken/opschonen.

**Bestanden**: `strategies/`, runner scripts

**Acceptatiecriteria**:
- [ ] Strategies consistent met huidige conventions
- [ ] Runner scripts werkend en gedocumenteerd
- [ ] Geen stale references naar oude experimenten
- [ ] CI groen

**Non-goals**: geen nieuwe strategieën, geen backtest runs, geen data changes

## Status

| PR | Status | Branch | Merged |
|----|--------|--------|--------|
| metric-key-alignment | DONE | cleanup/metric-key-alignment | PR #40 |
| paper-bot-cleanup | TODO | — | — |
| superhf sprint3 | TODO | — | — |
