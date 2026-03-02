"""Tests for lab/resilience.py — circuit breaker + blocked task auto-retry."""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.resilience import (
    CIRCUIT_COOLDOWN_S,
    CIRCUIT_ERROR_THRESHOLD,
    CIRCUIT_MAX_OPEN_PERIODS,
    RETRY_MAX_ATTEMPTS,
    RETRY_MIN_AGE_S,
    AgentCircuit,
    CircuitBreakerRegistry,
    CircuitState,
)


# ── AgentCircuit unit tests ──────────────────────────────────

class TestAgentCircuit:
    """Per-agent circuit breaker state machine."""

    def test_initial_state_closed(self):
        c = AgentCircuit(agent_name='test')
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 0
        assert c.total_errors == 0
        assert c.open_count == 0

    def test_record_success_stays_closed(self):
        c = AgentCircuit(agent_name='test')
        c.record_success()
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 0

    def test_single_error_stays_closed(self):
        c = AgentCircuit(agent_name='test')
        c.record_error("boom")
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 1
        assert c.total_errors == 1

    def test_threshold_errors_opens_circuit(self):
        c = AgentCircuit(agent_name='test')
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c.record_error(f"error {i}")
        assert c.state == CircuitState.OPEN
        assert c.open_count == 1
        assert c.consecutive_errors == CIRCUIT_ERROR_THRESHOLD

    def test_success_after_errors_resets(self):
        c = AgentCircuit(agent_name='test')
        c.record_error("e1")
        c.record_error("e2")
        c.record_success()
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 0
        assert c.total_errors == 2  # total not reset

    def test_should_skip_when_closed(self):
        c = AgentCircuit(agent_name='test')
        assert c.should_skip() is False

    def test_should_skip_when_open_in_cooldown(self):
        c = AgentCircuit(agent_name='test')
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c.record_error(f"e{i}")
        assert c.state == CircuitState.OPEN
        assert c.should_skip() is True

    def test_should_skip_transitions_half_open_after_cooldown(self):
        c = AgentCircuit(agent_name='test')
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c.record_error(f"e{i}")
        # Fake: cooldown elapsed
        c.last_open_time = time.time() - CIRCUIT_COOLDOWN_S - 1
        assert c.should_skip() is False
        assert c.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_attempt(self):
        c = AgentCircuit(agent_name='test')
        c.state = CircuitState.HALF_OPEN
        assert c.should_skip() is False

    def test_half_open_success_closes(self):
        c = AgentCircuit(agent_name='test')
        c.state = CircuitState.HALF_OPEN
        c.consecutive_errors = 3
        c.record_success()
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 0

    def test_half_open_failure_reopens(self):
        c = AgentCircuit(agent_name='test')
        c.state = CircuitState.HALF_OPEN
        c.consecutive_errors = CIRCUIT_ERROR_THRESHOLD - 1
        c.record_error("still broken")
        assert c.state == CircuitState.OPEN
        assert c.open_count == 1

    def test_needs_escalation_false_initially(self):
        c = AgentCircuit(agent_name='test')
        assert c.needs_escalation is False

    def test_needs_escalation_after_max_opens(self):
        c = AgentCircuit(agent_name='test')
        c.open_count = CIRCUIT_MAX_OPEN_PERIODS
        assert c.needs_escalation is True

    def test_error_msg_truncated(self):
        c = AgentCircuit(agent_name='test')
        long_msg = "x" * 500
        c.record_error(long_msg)
        assert len(c.last_error_msg) == 200

    def test_total_errors_accumulates(self):
        c = AgentCircuit(agent_name='test')
        for i in range(5):
            c.record_error(f"e{i}")
            if i < CIRCUIT_ERROR_THRESHOLD - 1:
                pass  # Still building up
        # Reset with success
        c.record_success()
        for i in range(2):
            c.record_error(f"e{i}")
        assert c.total_errors == 7
        assert c.consecutive_errors == 2

    def test_multiple_open_close_cycles(self):
        """Circuit can open, half-open, close, then open again.

        v1.1.0: open_count resets on HALF_OPEN → CLOSED recovery,
        so after successful recovery + re-trip, open_count is 1 (not 2).
        """
        c = AgentCircuit(agent_name='test')

        # Cycle 1: open
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c.record_error(f"e{i}")
        assert c.state == CircuitState.OPEN
        assert c.open_count == 1

        # Half-open after cooldown
        c.last_open_time = time.time() - CIRCUIT_COOLDOWN_S - 1
        c.should_skip()
        assert c.state == CircuitState.HALF_OPEN

        # Success closes — open_count resets (v1.1.0 fix)
        c.record_success()
        assert c.state == CircuitState.CLOSED
        assert c.open_count == 0  # Reset on recovery

        # Cycle 2: open again — fresh count
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c.record_error(f"e{i}")
        assert c.state == CircuitState.OPEN
        assert c.open_count == 1  # Fresh start after recovery


# ── CircuitBreakerRegistry tests ─────────────────────────────

class TestCircuitBreakerRegistry:
    """Registry managing multiple agent circuits."""

    def test_get_creates_new(self):
        reg = CircuitBreakerRegistry()
        c = reg.get('agent_a')
        assert c.agent_name == 'agent_a'
        assert c.state == CircuitState.CLOSED

    def test_get_returns_same_instance(self):
        reg = CircuitBreakerRegistry()
        c1 = reg.get('agent_a')
        c2 = reg.get('agent_a')
        assert c1 is c2

    def test_all_circuits(self):
        reg = CircuitBreakerRegistry()
        reg.get('a')
        reg.get('b')
        reg.get('c')
        assert len(reg.all_circuits()) == 3

    def test_open_circuits_empty(self):
        reg = CircuitBreakerRegistry()
        reg.get('a')
        assert reg.open_circuits() == []

    def test_open_circuits_returns_open_only(self):
        reg = CircuitBreakerRegistry()
        c_good = reg.get('good')
        c_bad = reg.get('bad')
        for i in range(CIRCUIT_ERROR_THRESHOLD):
            c_bad.record_error(f"e{i}")
        open_list = reg.open_circuits()
        assert len(open_list) == 1
        assert open_list[0].agent_name == 'bad'

    def test_escalation_needed(self):
        reg = CircuitBreakerRegistry()
        c = reg.get('fragile')
        c.open_count = CIRCUIT_MAX_OPEN_PERIODS
        esc = reg.escalation_needed()
        assert len(esc) == 1
        assert esc[0].agent_name == 'fragile'

    def test_summary(self):
        reg = CircuitBreakerRegistry()
        reg.get('a').record_error("e1")
        summary = reg.summary()
        assert 'a' in summary
        assert summary['a']['state'] == 'closed'
        assert summary['a']['total_errors'] == 1


# ── Heartbeat + Circuit Breaker integration ──────────────────

class TestHeartbeatCircuitBreaker:
    """Integration: circuit breaker in heartbeat run_once()."""

    @pytest.fixture
    def db(self, tmp_path):
        from lab.db import LabDB
        d = LabDB(db_path=tmp_path / 'test.db')
        d.init_schema()
        yield d
        d.close()

    @pytest.fixture
    def notifier(self):
        from lab.notifier import LabNotifier
        n = LabNotifier(enabled=False)
        n.agent_error = MagicMock()
        n.agent_circuit_open = MagicMock()
        n.agent_circuit_escalation = MagicMock()
        n.heartbeat_summary = MagicMock()
        n.drain_mode_entered = MagicMock()
        n.drain_mode_exited = MagicMock()
        n.cap_breach_alert = MagicMock()
        n.daily_digest = MagicMock()
        n.poll_telegram = MagicMock(return_value=(0, []))
        return n

    def _make_agent(self, name='test', should_fail=False):
        agent = MagicMock()
        agent.name = name
        if should_fail:
            agent.heartbeat.side_effect = RuntimeError(f"{name} crash")
        else:
            agent.heartbeat.return_value = {
                'reviews': 0, 'tasks': 1, 'promotions': 0, 'errors': 0}
        return agent

    def test_circuit_registry_initialized(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        loop = HeartbeatLoop(db, notifier, [])
        assert isinstance(loop._circuits, CircuitBreakerRegistry)

    def test_success_records_on_circuit(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('good')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        c = loop._circuits.get('good')
        assert c.state == CircuitState.CLOSED
        assert c.consecutive_errors == 0

    def test_error_records_on_circuit(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('bad', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            loop.run_once()
        c = loop._circuits.get('bad')
        assert c.consecutive_errors == 1
        assert c.total_errors == 1

    def test_circuit_opens_after_threshold_errors(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('fragile', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            for _ in range(CIRCUIT_ERROR_THRESHOLD):
                loop.run_once()
        c = loop._circuits.get('fragile')
        assert c.state == CircuitState.OPEN
        notifier.agent_circuit_open.assert_called_once_with(
            'fragile', CIRCUIT_ERROR_THRESHOLD, 1)

    def test_open_circuit_skips_agent(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('bad', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])

            # Trip the circuit
            for _ in range(CIRCUIT_ERROR_THRESHOLD):
                loop.run_once()
            assert loop._circuits.get('bad').state == CircuitState.OPEN

            # Next cycle: agent should be skipped
            call_count_before = agent.heartbeat.call_count
            stats = loop.run_once()
            assert agent.heartbeat.call_count == call_count_before
            assert stats['skipped_agents'] == 1

    def test_skipped_agents_in_stats(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        good = self._make_agent('good')
        bad = self._make_agent('bad', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [good, bad])

            # Trip bad's circuit
            for _ in range(CIRCUIT_ERROR_THRESHOLD):
                loop.run_once()

            stats = loop.run_once()
            assert stats['skipped_agents'] == 1
            assert stats['tasks'] == 1  # good agent still runs

    def test_escalation_notified(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('fragile', should_fail=True)
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])

            # Force open_count to MAX-1, then trigger one more open
            circuit = loop._circuits.get('fragile')
            circuit.open_count = CIRCUIT_MAX_OPEN_PERIODS - 1

            # Trip circuit once more
            for _ in range(CIRCUIT_ERROR_THRESHOLD):
                loop.run_once()

            notifier.agent_circuit_escalation.assert_called()

    def test_retries_count_in_stats(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = self._make_agent('good')
        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()
        assert 'retries' in stats
        assert stats['retries'] == 0  # no blocked tasks


# ── Blocked task auto-retry tests ────────────────────────────

class TestBlockedTaskRetry:
    """Heartbeat auto-retry for blocked tasks."""

    @pytest.fixture
    def db(self, tmp_path):
        from lab.db import LabDB
        d = LabDB(db_path=tmp_path / 'test.db')
        d.init_schema()
        yield d
        d.close()

    @pytest.fixture
    def notifier(self):
        from lab.notifier import LabNotifier
        n = LabNotifier(enabled=False)
        n.agent_error = MagicMock()
        n.agent_circuit_open = MagicMock()
        n.agent_circuit_escalation = MagicMock()
        n.heartbeat_summary = MagicMock()
        n.drain_mode_entered = MagicMock()
        n.drain_mode_exited = MagicMock()
        n.cap_breach_alert = MagicMock()
        n.daily_digest = MagicMock()
        n.poll_telegram = MagicMock(return_value=(0, []))
        return n

    def _create_blocked_task(self, db, minutes_ago=20):
        """Create a task in blocked state with custom age."""
        from datetime import datetime, timedelta, timezone
        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(
            goal_id, "Blocked task", 'edge_analyst', 'boss',
            initial_status='todo',
            exit_conditions={
                'scope': 'reports/lab/*', 'dod': 'Test',
                'artifact': 'reports/lab/x.json',
                'write_surface': "['lab/lab.db']",
                'stop_condition': 'Error → blocked',
            },
        )
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'blocked', actor='edge_analyst')

        # Backdate blocked_since
        blocked_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        db.conn.execute(
            "UPDATE tasks SET blocked_since = ? WHERE id = ?",
            (blocked_time.strftime('%Y-%m-%d %H:%M:%S'), tid),
        )
        db.conn.commit()
        return tid, goal_id

    def test_retry_old_blocked_task(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        tid, _ = self._create_blocked_task(db, minutes_ago=20)

        agent = MagicMock()
        agent.name = 'edge_analyst'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()

        assert stats['retries'] == 1
        task = db.get_task(tid)
        assert task.status == 'in_progress'

        # Verify retry comment
        comments = db.get_comments(tid)
        retry_comments = [c for c in comments if '🔄 Auto-retry' in c.body]
        assert len(retry_comments) == 1

    def test_no_retry_young_blocked_task(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        tid, _ = self._create_blocked_task(db, minutes_ago=5)

        agent = MagicMock()
        agent.name = 'edge_analyst'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()

        assert stats['retries'] == 0
        task = db.get_task(tid)
        assert task.status == 'blocked'

    def test_max_retries_respected(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        tid, _ = self._create_blocked_task(db, minutes_ago=20)

        # Add RETRY_MAX_ATTEMPTS worth of retry comments
        for i in range(RETRY_MAX_ATTEMPTS):
            db.add_comment(
                tid, 'heartbeat',
                f"🔄 Auto-retry #{i + 1}/{RETRY_MAX_ATTEMPTS}",
                'comment',
            )

        agent = MagicMock()
        agent.name = 'edge_analyst'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()

        assert stats['retries'] == 0
        task = db.get_task(tid)
        assert task.status == 'blocked'  # still blocked

    def test_retry_blocked_by_wip_cap(self, db, notifier):
        """Retry respects WIP cap — blocked→in_progress fails at cap."""
        from lab.heartbeat import HeartbeatLoop
        from lab.config import WIP_CAPS

        goal_id = db.create_goal("Test", agents=['edge_analyst'])

        # Create blocked task first (before cap is full)
        tid, _ = self._create_blocked_task(db, minutes_ago=20)

        # Fill in_progress cap AFTER blocked task exists
        ip_cap = WIP_CAPS['in_progress']
        for _ in range(ip_cap):
            t = db.create_task(
                goal_id, "Fill IP", 'edge_analyst', 'boss',
                initial_status='todo',
                exit_conditions={
                    'scope': 'reports/lab/*', 'dod': 'Test',
                    'artifact': 'reports/lab/x.json',
                    'write_surface': "['lab/lab.db']",
                    'stop_condition': 'Error → blocked',
                },
            )
            db.transition(t, 'in_progress', actor='edge_analyst')

        agent = MagicMock()
        agent.name = 'edge_analyst'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()

        # Retry should fail silently (cap reached)
        assert stats['retries'] == 0
        task = db.get_task(tid)
        assert task.status == 'blocked'

    def test_no_retry_without_blocked_since(self, db, notifier):
        """Tasks without blocked_since are skipped."""
        from lab.heartbeat import HeartbeatLoop

        goal_id = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(
            goal_id, "No blocked_since", 'edge_analyst', 'boss',
            initial_status='todo',
            exit_conditions={
                'scope': 'reports/lab/*', 'dod': 'Test',
                'artifact': 'reports/lab/x.json',
                'write_surface': "['lab/lab.db']",
                'stop_condition': 'Error → blocked',
            },
        )
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'blocked', actor='edge_analyst')

        # Clear blocked_since
        db.conn.execute(
            "UPDATE tasks SET blocked_since = NULL WHERE id = ?", (tid,))
        db.conn.commit()

        agent = MagicMock()
        agent.name = 'edge_analyst'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}

        with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0), \
             patch('lab.heartbeat.DAILY_DIGEST_INTERVAL_S', 999999):
            loop = HeartbeatLoop(db, notifier, [agent])
            stats = loop.run_once()

        assert stats['retries'] == 0


# ── Notifier circuit breaker methods ─────────────────────────

class TestNotifierCircuitMethods:
    """LabNotifier methods for circuit breaker alerts."""

    def test_agent_circuit_open_disabled(self):
        from lab.notifier import LabNotifier
        n = LabNotifier(enabled=False)
        # Should not raise
        n.agent_circuit_open('test', 3, 1)

    def test_agent_circuit_escalation_disabled(self):
        from lab.notifier import LabNotifier
        n = LabNotifier(enabled=False)
        # Should not raise
        n.agent_circuit_escalation('test', 3, 'some error')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
