"""Tests for v1.2.4 — TG ↔ CLI sync for task approvals.

Covers:
- Pending messages persistence (save/load to DB)
- External approval sync (CLI approve → TG message updated)
- External rejection sync
- task_promoted persists message_id
- notify_task_done/rejected loads from DB
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.db import LabDB


@pytest.fixture
def db(tmp_path):
    """Create fresh DB for each test."""
    db_path = tmp_path / 'test.db'
    d = LabDB(str(db_path))
    d.init_schema()
    return d


def _make_notifier():
    """Create notifier with mocked API."""
    from lab.notifier import LabNotifier
    notifier = LabNotifier(enabled=False)
    notifier.enabled = True
    notifier._last_update_id = 0
    notifier._update_id_loaded = True
    notifier._pending_loaded = False
    return notifier


# ═══════════════════════════════════════════════════════════
# Pending messages persistence
# ═══════════════════════════════════════════════════════════

class TestPendingPersistence:
    """Verify pending_messages round-trips to DB."""

    def test_save_and_load(self, db):
        """Pending messages survive save → load cycle."""
        notifier = _make_notifier()
        notifier._pending_messages = {1: 100, 2: 200, 3: 300}
        notifier._save_pending_messages(db)

        # Create new notifier (simulates daemon restart)
        notifier2 = _make_notifier()
        notifier2._load_pending_messages(db)

        assert notifier2._pending_messages == {1: 100, 2: 200, 3: 300}

    def test_load_empty_db(self, db):
        """Loading from empty DB gives empty dict."""
        notifier = _make_notifier()
        notifier._load_pending_messages(db)

        assert notifier._pending_messages == {}
        assert notifier._pending_loaded is True

    def test_load_corrupt_json(self, db):
        """Corrupt JSON in DB → empty dict (no crash)."""
        db.set_setting('tg_pending_messages', 'NOT_JSON{{{')

        notifier = _make_notifier()
        notifier._load_pending_messages(db)

        assert notifier._pending_messages == {}

    def test_load_only_once(self, db):
        """Pending messages only loaded once (lazy-load)."""
        notifier = _make_notifier()
        notifier._pending_messages = {1: 100}
        notifier._save_pending_messages(db)

        notifier2 = _make_notifier()
        notifier2._load_pending_messages(db)
        assert notifier2._pending_messages == {1: 100}

        # Now change DB directly
        db.set_setting('tg_pending_messages', '{"99": 999}')

        # Second load should be a no-op (already loaded)
        notifier2._load_pending_messages(db)
        assert notifier2._pending_messages == {1: 100}  # Not changed

    def test_keys_stored_as_strings(self, db):
        """JSON keys are strings but load back as ints."""
        notifier = _make_notifier()
        notifier._pending_messages = {42: 7777}
        notifier._save_pending_messages(db)

        raw = db.get_setting('tg_pending_messages')
        data = json.loads(raw)
        assert '42' in data  # Stored as string
        assert data['42'] == 7777

        # Load back
        notifier2 = _make_notifier()
        notifier2._load_pending_messages(db)
        assert 42 in notifier2._pending_messages  # Loaded as int


# ═══════════════════════════════════════════════════════════
# External approval sync
# ═══════════════════════════════════════════════════════════

class TestExternalSync:
    """Verify _sync_approved_tasks detects external changes."""

    def _create_task(self, db, status='approved'):
        """Helper: create a goal + task at given status."""
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('g', '[]', 1)"
        )
        db.conn.execute(
            "INSERT INTO tasks (goal_id, title, assigned_to, created_by, "
            "status) VALUES (1, 'test task', 'boss', 'boss', ?)",
            (status,),
        )
        db.conn.commit()

    def test_sync_detects_done(self, db):
        """Task moved to done externally → TG message edited."""
        self._create_task(db, status='done')

        notifier = _make_notifier()
        notifier._pending_messages = {1: 555}
        notifier._pending_loaded = True
        notifier._edit_message = MagicMock()

        synced = notifier._sync_approved_tasks(db)

        assert synced == 1
        notifier._edit_message.assert_called_once()
        assert '✅' in notifier._edit_message.call_args[0][1]
        assert 'GOEDGEKEURD' in notifier._edit_message.call_args[0][1]
        assert 1 not in notifier._pending_messages

    def test_sync_detects_rejected(self, db):
        """Task moved to in_progress externally → TG message edited."""
        self._create_task(db, status='in_progress')

        notifier = _make_notifier()
        notifier._pending_messages = {1: 555}
        notifier._pending_loaded = True
        notifier._edit_message = MagicMock()

        synced = notifier._sync_approved_tasks(db)

        assert synced == 1
        assert 'extern gewijzigd' in notifier._edit_message.call_args[0][1]
        assert 1 not in notifier._pending_messages

    def test_sync_skips_still_approved(self, db):
        """Task still approved → no sync action."""
        self._create_task(db, status='approved')

        notifier = _make_notifier()
        notifier._pending_messages = {1: 555}
        notifier._pending_loaded = True
        notifier._edit_message = MagicMock()

        synced = notifier._sync_approved_tasks(db)

        assert synced == 0
        notifier._edit_message.assert_not_called()
        assert 1 in notifier._pending_messages  # Still tracked

    def test_sync_removes_missing_task(self, db):
        """Deleted task → removed from pending (no crash)."""
        notifier = _make_notifier()
        notifier._pending_messages = {999: 555}  # Task 999 doesn't exist
        notifier._pending_loaded = True
        notifier._edit_message = MagicMock()

        synced = notifier._sync_approved_tasks(db)

        assert 999 not in notifier._pending_messages

    def test_sync_saves_to_db(self, db):
        """Sync saves updated pending_messages to DB."""
        self._create_task(db, status='done')

        notifier = _make_notifier()
        notifier._pending_messages = {1: 555}
        notifier._pending_loaded = True
        notifier._edit_message = MagicMock()

        notifier._sync_approved_tasks(db)

        # Verify DB was updated
        raw = db.get_setting('tg_pending_messages')
        data = json.loads(raw)
        assert '1' not in data  # Removed

    def test_sync_empty_pending(self, db):
        """No pending messages → sync is a no-op."""
        notifier = _make_notifier()
        notifier._pending_messages = {}
        notifier._pending_loaded = True

        synced = notifier._sync_approved_tasks(db)

        assert synced == 0


# ═══════════════════════════════════════════════════════════
# Integration: poll_telegram triggers sync
# ═══════════════════════════════════════════════════════════

class TestPollTelegramSync:
    """Verify poll_telegram loads pending and triggers sync."""

    def test_poll_loads_pending_from_db(self, db):
        """poll_telegram loads pending_messages from DB."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Create task #5 in approved status so sync doesn't clear it
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('g', '[]', 1)"
        )
        db.conn.execute(
            "INSERT INTO tasks (id, goal_id, title, assigned_to, "
            "created_by, status) VALUES (5, 1, 't', 'boss', 'boss', "
            "'approved')"
        )
        db.conn.commit()

        # Pre-store pending messages in DB
        db.set_setting('tg_pending_messages', json.dumps({'5': 123}))

        notifier = _make_notifier()
        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        notifier.poll_telegram(db=db)

        assert notifier._pending_loaded is True
        assert notifier._pending_messages == {5: 123}

    def test_poll_syncs_external_approvals(self, db):
        """poll_telegram detects tasks done externally."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Create task already done
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('g', '[]', 1)"
        )
        db.conn.execute(
            "INSERT INTO tasks (goal_id, title, assigned_to, created_by, "
            "status) VALUES (1, 'external', 'boss', 'boss', 'done')"
        )
        db.conn.commit()

        # Store pending message for that task
        db.set_setting('tg_pending_messages', json.dumps({'1': 777}))

        notifier = _make_notifier()
        notifier._api = MagicMock(return_value={'ok': True, 'result': []})
        notifier._edit_message = MagicMock()

        notifier.poll_telegram(db=db)

        # Should have edited the TG message
        notifier._edit_message.assert_called_once()
        assert '✅' in notifier._edit_message.call_args[0][1]


# ═══════════════════════════════════════════════════════════
# notify_task_done/rejected with DB persistence
# ═══════════════════════════════════════════════════════════

class TestNotifyWithDB:
    """Verify notify methods load/save pending from DB."""

    def test_notify_done_loads_from_db(self, db):
        """notify_task_done loads pending from DB, edits message."""
        # Store pending message in DB
        db.set_setting('tg_pending_messages', json.dumps({'10': 888}))

        notifier = _make_notifier()
        notifier._edit_message = MagicMock()

        notifier.notify_task_done(10, 'test task', via='cli', db=db)

        # Should have edited the message (found via DB)
        notifier._edit_message.assert_called_once_with(
            888,
            '✅ <b>GOEDGEKEURD</b> (via cli) — Taak #10: '
            'test task\n\nStatus: done'
        )

        # Pending messages should be saved (without task 10)
        raw = db.get_setting('tg_pending_messages')
        data = json.loads(raw)
        assert '10' not in data

    def test_notify_rejected_loads_from_db(self, db):
        """notify_task_rejected loads pending from DB, edits message."""
        db.set_setting('tg_pending_messages', json.dumps({'20': 999}))

        notifier = _make_notifier()
        notifier._edit_message = MagicMock()

        notifier.notify_task_rejected(20, 'rejected task', via='cli', db=db)

        notifier._edit_message.assert_called_once_with(
            999,
            '❌ <b>AFGEKEURD</b> (via cli) — Taak #20: '
            'rejected task\n\nStatus: in_progress (retry)'
        )

    def test_notify_done_without_db_still_works(self):
        """notify_task_done works without db (backward compat)."""
        notifier = _make_notifier()
        notifier._pending_messages = {5: 111}
        notifier._edit_message = MagicMock()

        notifier.notify_task_done(5, 'task', via='cli')

        notifier._edit_message.assert_called_once()

    def test_task_promoted_saves_to_db(self, db):
        """task_promoted saves new pending message to DB."""
        notifier = _make_notifier()
        notifier._pending_loaded = True
        notifier._send_with_buttons = MagicMock(return_value=12345)

        notifier.task_promoted(42, 'new task', db=db)

        assert notifier._pending_messages[42] == 12345

        # Verify persisted
        raw = db.get_setting('tg_pending_messages')
        data = json.loads(raw)
        assert data['42'] == 12345
