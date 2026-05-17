"""TaskManager - task queue and chat worker coordinator."""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from utils.logger import get_logger

logger = get_logger("agent.task_manager")


class TaskType(Enum):
    CHAT = "chat"
    TASK = "task"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    task_type: TaskType = TaskType.TASK
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float = None
    result: str = None
    error: str = None
    messages: list = field(default_factory=list)
    tool_calls_log: list = field(default_factory=list)
    cancel_requested: bool = False


class TaskManager(QObject):
    task_created = Signal(str)
    task_status_changed = Signal(str, str)
    task_completed = Signal(str)
    task_failed = Signal(str)
    tool_status_update = Signal(str, str, str)
    tool_result_update = Signal(str, str, str)
    hitl_confirmation_needed = Signal(str, str, dict)
    stream_chunk = Signal(str, str)
    stream_done = Signal(str, str)

    def __init__(self, agent, parent=None):
        super().__init__(parent)
        self._agent = agent
        self._tasks: dict[str, Task] = {}
        self._queue: list[str] = []
        self._current_task_id: str | None = None
        self._workers: dict[str, object] = {}

    def create_task(self, name: str, task_type: TaskType,
                    message: str, context: dict = None) -> str:
        task = Task(name=name[:30], task_type=task_type)
        task.messages = [{"role": "user", "content": message}]
        self._tasks[task.task_id] = task
        logger.info(f"TaskManager create_task: tid={task.task_id} type={task_type.value} text={message[:60]}")
        self.task_created.emit(task.task_id)

        if task_type == TaskType.CHAT:
            # Chat workers are independent: a long task must not block conversation.
            task.status = TaskStatus.RUNNING
            self.task_status_changed.emit(task.task_id, task.status.value)
            self._start_worker(task)
        else:
            task.status = TaskStatus.PENDING
            self._queue.append(task.task_id)
            self.task_status_changed.emit(task.task_id, task.status.value)
            self._process_queue()

        return task.task_id

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            if task_id in self._queue:
                self._queue.remove(task_id)
            self.task_status_changed.emit(task_id, task.status.value)
            return True
        if task.status == TaskStatus.RUNNING:
            task.cancel_requested = True
            worker = self._workers.get(task_id)
            if worker and hasattr(worker, "request_cancel"):
                worker.request_cancel()
            return True
        return False

    def resolve_hitl(self, task_id: str, tool_name: str, approved: bool) -> bool:
        worker = self._workers.get(task_id)
        if not worker or not hasattr(worker, "resolve_hitl"):
            return False
        worker.resolve_hitl(tool_name, approved)
        return True

    def get_task(self, task_id: str) -> Task:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.task_type == TaskType.TASK]

    def clear_completed(self):
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        for tid in to_remove:
            del self._tasks[tid]

    def _process_queue(self):
        if self._current_task_id or not self._queue:
            return
        tid = self._queue.pop(0)
        task = self._tasks.get(tid)
        if not task or task.status == TaskStatus.CANCELLED:
            logger.debug(f"[TaskMgr] process_queue skip: tid={tid} (cancelled or missing)")
            self._process_queue()
            return
        task.status = TaskStatus.RUNNING
        self._current_task_id = tid
        logger.info(f"[TaskMgr] process_queue start: tid={tid} queue_remaining={len(self._queue)}")
        self.task_status_changed.emit(tid, task.status.value)
        self._start_worker(task)

    def _start_worker(self, task: Task):
        from agent.task_worker import TaskWorker

        worker = TaskWorker(task, self._agent)
        self._workers[task.task_id] = worker
        logger.info(f"[TaskMgr] worker_created: tid={task.task_id} type={task.task_type.value} name={task.name[:30]}")
        queued = Qt.ConnectionType.QueuedConnection
        worker.task_done.connect(self._on_worker_done, queued)
        worker.tool_status.connect(self._on_tool_status, queued)
        worker.tool_result.connect(self._on_tool_result, queued)
        worker.stream_chunk.connect(self._on_stream_chunk, queued)
        worker.stream_done.connect(self._on_stream_done, queued)
        worker.hitl_needed.connect(self._on_hitl_needed, queued)
        worker.finished.connect(lambda tid=task.task_id: self._on_worker_finished(tid), queued)
        worker.start()
        logger.debug(f"[TaskMgr] worker_started: tid={task.task_id} signals_connected")

    def _on_worker_done(self, tid: str, result: str, error: str):
        from utils.logger import get_logger

        get_logger().info(
            f"Worker done: {tid} result_len={len(result or '')} "
            f"error={error[:80] if error else 'none'}"
        )
        task = self._tasks.get(tid)
        if not task:
            return

        task.completed_at = time.time()
        if error:
            task.status = TaskStatus.FAILED
            task.error = error
            self.task_failed.emit(tid)
        elif task.cancel_requested:
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.COMPLETED
            task.result = result
            logger.info(f"TaskManager emit task_completed: tid={tid} result_len={len(result or '')}")
            self.task_completed.emit(tid)

        self.task_status_changed.emit(tid, task.status.value)

        if task.task_type == TaskType.TASK and self._current_task_id == tid:
            self._current_task_id = None
            self._process_queue()

    def _on_worker_finished(self, tid: str):
        worker = self._workers.pop(tid, None)
        if worker:
            worker.deleteLater()

    def _on_tool_status(self, tid, tool_name, text):
        self.tool_status_update.emit(tid, tool_name, text)

    def _on_tool_result(self, tid, tool_name, text):
        self.tool_result_update.emit(tid, tool_name, text)

    def _on_stream_chunk(self, tid, chunk):
        self.stream_chunk.emit(tid, chunk)

    def _on_stream_done(self, tid, full):
        logger.info(f"TaskManager stream_done forwarded: tid={tid} reply_len={len(full or '')}")
        self.stream_done.emit(tid, full)

    def _on_hitl_needed(self, tid, tool_name, params):
        self.hitl_confirmation_needed.emit(tid, tool_name, params)
