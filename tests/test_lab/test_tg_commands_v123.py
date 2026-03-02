"""Tests for v1.2.3 — Telegram text commands.

Covers:
- /dashboard and /status → send_dashboard()
- /trends → _handle_trends()
- /gates → _handle_gates()
- /health → _send_status_summary()
- /help → command list
- Unknown text → passed through as incoming_messages
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


def _make_notifier(chat_id):
    """Create notifier with mocked API returning a text message."""
    from lab.notifier import LabNotifier
    notifier = LabNotifier(enabled=False)
    notifier.enabled = True
    notifier._last_update_id = 0
    notifier._update_id_loaded = True
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
# Text command: /dashboard and /status
# ═══════════════════════════════════════════════════════════

class TestDashboardCommand:
    """Verify /dashboard and /status text commands."""

    def test_dashboard_command(self, db):
        """/dashboard sends dashboard with buttons."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/dashboard')
        notifier.send_dashboard = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier.send_dashboard.assert_called_once_with(db)
        assert actions == 1
        assert msgs == []  # Not passed through

    def test_status_command(self, db):
        """/status is alias for dashboard."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/status')
        notifier.send_dashboard = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier.send_dashboard.assert_called_once_with(db)
        assert actions == 1

    def test_status_case_insensitive(self, db):
        """Commands are case insensitive."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, 'Dashboard')
        notifier.send_dashboard = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier.send_dashboard.assert_called_once_with(db)
        assert actions == 1

    def test_status_without_slash(self, db):
        """Commands work without leading slash."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, 'status')
        notifier.send_dashboard = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier.send_dashboard.assert_called_once_with(db)


# ═══════════════════════════════════════════════════════════
# Text command: /trends
# ═══════════════════════════════════════════════════════════

class TestTrendsCommand:
    """Verify /trends text command."""

    def test_trends_command(self, db):
        """/trends sends trends report."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/trends')
        notifier._handle_trends = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._handle_trends.assert_called_once_with(db)
        assert actions == 1
        assert msgs == []


# ═══════════════════════════════════════════════════════════
# Text command: /gates
# ═══════════════════════════════════════════════════════════

class TestGatesCommand:
    """Verify /gates text command."""

    def test_gates_command(self, db):
        """/gates sends gate health report."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/gates')
        notifier._handle_gates = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._handle_gates.assert_called_once_with(db)
        assert actions == 1


# ═══════════════════════════════════════════════════════════
# Text command: /health
# ═══════════════════════════════════════════════════════════

class TestHealthCommand:
    """Verify /health text command."""

    def test_health_command(self, db):
        """/health sends full inspector report."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/health')
        notifier._send_status_summary = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._send_status_summary.assert_called_once_with(db)
        assert actions == 1


# ═══════════════════════════════════════════════════════════
# Text command: /help
# ═══════════════════════════════════════════════════════════

class TestHelpCommand:
    """Verify /help text command."""

    def test_help_command(self, db):
        """/help sends command list."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/help')
        notifier._send_html = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._send_html.assert_called_once()
        sent = notifier._send_html.call_args[0][0]
        assert 'LAB COMMANDS' in sent
        assert '/dashboard' in sent
        assert '/health' in sent
        assert '/trends' in sent
        assert '/gates' in sent
        assert actions == 1

    def test_help_questionmark(self, db):
        """? is alias for /help."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '?')
        notifier._send_html = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._send_html.assert_called_once()
        assert actions == 1

    def test_help_no_db_required(self):
        """/help works even without db."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, '/help')
        notifier._send_html = MagicMock()

        actions, msgs = notifier.poll_telegram(db=None)

        notifier._send_html.assert_called_once()
        assert actions == 1


# ═══════════════════════════════════════════════════════════
# Unknown text → passthrough
# ═══════════════════════════════════════════════════════════

class TestUnknownText:
    """Verify unknown text is passed through as messages."""

    def test_unknown_text_passthrough(self, db):
        """Non-command text is returned as incoming_messages."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, 'hallo bot')

        actions, msgs = notifier.poll_telegram(db=db)

        assert actions == 0
        assert msgs == ['hallo bot']

    def test_partial_command_not_matched(self, db):
        """Partial commands are not matched."""
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        notifier = _make_notifier(chat_id)
        _mock_text_update(notifier, chat_id, 'dashboardx')

        actions, msgs = notifier.poll_telegram(db=db)

        assert actions == 0
        assert msgs == ['dashboardx']
