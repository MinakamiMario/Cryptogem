"""Robustness Auditor — anti-overfit inquisitor.

Window sweeps, bootstrap P5/P10, Monte Carlo ruin analysis,
full robustness harness. Rule-based agent (no LLM).
"""
from __future__ import annotations

import logging
import re
import traceback

from lab.agents.base import BaseAgent
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.robustness_auditor')

# Minimum trade count to consider a result credible
MIN_TRADES_CREDIBLE = 50

# Monte Carlo ruin threshold for concern
MC_RUIN_CONCERN_PCT = 5.0


class RobustnessAuditor(BaseAgent):
    name = 'robustness_auditor'
    role = 'Anti-Overfit Inquisitor'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Run robustness checks based on task title keywords."""
        title_lower = task.title.lower()

        try:
            if 'window sweep' in title_lower or 'stability' in title_lower:
                return self._window_sweep(task)
            elif 'bootstrap' in title_lower or 'p5' in title_lower:
                return self._bootstrap_analysis(task)
            elif 'monte carlo' in title_lower or 'ruin' in title_lower:
                return self._monte_carlo_analysis(task)
            elif 'robustness harness' in title_lower or 'full' in title_lower:
                return self._full_harness(task)
            else:
                # Default: run full robustness harness
                return self._full_harness(task)
        except Exception as e:
            logger.error(f"Task #{task.id} failed: {traceback.format_exc()}")
            return TaskResult(
                success=False,
                summary=f"RobustnessAuditor error: {e}",
            )

    def review_task(self, task: Task) -> None:
        """Skeptical reviewer. Check for overfitting signals."""
        comments = self.db.get_comments(task.id)
        issues = []

        # Extract metrics from comments
        trade_count = None
        mc_ruin = None
        has_window_data = False

        for c in comments:
            if c.agent == task.assigned_to:
                body_lower = c.body.lower()

                # Extract trade count
                trade_match = re.search(
                    r'(?:trades|n_trades)[=: ]*(\d+)', body_lower
                )
                if trade_match:
                    trade_count = int(trade_match.group(1))

                # Extract MC ruin
                ruin_match = re.search(
                    r'ruin[=: ]*(\d+\.?\d*)%', body_lower
                )
                if ruin_match:
                    mc_ruin = float(ruin_match.group(1))

                # Check for window/stability data
                if 'window' in body_lower or 'stability' in body_lower:
                    has_window_data = True

        # Concern 1: Too few trades (overfitting signal)
        if trade_count is not None and trade_count < MIN_TRADES_CREDIBLE:
            issues.append(
                f"Only {trade_count} trades (minimum {MIN_TRADES_CREDIBLE} for "
                f"statistical credibility). Overfitting risk."
            )

        # Concern 2: Window sensitivity (if applicable)
        title_lower = task.title.lower()
        if ('window' in title_lower or 'stability' in title_lower) and not has_window_data:
            issues.append(
                "Task involves window stability but no window analysis in results"
            )

        # Concern 3: High MC ruin probability
        if mc_ruin is not None and mc_ruin > MC_RUIN_CONCERN_PCT:
            issues.append(
                f"MC ruin probability {mc_ruin:.1f}% exceeds {MC_RUIN_CONCERN_PCT}% "
                f"concern threshold"
            )

        # Concern 4: No artifact
        if not task.artifact_path:
            issues.append("No artifact produced")

        # Concern 5: Weak completion comment
        has_completion = any(
            c.agent == task.assigned_to and len(c.body) > 30
            for c in comments
        )
        if not has_completion:
            issues.append("No substantive completion comment from assignee")

        # Post review (skeptical stance)
        if issues:
            body = "ROBUSTNESS AUDITOR REVIEW -- needs_changes (skeptical):\n" + "\n".join(
                f"- {i}" for i in issues
            )
            comment_id = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', comment_id)
        else:
            comment_id = self.db.add_comment(
                task.id, self.name,
                "ROBUSTNESS AUDITOR REVIEW -- approved. "
                "No overfitting signals detected. Statistical credibility OK.",
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

    def _window_sweep(self, task: Task) -> TaskResult:
        """Run backtest on different time windows to check stability."""
        from lab.tools.backtest_runner import backtest, cfg_hash, get_indicators

        cfg = self._get_champion_cfg()

        # Get total bar count from data
        _, coins = get_indicators()
        # Use end_bar slicing for different windows
        # Test windows: 60%, 70%, 80%, 90%, 100% of data
        window_pcts = [60, 70, 80, 90, 100]
        results = {}

        for pct in window_pcts:
            end_bar = None if pct == 100 else int(532 * pct / 100)
            bt = backtest(cfg, end_bar=end_bar)
            if bt is not None:
                results[pct] = {
                    'end_bar': end_bar or 532,
                    'pnl_pct': bt.get('total_pnl_pct', 0.0),
                    'max_dd_pct': bt.get('max_dd_pct', 0.0),
                    'n_trades': bt.get('n_trades', 0),
                    'win_rate': bt.get('win_rate', 0.0),
                    'sharpe': bt.get('sharpe', 0.0),
                }
            else:
                results[pct] = {'error': 'gate_fail'}

        valid = {k: v for k, v in results.items() if 'error' not in v}

        # Stability check: are results consistent across windows?
        stable = True
        stability_issues = []
        if len(valid) >= 3:
            pnls = [v['pnl_pct'] for v in valid.values()]
            # Check sign consistency
            positive = sum(1 for p in pnls if p > 0)
            if positive < len(pnls) * 0.6:
                stable = False
                stability_issues.append(
                    f"Only {positive}/{len(pnls)} windows profitable"
                )

            # Check variance
            if pnls:
                mean_pnl = sum(pnls) / len(pnls)
                variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
                std_pnl = variance ** 0.5
                cv = std_pnl / abs(mean_pnl) if mean_pnl != 0 else float('inf')
                if cv > 1.0:
                    stable = False
                    stability_issues.append(
                        f"High PnL variance (CV={cv:.2f})"
                    )

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'windows_tested': window_pcts,
            'results': results,
            'stable': stable,
            'stability_issues': stability_issues,
        }

        md = (
            f"# Window Sweep Stability Analysis\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Stability**: {'STABLE' if stable else 'UNSTABLE'}\n\n"
        )
        if stability_issues:
            md += "**Issues**:\n"
            for issue in stability_issues:
                md += f"- {issue}\n"
            md += "\n"

        md += (
            f"## Results\n\n"
            f"| Window % | End Bar | PnL % | Max DD % | Trades | Win Rate | Sharpe |\n"
            f"|----------|---------|--------|----------|--------|----------|--------|\n"
        )
        for pct in window_pcts:
            r = results[pct]
            if 'error' in r:
                md += f"| {pct}% | - | FAIL | - | - | - | - |\n"
            else:
                md += (
                    f"| {pct}% | {r['end_bar']} | {r['pnl_pct']:.2f}% "
                    f"| {r['max_dd_pct']:.2f}% | {r['n_trades']} "
                    f"| {r['win_rate']:.2%} | {r['sharpe']:.3f} |\n"
                )

        report_name = f"window_sweep_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"Window sweep: tested {window_pcts}% windows. "
            f"Stability={'STABLE' if stable else 'UNSTABLE'}. "
            f"{len(valid)}/{len(window_pcts)} valid."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"window_sweep({window_pcts})",
        )

    def _bootstrap_analysis(self, task: Task) -> TaskResult:
        """Run Monte Carlo on champion trades, focus on P5/P10 percentiles."""
        from lab.tools.backtest_runner import backtest, cfg_hash, monte_carlo

        cfg = self._get_champion_cfg()
        bt = backtest(cfg)

        if bt is None:
            return TaskResult(
                success=False,
                summary="Backtest returned None (gate fail) on champion.",
            )

        trades = bt.get('trades', [])
        trade_pnls = [t.get('pnl_pct', 0.0) for t in trades if isinstance(t, dict)]

        if not trade_pnls:
            # Try flat list
            trade_pnls = bt.get('trade_pnl_pcts', [])

        if len(trade_pnls) < 10:
            return TaskResult(
                success=False,
                summary=f"Too few trades ({len(trade_pnls)}) for bootstrap analysis.",
            )

        mc = monte_carlo(trade_pnls, n_sims=3000, block_size=5)

        p5 = mc.get('p5', 0.0)
        p10 = mc.get('p10', 0.0)
        p25 = mc.get('p25', 0.0)
        p50 = mc.get('p50', 0.0)
        p75 = mc.get('p75', 0.0)
        p95 = mc.get('p95', 0.0)
        mean_pnl = mc.get('mean', 0.0)
        ruin_pct = mc.get('ruin_pct', 0.0)

        # Assessment
        p5_ok = p5 > -20.0  # P5 shouldn't be worse than -20%
        ruin_ok = ruin_pct < MC_RUIN_CONCERN_PCT

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'n_trades': len(trade_pnls),
            'n_sims': 3000,
            'block_size': 5,
            'percentiles': {
                'p5': p5, 'p10': p10, 'p25': p25,
                'p50': p50, 'p75': p75, 'p95': p95,
            },
            'mean': mean_pnl,
            'ruin_pct': ruin_pct,
            'p5_acceptable': p5_ok,
            'ruin_acceptable': ruin_ok,
        }

        md = (
            f"# Bootstrap P5/P10 Analysis\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Trades**: {len(trade_pnls)}\n"
            f"**Simulations**: 3000 (block size=5)\n\n"
            f"## Percentile Distribution\n\n"
            f"| Percentile | PnL % |\n"
            f"|------------|--------|\n"
            f"| P5 | {p5:.2f}% |\n"
            f"| P10 | {p10:.2f}% |\n"
            f"| P25 | {p25:.2f}% |\n"
            f"| P50 (median) | {p50:.2f}% |\n"
            f"| P75 | {p75:.2f}% |\n"
            f"| P95 | {p95:.2f}% |\n\n"
            f"**Mean PnL**: {mean_pnl:.2f}%\n"
            f"**Ruin probability**: {ruin_pct:.2f}%\n\n"
            f"## Assessment\n\n"
            f"- P5 > -20%: {'PASS' if p5_ok else 'FAIL'}\n"
            f"- Ruin < {MC_RUIN_CONCERN_PCT}%: {'PASS' if ruin_ok else 'FAIL'}\n"
        )

        report_name = f"bootstrap_p5_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"Bootstrap analysis: {len(trade_pnls)} trades, 3000 sims. "
            f"P5={p5:.2f}%, P10={p10:.2f}%, ruin={ruin_pct:.2f}%. "
            f"P5={'OK' if p5_ok else 'CONCERN'}, ruin={'OK' if ruin_ok else 'HIGH'}."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"monte_carlo(n={len(trade_pnls)}, sims=3000)",
        )

    def _monte_carlo_analysis(self, task: Task) -> TaskResult:
        """Run Monte Carlo, analyze ruin probability and CVaR."""
        from lab.tools.backtest_runner import backtest, cfg_hash, monte_carlo

        cfg = self._get_champion_cfg()
        bt = backtest(cfg)

        if bt is None:
            return TaskResult(
                success=False,
                summary="Backtest returned None (gate fail) on champion.",
            )

        trades = bt.get('trades', [])
        trade_pnls = [t.get('pnl_pct', 0.0) for t in trades if isinstance(t, dict)]

        if not trade_pnls:
            trade_pnls = bt.get('trade_pnl_pcts', [])

        if len(trade_pnls) < 10:
            return TaskResult(
                success=False,
                summary=f"Too few trades ({len(trade_pnls)}) for MC analysis.",
            )

        mc = monte_carlo(trade_pnls, n_sims=3000, block_size=5)

        ruin_pct = mc.get('ruin_pct', 0.0)
        cvar = mc.get('cvar_5', mc.get('cvar', 0.0))
        p5 = mc.get('p5', 0.0)
        p50 = mc.get('p50', 0.0)
        mean_pnl = mc.get('mean', 0.0)
        max_dd_mc = mc.get('max_dd_pct', 0.0)

        # Risk assessment
        ruin_ok = ruin_pct < MC_RUIN_CONCERN_PCT
        cvar_ok = cvar > -30.0  # CVaR shouldn't be worse than -30%

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'n_trades': len(trade_pnls),
            'n_sims': 3000,
            'ruin_pct': ruin_pct,
            'cvar_5': cvar,
            'p5': p5,
            'p50': p50,
            'mean': mean_pnl,
            'max_dd_mc': max_dd_mc,
            'ruin_acceptable': ruin_ok,
            'cvar_acceptable': cvar_ok,
        }

        md = (
            f"# Monte Carlo Ruin & CVaR Analysis\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Trades**: {len(trade_pnls)}\n"
            f"**Simulations**: 3000\n\n"
            f"## Key Metrics\n\n"
            f"| Metric | Value | Threshold | Status |\n"
            f"|--------|-------|-----------|--------|\n"
            f"| Ruin probability | {ruin_pct:.2f}% | <{MC_RUIN_CONCERN_PCT}% "
            f"| {'PASS' if ruin_ok else 'FAIL'} |\n"
            f"| CVaR (5%) | {cvar:.2f}% | >-30% | {'PASS' if cvar_ok else 'FAIL'} |\n"
            f"| P5 | {p5:.2f}% | - | - |\n"
            f"| Median PnL | {p50:.2f}% | - | - |\n"
            f"| Mean PnL | {mean_pnl:.2f}% | - | - |\n"
            f"| MC Max DD | {max_dd_mc:.2f}% | - | - |\n"
        )

        report_name = f"monte_carlo_ruin_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"MC ruin analysis: {len(trade_pnls)} trades, 3000 sims. "
            f"Ruin={ruin_pct:.2f}% ({'OK' if ruin_ok else 'HIGH'}), "
            f"CVaR={cvar:.2f}% ({'OK' if cvar_ok else 'CONCERN'}), "
            f"P5={p5:.2f}%."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"monte_carlo(n={len(trade_pnls)}, sims=3000)",
        )

    def _full_harness(self, task: Task) -> TaskResult:
        """Run full robustness harness via run_candidate()."""
        from lab.tools.backtest_runner import cfg_hash
        from lab.tools.robustness_runner import check_gates, run_candidate

        cfg = self._get_champion_cfg()
        candidate_id = f"task_{task.id}"

        result = run_candidate(cfg, candidate_id, label=task.title)
        gates = check_gates(result)

        verdict = result.get('verdict', 'NO-GO')
        fails = result.get('fails', [])

        # Extract key metrics
        baseline = result.get('baseline', {})
        wf = result.get('walk_forward', {})
        mc = result.get('monte_carlo', {})
        jitter = result.get('param_jitter', {})

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'candidate_id': candidate_id,
            'verdict': verdict,
            'gates': gates,
            'fails': fails,
            'baseline_pnl': baseline.get('total_pnl_pct', 0.0),
            'baseline_dd': baseline.get('max_dd_pct', 0.0),
            'baseline_trades': baseline.get('n_trades', 0),
            'wf_positive': wf.get('n_positive', 0),
            'wf_total': wf.get('n_folds', 5),
            'mc_ruin': mc.get('ruin_pct', 0.0),
            'jitter_positive_pct': jitter.get('pct_positive', 0.0),
        }

        md = (
            f"# Full Robustness Harness\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Verdict**: **{verdict}**\n\n"
            f"## Gate Results\n\n"
            f"| Gate | Status | Value | Threshold |\n"
            f"|------|--------|-------|----------|\n"
        )
        for gate_name, gate_data in gates.items():
            if isinstance(gate_data, dict):
                status = 'PASS' if gate_data.get('pass') else 'FAIL'
                details = {k: v for k, v in gate_data.items() if k != 'pass'}
                md += f"| {gate_name} | {status} | {details} | {gate_data.get('threshold', '-')} |\n"

        if fails:
            md += f"\n## Failed Gates\n\n"
            for fail in fails:
                md += f"- {fail}\n"

        md += (
            f"\n## Baseline Metrics\n\n"
            f"- PnL: {baseline.get('total_pnl_pct', 0):.2f}%\n"
            f"- Max DD: {baseline.get('max_dd_pct', 0):.2f}%\n"
            f"- Trades: {baseline.get('n_trades', 0)}\n"
            f"- WF positive: {wf.get('n_positive', 0)}/{wf.get('n_folds', 5)}\n"
            f"- MC ruin: {mc.get('ruin_pct', 0):.2f}%\n"
        )

        report_name = f"robustness_harness_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"Full robustness harness: verdict={verdict}. "
            f"WF={wf.get('n_positive', 0)}/{wf.get('n_folds', 5)}, "
            f"MC ruin={mc.get('ruin_pct', 0):.2f}%, "
            f"trades={baseline.get('n_trades', 0)}. "
            f"Fails: {len(fails)}."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"run_candidate({candidate_id})",
        )
