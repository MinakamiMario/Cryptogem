"""Report writer — JSON+MD artifact generator for lab agents."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lab.config import REPO_ROOT, REPORTS_DIR, safe_write_check


# ── Provenance helpers ───────────────────────────────────


def _git_hash() -> str:
    """Get current short git hash (no subprocess)."""
    try:
        head = (REPO_ROOT / '.git' / 'HEAD').read_text().strip()
        if head.startswith('ref:'):
            ref_path = REPO_ROOT / '.git' / head.split(' ', 1)[1]
            return ref_path.read_text().strip()[:7]
        return head[:7]
    except Exception:
        return 'unknown'


def _file_sha256(path: str | Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _provenance(agent_name: str, cmd: str = '') -> dict:
    """Generate provenance metadata: timestamp, git_hash, agent, cmd."""
    prov = {
        'agent': agent_name,
        'git_hash': _git_hash(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    if cmd:
        prov['cmd'] = cmd
    return prov


# ── Formatting helpers ───────────────────────────────────


def format_cfg_table(cfg: dict) -> str:
    """Format a config dict as a Markdown table."""
    lines = ['| Parameter | Value |', '|-----------|-------|']
    for k, v in sorted(cfg.items()):
        lines.append(f'| `{k}` | `{v}` |')
    return '\n'.join(lines)


# ── Core write function ─────────────────────────────────


def write_report(agent_name: str, report_name: str, data: dict,
                 md_content: str, cmd: str = '') -> dict:
    """Write JSON+MD report pair to reports/lab/{report_name}/.

    Args:
        agent_name: Name of the agent writing the report.
        report_name: Subdirectory name (e.g., 'edge_analysis_42').
        data: JSON-serializable dict with analysis results.
        md_content: Markdown summary.
        cmd: Command that generated this artifact.

    Returns:
        dict with keys: json_path, md_path, sha256, git_hash
    """
    report_dir = REPORTS_DIR / report_name
    json_path = report_dir / f'{report_name}.json'
    md_path = report_dir / f'{report_name}.md'

    # Safety check before any write
    safe_write_check(json_path)
    safe_write_check(md_path)

    report_dir.mkdir(parents=True, exist_ok=True)

    # Inject provenance metadata
    data['_meta'] = _provenance(agent_name, cmd)

    with open(json_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    with open(md_path, 'w') as f:
        f.write(md_content)

    sha = _file_sha256(json_path)
    git_h = data['_meta']['git_hash']

    return {
        'json_path': str(json_path),
        'md_path': str(md_path),
        'sha256': sha,
        'git_hash': git_h,
    }


# ── Backtest report ─────────────────────────────────────


def write_backtest_report(agent_name: str, task_id: int,
                          cfg: dict, bt_result: dict,
                          analysis: dict | None = None,
                          cmd: str = '') -> dict:
    """Write a formatted backtest report (common format for multiple agents).

    Generates standard MD with:
    - Config table
    - Performance metrics (trades, WR, PnL, PF, DD)
    - Exit class breakdown if available
    - MC results if available
    - Custom analysis section

    Args:
        agent_name: Name of the agent writing the report.
        task_id: Lab task ID for naming.
        cfg: Strategy config dict.
        bt_result: Backtest result dict from backtest_runner.
        analysis: Optional extra analysis dict to include.
        cmd: Command that generated this artifact.

    Returns:
        dict with keys: json_path, md_path, sha256, git_hash
    """
    report_name = f'{agent_name}_{task_id}'

    # ── Build data payload ───────────────────────────────
    data = {
        'config': cfg,
        'backtest': bt_result,
    }
    if analysis:
        data['analysis'] = analysis

    # ── Build Markdown ───────────────────────────────────
    sections = [f'# Backtest Report — task #{task_id}']
    sections.append(f'\n**Agent**: `{agent_name}`\n')

    # Config table
    sections.append('## Configuration\n')
    sections.append(format_cfg_table(cfg))

    # Performance metrics
    sections.append('\n## Performance\n')
    n_trades = bt_result.get('trades', 0)
    wr = bt_result.get('wr', 0)
    pnl = bt_result.get('pnl', 0)
    pf = bt_result.get('pf', 0)
    dd = bt_result.get('dd', 0)

    sections.append(
        f'| Metric | Value |\n'
        f'|--------|-------|\n'
        f'| Trades | {n_trades} |\n'
        f'| Win Rate | {wr:.1f}% |\n'
        f'| PnL | ${pnl:+.2f} |\n'
        f'| Profit Factor | {pf:.2f} |\n'
        f'| Max Drawdown | {dd:.1f}% |'
    )

    # Exit class breakdown
    exit_counts = bt_result.get('exit_counts', bt_result.get('exits', {}))
    if exit_counts:
        sections.append('\n## Exit Breakdown\n')
        lines = ['| Exit Class | Count |', '|------------|-------|']
        for exit_cls, cnt in sorted(exit_counts.items(),
                                    key=lambda x: -x[1]):
            lines.append(f'| {exit_cls} | {cnt} |')
        sections.append('\n'.join(lines))

    # Monte Carlo
    mc = bt_result.get('mc', bt_result.get('monte_carlo', {}))
    if mc:
        sections.append('\n## Monte Carlo\n')
        mc_median = mc.get('median_equity', 0)
        mc_p5 = mc.get('p5', 0)
        mc_ruin = mc.get('broke_pct', mc.get('ruin_prob_pct', 0))
        sections.append(
            f'| Metric | Value |\n'
            f'|--------|-------|\n'
            f'| Median Equity | ${mc_median:.0f} |\n'
            f'| P5 Equity | ${mc_p5:.0f} |\n'
            f'| Ruin % | {mc_ruin:.1f}% |'
        )

    # Custom analysis section
    if analysis:
        sections.append('\n## Analysis\n')
        for key, value in analysis.items():
            if isinstance(value, dict):
                sections.append(f'### {key}\n')
                sections.append(format_cfg_table(value))
            elif isinstance(value, list):
                sections.append(f'### {key}\n')
                for item in value:
                    sections.append(f'- {item}')
            else:
                sections.append(f'**{key}**: {value}\n')

    md_content = '\n'.join(sections) + '\n'
    return write_report(agent_name, report_name, data, md_content, cmd=cmd)


# ── Robustness report ───────────────────────────────────


def write_robustness_report(agent_name: str, task_id: int,
                            cfg: dict, harness_result: dict,
                            cmd: str = '') -> dict:
    """Write a formatted robustness harness report.

    Generates standard MD with:
    - Verdict (GO/NO-GO/SOFT-GO) prominently displayed
    - Gate results table (pass/fail per test)
    - Walk-forward fold details
    - MC simulation summary
    - Parameter sensitivity results

    Args:
        agent_name: Name of the agent writing the report.
        task_id: Lab task ID for naming.
        cfg: Strategy config dict.
        harness_result: Result dict from robustness_runner.run_candidate().
        cmd: Command that generated this artifact.

    Returns:
        dict with keys: json_path, md_path, sha256, git_hash
    """
    report_name = f'{agent_name}_robustness_{task_id}'
    verdict = harness_result.get('verdict', 'NO-GO')
    fails = harness_result.get('fails', [])

    # ── Build data payload ───────────────────────────────
    data = {
        'config': cfg,
        'robustness': harness_result,
        'verdict': verdict,
    }

    # ── Build Markdown ───────────────────────────────────
    verdict_emoji = {'GO': 'PASS', 'SOFT-GO': 'WARN', 'NO-GO': 'FAIL'}
    badge = verdict_emoji.get(verdict, 'UNKNOWN')

    sections = [f'# Robustness Report — task #{task_id}']
    sections.append(f'\n**Agent**: `{agent_name}`\n')
    sections.append(f'## Verdict: **{verdict}** [{badge}]\n')

    if fails:
        sections.append('### Failed gates\n')
        for fail in fails:
            sections.append(f'- {fail}')
        sections.append('')

    # Config
    sections.append('## Configuration\n')
    sections.append(format_cfg_table(cfg))

    # Baseline
    baseline = harness_result.get('baseline', {})
    if baseline:
        sections.append('\n## Baseline Performance\n')
        sections.append(
            f'| Metric | Value |\n'
            f'|--------|-------|\n'
            f'| Trades | {baseline.get("trades", "?")} |\n'
            f'| Win Rate | {baseline.get("wr", 0):.1f}% |\n'
            f'| PnL | ${baseline.get("pnl", 0):+.2f} |\n'
            f'| Profit Factor | {baseline.get("pf", 0):.2f} |\n'
            f'| Max Drawdown | {baseline.get("dd", 0):.1f}% |'
        )

    # Gate results table
    sections.append('\n## Gate Results\n')
    gate_lines = ['| Gate | Result | Detail |', '|------|--------|--------|']

    # Walk-forward
    wf = harness_result.get('walk_forward', {})
    wf_pos = wf.get('passed_folds', 0)
    wf_total = wf.get('n_folds', 5)
    wf_pass = wf_pos >= 4
    gate_lines.append(
        f'| Walk-Forward | {"PASS" if wf_pass else "FAIL"} '
        f'| {wf_pos}/{wf_total} folds positive |'
    )

    # MC
    mc = harness_result.get('monte_carlo', {})
    mc_ruin = mc.get('ruin_prob_pct', 100)
    mc_pass = mc_ruin <= 5.0
    gate_lines.append(
        f'| Monte Carlo | {"PASS" if mc_pass else "FAIL"} '
        f'| ruin {mc_ruin:.1f}% |'
    )

    # Param jitter
    jitter = harness_result.get('param_jitter', {})
    jitter_pct = jitter.get('positive_pct', 0)
    jitter_pass = jitter_pct >= 70.0
    gate_lines.append(
        f'| Param Jitter | {"PASS" if jitter_pass else "FAIL"} '
        f'| {jitter_pct:.0f}% positive |'
    )

    # Universe
    univ = harness_result.get('universe', {})
    univ_pos = univ.get('n_positive_subsets', 0)
    univ_pass = univ_pos >= 2
    gate_lines.append(
        f'| Universe Shift | {"PASS" if univ_pass else "FAIL"} '
        f'| {univ_pos}/4 subsets positive |'
    )

    # Friction
    friction = harness_result.get('friction', {})
    if friction:
        fr_pass = friction.get('pass', friction.get('positive', False))
        fr_detail = friction.get('detail', f"PnL {friction.get('pnl_pct', '?')}%")
        gate_lines.append(
            f'| Friction | {"PASS" if fr_pass else "FAIL"} '
            f'| {fr_detail} |'
        )

    sections.append('\n'.join(gate_lines))

    # Walk-forward fold details
    folds = wf.get('folds', wf.get('results', []))
    if folds:
        sections.append('\n## Walk-Forward Folds\n')
        fold_lines = ['| Fold | PnL % | Trades | Win Rate |',
                      '|------|-------|--------|----------|']
        for i, fold in enumerate(folds):
            f_pnl = fold.get('test_pnl', 0)
            f_trades = fold.get('test_trades', '?')
            f_wr = fold.get('test_wr', 0)
            fold_lines.append(
                f'| {i + 1} | {f_pnl:+.2f}% | {f_trades} | {f_wr:.1f}% |'
            )
        sections.append('\n'.join(fold_lines))

    # MC detail (from robustness_harness.monte_carlo_shuffle)
    if mc:
        sections.append('\n## Monte Carlo Detail\n')
        mc_eq = mc.get('equity', {})
        mc_dd = mc.get('max_dd', {})
        sections.append(
            f'| Metric | Value |\n'
            f'|--------|-------|\n'
            f'| Median Equity | ${mc_eq.get("median", 0):.0f} |\n'
            f'| P5 Equity | ${mc_eq.get("p5", 0):.0f} |\n'
            f'| P95 Equity | ${mc_eq.get("p95", 0):.0f} |\n'
            f'| P95 Max DD | {mc_dd.get("p95", 0):.1f}% |\n'
            f'| Ruin % | {mc_ruin:.1f}% |'
        )

    # Parameter sensitivity
    if jitter and jitter.get('results', jitter.get('params', {})):
        sections.append('\n## Parameter Sensitivity\n')
        params = jitter.get('results', jitter.get('params', {}))
        if isinstance(params, dict):
            sens_lines = ['| Parameter | -10% PnL | +10% PnL |',
                          '|-----------|----------|----------|']
            for param, vals in sorted(params.items()):
                lo = vals.get('lo_pnl_pct', vals.get('minus', '?'))
                hi = vals.get('hi_pnl_pct', vals.get('plus', '?'))
                if isinstance(lo, (int, float)):
                    lo = f'{lo:+.2f}%'
                if isinstance(hi, (int, float)):
                    hi = f'{hi:+.2f}%'
                sens_lines.append(f'| `{param}` | {lo} | {hi} |')
            sections.append('\n'.join(sens_lines))
        elif isinstance(params, list):
            for item in params:
                sections.append(f'- {item}')

    md_content = '\n'.join(sections) + '\n'
    return write_report(agent_name, report_name, data, md_content, cmd=cmd)
