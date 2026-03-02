"""Tests for lab/heartbeat.py — heartbeat loop orchestration."""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.db import LabDB
from lab.heartbeat import HeartbeatLoop
from lab.models import Task, TaskResult
from lab.notifier import LabNotifier


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_hb.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def notifier():
    """Disabled notifier (no Telegram)."""
    return LabNotifier(enabled=False)


class MockAgent:
    """Minimal agent for heartbeat tests."""

    def __init__(self, name='test_agent', role='Test', should_fail=False):
        self.name = name
        self.role = role
        self.heartbeat_count = 0
        self.should_fail = should_fail

    def heartbeat(self):
        self.heartbeat_count += 1
        if self.should_fail:
            raise RuntimeError(f"{self.name} crashed")
        return {'reviews': 0, 'tasks': 1, 'promotions': 0, 'errors': 0}


class TestHeartbeatLoop:
    """Core heartbeat loop behavior."""

    def test_single_cycle(self, db, notifier):
        agent = MockAgent('agent_a')
        loop = HeartbeatLoop(db, notifier, [agent])
        stats = loop.run_once()
        assert agent.heartbeat_count == 1
        assert stats['cycle'] == 1
        assert stats['tasks'] == 1

    def test_multiple_agents(self, db, notifier):
        agents = [
            MockAgent('agent_a'),
            MockAgent('agent_b'),
            MockAgent('agent_c'),
        ]
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, agents)
            stats = loop.run_once()
        assert all(a.heartbeat_count == 1 for a in agents)
        assert stats['tasks'] == 3  # 1 per agent

    def test_agent_crash_continues(self, db, notifier):
        """If one agent crashes, the loop continues with the next."""
        agents = [
            MockAgent('good_1'),
            MockAgent('crasher', should_fail=True),
            MockAgent('good_2'),
        ]
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, agents)
            stats = loop.run_once()
        assert agents[0].heartbeat_count == 1
        assert agents[1].heartbeat_count == 1  # tried but crashed
        assert agents[2].heartbeat_count == 1  # still ran
        assert stats['errors'] == 1
        assert stats['tasks'] == 2  # only the two good ones

    def test_cycle_counter_increments(self, db, notifier):
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
            loop.run_once()
            loop.run_once()
        assert loop._cycle == 3
        assert agent.heartbeat_count == 3

    def test_dry_run_stops_after_one(self, db, notifier):
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.HEARTBEAT_INTERVAL_S', 1):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run(dry_run=True)
        assert agent.heartbeat_count == 1
        assert loop._cycle == 1

    def test_max_hours_stops(self, db, notifier):
        """max_hours=0.0001 (~0.36s) should stop quickly."""
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.HEARTBEAT_INTERVAL_S', 0.1):
            loop = HeartbeatLoop(db, notifier, [agent])
            start = time.time()
            loop.run(max_hours=0.0001)
            elapsed = time.time() - start
        assert elapsed < 5  # should stop within a few seconds
        assert agent.heartbeat_count >= 1

    def test_graceful_shutdown(self, db, notifier):
        """Setting _running=False stops the loop."""
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop._running = False
            stats = loop.run_once()
        # No agents should have been called
        assert agent.heartbeat_count == 0

    def test_stats_aggregation(self, db, notifier):
        """Stats from multiple agents are summed."""

        class CustomAgent:
            name = 'custom'
            role = 'Custom'

            def heartbeat(self):
                return {'reviews': 3, 'tasks': 2, 'promotions': 1, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [CustomAgent(), CustomAgent()])
            stats = loop.run_once()
        assert stats['reviews'] == 6
        assert stats['tasks'] == 4
        assert stats['promotions'] == 2
        assert stats['errors'] == 0

    def test_notifier_called_on_crash(self, db, notifier):
        """Agent crash triggers notifier.agent_error()."""
        notifier.agent_error = MagicMock()
        agent = MockAgent('crasher', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        notifier.agent_error.assert_called_once()

    def test_notifier_summary_called(self, db, notifier):
        """Heartbeat summary is sent after each cycle."""
        notifier.heartbeat_summary = MagicMock()
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        notifier.heartbeat_summary.assert_called_once()


class TestHeartbeatWithDB:
    """Integration: heartbeat + real DB operations."""

    def test_agent_status_set_on_crash(self, db, notifier):
        """Crashed agent gets 'error' status in DB."""
        agent = MockAgent('infra_guardian', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        status = db.get_agent_status('infra_guardian')
        assert status.status == 'error'


class TestGuardrailIntegration:
    """Heartbeat loop + Guardrail v1 drain mode & daily digest."""

    def _fill_cap(self, db, goal_id, status='blocked'):
        """Fill a WIP cap to trigger drain mode."""
        from lab.config import WIP_CAPS
        cap = WIP_CAPS[status]
        for _ in range(cap):
            tid = db.create_task(
                goal_id, f"Fill {status}", 'edge_analyst', 'boss',
                initial_status='todo',
                exit_conditions={
                    'scope': 'reports/lab/*', 'dod': 'Test',
                    'artifact': 'reports/lab/x.json',
                    'write_surface': "['lab/lab.db']",
                    'stop_condition': 'Error → blocked',
                },
            )
            db.transition(tid, 'in_progress', actor='edge_analyst')
            if status == 'blocked':
                db.transition(tid, 'blocked', actor='edge_analyst')

    def test_drain_mode_in_cycle_stats(self, db, notifier):
        """run_once() includes drain_mode in stats."""
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()
        assert 'drain_mode' in stats
        assert stats['drain_mode'] is False

    def test_drain_mode_entered_notified(self, db, notifier):
        """Entering drain mode sends TG notification."""
        notifier.drain_mode_entered = MagicMock()
        goal_id = db.create_goal("Test", agents=['edge_analyst'])

        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])

            # Cycle 1: no drain
            stats = loop.run_once()
            assert stats['drain_mode'] is False
            notifier.drain_mode_entered.assert_not_called()

            # Fill blocked cap → drain
            self._fill_cap(db, goal_id, 'blocked')
            assert db.is_drain_mode() is True

            # Cycle 2: drain entered
            stats = loop.run_once()
            assert stats['drain_mode'] is True
            notifier.drain_mode_entered.assert_called_once()

    def test_drain_mode_exited_notified(self, db, notifier):
        """Exiting drain mode sends TG notification."""
        notifier.drain_mode_entered = MagicMock()
        notifier.drain_mode_exited = MagicMock()
        goal_id = db.create_goal("Test", agents=['edge_analyst'])

        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])

            # Fill blocked cap → drain
            self._fill_cap(db, goal_id, 'blocked')
            loop.run_once()  # enters drain
            assert loop._prev_drain_mode is True

            # Clear blocked tasks → exit drain
            for task in db.get_tasks_by_status('blocked'):
                db.set_exit_conditions(task.id, {
                    'scope': 'reports/lab/*', 'dod': 'Test',
                    'artifact': 'reports/lab/x.json',
                    'write_surface': "['lab/lab.db']",
                    'stop_condition': 'Error → blocked',
                })
                db.transition(task.id, 'in_progress', actor='edge_analyst')
                db.transition(task.id, 'peer_review', actor='edge_analyst')
            assert db.is_drain_mode() is False

            loop.run_once()  # exits drain
            notifier.drain_mode_exited.assert_called_once()
            assert loop._prev_drain_mode is False

    def test_cap_breach_escalated_after_threshold(self, db, notifier):
        """Persistent drain mode (>2 cycles) triggers cap_breach_alert."""
        notifier.drain_mode_entered = MagicMock()
        notifier.cap_breach_alert = MagicMock()
        goal_id = db.create_goal("Test", agents=['edge_analyst'])

        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999), \
             patch('lab.heartbeat.CAP_BREACH_ESCALATE_CYCLES', 2):
            loop = HeartbeatLoop(db, notifier, [agent])

            self._fill_cap(db, goal_id, 'blocked')

            # Cycle 1: drain enters (cycle count = 1)
            loop.run_once()
            notifier.cap_breach_alert.assert_not_called()

            # Cycle 2: drain persists (cycle count = 2)
            loop.run_once()
            notifier.cap_breach_alert.assert_not_called()

            # Cycle 3: > threshold → escalate
            loop.run_once()
            notifier.cap_breach_alert.assert_called()

    def test_daily_digest_fires_on_first_cycle(self, db, notifier):
        """Daily digest fires on first heartbeat cycle (time=0)."""
        notifier.daily_digest = MagicMock()
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 0):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        notifier.daily_digest.assert_called_once_with(db)

    def test_daily_digest_skipped_before_interval(self, db, notifier):
        """Daily digest skipped when interval hasn't elapsed."""
        notifier.daily_digest = MagicMock()
        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            # Fake: last digest was just sent
            loop._last_digest_time = time.time()
            loop.run_once()
        notifier.daily_digest.assert_not_called()

    def test_drain_cycles_reset_on_exit(self, db, notifier):
        """Drain cycle counter resets when drain mode exits."""
        notifier.drain_mode_entered = MagicMock()
        notifier.drain_mode_exited = MagicMock()
        goal_id = db.create_goal("Test", agents=['edge_analyst'])

        agent = MockAgent('agent_a')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])

            self._fill_cap(db, goal_id, 'blocked')
            loop.run_once()  # drain enters, _drain_cycles = 1
            loop.run_once()  # _drain_cycles = 2
            assert loop._drain_cycles == 2

            # Clear drain
            for task in db.get_tasks_by_status('blocked'):
                db.set_exit_conditions(task.id, {
                    'scope': 'reports/lab/*', 'dod': 'Test',
                    'artifact': 'reports/lab/x.json',
                    'write_surface': "['lab/lab.db']",
                    'stop_condition': 'Error → blocked',
                })
                db.transition(task.id, 'in_progress', actor='edge_analyst')
                db.transition(task.id, 'peer_review', actor='edge_analyst')

            loop.run_once()  # drain exits
            assert loop._drain_cycles == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
