"""Lab Inspector — system health snapshots and trend analysis.

Provides:
- health_snapshot(): point-in-time system state
- throughput_trend(): tasks completed per time period
- error_rate(): error frequency over recent cycles
- drain_history(): drain mode activation patterns
- agent_performance(): per-agent review/task throughput
- capacity_forecast(): cycles until drain mode predicted
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from lab.config import WIP_CAPS
from lab.db import LabDB
from lab.models import CycleMetrics

logger = logging.getLogger('lab.inspector')


@dataclass
class HealthSnapshot:
    """Point-in-time system health summary."""
    # Task pipeline
    task_counts: dict[str, int] = field(default_factory=dict)
    total_tasks: int = 0
    active_tasks: int = 0      # in_progress + peer_review + review
    blocked_tasks: int = 0
    done_tasks: int = 0
    # Governance
    drain_mode: bool = False
    cap_breaches: dict[str, tuple[int, int]] = field(default_factory=dict)
    cap_utilization: dict[str, float] = field(default_factory=dict)
    # Agent health
    agents_idle: int = 0
    agents_active: int = 0
    agents_error: int = 0
    # Metrics (last 24h)
    cycles_24h: int = 0
    tasks_completed_24h: int = 0
    errors_24h: int = 0
    avg_cycle_duration_s: float = 0.0
    drain_cycles_24h: int = 0
    # Approved queue (waiting on user)
    approved_waiting: int = 0
    # Goals
    goal_count: int = 0


@dataclass
class ThroughputTrend:
    """Task throughput over a time window."""
    hours: int
    total_tasks: int = 0
    total_reviews: int = 0
    total_promotions: int = 0
    total_errors: int = 0
    cycles: int = 0
    tasks_per_cycle: float = 0.0
    reviews_per_cycle: float = 0.0
    error_rate: float = 0.0  # errors / cycles


class LabInspector:
    """Queries lab DB for system health and trend analysis.

    Stateless — all data comes from DB queries. Safe to instantiate
    per-cycle or per-request.
    """

    def __init__(self, db: LabDB):
        self.db = db

    def health_snapshot(self) -> HealthSnapshot:
        """Take a point-in-time snapshot of system health."""
        snap = HealthSnapshot()

        # Task pipeline
        snap.task_counts = self.db.get_task_counts_by_status()
        snap.total_tasks = sum(snap.task_counts.values())
        snap.active_tasks = sum(
            snap.task_counts.get(s, 0)
            for s in ('in_progress', 'peer_review', 'review')
        )
        snap.blocked_tasks = snap.task_counts.get('blocked', 0)
        snap.done_tasks = snap.task_counts.get('done', 0)
        snap.approved_waiting = snap.task_counts.get('approved', 0)

        # Governance
        snap.drain_mode = self.db.is_drain_mode()
        snap.cap_breaches = self.db.get_cap_breaches()
        snap.cap_utilization = {
            status: snap.task_counts.get(status, 0) / cap
            for status, cap in WIP_CAPS.items()
            if cap > 0
        }

        # Agent health
        agent_statuses = self.db.get_all_agent_statuses()
        for a in agent_statuses:
            if a.status == 'error':
                snap.agents_error += 1
            elif a.status == 'idle':
                snap.agents_idle += 1
            else:
                snap.agents_active += 1

        # Metrics (last 24h)
        metrics_24h = self.db.get_cycle_metrics_since(hours=24)
        snap.cycles_24h = len(metrics_24h)
        if metrics_24h:
            snap.tasks_completed_24h = sum(m.tasks for m in metrics_24h)
            snap.errors_24h = sum(m.errors for m in metrics_24h)
            snap.drain_cycles_24h = sum(
                1 for m in metrics_24h if m.drain_mode
            )
            durations = [m.cycle_duration_s for m in metrics_24h
                         if m.cycle_duration_s > 0]
            snap.avg_cycle_duration_s = (
                sum(durations) / len(durations) if durations else 0.0
            )

        # Goals
        snap.goal_count = len(self.db.get_goals())

        return snap

    def throughput_trend(self, hours: int = 24) -> ThroughputTrend:
        """Calculate throughput metrics over the last N hours."""
        metrics = self.db.get_cycle_metrics_since(hours=hours)
        trend = ThroughputTrend(hours=hours)
        trend.cycles = len(metrics)

        if not metrics:
            return trend

        trend.total_tasks = sum(m.tasks for m in metrics)
        trend.total_reviews = sum(m.reviews for m in metrics)
        trend.total_promotions = sum(m.promotions for m in metrics)
        trend.total_errors = sum(m.errors for m in metrics)

        if trend.cycles > 0:
            trend.tasks_per_cycle = trend.total_tasks / trend.cycles
            trend.reviews_per_cycle = trend.total_reviews / trend.cycles
            trend.error_rate = trend.total_errors / trend.cycles

        return trend

    def error_rate(self, hours: int = 24) -> float:
        """Error frequency: errors per cycle over the last N hours."""
        metrics = self.db.get_cycle_metrics_since(hours=hours)
        if not metrics:
            return 0.0
        total_errors = sum(m.errors for m in metrics)
        return total_errors / len(metrics)

    def drain_history(self, hours: int = 24) -> dict:
        """Drain mode activation patterns over the last N hours.

        Returns:
            dict with: total_cycles, drain_cycles, drain_pct,
                       longest_drain_streak, current_streak.
        """
        metrics = self.db.get_cycle_metrics_since(hours=hours)
        if not metrics:
            return {
                'total_cycles': 0,
                'drain_cycles': 0,
                'drain_pct': 0.0,
                'longest_drain_streak': 0,
                'current_streak': 0,
            }

        total = len(metrics)
        drain_count = sum(1 for m in metrics if m.drain_mode)

        # Streak analysis
        longest = 0
        current = 0
        for m in metrics:
            if m.drain_mode:
                current += 1
                longest = max(longest, current)
            else:
                current = 0

        return {
            'total_cycles': total,
            'drain_cycles': drain_count,
            'drain_pct': drain_count / total * 100 if total else 0.0,
            'longest_drain_streak': longest,
            'current_streak': current,
        }

    def gate_health(self, hours: int = 24) -> dict:
        """Analyze gate rejection patterns over the last N hours.

        Returns:
            dict with:
                total_rejections: int
                by_gate: {gate_name: count}
                top_blocked_tasks: [(task_id, count)] — most-blocked tasks
                recent: list of last 10 rejections (gate, task_id, reason)
        """
        rejections = self.db.get_gate_rejections(hours=hours, limit=500)
        by_gate = self.db.get_gate_rejection_counts(hours=hours)

        # Top blocked tasks (most rejections)
        task_counts: dict[int, int] = {}
        for r in rejections:
            if r.task_id:
                task_counts[r.task_id] = task_counts.get(r.task_id, 0) + 1
        top_tasks = sorted(task_counts.items(), key=lambda x: x[1],
                           reverse=True)[:5]

        # Recent rejections (last 10)
        recent = [
            {'gate': r.gate, 'task_id': r.task_id,
             'actor': r.actor, 'reason': r.reason[:200],
             'from': r.from_status, 'to': r.to_status}
            for r in rejections[:10]
        ]

        return {
            'total_rejections': len(rejections),
            'by_gate': by_gate,
            'top_blocked_tasks': top_tasks,
            'recent': recent,
        }

    def capacity_forecast(self) -> dict[str, Optional[int]]:
        """Estimate cycles until each WIP cap is hit.

        Returns:
            {status: cycles_until_breach} — None if stable or declining.
        """
        # Compare two windows: last 12h vs previous 12h
        recent = self.db.get_cycle_metrics_since(hours=12)
        older = self.db.get_cycle_metrics_since(hours=24)

        # Remove recent from older to get previous 12h only
        recent_ids = {m.id for m in recent}
        previous = [m for m in older if m.id not in recent_ids]

        counts = self.db.get_task_counts_by_status()
        forecast: dict[str, Optional[int]] = {}

        for status, cap in WIP_CAPS.items():
            current = counts.get(status, 0)
            headroom = cap - current

            if headroom <= 0:
                # Already breached
                forecast[status] = 0
                continue

            if not recent:
                forecast[status] = None
                continue

            # Estimate net intake rate for this status from task throughput
            # Simplified: use task + promotion rate as proxy
            recent_tasks_per_cycle = sum(m.tasks for m in recent) / len(recent)
            prev_tasks_per_cycle = (
                sum(m.tasks for m in previous) / len(previous)
                if previous else recent_tasks_per_cycle
            )

            # If throughput is decreasing or zero, no breach predicted
            if recent_tasks_per_cycle <= prev_tasks_per_cycle or \
                    recent_tasks_per_cycle == 0:
                forecast[status] = None
            else:
                # Very rough estimate — real prediction needs per-status flow rates
                net_rate = recent_tasks_per_cycle - prev_tasks_per_cycle
                cycles = int(headroom / net_rate) if net_rate > 0 else None
                forecast[status] = cycles

        return forecast

    def format_health_report(self) -> str:
        """Format a human-readable health report for Telegram digest."""
        snap = self.health_snapshot()
        trend = self.throughput_trend(hours=24)
        drain = self.drain_history(hours=24)
        gate = self.gate_health(hours=24)

        lines = []

        # Pipeline summary
        lines.append('<b>Pipeline</b>')
        lines.append(
            f'  Total: {snap.total_tasks} | '
            f'Active: {snap.active_tasks} | '
            f'Blocked: {snap.blocked_tasks} | '
            f'Done: {snap.done_tasks}'
        )

        # Cap utilization (compact)
        lines.append('\n<b>Cap Utilization</b>')
        for status, util in sorted(snap.cap_utilization.items()):
            bar_filled = min(int(util * 10), 10)
            bar = '\u2588' * bar_filled + '\u2591' * (10 - bar_filled)
            cap = WIP_CAPS[status]
            count = snap.task_counts.get(status, 0)
            warn = ' \u26a0\ufe0f' if count >= cap else ''
            lines.append(f'  {status}: {bar} {count}/{cap}{warn}')

        # Throughput (24h)
        if trend.cycles > 0:
            lines.append('\n<b>Throughput (24h)</b>')
            lines.append(
                f'  Cycles: {trend.cycles} | '
                f'Tasks: {trend.total_tasks} | '
                f'Reviews: {trend.total_reviews}'
            )
            lines.append(
                f'  Tasks/cycle: {trend.tasks_per_cycle:.1f} | '
                f'Error rate: {trend.error_rate:.2f}/cycle'
            )
            if snap.avg_cycle_duration_s > 0:
                lines.append(
                    f'  Avg cycle: {snap.avg_cycle_duration_s:.1f}s'
                )

        # Drain mode
        drain_icon = '\U0001f534' if snap.drain_mode else '\U0001f7e2'
        drain_text = 'ACTIVE' if snap.drain_mode else 'INACTIVE'
        lines.append(f'\n{drain_icon} <b>Drain Mode</b>: {drain_text}')
        if drain['drain_cycles'] > 0:
            lines.append(
                f'  24h: {drain["drain_cycles"]}/{drain["total_cycles"]} '
                f'cycles ({drain["drain_pct"]:.0f}%)'
            )
            if drain['longest_drain_streak'] > 1:
                lines.append(
                    f'  Longest streak: {drain["longest_drain_streak"]} cycles'
                )

        # Agents
        lines.append(
            f'\n<b>Agents</b>: '
            f'{snap.agents_active} active | '
            f'{snap.agents_idle} idle | '
            f'{snap.agents_error} error'
        )

        # Approved queue
        if snap.approved_waiting > 0:
            lines.append(
                f'\n\u23f3 <b>Waiting on user</b>: '
                f'{snap.approved_waiting} task(s)'
            )

        # Gate health (only show if rejections exist)
        if gate['total_rejections'] > 0:
            lines.append(f'\n\U0001f6a7 <b>Gate Rejections (24h)</b>: '
                         f'{gate["total_rejections"]}')
            for g, cnt in sorted(gate['by_gate'].items(),
                                 key=lambda x: x[1], reverse=True):
                lines.append(f'  {g}: {cnt}')
            if gate['top_blocked_tasks']:
                lines.append('  Most blocked:')
                for tid, cnt in gate['top_blocked_tasks'][:3]:
                    lines.append(f'    Task #{tid}: {cnt} rejections')

        return '\n'.join(lines)
