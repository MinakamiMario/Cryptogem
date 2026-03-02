"""Tests for Guardrail v1 — Flow Control.

Covers:
- WIP caps enforcement in db.transition()
- Drain mode detection and forbidden transitions
- Exit conditions validation
- Proposal creation blocked in drain mode
- Boss backpressure in drain mode
- Task model get_missing_exit_conditions()
- Notifier daily_digest + cap_breach_alert
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import EXIT_CONDITIONS, VALID_TRANSITIONS, WIP_CAPS
from lab.db import LabDB
from lab.models import Task


@pytest.fixture
def db(tmp_path):
    """Create a fresh DB in a temp directory."""
    db_path = tmp_path / 'test_guardrails.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def goal_id(db):
    """Create a default goal and return its ID."""
    return db.create_goal(
        title="Test DD reduction",
        agents=['risk_governor', 'robustness_auditor', 'edge_analyst', 'boss'],
        description="Test goal for guardrails",
        tasks_per_day=20,  # high limit for testing
    )


def _make_exit_conditions() -> dict:
    """Create a valid exit conditions dict."""
    return {
        'scope': 'reports/lab/test_*',
        'dod': 'JSON+MD report with DD% and Calmar ratio',
        'artifact': 'reports/lab/test_42/test_42.json',
        'write_surface': "['lab/lab.db', 'reports/lab/']",
        'stop_condition': 'Backtest returns None → blocked',
    }


def _task_to_in_progress(db, goal_id, agent='edge_analyst',
                          with_exit_conditions=True):
    """Helper: create task and move to in_progress."""
    ec = _make_exit_conditions() if with_exit_conditions else None
    tid = db.create_task(
        goal_id, f"Task by {agent}", agent, 'boss',
        initial_status='todo', exit_conditions=ec,
    )
    db.transition(tid, 'in_progress', actor=agent)
    return tid


# ═══════════════════════════════════════════════════════════
# WIP Caps
# ═══════════════════════════════════════════════════════════


class TestWIPCaps:
    """WIP cap enforcement in db.transition()."""

    def test_cap_blocks_transition_into_full_status(self, db, goal_id):
        """Transition into a status at cap should be blocked."""
        cap = WIP_CAPS['in_progress']
        # Fill up in_progress to cap
        for i in range(cap):
            _task_to_in_progress(db, goal_id, agent='edge_analyst')

        # Next todo→in_progress should fail
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "One too many", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        with pytest.raises(ValueError, match="WIP cap reached"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_cap_allows_under_limit(self, db, goal_id):
        """Transition allowed when count < cap."""
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "First task", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        # Should not raise — 0 < cap
        db.transition(tid, 'in_progress', actor='edge_analyst')
        assert db.get_task(tid).status == 'in_progress'

    def test_pipeline_transitions_respect_caps(self, db, goal_id):
        """in_progress→peer_review also respects peer_review cap."""
        cap = WIP_CAPS['peer_review']
        # Pre-create test task in in_progress BEFORE drain kicks in
        extra_tid = _task_to_in_progress(db, goal_id)

        # Fill peer_review to cap
        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'peer_review', actor='edge_analyst')

        # Now extra_tid's in_progress→peer_review should fail (cap hit)
        with pytest.raises(ValueError, match="WIP cap reached"):
            db.transition(extra_tid, 'peer_review', actor='edge_analyst')

    def test_blocked_cap(self, db, goal_id):
        """blocked status has its own cap."""
        cap = WIP_CAPS['blocked']
        # Pre-create test task in in_progress BEFORE drain kicks in
        extra_tid = _task_to_in_progress(db, goal_id)

        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'blocked', actor='edge_analyst')

        # Now extra_tid's in_progress→blocked should fail (cap hit)
        with pytest.raises(ValueError, match="WIP cap reached"):
            db.transition(extra_tid, 'blocked', actor='edge_analyst')

    def test_proposal_cap_on_create(self, db, goal_id):
        """Proposal cap enforced at create_task level."""
        cap = WIP_CAPS['proposal']
        for i in range(cap):
            db.create_task(
                goal_id, f"Proposal {i}", 'edge_analyst', 'boss',
                initial_status='proposal',
            )
        # Next proposal should fail
        with pytest.raises(ValueError, match="WIP cap reached"):
            db.create_task(
                goal_id, "One too many", 'edge_analyst', 'boss',
                initial_status='proposal',
            )


# ═══════════════════════════════════════════════════════════
# Drain Mode
# ═══════════════════════════════════════════════════════════


class TestDrainMode:
    """Drain mode detection and forbidden transitions."""

    def test_no_drain_mode_when_empty(self, db):
        """Empty DB → no drain mode."""
        assert db.is_drain_mode() is False

    def test_drain_mode_activates_on_cap_hit(self, db, goal_id):
        """Drain mode activates when ANY cap is hit."""
        cap = WIP_CAPS['in_progress']
        for i in range(cap):
            _task_to_in_progress(db, goal_id)
        assert db.is_drain_mode() is True

    def test_drain_mode_blocks_todo_to_in_progress(self, db, goal_id):
        """Drain mode forbids todo→in_progress."""
        # Hit a cap (blocked is easiest with cap=3)
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        # New todo→in_progress should be forbidden
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "Blocked by drain", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        with pytest.raises(ValueError, match="Drain mode active"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_drain_mode_blocks_proposal_to_todo(self, db, goal_id):
        """Drain mode forbids proposal→todo."""
        # Create a fully-approved proposal BEFORE triggering drain
        tid = db.create_task(
            goal_id, "Approved proposal", 'edge_analyst', 'boss',
            initial_status='proposal',
        )
        db.create_review(tid, 'risk_governor')
        db.create_review(tid, 'robustness_auditor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.update_review(tid, 'robustness_auditor', 'approved')

        # Now hit a cap to trigger drain
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            t = _task_to_in_progress(db, goal_id)
            db.transition(t, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        with pytest.raises(ValueError, match="Drain mode active"):
            db.transition(tid, 'todo', actor='boss')

    def test_drain_mode_blocks_new_proposals(self, db, goal_id):
        """Drain mode forbids create_task(initial_status='proposal')."""
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        with pytest.raises(ValueError, match="Drain mode active"):
            db.create_task(
                goal_id, "New proposal", 'edge_analyst', 'boss',
                initial_status='proposal',
            )

    def test_drain_mode_allows_pipeline_transitions(self, db, goal_id):
        """Drain mode allows in_progress→peer_review (draining)."""
        # Pre-create task in in_progress BEFORE drain triggers
        tid = _task_to_in_progress(db, goal_id)

        # Fill blocked cap to trigger drain
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            t = _task_to_in_progress(db, goal_id)
            db.transition(t, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        # in_progress→peer_review should still work (draining pipeline)
        db.transition(tid, 'peer_review', actor='edge_analyst')
        assert db.get_task(tid).status == 'peer_review'

    def test_drain_mode_allows_approved_to_done(self, db, goal_id):
        """Drain mode allows approved→done (user action)."""
        # Set up a task at approved
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "Approved task", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'risk_governor')
        db.update_review(tid, 'risk_governor', 'approved')
        db.transition(tid, 'review', actor='boss')
        db.transition(tid, 'approved', actor='boss')

        # Now trigger drain mode
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            t = _task_to_in_progress(db, goal_id)
            db.transition(t, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        # approved→done should still work
        db.transition(tid, 'done', actor='user')
        assert db.get_task(tid).status == 'done'

    def test_get_cap_breaches(self, db, goal_id):
        """get_cap_breaches returns only statuses at/above cap."""
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'blocked', actor='edge_analyst')

        breaches = db.get_cap_breaches()
        assert 'blocked' in breaches
        count, cap_val = breaches['blocked']
        assert count >= cap_val

    def test_no_breaches_when_empty(self, db):
        """No breaches on empty DB."""
        assert db.get_cap_breaches() == {}


# ═══════════════════════════════════════════════════════════
# Exit Conditions
# ═══════════════════════════════════════════════════════════


class TestExitConditions:
    """Exit condition validation for todo→in_progress."""

    def test_task_with_exit_conditions_can_start(self, db, goal_id):
        """Task with all 5 exit conditions can transition to in_progress."""
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "Complete task", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        db.transition(tid, 'in_progress', actor='edge_analyst')
        assert db.get_task(tid).status == 'in_progress'

    def test_task_without_exit_conditions_blocked(self, db, goal_id):
        """Task without exit conditions cannot start."""
        tid = db.create_task(
            goal_id, "No EC task", 'edge_analyst', 'boss',
            initial_status='todo',
        )
        with pytest.raises(ValueError, match="Exit conditions missing"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_task_partial_exit_conditions_blocked(self, db, goal_id):
        """Task with partial exit conditions cannot start."""
        partial_ec = {
            'scope': 'reports/lab/',
            'dod': 'A report',
            # Missing: artifact, write_surface, stop_condition
        }
        tid = db.create_task(
            goal_id, "Partial EC", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=partial_ec,
        )
        with pytest.raises(ValueError, match="Exit conditions missing"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_missing_exit_conditions_lists_fields(self, db, goal_id):
        """Error message includes which fields are missing."""
        partial_ec = {'scope': 'x', 'dod': 'y'}
        tid = db.create_task(
            goal_id, "Partial", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=partial_ec,
        )
        with pytest.raises(ValueError, match="artifact"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_exit_conditions_stored_and_retrieved(self, db, goal_id):
        """Exit conditions round-trip through DB correctly."""
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "EC task", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        task = db.get_task(tid)
        assert task.exit_conditions == ec
        assert task.exit_conditions['scope'] == 'reports/lab/test_*'
        assert task.exit_conditions['stop_condition'] == \
            'Backtest returns None → blocked'

    def test_exit_conditions_not_checked_for_other_transitions(
            self, db, goal_id):
        """Exit conditions only checked for todo→in_progress."""
        # in_progress→peer_review should NOT check exit conditions
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "Task", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        db.transition(tid, 'in_progress', actor='edge_analyst')
        # Should work fine without re-checking EC
        db.transition(tid, 'peer_review', actor='edge_analyst')
        assert db.get_task(tid).status == 'peer_review'

    def test_set_exit_conditions(self, db, goal_id):
        """set_exit_conditions updates existing task."""
        tid = db.create_task(
            goal_id, "No EC", 'edge_analyst', 'boss',
            initial_status='todo',
        )
        # Cannot start without EC
        with pytest.raises(ValueError, match="Exit conditions missing"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

        # Boss sets EC
        db.set_exit_conditions(tid, _make_exit_conditions())

        # Now can start
        db.transition(tid, 'in_progress', actor='edge_analyst')
        assert db.get_task(tid).status == 'in_progress'

    def test_exit_conditions_config_has_five_fields(self):
        """Config EXIT_CONDITIONS has exactly 5 fields per spec."""
        assert len(EXIT_CONDITIONS) == 5
        assert 'scope' in EXIT_CONDITIONS
        assert 'dod' in EXIT_CONDITIONS
        assert 'artifact' in EXIT_CONDITIONS
        assert 'write_surface' in EXIT_CONDITIONS
        assert 'stop_condition' in EXIT_CONDITIONS


# ═══════════════════════════════════════════════════════════
# Task Model — get_missing_exit_conditions()
# ═══════════════════════════════════════════════════════════


class TestTaskExitConditions:
    """Task.get_missing_exit_conditions() method."""

    def test_all_present(self):
        """No missing fields when all are present."""
        task = Task(
            id=1, goal_id=1, title="T", assigned_to="a",
            created_by="b", exit_conditions=_make_exit_conditions(),
        )
        assert task.get_missing_exit_conditions() == []

    def test_none_present(self):
        """All fields missing when exit_conditions is None."""
        task = Task(
            id=1, goal_id=1, title="T", assigned_to="a",
            created_by="b", exit_conditions=None,
        )
        missing = task.get_missing_exit_conditions()
        assert len(missing) == 5
        assert set(missing) == set(EXIT_CONDITIONS)

    def test_partial_present(self):
        """Reports only actually missing fields."""
        task = Task(
            id=1, goal_id=1, title="T", assigned_to="a",
            created_by="b",
            exit_conditions={'scope': 'x', 'dod': 'y', 'artifact': 'z'},
        )
        missing = task.get_missing_exit_conditions()
        assert 'write_surface' in missing
        assert 'stop_condition' in missing
        assert 'scope' not in missing

    def test_empty_string_counts_as_missing(self):
        """Empty string values count as missing."""
        task = Task(
            id=1, goal_id=1, title="T", assigned_to="a",
            created_by="b",
            exit_conditions={
                'scope': 'x', 'dod': '', 'artifact': 'z',
                'write_surface': 'w', 'stop_condition': 's',
            },
        )
        missing = task.get_missing_exit_conditions()
        assert 'dod' in missing


# ═══════════════════════════════════════════════════════════
# Counts & Summary
# ═══════════════════════════════════════════════════════════


class TestCounts:
    """get_task_counts_by_status() and is_drain_mode()."""

    def test_counts_empty_db(self, db):
        """All counts 0 on empty DB."""
        counts = db.get_task_counts_by_status()
        assert all(v == 0 for v in counts.values())

    def test_counts_reflect_tasks(self, db, goal_id):
        """Counts accurately reflect task distribution."""
        # Create 2 backlog tasks
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        db.create_task(goal_id, "T2", 'edge_analyst', 'boss')
        # Create 1 todo task
        db.create_task(
            goal_id, "T3", 'edge_analyst', 'boss',
            initial_status='todo',
        )
        counts = db.get_task_counts_by_status()
        assert counts['backlog'] == 2
        assert counts['todo'] == 1

    def test_is_drain_mode_false_under_caps(self, db, goal_id):
        """Not in drain mode when all counts below caps."""
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        assert db.is_drain_mode() is False


# ═══════════════════════════════════════════════════════════
# Boss Backpressure
# ═══════════════════════════════════════════════════════════


class TestBossBackpressure:
    """Boss skips generate_tasks and proposal promotion in drain mode."""

    def test_boss_skips_generation_in_drain(self, db, goal_id):
        """Boss heartbeat skips task generation when drain mode active."""
        from lab.agents.boss import BossAgent
        notifier = MagicMock()
        notifier.enabled = False
        boss = BossAgent(db, notifier)

        # Fill blocked cap to trigger drain
        cap = WIP_CAPS['blocked']
        for i in range(cap):
            tid = _task_to_in_progress(db, goal_id)
            db.transition(tid, 'blocked', actor='edge_analyst')

        assert db.is_drain_mode() is True

        stats = boss.heartbeat()
        assert stats['drain_mode'] is True
        assert stats['tasks_generated'] == 0
        assert stats['proposals_promoted'] == 0

    def test_boss_generates_when_no_drain(self, db, goal_id):
        """Boss generates tasks normally when not in drain mode."""
        from lab.agents.boss import BossAgent
        notifier = MagicMock()
        notifier.enabled = False
        boss = BossAgent(db, notifier)

        assert db.is_drain_mode() is False

        stats = boss.heartbeat()
        assert stats['drain_mode'] is False
        # May generate 0 if no templates match, but should have tried
        assert 'tasks_generated' in stats


# ═══════════════════════════════════════════════════════════
# Notifier
# ═══════════════════════════════════════════════════════════


class TestNotifierGuardrails:
    """daily_digest and cap_breach_alert methods."""

    def test_daily_digest_runs(self, db, goal_id):
        """daily_digest doesn't crash with data."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)

        # Create some tasks for variety
        db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        _task_to_in_progress(db, goal_id)

        # Should not raise
        notifier.daily_digest(db)

    def test_daily_digest_empty_db(self, db):
        """daily_digest works on empty DB."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier.daily_digest(db)

    def test_cap_breach_alert(self):
        """cap_breach_alert sends correct message."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        # Should not raise
        notifier.cap_breach_alert('in_progress', 4, 3)

    def test_drain_mode_entered(self):
        """drain_mode_entered sends correct message."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier.drain_mode_entered({'blocked': (3, 3)})

    def test_drain_mode_exited(self):
        """drain_mode_exited sends correct message."""
        from lab.notifier import LabNotifier
        notifier = LabNotifier(enabled=False)
        notifier.drain_mode_exited()


# ═══════════════════════════════════════════════════════════
# Schema Migration
# ═══════════════════════════════════════════════════════════


class TestSchemaMigration:
    """exit_conditions column migration."""

    def test_init_schema_idempotent(self, db):
        """init_schema can be called multiple times."""
        db.init_schema()
        db.init_schema()
        # Should not crash, column already exists

    def test_exit_conditions_column_exists(self, db, goal_id):
        """exit_conditions column is present in tasks table."""
        cols = {row[1] for row in
                db.conn.execute("PRAGMA table_info(tasks)").fetchall()}
        assert 'exit_conditions' in cols

    def test_null_exit_conditions(self, db, goal_id):
        """Task without exit_conditions has None."""
        tid = db.create_task(goal_id, "T1", 'edge_analyst', 'boss')
        task = db.get_task(tid)
        assert task.exit_conditions is None


# ═══════════════════════════════════════════════════════════
# Veto Chain Integration
# ═══════════════════════════════════════════════════════════


class TestVetoChain:
    """Full 5-layer veto chain: state machine → gate → cap → drain → EC."""

    def test_state_machine_blocks_first(self, db, goal_id):
        """Invalid transition blocked before caps/drain/EC checks."""
        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "T1", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        # todo → peer_review is invalid
        with pytest.raises(ValueError, match="Invalid transition"):
            db.transition(tid, 'peer_review', actor='edge_analyst')

    def test_gate_blocks_before_cap(self, db, goal_id):
        """Quorum gate blocks before cap check matters."""
        tid = db.create_task(
            goal_id, "Proposal", 'edge_analyst', 'boss',
            initial_status='proposal',
        )
        # No reviews → gate blocks
        with pytest.raises(ValueError, match="review ontbreekt"):
            db.transition(tid, 'todo', actor='boss')

    def test_cap_blocks_before_drain_check(self, db, goal_id):
        """Cap check fires even without explicit drain mode."""
        cap = WIP_CAPS['in_progress']
        for i in range(cap):
            _task_to_in_progress(db, goal_id)

        ec = _make_exit_conditions()
        tid = db.create_task(
            goal_id, "Over cap", 'edge_analyst', 'boss',
            initial_status='todo', exit_conditions=ec,
        )
        # Cap blocks the transition (WIP cap message, not drain)
        with pytest.raises(ValueError, match="WIP cap reached"):
            db.transition(tid, 'in_progress', actor='edge_analyst')

    def test_ec_blocks_after_caps_clear(self, db, goal_id):
        """Exit conditions block even when caps are fine."""
        # No cap issues, but no exit conditions
        tid = db.create_task(
            goal_id, "No EC", 'edge_analyst', 'boss',
            initial_status='todo',
        )
        with pytest.raises(ValueError, match="Exit conditions missing"):
            db.transition(tid, 'in_progress', actor='edge_analyst')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
