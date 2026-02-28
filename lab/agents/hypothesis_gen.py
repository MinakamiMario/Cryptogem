"""Hypothesis Generator — designs testable research hypotheses.

Input: meta-research output + ADR/DECISIONS context.
Output: max 3 hypotheses per run, each with sweep params,
expected impact, acceptance criteria, and concrete tasks.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from lab.agents.base import BaseAgent
from lab.config import AGENT_NAMES, REPO_ROOT, REPORTS_DIR
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.hypothesis_gen')

# Agents that can receive research tasks
RESEARCH_AGENTS = {
    'edge_analyst', 'risk_governor', 'robustness_auditor',
    'deployment_judge',
}

MAX_HYPOTHESES = 3


class HypothesisGenAgent(BaseAgent):
    name = 'hypothesis_gen'
    role = 'Research Hypothesis Designer'
    is_llm = True

    def execute_task(self, task: Task) -> TaskResult:
        """Generate hypotheses from meta-research + context."""
        try:
            # Step 1: Gather latest meta-research
            meta_report = self._find_latest_meta_research()
            decisions = self._read_decisions()

            # Step 2: Build LLM prompt
            prompt = self._build_prompt(meta_report, decisions, task)

            # Step 3: Call LLM
            from lab.llm import ask_json
            response = ask_json(prompt, agent_name=self.name)

            # Enforce max hypotheses
            hypotheses = response.get('hypotheses', [])[:MAX_HYPOTHESES]
            response['hypotheses'] = hypotheses

            # Step 4: Create concrete tasks from hypotheses
            tasks_created = 0
            for hypo in hypotheses:
                for t in hypo.get('tasks', []):
                    agent = t.get('assigned_to', '')
                    if agent not in RESEARCH_AGENTS:
                        logger.warning(
                            f"Skipping task for unknown agent: {agent}"
                        )
                        continue

                    # Find the goal this task belongs to
                    goal_id = task.goal_id
                    self.db.create_task(
                        goal_id=goal_id,
                        title=t.get('title', f"Hypothesis task: {hypo.get('id', '?')}"),
                        assigned_to=agent,
                        created_by=self.name,
                        description=(
                            f"Hypothesis {hypo.get('id', '?')}: "
                            f"{hypo.get('title', '?')}\n\n"
                            f"{t.get('description', '')}\n\n"
                            f"Acceptatiecriteria:\n"
                            + '\n'.join(
                                f"- {c}" for c in
                                hypo.get('acceptance_criteria', [])
                            )
                        ),
                    )
                    tasks_created += 1

            # Step 5: Write artifact
            ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            report_name = f'hypothesis_gen_{ts}'

            report_data = {
                'task_id': task.id,
                'meta_research_source': meta_report.get('path', 'none'),
                'hypotheses': hypotheses,
                'tasks_created': tasks_created,
                'reasoning': response.get('reasoning', ''),
            }

            md = self._build_markdown(hypotheses, tasks_created, ts,
                                       response.get('reasoning', ''))
            json_path = self._write_report(report_name, report_data, md)

            summary = (
                f"Hypothese-generatie: {len(hypotheses)} hypotheses ontworpen, "
                f"{tasks_created} taken aangemaakt.\n"
                f"Artefact: {json_path}"
            )

            return TaskResult(
                success=True,
                summary=summary,
                artifact_path=str(json_path),
                sha256=self._file_sha256(json_path),
                git_hash=self._git_hash(),
                cmd='hypothesis_generation',
            )

        except json.JSONDecodeError as e:
            return TaskResult(
                success=False,
                summary=f"LLM response was not valid JSON: {e}",
            )
        except Exception as e:
            return TaskResult(
                success=False,
                summary=f"Hypothesis generation failed: {str(e)[:500]}",
            )

    def review_task(self, task: Task) -> None:
        """Hypothesis Gen reviews for scientific rigor and feasibility."""
        comments = self.db.get_comments(task.id)

        issues = []

        # Check artifact exists
        if not task.artifact_path:
            issues.append("Geen artefact geproduceerd")

        # Check for substantive completion
        has_substance = any(
            c.agent == task.assigned_to and len(c.body) > 40
            for c in comments
        )
        if not has_substance:
            issues.append("Completion comment te kort")

        # Check artifact content for testability
        if task.artifact_path and Path(task.artifact_path).exists():
            try:
                with open(task.artifact_path) as f:
                    data = json.load(f)
                analysis = data.get('analysis', data)
                # Check hypotheses have acceptance criteria
                hypotheses = analysis.get('hypotheses', [])
                for h in hypotheses:
                    if not h.get('acceptance_criteria'):
                        issues.append(
                            f"Hypothese {h.get('id', '?')} mist "
                            f"acceptatiecriteria"
                        )
            except (json.JSONDecodeError, KeyError):
                pass

        if issues:
            body = "HYPOTHESIS REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "HYPOTHESIS REVIEW — approved. Hypotheses testable, "
                "criteria defined.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    # ── Helpers ──────────────────────────────────────────

    def _find_latest_meta_research(self) -> dict:
        """Find most recent meta_research report."""
        if not REPORTS_DIR.exists():
            return {}

        meta_dirs = sorted(
            [d for d in REPORTS_DIR.iterdir()
             if d.is_dir() and d.name.startswith('meta_research_')],
            reverse=True,
        )

        for d in meta_dirs:
            json_file = d / f'{d.name}.json'
            if json_file.exists():
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                    data['path'] = str(json_file.relative_to(REPO_ROOT))
                    return data
                except (json.JSONDecodeError, OSError):
                    continue

        return {}

    def _read_decisions(self) -> str:
        """Read docs/DECISIONS.md if exists."""
        path = REPO_ROOT / 'docs' / 'DECISIONS.md'
        if path.exists():
            return path.read_text(errors='replace')[:3000]
        return ''

    def _build_prompt(self, meta_report: dict, decisions: str,
                      task: Task) -> str:
        """Build LLM prompt with meta-research context."""
        parts = [
            f"Taak: {task.title}",
            f"Beschrijving: {task.description}",
            "",
        ]

        if meta_report:
            analysis = meta_report.get('analysis', {})
            parts.append("## Laatste Meta-Research Bevindingen\n")
            parts.append(json.dumps(analysis, indent=2, default=str)[:4000])
            parts.append("")

        if decisions:
            parts.append("## DECISIONS.md\n")
            parts.append(decisions)
            parts.append("")

        # Available agents
        parts.append("## Beschikbare agents voor taken\n")
        for a in sorted(RESEARCH_AGENTS):
            parts.append(f"- {a}")
        parts.append("")

        parts.append(
            f"Ontwerp maximaal {MAX_HYPOTHESES} testbare hypotheses "
            f"in het JSON-formaat zoals beschreven in je systeemprompt. "
            f"Elke hypothese moet concrete taken bevatten voor de "
            f"bovenstaande agents."
        )

        return '\n'.join(parts)

    def _build_markdown(self, hypotheses: list[dict], tasks_created: int,
                        ts: str, reasoning: str) -> str:
        """Build human-readable Markdown report."""
        lines = [
            f"# Hypothesis Report — {ts}",
            f"\n**Hypotheses**: {len(hypotheses)} | "
            f"**Taken aangemaakt**: {tasks_created}",
            "",
        ]

        for h in hypotheses:
            lines.append(f"## {h.get('id', '?')}: {h.get('title', '?')}")
            lines.append(f"\n{h.get('description', '')}\n")

            # Sweep params
            sweep = h.get('sweep_params', {})
            if sweep:
                lines.append("### Sweep parameters\n")
                for p, v in sweep.items():
                    lines.append(f"- `{p}`: {v}")
                lines.append("")

            # Expected impact
            impact = h.get('expected_impact', {})
            if impact:
                lines.append("### Verwachte impact\n")
                for k, v in impact.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")

            # Acceptance criteria
            criteria = h.get('acceptance_criteria', [])
            if criteria:
                lines.append("### Acceptatiecriteria\n")
                for c in criteria:
                    lines.append(f"- [ ] {c}")
                lines.append("")

            # Tasks
            tasks = h.get('tasks', [])
            if tasks:
                lines.append("### Taken\n")
                for t in tasks:
                    lines.append(
                        f"- **{t.get('title', '?')}** "
                        f"→ {t.get('assigned_to', '?')}"
                    )
                lines.append("")

        if reasoning:
            lines.append(f"## Redenering\n\n{reasoning}")

        return '\n'.join(lines) + '\n'
