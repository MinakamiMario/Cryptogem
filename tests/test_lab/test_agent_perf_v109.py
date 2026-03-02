"""Tests for v1.0.9 — agent performance, shell guard rate limiting, etc.

Covers:
- agent_performance() in LabInspector
- Agent perf in health report
- DB queries: get_agent_task_counts, get_agent_review_counts
- Shell guard violation rate limiting
- Boss template fix (no more 'make check')
"""
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import GATEKEEPERS
from lab.db import LabDB
from lab.inspector import LabInspector


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_v109.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


EC = {
    'scope': 'reports/lab/*', 'dod': 'Test',
    'artifact': 'reports/lab/x.json',
    'write_surface': "['lab/lab.db']",
    'stop_condition': 'Error → blocked',
}


# ── DB: agent task/review counts ─────────────────────────

class TestAgentTaskCounts:
    """get_agent_task_counts() — per-agent task counts by status."""

    def test_empty_db(self, db):
        """No tasks → empty dict."""
        counts = db.get_agent_task_counts()
        assert counts == {}

    def test_single_agent(self, db):
        """Tasks for one agent grouped by status."""
        gid = db.create_goal("Test", agents=['edge_analyst'])
        db.create_task(gid, "T1", 'edge_analyst', 'boss',
                       initial_status='todo', exit_conditions=EC)
        tid2 = db.create_task(gid, "T2", 'edge_analyst', 'boss',
                              initial_status='todo', exit_conditions=EC)
        db.transition(tid2, 'in_progress', actor='edge_analyst')

        counts = db.get_agent_task_counts()
        assert 'edge_analyst' in counts
        assert counts['edge_analyst']['todo'] == 1
        assert counts['edge_analyst']['in_progress'] == 1

    def test_multiple_agents(self, db):
        """Tasks split across agents."""
        gid = db.create_goal("Test", agents=['edge_analyst', 'risk_governor'])
        db.create_task(gid, "T1", 'edge_analyst', 'boss',
                       initial_status='todo', exit_conditions=EC)
        db.create_task(gid, "T2", 'risk_governor', 'boss',
                       initial_status='todo', exit_conditions=EC)

        counts = db.get_agent_task_counts()
        assert counts['edge_analyst']['todo'] == 1
        assert counts['risk_governor']['todo'] == 1


class TestAgentReviewCounts:
    """get_agent_review_counts() — reviews per agent in time window."""

    def test_empty(self, db):
        """No reviews → empty dict."""
        counts = db.get_agent_review_counts(hours=24)
        assert counts == {}

    def test_counts_completed_reviews(self, db):
        """Only counts non-pending reviews."""
        gid = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(gid, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC)
        # Gatekeepers approve (creates non-pending reviews)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
            db.update_review(tid, reviewer=gk, verdict='approved')

        counts = db.get_agent_review_counts(hours=24)
        for gk in GATEKEEPERS:
            assert counts[gk] == 1


# ── Inspector: agent_performance ─────────────────────────

class TestAgentPerformance:
    """LabInspector.agent_performance() — per-agent summary."""

    def test_empty_system(self, db):
        """All agents returned, no tasks or reviews."""
        inspector = LabInspector(db)
        perf = inspector.agent_performance(hours=24)
        # Should have all 10 agents
        assert len(perf) == 10
        for p in perf:
            assert p['done_tasks'] == 0
            assert p['active_tasks'] == 0
            assert p['reviews_24h'] == 0

    def test_agent_with_done_tasks(self, db):
        """Agent with done tasks appears at top."""
        gid = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(gid, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC)

        # Move through pipeline to done
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
        db.transition(tid, 'done', actor='user')

        inspector = LabInspector(db)
        perf = inspector.agent_performance(hours=24)
        # edge_analyst should be first (1 done task)
        assert perf[0]['agent'] == 'edge_analyst'
        assert perf[0]['done_tasks'] == 1

    def test_reviews_counted(self, db):
        """Agents with reviews show review counts."""
        gid = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(gid, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC)
        for gk in GATEKEEPERS:
            db.create_review(tid, reviewer=gk)
            db.update_review(tid, reviewer=gk, verdict='approved')

        inspector = LabInspector(db)
        perf = inspector.agent_performance(hours=24)
        gk_perf = {p['agent']: p for p in perf}
        for gk in GATEKEEPERS:
            assert gk_perf[gk]['reviews_24h'] >= 1

    def test_sorted_by_done_then_reviews(self, db):
        """Performance sorted by done_tasks desc, then reviews desc."""
        inspector = LabInspector(db)
        perf = inspector.agent_performance(hours=24)
        for i in range(len(perf) - 1):
            # done_tasks decreasing, then reviews_24h decreasing
            assert (perf[i]['done_tasks'], perf[i]['reviews_24h']) >= \
                   (perf[i + 1]['done_tasks'], perf[i + 1]['reviews_24h'])


# ── Health report: agent perf section ────────────────────

class TestAgentPerfInReport:
    """Agent performance data appears in format_health_report()."""

    def test_no_perf_section_when_idle(self, db):
        """No agent perf lines when nobody did anything."""
        db.save_cycle_metrics({'cycle': 1, 'tasks': 0})
        inspector = LabInspector(db)
        report = inspector.format_health_report()
        # Should have agents summary but no individual lines
        assert '<b>Agents</b>' in report
        assert 'done, ' not in report

    def test_perf_lines_when_productive(self, db):
        """Agent perf lines when tasks completed."""
        gid = db.create_goal("Test", agents=['edge_analyst'])
        tid = db.create_task(gid, "T1", 'edge_analyst', 'boss',
                             initial_status='proposal', exit_conditions=EC)
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
        db.transition(tid, 'done', actor='user')

        db.save_cycle_metrics({'cycle': 1, 'tasks': 1})
        inspector = LabInspector(db)
        report = inspector.format_health_report()
        assert 'edge_analyst' in report
        assert '1 done' in report


# ── Shell guard: violation rate limiting ─────────────────

class TestShellGuardRateLimit:
    """Violation callback rate-limited to prevent TG spam."""

    def test_first_violation_fires(self):
        """First violation fires the callback."""
        from lab import shell_guard
        # Clear state
        shell_guard._violation_last_fire.clear()
        callback = MagicMock()
        shell_guard._violation_callback = callback

        shell_guard._fire_violation('git')
        callback.assert_called_once_with('git')

        # Cleanup
        shell_guard._violation_callback = None

    def test_rapid_violations_suppressed(self):
        """Rapid violations for same binary suppressed."""
        from lab import shell_guard
        shell_guard._violation_last_fire.clear()
        callback = MagicMock()
        shell_guard._violation_callback = callback

        shell_guard._fire_violation('git')
        shell_guard._fire_violation('git')  # suppressed
        shell_guard._fire_violation('git')  # suppressed

        assert callback.call_count == 1

        # Cleanup
        shell_guard._violation_callback = None

    def test_different_binaries_not_suppressed(self):
        """Different binaries fire independently."""
        from lab import shell_guard
        shell_guard._violation_last_fire.clear()
        callback = MagicMock()
        shell_guard._violation_callback = callback

        shell_guard._fire_violation('git')
        shell_guard._fire_violation('make')

        assert callback.call_count == 2

        # Cleanup
        shell_guard._violation_callback = None

    def test_fires_after_cooldown(self):
        """Same binary fires again after cooldown."""
        from lab import shell_guard
        shell_guard._violation_last_fire.clear()
        callback = MagicMock()
        shell_guard._violation_callback = callback

        shell_guard._fire_violation('git')
        # Simulate cooldown expiry
        shell_guard._violation_last_fire['git'] = time.time() - 60
        shell_guard._fire_violation('git')

        assert callback.call_count == 2

        # Cleanup
        shell_guard._violation_callback = None


# ── Boss template fix ────────────────────────────────────

class TestBossTemplates:
    """Boss task templates no longer reference 'make check'."""

    def test_no_make_check_in_templates(self):
        """Templates don't mention 'make check'."""
        from lab.agents.boss import TASK_TEMPLATES
        for keyword, templates in TASK_TEMPLATES.items():
            for title, agent in templates:
                assert 'make check' not in title.lower(), \
                    f"Template '{title}' still references make check"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
