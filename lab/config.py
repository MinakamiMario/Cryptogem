"""Lab configuration — constants, paths, safety."""
from __future__ import annotations

from pathlib import Path

LAB_VERSION = "1.1.1"

# ── GitHub ────────────────────────────────────────────────
GITHUB_REPO = 'MinakamiMario/Cryptogem'

# ── Shell guard ──────────────────────────────────────────
# Hard kill-switch: blocks subprocess calls to gh, git, pytest, etc.
# InfraGuardian system commands (df, uptime) are unaffected.
ALLOW_LOCAL_SHELL = False

# ── Paths ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = REPO_ROOT / 'lab'
DB_PATH = LAB_DIR / 'lab.db'
REPORTS_DIR = REPO_ROOT / 'reports' / 'lab'
TRADING_BOT_DIR = REPO_ROOT / 'trading_bot'
SOULS_DIR = LAB_DIR / 'souls'
DOTENV_PATH = TRADING_BOT_DIR / '.env'

# ── Write allowlist (safety) ──────────────────────────────
# Lab mag ALLEEN naar deze paden schrijven — alles buiten → PermissionError
WRITE_ALLOWLIST = [
    'lab/lab.db',
    'reports/lab/',
]


def safe_write_check(path: str | Path) -> None:
    """Raise PermissionError als path buiten allowlist valt."""
    resolved = Path(path).resolve()
    try:
        rel = str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        raise PermissionError(f"Lab write blocked: {resolved} is outside repo")
    if not any(rel.startswith(allowed) for allowed in WRITE_ALLOWLIST):
        raise PermissionError(
            f"Lab write blocked: {rel} not in allowlist {WRITE_ALLOWLIST}"
        )


# ── Heartbeat ─────────────────────────────────────────────
HEARTBEAT_INTERVAL_S = 600        # 10 minuten
HEARTBEAT_STAGGER_S = 60          # 1 min offset per agent
STUCK_THRESHOLD_H = 24            # uren voordat boss escaleert
DAILY_DIGEST_INTERVAL_S = 86400   # 24 uur — digest 1×/dag
CAP_BREACH_ESCALATE_CYCLES = 2    # drain >N cycles → cap_breach_alert

# ── LLM ───────────────────────────────────────────────────
LLM_MODEL = 'claude-sonnet-4-20250514'
LLM_MAX_OUTPUT_TOKENS = 4096
LLM_TIMEOUT_S = 30
LLM_MAX_RETRIES = 3
LLM_BACKOFF_BASE_S = 2.0         # exponential: 2, 4, 8 + jitter

# ── Agent registry ────────────────────────────────────────
AGENT_NAMES = [
    'boss',
    'edge_analyst',
    'risk_governor',
    'robustness_auditor',
    'infra_guardian',
    'meta_research',
    'hypothesis_gen',
    'live_monitor',
    'portfolio_architect',
    'deployment_judge',
]

LLM_AGENTS = {'boss', 'meta_research', 'hypothesis_gen'}

# ── Governance ────────────────────────────────────────────
# Gatekeepers: ALLEEN deze agents mogen proposals reviewen.
# Hardcoded — niet via DB of goal membership af te leiden.
GATEKEEPERS = ['risk_governor', 'robustness_auditor']
GATEKEEPER_QUORUM = 2  # len(GATEKEEPERS), beide moeten approved

# ── Task states ───────────────────────────────────────────
VALID_TRANSITIONS = {
    'proposal':     ['todo'],              # quorum gate in DB
    'backlog':      ['todo'],              # deprecated, user only
    'todo':         ['in_progress'],
    'in_progress':  ['peer_review', 'blocked'],
    'peer_review':  ['review', 'in_progress'],
    'review':       ['approved'],          # boss auto-promote
    'approved':     ['done', 'in_progress'],  # user approve of reject
    'done':         [],                    # terminal, expliciet
    'blocked':      ['in_progress', 'todo'],
}

ALL_STATUSES = list(VALID_TRANSITIONS.keys())  # done zit er nu in

# ── Review verdicts ───────────────────────────────────────
REVIEW_VERDICTS = ['pending', 'approved', 'rejected', 'needs_changes']

# ── WIP caps (Guardrail v1) ──────────────────────────────
# Static caps per status — no runtime modification.
# Cap breach blocks NEW transitions into that status; existing tasks continue.
WIP_CAPS: dict[str, int] = {
    'in_progress':  3,
    'peer_review':  5,
    'review':       5,
    'approved':     7,
    'blocked':      3,
    'proposal':     6,   # open_proposals cap
}

# ── Exit conditions (required for todo → in_progress) ────
# Every task MUST have these fields populated before start.
# Missing any → transition blocked, agent must move to blocked.
# Boss fills these at proposal creation; gatekeepers validate completeness.
EXIT_CONDITIONS = [
    'scope',            # Allowed files, or "NO WRITES"
    'dod',              # Definition of Done — concrete end result
    'artifact',         # What will be delivered (file type + location)
    'write_surface',    # Exact paths; subset of WRITE_ALLOWLIST
    'stop_condition',   # When to stop + move to blocked
]

# ── High-risk files (TG alert on modification) ───────────
HIGH_RISK_FILES = [
    '.github/workflows/',
    'lab/config.py',
    'lab/db.py',
    'lab/shell_guard.py',
    'lab/notifier.py',
    'lab/deploy/',
]
