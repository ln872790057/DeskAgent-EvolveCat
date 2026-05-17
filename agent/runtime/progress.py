"""Progress events emitted by workflows."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProgressEvent:
    task_id: str
    stage: str
    message: str
    progress: float | None = None
    artifact_path: str | None = None

