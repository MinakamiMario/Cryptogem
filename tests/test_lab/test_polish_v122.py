"""Tests for v1.2.2 — final polish.

Covers:
- Gate rejection logging (was silent pass, now logged)
- Capacity forecast in TG Trends
- Documented future agent hooks
"""
import logging
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
# Gate rejection logging
# ═══════════════════════════════════════════════════════════

class TestGateRejectionLogging:
    """Verify _log_gate_rejection logs failures instead of silencing."""

    def test_successful_logging(self, db):
        """Gate rejection inserts into table normally."""
        # Need a task for the FK
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('g', '[]', 1)"
        )
        db.conn.execute(
            "INSERT INTO tasks (goal_id, title, assigned_to, created_by, "
            "status) VALUES (1, 't', 'boss', 'boss', 'todo')"
        )
        db.conn.commit()

        db._log_gate_rejection(
            'wip_cap', 1, 'boss', 'todo', 'in_progress',
            'WIP cap reached')

        row = db.conn.execute(
            "SELECT * FROM gate_rejections WHERE task_id = 1"
        ).fetchone()
        assert row is not None
        assert row['gate'] == 'wip_cap'

    def test_failure_logged_as_warning(self, db, caplog):
        """Failed gate rejection logging emits warning instead of pass."""
        # Close the connection to force an error
        db.conn.close()

        with caplog.at_level(logging.WARNING, logger='lab.db'):
            # This should NOT raise, but should log a warning
            db._log_gate_rejection(
                'test_gate', 999, 'actor', 'from', 'to', 'reason')

        assert any('Gate rejection log failed' in r.message
                    for r in caplog.records)


# ═══════════════════════════════════════════════════════════
# Capacity forecast in TG Trends
# ═══════════════════════════════════════════════════════════

class TestTrendsForecast:
    """Verify capacity forecast appears in Trends output."""

    def test_trends_no_forecast_when_stable(self, db):
        """No forecast section when all caps are stable."""
        from lab.notifier import LabNotifier

        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 1, 'cycle_duration_s': 10.0,
        })

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_trends(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'TRENDS' in sent
        # No forecast section expected (no approaching breaches)
        assert 'Capacity Forecast' not in sent

    def test_trends_shows_breached_cap(self, db):
        """Forecast section shows BREACHED caps."""
        from lab.notifier import LabNotifier
        from lab.config import WIP_CAPS

        # Seed cycle metrics
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 1, 'cycle_duration_s': 10.0,
        })

        # Artificially breach in_progress cap (3/3)
        db.conn.execute(
            "INSERT INTO goals (title, agents, tasks_per_day) "
            "VALUES ('g', '[]', 1)"
        )
        db.conn.commit()
        for i in range(WIP_CAPS['in_progress']):
            db.conn.execute(
                "INSERT INTO tasks (goal_id, title, assigned_to, "
                "created_by, status) "
                "VALUES (1, ?, 'boss', 'boss', 'in_progress')",
                (f'task_{i}',),
            )
        db.conn.commit()

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_trends(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'Capacity Forecast' in sent
        assert 'BREACHED' in sent


# ═══════════════════════════════════════════════════════════
# Future agent hooks documented
# ═══════════════════════════════════════════════════════════

class TestFutureAgentHooks:
    """Verify future agent notification methods exist and work."""

    def test_live_drift_works(self):
        """live_drift() sends correctly when enabled."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.live_drift('PnL', '$100', '$50')

        notifier._send.assert_called_once()
        sent = notifier._send.call_args[0][0]
        assert 'drift' in sent.lower()
        assert 'PnL' in sent

    def test_deployment_verdict_works(self):
        """deployment_verdict() sends with correct icon."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.deployment_verdict(42, 'GO', 'All checks pass')

        sent = notifier._send.call_args[0][0]
        assert '🟢' in sent
        assert 'GO' in sent
        assert '#42' in sent

    def test_deployment_verdict_nogo(self):
        """deployment_verdict() shows red for NO-GO."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.deployment_verdict(1, 'NO-GO', 'Risk too high')

        sent = notifier._send.call_args[0][0]
        assert '🔴' in sent
        assert 'NO-GO' in sent
