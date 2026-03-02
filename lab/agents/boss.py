"""Boss Agent — research lead, workflow governor.

Creates task proposals, promotes peer-reviewed work, detects stuck tasks.
Core operation is rule-based; LLM is an optional enhancement for smarter
task generation.

Governance rules:
- Boss creates tasks in 'proposal' (gatekeepers must approve before todo)
- Boss promotes: proposal→todo (DB quorum gate), peer_review→review,
  review→approved
- Only user can approve→done or approve→in_progress (reject)
- DB is the canonical enforcer — boss tries, DB decides
"""
from __future__ import annotations

import json
import logging

from lab.agents.base import BaseAgent
from lab.config import GATEKEEPERS, STUCK_THRESHOLD_H
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.boss')


# Task templates per goal keyword
TASK_TEMPLATES = {
    'dd': [
        ("Run DD attribution analysis on current champion", 'risk_governor'),
        ("Test adaptive_maxpos 3/2/1 vs 2/1/1 variants", 'risk_governor'),
        ("Run dd_throttle microsweep 4-6% range", 'risk_governor'),
        ("Window sweep stability check on champion", 'robustness_auditor'),
        ("Bootstrap P5 analysis on latest config", 'robustness_auditor'),
    ],
    'ev': [
        ("Exit attribution analysis: A vs B class breakdown", 'edge_analyst'),
        ("RSI RECOVERY parameter sensitivity sweep", 'edge_analyst'),
        ("TIME MAX leakage analysis", 'edge_analyst'),
        ("Monte Carlo ruin probability analysis", 'robustness_auditor'),
    ],
    'portfolio': [
        ("Capital allocation analysis for top 3 configs", 'portfolio_architect'),
        ("Parallel deployment feasibility check", 'portfolio_architect'),
        ("Cross-config correlation analysis", 'edge_analyst'),
    ],
    'validate': [
        ("Full robustness harness on candidate config", 'robustness_auditor'),
        ("GO/NO-GO gate check on candidate", 'deployment_judge'),
        ("Infrastructure integrity check", 'infra_guardian'),
    ],
    'drift': [
        ("Live state drift check vs backtest baseline", 'live_monitor'),
        ("Regime detection on current market data", 'live_monitor'),
    ],
    '4h': [
        ("Exit attribution analysis: A vs B class breakdown", 'edge_analyst'),
        ("Window sweep stability check on champion", 'robustness_auditor'),
        ("RSI RECOVERY parameter sensitivity sweep", 'edge_analyst'),
        ("Full robustness harness on candidate config", 'robustness_auditor'),
        ("GO/NO-GO gate check on candidate", 'deployment_judge'),
    ],
    'default': [
        ("Infrastructure integrity check (make check)", 'infra_guardian'),
    ],
}


class BossAgent(BaseAgent):
    name = 'boss'
    role = 'Research Lead / Workflow Governor'
    is_llm = False  # Core operation is rule-based

    def execute_task(self, task: Task) -> TaskResult:
        """Boss coordinates — not assigned research tasks.

        If somehow assigned a task, generate a status report instead.
        """
        summary = self.db.get_status_summary()
        task_counts = summary.get('tasks', {})
        total = sum(task_counts.values())
        done = task_counts.get('done', 0)

        report_lines = [
            f"Boss coordination report for task #{task.id}",
            f"Total tasks: {total}, Done: {done}",
        ]
        for status, count in task_counts.items():
            if count > 0:
                report_lines.append(f"  {status}: {count}")

        return TaskResult(
            success=True,
            summary='\n'.join(report_lines),
        )

    def review_task(self, task: Task) -> None:
        """Boss reviews for completeness: artifact + substantive work comment.

        No overrides — only checks objective criteria.
        """
        comments = self.db.get_comments(task.id)
        issues = []

        # Check: has artifact?
        if not task.artifact_path:
            issues.append("Geen artifact geproduceerd")

        # Check: artifact has SHA-256 provenance?
        if task.artifact_path and not task.artifact_sha256:
            issues.append("Artifact mist SHA-256 provenance hash")

        # Check: has substantive work comment?
        has_work = any(
            c.agent == task.assigned_to and len(c.body) > 30
            for c in comments
        )
        if not has_work:
            issues.append("Geen substantieve work comment van assignee")

        if issues:
            body = "BOSS REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "BOSS REVIEW — approved. Artifact present with provenance, "
                "work comment substantive.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    def generate_tasks(self) -> int:
        """Generate task proposals for active goals. Returns count created.

        Tasks go to 'proposal' — gatekeepers must approve before todo.
        LLM generation is attempted first; rule-based templates as fallback.
        """
        created = 0
        goals = self.db.get_goals(status='active')

        for goal in goals:
            # Check daily limit
            today_count = self.db.count_tasks_today(goal.id)
            if today_count >= goal.tasks_per_day:
                continue

            remaining = goal.tasks_per_day - today_count

            # Get existing task titles to avoid duplicates
            existing = self.db.get_tasks_by_goal(goal.id)
            existing_titles = {t.title for t in existing}

            # Try LLM-based generation first (optional enhancement)
            llm_tasks = self._generate_llm_tasks(goal, existing_titles,
                                                  remaining)
            if llm_tasks is not None:
                for title, agent, description in llm_tasks:
                    if remaining <= 0:
                        break
                    if title in existing_titles:
                        continue
                    if agent not in goal.agents:
                        continue

                    task_id = self._create_proposal(
                        goal, title, agent, description,
                    )
                    if task_id:
                        created += 1
                        remaining -= 1
                        existing_titles.add(title)
                continue

            # Fallback: rule-based templates
            templates = self._get_templates(goal.title)

            for title, agent in templates:
                if remaining <= 0:
                    break
                if title in existing_titles:
                    continue
                if agent not in goal.agents:
                    continue

                task_id = self._create_proposal(
                    goal, title, agent,
                    f"Auto-generated for goal: {goal.title}",
                )
                if task_id:
                    created += 1
                    remaining -= 1
                    existing_titles.add(title)

        return created

    def _create_proposal(self, goal, title: str, agent: str,
                         description: str) -> int | None:
        """Create a proposal task and review entries for GATEKEEPERS.

        Returns task_id or None if blocked by WIP cap / drain mode.
        """
        try:
            task_id = self.db.create_task(
                goal_id=goal.id,
                title=title,
                assigned_to=agent,
                created_by='boss',
                description=description,
                initial_status='proposal',
            )
        except ValueError as e:
            logger.info(f"Proposal blocked: {e}")
            return None
        # Create review entries for GATEKEEPERS (not goal agents)
        for gk in GATEKEEPERS:
            self.db.create_review(task_id, reviewer=gk)
        self.notifier.task_created(task_id, title, agent, goal.title)
        return task_id

    def _generate_llm_tasks(self, goal, existing_titles: set,
                            remaining: int) -> list | None:
        """Use LLM to suggest tasks. Returns list of (title, agent, desc)
        or None if LLM unavailable.

        This is an optional enhancement — boss works fully rule-based
        if LLM is not available.
        """
        try:
            from lab.llm import ask_json, load_soul

            # Build context
            recent_activity = self.db.get_recent_activity(limit=20)
            activity_summary = '\n'.join(
                f"- [{a['action']}] {a.get('details', '')} "
                f"(agent: {a['agent']})"
                for a in recent_activity[:15]
            )

            existing_list = '\n'.join(f"- {t}" for t in
                                       sorted(existing_titles)[:20])

            prompt = (
                f"Goal: {goal.title}\n"
                f"Beschrijving: {goal.description}\n"
                f"Beschikbare agents: {', '.join(goal.agents)}\n"
                f"Max {remaining} nieuwe taken.\n\n"
                f"## Bestaande taken (niet dupliceren)\n{existing_list}\n\n"
                f"## Recente activiteit (laatste 15 dagen)\n{activity_summary}\n\n"
                f"Stel {remaining} concrete taken voor in JSON-formaat."
            )

            response = ask_json(prompt, agent_name='boss')
            tasks = response.get('tasks', [])

            result = []
            for t in tasks:
                title = t.get('title', '')
                agent = t.get('assigned_to', '')
                desc = t.get('description', f"LLM-generated for: {goal.title}")
                if title and agent:
                    result.append((title, agent, desc))

            logger.info(f"LLM generated {len(result)} tasks for goal "
                        f"'{goal.title}'")
            return result if result else None

        except Exception as e:
            logger.info(f"LLM unavailable, using templates: {e}")
            return None

    def check_stuck_tasks(self) -> int:
        """Detect and escalate stuck tasks. Returns count of stuck tasks."""
        stuck = self.db.get_stuck_tasks(hours=STUCK_THRESHOLD_H)
        for task in stuck:
            hours = STUCK_THRESHOLD_H  # approximate
            self.notifier.task_stuck(task.id, task.title, hours,
                                     task.assigned_to)
            self.db.add_comment(
                task.id, self.name,
                f"Taak vast sinds >{STUCK_THRESHOLD_H}h. "
                f"Escalatie naar user.",
                'comment',
            )
        return len(stuck)

    def _promote_approved_proposals(self) -> int:
        """proposal → todo. Boss probeert, DB beslist (quorum gate)."""
        promoted = 0
        for task in self.db.get_approved_proposals():
            try:
                self.db.transition(task.id, 'todo', actor='boss')
                promoted += 1
                logger.info(f"Proposal #{task.id} promoted to todo")
            except ValueError:
                pass
        return promoted

    def _promote_peerreview_to_review(self) -> int:
        """peer_review → review. Alle peers approved → boss promotes."""
        promoted = 0
        for task in self.db.get_fully_reviewed_tasks():
            try:
                self.db.transition(task.id, 'review', actor='boss')
                promoted += 1
            except ValueError:
                pass
        return promoted

    def _promote_review_to_approved(self) -> int:
        """review → approved. Auto-promote + TG buttons verschijnen."""
        promoted = 0
        for task in self.db.get_tasks_by_status('review'):
            try:
                self.db.transition(task.id, 'approved', actor='boss')
                self.notifier.task_promoted(task.id, task.title)
                promoted += 1
            except ValueError:
                pass
        return promoted

    def heartbeat(self) -> dict:
        """Override: boss generates proposals, promotes, checks stuck.

        Guardrail v1 backpressure:
        - Drain mode → skip generate_tasks() and _promote_approved_proposals()
        - Pipeline transitions (peer_review→review, review→approved) always run
        - Stuck detection always runs (monitoring)
        """
        stats = super().heartbeat()

        drain = self.db.is_drain_mode()
        stats['drain_mode'] = drain

        if drain:
            logger.info("Drain mode active — skipping task generation "
                        "and proposal promotion")
            stats['tasks_generated'] = 0
            stats['proposals_promoted'] = 0
        else:
            stats['tasks_generated'] = self.generate_tasks()
            stats['proposals_promoted'] = self._promote_approved_proposals()

        # Pipeline draining — always allowed
        stats['peerreview_promoted'] = self._promote_peerreview_to_review()
        stats['review_promoted'] = self._promote_review_to_approved()

        # Monitoring — always allowed
        stats['stuck_detected'] = self.check_stuck_tasks()

        return stats

    @staticmethod
    def _get_templates(goal_title: str) -> list[tuple[str, str]]:
        """Match goal title to task templates."""
        title_lower = goal_title.lower()
        matched = []
        for keyword, templates in TASK_TEMPLATES.items():
            if keyword in title_lower:
                matched.extend(templates)
        # Deduplicate while preserving order
        seen = set()
        result = []
        for t in matched:
            if t[0] not in seen:
                seen.add(t[0])
                result.append(t)
        return result or TASK_TEMPLATES['default']
