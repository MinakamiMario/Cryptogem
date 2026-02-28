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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
