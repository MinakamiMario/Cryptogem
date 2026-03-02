"""Lab SQLite database — schema, CRUD, state machine enforcement."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger('lab.db')

from lab.config import (
    AGENT_NAMES, ALL_STATUSES, DB_PATH, EXIT_CONDITIONS, GATEKEEPERS,
    REVIEW_VERDICTS, VALID_TRANSITIONS, WIP_CAPS,
)
from lab.models import (
    AgentStatus, Comment, CycleMetrics, GateRejection, Goal, Task,
    TaskResult, TaskReview,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    agents      TEXT NOT NULL,
    tasks_per_day INTEGER DEFAULT 2,
    status      TEXT DEFAULT 'active',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY,
    goal_id         INTEGER REFERENCES goals(id),
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    assigned_to     TEXT NOT NULL,
    status          TEXT DEFAULT 'backlog',
    priority        INTEGER DEFAULT 5,
    created_by      TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    blocked_since   TEXT,
    artifact_path   TEXT,
    artifact_sha256 TEXT,
    artifact_git_hash TEXT,
    artifact_cmd    TEXT,
    exit_conditions TEXT
);

CREATE TABLE IF NOT EXISTS task_reviews (
    id          INTEGER PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES tasks(id),
    reviewer    TEXT NOT NULL,
    verdict     TEXT NOT NULL DEFAULT 'pending',
    comment_id  INTEGER REFERENCES comments(id),
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(task_id, reviewer)
);

CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER REFERENCES tasks(id),
    agent        TEXT NOT NULL,
    body         TEXT NOT NULL,
    comment_type TEXT DEFAULT 'comment',
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_status (
    agent           TEXT PRIMARY KEY,
    status          TEXT DEFAULT 'idle',
    last_heartbeat  TEXT,
    current_task_id INTEGER,
    progress_note   TEXT
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY,
    agent       TEXT NOT NULL,
    action      TEXT NOT NULL,
    task_id     INTEGER,
    details     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cycle_metrics (
    id              INTEGER PRIMARY KEY,
    cycle           INTEGER NOT NULL,
    reviews         INTEGER DEFAULT 0,
    tasks           INTEGER DEFAULT 0,
    promotions      INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    drain_mode      INTEGER DEFAULT 0,
    drain_cycles    INTEGER DEFAULT 0,
    agent_count     INTEGER DEFAULT 0,
    cycle_duration_s REAL DEFAULT 0.0,
    skipped_agents  INTEGER DEFAULT 0,
    retries         INTEGER DEFAULT 0,
    agent_timings   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gate_rejections (
    id          INTEGER PRIMARY KEY,
    gate        TEXT NOT NULL,
    task_id     INTEGER,
    actor       TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lab_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


class LabDB:
    """SQLite database with WAL mode, state machine, and write safety."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        # Pragmas
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Create tables + seed agent_status rows + run migrations."""
        self.conn.executescript(SCHEMA_SQL)
        for name in AGENT_NAMES:
            self.conn.execute(
                "INSERT OR IGNORE INTO agent_status (agent) VALUES (?)",
                (name,),
            )
        # Migration: add exit_conditions column if missing (existing DBs)
        cols = {row[1] for row in
                self.conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if 'exit_conditions' not in cols:
            self.conn.execute(
                "ALTER TABLE tasks ADD COLUMN exit_conditions TEXT"
            )
        # Migration: create cycle_metrics table if missing (v1.0.5)
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if 'cycle_metrics' not in tables:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cycle_metrics (
                    id              INTEGER PRIMARY KEY,
                    cycle           INTEGER NOT NULL,
                    reviews         INTEGER DEFAULT 0,
                    tasks           INTEGER DEFAULT 0,
                    promotions      INTEGER DEFAULT 0,
                    errors          INTEGER DEFAULT 0,
                    drain_mode      INTEGER DEFAULT 0,
                    drain_cycles    INTEGER DEFAULT 0,
                    agent_count     INTEGER DEFAULT 0,
                    cycle_duration_s REAL DEFAULT 0.0,
                    created_at      TEXT DEFAULT (datetime('now'))
                )
            """)
        # Migration: create gate_rejections table if missing (v1.0.7)
        if 'gate_rejections' not in tables:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS gate_rejections (
                    id          INTEGER PRIMARY KEY,
                    gate        TEXT NOT NULL,
                    task_id     INTEGER,
                    actor       TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status   TEXT NOT NULL,
                    reason      TEXT NOT NULL,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)
        # Migration: add skipped_agents + retries to cycle_metrics (v1.0.8)
        if 'cycle_metrics' in tables:
            cm_cols = {row[1] for row in
                       self.conn.execute(
                           "PRAGMA table_info(cycle_metrics)").fetchall()}
            if 'skipped_agents' not in cm_cols:
                self.conn.execute(
                    "ALTER TABLE cycle_metrics "
                    "ADD COLUMN skipped_agents INTEGER DEFAULT 0"
                )
            if 'retries' not in cm_cols:
                self.conn.execute(
                    "ALTER TABLE cycle_metrics "
                    "ADD COLUMN retries INTEGER DEFAULT 0"
                )
        # Migration: create lab_settings table if missing (v1.1.1)
        if 'lab_settings' not in tables:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS lab_settings (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    updated_at  TEXT DEFAULT (datetime('now'))
                )
            """)
        # Migration: add agent_timings column to cycle_metrics (v1.2.0)
        if 'cycle_metrics' in tables:
            if 'agent_timings' not in cm_cols:
                self.conn.execute(
                    "ALTER TABLE cycle_metrics "
                    "ADD COLUMN agent_timings TEXT DEFAULT '{}'"
                )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── Settings (key-value store) ─────────────────────────

    def get_setting(self, key: str, default: str = '') -> str:
        """Get a setting by key. Returns default if not found."""
        row = self.conn.execute(
            "SELECT value FROM lab_settings WHERE key = ?", (key,)
        ).fetchone()
        return row['value'] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Upsert a setting."""
        self.conn.execute(
            "INSERT INTO lab_settings (key, value, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, value),
        )
        self.conn.commit()

    # ── Goals ─────────────────────────────────────────────

    def create_goal(self, title: str, agents: list[str],
                    description: str = '', tasks_per_day: int = 2) -> int:
        cur = self.conn.execute(
            "INSERT INTO goals (title, description, agents, tasks_per_day) "
            "VALUES (?, ?, ?, ?)",
            (title, description, json.dumps(agents), tasks_per_day),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_goals(self, status: str = 'active') -> list[Goal]:
        rows = self.conn.execute(
            "SELECT * FROM goals WHERE status = ?", (status,)
        ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        row = self.conn.execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        return self._row_to_goal(row) if row else None

    def get_goal_agents(self, goal_id: int) -> list[str]:
        goal = self.get_goal(goal_id)
        return goal.agents if goal else []

    # ── Tasks ─────────────────────────────────────────────

    def create_task(self, goal_id: int, title: str, assigned_to: str,
                    created_by: str, description: str = '',
                    priority: int = 5,
                    initial_status: str = 'backlog',
                    exit_conditions: Optional[dict] = None) -> int:
        """Create a task. Boss uses initial_status='proposal' for quorum gate.

        Args:
            exit_conditions: dict with keys from config.EXIT_CONDITIONS.
                             Stored as JSON in DB. Boss fills at proposal time.
        """
        if initial_status not in ('backlog', 'todo', 'proposal'):
            raise ValueError(
                f"initial_status must be 'backlog', 'todo', or 'proposal', "
                f"got '{initial_status}'"
            )
        # Guardrail v1: check proposal cap first (specific error)
        if initial_status == 'proposal' and 'proposal' in WIP_CAPS:
            counts = self.get_task_counts_by_status()
            cap = WIP_CAPS['proposal']
            if counts.get('proposal', 0) >= cap:
                raise ValueError(
                    f"WIP cap reached: proposal has "
                    f"{counts['proposal']}/{cap} tasks"
                )
        # Guardrail v1: block new proposals in drain mode (other caps hit)
        if initial_status == 'proposal' and self.is_drain_mode():
            raise ValueError(
                "Drain mode active — new proposals forbidden. "
                f"Cap breaches: {self.get_cap_breaches()}"
            )
        ec_json = json.dumps(exit_conditions) if exit_conditions else None
        cur = self.conn.execute(
            "INSERT INTO tasks (goal_id, title, description, assigned_to, "
            "created_by, priority, status, exit_conditions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (goal_id, title, description, assigned_to, created_by, priority,
             initial_status, ec_json),
        )
        self.conn.commit()
        self.log_activity(created_by, 'task_created', cur.lastrowid,
                          {'title': title, 'assigned_to': assigned_to,
                           'status': initial_status})
        return cur.lastrowid

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def get_my_tasks(self, agent: str, status: str = 'todo') -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE assigned_to = ? AND status = ? "
            "ORDER BY priority ASC, created_at ASC",
            (agent, status),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_my_rejected_tasks(self, agent: str) -> list[Task]:
        """Get tasks assigned to agent in peer_review with needs_changes."""
        rows = self.conn.execute(
            """SELECT DISTINCT t.* FROM tasks t
               JOIN task_reviews tr ON tr.task_id = t.id
               WHERE t.assigned_to = ? AND t.status = 'peer_review'
                 AND tr.verdict = 'needs_changes'
               ORDER BY t.priority ASC, t.created_at ASC""",
            (agent,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_tasks_by_status(self, status: str) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY priority ASC",
            (status,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_tasks_by_goal(self, goal_id: int) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE goal_id = ? ORDER BY created_at DESC",
            (goal_id,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def count_tasks_today(self, goal_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE goal_id = ? "
            "AND date(created_at) = date('now')",
            (goal_id,),
        ).fetchone()
        return row[0]

    def _log_gate_rejection(self, gate: str, task_id: int, actor: str,
                            from_status: str, to_status: str,
                            reason: str) -> None:
        """Record a gate rejection in the gate_rejections table."""
        try:
            self.conn.execute(
                "INSERT INTO gate_rejections "
                "(gate, task_id, actor, from_status, to_status, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gate, task_id, actor, from_status, to_status, reason),
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(
                f"Gate rejection log failed ({gate}, task #{task_id}): {e}"
            )

    def transition(self, task_id: int, new_status: str, actor: str) -> None:
        """Enforce state machine. Raises ValueError on invalid transition.

        Gates:
        1. peer_review → review: all peer reviews must be approved
        2. proposal → todo: BOTH gatekeepers must have approved reviews
        3. approved → done: only user actor allowed
        4. approved → in_progress: only user actor allowed (reject)
        5. WIP cap check
        6. Drain mode check
        7. Exit conditions check

        All gate rejections are logged to gate_rejections table.
        """
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        allowed = VALID_TRANSITIONS.get(task.status, [])
        if new_status not in allowed:
            reason = (f"Invalid transition: {task.status} -> {new_status} "
                      f"(allowed: {allowed})")
            self._log_gate_rejection(
                'invalid_transition', task_id, actor,
                task.status, new_status, reason)
            raise ValueError(reason)

        # Gate 1: peer_review → review requires all peer reviews approved
        if task.status == 'peer_review' and new_status == 'review':
            pending = self.get_pending_reviews(task_id)
            if pending:
                reason = (f"Cannot promote: {len(pending)} reviews pending: "
                          f"{[r.reviewer for r in pending]}")
                self._log_gate_rejection(
                    'peer_review_quorum', task_id, actor,
                    task.status, new_status, reason)
                raise ValueError(reason)

        # Gate 2: proposal → todo requires GATEKEEPER quorum
        if task.status == 'proposal' and new_status == 'todo':
            reviews = self.get_reviews_for_task(task_id)
            review_map = {r.reviewer: r.verdict for r in reviews}
            for gk in GATEKEEPERS:
                if gk not in review_map:
                    reason = f"Gatekeeper '{gk}' review ontbreekt"
                    self._log_gate_rejection(
                        'gatekeeper_quorum', task_id, actor,
                        task.status, new_status, reason)
                    raise ValueError(reason)
                if review_map[gk] != 'approved':
                    reason = (f"Gatekeeper '{gk}' verdict is "
                              f"'{review_map[gk]}', niet 'approved'")
                    self._log_gate_rejection(
                        'gatekeeper_quorum', task_id, actor,
                        task.status, new_status, reason)
                    raise ValueError(reason)

        # Gate 3: approved → done ALLEEN door user
        if new_status == 'done' and actor != 'user':
            reason = (f"Alleen user mag approved → done zetten, "
                      f"niet '{actor}'")
            self._log_gate_rejection(
                'user_only', task_id, actor,
                task.status, new_status, reason)
            raise ValueError(reason)

        # Gate 4: approved → in_progress (reject) ALLEEN door user
        if task.status == 'approved' and new_status == 'in_progress' \
                and actor != 'user':
            reason = (f"Alleen user mag approved → in_progress zetten, "
                      f"niet '{actor}'")
            self._log_gate_rejection(
                'user_only', task_id, actor,
                task.status, new_status, reason)
            raise ValueError(reason)

        # ── Guardrail v1 gates ──────────────────────────────

        # Gate 5: WIP cap check — target status must not be at capacity
        # Pipeline transitions (draining work) bypass cap checks.
        # Only intake/accumulation transitions are subject to caps.
        if new_status in WIP_CAPS:
            counts = self.get_task_counts_by_status()
            cap = WIP_CAPS[new_status]
            if counts.get(new_status, 0) >= cap:
                reason = (f"WIP cap reached: {new_status} has "
                          f"{counts[new_status]}/{cap} tasks")
                self._log_gate_rejection(
                    'wip_cap', task_id, actor,
                    task.status, new_status, reason)
                raise ValueError(reason)

        # Gate 6: Drain mode — block intake transitions
        # Forbidden in drain mode: todo→in_progress, proposal→todo
        _drain_forbidden = {
            ('todo', 'in_progress'),
            ('proposal', 'todo'),
        }
        if (task.status, new_status) in _drain_forbidden:
            if self.is_drain_mode():
                breaches = self.get_cap_breaches()
                reason = (f"Drain mode active — {task.status}→{new_status} "
                          f"forbidden. Breaches: {breaches}")
                self._log_gate_rejection(
                    'drain_mode', task_id, actor,
                    task.status, new_status, reason)
                raise ValueError(reason)

        # Gate 7: Exit conditions — required for todo→in_progress
        if task.status == 'todo' and new_status == 'in_progress':
            missing = task.get_missing_exit_conditions()
            if missing:
                reason = (f"Exit conditions missing for task #{task_id}: "
                          f"{', '.join(missing)}. "
                          f"Boss must fill these before start.")
                self._log_gate_rejection(
                    'exit_conditions', task_id, actor,
                    task.status, new_status, reason)
                raise ValueError(reason)

        now = _now()
        blocked_since = now if new_status == 'blocked' else None

        self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, blocked_since = ? "
            "WHERE id = ?",
            (new_status, now, blocked_since, task_id),
        )
        self.conn.commit()
        self.log_activity(actor, 'status_changed', task_id,
                          {'from': task.status, 'to': new_status})

    def set_artifact(self, task_id: int, path: str,
                     sha256: Optional[str] = None,
                     git_hash: Optional[str] = None,
                     cmd: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE tasks SET artifact_path = ?, artifact_sha256 = ?, "
            "artifact_git_hash = ?, artifact_cmd = ?, updated_at = ? "
            "WHERE id = ?",
            (path, sha256, git_hash, cmd, _now(), task_id),
        )
        self.conn.commit()

    # ── Reviews ───────────────────────────────────────────

    def create_review(self, task_id: int, reviewer: str) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO task_reviews (task_id, reviewer, verdict) "
            "VALUES (?, ?, 'pending')",
            (task_id, reviewer),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_review(self, task_id: int, reviewer: str, verdict: str,
                      comment_id: Optional[int] = None) -> None:
        if verdict not in REVIEW_VERDICTS:
            raise ValueError(f"Invalid verdict: {verdict}")
        self.conn.execute(
            "UPDATE task_reviews SET verdict = ?, comment_id = ?, "
            "updated_at = ? WHERE task_id = ? AND reviewer = ?",
            (verdict, comment_id, _now(), task_id, reviewer),
        )
        self.conn.commit()

    def get_pending_reviews(self, task_id: int) -> list[TaskReview]:
        rows = self.conn.execute(
            "SELECT * FROM task_reviews WHERE task_id = ? "
            "AND verdict = 'pending'",
            (task_id,),
        ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def get_reviews_for_task(self, task_id: int) -> list[TaskReview]:
        rows = self.conn.execute(
            "SELECT * FROM task_reviews WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def get_tasks_needing_my_review(self, agent: str) -> list[Task]:
        """Tasks in peer_review where I have a pending review."""
        rows = self.conn.execute(
            "SELECT t.* FROM tasks t "
            "JOIN task_reviews r ON t.id = r.task_id "
            "WHERE r.reviewer = ? AND r.verdict = 'pending' "
            "AND t.status = 'peer_review' "
            "ORDER BY t.priority ASC",
            (agent,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_fully_reviewed_tasks(self) -> list[Task]:
        """Tasks in peer_review where ALL reviews are approved."""
        rows = self.conn.execute(
            "SELECT t.* FROM tasks t "
            "WHERE t.status = 'peer_review' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM task_reviews r "
            "  WHERE r.task_id = t.id AND r.verdict != 'approved'"
            ") "
            "AND EXISTS ("
            "  SELECT 1 FROM task_reviews r WHERE r.task_id = t.id"
            ")",
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_proposals_needing_gatekeeper_review(self, agent: str) -> list[Task]:
        """Proposals where this gatekeeper has a pending review.

        ALLEEN voor agents in GATEKEEPERS — andere agents zien proposals niet.
        """
        if agent not in GATEKEEPERS:
            return []
        rows = self.conn.execute(
            "SELECT t.* FROM tasks t "
            "JOIN task_reviews r ON t.id = r.task_id "
            "WHERE r.reviewer = ? AND r.verdict = 'pending' "
            "AND t.status = 'proposal' "
            "ORDER BY t.priority ASC",
            (agent,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_peer_reviews_needing_review(self, agent: str) -> list[Task]:
        """Tasks in peer_review where this agent has a pending review."""
        rows = self.conn.execute(
            "SELECT t.* FROM tasks t "
            "JOIN task_reviews r ON t.id = r.task_id "
            "WHERE r.reviewer = ? AND r.verdict = 'pending' "
            "AND t.status = 'peer_review' "
            "ORDER BY t.priority ASC",
            (agent,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def get_approved_proposals(self) -> list[Task]:
        """Proposals where ALL GATEKEEPERS have approved reviews."""
        # Build query: status='proposal' AND for each gatekeeper
        # a review exists with verdict='approved'
        placeholders = ' AND '.join(
            "EXISTS (SELECT 1 FROM task_reviews r "
            "WHERE r.task_id = t.id AND r.reviewer = ? "
            "AND r.verdict = 'approved')"
            for _ in GATEKEEPERS
        )
        rows = self.conn.execute(
            f"SELECT t.* FROM tasks t "
            f"WHERE t.status = 'proposal' AND {placeholders}",
            tuple(GATEKEEPERS),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def set_proposal_blocked(self, task_id: int) -> None:
        """Update blocked_since op proposal na gatekeeper needs_changes.

        Dit is GEEN state transition — status blijft 'proposal'.
        """
        self.conn.execute(
            "UPDATE tasks SET blocked_since = ? "
            "WHERE id = ? AND status = 'proposal'",
            (_now(), task_id),
        )
        self.conn.commit()

    # ── Comments ──────────────────────────────────────────

    def add_comment(self, task_id: int, agent: str, body: str,
                    comment_type: str = 'comment') -> int:
        cur = self.conn.execute(
            "INSERT INTO comments (task_id, agent, body, comment_type) "
            "VALUES (?, ?, ?, ?)",
            (task_id, agent, body, comment_type),
        )
        self.conn.commit()
        self.log_activity(agent, 'comment_posted', task_id,
                          {'type': comment_type})
        return cur.lastrowid

    def get_comments(self, task_id: int) -> list[Comment]:
        rows = self.conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_comment(r) for r in rows]

    # ── Agent Status ──────────────────────────────────────

    def set_status(self, agent: str, status: str,
                   task_id: Optional[int] = None,
                   note: Optional[str] = None) -> None:
        self.conn.execute(
            "UPDATE agent_status SET status = ?, last_heartbeat = ?, "
            "current_task_id = ?, progress_note = ? WHERE agent = ?",
            (status, _now(), task_id, note, agent),
        )
        self.conn.commit()

    def get_agent_status(self, agent: str) -> Optional[AgentStatus]:
        row = self.conn.execute(
            "SELECT * FROM agent_status WHERE agent = ?", (agent,)
        ).fetchone()
        return self._row_to_agent_status(row) if row else None

    def get_all_agent_statuses(self) -> list[AgentStatus]:
        rows = self.conn.execute(
            "SELECT * FROM agent_status ORDER BY agent"
        ).fetchall()
        return [self._row_to_agent_status(r) for r in rows]

    # ── Activity Log ──────────────────────────────────────

    def log_activity(self, agent: str, action: str,
                     task_id: Optional[int] = None,
                     details: Optional[dict] = None) -> None:
        self.conn.execute(
            "INSERT INTO activity_log (agent, action, task_id, details) "
            "VALUES (?, ?, ?, ?)",
            (agent, action, task_id,
             json.dumps(details) if details else None),
        )
        self.conn.commit()

    def get_recent_activity(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Stuck detection ───────────────────────────────────

    def get_stuck_tasks(self, hours: int = 24) -> list[Task]:
        """Tasks blocked or in_progress for more than N hours."""
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status IN ('in_progress', 'blocked') "
            "AND updated_at < datetime('now', ? || ' hours')",
            (f'-{hours}',),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    # ── Guardrail v1 — Flow Control ─────────────────────

    def get_task_counts_by_status(self) -> dict[str, int]:
        """Canonical task counts per status. Source of truth for WIP caps."""
        counts: dict[str, int] = {}
        for status in ALL_STATUSES:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ?", (status,)
            ).fetchone()
            counts[status] = row[0]
        return counts

    def is_drain_mode(self) -> bool:
        """True if any WIP cap is hit. Evaluated every heartbeat cycle."""
        counts = self.get_task_counts_by_status()
        return any(
            counts.get(status, 0) >= cap
            for status, cap in WIP_CAPS.items()
        )

    def get_cap_breaches(self) -> dict[str, tuple[int, int]]:
        """Return {status: (count, cap)} for every breached/hit cap."""
        counts = self.get_task_counts_by_status()
        return {
            status: (counts.get(status, 0), cap)
            for status, cap in WIP_CAPS.items()
            if counts.get(status, 0) >= cap
        }

    # ── Agent Performance ─────────────────────────────────

    def get_agent_task_counts(self) -> dict[str, dict[str, int]]:
        """Per-agent task counts by status.

        Returns:
            {agent: {status: count}} for all agents with tasks.
        """
        rows = self.conn.execute(
            "SELECT assigned_to, status, COUNT(*) as cnt "
            "FROM tasks GROUP BY assigned_to, status"
        ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            agent = row['assigned_to']
            if agent not in result:
                result[agent] = {}
            result[agent][row['status']] = row['cnt']
        return result

    def get_agent_review_counts(self, hours: int = 24) -> dict[str, int]:
        """Per-agent review count in the last N hours.

        Returns:
            {reviewer: count} for reviewers with verdicts != 'pending'.
        """
        rows = self.conn.execute(
            "SELECT reviewer, COUNT(*) as cnt FROM task_reviews "
            "WHERE verdict != 'pending' "
            "AND updated_at >= datetime('now', ? || ' hours') "
            "GROUP BY reviewer",
            (f'-{hours}',),
        ).fetchall()
        return {row['reviewer']: row['cnt'] for row in rows}

    # ── Gate Rejections ─────────────────────────────────

    def get_gate_rejections(self, hours: int = 24,
                            gate: Optional[str] = None,
                            task_id: Optional[int] = None,
                            limit: int = 100) -> list[GateRejection]:
        """Query gate rejections with optional filters."""
        clauses = ["created_at >= datetime('now', ? || ' hours')"]
        params: list = [f'-{hours}']

        if gate:
            clauses.append("gate = ?")
            params.append(gate)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)

        where = " AND ".join(clauses)
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM gate_rejections "
            f"WHERE {where} "
            f"ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [self._row_to_gate_rejection(r) for r in rows]

    def get_gate_rejection_counts(self, hours: int = 24) -> dict[str, int]:
        """Count gate rejections by gate type over the last N hours."""
        rows = self.conn.execute(
            "SELECT gate, COUNT(*) as cnt FROM gate_rejections "
            "WHERE created_at >= datetime('now', ? || ' hours') "
            "GROUP BY gate ORDER BY cnt DESC",
            (f'-{hours}',),
        ).fetchall()
        return {row['gate']: row['cnt'] for row in rows}

    def set_exit_conditions(self, task_id: int,
                            exit_conditions: dict) -> None:
        """Set exit conditions on an existing task. Boss fills at proposal."""
        self.conn.execute(
            "UPDATE tasks SET exit_conditions = ?, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(exit_conditions), _now(), task_id),
        )
        self.conn.commit()

    # ── Cycle Metrics ──────────────────────────────────────

    def save_cycle_metrics(self, stats: dict) -> int:
        """Persist a heartbeat cycle's stats for trend analysis.

        Args:
            stats: dict with keys: cycle, reviews, tasks, promotions,
                   errors, drain_mode, drain_cycles, agent_count,
                   cycle_duration_s, skipped_agents, retries,
                   agent_timings.
        Returns:
            Row ID of inserted metric.
        """
        agent_timings = stats.get('agent_timings', {})
        timings_json = json.dumps(agent_timings) if agent_timings else '{}'
        cur = self.conn.execute(
            "INSERT INTO cycle_metrics "
            "(cycle, reviews, tasks, promotions, errors, "
            " drain_mode, drain_cycles, agent_count, cycle_duration_s,"
            " skipped_agents, retries, agent_timings) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stats.get('cycle', 0),
                stats.get('reviews', 0),
                stats.get('tasks', 0),
                stats.get('promotions', 0),
                stats.get('errors', 0),
                1 if stats.get('drain_mode') else 0,
                stats.get('drain_cycles', 0),
                stats.get('agent_count', 0),
                stats.get('cycle_duration_s', 0.0),
                stats.get('skipped_agents', 0),
                stats.get('retries', 0),
                timings_json,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_cycle_metrics(self, limit: int = 100) -> list[CycleMetrics]:
        """Retrieve recent cycle metrics, newest first."""
        rows = self.conn.execute(
            "SELECT * FROM cycle_metrics "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_cycle_metrics(r) for r in rows]

    def get_cycle_metrics_since(self, hours: int = 24) -> list[CycleMetrics]:
        """Retrieve cycle metrics from the last N hours."""
        rows = self.conn.execute(
            "SELECT * FROM cycle_metrics "
            "WHERE created_at >= datetime('now', ? || ' hours') "
            "ORDER BY created_at ASC",
            (f'-{hours}',),
        ).fetchall()
        return [self._row_to_cycle_metrics(r) for r in rows]

    def get_cycle_metrics_stats(self, hours: int = 24) -> dict:
        """Aggregate cycle metrics over a time window.

        Returns dict with:
            cycles: int — number of cycles
            total_tasks, total_reviews, total_errors: int
            avg_duration_s, min_duration_s, max_duration_s: float
            drain_pct: float — percentage of cycles in drain mode
            avg_agent_time: dict[str, float] — per-agent avg execution time
            slowest_agent: str | None — agent with highest avg time
        """
        metrics = self.get_cycle_metrics_since(hours=hours)
        if not metrics:
            return {
                'cycles': 0,
                'total_tasks': 0, 'total_reviews': 0, 'total_errors': 0,
                'avg_duration_s': 0.0, 'min_duration_s': 0.0,
                'max_duration_s': 0.0,
                'drain_pct': 0.0,
                'avg_agent_time': {},
                'slowest_agent': None,
            }

        durations = [m.cycle_duration_s for m in metrics
                     if m.cycle_duration_s > 0]
        drain_count = sum(1 for m in metrics if m.drain_mode)

        # Aggregate per-agent timings across all cycles
        agent_totals: dict[str, list[float]] = {}
        for m in metrics:
            for agent, elapsed in m.agent_timings.items():
                agent_totals.setdefault(agent, []).append(elapsed)

        avg_agent_time = {
            agent: sum(times) / len(times)
            for agent, times in agent_totals.items()
        }
        slowest = max(avg_agent_time, key=avg_agent_time.get) \
            if avg_agent_time else None

        return {
            'cycles': len(metrics),
            'total_tasks': sum(m.tasks for m in metrics),
            'total_reviews': sum(m.reviews for m in metrics),
            'total_errors': sum(m.errors for m in metrics),
            'avg_duration_s': (
                sum(durations) / len(durations) if durations else 0.0
            ),
            'min_duration_s': min(durations) if durations else 0.0,
            'max_duration_s': max(durations) if durations else 0.0,
            'drain_pct': (
                drain_count / len(metrics) * 100 if metrics else 0.0
            ),
            'avg_agent_time': avg_agent_time,
            'slowest_agent': slowest,
        }

    # ── Summary ───────────────────────────────────────────

    def get_status_summary(self) -> dict:
        """Dashboard summary: task counts by status, agent statuses."""
        summary = {'tasks': {}, 'agents': {}, 'goals': []}
        for status in ALL_STATUSES:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = ?", (status,)
            ).fetchone()
            summary['tasks'][status] = row[0]

        for agent_st in self.get_all_agent_statuses():
            summary['agents'][agent_st.agent] = {
                'status': agent_st.status,
                'last_heartbeat': agent_st.last_heartbeat,
            }

        for goal in self.get_goals():
            tasks = self.get_tasks_by_goal(goal.id)
            done = sum(1 for t in tasks if t.status == 'done')
            summary['goals'].append({
                'id': goal.id,
                'title': goal.title,
                'total_tasks': len(tasks),
                'done': done,
            })

        return summary

    # ── Row converters ────────────────────────────────────

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> Goal:
        return Goal(
            id=row['id'], title=row['title'],
            description=row['description'] or '',
            agents=json.loads(row['agents']),
            tasks_per_day=row['tasks_per_day'],
            status=row['status'],
            created_at=row['created_at'] or '',
            updated_at=row['updated_at'] or '',
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        ec_raw = row['exit_conditions']
        ec = json.loads(ec_raw) if ec_raw else None
        return Task(
            id=row['id'], goal_id=row['goal_id'],
            title=row['title'], description=row['description'] or '',
            assigned_to=row['assigned_to'], status=row['status'],
            priority=row['priority'], created_by=row['created_by'],
            created_at=row['created_at'] or '',
            updated_at=row['updated_at'] or '',
            blocked_since=row['blocked_since'],
            artifact_path=row['artifact_path'],
            artifact_sha256=row['artifact_sha256'],
            artifact_git_hash=row['artifact_git_hash'],
            artifact_cmd=row['artifact_cmd'],
            exit_conditions=ec,
        )

    @staticmethod
    def _row_to_comment(row: sqlite3.Row) -> Comment:
        return Comment(
            id=row['id'], task_id=row['task_id'],
            agent=row['agent'], body=row['body'],
            comment_type=row['comment_type'],
            created_at=row['created_at'] or '',
        )

    @staticmethod
    def _row_to_review(row: sqlite3.Row) -> TaskReview:
        return TaskReview(
            id=row['id'], task_id=row['task_id'],
            reviewer=row['reviewer'], verdict=row['verdict'],
            comment_id=row['comment_id'],
            created_at=row['created_at'] or '',
            updated_at=row['updated_at'] or '',
        )

    @staticmethod
    def _row_to_agent_status(row: sqlite3.Row) -> AgentStatus:
        return AgentStatus(
            agent=row['agent'], status=row['status'],
            last_heartbeat=row['last_heartbeat'],
            current_task_id=row['current_task_id'],
            progress_note=row['progress_note'],
        )

    @staticmethod
    def _row_to_cycle_metrics(row: sqlite3.Row) -> CycleMetrics:
        # Parse agent_timings JSON — graceful fallback to empty dict
        timings_raw = row['agent_timings'] if 'agent_timings' in row.keys() else '{}'
        try:
            agent_timings = json.loads(timings_raw) if timings_raw else {}
        except (json.JSONDecodeError, TypeError):
            agent_timings = {}
        return CycleMetrics(
            id=row['id'], cycle=row['cycle'],
            reviews=row['reviews'], tasks=row['tasks'],
            promotions=row['promotions'], errors=row['errors'],
            drain_mode=bool(row['drain_mode']),
            drain_cycles=row['drain_cycles'],
            agent_count=row['agent_count'],
            cycle_duration_s=row['cycle_duration_s'],
            skipped_agents=row['skipped_agents'] or 0,
            retries=row['retries'] or 0,
            created_at=row['created_at'] or '',
            agent_timings=agent_timings,
        )

    @staticmethod
    def _row_to_gate_rejection(row: sqlite3.Row) -> GateRejection:
        return GateRejection(
            id=row['id'], gate=row['gate'],
            task_id=row['task_id'], actor=row['actor'],
            from_status=row['from_status'], to_status=row['to_status'],
            reason=row['reason'],
            created_at=row['created_at'] or '',
        )
