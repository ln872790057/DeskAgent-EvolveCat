"""Minimal workflow registry for the new agent runtime."""
from __future__ import annotations

from agent.runtime.task_session import TaskSession
from agent.runtime.workflow import Workflow, WorkflowResult


class WorkflowEngine:
    def __init__(self):
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        self._workflows[workflow.name] = workflow

    def get(self, name: str) -> Workflow | None:
        return self._workflows.get(name)

    def run(self, name: str, session: TaskSession, agent=None) -> WorkflowResult:
        workflow = self.get(name)
        if not workflow:
            return WorkflowResult("failed", f"workflow not registered: {name}", str(session.artifacts.root if session.artifacts else ""))
        return workflow.run(session, agent=agent)
