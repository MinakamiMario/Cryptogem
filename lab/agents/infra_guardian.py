"""Infrastructure Guardian — repo integrity enforcer.

Draait `make check`, bewaakt schema invariants, detecteert tm_bars regressies.
Rule-based agent (geen LLM).
"""
from __future__ import annotations

import subprocess

from lab.agents.base import BaseAgent
from lab.config import REPO_ROOT
from lab.models import Task, TaskResult


class InfraGuardian(BaseAgent):
    name = 'infra_guardian'
    role = 'Repo Integrity Enforcer'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Run infrastructure checks based on task description."""
        title_lower = task.title.lower()

        if 'make check' in title_lower or 'full check' in title_lower:
            return self._run_make_check(task)
        elif 'schema' in title_lower or 'tm_bars' in title_lower:
            return self._check_schema_invariants(task)
        else:
            # Default: run make check
            return self._run_make_check(task)

    def review_task(self, task: Task) -> None:
        """Infra Guardian reviews ALL tasks — checks artifact integrity."""
        comments = self.db.get_comments(task.id)
        artifact = task.artifact_path

        issues = []

        # Check: artifact exists?
        if artifact:
            from pathlib import Path
            if not Path(artifact).exists():
                issues.append(f"Artifact niet gevonden: {artifact}")
            elif not task.artifact_sha256:
                issues.append("Artifact mist SHA-256 hash (provenance)")

        # Check: has substantive completion comment?
        has_completion = any(
            c.agent == task.assigned_to and len(c.body) > 20
            for c in comments
        )
        if not has_completion:
            issues.append("Geen substantieve completion comment gevonden")

        # Post review
        if issues:
            body = "INFRA REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            comment_id = self.db.add_comment(
                task.id, self.name, body, 'review'
            )
            self.db.update_review(task.id, self.name, 'needs_changes',
                                  comment_id)
        else:
            comment_id = self.db.add_comment(
                task.id, self.name,
                "INFRA REVIEW — approved. Artifact integrity OK.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', comment_id)

    def _run_make_check(self, task: Task) -> TaskResult:
        """Run `make check` and report results."""
        try:
            result = subprocess.run(
                ['make', 'check'],
                capture_output=True, text=True,
                cwd=str(REPO_ROOT),
                timeout=300,  # 5 min max
            )
            passed = result.returncode == 0
            output = result.stdout[-2000:] if result.stdout else ''
            errors = result.stderr[-1000:] if result.stderr else ''

            summary_lines = []
            # Parse test count from output
            for line in output.split('\n'):
                if 'passed' in line.lower() or 'failed' in line.lower():
                    summary_lines.append(line.strip())

            summary = (
                f"make check: {'PASS' if passed else 'FAIL'}\n"
                f"Return code: {result.returncode}\n"
                + '\n'.join(summary_lines[-5:])
            )

            self.notifier.infra_check(passed, summary)

            # Write report
            report_data = {
                'passed': passed,
                'return_code': result.returncode,
                'stdout_tail': output,
                'stderr_tail': errors,
            }
            md = f"# Infrastructure Check\n\n{summary}\n"
            if errors:
                md += f"\n## Errors\n```\n{errors}\n```\n"

            report_name = f"infra_check_{task.id}"
            json_path = self._write_report(report_name, report_data, md)

            return TaskResult(
                success=passed,
                summary=summary,
                artifact_path=str(json_path),
                sha256=self._file_sha256(json_path),
                git_hash=self._git_hash(),
                cmd='make check',
            )

        except subprocess.TimeoutExpired:
            return TaskResult(
                success=False,
                summary="make check timed out after 300s",
            )
        except Exception as e:
            return TaskResult(
                success=False,
                summary=f"make check error: {e}",
            )

    def _check_schema_invariants(self, task: Task) -> TaskResult:
        """Check for tm_bars regression and schema issues."""
        import re

        issues = []
        tb_dir = REPO_ROOT / 'trading_bot'

        # Check for tm_bars usage (should be time_max_bars only)
        for py_file in tb_dir.glob('*.py'):
            if py_file.name.startswith('.'):
                continue
            content = py_file.read_text(errors='replace')
            # Look for tm_bars as a key (not in comments or normalize_cfg)
            matches = re.findall(r"['\"]tm_bars['\"]", content)
            if matches and 'normalize_cfg' not in py_file.name:
                # Filter: ok in normalize_cfg function itself
                if "tm_bars" in content and "time_max_bars" not in content:
                    issues.append(
                        f"{py_file.name}: uses 'tm_bars' without "
                        f"'time_max_bars' — possible regression"
                    )

        passed = len(issues) == 0
        summary = (
            f"Schema invariant check: {'PASS' if passed else 'FAIL'}\n"
            f"Issues: {len(issues)}"
        )
        if issues:
            summary += '\n' + '\n'.join(f"- {i}" for i in issues)

        return TaskResult(success=passed, summary=summary)
