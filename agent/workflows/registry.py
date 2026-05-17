"""Default workflow registry."""
from __future__ import annotations

from agent.runtime.workflow_engine import WorkflowEngine
from agent.workflows.research import ResearchWorkflow


def create_default_workflow_engine() -> WorkflowEngine:
    engine = WorkflowEngine()
    engine.register(ResearchWorkflow())
    return engine

