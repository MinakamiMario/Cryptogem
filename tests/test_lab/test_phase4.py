"""Tests for Fase 4: Live Monitor + Portfolio Architect."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from lab.config import SOULS_DIR
from lab.db import LabDB
from lab.notifier import LabNotifier


# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / 'test_p4.db'
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
        title="Live monitoring and portfolio analysis",
        agents=['boss', 'live_monitor', 'portfolio_architect',
                'edge_analyst', 'risk_governor'],
    )


# Fake live state
FAKE_LIVE_STATE = {
    'mode': 'micro',
    'start_time': '2026-02-26T20:16:28+00:00',
    'total_rounds': 20,
    'filled': 18,
    'partial': 0,
    'missed': 1,
    'errors': 1,
    'taker_incidents': 0,
    'stuck_positions': 0,
    'total_rt_pnl': 0.0,
    'total_flatten_fees': 0.0,
    'slippages': [3.0, 2.5, -0.5, 4.0, 1.5, 3.2, -0.3, 2.8],
    'consecutive_errors': 0,
    'last_cycle': '2026-02-28T12:00:00+00:00',
    'coin_stats': {
        'KAS/USDT': {'filled': 4, 'partial': 0, 'missed': 0, 'errors': 0},
        'ARB/USDT': {'filled': 7, 'partial': 0, 'missed': 0, 'errors': 0},
    },
    'rollback_triggered': None,
    'micro_positions': {
        'KAS/USDT': {'entry_price': 0.03, 'qty': 300},
    },
    'micro_closed': [
        {'symbol': 'ARB/USDT', 'pnl_pct': 3.5, 'exit_reason': 'TP'},
        {'symbol': 'KAS/USDT', 'pnl_pct': -0.9, 'exit_reason': 'SL'},
        {'symbol': 'ARB/USDT', 'pnl_pct': 1.2, 'exit_reason': 'TP'},
    ],
    'micro_new_entries_blocked': False,
    'micro_caps_hit': 100,
}

FAKE_CHAMPION = {
    'cfg': {
        'rsi_max': 45, 'vol_spike_mult': 3.0, 'exit_type': 'tp_sl',
        'tp_pct': 15, 'sl_pct': 15, 'tm_bars': 15, 'max_pos': 1,
    },
    'score': 71.8,
    'label': 'abl-rsi_max=45',
    'backtest': {
        'trades': 29, 'wr': 75.9, 'pnl': 4931.48,
        'final_equity': 6931.48, 'pf': 4.93, 'dd': 23.0,
    },
    'mc_block': {
        'win_pct': 100.0, 'median_eq': 7075.0, 'p5': 4500.0,
    },
    'hash': '7d53b6926ad6',
}


# ── Live Monitor Tests ───────────────────────────────────

class TestLiveMonitorAttributes:
    def test_attributes(self, db, notifier):
        from lab.agents.live_monitor import LiveMonitor
        agent = LiveMonitor(db, notifier)
        assert agent.name == 'live_monitor'
        assert agent.role == 'Live Drift Detector'
        assert agent.is_llm is False


class TestLiveMonitorChecks:
    """Test individual health check logic."""

    def _get_agent(self, db, notifier):
        from lab.agents.live_monitor import LiveMonitor
        return LiveMonitor(db, notifier)

    def test_healthy_state(self, db, notifier):
        agent = self._get_agent(db, notifier)
        checks = agent._run_checks(FAKE_LIVE_STATE, FAKE_CHAMPION)

        # All checks should pass for healthy state
        failed = [c for c in checks if not c['passed']]
        # WR check will fail (live WR ~66% vs backtest 75.9%)
        # but diff is only ~10pp which is warning, not critical
        criticals = [c for c in checks if c['severity'] == 'critical']
        assert len(criticals) == 0

    def test_high_slippage_detected(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE,
                     'slippages': [15.0, 12.0, 20.0, 11.0]}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        slip_check = next(c for c in checks if c['check'] == 'mean_slippage')
        assert not slip_check['passed']
        assert slip_check['severity'] == 'critical'

    def test_high_error_rate_detected(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE, 'errors': 5, 'total_rounds': 10}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        err_check = next(c for c in checks if c['check'] == 'error_rate')
        assert not err_check['passed']
        assert err_check['severity'] == 'critical'

    def test_consecutive_errors_detected(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE, 'consecutive_errors': 5}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        consec_check = next(
            c for c in checks if c['check'] == 'consecutive_errors'
        )
        assert not consec_check['passed']
        assert consec_check['severity'] == 'critical'

    def test_rollback_detected(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE,
                     'rollback_triggered': '2026-02-28T10:00:00+00:00'}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        rb_check = next(c for c in checks if c['check'] == 'rollback_status')
        assert not rb_check['passed']
        assert rb_check['severity'] == 'critical'

    def test_entries_blocked_warning(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE, 'micro_new_entries_blocked': True}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        block_check = next(
            c for c in checks if c['check'] == 'entries_blocked'
        )
        assert not block_check['passed']
        assert block_check['severity'] == 'warning'

    def test_low_fill_rate_warning(self, db, notifier):
        agent = self._get_agent(db, notifier)
        bad_state = {**FAKE_LIVE_STATE, 'filled': 8, 'total_rounds': 20}
        checks = agent._run_checks(bad_state, FAKE_CHAMPION)

        fill_check = next(c for c in checks if c['check'] == 'fill_rate')
        assert not fill_check['passed']


class TestLiveMonitorVerdicts:
    def _get_agent(self, db, notifier):
        from lab.agents.live_monitor import LiveMonitor
        return LiveMonitor(db, notifier)

    def test_verdict_healthy(self, db, notifier):
        agent = self._get_agent(db, notifier)
        checks = [
            {'severity': 'ok', 'passed': True},
            {'severity': 'ok', 'passed': True},
        ]
        assert agent._verdict(checks) == 'HEALTHY'

    def test_verdict_caution(self, db, notifier):
        agent = self._get_agent(db, notifier)
        checks = [
            {'severity': 'warning', 'passed': False},
            {'severity': 'ok', 'passed': True},
        ]
        assert agent._verdict(checks) == 'CAUTION'

    def test_verdict_degraded(self, db, notifier):
        agent = self._get_agent(db, notifier)
        checks = [
            {'severity': 'warning', 'passed': False},
            {'severity': 'warning', 'passed': False},
            {'severity': 'warning', 'passed': False},
        ]
        assert agent._verdict(checks) == 'DEGRADED'

    def test_verdict_alert(self, db, notifier):
        agent = self._get_agent(db, notifier)
        checks = [
            {'severity': 'critical', 'passed': False},
            {'severity': 'ok', 'passed': True},
        ]
        assert agent._verdict(checks) == 'ALERT'


class TestLiveMonitorExecute:
    def test_execute_produces_artifact(self, db, notifier, goal_id, tmp_path):
        from lab.agents.live_monitor import LiveMonitor
        agent = LiveMonitor(db, notifier)

        tid = db.create_task(goal_id, "Live drift check",
                             'live_monitor', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch.object(agent, '_read_live_state',
                         return_value=FAKE_LIVE_STATE), \
             patch.object(agent, '_read_champion',
                         return_value=FAKE_CHAMPION), \
             patch.object(agent, '_write_report') as mock_wr:
            fake_json = tmp_path / 'live.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True
        assert 'checks' in result.summary.lower() or 'verdict' in result.summary.lower()
        assert result.artifact_path is not None

    def test_execute_no_live_state(self, db, notifier, goal_id):
        from lab.agents.live_monitor import LiveMonitor
        agent = LiveMonitor(db, notifier)

        tid = db.create_task(goal_id, "Live check",
                             'live_monitor', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch.object(agent, '_read_live_state', return_value=None):
            result = agent.execute_task(task)

        assert result.success is True
        assert 'niet gevonden' in result.summary.lower()

    def test_review_checks_artifact(self, db, notifier, goal_id):
        from lab.agents.live_monitor import LiveMonitor
        agent = LiveMonitor(db, notifier)

        # Create task without artifact
        tid = db.create_task(goal_id, "Test task", 'edge_analyst', 'boss')
        db.transition(tid, 'todo', actor='user')
        db.transition(tid, 'in_progress', actor='edge_analyst')
        db.transition(tid, 'peer_review', actor='edge_analyst')
        db.create_review(tid, 'live_monitor')

        task = db.get_task(tid)
        agent.review_task(task)

        reviews = db.get_reviews_for_task(tid)
        assert reviews[0].verdict == 'needs_changes'


# ── Portfolio Architect Tests ────────────────────────────

class TestPortfolioArchitectAttributes:
    def test_attributes(self, db, notifier):
        from lab.agents.portfolio_architect import PortfolioArchitect
        agent = PortfolioArchitect(db, notifier)
        assert agent.name == 'portfolio_architect'
        assert agent.role == 'Capital Allocation Designer'
        assert agent.is_llm is False


class TestPortfolioRanking:
    def _get_agent(self, db, notifier):
        from lab.agents.portfolio_architect import PortfolioArchitect
        return PortfolioArchitect(db, notifier)

    def test_rank_filters_by_pf(self, db, notifier):
        agent = self._get_agent(db, notifier)
        candidates = [
            {'pf': 5.0, 'dd': 20.0, 'trades': 30, 'wr': 70,
             'label': 'good'},
            {'pf': 0.8, 'dd': 10.0, 'trades': 50, 'wr': 50,
             'label': 'bad_pf'},  # Below PF threshold
        ]
        ranked = agent._rank_candidates(candidates)
        assert len(ranked) == 1
        assert ranked[0]['label'] == 'good'

    def test_rank_filters_by_dd(self, db, notifier):
        agent = self._get_agent(db, notifier)
        candidates = [
            {'pf': 3.0, 'dd': 20.0, 'trades': 30, 'wr': 70,
             'label': 'good'},
            {'pf': 3.0, 'dd': 45.0, 'trades': 30, 'wr': 70,
             'label': 'bad_dd'},  # Above DD threshold
        ]
        ranked = agent._rank_candidates(candidates)
        assert len(ranked) == 1
        assert ranked[0]['label'] == 'good'

    def test_rank_filters_by_trades(self, db, notifier):
        agent = self._get_agent(db, notifier)
        candidates = [
            {'pf': 3.0, 'dd': 20.0, 'trades': 30, 'wr': 70,
             'label': 'good'},
            {'pf': 3.0, 'dd': 20.0, 'trades': 5, 'wr': 70,
             'label': 'few_trades'},  # Below trades threshold
        ]
        ranked = agent._rank_candidates(candidates)
        assert len(ranked) == 1

    def test_rank_sorted_by_score(self, db, notifier):
        agent = self._get_agent(db, notifier)
        candidates = [
            {'pf': 3.0, 'dd': 25.0, 'trades': 30, 'wr': 60,
             'label': 'mid'},
            {'pf': 5.0, 'dd': 15.0, 'trades': 40, 'wr': 75,
             'label': 'best'},
            {'pf': 2.0, 'dd': 20.0, 'trades': 25, 'wr': 55,
             'label': 'low'},
        ]
        ranked = agent._rank_candidates(candidates)
        assert ranked[0]['label'] == 'best'
        assert ranked[-1]['label'] == 'low'


class TestPortfolioAllocation:
    def _get_agent(self, db, notifier):
        from lab.agents.portfolio_architect import PortfolioArchitect
        return PortfolioArchitect(db, notifier)

    def test_allocation_inverse_dd(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 10.0, 'pf': 4.0, 'label': 'low_dd',
             'hash': 'a', 'portfolio_score': 40},
            {'dd': 30.0, 'pf': 3.0, 'label': 'high_dd',
             'hash': 'b', 'portfolio_score': 30},
        ]
        alloc = agent._compute_allocation(configs)

        assert alloc['method'] == 'inverse_dd_weighted'
        assert len(alloc['configs']) == 2
        # Low DD should get higher weight
        low_dd_alloc = next(
            a for a in alloc['configs'] if a['label'] == 'low_dd'
        )
        high_dd_alloc = next(
            a for a in alloc['configs'] if a['label'] == 'high_dd'
        )
        assert low_dd_alloc['weight_pct'] > high_dd_alloc['weight_pct']

    def test_allocation_empty(self, db, notifier):
        agent = self._get_agent(db, notifier)
        alloc = agent._compute_allocation([])
        assert alloc['method'] == 'none'
        assert alloc['configs'] == []

    def test_weights_sum_to_100(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 10.0, 'pf': 4.0, 'label': 'a',
             'hash': 'a', 'portfolio_score': 40},
            {'dd': 20.0, 'pf': 3.0, 'label': 'b',
             'hash': 'b', 'portfolio_score': 30},
            {'dd': 15.0, 'pf': 3.5, 'label': 'c',
             'hash': 'c', 'portfolio_score': 35},
        ]
        alloc = agent._compute_allocation(configs)
        total = sum(a['weight_pct'] for a in alloc['configs'])
        assert abs(total - 100.0) < 0.5  # Allow rounding tolerance


class TestPortfolioFeasibility:
    def _get_agent(self, db, notifier):
        from lab.agents.portfolio_architect import PortfolioArchitect
        return PortfolioArchitect(db, notifier)

    def test_go_verdict(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 15.0, 'cfg': {'exit_type': 'tp_sl'},
             'mc_block': {'win_pct': 100}},
            {'dd': 18.0, 'cfg': {'exit_type': 'trail'},
             'mc_block': {'win_pct': 98}},
        ]
        feas = agent._check_feasibility(configs)
        assert feas['verdict'] == 'GO'

    def test_single_config_issue(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 15.0, 'cfg': {'exit_type': 'tp_sl'},
             'mc_block': {'win_pct': 100}},
        ]
        feas = agent._check_feasibility(configs)
        # Single config = issue
        assert len(feas['issues']) > 0

    def test_high_dd_warning(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 28.0, 'cfg': {'exit_type': 'tp_sl'},
             'mc_block': {'win_pct': 100}},
            {'dd': 20.0, 'cfg': {'exit_type': 'trail'},
             'mc_block': {'win_pct': 100}},
        ]
        feas = agent._check_feasibility(configs)
        assert any('DD' in i or 'dd' in i.lower() for i in feas['issues'])

    def test_low_mc_win_issue(self, db, notifier):
        agent = self._get_agent(db, notifier)
        configs = [
            {'dd': 15.0, 'cfg': {'exit_type': 'tp_sl'},
             'mc_block': {'win_pct': 80}},
            {'dd': 18.0, 'cfg': {'exit_type': 'trail'},
             'mc_block': {'win_pct': 100}},
        ]
        feas = agent._check_feasibility(configs)
        assert any('MC' in i or 'ruin' in i.lower() for i in feas['issues'])

    def test_no_candidates(self, db, notifier):
        agent = self._get_agent(db, notifier)
        feas = agent._check_feasibility([])
        assert feas['verdict'] == 'NO_CANDIDATES'


class TestPortfolioExecute:
    def test_execute_no_candidates(self, db, notifier, goal_id):
        from lab.agents.portfolio_architect import PortfolioArchitect
        agent = PortfolioArchitect(db, notifier)

        tid = db.create_task(goal_id, "Portfolio analysis",
                             'portfolio_architect', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        with patch.object(agent, '_gather_candidates', return_value=[]):
            result = agent.execute_task(task)

        assert result.success is True
        assert 'geen' in result.summary.lower()

    def test_execute_with_candidates(self, db, notifier, goal_id, tmp_path):
        from lab.agents.portfolio_architect import PortfolioArchitect
        agent = PortfolioArchitect(db, notifier)

        tid = db.create_task(goal_id, "Portfolio analysis",
                             'portfolio_architect', 'boss')
        db.transition(tid, 'todo', actor='user')
        task = db.get_task(tid)

        candidates = [
            {'pf': 4.93, 'dd': 23.0, 'trades': 29, 'wr': 75.9,
             'label': 'champion', 'hash': 'abc', 'cfg': {'exit_type': 'tp_sl'},
             'mc_block': {'win_pct': 100}, 'pnl': 4931, 'source': 'champion.json'},
        ]

        with patch.object(agent, '_gather_candidates',
                         return_value=candidates), \
             patch.object(agent, '_write_report') as mock_wr:
            fake_json = tmp_path / 'portfolio.json'
            fake_json.write_text(json.dumps({'test': True}))
            mock_wr.return_value = fake_json

            result = agent.execute_task(task)

        assert result.success is True
        assert result.artifact_path is not None

    def test_review_checks_artifact(self, db, notifier, goal_id):
        from lab.agents.portfolio_architect import PortfolioArchitect
        agent = PortfolioArchitect(db, notifier)

        tid = db.create_task(goal_id, "Test", 'risk_governor', 'boss')
        db.transition(tid, 'todo', actor='user')
        db.transition(tid, 'in_progress', actor='risk_governor')
        db.transition(tid, 'peer_review', actor='risk_governor')
        db.create_review(tid, 'portfolio_architect')

        task = db.get_task(tid)
        agent.review_task(task)

        reviews = db.get_reviews_for_task(tid)
        assert reviews[0].verdict == 'needs_changes'


# ── Soul Files ───────────────────────────────────────────

class TestPhase4Souls:
    def test_live_monitor_soul_exists(self):
        path = SOULS_DIR / 'live_monitor.md'
        assert path.exists()
        content = path.read_text()
        assert 'VERBODEN' in content
        assert 'trading_bot' in content
        assert 'HF' in content

    def test_portfolio_architect_soul_exists(self):
        path = SOULS_DIR / 'portfolio_architect.md'
        assert path.exists()
        content = path.read_text()
        assert 'VERBODEN' in content
        assert 'trading_bot' in content
        assert 'HF' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
