"""Tests for v1.2.1 — on-demand governance visibility.

Covers:
- Enhanced status summary (inspector health report)
- Gate health TG button + callback
- Agent timing in inspector health report
- Dashboard button layout (2 rows)
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
# Enhanced status summary
# ═══════════════════════════════════════════════════════════

class TestEnhancedStatus:
    """Verify status button uses inspector health report."""

    def test_status_uses_inspector(self, db):
        """Status summary tries inspector first."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._send_status_summary(db)

        # Should use inspector's format_health_report
        notifier._send_html.assert_called_once()
        sent = notifier._send_html.call_args[0][0]
        assert 'STATUS REPORT' in sent
        assert 'Pipeline' in sent

    def test_status_fallback_to_dashboard(self, db):
        """Falls back to dashboard if inspector fails."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_with_buttons = MagicMock()

        # Force inspector to fail
        with patch('lab.notifier.LabNotifier._send_html',
                   side_effect=Exception('inspector broken')):
            # The fallback calls send_dashboard which uses _send_with_buttons
            notifier._send_status_summary(db)

        # Should have fallen back to send_dashboard
        notifier._send_with_buttons.assert_called_once()


# ═══════════════════════════════════════════════════════════
# Gate health TG button
# ═══════════════════════════════════════════════════════════

class TestGateHealth:
    """Verify gate health button and handler."""

    def test_gates_button_in_dashboard(self, db):
        """Dashboard includes Gates button."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_with_buttons = MagicMock()

        notifier.send_dashboard(db)

        call_args = notifier._send_with_buttons.call_args
        buttons = call_args[1]['buttons'] if 'buttons' in call_args[1] \
            else call_args[0][1]
        all_data = [b['callback_data'] for row in buttons for b in row]
        assert 'gates:0' in all_data

    def test_dashboard_two_rows(self, db):
        """Dashboard buttons are organized in 2 rows."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_with_buttons = MagicMock()

        notifier.send_dashboard(db)

        call_args = notifier._send_with_buttons.call_args
        buttons = call_args[1]['buttons'] if 'buttons' in call_args[1] \
            else call_args[0][1]
        assert len(buttons) == 2  # 2 rows
        # Row 1: Trends + Gates
        assert len(buttons[0]) == 2
        # Row 2: CI + Remote Hands
        assert len(buttons[1]) == 2

    def test_handle_gates_no_rejections(self, db):
        """Gate handler shows clean state when no rejections."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_gates(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'GATE HEALTH' in sent
        assert 'Geen gate rejections' in sent

    def test_handle_gates_with_rejections(self, db):
        """Gate handler formats rejection data."""
        from lab.notifier import LabNotifier

        # Create a task and goal first
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('test', '[]', 1)"
        )
        db.conn.commit()
        db.conn.execute(
            "INSERT INTO tasks (goal_id, title, assigned_to, created_by, "
            "status) VALUES (1, 'test task', 'boss', 'boss', 'todo')"
        )
        db.conn.commit()

        # Insert gate rejections directly
        db.conn.execute(
            "INSERT INTO gate_rejections "
            "(gate, task_id, actor, from_status, to_status, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ('wip_cap', 1, 'boss', 'todo', 'in_progress',
             'WIP cap reached: in_progress 3/3'),
        )
        db.conn.execute(
            "INSERT INTO gate_rejections "
            "(gate, task_id, actor, from_status, to_status, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ('drain_mode', 1, 'boss', 'todo', 'in_progress',
             'Drain mode active'),
        )
        db.conn.commit()

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_gates(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'GATE HEALTH' in sent
        assert 'Totaal' in sent
        assert '2 rejections' in sent
        assert 'wip_cap' in sent
        assert 'drain_mode' in sent

    def test_gates_callback_processed(self, db):
        """poll_telegram processes gates:0 callback."""
        from lab.notifier import LabNotifier
        import lab.notifier as notifier_mod

        chat_id = notifier_mod._CHAT_ID

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = True

        notifier._api = MagicMock(return_value={
            'ok': True,
            'result': [
                {
                    'update_id': 200,
                    'callback_query': {
                        'id': 'cb_gates',
                        'data': 'gates:0',
                        'message': {
                            'chat': {'id': chat_id},
                            'message_id': 99,
                        },
                    },
                }
            ],
        })

        notifier._answer_callback = MagicMock()
        notifier._handle_gates = MagicMock()

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._answer_callback.assert_called_once_with(
            'cb_gates', 'Gate health wordt geladen...')
        notifier._handle_gates.assert_called_once_with(db)
        assert actions == 1


# ═══════════════════════════════════════════════════════════
# Agent timing in health report
# ═══════════════════════════════════════════════════════════

class TestHealthReportTiming:
    """Verify agent timing appears in inspector health report."""

    def test_health_report_includes_timing(self, db):
        """Health report shows agent timing when metrics exist."""
        from lab.inspector import LabInspector

        # Seed cycle metrics with agent timings
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 2, 'reviews': 3,
            'cycle_duration_s': 15.0,
            'agent_timings': {'boss': 5.0, 'edge_analyst': 3.0,
                              'risk_governor': 1.0},
        })

        inspector = LabInspector(db)
        report = inspector.format_health_report()

        assert '⏱' in report
        assert 'boss' in report
        assert '5.0s' in report

    def test_health_report_no_timing_without_metrics(self, db):
        """Health report works fine without any cycle metrics."""
        from lab.inspector import LabInspector

        inspector = LabInspector(db)
        report = inspector.format_health_report()

        # Should still produce valid report without timing section
        assert 'Pipeline' in report
        # No timing markers
        assert '⏱' not in report

    def test_health_report_slowest_shown(self, db):
        """Slowest agent indicator shown when >3 agents."""
        from lab.inspector import LabInspector

        db.save_cycle_metrics({
            'cycle': 1, 'cycle_duration_s': 20.0,
            'agent_timings': {
                'boss': 8.0, 'edge_analyst': 3.0,
                'risk_governor': 1.0, 'infra_guardian': 2.0,
            },
        })

        inspector = LabInspector(db)
        report = inspector.format_health_report()

        assert '🐢' in report
        assert 'boss' in report
