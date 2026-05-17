"""Task session model shared by workflows."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from agent.runtime.artifact_store import ArtifactStore


@dataclass
class TaskSession:
    user_message: str
    task_type: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "created"
    current_stage: str = "created"
    plan: dict = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    completed_at: str = ""
    artifacts: ArtifactStore | None = None
    progress_callback: Callable[[str, str], None] | None = None

    @classmethod
    def create(cls, user_message: str, task_type: str, task_name: str = "") -> "TaskSession":
        session = cls(user_message=user_message, task_type=task_type)
        session.artifacts = ArtifactStore(session.task_id, task_name or task_type)
        return session

    def set_stage(self, stage: str, status: str | None = None) -> None:
        self.current_stage = stage
        if status:
            self.status = status
        if self.progress_callback:
            try:
                self.progress_callback(stage, status or self.status)
            except Exception:
                pass

    def finish(self, status: str = "completed", error: str = "") -> None:
        self.status = status
        self.error = error
        self.completed_at = datetime.now().isoformat(timespec="seconds")
