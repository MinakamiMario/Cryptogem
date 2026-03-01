# Contributing — Cryptogem

## PR Definition of Done

Elke PR moet aan **alle** criteria voldoen voordat merge:

### Verplicht
- [ ] **CI groen** — alle tests slagen in GitHub Actions
- [ ] **Scope beschreven** — PR description bevat: scope, non-goals, test plan
- [ ] **Één thema per PR** — geen feature creep, geen "even meenemen"
- [ ] **Geen runtime state files** — geen `.db`, `.db-shm`, `.db-wal`, `.log`, `.json` data
- [ ] **Geen secrets** — geen tokens, wachtwoorden, API keys in code of config

### Lab-specifiek
- [ ] **Shell guard intact** — geen nieuwe `subprocess.*` calls buiten allowlist
- [ ] **Governance invariant** — state machine transitions ongewijzigd tenzij dat het PR-doel is
- [ ] **CODEOWNERS respect** — wijzigingen aan beschermde bestanden door owner reviewed

### Workflow-only PRs
PRs die alleen `.github/workflows/` wijzigen MOETEN:
- [ ] Een `workflow_dispatch` trigger hebben OF een expliciete uitzondering documenteren
- [ ] Getest zijn via dry-run of dispatch voordat merge

## PR Beschrijving Template

```markdown
## Scope
[Wat dit PR doet — 1-3 bullets]

## Non-goals
[Wat dit PR NIET doet — voorkom scope discussie]

## Test plan
- [ ] CI groen
- [ ] [Specifieke test scenario's]

## Gevoelige bestanden
[Lijst bestanden die CODEOWNERS-review vereisen, of "Geen"]
```

## Commit Messages

Format: `type(scope): korte beschrijving`

Types:
- `feat` — nieuwe feature
- `fix` — bugfix
- `docs` — documentatie
- `test` — tests toevoegen/wijzigen
- `refactor` — code herstructureren zonder gedragswijziging
- `ci` — CI/CD wijzigingen
- `chore` — overig (deps, config)

Voorbeelden:
```
feat(notifier): add Remote Hands healthcheck button
fix(db): enforce gatekeeper quorum on proposal→todo
docs(ops): add controlled reboot runbook
test(notifier): add approve/reject callback tests
```

## Branch Naming

Format: `type/korte-beschrijving`

```
feat/remote-hands-button
fix/metric-key-alignment
docs/ops-runbook
```
