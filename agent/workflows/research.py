"""Research workflow adapter for the generic runtime."""
from __future__ import annotations

from agent.runtime.task_session import TaskSession
from agent.runtime.workflow import Workflow, WorkflowResult
from skills.pro_researcher.researcher import research_topic_execute


class ResearchWorkflow(Workflow):
    name = "research"

    def __init__(self, depth: int = 3, focus: list | None = None, incremental: bool = False):
        self.depth = depth
        self.focus = focus or []
        self.incremental = incremental

    def run(self, session: TaskSession, agent=None) -> WorkflowResult:
        result = research_topic_execute(
            session.user_message,
            depth=self.depth,
            focus=self.focus,
            incremental=self.incremental,
            agent=agent,
            session=session,
        )
        return WorkflowResult(
            status=result.get("status", "failed"),
            message=result.get("message", ""),
            artifacts_dir=str(session.artifacts.root if session.artifacts else ""),
        )
