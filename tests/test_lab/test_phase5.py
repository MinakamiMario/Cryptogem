"""Tests for Fase 5: Polish — shutdown, dashboard, recovery, deploy configs."""
import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import REPO_ROOT, SOULS_DIR
from lab.db import LabDB
from lab.notifier import LabNotifier


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_p5.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def notifier():
    return LabNotifier(enabled=False)


# ── Graceful Shutdown Tests ──────────────────────────────

class TestGracefulShutdown:
    def test_shutdown_method_exists(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = MagicMock()
        agent.name = 'test'
        loop = HeartbeatLoop(db, notifier, [agent])
        assert hasattr(loop, 'shutdown')

    def test_shutdown_stops_loop(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = MagicMock()
        agent.name = 'test'
        loop = HeartbeatLoop(db, notifier, [agent])
        loop.shutdown()
        assert loop._running is False

    def test_current_agent_tracked(self, db, notifier):
        from lab.heartbeat import HeartbeatLoop
        agent = MagicMock()
        agent.name = 'test_agent'
        agent.heartbeat.return_value = {'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}
        loop = HeartbeatLoop(db, notifier, [agent])
        assert loop._current_agent is None
        # After run_once, current_agent should be reset to None
        loop.run_once()
        assert loop._current_agent is None


# ── Error Recovery Tests ─────────────────────────────────

class TestErrorRecovery:
    def test_agent_crash_sets_error_status(self, db, notifier):
        """Agent crash in heartbeat loop marks status as error."""
        from lab.heartbeat import HeartbeatLoop
        # Use a registered agent name so agent_status row exists
        agent = MagicMock()
        agent.name = 'boss'
        agent.heartbeat.side_effect = RuntimeError("boom")

        loop = HeartbeatLoop(db, notifier, [agent])
        stats = loop.run_once()

        assert stats['errors'] == 1
        status = db.get_agent_status('boss')
        assert status is not None
        assert status.status == 'error'

    def test_crash_doesnt_stop_other_agents(self, db, notifier):
        """One agent crash doesn't prevent others from running."""
        from lab.heartbeat import HeartbeatLoop

        crasher = MagicMock()
        crasher.name = 'crasher'
        crasher.heartbeat.side_effect = RuntimeError("boom")

        survivor = MagicMock()
        survivor.name = 'survivor'
        survivor.heartbeat.return_value = {
            'reviews': 1, 'tasks': 0, 'promotions': 0, 'errors': 0
        }

        loop = HeartbeatLoop(db, notifier, [crasher, survivor])
        stats = loop.run_once()

        assert stats['errors'] == 1
        assert stats['reviews'] == 1
        survivor.heartbeat.assert_called_once()

    def test_task_blocked_on_failure(self, db, notifier):
        """Failed task execution moves task to blocked state."""
        goal_id = db.create_goal("Test", agents=['test_agent'])
        tid = db.create_task(goal_id, "Failing task", 'test_agent', 'boss')
        db.transition(tid, 'todo', actor='user')
        db.set_exit_conditions(tid, {
            'scope': 'reports/lab/test_*', 'dod': 'Test report',
            'artifact': 'reports/lab/test.json',
            'write_surface': "['lab/lab.db', 'reports/lab/']",
            'stop_condition': 'Error → blocked',
        })

        # Simulate: agent picks up task, transitions to in_progress, then fails
        db.transition(tid, 'in_progress', actor='test_agent')

        # The agent's error recovery should move it to blocked
        try:
            db.transition(tid, 'blocked', actor='test_agent')
        except ValueError:
            pytest.fail("Should be able to transition in_progress → blocked")

        task = db.get_task(tid)
        assert task.status == 'blocked'


# ── Dashboard Report Tests ───────────────────────────────

class TestDashboardReport:
    def test_report_command_exists(self):
        from lab.main import cmd_report
        assert callable(cmd_report)

    def test_report_with_data(self, db, notifier, capsys):
        """Report generates output with goals and tasks."""
        from lab.main import cmd_report

        # Create some data
        goal_id = db.create_goal("Test Goal", agents=['boss', 'edge_analyst'])
        tid = db.create_task(goal_id, "Test task", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')

        args = MagicMock()
        args.verbose = False
        args.quiet = True
        args.json_output = False

        with patch('lab.main.LabDB', return_value=db):
            # Prevent db.close from actually closing our test db
            with patch.object(db, 'close'):
                cmd_report(args)

        captured = capsys.readouterr()
        assert 'Lab Report' in captured.out or 'LAB STATUS' in captured.out

    def test_report_json_format(self, db, notifier, capsys):
        """Report --json outputs valid JSON."""
        from lab.main import cmd_report

        goal_id = db.create_goal("Test Goal", agents=['boss'])

        args = MagicMock()
        args.verbose = False
        args.quiet = True
        args.json_output = True

        with patch('lab.main.LabDB', return_value=db):
            with patch.object(db, 'close'):
                cmd_report(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert 'goals' in data
        assert 'tasks_by_status' in data
        assert 'agents' in data
        assert 'generated_at' in data


# ── Deploy Configs ───────────────────────────────────────

class TestDeployConfigs:
    def test_launchd_plist_exists(self):
        path = REPO_ROOT / 'lab' / 'deploy' / 'com.cryptogem.lab.plist'
        assert path.exists()
        content = path.read_text()
        assert 'com.cryptogem.lab' in content
        assert 'start-daemon.sh' in content

    def test_systemd_service_exists(self):
        path = REPO_ROOT / 'lab' / 'deploy' / 'lab.service'
        assert path.exists()
        content = path.read_text()
        assert 'lab.main' in content
        assert '[Service]' in content

    def test_deploy_readme_exists(self):
        path = REPO_ROOT / 'lab' / 'deploy' / 'README.md'
        assert path.exists()


# ── ADR ──────────────────────────────────────────────────

class TestADR:
    def test_decisions_md_exists(self):
        path = REPO_ROOT / 'docs' / 'DECISIONS.md'
        assert path.exists()
        content = path.read_text()
        assert 'ADR-LAB-001' in content
        assert 'SQLite' in content
        assert 'Hybrid' in content
        assert 'Write Allowlist' in content or 'WRITE_ALLOWLIST' in content
        assert 'Peer Review' in content or 'peer_review' in content


# ── Soul Files Complete ──────────────────────────────────

class TestAllSoulsComplete:
    """Verify all 5 soul files exist and have VERBODEN."""

    @pytest.mark.parametrize("name", [
        'boss', 'meta_research', 'hypothesis_gen',
        'live_monitor', 'portfolio_architect',
    ])
    def test_soul_exists_with_verboden(self, name):
        path = SOULS_DIR / f'{name}.md'
        assert path.exists(), f"Soul file {name}.md not found"
        content = path.read_text()
        assert 'VERBODEN' in content, f"{name}.md missing VERBODEN"


# ── Makefile Targets ─────────────────────────────────────

class TestMakeTargets:
    def test_makefile_has_lab_targets(self):
        makefile = REPO_ROOT / 'Makefile'
        assert makefile.exists()
        content = makefile.read_text()
        assert 'lab-check' in content
        assert 'lab-tests' in content
        assert 'lab-smoke' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
