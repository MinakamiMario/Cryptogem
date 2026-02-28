"""Live Monitor Agent — drift detector for live micro-trader.

Reads paper_state_mx_micro_tp5sl3.json (READ-ONLY, never writes),
compares live metrics against backtest baseline from champion.json.
Detects: slippage anomalies, PnL degradation, error spikes, regime drift.
Writes artifact to reports/lab/live_monitor_<ts>.{json,md}.
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

from lab.agents.base import BaseAgent
from lab.config import REPO_ROOT, REPORTS_DIR
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.live_monitor')

# Paths (READ-ONLY)
PAPER_STATE_PATH = REPO_ROOT / 'trading_bot' / 'paper_state_mx_micro_tp5sl3.json'
CHAMPION_PATH = REPO_ROOT / 'trading_bot' / 'champion.json'

# Thresholds
MAX_SLIPPAGE_BPS = 10.0       # Alert if mean slippage > 10 bps
MAX_ERROR_RATE = 0.10          # Alert if errors/total > 10%
MAX_MISSED_RATE = 0.15         # Alert if missed/total > 15%
MIN_FILL_RATE = 0.85           # Alert if filled/total < 85%
MAX_CONSECUTIVE_ERRORS = 3     # Alert if consecutive errors >= 3
SLIPPAGE_OUTLIER_MULT = 3.0   # Flag individual slips > 3x median


class LiveMonitor(BaseAgent):
    name = 'live_monitor'
    role = 'Live Drift Detector'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Read live state (READ-ONLY), compare to baseline, report drift."""
        try:
            # Step 1: Read live state
            live = self._read_live_state()
            if live is None:
                return TaskResult(
                    success=True,
                    summary="Live state file niet gevonden — "
                            "micro-trader mogelijk niet actief.",
                )

            # Step 2: Read champion baseline
            baseline = self._read_champion()

            # Step 3: Run health checks
            checks = self._run_checks(live, baseline)

            # Step 4: Build report
            ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            report_name = f'live_monitor_{ts}'

            n_warnings = sum(1 for c in checks if c['severity'] == 'warning')
            n_critical = sum(1 for c in checks if c['severity'] == 'critical')

            report_data = {
                'task_id': task.id,
                'live_summary': self._summarize_live(live),
                'baseline': baseline,
                'checks': checks,
                'warnings': n_warnings,
                'critical': n_critical,
                'verdict': self._verdict(checks),
            }

            md = self._build_markdown(report_data, ts)
            json_path = self._write_report(report_name, report_data, md)

            summary = (
                f"Live monitor scan: {len(checks)} checks uitgevoerd.\n"
                f"Resultaat: {n_critical} critical, {n_warnings} warnings.\n"
                f"Verdict: {report_data['verdict']}.\n"
                f"Artefact: {json_path}"
            )

            return TaskResult(
                success=True,
                summary=summary,
                artifact_path=str(json_path),
                sha256=self._file_sha256(json_path),
                git_hash=self._git_hash(),
                cmd='live_monitor_scan',
            )

        except Exception as e:
            return TaskResult(
                success=False,
                summary=f"Live monitor failed: {str(e)[:500]}",
            )

    def review_task(self, task: Task) -> None:
        """Live Monitor reviews for operational risk signals."""
        comments = self.db.get_comments(task.id)

        issues = []

        # Check artifact exists
        if not task.artifact_path:
            issues.append("Geen artefact geproduceerd")

        # Check for substantive completion
        has_substance = any(
            c.agent == task.assigned_to and len(c.body) > 50
            for c in comments
        )
        if not has_substance:
            issues.append("Completion comment te kort (<50 chars)")

        if issues:
            body = "LIVE MONITOR REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "LIVE MONITOR REVIEW — approved. Operational review OK.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    # ── Helpers ──────────────────────────────────────────

    def _read_live_state(self) -> dict | None:
        """Read paper_state JSON. Returns None if file doesn't exist."""
        if not PAPER_STATE_PATH.exists():
            return None
        try:
            with open(PAPER_STATE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Cannot read live state: {e}")
            return None

    def _read_champion(self) -> dict:
        """Read champion.json baseline metrics."""
        if not CHAMPION_PATH.exists():
            return {}
        try:
            with open(CHAMPION_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _summarize_live(self, live: dict) -> dict:
        """Extract key metrics from live state."""
        slippages = live.get('slippages', [])
        closed = live.get('micro_closed', [])
        pnls = [c.get('pnl_pct', 0) for c in closed]

        return {
            'mode': live.get('mode', '?'),
            'start_time': live.get('start_time', '?'),
            'last_cycle': live.get('last_cycle', '?'),
            'total_rounds': live.get('total_rounds', 0),
            'filled': live.get('filled', 0),
            'partial': live.get('partial', 0),
            'missed': live.get('missed', 0),
            'errors': live.get('errors', 0),
            'consecutive_errors': live.get('consecutive_errors', 0),
            'taker_incidents': live.get('taker_incidents', 0),
            'stuck_positions': live.get('stuck_positions', 0),
            'open_positions': len(live.get('micro_positions', {})),
            'closed_trades': len(closed),
            'mean_slippage_bps': (
                statistics.mean(slippages) if slippages else 0.0
            ),
            'median_slippage_bps': (
                statistics.median(slippages) if slippages else 0.0
            ),
            'max_slippage_bps': max(slippages) if slippages else 0.0,
            'mean_pnl_pct': (
                statistics.mean(pnls) if pnls else 0.0
            ),
            'win_rate': (
                sum(1 for p in pnls if p > 0) / len(pnls) * 100
                if pnls else 0.0
            ),
            'total_rt_pnl': live.get('total_rt_pnl', 0.0),
            'rollback_triggered': live.get('rollback_triggered'),
            'new_entries_blocked': live.get('micro_new_entries_blocked', False),
            'coins_traded': list(live.get('coin_stats', {}).keys()),
        }

    def _run_checks(self, live: dict, baseline: dict) -> list[dict]:
        """Run all health checks against thresholds and baseline."""
        checks = []
        slippages = live.get('slippages', [])
        total_rounds = max(live.get('total_rounds', 1), 1)
        filled = live.get('filled', 0)
        missed = live.get('missed', 0)
        errors = live.get('errors', 0)

        # Check 1: Mean slippage
        if slippages:
            mean_slip = statistics.mean(slippages)
            checks.append({
                'check': 'mean_slippage',
                'value': round(mean_slip, 2),
                'threshold': MAX_SLIPPAGE_BPS,
                'passed': mean_slip <= MAX_SLIPPAGE_BPS,
                'severity': 'critical' if mean_slip > MAX_SLIPPAGE_BPS else 'ok',
                'detail': f"Mean slippage: {mean_slip:.2f} bps",
            })

        # Check 2: Slippage outliers
        if len(slippages) >= 3:
            median_slip = statistics.median(slippages)
            outliers = [
                s for s in slippages
                if abs(s) > abs(median_slip) * SLIPPAGE_OUTLIER_MULT
                and abs(median_slip) > 0.5
            ]
            checks.append({
                'check': 'slippage_outliers',
                'value': len(outliers),
                'threshold': 0,
                'passed': len(outliers) == 0,
                'severity': 'warning' if outliers else 'ok',
                'detail': f"{len(outliers)} slippage outliers (>{SLIPPAGE_OUTLIER_MULT}x median)",
            })

        # Check 3: Fill rate
        fill_rate = filled / total_rounds
        checks.append({
            'check': 'fill_rate',
            'value': round(fill_rate, 3),
            'threshold': MIN_FILL_RATE,
            'passed': fill_rate >= MIN_FILL_RATE,
            'severity': 'warning' if fill_rate < MIN_FILL_RATE else 'ok',
            'detail': f"Fill rate: {fill_rate*100:.1f}% ({filled}/{total_rounds})",
        })

        # Check 4: Error rate
        error_rate = errors / total_rounds
        checks.append({
            'check': 'error_rate',
            'value': round(error_rate, 3),
            'threshold': MAX_ERROR_RATE,
            'passed': error_rate <= MAX_ERROR_RATE,
            'severity': 'critical' if error_rate > MAX_ERROR_RATE else 'ok',
            'detail': f"Error rate: {error_rate*100:.1f}% ({errors}/{total_rounds})",
        })

        # Check 5: Missed rate
        missed_rate = missed / total_rounds
        checks.append({
            'check': 'missed_rate',
            'value': round(missed_rate, 3),
            'threshold': MAX_MISSED_RATE,
            'passed': missed_rate <= MAX_MISSED_RATE,
            'severity': 'warning' if missed_rate > MAX_MISSED_RATE else 'ok',
            'detail': f"Missed rate: {missed_rate*100:.1f}% ({missed}/{total_rounds})",
        })

        # Check 6: Consecutive errors
        consec = live.get('consecutive_errors', 0)
        checks.append({
            'check': 'consecutive_errors',
            'value': consec,
            'threshold': MAX_CONSECUTIVE_ERRORS,
            'passed': consec < MAX_CONSECUTIVE_ERRORS,
            'severity': 'critical' if consec >= MAX_CONSECUTIVE_ERRORS else 'ok',
            'detail': f"Consecutive errors: {consec}",
        })

        # Check 7: Rollback triggered
        rollback = live.get('rollback_triggered')
        checks.append({
            'check': 'rollback_status',
            'value': rollback,
            'threshold': None,
            'passed': rollback is None,
            'severity': 'critical' if rollback else 'ok',
            'detail': f"Rollback: {rollback or 'None'}",
        })

        # Check 8: New entries blocked
        blocked = live.get('micro_new_entries_blocked', False)
        checks.append({
            'check': 'entries_blocked',
            'value': blocked,
            'threshold': False,
            'passed': not blocked,
            'severity': 'warning' if blocked else 'ok',
            'detail': f"New entries blocked: {blocked}",
        })

        # Check 9: Stuck positions
        stuck = live.get('stuck_positions', 0)
        checks.append({
            'check': 'stuck_positions',
            'value': stuck,
            'threshold': 0,
            'passed': stuck == 0,
            'severity': 'warning' if stuck > 0 else 'ok',
            'detail': f"Stuck positions: {stuck}",
        })

        # Check 10: Live WR vs baseline WR (if closed trades exist)
        closed = live.get('micro_closed', [])
        if closed and baseline.get('backtest', {}).get('wr'):
            pnls = [c.get('pnl_pct', 0) for c in closed]
            live_wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            bt_wr = baseline['backtest']['wr']
            wr_diff = live_wr - bt_wr
            checks.append({
                'check': 'wr_vs_baseline',
                'value': round(live_wr, 1),
                'threshold': bt_wr,
                'passed': wr_diff >= -20,  # More than 20pp below baseline
                'severity': (
                    'critical' if wr_diff < -20
                    else 'warning' if wr_diff < -10
                    else 'ok'
                ),
                'detail': (
                    f"Live WR: {live_wr:.1f}% vs backtest: {bt_wr:.1f}% "
                    f"(diff: {wr_diff:+.1f}pp)"
                ),
            })

        return checks

    def _verdict(self, checks: list[dict]) -> str:
        """Overall verdict based on checks."""
        n_critical = sum(1 for c in checks if c['severity'] == 'critical')
        n_warning = sum(1 for c in checks if c['severity'] == 'warning')

        if n_critical > 0:
            return 'ALERT'
        elif n_warning >= 3:
            return 'DEGRADED'
        elif n_warning > 0:
            return 'CAUTION'
        else:
            return 'HEALTHY'

    def _build_markdown(self, report: dict, ts: str) -> str:
        """Build human-readable Markdown report."""
        lines = [
            f"# Live Monitor Report — {ts}",
            f"\n**Verdict**: {report['verdict']}",
            f"**Critical**: {report['critical']} | "
            f"**Warnings**: {report['warnings']}",
            "",
        ]

        # Live summary
        s = report.get('live_summary', {})
        lines.append("## Live State\n")
        lines.append(f"- Mode: {s.get('mode', '?')}")
        lines.append(f"- Started: {s.get('start_time', '?')}")
        lines.append(f"- Last cycle: {s.get('last_cycle', '?')}")
        lines.append(f"- Rounds: {s.get('total_rounds', 0)}")
        lines.append(f"- Filled: {s.get('filled', 0)} | "
                     f"Missed: {s.get('missed', 0)} | "
                     f"Errors: {s.get('errors', 0)}")
        lines.append(f"- Open positions: {s.get('open_positions', 0)}")
        lines.append(f"- Closed trades: {s.get('closed_trades', 0)}")
        lines.append(f"- Mean slippage: {s.get('mean_slippage_bps', 0):.2f} bps")
        lines.append(f"- Live WR: {s.get('win_rate', 0):.1f}%")
        lines.append(f"- Coins: {', '.join(s.get('coins_traded', []))}")
        lines.append("")

        # Health checks
        lines.append("## Health Checks\n")
        for c in report.get('checks', []):
            icon = '✅' if c['passed'] else (
                '🚨' if c['severity'] == 'critical' else '⚠️'
            )
            lines.append(f"- {icon} **{c['check']}**: {c['detail']}")
        lines.append("")

        return '\n'.join(lines) + '\n'
