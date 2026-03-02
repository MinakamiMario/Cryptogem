"""Tests for v1.0.8 observability improvements.

Covers:
- cycle_metrics new columns: skipped_agents, retries
- Capacity forecast in health report
- Drain mode recovery instructions in notifier
- InfraGuardian refactor (no shell calls)
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import WIP_CAPS
from lab.db import LabDB
from lab.inspector import LabInspector
from lab.models import CycleMetrics


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_v108.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


# ── cycle_metrics: skipped_agents + retries ──────────────────

class TestCycleMetricsNewColumns:
    """cycle_metrics table supports skipped_agents and retries."""

    def test_columns_exist_in_schema(self, db):
        """skipped_agents and retries columns exist."""
        cols = {row[1] for row in
                db.conn.execute("PRAGMA table_info(cycle_metrics)").fetchall()}
        assert 'skipped_agents' in cols
        assert 'retries' in cols

    def test_save_and_retrieve_new_fields(self, db):
        """New fields saved and retrieved correctly."""
        stats = {
            'cycle': 1, 'reviews': 2, 'tasks': 3,
            'promotions': 1, 'errors': 0,
            'skipped_agents': 2, 'retries': 1,
            'agent_count': 10, 'cycle_duration_s': 5.0,
        }
        db.save_cycle_metrics(stats)
        m = db.get_cycle_metrics(limit=1)[0]
        assert m.skipped_agents == 2
        assert m.retries == 1

    def test_defaults_to_zero(self, db):
        """Missing keys default to 0."""
        db.save_cycle_metrics({'cycle': 1})
        m = db.get_cycle_metrics(limit=1)[0]
        assert m.skipped_agents == 0
        assert m.retries == 0

    def test_migration_idempotent(self, db):
        """init_schema() can run multiple times safely."""
        db.init_schema()
        db.init_schema()
        db.save_cycle_metrics({
            'cycle': 1, 'skipped_agents': 3, 'retries': 2,
        })
        m = db.get_cycle_metrics(limit=1)[0]
        assert m.skipped_agents == 3
        assert m.retries == 2

    def test_get_since_includes_new_fields(self, db):
        """get_cycle_metrics_since() returns new fields."""
        db.save_cycle_metrics({
            'cycle': 1, 'skipped_agents': 1, 'retries': 2,
        })
        metrics = db.get_cycle_metrics_since(hours=24)
        assert len(metrics) == 1
        assert metrics[0].skipped_agents == 1
        assert metrics[0].retries == 2

    def test_model_has_new_fields(self):
        """CycleMetrics dataclass has skipped_agents and retries."""
        m = CycleMetrics(id=1, cycle=1, skipped_agents=5, retries=3)
        assert m.skipped_agents == 5
        assert m.retries == 3

    def test_heartbeat_persists_new_fields(self, db):
        """HeartbeatLoop.run_once() persists skipped_agents + retries."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)

        class SkippedAgent:
            """Agent whose circuit breaker is open → gets skipped."""
            name = 'test_agent'
            role = 'Test'
            def heartbeat(self):
                return {'reviews': 0, 'tasks': 0,
                        'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [SkippedAgent()])
            loop.run_once()

        m = db.get_cycle_metrics(limit=1)[0]
        # With 1 agent, 0 skipped, 0 retries (no blocked tasks)
        assert m.skipped_agents == 0
        assert m.retries == 0


# ── Capacity forecast in health report ───────────────────────

class TestCapacityForecastInReport:
    """Capacity forecast section in format_health_report()."""

    def test_no_forecast_when_stable(self, db):
        """Report omits forecast section when no imminent breaches."""
        db.save_cycle_metrics({'cycle': 1, 'tasks': 1})
        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Capacity Forecast' not in report

    def test_forecast_shows_breached(self, db):
        """Report shows BREACHED when cap already exceeded."""
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        # Fill blocked cap (3)
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = db.create_task(goal_id, f"B{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=ec)
            db.transition(tid, 'in_progress', actor='edge_analyst')
            db.transition(tid, 'blocked', actor='edge_analyst')

        # Need metrics for forecast to work
        db.save_cycle_metrics({'cycle': 1, 'tasks': 1})

        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Capacity Forecast' in report
        assert 'BREACHED' in report


# ── Drain mode recovery instructions ─────────────────────────

class TestDrainModeRecovery:
    """drain_mode_entered() now includes recovery guidance."""

    def test_recovery_in_progress_breach(self):
        """in_progress breach → review/complete existing tasks."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.drain_mode_entered({'in_progress': (4, 3)})
        call_args = notifier._send.call_args[0][0]
        assert 'Recovery' in call_args
        assert 'review/complete existing tasks' in call_args

    def test_recovery_approved_breach(self):
        """approved breach → user TG action needed."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.drain_mode_entered({'approved': (3, 2)})
        call_args = notifier._send.call_args[0][0]
        assert 'Recovery' in call_args
        assert 'user TG' in call_args

    def test_recovery_review_breach(self):
        """review breach → boss must approve or reject."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.drain_mode_entered({'review': (3, 2)})
        call_args = notifier._send.call_args[0][0]
        assert 'boss must approve' in call_args

    def test_recovery_multiple_breaches(self):
        """Multiple breaches → multiple recovery hints."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier._send = MagicMock()

        notifier.drain_mode_entered({
            'in_progress': (4, 3),
            'approved': (3, 2),
        })
        call_args = notifier._send.call_args[0][0]
        assert 'review/complete' in call_args
        assert 'user TG' in call_args


# ── InfraGuardian refactor ───────────────────────────────────

class TestInfraGuardianRefactor:
    """InfraGuardian no longer calls shell commands."""

    def test_no_subprocess_import(self):
        """infra_guardian.py does not import subprocess."""
        import importlib
        import lab.agents.infra_guardian as mod
        importlib.reload(mod)
        source = open(mod.__file__).read()
        assert 'import subprocess' not in source

    def test_execute_task_default_runs_all_checks(self, db):
        """Default execute_task runs in-process checks, not make check."""
        from lab.agents.infra_guardian import InfraGuardian
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.infra_check = MagicMock()
        agent = InfraGuardian(db=db, notifier=notifier)

        from lab.models import Task
        task = Task(id=1, goal_id=1, title="General check",
                    assigned_to='infra_guardian', created_by='boss')
        result = agent.execute_task(task)
        # Should not crash (subprocess.run would crash with shell_guard)
        assert isinstance(result.success, bool)
        assert result.cmd == 'infra_checks'

    def test_schema_check_works(self, db):
        """Schema invariant check works in-process."""
        from lab.agents.infra_guardian import InfraGuardian
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        agent = InfraGuardian(db=db, notifier=notifier)

        from lab.models import Task
        task = Task(id=1, goal_id=1, title="Check schema invariants",
                    assigned_to='infra_guardian', created_by='boss')
        result = agent.execute_task(task)
        assert isinstance(result.success, bool)
        assert 'Schema invariant' in result.summary

    def test_file_integrity_check(self, db):
        """File integrity check runs without shell."""
        from lab.agents.infra_guardian import InfraGuardian
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        agent = InfraGuardian(db=db, notifier=notifier)

        from lab.models import Task
        task = Task(id=1, goal_id=1, title="Check file integrity",
                    assigned_to='infra_guardian', created_by='boss')
        result = agent.execute_task(task)
        assert isinstance(result.success, bool)
        assert 'File integrity' in result.summary

    def test_review_task_still_works(self, db):
        """review_task() unchanged — still checks artifacts."""
        from lab.agents.infra_guardian import InfraGuardian
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        agent = InfraGuardian(db=db, notifier=notifier)

        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        tid = db.create_task(goal_id, "Test task", 'edge_analyst', 'boss',
                             initial_status='todo', exit_conditions=ec)
        db.transition(tid, 'in_progress', actor='edge_analyst')

        # Add a completion comment
        db.add_comment(tid, 'edge_analyst',
                       'Completed the analysis with full results.', 'comment')
        db.transition(tid, 'peer_review', actor='edge_analyst')

        # Create review for infra_guardian
        db.create_review(tid, reviewer='infra_guardian')

        task = db.get_task(tid)
        agent.review_task(task)

        # Should have posted a review (needs_changes since no artifact)
        reviews = db.get_reviews_for_task(tid)
        ig_review = [r for r in reviews if r.reviewer == 'infra_guardian']
        assert len(ig_review) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
