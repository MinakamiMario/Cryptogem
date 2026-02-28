"""Tests for lab/tools/ — backtest_runner, robustness_runner, report_writer."""
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ── Fake engine for mocking _load_engine ─────────────────────

FAKE_NORMALIZE = lambda cfg: dict(cfg, _normalized=True)
FAKE_CFG_HASH = lambda cfg: hashlib.sha256(
    json.dumps(cfg, sort_keys=True).encode()
).hexdigest()[:12]


def _make_fake_engine():
    """Return a fake _engine dict that mirrors backtest_runner._load_engine()."""
    return {
        'precompute_all': MagicMock(return_value={'ind': 'data'}),
        'run_backtest': MagicMock(return_value={
            'trades': 30, 'wr': 72.0, 'pnl': 3500,
            'final_equity': 5500, 'pf': 3.2, 'dd': 18.0,
            'broke': False, 'early_stopped': False,
        }),
        'monte_carlo_block': MagicMock(return_value={
            'median': 3200, 'p5': 2800, 'ruin_pct': 1.0,
        }),
        'cfg_hash': FAKE_CFG_HASH,
        'normalize_cfg': FAKE_NORMALIZE,
        'PARAMS_BY_EXIT': {'A': ['rsi_period'], 'B': ['time_max_bars']},
        'BASELINE_CFG': {'rsi_period': 14, 'time_max_bars': 100},
        'BEST_KNOWN': {'rsi_period': 12, 'time_max_bars': 80},
        'INITIAL_CAPITAL': 2000.0,
        'KRAKEN_FEE': 0.0026,
    }


# ═════════════════════════════════════════════════════════════
# report_writer tests
# ═════════════════════════════════════════════════════════════

class TestReportWriter:
    """Tests for lab/tools/report_writer.py."""

    def test_write_report_creates_files(self, tmp_path):
        """write_report creates both JSON and MD files in reports/lab/."""
        with patch('lab.tools.report_writer.REPORTS_DIR', tmp_path), \
             patch('lab.tools.report_writer.safe_write_check'):
            from lab.tools.report_writer import write_report

            result = write_report(
                agent_name='edge_analyst',
                report_name='test_report_42',
                data={'result': 'ok', 'trades': 30},
                md_content='# Test Report\n\nAll good.\n',
            )

            json_path = Path(result['json_path'])
            md_path = Path(result['md_path'])

            assert json_path.exists(), f"JSON file not created: {json_path}"
            assert md_path.exists(), f"MD file not created: {md_path}"

            # Verify JSON is valid
            with open(json_path) as f:
                data = json.load(f)
            assert data['result'] == 'ok'

            # Verify MD content
            md_text = md_path.read_text()
            assert '# Test Report' in md_text

    def test_write_report_sha256(self, tmp_path):
        """SHA-256 in result matches actual file hash."""
        with patch('lab.tools.report_writer.REPORTS_DIR', tmp_path), \
             patch('lab.tools.report_writer.safe_write_check'):
            from lab.tools.report_writer import write_report

            result = write_report(
                agent_name='edge_analyst',
                report_name='sha_test',
                data={'value': 123},
                md_content='# SHA Test\n',
            )

            # Compute SHA-256 independently
            h = hashlib.sha256()
            with open(result['json_path'], 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            expected_sha = h.hexdigest()

            assert result['sha256'] == expected_sha

    def test_write_report_provenance(self, tmp_path):
        """_meta block contains agent, git_hash, and timestamp."""
        with patch('lab.tools.report_writer.REPORTS_DIR', tmp_path), \
             patch('lab.tools.report_writer.safe_write_check'):
            from lab.tools.report_writer import write_report

            result = write_report(
                agent_name='risk_governor',
                report_name='prov_test',
                data={'x': 1},
                md_content='# Provenance\n',
                cmd='backtest --cfg champion',
            )

            with open(result['json_path']) as f:
                data = json.load(f)

            meta = data['_meta']
            assert meta['agent'] == 'risk_governor'
            assert 'git_hash' in meta
            assert 'timestamp' in meta
            assert meta['cmd'] == 'backtest --cfg champion'

    def test_write_report_safe_write(self, tmp_path):
        """Reports go only to allowed paths (safe_write_check is called)."""
        mock_check = MagicMock()
        with patch('lab.tools.report_writer.REPORTS_DIR', tmp_path), \
             patch('lab.tools.report_writer.safe_write_check', mock_check):
            from lab.tools.report_writer import write_report

            write_report(
                agent_name='edge_analyst',
                report_name='safe_test',
                data={'safe': True},
                md_content='# Safe\n',
            )

            # safe_write_check should be called for both JSON and MD paths
            assert mock_check.call_count == 2
            call_paths = [str(c[0][0]) for c in mock_check.call_args_list]
            assert any('safe_test.json' in p for p in call_paths)
            assert any('safe_test.md' in p for p in call_paths)

    def test_format_cfg_table(self):
        """format_cfg_table produces valid Markdown table."""
        from lab.tools.report_writer import format_cfg_table

        cfg = {'rsi_period': 14, 'time_max_bars': 100, 'dd_throttle': 5.0}
        table = format_cfg_table(cfg)

        lines = table.strip().split('\n')
        # Header + separator + 3 data rows
        assert len(lines) == 5
        assert '| Parameter | Value |' in lines[0]
        assert '|-----------|-------|' in lines[1]
        # Keys should be sorted
        assert '`dd_throttle`' in lines[2]
        assert '`rsi_period`' in lines[3]
        assert '`time_max_bars`' in lines[4]


# ═════════════════════════════════════════════════════════════
# backtest_runner tests (mock _engine)
# ═════════════════════════════════════════════════════════════

class TestBacktestRunner:
    """Tests for lab/tools/backtest_runner.py (with mocked engine)."""

    def test_backtest_normalizes_cfg(self):
        """backtest() calls normalize_cfg on the input config."""
        fake_engine = _make_fake_engine()

        with patch('lab.tools.backtest_runner._engine', fake_engine), \
             patch('lab.tools.backtest_runner._load_engine',
                   return_value=fake_engine), \
             patch('lab.tools.backtest_runner.get_indicators',
                   return_value=({'ind': 'data'}, ['BTC'])):
            from lab.tools.backtest_runner import backtest

            cfg = {'rsi_period': 14, 'time_max_bars': 100}
            backtest(cfg)

            # run_backtest should have been called with normalized cfg
            call_args = fake_engine['run_backtest'].call_args
            passed_cfg = call_args[0][2]  # third positional arg
            assert passed_cfg.get('_normalized') is True

    def test_get_champion_reads_json(self, tmp_path):
        """get_champion() loads champion.json from TRADING_BOT_DIR."""
        champion_data = {
            'cfg': {'rsi_period': 12, 'time_max_bars': 80},
            'pnl': 4200,
            'dd': 14.5,
        }
        champion_file = tmp_path / 'champion.json'
        champion_file.write_text(json.dumps(champion_data))

        with patch('lab.tools.backtest_runner.TRADING_BOT_DIR', tmp_path):
            from lab.tools.backtest_runner import get_champion

            result = get_champion()
            assert result is not None
            assert result['pnl'] == 4200
            assert result['cfg']['rsi_period'] == 12

    def test_get_champion_missing(self, tmp_path):
        """get_champion() returns None when champion.json doesn't exist."""
        with patch('lab.tools.backtest_runner.TRADING_BOT_DIR', tmp_path):
            from lab.tools.backtest_runner import get_champion

            result = get_champion()
            assert result is None

    def test_cfg_hash_deterministic(self):
        """Same config always produces the same hash."""
        fake_engine = _make_fake_engine()

        with patch('lab.tools.backtest_runner._engine', fake_engine), \
             patch('lab.tools.backtest_runner._load_engine',
                   return_value=fake_engine):
            from lab.tools.backtest_runner import cfg_hash

            cfg = {'rsi_period': 14, 'time_max_bars': 100, 'dd_throttle': 5.0}

            h1 = cfg_hash(cfg)
            h2 = cfg_hash(cfg)
            h3 = cfg_hash(dict(cfg))  # new dict, same content

            assert h1 == h2
            assert h1 == h3

            # Different config should give different hash
            cfg2 = {'rsi_period': 12, 'time_max_bars': 80}
            h4 = cfg_hash(cfg2)
            assert h4 != h1


# ═════════════════════════════════════════════════════════════
# robustness_runner tests
# ═════════════════════════════════════════════════════════════

FAKE_GO = {
    'wf_min_pass': 4,
    'mc_ruin_max': 5.0,
    'jitter_min_positive_pct': 70.0,
    'univ_min_subsets_positive': 2,
}


class TestRobustnessRunner:
    """Tests for lab/tools/robustness_runner.py."""

    def test_check_gates_all_pass(self):
        """check_gates returns all_pass=True when all gates pass."""
        result = {
            'walk_forward': {'n_positive': 5, 'n_folds': 5},
            'monte_carlo': {'ruin_pct': 1.0},
            'param_jitter': {'pct_positive': 85},
            'universe': {'n_positive_subsets': 3},
            'verdict': 'GO',
        }

        fake_harness = {'GO': FAKE_GO, 'KILL_SWITCH': {}, 'run_candidate': MagicMock()}
        with patch('lab.tools.robustness_runner._harness', fake_harness), \
             patch('lab.tools.robustness_runner._load_harness',
                   return_value=fake_harness):
            from lab.tools.robustness_runner import check_gates

            gates = check_gates(result)

            assert gates['all_pass'] is True
            assert gates['walk_forward']['pass'] is True
            assert gates['monte_carlo']['pass'] is True
            assert gates['param_jitter']['pass'] is True
            assert gates['universe']['pass'] is True
            assert gates['verdict'] == 'GO'

    def test_check_gates_wf_fail(self):
        """check_gates detects walk-forward failure (too few positive folds)."""
        result = {
            'walk_forward': {'n_positive': 2, 'n_folds': 5},  # < 4
            'monte_carlo': {'ruin_pct': 1.0},
            'param_jitter': {'pct_positive': 85},
            'universe': {'n_positive_subsets': 3},
            'verdict': 'NO-GO',
        }

        fake_harness = {'GO': FAKE_GO, 'KILL_SWITCH': {}, 'run_candidate': MagicMock()}
        with patch('lab.tools.robustness_runner._harness', fake_harness), \
             patch('lab.tools.robustness_runner._load_harness',
                   return_value=fake_harness):
            from lab.tools.robustness_runner import check_gates

            gates = check_gates(result)

            assert gates['all_pass'] is False
            assert gates['walk_forward']['pass'] is False
            assert gates['walk_forward']['ratio'] == '2/5'

    def test_check_gates_mc_fail(self):
        """check_gates detects Monte Carlo ruin failure (ruin > 5%)."""
        result = {
            'walk_forward': {'n_positive': 4, 'n_folds': 5},
            'monte_carlo': {'ruin_pct': 12.0},  # > 5%
            'param_jitter': {'pct_positive': 85},
            'universe': {'n_positive_subsets': 3},
            'verdict': 'NO-GO',
        }

        fake_harness = {'GO': FAKE_GO, 'KILL_SWITCH': {}, 'run_candidate': MagicMock()}
        with patch('lab.tools.robustness_runner._harness', fake_harness), \
             patch('lab.tools.robustness_runner._load_harness',
                   return_value=fake_harness):
            from lab.tools.robustness_runner import check_gates

            gates = check_gates(result)

            assert gates['all_pass'] is False
            assert gates['monte_carlo']['pass'] is False
            assert gates['monte_carlo']['ruin_pct'] == 12.0

    def test_check_gates_jitter_fail(self):
        """check_gates detects param jitter failure (pct_positive < 70%)."""
        result = {
            'walk_forward': {'n_positive': 4, 'n_folds': 5},
            'monte_carlo': {'ruin_pct': 1.0},
            'param_jitter': {'pct_positive': 50},  # < 70%
            'universe': {'n_positive_subsets': 3},
            'verdict': 'NO-GO',
        }

        fake_harness = {'GO': FAKE_GO, 'KILL_SWITCH': {}, 'run_candidate': MagicMock()}
        with patch('lab.tools.robustness_runner._harness', fake_harness), \
             patch('lab.tools.robustness_runner._load_harness',
                   return_value=fake_harness):
            from lab.tools.robustness_runner import check_gates

            gates = check_gates(result)

            assert gates['all_pass'] is False
            assert gates['param_jitter']['pass'] is False

    def test_check_gates_universe_fail(self):
        """check_gates detects universe shift failure (< 2 positive subsets)."""
        result = {
            'walk_forward': {'n_positive': 4, 'n_folds': 5},
            'monte_carlo': {'ruin_pct': 1.0},
            'param_jitter': {'pct_positive': 85},
            'universe': {'n_positive_subsets': 1},  # < 2
            'verdict': 'NO-GO',
        }

        fake_harness = {'GO': FAKE_GO, 'KILL_SWITCH': {}, 'run_candidate': MagicMock()}
        with patch('lab.tools.robustness_runner._harness', fake_harness), \
             patch('lab.tools.robustness_runner._load_harness',
                   return_value=fake_harness):
            from lab.tools.robustness_runner import check_gates

            gates = check_gates(result)

            assert gates['all_pass'] is False
            assert gates['universe']['pass'] is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
