"""Base workflow protocol."""
from __future__ import annotations

from dataclasses import dataclass

from agent.runtime.task_session import TaskSession


@dataclass
class WorkflowResult:
    status: str
    message: str
    artifacts_dir: str = ""


class Workflow:
    name = "workflow"

    def run(self, session: TaskSession, agent=None) -> WorkflowResult:
        raise NotImplementedError
