"""Tests for lab/llm.py and Fase 3 LLM agents — all LLM calls mocked."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import SOULS_DIR
from lab.db import LabDB
from lab.notifier import LabNotifier


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_llm.db'
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
        agents=['boss', 'meta_research', 'hypothesis_gen',
                'edge_analyst', 'risk_governor', 'robustness_auditor'],
    )


# Fake LLM response for meta_research
FAKE_META_RESPONSE = {
    'patterns': [
        {
            'claim': 'DD consistently above 20% for tp_sl configs',
            'confidence': 'high',
            'evidence': ['reports/lab/risk_1/risk_1.json',
                         'reports/lab/risk_2/risk_2.json'],
            'domain': 'dd',
        },
        {
            'claim': 'RSI recovery improves WR by 5-8%',
            'confidence': 'medium',
            'evidence': ['reports/lab/edge_3/edge_3.json'],
            'domain': 'edge',
        },
    ],
    'contradictions': [],
    'recommendations': [
        {
            'action': 'Test max_stop_pct 10-14% range on champion',
            'rationale': 'Consistent DD reduction potential',
            'assigned_to': 'risk_governor',
            'priority': 3,
        },
    ],
    'summary': 'DD remains the primary challenge. RSI recovery shows promise.',
}

# Fake LLM response for hypothesis_gen
FAKE_HYPO_RESPONSE = {
    'hypotheses': [
        {
            'id': 'H001',
            'title': 'Tighter max_stop_pct reduces DD without sacrificing PF',
            'description': 'If max_stop_pct 10-12% instead of 15%, DD drops 3-5%',
            'sweep_params': {'max_stop_pct': {'min': 10, 'max': 14, 'step': 1}},
            'expected_impact': {
                'pf_change': '+0.1 to +0.3',
                'dd_change': '-3% to -5%',
                'trades_change': '±5%',
            },
            'acceptance_criteria': [
                'DD < 20% on full sample',
                'PF > 3.0 on walk-forward',
                'MC ruin < 3%',
            ],
            'evidence_base': ['reports/lab/risk_1/risk_1.json'],
            'tasks': [
                {
                    'title': 'Sweep max_stop_pct 10-14% on champion',
                    'assigned_to': 'risk_governor',
                    'description': 'Run backtest with max_stop_pct = 10,11,12,13,14',
                },
                {
                    'title': 'Robustness check on best max_stop_pct variant',
                    'assigned_to': 'robustness_auditor',
                    'description': 'Full harness on top variant',
                },
            ],
        },
    ],
    'reasoning': 'DD reduction is the top priority per meta-research findings.',
}

# Fake LLM response for boss task gen
FAKE_BOSS_RESPONSE = {
    'tasks': [
        {
            'title': 'Analyze champion DD breakdown by exit class',
            'assigned_to': 'risk_governor',
            'description': 'Break down DD contribution per exit class A/B/C',
        },
        {
            'title': 'RSI recovery sensitivity sweep 40-50 range',
            'assigned_to': 'edge_analyst',
            'description': 'Sweep rsi_rec_target param on champion config',
        },
    ],
    'reasoning': 'Focus on DD reduction and edge refinement per goal.',
}


# ── LLM Client Tests ────────────────────────────────────

class TestLLMClient:
    """Test lab/llm.py core functions."""

    def test_load_soul_exists(self):
        """load_soul returns content for existing soul file."""
        from lab.llm import load_soul
        # Boss soul should exist (we created it)
        if (SOULS_DIR / 'boss.md').exists():
            content = load_soul('boss')
            assert 'Boss' in content or 'boss' in content.lower()

    def test_load_soul_missing(self):
        """load_soul returns empty string for missing agent."""
        from lab.llm import load_soul
        assert load_soul('nonexistent_agent') == ''

    def test_hash_deterministic(self):
        """_hash produces same output for same input."""
        from lab.llm import _hash
        h1 = _hash('test string')
        h2 = _hash('test string')
        assert h1 == h2
        assert len(h1) == 12

    def test_hash_different(self):
        """_hash produces different output for different input."""
        from lab.llm import _hash
        h1 = _hash('test string 1')
        h2 = _hash('test string 2')
        assert h1 != h2

    def test_backoff_increases(self):
        """_backoff produces increasing wait times."""
        from lab.llm import _backoff
        waits = [_backoff(i) for i in range(5)]
        # General trend should be increasing (with jitter)
        assert waits[3] > waits[0]

    def test_backoff_capped(self):
        """_backoff never exceeds 60s."""
        from lab.llm import _backoff
        wait = _backoff(100)
        assert wait <= 60.0

    def test_ask_json_strips_fences(self):
        """ask_json strips markdown code fences from response."""
        from lab.llm import ask_json
        mock_response = '```json\n{"key": "value"}\n```'
        with patch('lab.llm.ask', return_value=mock_response):
            result = ask_json('test prompt')
            assert result == {'key': 'value'}

    def test_ask_json_plain(self):
        """ask_json handles plain JSON without fences."""
        from lab.llm import ask_json
        mock_response = '{"key": "value"}'
        with patch('lab.llm.ask', return_value=mock_response):
            result = ask_json('test prompt')
            assert result == {'key': 'value'}

    def test_api_key_from_env(self):
        """_load_api_key reads from environment."""
        import lab.llm as llm_mod
        llm_mod._api_key = None  # Reset cache
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key-123'}):
            key = llm_mod._load_api_key()
            assert key == 'test-key-123'
        llm_mod._api_key = None  # Cleanup

    def test_api_key_missing_raises(self):
        """_load_api_key raises RuntimeError when no key found."""
        import lab.llm as llm_mod
        llm_mod._api_key = None
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(llm_mod, 'DOTENV_PATH', Path('/nonexistent/.env')):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                llm_mod._load_api_key()
        llm_mod._api_key = None


# ── Meta-Research Agent Tests ────────────────────────────

class TestMetaResearchAgent:
    """Test MetaResearchAgent with mocked LLM."""

    def test_attributes(self, db, notifier):
        from lab.agents.meta_research import MetaResearchAgent
        agent = MetaResearchAgent(db, notifier)
        assert agent.name == 'meta_research'
        assert agent.is_llm is True

    def test_execute_produces_artifact(self, db, notifier, goal_id, tmp_path):
        """execute_task writes JSON+MD artifact to reports/lab/."""
        from lab.agents.meta_research import MetaResearchAgent
        agent = MetaResearchAgent(db, notifier)

        # Create task
        tid = db.create_task(goal_id, "Meta-research scan", 'meta_research',
                             'boss', description="Scan all artifacts")
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        # Mock LLM
        with patch('lab.agents.meta_research.MetaResearchAgent._write_report') as mock_wr, \
             patch('lab.llm.ask_json', return_value=FAKE_META_RESPONSE):
            # Mock _write_report to return a fake path
            fake_json = tmp_path / 'meta.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True
        assert 'patronen' in result.summary.lower() or 'artefact' in result.summary.lower()
        assert result.artifact_path is not None

    def test_execute_no_artifacts(self, db, notifier, goal_id):
        """execute_task succeeds gracefully with empty lab."""
        from lab.agents.meta_research import MetaResearchAgent
        agent = MetaResearchAgent(db, notifier)

        tid = db.create_task(goal_id, "Meta scan", 'meta_research', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        # No reports dir, no artifacts
        with patch.object(agent, '_gather_artifacts', return_value=[]), \
             patch.object(agent, '_read_decisions', return_value=''):
            result = agent.execute_task(task)

        assert result.success is True
        assert 'leeg' in result.summary.lower() or 'geen' in result.summary.lower()

    def test_review_checks_citations(self, db, notifier, goal_id, tmp_path):
        """review_task checks artifact for citation quality."""
        from lab.agents.meta_research import MetaResearchAgent
        agent = MetaResearchAgent(db, notifier)

        tid = db.create_task(goal_id, "Test task", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')

        # Create review entry
        db.create_review(tid, 'meta_research')

        # Create artifact with uncited pattern
        artifact = tmp_path / 'test.json'
        artifact.write_text(json.dumps({
            'analysis': {
                'patterns': [{'claim': 'uncited claim', 'evidence': []}],
            }
        }))
        db.set_artifact(tid, str(artifact))

        # Post a completion comment
        db.add_comment(tid, 'edge_analyst',
                       'Completed analysis with detailed findings and results',
                       'comment')

        task = db.get_task(tid)
        agent.review_task(task)

        reviews = db.get_reviews_for_task(tid)
        assert len(reviews) == 1
        assert reviews[0].verdict == 'needs_changes'


# ── Hypothesis Generator Tests ───────────────────────────

class TestHypothesisGenAgent:
    """Test HypothesisGenAgent with mocked LLM."""

    def test_attributes(self, db, notifier):
        from lab.agents.hypothesis_gen import HypothesisGenAgent
        agent = HypothesisGenAgent(db, notifier)
        assert agent.name == 'hypothesis_gen'
        assert agent.is_llm is True

    def test_execute_creates_tasks(self, db, notifier, goal_id, tmp_path):
        """execute_task creates concrete tasks from hypotheses."""
        from lab.agents.hypothesis_gen import HypothesisGenAgent
        agent = HypothesisGenAgent(db, notifier)

        tid = db.create_task(goal_id, "Generate hypotheses",
                             'hypothesis_gen', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch('lab.llm.ask_json', return_value=FAKE_HYPO_RESPONSE), \
             patch.object(agent, '_write_report') as mock_wr, \
             patch.object(agent, '_find_latest_meta_research',
                         return_value={'analysis': FAKE_META_RESPONSE}):
            fake_json = tmp_path / 'hypo.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True
        assert '2 taken' in result.summary or 'taken aangemaakt' in result.summary

        # Check tasks were created in DB
        all_tasks = db.get_tasks_by_goal(goal_id)
        # Original task + 2 from hypothesis
        created_by_hypo = [t for t in all_tasks if t.created_by == 'hypothesis_gen']
        assert len(created_by_hypo) == 2
        assert any('risk_governor' in t.assigned_to for t in created_by_hypo)
        assert any('robustness_auditor' in t.assigned_to for t in created_by_hypo)

    def test_max_hypotheses_enforced(self, db, notifier, goal_id, tmp_path):
        """Max 3 hypotheses even if LLM returns more."""
        from lab.agents.hypothesis_gen import HypothesisGenAgent
        agent = HypothesisGenAgent(db, notifier)

        # Response with 5 hypotheses
        big_response = {
            'hypotheses': [
                {'id': f'H{i}', 'title': f'Hypo {i}', 'tasks': [],
                 'acceptance_criteria': ['test'],
                 'description': f'Desc {i}'}
                for i in range(5)
            ],
            'reasoning': 'test',
        }

        tid = db.create_task(goal_id, "Gen hypos", 'hypothesis_gen', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch('lab.llm.ask_json', return_value=big_response), \
             patch.object(agent, '_write_report') as mock_wr, \
             patch.object(agent, '_find_latest_meta_research', return_value={}):
            fake_json = tmp_path / 'hypo.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True

    def test_invalid_agent_skipped(self, db, notifier, goal_id, tmp_path):
        """Tasks assigned to unknown agents are skipped."""
        from lab.agents.hypothesis_gen import HypothesisGenAgent
        agent = HypothesisGenAgent(db, notifier)

        bad_response = {
            'hypotheses': [{
                'id': 'H001', 'title': 'Test',
                'description': 'Test',
                'acceptance_criteria': ['test'],
                'tasks': [{
                    'title': 'Bad task',
                    'assigned_to': 'nonexistent_agent',
                    'description': 'Should be skipped',
                }],
            }],
            'reasoning': 'test',
        }

        tid = db.create_task(goal_id, "Gen", 'hypothesis_gen', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch('lab.llm.ask_json', return_value=bad_response), \
             patch.object(agent, '_write_report') as mock_wr, \
             patch.object(agent, '_find_latest_meta_research', return_value={}):
            fake_json = tmp_path / 'hypo.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True
        # No tasks should be created for unknown agent
        all_tasks = db.get_tasks_by_goal(goal_id)
        created_by_hypo = [t for t in all_tasks if t.created_by == 'hypothesis_gen']
        assert len(created_by_hypo) == 0


# ── Boss LLM Upgrade Tests ──────────────────────────────

class TestBossLLMUpgrade:
    """Test Boss LLM-assisted task generation."""

    def test_boss_is_llm(self, db, notifier):
        from lab.agents.boss import BossAgent
        agent = BossAgent(db, notifier)
        assert agent.is_llm is True

    def test_llm_task_gen_creates_tasks(self, db, notifier, goal_id):
        """LLM generates tasks when available."""
        from lab.agents.boss import BossAgent
        agent = BossAgent(db, notifier)

        with patch('lab.llm.ask_json', return_value=FAKE_BOSS_RESPONSE):
            created = agent.generate_tasks()

        # 2 tasks from LLM response
        assert created == 2
        tasks = db.get_tasks_by_goal(goal_id)
        assert len(tasks) == 2
        assert any('DD breakdown' in t.title for t in tasks)

    def test_llm_fallback_to_templates(self, db, notifier, goal_id):
        """Falls back to rule-based templates when LLM fails."""
        from lab.agents.boss import BossAgent
        agent = BossAgent(db, notifier)

        # Make LLM fail
        with patch('lab.llm.ask_json', side_effect=RuntimeError("API down")):
            created = agent.generate_tasks()

        # Should still create tasks from templates
        assert created > 0
        tasks = db.get_tasks_by_goal(goal_id)
        assert len(tasks) > 0

    def test_daily_limit_respected(self, db, notifier, goal_id):
        """Boss respects tasks_per_day limit."""
        from lab.agents.boss import BossAgent
        agent = BossAgent(db, notifier)

        # Goal has tasks_per_day=2 (set in fixture as default)
        # First run: creates 2
        with patch('lab.llm.ask_json', return_value=FAKE_BOSS_RESPONSE):
            created1 = agent.generate_tasks()

        # Second run: should create 0 (limit reached)
        big_response = {
            'tasks': [
                {'title': f'Extra task {i}', 'assigned_to': 'risk_governor',
                 'description': 'test'}
                for i in range(5)
            ],
            'reasoning': 'test',
        }
        with patch('lab.llm.ask_json', return_value=big_response):
            created2 = agent.generate_tasks()

        assert created1 == 2
        assert created2 == 0

    def test_duplicate_prevention(self, db, notifier, goal_id):
        """Boss doesn't create duplicate tasks."""
        from lab.agents.boss import BossAgent
        agent = BossAgent(db, notifier)

        # Create a task with same title as LLM would suggest
        db.create_task(goal_id, 'Analyze champion DD breakdown by exit class',
                       'risk_governor', 'boss')

        with patch('lab.llm.ask_json', return_value=FAKE_BOSS_RESPONSE):
            created = agent.generate_tasks()

        # Only 1 new task (the other was duplicate)
        assert created == 1


# ── Guardrail Tests ──────────────────────────────────────

class TestGuardrails:
    """Test that guardrails are enforced across LLM agents."""

    def test_write_allowlist_enforced(self):
        """safe_write_check blocks writes outside allowlist."""
        from lab.config import REPO_ROOT, safe_write_check

        # Allowed
        safe_write_check(REPO_ROOT / 'reports' / 'lab' / 'test.json')
        safe_write_check(REPO_ROOT / 'lab' / 'lab.db')

        # Blocked
        with pytest.raises(PermissionError):
            safe_write_check(REPO_ROOT / 'trading_bot' / 'agent_team_v3.py')

        with pytest.raises(PermissionError):
            safe_write_check(REPO_ROOT / 'trading_bot' / 'robustness_harness.py')

    def test_soul_files_contain_verboden(self):
        """All soul files contain VERBODEN section."""
        for name in ['boss', 'meta_research', 'hypothesis_gen']:
            soul_path = SOULS_DIR / f'{name}.md'
            if soul_path.exists():
                content = soul_path.read_text()
                assert 'VERBODEN' in content, \
                    f"Soul {name}.md missing VERBODEN section"

    def test_soul_files_no_trading_bot_write(self):
        """Soul files explicitly forbid trading_bot writes."""
        for name in ['boss', 'meta_research', 'hypothesis_gen']:
            soul_path = SOULS_DIR / f'{name}.md'
            if soul_path.exists():
                content = soul_path.read_text()
                assert 'trading_bot' in content, \
                    f"Soul {name}.md missing trading_bot restriction"

    def test_soul_files_no_hf_reopen(self):
        """Soul files forbid HF reopening."""
        for name in ['boss', 'meta_research', 'hypothesis_gen']:
            soul_path = SOULS_DIR / f'{name}.md'
            if soul_path.exists():
                content = soul_path.read_text()
                assert 'HF' in content, \
                    f"Soul {name}.md missing HF restriction"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
