"""Tests for gate rejection tracking (v1.0.7).

Tests:
- DB table creation and migration
- Gate rejections logged on every gate type
- Query methods (get_gate_rejections, get_gate_rejection_counts)
- LabInspector.gate_health()
- Health report includes gate section
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import EXIT_CONDITIONS, GATEKEEPERS, WIP_CAPS
from lab.db import LabDB
from lab.inspector import LabInspector
from lab.models import GateRejection


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_gate.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def goal_id(db):
    return db.create_goal("Test Goal", agents=['edge_analyst'])


EC_FULL = {
    'scope': 'reports/lab/*',
    'dod': 'Test report',
    'artifact': 'reports/lab/test.json',
    'write_surface': "['lab/lab.db']",
    'stop_condition': 'Error → blocked',
}


# ── Schema & Migration ──────────────────────────────


class TestGateRejectionsSchema:
    """gate_rejections table: creation and migration."""

    def test_table_exists(self, db):
        """gate_rejections table created by init_schema()."""
        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'gate_rejections' in tables

    def test_migration_idempotent(self, db):
        """init_schema() can run multiple times safely."""
        db.init_schema()
        db.init_schema()
        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'gate_rejections' in tables

    def test_log_gate_rejection_stores_row(self, db):
        """_log_gate_rejection() inserts a row."""
        db._log_gate_rejection(
            'wip_cap', 42, 'edge_analyst',
            'todo', 'in_progress', 'WIP cap reached')
        rows = db.conn.execute(
            "SELECT * FROM gate_rejections").fetchall()
        assert len(rows) == 1
        assert rows[0]['gate'] == 'wip_cap'
        assert rows[0]['task_id'] == 42
        assert rows[0]['actor'] == 'edge_analyst'
        assert rows[0]['from_status'] == 'todo'
        assert rows[0]['to_status'] == 'in_progress'
        assert 'WIP cap' in rows[0]['reason']


# ── Gate Rejection Logging ───────────────────────────


class TestGateRejectionLogging:
    """Every gate logs a rejection before raising ValueError."""

    def test_invalid_transition_logged(self, db, goal_id):
        """Invalid state transition → logged as 'invalid_transition'."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo', exit_conditions=EC_FULL)
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'done', actor='edge_analyst')

        rejections = db.get_gate_rejections(hours=1)
        assert len(rejections) == 1
        assert rejections[0].gate == 'invalid_transition'
        assert rejections[0].task_id == tid

    def test_peer_review_quorum_logged(self, db, goal_id):
        """peer_review → review with pending reviews → logged."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo', exit_conditions=EC_FULL)
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, reviewer='risk_governor')

        with pytest.raises(ValueError, match="reviews pending"):
            db.transition(tid, 'review', actor='edge_analyst')

        rejections = db.get_gate_rejections(hours=1, gate='peer_review_quorum')
        assert len(rejections) == 1
        assert rejections[0].task_id == tid

    def test_gatekeeper_quorum_logged(self, db, goal_id):
        """proposal → todo without gatekeeper reviews → logged."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC_FULL)

        with pytest.raises(ValueError, match="review ontbreekt"):
            db.transition(tid, 'todo', actor='boss')

        rejections = db.get_gate_rejections(hours=1, gate='gatekeeper_quorum')
        assert len(rejections) == 1
        assert rejections[0].task_id == tid

    def test_gatekeeper_rejected_verdict_logged(self, db, goal_id):
        """proposal → todo with rejected gatekeeper → logged."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC_FULL)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
        # First approves, second rejects
        db.update_review(tid, reviewer=GATEKEEPERS[0], verdict='approved')
        db.update_review(tid, reviewer=GATEKEEPERS[1], verdict='rejected')

        with pytest.raises(ValueError, match="niet 'approved'"):
            db.transition(tid, 'todo', actor='boss')

        rejections = db.get_gate_rejections(hours=1, gate='gatekeeper_quorum')
        assert len(rejections) == 1

    def test_user_only_done_logged(self, db, goal_id):
        """approved → done by non-user → logged as 'user_only'."""
        # Build task to approved state
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC_FULL)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
            db.update_review(tid, reviewer=gk, verdict='approved')
        db.transition(tid, 'todo', actor='boss')
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, reviewer='risk_governor')
        db.update_review(tid, reviewer='risk_governor', verdict='approved')
        db.transition(tid, 'review', actor='risk_governor')
        db.transition(tid, 'approved', actor='boss')

        with pytest.raises(ValueError, match="Alleen user"):
            db.transition(tid, 'done', actor='boss')

        rejections = db.get_gate_rejections(hours=1, gate='user_only')
        assert len(rejections) == 1
        assert rejections[0].from_status == 'approved'
        assert rejections[0].to_status == 'done'

    def test_user_only_reject_logged(self, db, goal_id):
        """approved → in_progress by non-user → logged as 'user_only'."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC_FULL)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
            db.update_review(tid, reviewer=gk, verdict='approved')
        db.transition(tid, 'todo', actor='boss')
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, reviewer='risk_governor')
        db.update_review(tid, reviewer='risk_governor', verdict='approved')
        db.transition(tid, 'review', actor='risk_governor')
        db.transition(tid, 'approved', actor='boss')

        with pytest.raises(ValueError, match="Alleen user"):
            db.transition(tid, 'in_progress', actor='boss')

        rejections = db.get_gate_rejections(hours=1, gate='user_only')
        assert len(rejections) == 1

    def test_wip_cap_logged(self, db, goal_id):
        """WIP cap breach → logged as 'wip_cap'."""
        cap = WIP_CAPS['in_progress']
        # Fill in_progress to cap
        for i in range(cap):
            tid = db.create_task(goal_id, f"T{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=EC_FULL)
            db.transition(tid, 'in_progress', actor='edge_analyst')

        # One more should fail
        tid_extra = db.create_task(goal_id, "TX", 'edge_analyst', 'boss',
                                   initial_status='todo',
                                   exit_conditions=EC_FULL)

        with pytest.raises(ValueError, match="WIP cap reached"):
            db.transition(tid_extra, 'in_progress', actor='edge_analyst')

        rejections = db.get_gate_rejections(hours=1, gate='wip_cap')
        assert len(rejections) == 1
        assert rejections[0].task_id == tid_extra

    def test_drain_mode_logged(self, db, goal_id):
        """Drain mode block → logged as 'drain_mode'."""
        # Fill blocked cap to trigger drain
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = db.create_task(goal_id, f"B{i}", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=EC_FULL)
            db.transition(tid, 'in_progress', actor='edge_analyst')
            db.transition(tid, 'blocked', actor='edge_analyst')

        # Now todo → in_progress should be forbidden
        tid_new = db.create_task(goal_id, "New", 'edge_analyst', 'boss',
                                 initial_status='todo', exit_conditions=EC_FULL)

        with pytest.raises(ValueError, match="Drain mode"):
            db.transition(tid_new, 'in_progress', actor='edge_analyst')

        rejections = db.get_gate_rejections(hours=1, gate='drain_mode')
        assert len(rejections) == 1
        assert rejections[0].task_id == tid_new

    def test_exit_conditions_logged(self, db, goal_id):
        """Missing exit conditions → logged as 'exit_conditions'."""
        # Task without exit conditions
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss',
                             initial_status='todo')

        with pytest.raises(ValueError, match="Exit conditions missing"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

        rejections = db.get_gate_rejections(hours=1, gate='exit_conditions')
        assert len(rejections) == 1
        assert rejections[0].task_id == tid


# ── Query Methods ────────────────────────────────────


class TestGateRejectionQueries:
    """get_gate_rejections() and get_gate_rejection_counts()."""

    def test_filter_by_gate(self, db):
        """Filter rejections by gate type."""
        db._log_gate_rejection('wip_cap', 1, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('drain_mode', 2, 'a', 'todo', 'ip', 'drain')
        db._log_gate_rejection('wip_cap', 3, 'a', 'todo', 'ip', 'cap2')

        result = db.get_gate_rejections(hours=1, gate='wip_cap')
        assert len(result) == 2
        assert all(r.gate == 'wip_cap' for r in result)

    def test_filter_by_task_id(self, db):
        """Filter rejections by task_id."""
        db._log_gate_rejection('wip_cap', 1, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('wip_cap', 2, 'a', 'todo', 'ip', 'cap')

        result = db.get_gate_rejections(hours=1, task_id=1)
        assert len(result) == 1
        assert result[0].task_id == 1

    def test_limit_respected(self, db):
        """Limit parameter caps results."""
        for i in range(10):
            db._log_gate_rejection('wip_cap', i, 'a', 'todo', 'ip', f'r{i}')

        result = db.get_gate_rejections(hours=1, limit=3)
        assert len(result) == 3

    def test_counts_by_gate(self, db):
        """get_gate_rejection_counts() groups by gate."""
        db._log_gate_rejection('wip_cap', 1, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('wip_cap', 2, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('drain_mode', 3, 'a', 'todo', 'ip', 'drain')
        db._log_gate_rejection('user_only', 4, 'a', 'ap', 'done', 'user')

        counts = db.get_gate_rejection_counts(hours=1)
        assert counts['wip_cap'] == 2
        assert counts['drain_mode'] == 1
        assert counts['user_only'] == 1

    def test_counts_empty(self, db):
        """No rejections → empty dict."""
        counts = db.get_gate_rejection_counts(hours=1)
        assert counts == {}

    def test_returns_gate_rejection_model(self, db):
        """Results are GateRejection dataclass instances."""
        db._log_gate_rejection('wip_cap', 42, 'actor', 'todo', 'ip', 'reason')
        results = db.get_gate_rejections(hours=1)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, GateRejection)
        assert r.gate == 'wip_cap'
        assert r.task_id == 42
        assert r.actor == 'actor'
        assert r.from_status == 'todo'
        assert r.to_status == 'ip'
        assert r.reason == 'reason'
        assert r.created_at != ''

    def test_ordered_newest_first(self, db):
        """Results ordered by created_at DESC."""
        db._log_gate_rejection('a', 1, 'x', 's', 't', 'first')
        db._log_gate_rejection('b', 2, 'x', 's', 't', 'second')

        results = db.get_gate_rejections(hours=1)
        # Newest (last inserted) should be first
        assert results[0].gate == 'b'
        assert results[1].gate == 'a'


# ── Inspector gate_health() ─────────────────────────


class TestInspectorGateHealth:
    """LabInspector.gate_health() — gate rejection analysis."""

    def test_empty(self, db):
        """No rejections → zeros."""
        inspector = LabInspector(db)
        health = inspector.gate_health(hours=24)
        assert health['total_rejections'] == 0
        assert health['by_gate'] == {}
        assert health['top_blocked_tasks'] == []
        assert health['recent'] == []

    def test_with_rejections(self, db):
        """Rejections aggregated correctly."""
        db._log_gate_rejection('wip_cap', 10, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('wip_cap', 10, 'a', 'todo', 'ip', 'cap2')
        db._log_gate_rejection('drain_mode', 20, 'b', 'todo', 'ip', 'drain')

        inspector = LabInspector(db)
        health = inspector.gate_health(hours=24)
        assert health['total_rejections'] == 3
        assert health['by_gate']['wip_cap'] == 2
        assert health['by_gate']['drain_mode'] == 1

    def test_top_blocked_tasks(self, db):
        """Most-blocked tasks identified."""
        for i in range(5):
            db._log_gate_rejection('wip_cap', 42, 'a', 'todo', 'ip', f'r{i}')
        for i in range(3):
            db._log_gate_rejection('wip_cap', 99, 'a', 'todo', 'ip', f'r{i}')

        inspector = LabInspector(db)
        health = inspector.gate_health(hours=24)
        top = health['top_blocked_tasks']
        assert len(top) == 2
        assert top[0] == (42, 5)  # most blocked
        assert top[1] == (99, 3)

    def test_recent_rejections(self, db):
        """Recent rejections list populated."""
        db._log_gate_rejection('wip_cap', 1, 'act', 'todo', 'ip', 'reason1')
        db._log_gate_rejection('drain_mode', 2, 'act', 'pr', 'todo', 'reason2')

        inspector = LabInspector(db)
        health = inspector.gate_health(hours=24)
        recent = health['recent']
        assert len(recent) == 2
        # Newest first
        assert recent[0]['gate'] == 'drain_mode'
        assert recent[0]['task_id'] == 2
        assert recent[1]['gate'] == 'wip_cap'


# ── Health Report Integration ────────────────────────


class TestHealthReportGateSection:
    """format_health_report() includes gate health when rejections exist."""

    def test_no_rejections_no_section(self, db):
        """No rejections → no gate section in report."""
        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Gate Rejections' not in report

    def test_rejections_shown(self, db):
        """Rejections → gate section in report."""
        db._log_gate_rejection('wip_cap', 1, 'a', 'todo', 'ip', 'cap')
        db._log_gate_rejection('wip_cap', 1, 'a', 'todo', 'ip', 'cap2')
        db._log_gate_rejection('drain_mode', 2, 'b', 'todo', 'ip', 'drain')

        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Gate Rejections (24h)' in report
        assert '3' in report  # total
        assert 'wip_cap' in report
        assert 'drain_mode' in report

    def test_most_blocked_shown(self, db):
        """Most blocked task shown in report."""
        for i in range(5):
            db._log_gate_rejection('wip_cap', 42, 'a', 'todo', 'ip', f'r{i}')

        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'Task #42' in report
        assert '5 rejections' in report


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
