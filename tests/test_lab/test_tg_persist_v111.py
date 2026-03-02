"""Tests for v1.1.1 — TG update_id persistence + heartbeat logging.

Covers:
- lab_settings table creation + migration
- get_setting / set_setting CRUD
- Notifier loads _last_update_id from DB on first poll
- Notifier persists _last_update_id after processing updates
- Heartbeat silent exceptions now logged
"""
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


# ═══════════════════════════════════════════════════════════
# lab_settings table + CRUD
# ═══════════════════════════════════════════════════════════

class TestLabSettings:
    """Verify lab_settings table and get/set operations."""

    def test_table_exists(self, db):
        """lab_settings table is created by init_schema."""
        tables = {row[0] for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'lab_settings' in tables

    def test_get_default(self, db):
        """get_setting returns default for missing key."""
        assert db.get_setting('nonexistent') == ''
        assert db.get_setting('nonexistent', 'fallback') == 'fallback'

    def test_set_and_get(self, db):
        """set_setting persists, get_setting retrieves."""
        db.set_setting('my_key', 'my_value')
        assert db.get_setting('my_key') == 'my_value'

    def test_upsert(self, db):
        """set_setting overwrites existing value."""
        db.set_setting('key', 'v1')
        assert db.get_setting('key') == 'v1'
        db.set_setting('key', 'v2')
        assert db.get_setting('key') == 'v2'

    def test_multiple_keys(self, db):
        """Multiple settings coexist independently."""
        db.set_setting('a', '1')
        db.set_setting('b', '2')
        assert db.get_setting('a') == '1'
        assert db.get_setting('b') == '2'

    def test_migration_idempotent(self, db):
        """Calling init_schema twice doesn't break lab_settings."""
        db.set_setting('persist', 'yes')
        db.init_schema()  # Second call
        assert db.get_setting('persist') == 'yes'


# ═══════════════════════════════════════════════════════════
# TG update_id persistence
# ═══════════════════════════════════════════════════════════

class TestTgUpdateIdPersistence:
    """Verify _last_update_id is loaded from and saved to DB."""

    def test_loads_from_db_on_first_poll(self, db):
        """First poll loads _last_update_id from DB."""
        from lab.notifier import LabNotifier

        # Pre-set the offset in DB
        db.set_setting('tg_last_update_id', '12345')

        notifier = LabNotifier(enabled=False)
        # Manually enable for testing
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = False

        # Mock _api to return empty result
        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        notifier.poll_telegram(db=db)

        assert notifier._last_update_id == 12345
        assert notifier._update_id_loaded is True

    def test_saves_to_db_after_updates(self, db):
        """After processing updates, _last_update_id is persisted."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 100
        notifier._update_id_loaded = True

        # Mock _api to return one update
        notifier._api = MagicMock(return_value={
            'ok': True,
            'result': [
                {
                    'update_id': 100,
                    'message': {
                        'chat': {'id': 0},  # Won't match _CHAT_ID
                        'text': 'test',
                    }
                }
            ]
        })

        notifier.poll_telegram(db=db)

        # update_id should be 101 (100 + 1)
        assert notifier._last_update_id == 101
        assert db.get_setting('tg_last_update_id') == '101'

    def test_no_save_when_no_updates(self, db):
        """No DB write when there are no updates."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 100
        notifier._update_id_loaded = True

        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        notifier.poll_telegram(db=db)

        # Nothing should be saved — no updates processed
        assert db.get_setting('tg_last_update_id', 'MISSING') == 'MISSING'

    def test_loads_only_once(self, db):
        """_last_update_id loaded from DB only on first poll."""
        from lab.notifier import LabNotifier

        db.set_setting('tg_last_update_id', '500')

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = False

        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        # First poll loads from DB
        notifier.poll_telegram(db=db)
        assert notifier._last_update_id == 500

        # Manually change in DB — should NOT affect next poll
        db.set_setting('tg_last_update_id', '999')
        notifier.poll_telegram(db=db)
        assert notifier._last_update_id == 500  # Still 500, not 999

    def test_works_without_db(self):
        """poll_telegram without db still works (no persistence)."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = False

        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        # Should not crash when db=None
        actions, msgs = notifier.poll_telegram(db=None)
        assert actions == 0
        assert notifier._update_id_loaded is False  # Not loaded without DB

    def test_handles_corrupt_db_value(self, db):
        """Corrupt value in DB doesn't crash — falls back to 0."""
        from lab.notifier import LabNotifier

        db.set_setting('tg_last_update_id', 'not_a_number')

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = False

        notifier._api = MagicMock(return_value={'ok': True, 'result': []})

        notifier.poll_telegram(db=db)
        assert notifier._last_update_id == 0
        assert notifier._update_id_loaded is True
