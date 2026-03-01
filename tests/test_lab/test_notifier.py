"""Tests for lab.notifier callback handlers and dashboard output."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lab.db import LabDB
from lab.notifier import LabNotifier


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = LabDB(db_path=tmp_path / 'test.db')
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def goal_id(db):
    return db.create_goal(
        title='Test goal', agents=['edge_analyst'],
        description='test', tasks_per_day=2,
    )


def _make_notifier() -> LabNotifier:
    """Create a testable notifier with mocked TG internals."""
    n = LabNotifier(enabled=False)
    # Monkey-patch internals so handlers work without real Telegram
    n.enabled = True
    n._token = 'fake-token'
    n._base_url = 'https://fake'
    n._last_update_id = 0
    n._pending_messages = {}
    n._send = MagicMock(return_value=123)
    n._edit_message = MagicMock()
    n._answer_callback = MagicMock()
    return n


def _task_to_approved(db, goal_id: int) -> int:
    """Create a task and walk it to 'approved' status."""
    tid = db.create_task(goal_id, 'Test task', 'edge_analyst', 'boss',
                         initial_status='proposal')
    # Gatekeeper reviews for quorum
    db.create_review(tid, 'risk_governor')
    db.create_review(tid, 'robustness_auditor')
    db.update_review(tid, 'risk_governor', 'approved')
    db.update_review(tid, 'robustness_auditor', 'approved')
    db.transition(tid, 'todo', actor='boss')
    db.transition(tid, 'in_progress', actor='edge_analyst')
    db.transition(tid, 'peer_review', actor='edge_analyst')
    # Peer reviews
    db.create_review(tid, 'risk_governor')
    db.create_review(tid, 'robustness_auditor')
    db.update_review(tid, 'risk_governor', 'approved')
    db.update_review(tid, 'robustness_auditor', 'approved')
    db.transition(tid, 'review', actor='boss')
    db.transition(tid, 'approved', actor='boss')
    return tid


# ── Approve tests ─────────────────────────────────────────

class TestApprove:

    def test_approve_ok(self, db, goal_id):
        """approved → done via Telegram button."""
        n = _make_notifier()
        tid = _task_to_approved(db, goal_id)
        assert db.get_task(tid).status == 'approved'

        result = n._handle_approve(db, tid, 'cb_123', 999)

        assert result == 1
        assert db.get_task(tid).status == 'done'
        n._answer_callback.assert_called_once()
        n._edit_message.assert_called_once()
        call_text = n._edit_message.call_args[0][1]
        assert 'GOEDGEKEURD' in call_text

    def test_approve_already_done(self, db, goal_id):
        """Approve on already-done task — idempotent, no crash."""
        n = _make_notifier()
        tid = _task_to_approved(db, goal_id)
        db.transition(tid, 'done', actor='user')
        assert db.get_task(tid).status == 'done'

        result = n._handle_approve(db, tid, 'cb_123', 999)

        assert result == 0
        assert db.get_task(tid).status == 'done'
        n._answer_callback.assert_called_once()
        assert 'al goedgekeurd' in n._answer_callback.call_args[0][1]

    def test_approve_wrong_status(self, db, goal_id):
        """Approve on task in wrong status — no crash, informative callback."""
        n = _make_notifier()
        tid = db.create_task(goal_id, 'Todo task', 'edge_analyst', 'boss',
                             initial_status='todo')
        assert db.get_task(tid).status == 'todo'

        result = n._handle_approve(db, tid, 'cb_123', 999)

        assert result == 0
        assert db.get_task(tid).status == 'todo'  # unchanged
        n._answer_callback.assert_called_once()
        assert 'todo' in n._answer_callback.call_args[0][1]


# ── Reject tests ──────────────────────────────────────────

class TestReject:

    def test_reject_ok(self, db, goal_id):
        """approved → in_progress via Telegram rejection."""
        n = _make_notifier()
        tid = _task_to_approved(db, goal_id)
        assert db.get_task(tid).status == 'approved'

        result = n._handle_reject(db, tid, 'cb_123', 999)

        assert result == 1
        assert db.get_task(tid).status == 'in_progress'
        n._answer_callback.assert_called_once()
        n._edit_message.assert_called_once()
        call_text = n._edit_message.call_args[0][1]
        assert 'AFGEKEURD' in call_text
        # Rejection comment in DB
        comments = db.conn.execute(
            "SELECT body FROM comments WHERE task_id = ? "
            "AND comment_type = 'rejection'", (tid,)
        ).fetchall()
        assert len(comments) == 1

    def test_reject_already_moved(self, db, goal_id):
        """Reject on already-rejected task — idempotent, no crash."""
        n = _make_notifier()
        tid = _task_to_approved(db, goal_id)
        db.transition(tid, 'in_progress', actor='user')
        assert db.get_task(tid).status == 'in_progress'

        result = n._handle_reject(db, tid, 'cb_123', 999)

        assert result == 0
        assert db.get_task(tid).status == 'in_progress'
        n._answer_callback.assert_called_once()
        assert 'al afgekeurd' in n._answer_callback.call_args[0][1]


# ── Dashboard test ────────────────────────────────────────

class TestDashboard:

    def test_status_dashboard_contains_all_statuses(self, db, goal_id):
        """Dashboard output includes all 8 status counts."""
        n = _make_notifier()
        # Create a task so there's something in the DB
        db.create_task(goal_id, 'T1', 'edge_analyst', 'boss',
                       initial_status='todo')

        n.send_dashboard(db)

        n._send.assert_called_once()
        text = n._send.call_args[0][0]
        for status in ['proposal', 'todo', 'in_progress', 'peer_review',
                        'review', 'approved', 'done', 'blocked']:
            assert status in text, f"'{status}' missing from dashboard"
