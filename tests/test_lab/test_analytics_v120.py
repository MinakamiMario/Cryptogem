"""Tests for v1.2.0 — per-agent timing + cycle analytics + TG trends.

Covers:
- agent_timings column in cycle_metrics (schema + migration)
- save/load agent_timings as JSON
- get_cycle_metrics_stats() aggregate query
- Heartbeat per-agent timing capture
- TG trends button and callback handler
"""
import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.db import LabDB
from lab.models import CycleMetrics


@pytest.fixture
def db(tmp_path):
    """Create fresh DB for each test."""
    db_path = tmp_path / 'test.db'
    d = LabDB(str(db_path))
    d.init_schema()
    return d


# ═══════════════════════════════════════════════════════════
# agent_timings column + persistence
# ═══════════════════════════════════════════════════════════

class TestAgentTimings:
    """Verify agent_timings field in cycle_metrics."""

    def test_column_exists(self, db):
        """agent_timings column is in cycle_metrics table."""
        cols = {row[1] for row in db.conn.execute(
            "PRAGMA table_info(cycle_metrics)"
        ).fetchall()}
        assert 'agent_timings' in cols

    def test_save_and_load_timings(self, db):
        """agent_timings JSON round-trips correctly."""
        timings = {'boss': 2.5, 'edge_analyst': 1.3, 'risk_governor': 0.8}
        row_id = db.save_cycle_metrics({
            'cycle': 1,
            'reviews': 3,
            'tasks': 2,
            'agent_timings': timings,
        })
        assert row_id > 0

        metrics = db.get_cycle_metrics(limit=1)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.agent_timings == timings
        assert m.agent_timings['boss'] == 2.5

    def test_save_empty_timings(self, db):
        """Empty agent_timings saves as empty dict."""
        db.save_cycle_metrics({'cycle': 1})
        metrics = db.get_cycle_metrics(limit=1)
        assert metrics[0].agent_timings == {}

    def test_save_no_timings_key(self, db):
        """Missing agent_timings key defaults to empty dict."""
        db.save_cycle_metrics({'cycle': 1, 'reviews': 0})
        metrics = db.get_cycle_metrics(limit=1)
        assert metrics[0].agent_timings == {}

    def test_migration_idempotent(self, db):
        """Calling init_schema twice doesn't break agent_timings."""
        timings = {'boss': 3.0}
        db.save_cycle_metrics({'cycle': 1, 'agent_timings': timings})
        db.init_schema()  # Second call
        metrics = db.get_cycle_metrics(limit=1)
        assert metrics[0].agent_timings == timings

    def test_model_default(self):
        """CycleMetrics has empty dict default for agent_timings."""
        m = CycleMetrics(id=1, cycle=1)
        assert m.agent_timings == {}

    def test_corrupt_json_fallback(self, db):
        """Corrupt agent_timings JSON falls back to empty dict."""
        # Insert row with invalid JSON directly
        db.conn.execute(
            "INSERT INTO cycle_metrics "
            "(cycle, reviews, tasks, promotions, errors, "
            " drain_mode, drain_cycles, agent_count, cycle_duration_s,"
            " skipped_agents, retries, agent_timings) "
            "VALUES (1, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0, 'NOT_JSON')"
        )
        db.conn.commit()
        metrics = db.get_cycle_metrics(limit=1)
        assert metrics[0].agent_timings == {}


# ═══════════════════════════════════════════════════════════
# get_cycle_metrics_stats() aggregate query
# ═══════════════════════════════════════════════════════════

class TestCycleMetricsStats:
    """Verify aggregated metrics query."""

    def test_empty_db(self, db):
        """Returns zeros for empty DB."""
        stats = db.get_cycle_metrics_stats(hours=24)
        assert stats['cycles'] == 0
        assert stats['total_tasks'] == 0
        assert stats['avg_duration_s'] == 0.0
        assert stats['avg_agent_time'] == {}
        assert stats['slowest_agent'] is None

    def test_single_cycle(self, db):
        """Stats correct for single cycle."""
        db.save_cycle_metrics({
            'cycle': 1, 'reviews': 5, 'tasks': 3, 'errors': 1,
            'cycle_duration_s': 12.5,
            'agent_timings': {'boss': 4.0, 'edge_analyst': 2.0},
        })
        stats = db.get_cycle_metrics_stats(hours=24)
        assert stats['cycles'] == 1
        assert stats['total_tasks'] == 3
        assert stats['total_reviews'] == 5
        assert stats['total_errors'] == 1
        assert stats['avg_duration_s'] == 12.5
        assert stats['min_duration_s'] == 12.5
        assert stats['max_duration_s'] == 12.5
        assert stats['avg_agent_time']['boss'] == 4.0
        assert stats['slowest_agent'] == 'boss'

    def test_multiple_cycles(self, db):
        """Stats aggregate correctly across cycles."""
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 2, 'reviews': 3, 'errors': 0,
            'cycle_duration_s': 10.0,
            'agent_timings': {'boss': 3.0, 'edge_analyst': 2.0},
        })
        db.save_cycle_metrics({
            'cycle': 2, 'tasks': 4, 'reviews': 1, 'errors': 1,
            'cycle_duration_s': 20.0,
            'agent_timings': {'boss': 5.0, 'edge_analyst': 6.0},
        })
        stats = db.get_cycle_metrics_stats(hours=24)
        assert stats['cycles'] == 2
        assert stats['total_tasks'] == 6
        assert stats['total_reviews'] == 4
        assert stats['total_errors'] == 1
        assert stats['avg_duration_s'] == 15.0
        assert stats['min_duration_s'] == 10.0
        assert stats['max_duration_s'] == 20.0
        # Boss avg: (3+5)/2=4.0, edge avg: (2+6)/2=4.0
        assert stats['avg_agent_time']['boss'] == 4.0
        assert stats['avg_agent_time']['edge_analyst'] == 4.0

    def test_drain_percentage(self, db):
        """Drain percentage computed correctly."""
        db.save_cycle_metrics({
            'cycle': 1, 'drain_mode': True, 'cycle_duration_s': 5.0,
        })
        db.save_cycle_metrics({
            'cycle': 2, 'drain_mode': False, 'cycle_duration_s': 5.0,
        })
        db.save_cycle_metrics({
            'cycle': 3, 'drain_mode': True, 'cycle_duration_s': 5.0,
        })
        stats = db.get_cycle_metrics_stats(hours=24)
        assert stats['drain_pct'] == pytest.approx(66.67, rel=0.01)

    def test_slowest_agent(self, db):
        """Slowest agent is the one with highest average time."""
        db.save_cycle_metrics({
            'cycle': 1,
            'cycle_duration_s': 10.0,
            'agent_timings': {'fast': 1.0, 'slow': 9.0},
        })
        stats = db.get_cycle_metrics_stats(hours=24)
        assert stats['slowest_agent'] == 'slow'


# ═══════════════════════════════════════════════════════════
# Heartbeat per-agent timing capture
# ═══════════════════════════════════════════════════════════

class TestHeartbeatTiming:
    """Verify heartbeat captures per-agent execution time."""

    def test_agent_timings_in_cycle_stats(self, db):
        """run_once() includes agent_timings in cycle_stats."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        # Create a mock agent that takes some time
        agent = MagicMock()
        agent.name = 'test_agent'
        agent.heartbeat.return_value = {
            'reviews': 1, 'tasks': 0, 'promotions': 0, 'errors': 0,
        }

        notifier = LabNotifier(enabled=False)
        with patch('lab.heartbeat.install_shell_guard'):
            with patch('lab.heartbeat.set_violation_callback'):
                loop = HeartbeatLoop(db, notifier, [agent])

        stats = loop.run_once()

        assert 'agent_timings' in stats
        assert 'test_agent' in stats['agent_timings']
        # Timing should be a positive float (near 0 for mocked agent)
        assert stats['agent_timings']['test_agent'] >= 0.0

    def test_multiple_agents_timed(self, db):
        """Each agent gets its own timing entry."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        agents = []
        for name in ['agent_a', 'agent_b', 'agent_c']:
            a = MagicMock()
            a.name = name
            a.heartbeat.return_value = {
                'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0,
            }
            agents.append(a)

        notifier = LabNotifier(enabled=False)
        with patch('lab.heartbeat.install_shell_guard'):
            with patch('lab.heartbeat.set_violation_callback'):
                with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
                    loop = HeartbeatLoop(db, notifier, agents)

        stats = loop.run_once()

        assert len(stats['agent_timings']) == 3
        for name in ['agent_a', 'agent_b', 'agent_c']:
            assert name in stats['agent_timings']

    def test_crashed_agent_no_timing(self, db):
        """Crashed agent doesn't get timing entry."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        good_agent = MagicMock()
        good_agent.name = 'good'
        good_agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0,
        }

        bad_agent = MagicMock()
        bad_agent.name = 'bad'
        bad_agent.heartbeat.side_effect = RuntimeError('boom')

        notifier = LabNotifier(enabled=False)
        with patch('lab.heartbeat.install_shell_guard'):
            with patch('lab.heartbeat.set_violation_callback'):
                with patch('lab.heartbeat.HEARTBEAT_STAGGER_S', 0):
                    loop = HeartbeatLoop(db, notifier, [good_agent, bad_agent])

        stats = loop.run_once()

        # Good agent has timing, bad agent doesn't
        assert 'good' in stats['agent_timings']
        assert 'bad' not in stats['agent_timings']

    def test_timings_persisted_to_db(self, db):
        """Agent timings from heartbeat end up in cycle_metrics."""
        from lab.heartbeat import HeartbeatLoop
        from lab.notifier import LabNotifier

        agent = MagicMock()
        agent.name = 'persist_test'
        agent.heartbeat.return_value = {
            'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0,
        }

        notifier = LabNotifier(enabled=False)
        with patch('lab.heartbeat.install_shell_guard'):
            with patch('lab.heartbeat.set_violation_callback'):
                loop = HeartbeatLoop(db, notifier, [agent])

        loop.run_once()

        metrics = db.get_cycle_metrics(limit=1)
        assert len(metrics) == 1
        assert 'persist_test' in metrics[0].agent_timings


# ═══════════════════════════════════════════════════════════
# TG trends button and callback
# ═══════════════════════════════════════════════════════════

class TestTgTrends:
    """Verify TG trends button and _handle_trends()."""

    def test_trends_button_in_dashboard(self, db):
        """Dashboard includes Trends button."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_with_buttons = MagicMock()

        notifier.send_dashboard(db)

        call_args = notifier._send_with_buttons.call_args
        buttons = call_args[1]['buttons'] if 'buttons' in call_args[1] \
            else call_args[0][1]
        # Find trends button in first row
        button_data = [
            b['callback_data'] for row in buttons for b in row
        ]
        assert 'trends:0' in button_data

    def test_handle_trends_empty_db(self, db):
        """Trends handler works with empty DB."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_trends(db)

        notifier._send_html.assert_called_once()
        sent = notifier._send_html.call_args[0][0]
        assert 'TRENDS' in sent
        assert 'Geen cycle data' in sent

    def test_handle_trends_with_data(self, db):
        """Trends handler formats analytics correctly."""
        from lab.notifier import LabNotifier

        # Seed some metrics
        db.save_cycle_metrics({
            'cycle': 1, 'tasks': 3, 'reviews': 5, 'errors': 1,
            'cycle_duration_s': 15.0,
            'agent_timings': {'boss': 4.0, 'edge_analyst': 2.5},
        })
        db.save_cycle_metrics({
            'cycle': 2, 'tasks': 2, 'reviews': 3, 'errors': 0,
            'cycle_duration_s': 12.0,
            'agent_timings': {'boss': 3.5, 'edge_analyst': 3.0},
        })

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_trends(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'TRENDS' in sent
        assert 'Throughput' in sent
        assert 'Cycles: 2' in sent
        assert 'Tasks: 5' in sent
        assert 'Reviews: 8' in sent
        assert 'Cycle Duration' in sent
        assert 'Agent Timing' in sent
        assert 'boss' in sent

    def test_handle_trends_drain_shown(self, db):
        """Drain percentage shown when > 0."""
        from lab.notifier import LabNotifier

        db.save_cycle_metrics({
            'cycle': 1, 'drain_mode': True,
            'cycle_duration_s': 10.0,
        })
        db.save_cycle_metrics({
            'cycle': 2, 'drain_mode': False,
            'cycle_duration_s': 10.0,
        })

        notifier = LabNotifier(enabled=False)
        notifier._send_html = MagicMock()

        notifier._handle_trends(db)

        sent = notifier._send_html.call_args[0][0]
        assert 'Drain' in sent
        assert '50%' in sent

    def test_trends_callback_processed(self, db):
        """poll_telegram processes trends:0 callback."""
        from lab.notifier import LabNotifier

        notifier = LabNotifier(enabled=False)
        notifier.enabled = True
        notifier._last_update_id = 0
        notifier._update_id_loaded = True

        # Mock API to return a trends callback
        notifier._api = MagicMock(return_value={
            'ok': True,
            'result': [
                {
                    'update_id': 100,
                    'callback_query': {
                        'id': 'cb_123',
                        'data': 'trends:0',
                        'message': {
                            'chat': {'id': notifier._CHAT_ID
                                     if hasattr(notifier, '_CHAT_ID')
                                     else 0},
                            'message_id': 42,
                        },
                    },
                }
            ],
        })

        # Mock internal methods
        notifier._answer_callback = MagicMock()
        notifier._handle_trends = MagicMock()

        # Need to set _CHAT_ID to match — read it from module
        import lab.notifier as notifier_mod
        chat_id = notifier_mod._CHAT_ID

        # Re-mock with correct chat_id
        notifier._api = MagicMock(return_value={
            'ok': True,
            'result': [
                {
                    'update_id': 100,
                    'callback_query': {
                        'id': 'cb_123',
                        'data': 'trends:0',
                        'message': {
                            'chat': {'id': chat_id},
                            'message_id': 42,
                        },
                    },
                }
            ],
        })

        actions, msgs = notifier.poll_telegram(db=db)

        notifier._answer_callback.assert_called_once_with(
            'cb_123', 'Trends worden geladen...')
        notifier._handle_trends.assert_called_once_with(db)
        assert actions == 1
