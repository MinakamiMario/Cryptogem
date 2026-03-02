"""Tests for lab/db.py — SQLite schema, CRUD, state machine enforcement."""
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import EXIT_CONDITIONS, VALID_TRANSITIONS, safe_write_check
from lab.db import LabDB


def _set_ec(db, task_id):
    """Set valid exit conditions on a task for testing."""
    db.set_exit_conditions(task_id, {
        'scope': 'reports/lab/test_*',
        'dod': 'Test report',
        'artifact': 'reports/lab/test.json',
        'write_surface': "['lab/lab.db', 'reports/lab/']",
        'stop_condition': 'Error → blocked',
    })


@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like DB in a temp directory."""
    db_path = tmp_path / 'test_lab.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def goal_id(db):
    """Create a default goal and return its ID."""
    return db.create_goal(
        title="Reduce DD below 15%",
        agents=['risk_governor', 'robustness_auditor', 'edge_analyst'],
        description="Test goal",
        tasks_per_day=3,
    )


class TestSchema:
    """Database schema and pragmas."""

    def test_wal_mode(self, db):
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == 'wal'

    def test_foreign_keys_on(self, db):
        fk = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_busy_timeout(self, db):
        timeout = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000

    def test_tables_exist(self, db):
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "ORDER BY name"
        ).fetchall()
        names = {r['name'] for r in tables}
        expected = {'goals', 'tasks', 'task_reviews', 'comments',
                    'agent_status', 'activity_log'}
        assert expected.issubset(names)

    def test_agent_status_seeded(self, db):
        statuses = db.get_all_agent_statuses()
        assert len(statuses) == 10  # all 10 agents
        for s in statuses:
            assert s.status == 'idle'

    def test_idempotent_init(self, db):
        """init_schema() can be called multiple times safely."""
        db.init_schema()
        db.init_schema()
        statuses = db.get_all_agent_statuses()
        assert len(statuses) == 10


class TestGoals:
    """Goal CRUD operations."""

    def test_create_goal(self, db):
        gid = db.create_goal(
            title="Test Goal",
            agents=['boss', 'edge_analyst'],
        )
        assert gid > 0

    def test_get_goal(self, db, goal_id):
        goal = db.get_goal(goal_id)
        assert goal is not None
        assert goal.title == "Reduce DD below 15%"
        assert goal.agents == ['risk_governor', 'robustness_auditor',
                                'edge_analyst']
        assert goal.tasks_per_day == 3
        assert goal.status == 'active'

    def test_get_goals_active(self, db, goal_id):
        goals = db.get_goals(status='active')
        assert len(goals) == 1
        assert goals[0].id == goal_id

    def test_get_goals_empty(self, db):
        goals = db.get_goals(status='completed')
        assert goals == []

    def test_goal_agents_json(self, db, goal_id):
        """Agents stored as JSON, parsed back to list."""
        row = db.conn.execute(
            "SELECT agents FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        parsed = json.loads(row['agents'])
        assert isinstance(parsed, list)
        assert 'risk_governor' in parsed

    def test_get_goal_agents(self, db, goal_id):
        agents = db.get_goal_agents(goal_id)
        assert agents == ['risk_governor', 'robustness_auditor', 'edge_analyst']

    def test_get_goal_agents_missing(self, db):
        agents = db.get_goal_agents(9999)
        assert agents == []


class TestTasks:
    """Task CRUD and queries."""

    def test_create_task(self, db, goal_id):
        tid = db.create_task(
            goal_id=goal_id,
            title="Test task",
            assigned_to='risk_governor',
            created_by='boss',
        )
        assert tid > 0

    def test_get_task(self, db, goal_id):
        tid = db.create_task(goal_id, "A task", 'edge_analyst', 'boss')
        task = db.get_task(tid)
        assert task is not None
        assert task.title == "A task"
        assert task.assigned_to == 'edge_analyst'
        assert task.status == 'backlog'
        assert task.priority == 5

    def test_get_task_missing(self, db):
        assert db.get_task(9999) is None

    def test_get_my_tasks(self, db, goal_id):
        t1 = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        t2 = db.create_task(goal_id, "T2", 'edge_analyst', 'boss')
        t3 = db.create_task(goal_id, "T3", 'risk_governor', 'boss')
        # All start as backlog, move T1 and T2 to todo
        db.transition(t1, 'todo', actor='user')
        db.transition(t2, 'todo', actor='user')
        tasks = db.get_my_tasks('edge_analyst', status='todo')
        assert len(tasks) == 2
        assert all(t.assigned_to == 'edge_analyst' for t in tasks)

    def test_get_tasks_by_status(self, db, goal_id):
        t1 = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        t2 = db.create_task(goal_id, "T2", 'risk_governor', 'boss')
        tasks = db.get_tasks_by_status('backlog')
        assert len(tasks) == 2

    def test_get_tasks_by_goal(self, db, goal_id):
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_task(goal_id, "T2", 'risk_governor', 'boss')
        tasks = db.get_tasks_by_goal(goal_id)
        assert len(tasks) == 2

    def test_count_tasks_today(self, db, goal_id):
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_task(goal_id, "T2", 'risk_governor', 'boss')
        assert db.count_tasks_today(goal_id) == 2

    def test_set_artifact(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.set_artifact(
            tid, '/reports/lab/test.json',
            sha256='abc123', git_hash='def456', cmd='make check',
        )
        task = db.get_task(tid)
        assert task.artifact_path == '/reports/lab/test.json'
        assert task.artifact_sha256 == 'abc123'
        assert task.artifact_git_hash == 'def456'
        assert task.artifact_cmd == 'make check'

    def test_task_priority_ordering(self, db, goal_id):
        t1 = db.create_task(goal_id, "Low", 'edge_analyst', 'boss',
                            priority=10)
        t2 = db.create_task(goal_id, "High", 'edge_analyst', 'boss',
                            priority=1)
        # Move both to todo
        db.transition(t1, 'todo', actor='user')
        db.transition(t2, 'todo', actor='user')
        tasks = db.get_my_tasks('edge_analyst', status='todo')
        assert tasks[0].title == "High"  # priority 1 first
        assert tasks[1].title == "Low"   # priority 10 second


class TestTransitions:
    """State machine enforcement via transition()."""

    def test_valid_backlog_to_todo(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        assert db.get_task(tid).status == 'todo'

    def test_valid_full_path(self, db, goal_id):
        """Walk the full happy path: backlog → todo → in_progress →
        peer_review → review → approved → done."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')

        # backlog → todo
        db.transition(tid, 'todo', actor='user')
        assert db.get_task(tid).status == 'todo'

        # todo → in_progress
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        assert db.get_task(tid).status == 'in_progress'

        # in_progress → peer_review
        db.transition(tid, 'peer_review', actor='edge_analyst')
        assert db.get_task(tid).status == 'peer_review'

        # Create and approve all reviews before promotion
        db.create_review(tid, reviewer='risk_governor')
        db.create_review(tid, reviewer='robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'approved')

        # peer_review → review (boss promotes after all reviews approved)
        db.transition(tid, 'review', actor='boss')
        assert db.get_task(tid).status == 'review'

        # review → approved (boss auto-promote)
        db.transition(tid, 'approved', actor='boss')
        assert db.get_task(tid).status == 'approved'

        # approved → done (user only)
        db.transition(tid, 'done', actor='user')
        assert db.get_task(tid).status == 'done'

    def test_invalid_backlog_to_in_progress(self, db, goal_id):
        """Cannot skip: backlog → in_progress."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_invalid_todo_to_peer_review(self, db, goal_id):
        """Cannot skip: todo → peer_review."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'peer_review', actor='edge_analyst')

    def test_invalid_reverse_done_to_review(self, db, goal_id):
        """Cannot go backwards from done (terminal state)."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        db.transition(tid, 'done', actor='user')
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'review', actor='user')

    def test_blocked_and_unblock(self, db, goal_id):
        """in_progress → blocked → in_progress."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'blocked', actor='edge_analyst')
        task = db.get_task(tid)
        assert task.status == 'blocked'
        assert task.blocked_since is not None
        # Unblock
        db.transition(tid, 'in_progress', actor='boss')
        task = db.get_task(tid)
        assert task.status == 'in_progress'
        assert task.blocked_since is None

    def test_transition_missing_task(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.transition(9999, 'todo', actor='user')

    def test_transition_logs_activity(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        activity = db.get_recent_activity(limit=5)
        # Should have both task_created and status_changed
        actions = [a['action'] for a in activity]
        assert 'status_changed' in actions
        assert 'task_created' in actions

    def test_all_valid_transitions_covered(self):
        """Verify VALID_TRANSITIONS matrix completeness."""
        assert 'proposal' in VALID_TRANSITIONS
        assert 'backlog' in VALID_TRANSITIONS
        assert 'todo' in VALID_TRANSITIONS
        assert 'in_progress' in VALID_TRANSITIONS
        assert 'peer_review' in VALID_TRANSITIONS
        assert 'review' in VALID_TRANSITIONS
        assert 'approved' in VALID_TRANSITIONS
        assert 'blocked' in VALID_TRANSITIONS
        # done is terminal — explicitly in transitions with empty list
        assert 'done' in VALID_TRANSITIONS
        assert VALID_TRANSITIONS['done'] == []


class TestBossPromotionGate:
    """Boss promotion check: peer_review → review requires all reviews."""

    def test_promote_blocked_with_pending_reviews(self, db, goal_id):
        """Cannot promote if reviews are still pending."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        # Create reviews
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        # Only approve one
        db.update_review(tid, 'risk_governor', 'approved')
        with pytest.raises(ValueError, match="reviews pending"):
            db.transition(tid, 'review', actor='boss')

    def test_promote_allowed_when_all_approved(self, db, goal_id):
        """Can promote when ALL reviews are approved."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'approved')
        # Should not raise
        db.transition(tid, 'review', actor='boss')
        assert db.get_task(tid).status == 'review'

    def test_promote_no_reviews_needed(self, db, goal_id):
        """Promote works when no reviews exist (no peers assigned)."""
        # This shouldn't happen in practice, but the query handles it:
        # get_fully_reviewed_tasks requires EXISTS(reviews) AND
        # NOT EXISTS(non-approved)
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        # No reviews created — transition should succeed
        # (no pending reviews = all zero reviews are "approved")
        db.transition(tid, 'review', actor='boss')
        assert db.get_task(tid).status == 'review'

    def test_rejection_sends_back(self, db, goal_id):
        """Rejected review: task can go back to in_progress."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'rejected')
        # peer_review → in_progress (rejection)
        db.transition(tid, 'in_progress', actor='boss')
        assert db.get_task(tid).status == 'in_progress'


class TestReviews:
    """Review CRUD operations."""

    def test_create_review(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        rid = db.create_review(tid, 'risk_governor')
        assert rid > 0

    def test_unique_review_per_agent(self, db, goal_id):
        """UNIQUE(task_id, reviewer) — second insert is ignored."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'risk_governor')  # INSERT OR IGNORE
        reviews = db.get_reviews_for_task(tid)
        assert len(reviews) == 1

    def test_update_review(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        reviews = db.get_reviews_for_task(tid)
        assert reviews[0].verdict == 'approved'

    def test_invalid_verdict(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_review(tid, 'risk_governor')
        with pytest.raises(ValueError, match="Invalid verdict"):
            db.update_review(tid, 'risk_governor', 'invalid_verdict')

    def test_get_pending_reviews(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        pending = db.get_pending_reviews(tid)
        assert len(pending) == 1
        assert pending[0].reviewer == 'robustness_auditor'

    def test_get_tasks_needing_my_review(self, db, goal_id):
        t1 = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        t2 = db.create_task(goal_id, "T2", 'risk_governor', 'boss')
        # Move both to peer_review
        for tid in [t1, t2]:
            db.transition(tid, 'todo', actor='user')
            _set_ec(db, tid)
            db.transition(tid, 'in_progress', actor='edge_analyst')
            db.transition(tid, 'peer_review', actor='edge_analyst')
        # Create reviews for robustness_auditor
        db.create_review(t1, 'robustness_auditor')
        db.create_review(t2, 'robustness_auditor')
        tasks = db.get_tasks_needing_my_review('robustness_auditor')
        assert len(tasks) == 2

    def test_get_fully_reviewed_tasks(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        # Create and approve reviews
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        # Not yet fully reviewed
        assert db.get_fully_reviewed_tasks() == []
        # Approve all
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'approved')
        fully = db.get_fully_reviewed_tasks()
        assert len(fully) == 1
        assert fully[0].id == tid

    def test_review_with_comment(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_review(tid, 'risk_governor')
        cid = db.add_comment(tid, 'risk_governor', "Looks good", 'review')
        db.update_review(tid, 'risk_governor', 'approved', comment_id=cid)
        reviews = db.get_reviews_for_task(tid)
        assert reviews[0].comment_id == cid


class TestComments:
    """Comment CRUD operations."""

    def test_add_and_get_comments(self, db, goal_id):
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.add_comment(tid, 'edge_analyst', "Working on it", 'comment')
        db.add_comment(tid, 'risk_governor', "Review note", 'review')
        comments = db.get_comments(tid)
        assert len(comments) == 2
        assert comments[0].body == "Working on it"
        assert comments[1].comment_type == 'review'


class TestAgentStatus:
    """Agent status tracking."""

    def test_set_and_get_status(self, db):
        db.set_status('boss', 'working', task_id=1, note="Processing")
        st = db.get_agent_status('boss')
        assert st.status == 'working'
        assert st.current_task_id == 1
        assert st.progress_note == "Processing"
        assert st.last_heartbeat is not None

    def test_get_all_statuses(self, db):
        statuses = db.get_all_agent_statuses()
        assert len(statuses) == 10
        names = {s.agent for s in statuses}
        assert 'boss' in names
        assert 'infra_guardian' in names


class TestActivityLog:
    """Activity logging and audit trail."""

    def test_log_and_retrieve(self, db):
        db.log_activity('boss', 'test_action', task_id=1,
                        details={'key': 'value'})
        activity = db.get_recent_activity(limit=1)
        assert len(activity) == 1
        assert activity[0]['agent'] == 'boss'
        assert activity[0]['action'] == 'test_action'

    def test_task_creation_logs(self, db, goal_id):
        """Creating a task automatically logs activity."""
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        activity = db.get_recent_activity(limit=5)
        assert any(a['action'] == 'task_created' for a in activity)


class TestSummary:
    """Dashboard summary."""

    def test_status_summary_empty(self, db):
        summary = db.get_status_summary()
        assert 'tasks' in summary
        assert 'agents' in summary
        assert 'goals' in summary
        assert summary['tasks']['backlog'] == 0

    def test_status_summary_with_data(self, db, goal_id):
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_task(goal_id, "T2", 'risk_governor', 'boss')
        summary = db.get_status_summary()
        assert summary['tasks']['backlog'] == 2
        assert len(summary['goals']) == 1
        assert summary['goals'][0]['total_tasks'] == 2


class TestWriteAllowlist:
    """safe_write_check() enforcement."""

    def test_allowed_lab_db(self):
        from lab.config import REPO_ROOT
        # Should NOT raise
        safe_write_check(REPO_ROOT / 'lab' / 'lab.db')

    def test_allowed_reports_lab(self):
        from lab.config import REPO_ROOT
        safe_write_check(REPO_ROOT / 'reports' / 'lab' / 'test.json')

    def test_blocked_trading_bot(self):
        from lab.config import REPO_ROOT
        with pytest.raises(PermissionError, match="Lab write blocked"):
            safe_write_check(REPO_ROOT / 'trading_bot' / 'config.py')

    def test_blocked_outside_repo(self):
        with pytest.raises(PermissionError):
            safe_write_check('/tmp/evil.py')


class TestInitialStatus:
    """Task creation with different initial statuses."""

    def test_default_creates_backlog(self, db, goal_id):
        """Default create_task still creates in backlog."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        task = db.get_task(tid)
        assert task.status == 'backlog'

    def test_create_with_todo_status(self, db, goal_id):
        """Can create tasks directly in 'todo'."""
        tid = db.create_task(
            goal_id, "T1", 'edge_analyst', 'boss',
            initial_status='todo',
        )
        task = db.get_task(tid)
        assert task.status == 'todo'

    def test_create_with_proposal_status(self, db, goal_id):
        """Boss creates proposals for gatekeeper review."""
        tid = db.create_task(
            goal_id, "T1", 'edge_analyst', 'boss',
            initial_status='proposal',
        )
        task = db.get_task(tid)
        assert task.status == 'proposal'

    def test_invalid_initial_status_rejected(self, db, goal_id):
        """Only 'backlog', 'todo', and 'proposal' are valid."""
        with pytest.raises(ValueError, match="initial_status"):
            db.create_task(
                goal_id, "T1", 'edge_analyst', 'boss',
                initial_status='in_progress',
            )

    def test_initial_status_logged_in_activity(self, db, goal_id):
        """Activity log captures the initial status."""
        db.create_task(
            goal_id, "T1", 'edge_analyst', 'boss',
            initial_status='proposal',
        )
        activity = db.get_recent_activity(limit=5)
        task_created = [a for a in activity if a['action'] == 'task_created']
        assert len(task_created) >= 1
        details = json.loads(task_created[0]['details'])
        assert details['status'] == 'proposal'


class TestProposalQuorum:
    """Governance: proposal → todo requires BOTH gatekeepers approved."""

    def test_proposal_to_todo_blocked_without_reviews(self, db, goal_id):
        """proposal → todo BLOCKED zonder reviews."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        with pytest.raises(ValueError, match="review ontbreekt"):
            db.transition(tid, 'todo', actor='boss')

    def test_proposal_to_todo_blocked_one_gatekeeper(self, db, goal_id):
        """proposal → todo BLOCKED met 1/2 gatekeepers approved."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        # robustness_auditor review ontbreekt
        with pytest.raises(ValueError, match="review ontbreekt"):
            db.transition(tid, 'todo', actor='boss')

    def test_proposal_to_todo_blocked_not_approved(self, db, goal_id):
        """proposal → todo BLOCKED als gatekeeper niet approved."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'needs_changes')
        with pytest.raises(ValueError, match="niet 'approved'"):
            db.transition(tid, 'todo', actor='boss')

    def test_proposal_to_todo_ok_both_approved(self, db, goal_id):
        """proposal → todo OK met 2/2 gatekeepers approved."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'approved')
        db.transition(tid, 'todo', actor='boss')
        assert db.get_task(tid).status == 'todo'

    def test_approved_to_done_blocked_if_not_user(self, db, goal_id):
        """approved → done BLOCKED als actor != 'user'."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        with pytest.raises(ValueError, match="Alleen user"):
            db.transition(tid, 'done', actor='boss')

    def test_approved_to_done_ok_user(self, db, goal_id):
        """approved → done OK als actor == 'user'."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        db.transition(tid, 'done', actor='user')
        assert db.get_task(tid).status == 'done'

    def test_done_is_terminal(self, db, goal_id):
        """done is terminal: geen transitions uit."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        db.transition(tid, 'done', actor='user')
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'in_progress', actor='user')

    def test_review_to_approved_ok_boss(self, db, goal_id):
        """review → approved OK (boss auto-promote)."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        assert db.get_task(tid).status == 'approved'

    def test_approved_to_in_progress_user_reject(self, db, goal_id):
        """approved → in_progress OK (user reject)."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        db.transition(tid, 'in_progress', actor='user')
        assert db.get_task(tid).status == 'in_progress'

    def test_approved_to_in_progress_blocked_not_user(self, db, goal_id):
        """approved → in_progress BLOCKED als actor != 'user'."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')
        _set_ec(db, tid)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')
        with pytest.raises(ValueError, match="Alleen user"):
            db.transition(tid, 'in_progress', actor='boss')

    def test_proposals_needing_gatekeeper_review_only_gatekeepers(self, db, goal_id):
        """ALLEEN gatekeepers zien proposals."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        # Gatekeeper sees proposals
        assert len(db.get_proposals_needing_gatekeeper_review('risk_governor')) == 1
        assert len(db.get_proposals_needing_gatekeeper_review('robustness_auditor')) == 1
        # Non-gatekeeper sees nothing
        assert db.get_proposals_needing_gatekeeper_review('edge_analyst') == []
        assert db.get_proposals_needing_gatekeeper_review('boss') == []

    def test_get_approved_proposals(self, db, goal_id):
        """get_approved_proposals returns only fully-approved proposals."""
        t1 = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                            initial_status='proposal')
        t2 = db.create_task(goal_id, "T2", 'risk_governor', 'boss',
                            initial_status='proposal')
        # Approve T1 fully
        db.create_review(t1, 'risk_governor')
        db.create_review(t1, 'robustness_auditor')
        db.update_review(t1, 'risk_governor', 'approved')
        db.update_review(t1, 'robustness_auditor', 'approved')
        # T2 only partially approved
        db.create_review(t2, 'risk_governor')
        db.create_review(t2, 'robustness_auditor')
        db.update_review(t2, 'risk_governor', 'approved')
        # Only T1 should appear
        approved = db.get_approved_proposals()
        assert len(approved) == 1
        assert approved[0].id == t1

    def test_set_proposal_blocked(self, db, goal_id):
        """set_proposal_blocked updates blocked_since without state change."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal')
        assert db.get_task(tid).blocked_since is None
        db.set_proposal_blocked(tid)
        task = db.get_task(tid)
        assert task.status == 'proposal'  # status unchanged
        assert task.blocked_since is not None

    def test_boss_generates_proposals(self, db, goal_id):
        """Boss generates tasks in 'proposal', not 'todo'."""
        from lab.agents.boss import BossAgent
        notifier = MagicMock()
        notifier.enabled = False
        agent = BossAgent(db, notifier)

        created = agent.generate_tasks()
        assert created > 0

        tasks = db.get_tasks_by_goal(goal_id)
        for task in tasks:
            assert task.status == 'proposal', (
                f"Task '{task.title}' should be 'proposal', got '{task.status}'"
            )

    def test_boss_creates_gatekeeper_reviews(self, db, goal_id):
        """Boss creates review entries for GATEKEEPERS on proposals."""
        from lab.agents.boss import BossAgent
        notifier = MagicMock()
        notifier.enabled = False
        agent = BossAgent(db, notifier)

        agent.generate_tasks()
        tasks = db.get_tasks_by_goal(goal_id)
        assert len(tasks) > 0

        for task in tasks:
            reviews = db.get_reviews_for_task(task.id)
            reviewers = {r.reviewer for r in reviews}
            assert 'risk_governor' in reviewers
            assert 'robustness_auditor' in reviewers


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
