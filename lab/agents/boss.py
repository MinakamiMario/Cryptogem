"""Boss Agent — research lead, workflow governor.

Creates tasks based on goals, promotes peer-reviewed work,
detects stuck tasks. Phase 3: hybrid rule-based + LLM task generation.
"""
from __future__ import annotations

import json
import logging

from lab.agents.base import BaseAgent
from lab.config import LLM_AGENTS, STUCK_THRESHOLD_H
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
    'default': [
        ("Infrastructure integrity check (make check)", 'infra_guardian'),
    ],
}


class BossAgent(BaseAgent):
    name = 'boss'
    role = 'Research Lead / Workflow Governor'
    is_llm = True  # Phase 3: LLM-assisted task generation

    def execute_task(self, task: Task) -> TaskResult:
        """Boss doesn't do research — creates tasks and coordinates."""
        return TaskResult(
            success=True,
            summary="Boss taak afgerond (coordinatie)",
        )

    def review_task(self, task: Task) -> None:
        """Boss reviews for completeness and goal alignment."""
        comments = self.db.get_comments(task.id)

        # Check: has artifact?
        has_artifact = task.artifact_path is not None

        # Check: has substantive work comment?
        work_comments = [
            c for c in comments
            if c.agent == task.assigned_to and len(c.body) > 30
        ]

        issues = []
        if not has_artifact:
            issues.append("Geen artifact geproduceerd")
        if not work_comments:
            issues.append("Geen substantieve work comment")

        if issues:
            body = "BOSS REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "BOSS REVIEW — approved. Work complete, artifact present.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    def generate_tasks(self) -> int:
        """Generate tasks for active goals. Returns count of tasks created.

        Strategy: try LLM first for intelligent suggestions.
        Fallback to rule-based templates if LLM unavailable.
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

            # Try LLM-based generation first
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

                    self.db.create_task(
                        goal_id=goal.id,
                        title=title,
                        assigned_to=agent,
                        created_by='boss',
                        description=description,
                    )
                    self.notifier.task_created(0, title, agent, goal.title)
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

                self.db.create_task(
                    goal_id=goal.id,
                    title=title,
                    assigned_to=agent,
                    created_by='boss',
                    description=f"Auto-generated for goal: {goal.title}",
                )
                self.notifier.task_created(0, title, agent, goal.title)
                created += 1
                remaining -= 1

        return created

    def _generate_llm_tasks(self, goal, existing_titles: set,
                            remaining: int) -> list | None:
        """Use LLM to suggest tasks. Returns list of (title, agent, desc)
        or None if LLM unavailable."""
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

            logger.info(f"LLM generated {len(result)} tasks for goal '{goal.title}'")
            return result if result else None

        except Exception as e:
            logger.warning(f"LLM task gen failed, using templates: {e}")
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
                f"⚠️ Taak vast sinds >{STUCK_THRESHOLD_H}h. "
                f"Escalatie naar user.",
                'comment',
            )
        return len(stuck)

    def heartbeat(self) -> dict:
        """Override: boss also generates tasks and checks stuck items."""
        stats = super().heartbeat()

        # Additional boss duties
        stats['tasks_generated'] = self.generate_tasks()
        stats['stuck_detected'] = self.check_stuck_tasks()

        return stats

    @staticmethod
    def _get_templates(goal_title: str) -> list[tuple[str, str]]:
        """Match goal title to task templates."""
        title_lower = goal_title.lower()
        for keyword, templates in TASK_TEMPLATES.items():
            if keyword in title_lower:
                return templates
        return TASK_TEMPLATES['default']
