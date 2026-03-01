"""BaseAgent — abstract heartbeat protocol for all lab agents."""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from lab.config import REPO_ROOT, REPORTS_DIR, safe_write_check
from lab.db import LabDB
from lab.models import Task, TaskResult
from lab.notifier import LabNotifier

logger = logging.getLogger('lab.agent')


class BaseAgent(ABC):
    """Every agent follows the same heartbeat protocol:
    1. Review others' work (peer reviews + proposal reviews)
    2. Work on own tasks (rework first, then new)
    """

    name: str = ''
    role: str = ''
    is_llm: bool = False

    def __init__(self, db: LabDB, notifier: LabNotifier):
        self.db = db
        self.notifier = notifier
        self.logger = logging.getLogger(f'lab.agent.{self.name}')

    def heartbeat(self) -> dict:
        """Run one heartbeat cycle. Returns stats dict."""
        stats = {'reviews': 0, 'tasks': 0, 'promotions': 0, 'errors': 0}
        self.db.set_status(self.name, 'working')

        try:
            # Step 1a: Peer reviews (alle agents)
            peer_reviews = self.db.get_peer_reviews_needing_review(self.name)
            for task in peer_reviews:
                try:
                    self.review_task(task)
                    stats['reviews'] += 1
                except Exception as e:
                    self.logger.error(f"Review failed for task #{task.id}: {e}")
                    stats['errors'] += 1

            # Step 1b: Proposal reviews (alleen gatekeepers, query filtert)
            proposals = self.db.get_proposals_needing_gatekeeper_review(
                self.name)
            for task in proposals:
                try:
                    self.review_proposal(task)
                    stats['reviews'] += 1
                except Exception as e:
                    self.logger.error(
                        f"Proposal review failed for #{task.id}: {e}")
                    stats['errors'] += 1

            # Step 2: Pick up tasks that got needs_changes reviews
            rejected = self.db.get_my_rejected_tasks(self.name)
            for task in rejected:
                try:
                    self.db.transition(task.id, 'in_progress', actor=self.name)
                    self.logger.info(f"Reworking #{task.id} after needs_changes")
                except ValueError:
                    pass  # Already moved

            # Step 3: Work on own tasks (rework first, then new)
            rework = self.db.get_my_tasks(self.name, status='in_progress')
            new_tasks = self.db.get_my_tasks(self.name, status='todo')
            my_tasks = rework + new_tasks
            if my_tasks:
                task = my_tasks[0]  # rework or oldest first
                if task.status == 'todo':
                    self.db.transition(task.id, 'in_progress', actor=self.name)
                self.db.set_status(self.name, 'working', task_id=task.id,
                                   note=task.title)

                try:
                    result = self.execute_task(task)
                    if result.artifact_path:
                        self.db.set_artifact(
                            task.id, result.artifact_path,
                            sha256=result.sha256,
                            git_hash=result.git_hash,
                            cmd=result.cmd,
                        )
                    # Post completion comment
                    self.db.add_comment(
                        task.id, self.name, result.summary, 'comment'
                    )
                    # Move to peer_review + create review entries for peers
                    self.db.transition(task.id, 'peer_review', actor=self.name)
                    goal_agents = self.db.get_goal_agents(task.goal_id)
                    for agent_name in goal_agents:
                        if agent_name != self.name:
                            self.db.create_review(task.id, reviewer=agent_name)
                    stats['tasks'] += 1
                except Exception as e:
                    self.logger.error(f"Task #{task.id} failed: {e}")
                    self.db.add_comment(
                        task.id, self.name,
                        f"ERROR: {str(e)[:500]}", 'comment'
                    )
                    # Try to move task back to blocked so it can be retried
                    try:
                        self.db.transition(task.id, 'blocked', actor=self.name)
                        self.db.add_comment(
                            task.id, self.name,
                            f"\u26a0\ufe0f Task blocked due to error: {str(e)[:200]}",
                            'comment'
                        )
                    except Exception:
                        pass  # Best effort
                    stats['errors'] += 1

        finally:
            self.db.set_status(self.name, 'idle')

        return stats

    @abstractmethod
    def execute_task(self, task: Task) -> TaskResult:
        """Agent-specific work logic. Must return TaskResult."""
        ...

    @abstractmethod
    def review_task(self, task: Task) -> None:
        """Review another agent's work. Must post comment + update review."""
        ...

    def review_proposal(self, task: Task) -> None:
        """Review a boss proposal. Default: no-op. Gatekeepers override."""
        pass

    # ── Helpers ───────────────────────────────────────────

    def _git_hash(self) -> str:
        """Get current short git hash (no subprocess).

        Handles: loose refs, packed-refs (after git gc), detached HEAD.
        """
        try:
            head = (REPO_ROOT / '.git' / 'HEAD').read_text().strip()
            if head.startswith('ref:'):
                ref = head.split(' ', 1)[1]
                loose = REPO_ROOT / '.git' / ref
                if loose.exists():
                    return loose.read_text().strip()[:7]
                # After git gc: ref lives in packed-refs
                packed = REPO_ROOT / '.git' / 'packed-refs'
                if packed.exists():
                    for line in packed.read_text().splitlines():
                        if line.startswith('#'):
                            continue
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == ref:
                            return parts[0][:7]
                return 'unknown'
            return head[:7]  # detached HEAD
        except Exception:
            return 'unknown'

    def _file_sha256(self, path: Path) -> str:
        """Compute SHA-256 of a file."""
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def _write_report(self, name: str, data: dict, md_content: str) -> Path:
        """Write JSON+MD report pair to reports/lab/. Returns JSON path."""
        import json
        from datetime import datetime, timezone

        report_dir = REPORTS_DIR / name
        report_dir.mkdir(parents=True, exist_ok=True)

        json_path = report_dir / f"{name}.json"
        md_path = report_dir / f"{name}.md"

        safe_write_check(json_path)
        safe_write_check(md_path)

        data['_meta'] = {
            'agent': self.name,
            'git_hash': self._git_hash(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)
        with open(md_path, 'w') as f:
            f.write(md_content)

        return json_path
