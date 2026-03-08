"""Tests for Fase 2 agents — edge_analyst, risk_governor, robustness_auditor, deployment_judge.

Uses a real (in-memory) DB but mocked tools to avoid heavy data loading.
Agents are imported from lab.agents.*; if an agent module doesn't exist yet
the test is skipped via pytest.importorskip().
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.db import LabDB
from lab.models import Task, TaskResult
from lab.notifier import LabNotifier


# ── Fake tool results (shared across all tests) ──────────────

FAKE_BT = {
    'trades': 30, 'wr': 72.0, 'pnl': 3500, 'final_equity': 5500,
    'pf': 3.2, 'dd': 18.0, 'broke': False, 'early_stopped': False,
    'trade_list': [{'pnl_pct': 2.5}] * 30,
    'exit_classes': {
        'A': {'count': 20, 'pnl': 3000},
        'B': {'count': 10, 'pnl': 500},
    },
}

FAKE_ROBUSTNESS = {
    'cid': 'TEST', 'verdict': 'GO',
    'baseline': {'trades': 30, 'pnl': 3500, 'dd': 18, 'wr': 72.0, 'pf': 3.2},
    'walk_forward': {'passed_folds': 4, 'n_folds': 5, 'go': True, 'soft_go': False},
    'monte_carlo': {'ruin_prob_pct': 1.0, 'equity': {'p5': 3000, 'median': 5000, 'p95': 8000}, 'go': True},
    'param_jitter': {'positive_pct': 85, 'go': True},
    'universe': {'n_positive_subsets': 3, 'go': True},
    'fails': [],
}


def _fake_report_result(tmp_path):
    """Build a fake write_report / write_backtest_report return value.

    Also creates the fake files so artifact existence checks pass.
    """
    json_path = tmp_path / 'fake.json'
    md_path = tmp_path / 'fake.md'
    json_path.write_text(json.dumps({'test': True}))
    md_path.write_text('# Fake Report\n')
    return {
        'json_path': str(json_path),
        'md_path': str(md_path),
        'sha256': 'abc123',
        'git_hash': 'def456',
    }


# ── Shared fixtures ──────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_agents.db'
    d = LabDB(db_path=db_path)
    d.init_schema()
    yield d
    d.close()


@pytest.fixture
def notifier():
    return LabNotifier(enabled=False)


@pytest.fixture
def goal_id(db):
    return db.create_goal(
        title="Reduce DD below 15%",
        agents=['edge_analyst', 'risk_governor',
                'robustness_auditor', 'deployment_judge'],
    )


# ── Agent import helpers (skip if not yet created) ───────────

@pytest.fixture
def EdgeAnalyst():
    mod = pytest.importorskip('lab.agents.edge_analyst')
    return mod.EdgeAnalyst


@pytest.fixture
def RiskGovernor():
    mod = pytest.importorskip('lab.agents.risk_governor')
    return mod.RiskGovernor


@pytest.fixture
def RobustnessAuditor():
    mod = pytest.importorskip('lab.agents.robustness_auditor')
    return mod.RobustnessAuditor


@pytest.fixture
def DeploymentJudge():
    mod = pytest.importorskip('lab.agents.deployment_judge')
    return mod.DeploymentJudge


# ═════════════════════════════════════════════════════════════
# Agent attribute tests
# ═════════════════════════════════════════════════════════════

class TestAgentAttributes:
    """Verify each Fase 2 agent has the required class attributes."""

    def test_edge_analyst_attributes(self, EdgeAnalyst, db, notifier):
        agent = EdgeAnalyst(db=db, notifier=notifier)
        assert agent.name == 'edge_analyst'
        assert agent.role != ''
        assert agent.is_llm is False

    def test_risk_governor_attributes(self, RiskGovernor, db, notifier):
        agent = RiskGovernor(db=db, notifier=notifier)
        assert agent.name == 'risk_governor'
        assert agent.role != ''
        assert agent.is_llm is False

    def test_robustness_auditor_attributes(self, RobustnessAuditor, db, notifier):
        agent = RobustnessAuditor(db=db, notifier=notifier)
        assert agent.name == 'robustness_auditor'
        assert agent.role != ''
        assert agent.is_llm is False

    def test_deployment_judge_attributes(self, DeploymentJudge, db, notifier):
        agent = DeploymentJudge(db=db, notifier=notifier)
        assert agent.name == 'deployment_judge'
        assert agent.role != ''
        assert agent.is_llm is False


# ═════════════════════════════════════════════════════════════
# Review tests — each agent can review another's task
# ═════════════════════════════════════════════════════════════

class TestAgentReviews:
    """Test review_task() logic for each Fase 2 agent.

    Creates a task in peer_review with a fake artifact and completion
    comment, then calls agent.review_task() and verifies:
    - A review comment was posted (db.get_comments)
    - The review verdict was set (db.get_reviews_for_task)
    """

    def _setup_reviewable_task(self, db, goal_id, assigned_to, tmp_path):
        """Create a task in peer_review state with artifact + completion comment."""
        tid = db.create_task(
            goal_id=goal_id,
            title=f"Test task by {assigned_to}",
            assigned_to=assigned_to,
            created_by='boss',
        )
        db.transition(tid, 'todo', actor='boss')
        db.set_exit_conditions(tid, {
            'scope': 'reports/lab/test_*',
            'dod': 'Test report',
            'artifact': 'reports/lab/test.json',
            'write_surface': "['lab/lab.db', 'reports/lab/']",
            'stop_condition': 'Error → blocked',
        })
        db.transition(tid, 'in_progress', actor=assigned_to)

        # Set artifact (fake file that actually exists)
        artifact_path = tmp_path / f'artifact_{tid}.json'
        artifact_path.write_text(json.dumps({'result': 'ok'}))
        db.set_artifact(
            tid, str(artifact_path),
            sha256='abc123', git_hash='def456', cmd='test',
        )

        # Post completion comment
        db.add_comment(
            tid, assigned_to,
            "Completed: analysis shows PF=3.2, DD=18%, WR=72%. "
            "All gates pass. See artifact for details.",
            'comment',
        )

        # Move to peer_review
        db.transition(tid, 'peer_review', actor=assigned_to)
        return tid

    def test_edge_analyst_reviews(self, EdgeAnalyst, db, notifier, goal_id,
                                  tmp_path):
        """edge_analyst can review a risk_governor task."""
        tid = self._setup_reviewable_task(db, goal_id, 'risk_governor', tmp_path)
        db.create_review(tid, reviewer='edge_analyst')

        agent = EdgeAnalyst(db=db, notifier=notifier)
        task = db.get_task(tid)
        agent.review_task(task)

        # Verify comment was posted
        comments = db.get_comments(tid)
        review_comments = [c for c in comments if c.agent == 'edge_analyst']
        assert len(review_comments) >= 1, "edge_analyst should post a review comment"

        # Verify verdict was set (no longer pending)
        reviews = db.get_reviews_for_task(tid)
        ea_reviews = [r for r in reviews if r.reviewer == 'edge_analyst']
        assert len(ea_reviews) == 1
        assert ea_reviews[0].verdict in ('approved', 'needs_changes', 'rejected')

    def test_risk_governor_reviews(self, RiskGovernor, db, notifier, goal_id,
                                   tmp_path):
        """risk_governor can review an edge_analyst task."""
        tid = self._setup_reviewable_task(db, goal_id, 'edge_analyst', tmp_path)
        db.create_review(tid, reviewer='risk_governor')

        agent = RiskGovernor(db=db, notifier=notifier)
        task = db.get_task(tid)
        agent.review_task(task)

        comments = db.get_comments(tid)
        review_comments = [c for c in comments if c.agent == 'risk_governor']
        assert len(review_comments) >= 1

        reviews = db.get_reviews_for_task(tid)
        rg_reviews = [r for r in reviews if r.reviewer == 'risk_governor']
        assert len(rg_reviews) == 1
        assert rg_reviews[0].verdict in ('approved', 'needs_changes', 'rejected')

    def test_robustness_auditor_reviews(self, RobustnessAuditor, db, notifier,
                                        goal_id, tmp_path):
        """robustness_auditor can review a risk_governor task."""
        tid = self._setup_reviewable_task(db, goal_id, 'risk_governor', tmp_path)
        db.create_review(tid, reviewer='robustness_auditor')

        agent = RobustnessAuditor(db=db, notifier=notifier)
        task = db.get_task(tid)
        agent.review_task(task)

        comments = db.get_comments(tid)
        review_comments = [c for c in comments if c.agent == 'robustness_auditor']
        assert len(review_comments) >= 1

        reviews = db.get_reviews_for_task(tid)
        ra_reviews = [r for r in reviews if r.reviewer == 'robustness_auditor']
        assert len(ra_reviews) == 1
        assert ra_reviews[0].verdict in ('approved', 'needs_changes', 'rejected')

    def test_deployment_judge_reviews(self, DeploymentJudge, db, notifier,
                                      goal_id, tmp_path):
        """deployment_judge can review a robustness_auditor task."""
        tid = self._setup_reviewable_task(db, goal_id, 'robustness_auditor',
                                          tmp_path)
        db.create_review(tid, reviewer='deployment_judge')

        agent = DeploymentJudge(db=db, notifier=notifier)
        task = db.get_task(tid)
        agent.review_task(task)

        comments = db.get_comments(tid)
        review_comments = [c for c in comments if c.agent == 'deployment_judge']
        assert len(review_comments) >= 1

        reviews = db.get_reviews_for_task(tid)
        dj_reviews = [r for r in reviews if r.reviewer == 'deployment_judge']
        assert len(dj_reviews) == 1
        assert dj_reviews[0].verdict in ('approved', 'needs_changes', 'rejected')


# ═════════════════════════════════════════════════════════════
# E2E heartbeat cycle
# ═════════════════════════════════════════════════════════════

class TestE2ECycle:
    """End-to-end cycle: create tasks, heartbeat, verify state transitions."""

    def test_e2e_heartbeat_cycle(self, db, notifier, goal_id, tmp_path,
                                 EdgeAnalyst, RiskGovernor,
                                 RobustnessAuditor, DeploymentJudge):
        """Create 4 tasks, run mock heartbeat, verify state transitions + reviews.

        Flow:
        1. Create one task per agent, move to 'todo'
        2. Mock tool imports to return fake results
        3. Call agent.heartbeat() for each agent
        4. Verify: tasks moved to peer_review, comments posted, review entries
        5. Cross-review: each agent reviews others' work
        """
        # Build fake report result (creates the files on disk)
        report_result = _fake_report_result(tmp_path)

        # ── Step 1: Create tasks ─────────────────────────────
        agent_names = ['edge_analyst', 'risk_governor',
                       'robustness_auditor', 'deployment_judge']
        task_ids = {}
        for name in agent_names:
            tid = db.create_task(
                goal_id=goal_id,
                title=f"Test task for {name}",
                assigned_to=name,
                created_by='boss',
            )
            db.transition(tid, 'todo', actor='boss')
            db.set_exit_conditions(tid, {
                'scope': 'reports/lab/test_*',
                'dod': 'Test report',
                'artifact': 'reports/lab/test.json',
                'write_surface': "['lab/lab.db', 'reports/lab/']",
                'stop_condition': 'Error → blocked',
            })
            task_ids[name] = tid

        # ── Step 2: Build agents ─────────────────────────────
        agents = {
            'edge_analyst': EdgeAnalyst(db=db, notifier=notifier),
            'risk_governor': RiskGovernor(db=db, notifier=notifier),
            'robustness_auditor': RobustnessAuditor(db=db, notifier=notifier),
            'deployment_judge': DeploymentJudge(db=db, notifier=notifier),
        }

        # ── Step 3: Run heartbeats with mocked tools ─────────
        with patch('lab.tools.backtest_runner.backtest',
                   return_value=FAKE_BT), \
             patch('lab.tools.robustness_runner.run_candidate',
                   return_value=FAKE_ROBUSTNESS), \
             patch('lab.tools.report_writer.write_report',
                   return_value=report_result), \
             patch('lab.tools.report_writer.write_backtest_report',
                   return_value=report_result), \
             patch('lab.tools.report_writer.write_robustness_report',
                   return_value=report_result):

            for name, agent in agents.items():
                stats = agent.heartbeat()
                # Should have worked on at least its own task
                assert stats['tasks'] >= 1 or stats['errors'] == 0, \
                    f"{name} heartbeat failed: {stats}"

        # ── Step 4: Verify tasks moved to peer_review ────────
        for name, tid in task_ids.items():
            task = db.get_task(tid)
            assert task.status == 'peer_review', \
                f"Task for {name} (#{tid}) should be in peer_review, " \
                f"got {task.status}"

            # Should have at least one comment
            comments = db.get_comments(tid)
            agent_comments = [c for c in comments if c.agent == name]
            assert len(agent_comments) >= 1, \
                f"{name} should have posted a completion comment on task #{tid}"

        # ── Step 5: Cross-review ─────────────────────────────
        # Create ALL review entries for ALL tasks first, then run
        # heartbeats for review-only (no rework). Without suppressing
        # rework, strict reviewers (e.g. deployment_judge) trigger
        # rework cycles that reset reviews via peer_review→in_progress
        # transition, causing a never-settling cascade.
        for reviewer_name in agents:
            for task_owner, tid in task_ids.items():
                if task_owner == reviewer_name:
                    continue  # Don't self-review
                db.create_review(tid, reviewer=reviewer_name)

        # Run heartbeats with rework suppressed so agents only review
        with patch('lab.tools.backtest_runner.backtest',
                   return_value=FAKE_BT), \
             patch('lab.tools.robustness_runner.run_candidate',
                   return_value=FAKE_ROBUSTNESS), \
             patch('lab.tools.report_writer.write_report',
                   return_value=report_result), \
             patch('lab.tools.report_writer.write_backtest_report',
                   return_value=report_result), \
             patch('lab.tools.report_writer.write_robustness_report',
                   return_value=report_result), \
             patch.object(db, 'get_my_rejected_tasks', return_value=[]):
            for _name, agent in agents.items():
                agent.heartbeat()

        # ── Step 6: Verify reviews were posted ───────────────
        for task_owner, tid in task_ids.items():
            reviews = db.get_reviews_for_task(tid)
            # Should have reviews from the other 3 agents
            reviewers = {r.reviewer for r in reviews}
            expected_reviewers = set(agent_names) - {task_owner}
            assert expected_reviewers.issubset(reviewers), \
                f"Task #{tid} ({task_owner}) missing reviews from " \
                f"{expected_reviewers - reviewers}"

            # At least some should have a verdict set
            verdicts = [r.verdict for r in reviews if r.reviewer != task_owner]
            non_pending = [v for v in verdicts if v != 'pending']
            assert len(non_pending) >= 1, \
                f"Task #{tid} ({task_owner}) should have at least one " \
                f"non-pending review verdict"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
