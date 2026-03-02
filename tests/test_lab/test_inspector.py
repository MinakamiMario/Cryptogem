"""Tests for lab/inspector.py — system health snapshots and trend analysis."""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import WIP_CAPS
from lab.db import LabDB
from lab.inspector import HealthSnapshot, LabInspector, ThroughputTrend
from lab.models import CycleMetrics


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_inspector.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


class TestCycleMetricsDB:
    """cycle_metrics table: save and query."""

    def test_save_and_retrieve(self, db):
        """Save a cycle metric and retrieve it."""
        stats = {
            'cycle': 1, 'reviews': 3, 'tasks': 5,
            'promotions': 1, 'errors': 0,
            'drain_mode': False, 'drain_cycles': 0,
            'agent_count': 10, 'cycle_duration_s': 2.5,
        }
        row_id = db.save_cycle_metrics(stats)
        assert row_id > 0

        metrics = db.get_cycle_metrics(limit=1)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.cycle == 1
        assert m.reviews == 3
        assert m.tasks == 5
        assert m.promotions == 1
        assert m.errors == 0
        assert m.drain_mode is False
        assert m.drain_cycles == 0
        assert m.agent_count == 10
        assert m.cycle_duration_s == 2.5

    def test_drain_mode_stored_as_bool(self, db):
        """drain_mode is stored as integer, returned as bool."""
        db.save_cycle_metrics({
            'cycle': 1, 'drain_mode': True, 'drain_cycles': 3,
        })
        m = db.get_cycle_metrics(limit=1)[0]
        assert m.drain_mode is True
        assert m.drain_cycles == 3

    def test_multiple_cycles_ordered(self, db):
        """Multiple cycles returned newest-first."""
        for i in range(5):
            db.save_cycle_metrics({'cycle': i + 1, 'tasks': i})
        metrics = db.get_cycle_metrics(limit=10)
        assert len(metrics) == 5
        # Newest first
        assert metrics[0].cycle == 5
        assert metrics[-1].cycle == 1

    def test_limit_respected(self, db):
        """Limit parameter caps returned results."""
        for i in range(10):
            db.save_cycle_metrics({'cycle': i + 1})
        metrics = db.get_cycle_metrics(limit=3)
        assert len(metrics) == 3

    def test_get_since_hours(self, db):
        """get_cycle_metrics_since() filters by time window."""
        # All metrics created with default timestamp (now)
        for i in range(3):
            db.save_cycle_metrics({'cycle': i + 1, 'tasks': i})
        # Should find all (created within last 24h)
        metrics = db.get_cycle_metrics_since(hours=24)
        assert len(metrics) == 3
        # Should be ordered ASC (oldest first)
        assert metrics[0].cycle == 1
        assert metrics[-1].cycle == 3

    def test_empty_stats_defaults(self, db):
        """Missing keys in stats dict default to 0."""
        db.save_cycle_metrics({'cycle': 1})
        m = db.get_cycle_metrics(limit=1)[0]
        assert m.reviews == 0
        assert m.tasks == 0
        assert m.promotions == 0
        assert m.errors == 0
        assert m.agent_count == 0
        assert m.cycle_duration_s == 0.0

    def test_schema_migration_idempotent(self, db):
        """init_schema() can run multiple times (migration safe)."""
        db.init_schema()
        db.init_schema()
        db.save_cycle_metrics({'cycle': 1, 'tasks': 1})
        assert len(db.get_cycle_metrics(limit=1)) == 1


class TestHealthSnapshot:
    """LabInspector.health_snapshot() — point-in-time system state."""

    def test_empty_system(self, db):
        """Fresh DB returns sensible defaults."""
        inspector = LabInspector(db)
        snap = inspector.health_snapshot()
        assert snap.total_tasks == 0
        assert snap.active_tasks == 0
        assert snap.blocked_tasks == 0
        assert snap.drain_mode is False
        assert snap.cap_breaches == {}
        assert snap.cycles_24h == 0
        assert snap.goal_count == 0

    def test_task_counts_populated(self, db):
        """Snapshot reflects actual task counts."""
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        # Create 2 tasks, move 1 to in_progress
        tid1 = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                              initial_status='todo', exit_conditions=ec)
        tid2 = db.create_task(goal_id, "T2", 'edge_analyst', 'boss',
                              initial_status='todo', exit_conditions=ec)
        db.transition(tid1, 'in_progress', actor='edge_analyst')

        inspector = LabInspector(db)
        snap = inspector.health_snapshot()
        assert snap.total_tasks == 2
        assert snap.active_tasks == 1  # 1 in_progress
        assert snap.task_counts['todo'] == 1
        assert snap.task_counts['in_progress'] == 1

    def test_cap_utilization(self, db):
        """Cap utilization calculated correctly."""
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        # Create 2 in_progress tasks (cap is 3)
        for i in range(2):
            tid = db.create_task(goal_id, f"T{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=ec)
            db.transition(tid, 'in_progress', actor='edge_analyst')

        inspector = LabInspector(db)
        snap = inspector.health_snapshot()
        assert snap.cap_utilization['in_progress'] == pytest.approx(2 / 3)

    def test_agent_health_counts(self, db):
        """Agent health categorized by status."""
        db.set_status('edge_analyst', 'active')
        db.set_status('risk_governor', 'error', note='crashed')
        # Others remain 'idle' from init_schema

        inspector = LabInspector(db)
        snap = inspector.health_snapshot()
        assert snap.agents_active == 1
        assert snap.agents_error == 1
        assert snap.agents_idle == 8  # 10 agents - 1 active - 1 error

    def test_metrics_integrated(self, db):
        """Snapshot uses cycle_metrics for 24h stats."""
        # Save some cycle metrics
        for i in range(5):
            db.save_cycle_metrics({
                'cycle': i + 1, 'tasks': 2, 'errors': 1 if i == 0 else 0,
                'cycle_duration_s': 1.5,
            })

        inspector = LabInspector(db)
        snap = inspector.health_snapshot()
        assert snap.cycles_24h == 5
        assert snap.tasks_completed_24h == 10
        assert snap.errors_24h == 1
        assert snap.avg_cycle_duration_s == pytest.approx(1.5)


class TestThroughputTrend:
    """LabInspector.throughput_trend() — throughput over time window."""

    def test_empty_returns_zeros(self, db):
        """No metrics → zero throughput."""
        inspector = LabInspector(db)
        trend = inspector.throughput_trend(hours=24)
        assert trend.cycles == 0
        assert trend.total_tasks == 0
        assert trend.tasks_per_cycle == 0.0

    def test_aggregation(self, db):
        """Throughput aggregated across cycles."""
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 3, 'reviews': 2,
            'promotions': 1, 'errors': 0,
        })
        db.save_cycle_metrics({
            'cycle': 2, 'tasks': 5, 'reviews': 4,
            'promotions': 2, 'errors': 1,
        })

        inspector = LabInspector(db)
        trend = inspector.throughput_trend(hours=24)
        assert trend.cycles == 2
        assert trend.total_tasks == 8
        assert trend.total_reviews == 6
        assert trend.total_promotions == 3
        assert trend.total_errors == 1
        assert trend.tasks_per_cycle == 4.0
        assert trend.reviews_per_cycle == 3.0
        assert trend.error_rate == 0.5


class TestDrainHistory:
    """LabInspector.drain_history() — drain mode patterns."""

    def test_no_drain(self, db):
        """No drain cycles → zeros."""
        db.save_cycle_metrics({'cycle': 1, 'drain_mode': False})
        db.save_cycle_metrics({'cycle': 2, 'drain_mode': False})

        inspector = LabInspector(db)
        hist = inspector.drain_history(hours=24)
        assert hist['total_cycles'] == 2
        assert hist['drain_cycles'] == 0
        assert hist['drain_pct'] == 0.0
        assert hist['longest_drain_streak'] == 0
        assert hist['current_streak'] == 0

    def test_drain_streak(self, db):
        """Drain streak tracked correctly."""
        db.save_cycle_metrics({'cycle': 1, 'drain_mode': False})
        db.save_cycle_metrics({'cycle': 2, 'drain_mode': True})
        db.save_cycle_metrics({'cycle': 3, 'drain_mode': True})
        db.save_cycle_metrics({'cycle': 4, 'drain_mode': True})
        db.save_cycle_metrics({'cycle': 5, 'drain_mode': False})

        inspector = LabInspector(db)
        hist = inspector.drain_history(hours=24)
        assert hist['drain_cycles'] == 3
        assert hist['drain_pct'] == pytest.approx(60.0)
        assert hist['longest_drain_streak'] == 3
        assert hist['current_streak'] == 0  # ended at cycle 5

    def test_current_streak(self, db):
        """Current drain streak detected when drain ongoing."""
        db.save_cycle_metrics({'cycle': 1, 'drain_mode': False})
        db.save_cycle_metrics({'cycle': 2, 'drain_mode': True})
        db.save_cycle_metrics({'cycle': 3, 'drain_mode': True})

        inspector = LabInspector(db)
        hist = inspector.drain_history(hours=24)
        assert hist['current_streak'] == 2
        assert hist['longest_drain_streak'] == 2

    def test_empty_history(self, db):
        """No metrics → zeros."""
        inspector = LabInspector(db)
        hist = inspector.drain_history(hours=24)
        assert hist['total_cycles'] == 0
        assert hist['drain_cycles'] == 0


class TestErrorRate:
    """LabInspector.error_rate() — error frequency."""

    def test_zero_errors(self, db):
        """No errors → 0.0."""
        db.save_cycle_metrics({'cycle': 1, 'errors': 0})
        db.save_cycle_metrics({'cycle': 2, 'errors': 0})

        inspector = LabInspector(db)
        assert inspector.error_rate(hours=24) == 0.0

    def test_error_rate_calculated(self, db):
        """Error rate is errors / cycles."""
        db.save_cycle_metrics({'cycle': 1, 'errors': 2})
        db.save_cycle_metrics({'cycle': 2, 'errors': 0})
        db.save_cycle_metrics({'cycle': 3, 'errors': 1})

        inspector = LabInspector(db)
        assert inspector.error_rate(hours=24) == pytest.approx(1.0)

    def test_empty_returns_zero(self, db):
        """No metrics → 0.0."""
        inspector = LabInspector(db)
        assert inspector.error_rate(hours=24) == 0.0


class TestCapacityForecast:
    """LabInspector.capacity_forecast() — predictive drain estimates."""

    def test_empty_returns_none(self, db):
        """No metrics → None forecasts."""
        inspector = LabInspector(db)
        forecast = inspector.capacity_forecast()
        for status in WIP_CAPS:
            assert forecast[status] is None

    def test_already_breached(self, db):
        """Breached cap returns 0."""
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        # Fill blocked cap (3)
        for i in range(3):
            tid = db.create_task(goal_id, f"B{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=ec)
            db.transition(tid, 'in_progress', actor='edge_analyst')
            db.transition(tid, 'blocked', actor='edge_analyst')

        # Add some metrics so forecast has data
        db.save_cycle_metrics({'cycle': 1, 'tasks': 1})

        inspector = LabInspector(db)
        forecast = inspector.capacity_forecast()
        assert forecast['blocked'] == 0


class TestFormatHealthReport:
    """LabInspector.format_health_report() — human-readable output."""

    def test_report_contains_sections(self, db):
        """Report has all expected sections."""
        # Add some data
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 2, 'reviews': 1,
            'errors': 0, 'drain_mode': False,
            'cycle_duration_s': 1.5,
        })

        inspector = LabInspector(db)
        report = inspector.format_health_report()

        assert '<b>Pipeline</b>' in report
        assert '<b>Cap Utilization</b>' in report
        assert '<b>Throughput (24h)</b>' in report
        assert '<b>Drain Mode</b>' in report
        assert '<b>Agents</b>' in report

    def test_report_empty_system(self, db):
        """Report works on empty system."""
        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert '<b>Pipeline</b>' in report
        assert 'Total: 0' in report

    def test_report_shows_approved_queue(self, db):
        """Report shows approved tasks waiting on user."""
        from lab.config import GATEKEEPERS
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        # Create task and move to approved
        tid = db.create_task(goal_id, "Test task", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=ec)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
            db.update_review(tid, reviewer=gk, verdict='approved')
        db.transition(tid, 'todo', actor='boss')
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        # Add peer review and approve
        db.create_review(tid, reviewer='risk_governor')
        db.update_review(tid, reviewer='risk_governor', verdict='approved')
        db.transition(tid, 'review', actor='risk_governor')
        db.transition(tid, 'approved', actor='boss')

        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Waiting on user' in report
        assert '1 task(s)' in report


class TestHeartbeatMetricsIntegration:
    """Integration: heartbeat run_once() persists cycle metrics."""

    def test_metrics_saved_after_cycle(self, db):
        """run_once() saves cycle metrics to DB."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)

        class MockAgent:
            name = 'test_agent'
            role = 'Test'
            def heartbeat(self):
                return {'reviews': 2, 'tasks': 3, 'promotions': 1, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [MockAgent()])
            loop.run_once()

        metrics = db.get_cycle_metrics(limit=1)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.cycle == 1
        assert m.reviews == 2
        assert m.tasks == 3
        assert m.promotions == 1
        assert m.errors == 0
        assert m.agent_count == 1
        assert m.cycle_duration_s > 0

    def test_drain_cycles_persisted(self, db):
        """Drain cycle count persisted in metrics."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.drain_mode_entered = MagicMock()

        class MockAgent:
            name = 'test_agent'
            role = 'Test'
            def heartbeat(self):
                return {'reviews': 0, 'tasks': 1, 'promotions': 0, 'errors': 0}

        # Fill blocked cap to trigger drain
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        ec = {
            'scope': 'reports/lab/*', 'dod': 'Test',
            'artifact': 'reports/lab/x.json',
            'write_surface': "['lab/lab.db']",
            'stop_condition': 'Error → blocked',
        }
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = db.create_task(goal_id, f"B{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=ec)
            db.transition(tid, 'in_progress', actor='edge_analyst')
            db.transition(tid, 'blocked', actor='edge_analyst')

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [MockAgent()])
            loop.run_once()  # drain_cycles = 1
            loop.run_once()  # drain_cycles = 2

        metrics = db.get_cycle_metrics(limit=2)
        assert metrics[0].drain_mode is True
        assert metrics[0].drain_cycles == 2  # newest first

    def test_multiple_cycles_all_persisted(self, db):
        """Multiple cycles all stored."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)

        class MockAgent:
            name = 'test_agent'
            role = 'Test'
            call_count = 0
            def heartbeat(self):
                self.call_count += 1
                return {'reviews': 0, 'tasks': self.call_count,
                        'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [MockAgent()])
            loop.run_once()
            loop.run_once()
            loop.run_once()

        metrics = db.get_cycle_metrics(limit=10)
        assert len(metrics) == 3
        # Newest first: cycle 3, 2, 1
        assert metrics[0].tasks == 3
        assert metrics[1].tasks == 2
        assert metrics[2].tasks == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
