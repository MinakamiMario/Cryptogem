"""Meta-Research Agent — pattern miner across lab artifacts.

Reads reports/**/*.json + docs/DECISIONS.md, uses LLM to identify
patterns, contradictions, and follow-up recommendations.
Writes artifact to reports/lab/meta_research_<ts>.{json,md}.
"""
from __future__ import annotations

import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from lab.agents.base import BaseAgent
from lab.config import REPO_ROOT, REPORTS_DIR
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.meta_research')

# Max reports to include in LLM context (prevent token overflow)
MAX_REPORTS = 30
MAX_REPORT_SIZE = 2000  # chars per report summary


class MetaResearchAgent(BaseAgent):
    name = 'meta_research'
    role = 'Pattern Miner / Research Synthesizer'
    is_llm = True

    def execute_task(self, task: Task) -> TaskResult:
        """Scan all lab artifacts, synthesize patterns via LLM."""
        try:
            # Step 1: Gather artifacts
            artifacts = self._gather_artifacts()
            decisions = self._read_decisions()

            if not artifacts and not decisions:
                return TaskResult(
                    success=True,
                    summary="Geen artefacten gevonden om te analyseren. "
                            "Lab is nog leeg — wacht op eerste agent-output.",
                )

            # Step 2: Build LLM prompt
            prompt = self._build_prompt(artifacts, decisions, task)

            # Step 3: Call LLM
            from lab.llm import ask_json
            response = ask_json(prompt, agent_name=self.name)

            # Step 4: Write artifact
            ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            report_name = f'meta_research_{ts}'

            report_data = {
                'task_id': task.id,
                'artifacts_scanned': len(artifacts),
                'decisions_found': bool(decisions),
                'analysis': response,
            }

            # Build markdown
            md = self._build_markdown(response, len(artifacts), ts)

            json_path = self._write_report(report_name, report_data, md)

            # Summary for comment
            n_patterns = len(response.get('patterns', []))
            n_recs = len(response.get('recommendations', []))
            summary = (
                f"Meta-research scan: {len(artifacts)} artefacten geanalyseerd.\n"
                f"Gevonden: {n_patterns} patronen, {n_recs} aanbevelingen.\n"
                f"Artefact: {json_path}"
            )

            return TaskResult(
                success=True,
                summary=summary,
                artifact_path=str(json_path),
                sha256=self._file_sha256(json_path),
                git_hash=self._git_hash(),
                cmd='meta_research_scan',
            )

        except json.JSONDecodeError as e:
            return TaskResult(
                success=False,
                summary=f"LLM response was not valid JSON: {e}",
            )
        except Exception as e:
            return TaskResult(
                success=False,
                summary=f"Meta-research failed: {str(e)[:500]}",
            )

    def review_task(self, task: Task) -> None:
        """Meta-Research reviews for evidence quality and citation accuracy."""
        comments = self.db.get_comments(task.id)

        issues = []

        # Check: has artifact?
        if not task.artifact_path:
            issues.append("Geen artefact geproduceerd")

        # Check: completion comment with substance
        has_substance = any(
            c.agent == task.assigned_to and len(c.body) > 50
            for c in comments
        )
        if not has_substance:
            issues.append("Completion comment te kort (<50 chars)")

        # Check artifact for citation quality (if it's a JSON report)
        if task.artifact_path and Path(task.artifact_path).exists():
            try:
                with open(task.artifact_path) as f:
                    data = json.load(f)
                # Check if analysis has evidence references
                analysis = data.get('analysis', data)
                patterns = analysis.get('patterns', [])
                uncited = [p for p in patterns
                           if not p.get('evidence')]
                if uncited:
                    issues.append(
                        f"{len(uncited)} patronen zonder bronverwijzing"
                    )
            except (json.JSONDecodeError, KeyError):
                pass  # Not a structured report, skip

        if issues:
            body = "META-RESEARCH REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "META-RESEARCH REVIEW — approved. Evidence quality OK, "
                "citations present.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    # ── Helpers ──────────────────────────────────────────

    def _gather_artifacts(self) -> list[dict]:
        """Scan reports/lab/**/*.json for analysis artifacts."""
        artifacts = []
        lab_reports = REPORTS_DIR

        if not lab_reports.exists():
            return artifacts

        json_files = sorted(
            lab_reports.glob('**/*.json'),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:MAX_REPORTS]

        for jf in json_files:
            try:
                with open(jf) as f:
                    data = json.load(f)
                # Extract key info, keep it compact
                summary = {
                    'path': str(jf.relative_to(REPO_ROOT)),
                    'agent': data.get('_meta', {}).get('agent', 'unknown'),
                    'timestamp': data.get('_meta', {}).get('timestamp', ''),
                }
                # Include first-level keys (truncated)
                for k, v in data.items():
                    if k == '_meta':
                        continue
                    if isinstance(v, dict):
                        summary[k] = {
                            kk: str(vv)[:200] for kk, vv in
                            list(v.items())[:10]
                        }
                    elif isinstance(v, list):
                        summary[k] = v[:5]
                    else:
                        summary[k] = str(v)[:200]
                artifacts.append(summary)
            except (json.JSONDecodeError, OSError):
                continue

        return artifacts

    def _read_decisions(self) -> str:
        """Read docs/DECISIONS.md if it exists."""
        decisions_path = REPO_ROOT / 'docs' / 'DECISIONS.md'
        if decisions_path.exists():
            content = decisions_path.read_text(errors='replace')
            return content[:5000]  # Cap at 5K chars
        return ''

    def _build_prompt(self, artifacts: list[dict], decisions: str,
                      task: Task) -> str:
        """Build the LLM prompt with artifact summaries."""
        parts = [
            f"Taak: {task.title}",
            f"Beschrijving: {task.description}",
            "",
            f"Er zijn {len(artifacts)} lab-artefacten beschikbaar.",
            "",
        ]

        if artifacts:
            parts.append("## Artefacten (samengevat)\n")
            for i, a in enumerate(artifacts[:MAX_REPORTS]):
                compact = json.dumps(a, default=str)[:MAX_REPORT_SIZE]
                parts.append(f"### [{i+1}] {a.get('path', '?')}")
                parts.append(compact)
                parts.append("")

        if decisions:
            parts.append("## DECISIONS.md (architectuurbeslissingen)\n")
            parts.append(decisions)
            parts.append("")

        parts.append(
            "Analyseer bovenstaande artefacten en produceer je output "
            "in het JSON-formaat zoals beschreven in je systeemprompt."
        )

        return '\n'.join(parts)

    def _build_markdown(self, analysis: dict, n_artifacts: int,
                        ts: str) -> str:
        """Build human-readable Markdown report."""
        lines = [
            f"# Meta-Research Report — {ts}",
            f"\n**Artefacten gescand**: {n_artifacts}",
            "",
        ]

        # Patterns
        patterns = analysis.get('patterns', [])
        if patterns:
            lines.append("## Patronen\n")
            for p in patterns:
                conf = p.get('confidence', '?')
                lines.append(f"### [{conf.upper()}] {p.get('claim', '?')}")
                lines.append(f"- Domein: {p.get('domain', '?')}")
                evidence = p.get('evidence', [])
                if evidence:
                    lines.append("- Bronnen:")
                    for e in evidence:
                        lines.append(f"  - `{e}`")
                lines.append("")

        # Contradictions
        contras = analysis.get('contradictions', [])
        if contras:
            lines.append("## Contradictions\n")
            for c in contras:
                lines.append(f"### {c.get('topic', '?')}")
                lines.append(f"- Source A (`{c.get('source_a', '?')}`): "
                             f"{c.get('claim_a', '?')}")
                lines.append(f"- Source B (`{c.get('source_b', '?')}`): "
                             f"{c.get('claim_b', '?')}")
                lines.append("")

        # Recommendations
        recs = analysis.get('recommendations', [])
        if recs:
            lines.append("## Aanbevelingen\n")
            for r in recs:
                lines.append(f"- **{r.get('action', '?')}** "
                             f"(→ {r.get('assigned_to', '?')}, "
                             f"P{r.get('priority', 5)})")
                lines.append(f"  {r.get('rationale', '')}")
                lines.append("")

        # Summary
        summary = analysis.get('summary', '')
        if summary:
            lines.append(f"## Samenvatting\n\n{summary}")

        return '\n'.join(lines) + '\n'
