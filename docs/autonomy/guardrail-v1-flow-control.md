# Guardrail v1 — Flow Control

## 1. WIP Caps

Canonieke bron: `db.get_task_counts_by_status()` — live counts uit DB.

| Status | Cap | Rationale |
|--------|-----|-----------|
| `in_progress` | 3 | Max parallelle executie — voorkomt resource race |
| `peer_review` | 5 | Review queue bounded — dwingt agents om reviews te doen |
| `review` | 5 | Staging queue bounded — voorkomt ophoping voor user |
| `approved` | 7 | User-actie queue — alerts als user niet approvet |
| `blocked` | 3 | Meer dan 3 blocked = systemisch probleem, niet meer tasks starten |
| `proposal` | 6 | Open proposals bounded — boss stopt genereren |

Caps zijn statisch in `config.py`. Geen runtime wijziging.

## 2. Backpressure & Drain Mode

### Definitie

```
counts = db.get_task_counts_by_status()
backpressure_active = any(
    counts.get(status, 0) >= cap
    for status, cap in WIP_CAPS.items()
)
drain_mode = backpressure_active
```

Evaluatie: elke heartbeat cycle, vóór transition-pogingen.

### Drain Mode: FORBIDDEN transitions

Zolang `drain_mode = True`:

| Transition | Wie | Reden blokkade |
|-----------|-----|---------------|
| `todo → in_progress` | iedereen | Geen nieuwe starts — pipeline leegtrekken |
| `proposal → todo` | boss | Geen nieuwe work intake — backlog groeit niet |
| `create_task(initial_status='proposal')` | boss | Geen nieuwe proposals — input stop |

### Drain Mode: ALLOWED transitions (pipeline leegtrekken)

| Transition | Wie | Voorwaarde |
|-----------|-----|-----------|
| `in_progress → peer_review` | assigned agent | Normaal — werk afronden |
| `in_progress → blocked` | assigned agent | Normaal — fout melden |
| `peer_review → review` | boss | Normaal — alle peers approved |
| `review → approved` | boss | Normaal — staging naar user |
| `approved → done` | user | Normaal — user keurt goed |
| `approved → in_progress` | user | Normaal — user reject |
| `peer_review → in_progress` | assigned agent | Normaal — rework na needs_changes |
| `blocked → in_progress` | assigned agent | **Alleen als** `counts['blocked'] > 0` (verlaagt blocked count) |
| `blocked → todo` | boss | **Alleen als** `counts['blocked'] > 0` (verlaagt blocked count) |

**Kernregel**: drain mode blokkeert alleen intake en nieuwe starts. Bestaande taken lopen door tot voltooiing.

## 3. Exit Conditions (anti-vage taken)

### Vereiste velden voor `todo → in_progress`

Elke taak MOET de volgende exit conditions bevatten (in task description, comment, of metadata) voordat start is toegestaan:

| Veld | Beschrijving | Voorbeeld |
|------|-------------|---------|
| `scope` | Allowed files, of `"NO WRITES"` | `reports/lab/dd_attribution_*` |
| `dod` | Concreet eindresultaat — wanneer is het klaar? | `JSON+MD report met DD% en Calmar ratio` |
| `artifact` | Wat wordt opgeleverd (bestandstype + locatie) | `reports/lab/dd_attribution_42/dd_attribution_42.json` |
| `write_surface` | Exacte paths; subset van `WRITE_ALLOWLIST` | `['lab/lab.db', 'reports/lab/']` |
| `stop_condition` | Wanneer stoppen + naar blocked | `Backtest returns None → blocked` |

### Validatie

Bij `todo → in_progress`:

1. Check of alle 5 velden aanwezig zijn in task description of comments.
2. **Alle velden aanwezig** → transition toegestaan (mits geen drain mode, geen cap breach).
3. **Veld(en) ontbreken** → agent MOET `todo → blocked` uitvoeren met comment:
   ```
   missing_exit_conditions: scope, stop_condition
   ```

### Wie vult exit conditions in?

- **Boss** vult exit conditions bij proposal-aanmaak (`_create_proposal`).
- **Gatekeepers** valideren completeness bij proposal review.
- **Agent** mag NIET zelf exit conditions toevoegen om eigen start te autoriseren — dat omzeilt de gate.

## 4. Boss Promote Rules onder Drain Mode

| Actie | Drain mode = False | Drain mode = True |
|-------|-------------------|-------------------|
| `generate_tasks()` (nieuwe proposals) | ✅ Normaal | ❌ FORBIDDEN |
| `proposal → todo` | ✅ Na gatekeeper quorum | ❌ FORBIDDEN |
| `peer_review → review` | ✅ Na alle peers approved | ✅ ALLOWED (drain) |
| `review → approved` | ✅ Auto-promote | ✅ ALLOWED (drain) |
| `check_stuck_tasks()` | ✅ Normaal | ✅ ALLOWED (monitoring) |

Boss heartbeat in drain mode: skip `generate_tasks()` en `_promote_approved_proposals()`, voer rest normaal uit.

## 5. Telegram Reporting

### Daily Digest (1× per dag)

Eén samenvatting per 24h met:

- Task counts per status (met cap indicators: `3/3 ⚠️`)
- Cap breaches (welke status, hoeveel over cap)
- Top 5 `approved` tasks wachtend op user actie
- Drain mode status: `ACTIVE` of `INACTIVE`

### Immediate Alerts (direct, geen batching)

Alleen bij escalaties:

| Trigger | Alert |
|---------|-------|
| Shell violation | `🚨 SHELL VIOLATION — agent: X, blocked: Y` |
| Daemon crash / self-test fail | `🚨 DAEMON CRASH — details` |
| Cap breach > 2 heartbeat cycles | `⚠️ CAP BREACH — status: X, count: Y/Z (>2 cycles)` |
| Write outside `WRITE_ALLOWLIST` | `🚨 WRITE VIOLATION — path: X` |
| Governance invariant breach attempt | `🚨 GOVERNANCE BREACH — details` |

**Geen alert bij**: normale cap hit (1-2 cycles), idle heartbeats, succesvolle transitions.

## 6. Samenhang met Autonomy Model v1

Dit document breidt `docs/autonomy-model-v1.md` uit met flow control. De transition classificatie (autonoom/gated/user-only) blijft ongewijzigd. Guardrail v1 voegt een **extra laag** toe:

```
Transition poging
  → VALID_TRANSITIONS check (state machine)
  → Gate check (quorum, peer reviews, user-only)
  → WIP cap check (is target status vol?)
  → Drain mode check (is intake geblokkeerd?)
  → Exit conditions check (zijn alle velden aanwezig?)
  → Transition uitgevoerd
```

Elke laag is een hard veto. Eerdere laag faalt → latere lagen worden niet geëvalueerd.
