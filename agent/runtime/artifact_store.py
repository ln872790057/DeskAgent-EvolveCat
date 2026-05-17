"""Artifact persistence for observable long-running workflows."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def safe_name(text: str, max_len: int = 80) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in (text or ""))
    cleaned = "_".join(cleaned.split())
    return (cleaned[:max_len].strip("._-") or "task")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "__dict__") and value.__class__.__module__.startswith("skills."):
        return to_jsonable(vars(value))
    return value


class ArtifactStore:
    """Writes workflow artifacts and per-stage timings to logs/task_runs."""

    def __init__(self, task_id: str, task_name: str = "", root: Path | None = None):
        base = root or (_project_root() / "logs" / "task_runs")
        self.task_id = task_id
        self.root = base / f"{task_id}_{safe_name(task_name)}"
        self.root.mkdir(parents=True, exist_ok=True)
        self._timings: list[dict[str, Any]] = []

    def path(self, name: str) -> Path:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_json(self, name: str, data: Any) -> str:
        path = self.path(name)
        path.write_text(
            json.dumps(to_jsonable(data), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(path)

    def write_text(self, name: str, text: str) -> str:
        path = self.path(name)
        path.write_text(text or "", encoding="utf-8")
        return str(path)

    def append_jsonl(self, name: str, data: Any) -> str:
        path = self.path(name)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(to_jsonable(data), ensure_ascii=False, default=str) + "\n")
        return str(path)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.time()
        started_at = datetime.now().isoformat(timespec="seconds")
        status = "completed"
        error = ""
        try:
            yield
        except Exception as exc:
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed_ms = round((time.time() - started) * 1000)
            self._timings.append({
                "stage": name,
                "status": status,
                "started_at": started_at,
                "elapsed_ms": elapsed_ms,
                "error": error,
            })
            self.write_json("timing.json", self._timings)

    def timing_summary(self) -> list[dict[str, Any]]:
        return list(self._timings)

    def record_stage(self, name: str, started: float, status: str = "completed", error: str = "") -> None:
        self._timings.append({
            "stage": name,
            "status": status,
            "started_at": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "elapsed_ms": round((time.time() - started) * 1000),
            "error": error,
        })
        self.write_json("timing.json", self._timings)
