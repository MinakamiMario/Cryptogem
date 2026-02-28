"""Lab data models — pure dataclasses, no logic."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Goal:
    id: int
    title: str
    agents: list[str]
    description: str = ''
    tasks_per_day: int = 2
    status: str = 'active'
    created_at: str = ''
    updated_at: str = ''

    @staticmethod
    def agents_from_json(raw: str) -> list[str]:
        return json.loads(raw) if isinstance(raw, str) else raw

    def agents_to_json(self) -> str:
        return json.dumps(self.agents)


@dataclass
class Task:
    id: int
    goal_id: int
    title: str
    assigned_to: str
    created_by: str
    description: str = ''
    status: str = 'backlog'
    priority: int = 5
    created_at: str = ''
    updated_at: str = ''
    blocked_since: Optional[str] = None
    artifact_path: Optional[str] = None
    artifact_sha256: Optional[str] = None
    artifact_git_hash: Optional[str] = None
    artifact_cmd: Optional[str] = None


@dataclass
class Comment:
    id: int
    task_id: int
    agent: str
    body: str
    comment_type: str = 'comment'
    created_at: str = ''


@dataclass
class TaskReview:
    id: int
    task_id: int
    reviewer: str
    verdict: str = 'pending'
    comment_id: Optional[int] = None
    created_at: str = ''
    updated_at: str = ''


@dataclass
class AgentStatus:
    agent: str
    status: str = 'idle'
    last_heartbeat: Optional[str] = None
    current_task_id: Optional[int] = None
    progress_note: Optional[str] = None


@dataclass
class TaskResult:
    """Returned by agent.execute_task()."""
    success: bool
    summary: str
    artifact_path: Optional[str] = None
    sha256: Optional[str] = None
    git_hash: Optional[str] = None
    cmd: Optional[str] = None
    details: dict = field(default_factory=dict)
