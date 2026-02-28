"""Deployment Judge — GO/NO-GO gatekeeper.

Runs full gate checks, determinism verification, and produces
final GO/NO-GO verdicts. Rule-based agent (no LLM).
"""
from __future__ import annotations

import hashlib
import logging
import re
import traceback

from lab.agents.base import BaseAgent
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.deployment_judge')

# Hard thresholds for GO approval
MIN_WF_PASS = 3          # walk-forward minimum positive folds (out of 5)
MAX_MC_RUIN_PCT = 5.0    # Monte Carlo ruin ceiling
MIN_TOTAL_TRADES = 250   # minimum trades across all contexts


class DeploymentJudge(BaseAgent):
    name = 'deployment_judge'
    role = 'GO/NO-GO Gatekeeper'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Run gate checks based on task title keywords."""
        title_lower = task.title.lower()

        try:
            if 'determinism' in title_lower:
                return self._determinism_check(task)
            elif 'go/no-go' in title_lower or 'gate check' in title_lower:
                return self._gate_check(task)
            else:
                # Default: run full gate check
                return self._gate_check(task)
        except Exception as e:
            logger.error(f"Task #{task.id} failed: {traceback.format_exc()}")
            return TaskResult(
                success=False,
                summary=f"DeploymentJudge error: {e}",
            )

    def review_task(self, task: Task) -> None:
        """Strictest reviewer. Only approves if all critical gates pass."""
        comments = self.db.get_comments(task.id)
        issues = []

        # Extract key metrics from work comments
        verdict_found = None
        wf_pass = None
        mc_ruin = None
        total_trades = None

        for c in comments:
            if c.agent == task.assigned_to:
                body_lower = c.body.lower()

                # Extract verdict
                verdict_match = re.search(
                    r'verdict[=: ]*(GO|SOFT-GO|NO-GO)', c.body, re.I
                )
                if verdict_match:
                    verdict_found = verdict_match.group(1).upper()

                # Extract WF pass count
                wf_match = re.search(r'wf[=: ]*(\d+)/(\d+)', body_lower)
                if wf_match:
                    wf_pass = int(wf_match.group(1))

                # Extract MC ruin
                ruin_match = re.search(
                    r'(?:mc )?ruin[=: ]*(\d+\.?\d*)%', body_lower
                )
                if ruin_match:
                    mc_ruin = float(ruin_match.group(1))

                # Extract trade count
                trade_match = re.search(
                    r'trades[=: ]*(\d+)', body_lower
                )
                if trade_match:
                    total_trades = int(trade_match.group(1))

        # Critical gate: verdict must be GO or SOFT-GO
        if verdict_found is not None:
            if verdict_found not in ('GO', 'SOFT-GO'):
                issues.append(
                    f"Verdict is {verdict_found} -- not deployable"
                )
        else:
            # No verdict found -- can't approve without one
            if task.artifact_path:
                issues.append("No GO/NO-GO verdict found in work comments")

        # Critical gate: WF >= 3/5
        if wf_pass is not None and wf_pass < MIN_WF_PASS:
            issues.append(
                f"Walk-forward {wf_pass}/5 < minimum {MIN_WF_PASS}/5"
            )

        # Critical gate: MC ruin < 5%
        if mc_ruin is not None and mc_ruin > MAX_MC_RUIN_PCT:
            issues.append(
                f"MC ruin {mc_ruin:.1f}% > maximum {MAX_MC_RUIN_PCT}%"
            )

        # Critical gate: total trades >= 250
        if total_trades is not None and total_trades < MIN_TOTAL_TRADES:
            issues.append(
                f"Total trades {total_trades} < minimum {MIN_TOTAL_TRADES}"
            )

        # Artifact check
        if not task.artifact_path:
            issues.append("No artifact produced")

        # Substantive comment check
        has_completion = any(
            c.agent == task.assigned_to and len(c.body) > 30
            for c in comments
        )
        if not has_completion:
            issues.append("No substantive completion comment from assignee")

        # Post review (strictest stance)
        if issues:
            body = "DEPLOYMENT JUDGE REVIEW -- needs_changes (STRICT):\n" + "\n".join(
                f"- {i}" for i in issues
            )
            comment_id = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', comment_id)
        else:
            comment_id = self.db.add_comment(
                task.id, self.name,
                "DEPLOYMENT JUDGE REVIEW -- approved. "
                "All critical gates pass. Verdict accepted.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', comment_id)

    # ── Private task implementations ──────────────────────

    def _get_champion_cfg(self) -> dict:
        """Load champion config, falling back to grid_best."""
        from lab.tools.backtest_runner import get_champion, get_grid_best
        champion = get_champion()
        if champion and 'cfg' in champion:
            return dict(champion['cfg'])
        return get_grid_best()

    def _gate_check(self, task: Task) -> TaskResult:
        """Run full run_candidate(), extract gates, produce GO/NO-GO verdict."""
        from lab.tools.backtest_runner import cfg_hash
        from lab.tools.robustness_runner import check_gates, run_candidate

        cfg = self._get_champion_cfg()
        candidate_id = f"deploy_{task.id}"

        result = run_candidate(cfg, candidate_id, label=task.title)
        gates = check_gates(result)

        verdict = result.get('verdict', 'NO-GO')
        fails = result.get('fails', [])

        # Extract metrics for gate table
        baseline = result.get('baseline', {})
        wf = result.get('walk_forward', {})
        mc = result.get('monte_carlo', {})
        jitter = result.get('param_jitter', {})
        universe = result.get('universe', {})
        friction = result.get('friction', {})

        wf_positive = wf.get('n_positive', 0)
        wf_total = wf.get('n_folds', 5)
        mc_ruin = mc.get('ruin_pct', 0.0)
        n_trades = baseline.get('n_trades', 0)
        total_pnl = baseline.get('total_pnl_pct', 0.0)
        max_dd = baseline.get('max_dd_pct', 0.0)

        # Build detailed gate table
        gate_rows = [
            ('Walk-Forward', f"{wf_positive}/{wf_total}",
             f">={MIN_WF_PASS}/{wf_total}",
             'PASS' if wf_positive >= MIN_WF_PASS else 'FAIL'),
            ('MC Ruin', f"{mc_ruin:.2f}%",
             f"<={MAX_MC_RUIN_PCT}%",
             'PASS' if mc_ruin <= MAX_MC_RUIN_PCT else 'FAIL'),
            ('Trade Count', str(n_trades),
             f">={MIN_TOTAL_TRADES}",
             'PASS' if n_trades >= MIN_TOTAL_TRADES else 'FAIL'),
            ('Param Jitter', f"{jitter.get('pct_positive', 0):.1f}%",
             gates.get('param_jitter', {}).get('threshold', '-'),
             'PASS' if gates.get('param_jitter', {}).get('pass') else 'FAIL'),
            ('Universe Shift', f"{universe.get('n_positive_subsets', 0)} subsets",
             gates.get('universe', {}).get('threshold', '-'),
             'PASS' if gates.get('universe', {}).get('pass') else 'FAIL'),
        ]

        # Overall assessment
        critical_pass = (
            wf_positive >= MIN_WF_PASS
            and mc_ruin <= MAX_MC_RUIN_PCT
            and n_trades >= MIN_TOTAL_TRADES
        )

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'candidate_id': candidate_id,
            'verdict': verdict,
            'critical_gates_pass': critical_pass,
            'gates': gates,
            'fails': fails,
            'gate_table': gate_rows,
            'baseline': {
                'pnl_pct': total_pnl,
                'max_dd_pct': max_dd,
                'n_trades': n_trades,
            },
            'walk_forward': {
                'positive': wf_positive,
                'total': wf_total,
            },
            'monte_carlo': {
                'ruin_pct': mc_ruin,
            },
        }

        md = (
            f"# GO/NO-GO Gate Check\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Candidate**: {candidate_id}\n\n"
            f"## VERDICT: **{verdict}**\n\n"
            f"Critical gates: {'ALL PASS' if critical_pass else 'FAIL'}\n\n"
            f"## Gate Table\n\n"
            f"| Gate | Value | Threshold | Status |\n"
            f"|------|-------|-----------|--------|\n"
        )
        for gate_name, value, threshold, status in gate_rows:
            md += f"| {gate_name} | {value} | {threshold} | {status} |\n"

        md += (
            f"\n## Baseline Summary\n\n"
            f"- **PnL**: {total_pnl:.2f}%\n"
            f"- **Max DD**: {max_dd:.2f}%\n"
            f"- **Trades**: {n_trades}\n"
        )

        if fails:
            md += f"\n## Failed Thresholds\n\n"
            for fail in fails:
                md += f"- {fail}\n"

        report_name = f"gate_check_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"GO/NO-GO gate check: verdict={verdict}. "
            f"WF={wf_positive}/{wf_total}, MC ruin={mc_ruin:.2f}%, "
            f"trades={n_trades}. "
            f"Critical gates={'PASS' if critical_pass else 'FAIL'}. "
            f"Fails: {len(fails)}."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"run_candidate({candidate_id}) -> gate_check",
        )

    def _determinism_check(self, task: Task) -> TaskResult:
        """Run same backtest twice, verify identical results via hash."""
        import json

        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()

        # Run 1
        result_1 = backtest(cfg)
        # Run 2
        result_2 = backtest(cfg)

        if result_1 is None or result_2 is None:
            return TaskResult(
                success=False,
                summary="One or both backtest runs returned None (gate fail).",
            )

        # Hash both results for comparison
        # Remove any timestamp/random fields that might differ
        def _stable_hash(result: dict) -> str:
            """Hash result dict excluding non-deterministic fields."""
            stable = {k: v for k, v in sorted(result.items())
                      if k not in ('timestamp', 'elapsed_s', 'run_id')}
            raw = json.dumps(stable, sort_keys=True, default=str).encode()
            return hashlib.sha256(raw).hexdigest()

        hash_1 = _stable_hash(result_1)
        hash_2 = _stable_hash(result_2)
        deterministic = hash_1 == hash_2

        # Compare key metrics explicitly
        metrics_match = (
            result_1.get('total_pnl_pct') == result_2.get('total_pnl_pct')
            and result_1.get('max_dd_pct') == result_2.get('max_dd_pct')
            and result_1.get('n_trades') == result_2.get('n_trades')
            and result_1.get('win_rate') == result_2.get('win_rate')
        )

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'hash_run_1': hash_1,
            'hash_run_2': hash_2,
            'deterministic': deterministic,
            'metrics_match': metrics_match,
            'run_1_pnl': result_1.get('total_pnl_pct', 0.0),
            'run_2_pnl': result_2.get('total_pnl_pct', 0.0),
            'run_1_trades': result_1.get('n_trades', 0),
            'run_2_trades': result_2.get('n_trades', 0),
        }

        md = (
            f"# Determinism Verification\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n\n"
            f"## Result\n\n"
            f"**Deterministic**: {'YES' if deterministic else 'NO -- CRITICAL FAILURE'}\n"
            f"**Metrics match**: {'YES' if metrics_match else 'NO'}\n\n"
            f"## Hash Comparison\n\n"
            f"| Run | SHA-256 |\n"
            f"|-----|----------|\n"
            f"| Run 1 | `{hash_1[:16]}...` |\n"
            f"| Run 2 | `{hash_2[:16]}...` |\n\n"
            f"## Metric Comparison\n\n"
            f"| Metric | Run 1 | Run 2 | Match |\n"
            f"|--------|-------|-------|-------|\n"
            f"| PnL % | {result_1.get('total_pnl_pct', 0):.4f} "
            f"| {result_2.get('total_pnl_pct', 0):.4f} "
            f"| {'YES' if result_1.get('total_pnl_pct') == result_2.get('total_pnl_pct') else 'NO'} |\n"
            f"| Max DD % | {result_1.get('max_dd_pct', 0):.4f} "
            f"| {result_2.get('max_dd_pct', 0):.4f} "
            f"| {'YES' if result_1.get('max_dd_pct') == result_2.get('max_dd_pct') else 'NO'} |\n"
            f"| Trades | {result_1.get('n_trades', 0)} "
            f"| {result_2.get('n_trades', 0)} "
            f"| {'YES' if result_1.get('n_trades') == result_2.get('n_trades') else 'NO'} |\n"
            f"| Win Rate | {result_1.get('win_rate', 0):.4f} "
            f"| {result_2.get('win_rate', 0):.4f} "
            f"| {'YES' if result_1.get('win_rate') == result_2.get('win_rate') else 'NO'} |\n"
        )

        report_name = f"determinism_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"Determinism check: {'PASS' if deterministic else 'FAIL'}. "
            f"Hash match={deterministic}, metrics match={metrics_match}. "
            f"PnL run1={result_1.get('total_pnl_pct', 0):.2f}%, "
            f"run2={result_2.get('total_pnl_pct', 0):.2f}%."
        )

        return TaskResult(
            success=deterministic,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"backtest(champion) x2 -> determinism | cfg_hash={cfg_hash(cfg)}",
        )
