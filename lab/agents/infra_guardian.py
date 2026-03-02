"""Infrastructure Guardian — repo integrity enforcer.

Bewaakt schema invariants, detecteert tm_bars regressies, checks
file integrity. Rule-based agent (geen LLM).

NOTE: Shell commands (make, pytest, git) are blocked by shell_guard.
CI is canonical — all build/test runs happen via GitHub Actions.
This agent performs in-process checks only.
"""
from __future__ import annotations

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

        if 'schema' in title_lower or 'tm_bars' in title_lower:
            return self._check_schema_invariants(task)
        elif 'integrity' in title_lower or 'file' in title_lower:
            return self._check_file_integrity(task)
        else:
            # Default: run all in-process checks
            return self._run_all_checks(task)

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

    def _run_all_checks(self, task: Task) -> TaskResult:
        """Run all in-process infrastructure checks.

        NOTE: Shell commands (make, pytest) are blocked by shell_guard.
        CI is canonical for build/test. This runs safe in-process checks.
        """
        issues = []

        # 1. Schema invariant check
        schema_result = self._check_schema_invariants(task)
        if not schema_result.success:
            issues.append(f"Schema: {schema_result.summary}")

        # 2. File integrity check
        integrity_result = self._check_file_integrity(task)
        if not integrity_result.success:
            issues.append(f"Integrity: {integrity_result.summary}")

        passed = len(issues) == 0
        summary = (
            f"Infra checks: {'PASS' if passed else 'FAIL'}\n"
            f"Issues: {len(issues)}"
        )
        if issues:
            summary += '\n' + '\n'.join(f"- {i}" for i in issues)

        self.notifier.infra_check(passed, summary)

        report_data = {'passed': passed, 'issues': issues}
        md = f"# Infrastructure Check\n\n{summary}\n"
        report_name = f"infra_check_{task.id}"
        json_path = self._write_report(report_name, report_data, md)

        return TaskResult(
            success=passed,
            summary=summary,
            artifact_path=str(json_path),
            sha256=self._file_sha256(json_path),
            git_hash=self._git_hash(),
            cmd='infra_checks',
        )

    def _check_file_integrity(self, task: Task) -> TaskResult:
        """Check critical file existence and basic integrity."""
        critical_files = [
            'lab/config.py', 'lab/db.py', 'lab/shell_guard.py',
            'lab/notifier.py', 'lab/heartbeat.py',
        ]
        missing = []
        for f in critical_files:
            path = REPO_ROOT / f
            if not path.exists():
                missing.append(f)
            elif path.stat().st_size == 0:
                missing.append(f"{f} (empty)")

        passed = len(missing) == 0
        summary = (
            f"File integrity: {'PASS' if passed else 'FAIL'}\n"
            f"Checked: {len(critical_files)}, "
            f"Missing/empty: {len(missing)}"
        )
        if missing:
            summary += '\n' + '\n'.join(f"- {m}" for m in missing)

        return TaskResult(success=passed, summary=summary)

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
