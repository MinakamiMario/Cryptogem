"""Tests for lab.notifier callback handlers and dashboard output."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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
    n._send_html = MagicMock(return_value=124)
    n._send_with_buttons = MagicMock(return_value=125)
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
        """Dashboard output includes all 8 status counts + CI button."""
        n = _make_notifier()
        # Create a task so there's something in the DB
        db.create_task(goal_id, 'T1', 'edge_analyst', 'boss',
                       initial_status='todo')

        n.send_dashboard(db)

        n._send_with_buttons.assert_called_once()
        text = n._send_with_buttons.call_args[0][0]
        for status in ['proposal', 'todo', 'in_progress', 'peer_review',
                        'review', 'approved', 'done', 'blocked']:
            assert status in text, f"'{status}' missing from dashboard"
        # CI button present
        buttons = n._send_with_buttons.call_args.kwargs['buttons']
        assert any('ci:' in b.get('callback_data', '')
                   for row in buttons for b in row)


# ── CI callback test ─────────────────────────────────────

class TestCICallback:

    def test_handle_ci_shows_workflow_runs(self):
        """📊 CI button fetches GitHub Actions runs and sends summary."""
        n = _make_notifier()

        # Mock GitHub API response
        fake_response = json.dumps({
            'workflow_runs': [
                {'name': 'Lab Tests', 'head_branch': 'master',
                 'conclusion': 'success', 'status': 'completed'},
                {'name': 'Lab Release', 'head_branch': 'master',
                 'conclusion': 'success', 'status': 'completed'},
                {'name': 'Lab Tests', 'head_branch': 'feat/x',
                 'conclusion': 'failure', 'status': 'completed'},
            ],
        }).encode('utf-8')

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=mock_resp):
            n._handle_ci('cb_ci')

        n._answer_callback.assert_called_once()
        n._send_html.assert_called_once()
        text = n._send_html.call_args[0][0]
        assert 'CI/CD Status' in text
        assert 'Lab Tests' in text
        assert '✅' in text
        assert '❌' in text

    def test_handle_ci_api_error(self):
        """GitHub API failure → error message, no crash."""
        n = _make_notifier()

        with patch('urllib.request.urlopen',
                   side_effect=Exception('timeout')):
            n._handle_ci('cb_ci')

        n._answer_callback.assert_called_once()
        n._send.assert_called_once()
        assert 'fout' in n._send.call_args[0][0].lower()


# ── Remote Hands healthcheck callback test ───────────

class TestRemoteHandsCallback:

    def test_handle_remote_hands_sends_output(self):
        """🖥 Remote Hands button runs healthcheck and sends result."""
        n = _make_notifier()

        with patch('lab.tools.remote_hands_healthcheck.check_tailscale_running',
                   return_value=(True, 'Tailscale IP: 100.67.19.108')), \
             patch('lab.tools.remote_hands_healthcheck.check_rustdesk_listening',
                   return_value=(True, 'RustDesk listening on port 21118')), \
             patch('lab.tools.remote_hands_healthcheck.check_pf_enabled',
                   return_value=(True, 'pf: Status: Enabled')):
            n._handle_remote_hands('cb_rh')

        n._answer_callback.assert_called_once()
        n._send_html.assert_called_once()
        text = n._send_html.call_args[0][0]
        assert 'Remote Hands' in text
        assert 'ALL PASS' in text
        assert 'Tailscale' in text

    def test_handle_remote_hands_shows_failures(self):
        """Healthcheck with failures shows FAIL verdict."""
        n = _make_notifier()

        with patch('lab.tools.remote_hands_healthcheck.check_tailscale_running',
                   return_value=(True, 'Tailscale IP: 100.67.19.108')), \
             patch('lab.tools.remote_hands_healthcheck.check_rustdesk_listening',
                   return_value=(False, 'RustDesk NOT listening')), \
             patch('lab.tools.remote_hands_healthcheck.check_pf_enabled',
                   return_value=(True, 'pf: Status: Enabled')):
            n._handle_remote_hands('cb_rh')

        text = n._send_html.call_args[0][0]
        assert 'FAIL' in text
        assert '❌' in text

    def test_handle_remote_hands_import_error(self):
        """Healthcheck import failure → error message, no crash."""
        n = _make_notifier()

        with patch.dict('sys.modules',
                        {'lab.tools.remote_hands_healthcheck': None}):
            n._handle_remote_hands('cb_rh')

        n._answer_callback.assert_called_once()
        n._send.assert_called_once()
        assert 'fout' in n._send.call_args[0][0].lower()
