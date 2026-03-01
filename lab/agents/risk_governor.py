"""Risk Governor — drawdown surgeon.

Analyzes DD curves, tests max_pos variants, runs dd_throttle microsweeps.
Rule-based agent (no LLM).
"""
from __future__ import annotations

import logging
import traceback

from lab.agents.base import BaseAgent
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.risk_governor')

# Hard ceiling: reject any config with DD above this without justification
DD_HARD_CEILING_PCT = 35.0


class RiskGovernor(BaseAgent):
    name = 'risk_governor'
    role = 'Drawdown Surgeon'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Run DD analysis based on task title keywords."""
        title_lower = task.title.lower()

        try:
            if 'adaptive_maxpos' in title_lower or 'maxpos' in title_lower:
                return self._maxpos_variants(task)
            elif 'tp/sl grid' in title_lower or 'tp_sl grid' in title_lower:
                return self._tpsl_grid_sweep(task)
            elif 'dd_throttle' in title_lower or 'microsweep' in title_lower:
                return self._dd_throttle_sweep(task)
            elif 'dd attribution' in title_lower or 'drawdown' in title_lower:
                return self._dd_attribution(task)
            else:
                # Default: DD analysis on champion
                return self._dd_attribution(task)
        except Exception as e:
            logger.error(f"Task #{task.id} failed: {traceback.format_exc()}")
            return TaskResult(
                success=False,
                summary=f"RiskGovernor error: {e}",
            )

    def review_task(self, task: Task) -> None:
        """Focus on DD metrics. Reject if DD > 35% without justification."""
        comments = self.db.get_comments(task.id)
        issues = []

        # Check for DD metrics in comments
        has_dd_data = False
        dd_value = None
        has_max_stop = False
        for c in comments:
            if c.agent == task.assigned_to:
                body_lower = c.body.lower()
                # Look for DD reporting
                if 'dd' in body_lower or 'drawdown' in body_lower:
                    has_dd_data = True
                # Try to extract DD value
                import re
                dd_match = re.search(r'dd[=: ]*(\d+\.?\d*)%', body_lower)
                if dd_match:
                    dd_value = float(dd_match.group(1))
                # Check max_stop_pct mention
                if 'max_stop' in body_lower:
                    has_max_stop = True

        # Reject if DD exceeds ceiling without justification
        if dd_value is not None and dd_value > DD_HARD_CEILING_PCT:
            # Look for justification
            has_justification = any(
                'justif' in c.body.lower() or 'acceptable' in c.body.lower()
                or 'mitigat' in c.body.lower()
                for c in comments if c.agent == task.assigned_to
            )
            if not has_justification:
                issues.append(
                    f"DD={dd_value:.1f}% exceeds {DD_HARD_CEILING_PCT}% ceiling "
                    f"without justification"
                )

        # Check for artifact
        if not task.artifact_path:
            issues.append("No artifact produced")

        # Check for max_stop_pct regression awareness
        title_lower = task.title.lower()
        if ('max_stop' in title_lower or 'throttle' in title_lower) and not has_max_stop:
            issues.append("Task involves max_stop_pct but no max_stop analysis in results")

        # Check DD discipline: must report DD metrics
        if not has_dd_data and task.artifact_path:
            issues.append("No DD metrics reported in work comments")

        # Post review
        if issues:
            body = "RISK GOVERNOR REVIEW -- needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            comment_id = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', comment_id)
        else:
            comment_id = self.db.add_comment(
                task.id, self.name,
                "RISK GOVERNOR REVIEW -- approved. DD discipline maintained.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', comment_id)

    def review_proposal(self, task: Task) -> None:
        """Gatekeeper review: validate proposal before it becomes todo.

        Checks: agent available, no duplicate title, agent in goal.
        Atomisch: comment + verdict + blocked_since in één call.
        """
        issues = []

        # Check: assigned agent not overloaded (2+ taken)
        in_progress = self.db.get_my_tasks(task.assigned_to, 'in_progress')
        todo = self.db.get_my_tasks(task.assigned_to, 'todo')
        if len(in_progress) + len(todo) >= 2:
            issues.append(
                f"Agent '{task.assigned_to}' heeft al "
                f"{len(in_progress) + len(todo)} actieve taken"
            )

        # Check: no duplicate title in existing tasks
        if task.goal_id:
            existing = self.db.get_tasks_by_goal(task.goal_id)
            existing_active = [
                t for t in existing
                if t.id != task.id
                and t.status not in ('done', 'proposal')
            ]
            if any(t.title == task.title for t in existing_active):
                issues.append(f"Duplicaat titel in actieve taken: '{task.title}'")

        # Check: assigned agent belongs to goal
        if task.goal_id:
            goal = self.db.get_goal(task.goal_id)
            if goal and task.assigned_to not in goal.agents:
                issues.append(
                    f"Agent '{task.assigned_to}' niet in goal agents "
                    f"{goal.agents}"
                )

        if issues:
            # Atomisch: comment + verdict + blocked_since
            body = "RISK GOVERNOR PROPOSAL REVIEW — needs_changes:\n" + \
                "\n".join(f"- {i}" for i in issues)
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
            self.db.set_proposal_blocked(task.id)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "RISK GOVERNOR PROPOSAL REVIEW — approved. "
                "Agent beschikbaar, geen duplicaat, goal match OK.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    # ── Private task implementations ──────────────────────

    def _get_champion_cfg(self) -> dict:
        """Load champion config, falling back to best_known."""
        from lab.tools.backtest_runner import get_champion, get_best_known
        champion = get_champion()
        if champion and 'cfg' in champion:
            return dict(champion['cfg'])
        return get_best_known()

    def _dd_attribution(self, task: Task) -> TaskResult:
        """Run backtest on champion, analyze DD curve and worst periods."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        result = backtest(cfg)

        if result is None:
            return TaskResult(
                success=False,
                summary="Backtest returned None (gate fail) on champion config.",
            )

        max_dd = result.get('dd', 0.0)
        total_pnl = result.get('pnl', 0.0)
        n_trades = result.get('trades', 0)
        trade_list = result.get('trade_list', [])

        # Build equity curve from trade_list for DD period analysis
        equity_curve = [t.get('equity_after', 0) for t in trade_list
                        if isinstance(t, dict)]

        # Analyze DD periods from equity curve
        dd_periods = self._find_dd_periods(equity_curve)

        # Calmar-style ratio: PnL / max DD
        calmar = abs(total_pnl / max_dd) if max_dd != 0 else 0.0

        # DD discipline check
        dd_ok = max_dd <= DD_HARD_CEILING_PCT

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'max_dd_pct': max_dd,
            'total_pnl': total_pnl,
            'n_trades': n_trades,
            'calmar_ratio': round(calmar, 3),
            'dd_within_ceiling': dd_ok,
            'dd_ceiling': DD_HARD_CEILING_PCT,
            'worst_dd_periods': dd_periods[:5],
        }

        md = (
            f"# DD Attribution Analysis\n\n"
            f"**Config**: `{cfg_hash(cfg)}`\n"
            f"**Max DD**: {max_dd:.2f}%\n"
            f"**Total PnL**: ${total_pnl:.2f}\n"
            f"**Trades**: {n_trades}\n"
            f"**Calmar ratio**: {calmar:.3f}\n"
            f"**DD within ceiling** ({DD_HARD_CEILING_PCT}%): "
            f"{'YES' if dd_ok else 'NO -- BREACH'}\n\n"
        )

        if dd_periods:
            md += "## Worst DD Periods\n\n"
            md += "| # | DD % | Duration (bars) | Peak Idx | Trough Idx |\n"
            md += "|---|------|-----------------|----------|------------|\n"
            for i, period in enumerate(dd_periods[:5], 1):
                md += (
                    f"| {i} | {period.get('dd_pct', 0):.2f}% "
                    f"| {period.get('duration', 0)} "
                    f"| {period.get('peak_idx', '-')} "
                    f"| {period.get('trough_idx', '-')} |\n"
                )

        report_name = f"dd_attribution_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"DD attribution complete. Max DD={max_dd:.2f}%, "
            f"PnL=${total_pnl:.2f}, Calmar={calmar:.3f}. "
            f"DD ceiling {'OK' if dd_ok else 'BREACHED'}."
        )

        return TaskResult(
            success=True,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"backtest(champion) -> dd_attribution | cfg_hash={cfg_hash(cfg)}",
        )

    def _maxpos_variants(self, task: Task) -> TaskResult:
        """Test max_pos variants (1, 2, 3) with champion config."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        max_pos_values = [1, 2, 3]
        results = {}

        for mp in max_pos_values:
            test_cfg = dict(cfg)
            test_cfg['max_pos'] = mp
            bt = backtest(test_cfg)
            if bt is not None:
                results[mp] = {
                    'pnl': bt.get('pnl', 0.0),
                    'dd': bt.get('dd', 0.0),
                    'trades': bt.get('trades', 0),
                    'wr': bt.get('wr', 0.0),
                    'pf': bt.get('pf', 0.0),
                }
            else:
                results[mp] = {'pnl': 0.0, 'error': 'gate_fail'}

        valid = {k: v for k, v in results.items() if 'error' not in v}

        # Find best DD/return tradeoff: maximize PnL while keeping DD manageable
        best_mp = None
        best_score = float('-inf')
        for mp, r in valid.items():
            dd = abs(r['dd']) if r['dd'] != 0 else 0.01
            score = r['pnl'] / dd  # Calmar-like score
            if score > best_score:
                best_score = score
                best_mp = mp

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'sweep_param': 'max_pos',
            'values_tested': max_pos_values,
            'results': results,
            'best_max_pos': best_mp,
            'best_calmar_score': round(best_score, 3) if best_mp else None,
        }

        md = (
            f"# Max Position Variant Analysis\n\n"
            f"**Base config**: `{cfg_hash(cfg)}`\n\n"
            f"## Results\n\n"
            f"| max_pos | PnL $ | DD % | Trades | WR % | PF |\n"
            f"|---------|-------|------|--------|------|----|\n"
        )
        for mp in max_pos_values:
            r = results[mp]
            if 'error' in r:
                md += f"| {mp} | FAIL | - | - | - | - |\n"
            else:
                marker = " **" if mp == best_mp else ""
                md += (
                    f"| {mp}{marker} | ${r['pnl']:.0f} "
                    f"| {r['dd']:.2f}% | {r['trades']} "
                    f"| {r['wr']:.1f}% | {r['pf']:.2f} |\n"
                )
        if best_mp is not None:
            md += f"\n**Best DD/return tradeoff**: max_pos={best_mp}\n"

        report_name = f"maxpos_variants_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"Max pos sweep: tested {max_pos_values}. "
            f"Best DD/return tradeoff: max_pos={best_mp}. "
            f"{len(valid)}/{len(max_pos_values)} valid."
        )

        return TaskResult(
            success=len(valid) > 0,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"maxpos_sweep({max_pos_values})",
        )

    def _dd_throttle_sweep(self, task: Task) -> TaskResult:
        """Run backtest across max_stop_pct range to find optimal DD throttle."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        stop_values = [8, 10, 12, 15, 18, 20]
        results = {}

        for stop_pct in stop_values:
            test_cfg = dict(cfg)
            test_cfg['max_stop_pct'] = stop_pct
            bt = backtest(test_cfg)
            if bt is not None:
                results[stop_pct] = {
                    'pnl': bt.get('pnl', 0.0),
                    'dd': bt.get('dd', 0.0),
                    'trades': bt.get('trades', 0),
                    'wr': bt.get('wr', 0.0),
                    'pf': bt.get('pf', 0.0),
                }
            else:
                results[stop_pct] = {'pnl': 0.0, 'error': 'gate_fail'}

        valid = {k: v for k, v in results.items() if 'error' not in v}

        # Find optimal: best PnL with DD under ceiling
        optimal = None
        for stop_pct in sorted(valid.keys()):
            r = valid[stop_pct]
            if abs(r['dd']) <= DD_HARD_CEILING_PCT:
                if optimal is None or r['pnl'] > valid[optimal]['pnl']:
                    optimal = stop_pct

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'sweep_param': 'max_stop_pct',
            'values_tested': stop_values,
            'results': results,
            'optimal_max_stop_pct': optimal,
            'dd_ceiling': DD_HARD_CEILING_PCT,
        }

        md = (
            f"# DD Throttle Microsweep\n\n"
            f"**Base config**: `{cfg_hash(cfg)}`\n"
            f"**DD ceiling**: {DD_HARD_CEILING_PCT}%\n\n"
            f"## Results\n\n"
            f"| max_stop_pct | PnL $ | DD % | Trades | WR % | PF |\n"
            f"|--------------|-------|------|--------|------|----|\n"
        )
        for stop_pct in stop_values:
            r = results[stop_pct]
            if 'error' in r:
                md += f"| {stop_pct} | FAIL | - | - | - | - |\n"
            else:
                dd_flag = " !!" if abs(r['dd']) > DD_HARD_CEILING_PCT else ""
                md += (
                    f"| {stop_pct} | ${r['pnl']:.0f} "
                    f"| {r['dd']:.2f}%{dd_flag} | {r['trades']} "
                    f"| {r['wr']:.1f}% | {r['pf']:.2f} |\n"
                )
        if optimal is not None:
            md += f"\n**Optimal**: max_stop_pct={optimal} (within DD ceiling)\n"
        else:
            md += "\n**WARNING**: No max_stop_pct value keeps DD within ceiling.\n"

        report_name = f"dd_throttle_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"DD throttle sweep: tested max_stop_pct={stop_values}. "
            f"Optimal={optimal}. {len(valid)}/{len(stop_values)} valid."
        )

        return TaskResult(
            success=len(valid) > 0,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"dd_throttle_sweep({stop_values})",
        )

    def _tpsl_grid_sweep(self, task: Task) -> TaskResult:
        """Sweep TP/SL combinations on champion config to find DD-optimal combo."""
        from lab.tools.backtest_runner import backtest, cfg_hash

        cfg = self._get_champion_cfg()
        tp_values = [8, 10, 12, 15]
        sl_values = [5, 7, 10, 12]
        results = {}

        for tp in tp_values:
            for sl in sl_values:
                test_cfg = dict(cfg)
                test_cfg['tp_pct'] = tp
                test_cfg['sl_pct'] = sl
                test_cfg['exit_type'] = 'tp_sl'
                bt = backtest(test_cfg)
                key = f"TP{tp}_SL{sl}"
                if bt is not None:
                    results[key] = {
                        'tp_pct': tp, 'sl_pct': sl,
                        'pnl': bt.get('pnl', 0.0),
                        'max_dd_pct': bt.get('dd', 0.0),
                        'n_trades': bt.get('trades', 0),
                        'win_rate': bt.get('wr', 0.0),
                        'pf': bt.get('pf', 0.0),
                    }
                else:
                    results[key] = {'tp_pct': tp, 'sl_pct': sl, 'error': 'gate_fail'}

        valid = {k: v for k, v in results.items() if 'error' not in v and v['n_trades'] > 0}

        # Rank by: DD ≤ 18% AND highest PnL
        candidates = {
            k: v for k, v in valid.items()
            if abs(v['max_dd_pct']) <= 18.0 and v['pf'] >= 1.4
        }
        if not candidates:
            # Fallback: lowest DD with positive PnL
            candidates = {k: v for k, v in valid.items() if v['pnl'] > 0}

        best_key = None
        if candidates:
            best_key = max(candidates, key=lambda k: candidates[k]['pnl'])

        report_data = {
            'cfg_hash': cfg_hash(cfg),
            'sweep': 'tp_sl_grid',
            'tp_values': tp_values,
            'sl_values': sl_values,
            'results': results,
            'best_combo': best_key,
            'target_dd': 18.0,
            'target_pf': 1.4,
        }

        md = (
            f"# TP/SL Grid Sweep — DD Optimization\n\n"
            f"**Base config**: `{cfg_hash(cfg)}`\n"
            f"**Target**: DD ≤ 18%, PF ≥ 1.4\n\n"
            f"## Results\n\n"
            f"| Combo | Trades | PnL | DD% | WR% | PF |\n"
            f"|-------|--------|-----|-----|-----|----|\n"
        )
        for key in sorted(results.keys()):
            r = results[key]
            if 'error' in r:
                md += f"| {key} | FAIL | - | - | - | - |\n"
            else:
                marker = " **" if key == best_key else ""
                md += (
                    f"| {key}{marker} | {r['n_trades']} | ${r['pnl']:.0f} "
                    f"| {r['max_dd_pct']:.1f}% | {r['win_rate']:.1f}% "
                    f"| {r['pf']:.2f} |\n"
                )
        if best_key:
            b = results[best_key]
            md += (
                f"\n**Best**: {best_key} — ${b['pnl']:.0f} PnL, "
                f"{b['max_dd_pct']:.1f}% DD, PF {b['pf']:.2f}\n"
            )

        report_name = f"tpsl_grid_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        summary = (
            f"TP/SL grid sweep: {len(tp_values)}x{len(sl_values)}={len(results)} combos. "
            f"{len(valid)} valid, {len(candidates)} meet target. "
            f"Best={best_key}."
        )

        return TaskResult(
            success=len(valid) > 0,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd=f"tpsl_grid_sweep(tp={tp_values}, sl={sl_values})",
        )

    @staticmethod
    def _find_dd_periods(equity_curve: list) -> list[dict]:
        """Identify drawdown periods from equity curve.

        Returns list of {dd_pct, duration, peak_idx, trough_idx} sorted by severity.
        """
        if not equity_curve or len(equity_curve) < 2:
            return []

        periods = []
        peak = equity_curve[0]
        peak_idx = 0
        trough = peak
        trough_idx = 0

        for i, val in enumerate(equity_curve):
            if val > peak:
                # New peak: close current DD period if it was significant
                if peak > 0 and trough < peak:
                    dd_pct = ((peak - trough) / peak) * 100
                    if dd_pct > 1.0:  # Only track DD > 1%
                        periods.append({
                            'dd_pct': round(dd_pct, 2),
                            'duration': trough_idx - peak_idx,
                            'peak_idx': peak_idx,
                            'trough_idx': trough_idx,
                        })
                peak = val
                peak_idx = i
                trough = val
                trough_idx = i
            elif val < trough:
                trough = val
                trough_idx = i

        # Close last period
        if peak > 0 and trough < peak:
            dd_pct = ((peak - trough) / peak) * 100
            if dd_pct > 1.0:
                periods.append({
                    'dd_pct': round(dd_pct, 2),
                    'duration': trough_idx - peak_idx,
                    'peak_idx': peak_idx,
                    'trough_idx': trough_idx,
                })

        return sorted(periods, key=lambda p: p['dd_pct'], reverse=True)
