"""Lab configuration — constants, paths, safety."""
from pathlib import Path

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

# ── Task states ───────────────────────────────────────────
VALID_TRANSITIONS = {
    'backlog':      ['todo'],
    'todo':         ['in_progress'],
    'in_progress':  ['peer_review', 'blocked'],
    'peer_review':  ['review', 'in_progress'],
    'review':       ['approved', 'in_progress'],
    'approved':     ['done'],
    'blocked':      ['in_progress', 'todo'],
}

ALL_STATUSES = list(VALID_TRANSITIONS.keys()) + ['done']

# ── Review verdicts ───────────────────────────────────────
REVIEW_VERDICTS = ['pending', 'approved', 'rejected', 'needs_changes']
