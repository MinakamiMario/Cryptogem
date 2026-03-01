"""Edge Analyst — exit attribution specialist.

Analyzes exit class breakdowns (A vs B), RSI recovery sensitivity,
TIME MAX leakage. Rule-based agent (no LLM).
"""
from __future__ import annotations

import logging
import re
import traceback

from lab.agents.base import BaseAgent
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.edge_analyst')


class EdgeAnalyst(BaseAgent):
    name = 'edge_analyst'
    role = 'Exit Attribution Specialist'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Run exit-attribution analysis based on task title keywords."""
        title_lower = task.title.lower()

        try:
            if 'rsi recovery' in title_lower or 'rsi_rec' in title_lower:
                return self._rsi_recovery_sweep(task)
            elif 'time max' in title_lower or 'leakage' in title_lower:
                return self._time_max_analysis(task)
            elif 'exit attribution' in title_lower or 'exit class' in title_lower:
                return self._exit_attribution(task)
            else:
                # Default: run exit attribution on champion
                return self._exit_attribution(task)
        except Exception as e:
            logger.error(f"Task #{task.id} failed: {traceback.format_exc()}")
            return TaskResult(
                success=False,
                summary=f"EdgeAnalyst error: {e}",
            )

    def review_task(self, task: Task) -> None:
        """Check for quantitative evidence, artifact, and provenance."""
        comments = self.db.get_comments(task.id)
        issues = []

        # Check: has quantitative evidence (numbers/metrics)?
        has_numbers = False
        for c in comments:
            if c.agent == task.assigned_to:
                if re.search(r'\d+\.?\d*%|\d+\.\d+|ratio|pnl|dd|trades', c.body, re.I):
                    has_numbers = True
                    break
        if not has_numbers:
            issues.append("No quantitative evidence (numbers/metrics) in work comments")

        # Check: artifact exists?
        if not task.artifact_path:
            issues.append("No artifact produced")
        elif not task.artifact_sha256:
            issues.append("Artifact missing SHA-256 provenance hash")

        # Check: substantive completion comment?
        has_completion = any(
            c.agent == task.assigned_to and len(c.body) > 30
            for c in comments
        )
        if not has_completion:
            issues.append("No substantive completion comment from assignee")

        # Post review
        if issues:
            body = "EDGE ANALYST REVIEW -- needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            comment_id = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', comment_id)
        else:
            comment_id = self.db.add_comment(
                task.id, self.name,
                "EDGE ANALYST REVIEW -- approved. Quantitative evidence present, "
                "artifact with provenance OK.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', comment_id)

    # ── Private task implementations ──────────────────────

    def _get_champion_cfg(self) -> dict:
        """Load champion config, falling back to best_known."""
        from lab.tools.backtest_runner import get_champion, get_best_known
        champion = get_champion()
        if champion and 'cfg' in champion:
            return dict(champion['cfg'])
        return get_best_known()

    def _exit_attribution(self, task: Task) -> TaskResult:
        """Run backtest on champion, analyze exit class breakdown."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        result = backtest(cfg)

        if result is None:
            return TaskResult(
                success=False,
                summary="Backtest returned None (gate fail) on champion config.",
            )

        # Analyze exit classes
        exit_classes = result.get('exit_classes', {})
        trade_list = result.get('trade_list', [])
        total_trades = result.get('trades', len(trade_list))

        # Compute A vs B class breakdown
        class_a = exit_classes.get('A', {})
        class_b = exit_classes.get('B', {})
        class_a_count = class_a.get('count', 0)
        class_b_count = class_b.get('count', 0)
        class_a_pnl = class_a.get('pnl', 0.0)
        class_b_pnl = class_b.get('pnl', 0.0)
        class_a_ratio = class_a_count / max(total_trades, 1)

        # Exit reason breakdown (computed from trade_list)
        exit_reasons = {}
        for t in trade_list:
            if isinstance(t, dict):
                reason = t.get('reason', 'unknown')
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        dominant_exit = max(exit_reasons, key=exit_reasons.get) if exit_reasons else 'unknown'

        # Core metrics
        total_pnl = result.get('pnl', 0.0)
        max_dd = result.get('dd', 0.0)

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'max_dd_pct': max_dd,
            'exit_classes': exit_classes,
            'class_a_count': class_a_count,
            'class_b_count': class_b_count,
            'class_a_pnl': class_a_pnl,
            'class_b_pnl': class_b_pnl,
            'class_a_ratio': round(class_a_ratio, 4),
            'exit_reasons': exit_reasons,
            'dominant_exit': dominant_exit,
        }

        md = (
            f"# Exit Attribution Analysis\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Total trades**: {total_trades}\n"
            f"**Total PnL**: ${total_pnl:.2f}\n"
            f"**Max DD**: {max_dd:.2f}%\n\n"
            f"## Exit Class Breakdown\n\n"
            f"| Class | Count | PnL % |\n"
            f"|-------|-------|-------|\n"
            f"| A | {class_a_count} | {class_a_pnl:.2f}% |\n"
            f"| B | {class_b_count} | {class_b_pnl:.2f}% |\n\n"
            f"**Class A ratio**: {class_a_ratio:.2%}\n\n"
            f"## Exit Reasons\n\n"
        )
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            md += f"- **{reason}**: {count}\n"
        md += f"\n**Dominant exit**: {dominant_exit}\n"

        report_name = f"exit_attribution_{task.id}"
        json_path = self._write_report(report_name, report_data, md)
        cmd = f"backtest(champion) -> exit_attribution | cfg_hash={cfg_hash(cfg)}"

        summary = (
            f"Exit attribution complete. {total_trades} trades, "
            f"PnL=${total_pnl:.2f}, DD={max_dd:.2f}%. "
            f"Class A ratio={class_a_ratio:.2%}, dominant exit={dominant_exit}."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=cmd,
        )

    def _rsi_recovery_sweep(self, task: Task) -> TaskResult:
        """Sweep RSI recovery target values and compare."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        rsi_values = [35, 40, 45, 50, 55]
        results = {}

        for rsi_val in rsi_values:
            test_cfg = dict(cfg)
            test_cfg['rsi_rec_target'] = rsi_val
            bt = backtest(test_cfg)
            if bt is not None:
                results[rsi_val] = {
                    'pnl': bt.get('pnl', 0.0),
                    'dd': bt.get('dd', 0.0),
                    'trades': bt.get('trades', 0),
                    'wr': bt.get('wr', 0.0),
                    'pf': bt.get('pf', 0.0),
                }
            else:
                results[rsi_val] = {'pnl': 0.0, 'error': 'gate_fail'}

        # Find optimal
        valid = {k: v for k, v in results.items() if 'error' not in v}
        if valid:
            optimal = max(valid, key=lambda k: valid[k]['pnl'])
            optimal_data = valid[optimal]
        else:
            optimal = None
            optimal_data = {}

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'sweep_param': 'rsi_rec_target',
            'values_tested': rsi_values,
            'results': results,
            'optimal_value': optimal,
            'optimal_metrics': optimal_data,
        }

        md = (
            f"# RSI Recovery Target Sweep\n\n"
            f"**Base config**: `{cfg_hash(cfg)}`\n\n"
            f"## Results\n\n"
            f"| rsi_rec_target | PnL $ | DD % | Trades | WR % | PF |\n"
            f"|----------------|-------|------|--------|------|----|\n"
        )
        for val in rsi_values:
            r = results[val]
            if 'error' in r:
                md += f"| {val} | FAIL | - | - | - | - |\n"
            else:
                md += (
                    f"| {val} | ${r['pnl']:.0f} | {r['dd']:.2f}% "
                    f"| {r['trades']} | {r['wr']:.1f}% | {r['pf']:.2f} |\n"
                )
        if optimal is not None:
            md += f"\n**Optimal**: rsi_rec_target={optimal} (PnL=${optimal_data['pnl']:.0f})\n"

        report_name = f"rsi_recovery_sweep_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"RSI recovery sweep: tested {rsi_values}. "
            f"Optimal={optimal} with PnL=${optimal_data.get('pnl', 0):.0f}. "
            f"{len(valid)}/{len(rsi_values)} configs valid."
        )

        return TaskResult(
            success=len(valid) > 0,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"rsi_rec_sweep({rsi_values})",
        )

    def _time_max_analysis(self, task: Task) -> TaskResult:
        """Analyze TIME MAX exit frequency vs PnL contribution."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        tm_values = [5, 8, 10, 15, 20]
        results = {}

        for tm_val in tm_values:
            test_cfg = dict(cfg)
            test_cfg['time_max_bars'] = tm_val
            bt = backtest(test_cfg)
            if bt is not None:
                # Extract TIME MAX specific metrics from trade_list
                trade_list = bt.get('trade_list', [])
                time_max_exits = sum(
                    1 for t in trade_list
                    if isinstance(t, dict) and t.get('reason', '').upper() == 'TIME MAX'
                )
                total_exits = len(trade_list) or 1
                time_max_freq = time_max_exits / max(total_exits, 1)

                results[tm_val] = {
                    'pnl': bt.get('pnl', 0.0),
                    'dd': bt.get('dd', 0.0),
                    'trades': bt.get('trades', 0),
                    'time_max_exits': time_max_exits,
                    'time_max_freq': round(time_max_freq, 4),
                    'wr': bt.get('wr', 0.0),
                }
            else:
                results[tm_val] = {'pnl': 0.0, 'error': 'gate_fail'}

        valid = {k: v for k, v in results.items() if 'error' not in v}

        # Identify leakage: high TIME MAX frequency suggests PnL leakage
        leakage_alert = False
        for val, r in valid.items():
            if r.get('time_max_freq', 0) > 0.3:
                leakage_alert = True

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'sweep_param': 'time_max_bars',
            'values_tested': tm_values,
            'results': results,
            'leakage_alert': leakage_alert,
        }

        md = (
            f"# TIME MAX Leakage Analysis\n\n"
            f"**Base config**: `{cfg_hash(cfg)}`\n\n"
        )
        if leakage_alert:
            md += "**WARNING**: High TIME MAX exit frequency detected (>30%). Possible PnL leakage.\n\n"

        md += (
            f"## Results\n\n"
            f"| time_max_bars | PnL $ | DD % | Trades | TM Exits | TM Freq |\n"
            f"|---------------|-------|------|--------|----------|----------|\n"
        )
        for val in tm_values:
            r = results[val]
            if 'error' in r:
                md += f"| {val} | FAIL | - | - | - | - |\n"
            else:
                md += (
                    f"| {val} | ${r['pnl']:.0f} | {r['dd']:.2f}% "
                    f"| {r['trades']} | {r['time_max_exits']} "
                    f"| {r['time_max_freq']:.1%} |\n"
                )

        report_name = f"time_max_leakage_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"TIME MAX leakage analysis: tested {tm_values}. "
            f"{len(valid)}/{len(tm_values)} valid. "
            f"Leakage alert={'YES' if leakage_alert else 'NO'}."
        )

        return TaskResult(
            success=len(valid) > 0,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"time_max_sweep({tm_values})",
        )
