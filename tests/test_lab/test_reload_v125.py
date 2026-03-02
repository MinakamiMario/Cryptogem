"""Tests for v1.2.5 — auto-reload daemon via TG + launchd.

Covers:
- /reload TG command sends SIGTERM
- /help shows version and /reload
- Wrapper script exists and is executable
"""
import json
import os
import signal
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


def _make_notifier(chat_id):
    """Create notifier with mocked internals."""
    from lab.notifier import LabNotifier
    notifier = LabNotifier(enabled=False)
    notifier.enabled = True
    notifier._last_update_id = 0
    notifier._update_id_loaded = True
    notifier._pending_loaded = True
    return notifier


def _mock_text_update(notifier, chat_id, text, update_id=100):
    """Configure notifier._api to return a text message update."""
    notifier._api = MagicMock(return_value={
        'ok': True,
        'result': [
            {
                'update_id': update_id,
                'message': {
                    'chat': {'id': chat_id},
                    'message_id': 50,
                    'text': text,
                },
            }
        ],
    })


# ═══════════════════════════════════════════════════════════
# /reload command
# ═══════════════════════════════════════════════════════════

class TestReloadCommand:
    """Verify /reload triggers daemon restart via SIGTERM."""

    def test_reload_sends_sigterm(self, db):
        """/reload sends SIGTERM to current process."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            actions, msgs = notifier.poll_telegram(db=db)

        # Should have sent TG confirmation
        notifier._send.assert_called_once()
        sent = notifier._send.call_args[0][0]
        assert 'Reload' in sent or 'reload' in sent

        # Should have sent SIGTERM
        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        assert actions == 1

    def test_reload_persists_update_id(self, db):
        """/reload saves update_id before exit."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload', update_id=500)
        notifier._send = MagicMock()

        with patch('os.kill'):
            notifier.poll_telegram(db=db)

        # Update ID should be persisted (500 + 1 = 501)
        stored = db.get_setting('tg_last_update_id', '0')
        assert int(stored) == 501

    def test_reload_case_insensitive(self, db):
        """/Reload works case-insensitively."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, 'Reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            notifier.poll_telegram(db=db)

        mock_kill.assert_called_once()


# ═══════════════════════════════════════════════════════════
# /help updated
# ═══════════════════════════════════════════════════════════

class TestHelpUpdated:
    """Verify /help shows version and reload command."""

    def test_help_shows_version(self, db):
        """/help includes current version."""
        import lab.notifier as notifier_mod
        from lab.config import LAB_VERSION
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/help')
        notifier._send_html = MagicMock()

        notifier.poll_telegram(db=db)

        sent = notifier._send_html.call_args[0][0]
        assert LAB_VERSION in sent

    def test_help_shows_reload(self, db):
        """/help lists /reload command."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/help')
        notifier._send_html = MagicMock()

        notifier.poll_telegram(db=db)

        sent = notifier._send_html.call_args[0][0]
        assert '/reload' in sent


# ═══════════════════════════════════════════════════════════
# Wrapper script
# ═══════════════════════════════════════════════════════════

class TestWrapperScript:
    """Verify start-daemon.sh exists and is executable."""

    def test_wrapper_exists(self):
        """start-daemon.sh exists."""
        script = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'start-daemon.sh'
        )
        assert os.path.exists(script)

    def test_wrapper_executable(self):
        """start-daemon.sh is executable."""
        script = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'start-daemon.sh'
        )
        assert os.access(script, os.X_OK)

    def test_plist_uses_wrapper(self):
        """Plist template references start-daemon.sh."""
        plist = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'com.cryptogem.lab.plist'
        )
        with open(plist) as f:
            content = f.read()
        assert 'start-daemon.sh' in content
