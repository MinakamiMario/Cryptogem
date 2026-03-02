# Autonomy Capability Model v1

## 1. Capability Tiers

| Tier | Naam | Omschrijving | Rationale |
|------|------|-------------|-----------|
| **T0** | **Observe** | Read DB state, heartbeat pulse, lees tasks/reviews/comments. Geen state mutations. | Basis voor elke agent — informatie ophalen is altijd veilig. |
| **T1** | **Internal Write** | Comments toevoegen, reports schrijven (binnen `WRITE_ALLOWLIST`), eigen agent status updaten. | Output produceren zonder workflow state te veranderen. Begrensd door allowlist (`lab/lab.db`, `reports/lab/`). |
| **T2** | **Propose & Self-Promote** | Task proposals aanmaken (`status='proposal'`). Eigen taken verplaatsen: `in_progress→peer_review`, `in_progress→blocked`. | Agent heeft autonomie over eigen actieve werk. Proposals zijn geblokkeerd tot gatekeepers goedkeuren — geen risico. |
| **T3** | **Review & Gate** | Peer work reviewen (approve/needs_changes). Gatekeeper proposal reviews. Workflow promotions na quorum: `proposal→todo`, `peer_review→review`, `review→approved`. Start-gate: `todo→in_progress`. Herplanning: `blocked→todo`. | Collectieve besluitvorming. DB enforced alle gates — agent probeert, DB beslist. Geen agent kan gates omzeilen. |
| **T4** | **Final Authority** | `approved→done` en `approved→in_progress` (reject). | Exclusief user via Telegram. Menselijke handtekening op finale beslissing. Nooit autonoom. |

**Invariant**: DB `transition()` is de canonieke enforcer. Agents roepen transitions aan, maar de DB valideert elke gate. Geen tier kan een hogere tier omzeilen.

## 2. Capability Matrix

| Agent | T0 Observe | T1 Write | T2 Propose | T2 Self-Promote | T3 Review | T3 Gate | T4 Final |
|-------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **boss** | R | C,Rp | P | S | Pr | WP,ST,HP | -- |
| **risk_governor** | R | C,Rp | -- | S | Pr | GK | -- |
| **robustness_auditor** | R | C,Rp | -- | S | Pr | GK | -- |
| **deployment_judge** | R | C,Rp | -- | S | Pr | -- | -- |
| **edge_analyst** | R | C,Rp | -- | S | Pr | -- | -- |
| **live_monitor** | R | C,Rp | -- | S | Pr | -- | -- |
| **portfolio_architect** | R | C,Rp | -- | S | Pr | -- | -- |
| **hypothesis_gen** | R | C,Rp | -- | S | Pr | -- | -- |
| **meta_research** | R | C,Rp | -- | S | Pr | -- | -- |
| **infra_guardian** | R | C,Rp | -- | S | Pr | -- | -- |

**Legenda**:
- **R** = Read DB state, heartbeat
- **C** = Comments toevoegen
- **Rp** = Reports schrijven (`reports/lab/`)
- **P** = Proposals aanmaken (task met `status='proposal'`)
- **S** = Self-promote (eigen actieve taken: `in_progress→peer_review|blocked`)
- **Pr** = Peer review (approve/needs_changes op andermans werk)
- **GK** = Gatekeeper review (proposal goedkeuring, vereist voor `proposal→todo`)
- **WP** = Workflow promotions (`proposal→todo`, `peer_review→review`, `review→approved`)
- **ST** = Start-gate (`todo→in_progress` — boss zet `safe_to_start` flag)
- **HP** = Herplanning (`blocked→todo` — boss beoordeelt of taak terug mag)
- **--** = Niet toegestaan

### Opmerkingen bij specifieke agents

- **boss**: Enige agent die proposals aanmaakt, start-gate beheert, herplanning doet, en workflow promotions uitvoert. Kernoperatie is rule-based; LLM optioneel voor task generatie.
- **risk_governor + robustness_auditor**: Gatekeepers. BEIDE moeten proposals goedkeuren (quorum=2/2). Afgedwongen in `db.transition()`.
- **hypothesis_gen + meta_research**: LLM agents. Zelfde tier-rechten als non-LLM workers — LLM beperkt tot task execution, niet governance.
- **infra_guardian**: Repo integrity checks. Geen extra privileges ondanks infrastructuur-rol.

## 3. Transition Classificatie

### Autonome transitions (agent mag zelfstandig)

| Transition | Wie | Voorwaarde |
|-----------|-----|-----------|
| `in_progress → peer_review` | assigned agent | Na execute + artifact + comment |
| `in_progress → blocked` | assigned agent | Verplicht: `reason` (string) + `blocked_since` (timestamp). Zonder reason = rejection door DB. |
| `blocked → in_progress` | assigned agent | Retry na blokkade opgelost |
| `peer_review → in_progress` | assigned agent | Na needs_changes review (rework) |

### Gated transitions (T3 — boss/gatekeeper vereist)

| Transition | Wie initieert | Gate |
|-----------|--------------|------|
| `todo → in_progress` | assigned agent | **Start-gate**: boss (of gatekeeper) moet `safe_to_start=true` zetten op task. Agent mag alleen starten als flag gezet is. Voorkomt: fake voortgang, ongecontroleerde writes, metrics-manipulatie. |
| `blocked → todo` | boss | **Herplanning**: alleen boss mag taak terugzetten naar todo. Voorkomt: status verdoezelen door agent die eigen blokkade wist. |
| `proposal → todo` | boss | **2/2 gatekeepers approved** (`risk_governor` + `robustness_auditor`) |
| `peer_review → review` | boss | **Alle peer reviews approved** (geen pending reviews) |
| `review → approved` | boss | Geen extra gate — boss auto-promotes. `review` is een staging state: werk is peer-approved, wacht op user-facing presentatie via Telegram. |

**Design note**: `review` is puur een staging state. Betekenis: "alle peers akkoord, boss presenteert aan user". Geen inhoudelijke gate — de peer review gate zit op `peer_review→review`.

### Exclusief user transitions (T4 — nooit autonoom)

| Transition | Gate | Mechanisme |
|-----------|------|-----------|
| `approved → done` | `actor = 'user'` | Telegram ✅ knop |
| `approved → in_progress` | `actor = 'user'` | Telegram ❌ knop (reject → rework) |

### Transition totaal: 11

| Categorie | Transitions | Telling |
|-----------|------------|---------|
| Autonoom (T2) | `in_progress→peer_review`, `in_progress→blocked`, `blocked→in_progress`, `peer_review→in_progress` | 4 |
| Gated (T3) | `todo→in_progress`, `blocked→todo`, `proposal→todo`, `peer_review→review`, `review→approved` | 5 |
| User-only (T4) | `approved→done`, `approved→in_progress` | 2 |

## 4. Never Autonomous (harde grenzen)

### Nooit autonoom — acties die ALTIJD menselijke handtekening vereisen

1. **`approved → done`** — Finale goedkeuring van resultaat
2. **`approved → in_progress`** — Reject en terugsturen voor rework
3. **Reboot/shutdown** — Shell guard blokkeert; expliciete user-taak met maintenance window
4. **Goal aanmaken/archiveren** — Strategische beslissing, niet agent-initiatief
5. **Gatekeeper of quorum config wijzigen** — CODEOWNERS-beschermd (`lab/config.py`)
6. **Shell/CLI uitvoeren** — Shell guard blokkeert alle subprocess calls
7. **Schrijven buiten WRITE_ALLOWLIST** — `PermissionError` bij poging
8. **CI/CD triggers** — Uitsluitend via GitHub Actions, niet via agents
9. **Communicatie buiten Telegram** — LabNotifier is de enige UI

### User-Only lijst (samenvatting)

| Actie | Reden |
|-------|-------|
| Task definitief afronden | Menselijke verificatie van research output |
| Task rejecten na approval | Koerswijziging is strategische beslissing |
| Goals beheren | Research richting bepalen |
| Config wijzigen | Governance invarianten beschermen |
| Rebooten | Fysieke toegang + maintenance window vereist |
| Releases taggen | CI/CD canonical, niet agent-initiated |
