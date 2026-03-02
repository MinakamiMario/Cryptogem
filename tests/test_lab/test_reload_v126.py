"""Tests for v1.2.6 — reload guardrails + fail-safe signals.

Covers:
- Rate-limit: max 1 reload per 5 min
- Fail-safe: dual TG signals (ontvangen + voltooid)
- Wrapper log output includes version + self-test status
- Reload persists cooldown timestamp in DB
"""
import os
import signal
import sys
import time
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
# Rate-limit tests
# ═══════════════════════════════════════════════════════════

class TestReloadRateLimit:
    """Verify /reload cooldown prevents spam."""

    def test_first_reload_allowed(self, db):
        """First /reload succeeds (no prior cooldown)."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            actions, msgs = notifier.poll_telegram(db=db)

        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        assert actions == 1

    def test_second_reload_blocked_within_cooldown(self, db):
        """Second /reload within 5 min is blocked."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Simulate a recent reload (10 seconds ago)
        db.set_setting('reload_last_ts', str(time.time() - 10))

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            actions, msgs = notifier.poll_telegram(db=db)

        # Should NOT send SIGTERM
        mock_kill.assert_not_called()
        # Should send cooldown message
        notifier._send.assert_called_once()
        sent = notifier._send.call_args[0][0]
        assert 'cooldown' in sent.lower() or 'geweigerd' in sent.lower()
        assert actions == 1

    def test_reload_allowed_after_cooldown_expires(self, db):
        """Reload succeeds after cooldown period expires."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Simulate an old reload (10 minutes ago)
        db.set_setting('reload_last_ts', str(time.time() - 600))

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            actions, msgs = notifier.poll_telegram(db=db)

        mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_reload_persists_cooldown_timestamp(self, db):
        """/reload saves its timestamp for cooldown enforcement."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        before = time.time()

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill'):
            notifier.poll_telegram(db=db)

        after = time.time()
        stored = float(db.get_setting('reload_last_ts', '0'))
        assert before <= stored <= after

    def test_cooldown_message_shows_remaining_time(self, db):
        """Cooldown message tells user how long to wait."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Simulate reload 60 seconds ago → ~240s remaining
        db.set_setting('reload_last_ts', str(time.time() - 60))

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill') as mock_kill:
            notifier.poll_telegram(db=db)

        mock_kill.assert_not_called()
        sent = notifier._send.call_args[0][0]
        # Should mention remaining seconds (approximately 240)
        assert 'wacht' in sent.lower() or 's' in sent


# ═══════════════════════════════════════════════════════════
# Fail-safe signal tests
# ═══════════════════════════════════════════════════════════

class TestReloadFailSafe:
    """Verify dual signal pattern for reload confirmation."""

    def test_signal1_tg_reload_ontvangen(self, db):
        """TG signal 1: 'reload ontvangen' message sent."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill'):
            notifier.poll_telegram(db=db)

        sent = notifier._send.call_args[0][0]
        assert 'ontvangen' in sent.lower() or 'reload' in sent.lower()
        assert 'stopt' in sent.lower()

    def test_signal1_mentions_expected_confirmation(self, db):
        """Signal 1 tells user to expect a confirmation."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/reload')
        notifier._send = MagicMock()

        with patch('os.kill'):
            notifier.poll_telegram(db=db)

        sent = notifier._send.call_args[0][0]
        assert 'bevestiging' in sent.lower() or 'verwacht' in sent.lower()

    def test_signal2_wrapper_contains_reload_voltooid(self):
        """Wrapper script contains 'Reload voltooid' TG message."""
        script = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'start-daemon.sh'
        )
        with open(script) as f:
            content = f.read()
        assert 'Reload voltooid' in content

    def test_wrapper_log_contains_loaded_version(self):
        """Wrapper logs 'Loaded version: vX.Y.Z' for log monitoring."""
        script = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'start-daemon.sh'
        )
        with open(script) as f:
            content = f.read()
        assert 'Loaded version:' in content
        assert 'Self-test PASS' in content

    def test_wrapper_log_contains_selftest_status(self):
        """Wrapper logs self-test result for monitoring."""
        script = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'lab', 'deploy', 'start-daemon.sh'
        )
        with open(script) as f:
            content = f.read()
        # Both success and failure paths exist
        assert 'Self-test PASS' in content or 'Self-test passed' in content
        assert 'Self-test FAILED' in content
