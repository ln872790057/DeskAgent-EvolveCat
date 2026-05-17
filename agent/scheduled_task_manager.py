"""ScheduledTaskManager - periodic task scheduler with JSON persistence."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date

from PySide6.QtCore import QObject, QTimer, Signal

from utils.logger import get_logger

logger = get_logger("agent.scheduled_task_manager")

SCHEDULED_TASKS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "scheduled_tasks.json"
)

# Module-level singleton for tool access
_instance = None


def set_scheduled_task_manager_instance(mgr):
    global _instance
    _instance = mgr


def get_scheduled_task_manager_instance():
    return _instance


@dataclass
class ScheduledTaskConfig:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    task_type: str = "once"       # once | daily | weekly | cron
    schedule: str = ""            # ISO datetime / HH:MM / W HH:MM / cron expr
    content: str = ""             # Task description without time words
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_fired_at: str | None = None


class ScheduledTaskManager(QObject):
    task_fired = Signal(str, str)    # task_id, content
    tasks_changed = Signal()         # UI refresh trigger

    def __init__(self, task_mgr, pet, parent=None):
        super().__init__(parent)
        self._task_mgr = task_mgr    # TaskManager instance
        self._pet = pet              # PetWindow for bubble notifications
        self._tasks: dict[str, ScheduledTaskConfig] = {}
        self._load()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60000)
        logger.info(f"ScheduledTaskManager started, {len(self._tasks)} tasks loaded")

    # ── Public API ──

    def add_task(self, task_type: str, schedule: str, content: str) -> str:
        cfg = ScheduledTaskConfig(task_type=task_type, schedule=schedule, content=content)
        self._tasks[cfg.task_id] = cfg
        self._save()
        self.tasks_changed.emit()
        logger.info(
            f"[SchedMgr] task added: {cfg.task_id} type={task_type} "
            f"schedule={schedule} content={content[:40]}"
        )
        return cfg.task_id

    def update_task(self, task_id: str, **kwargs) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        for key, val in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, val)
        self._save()
        self.tasks_changed.emit()
        return True

    def delete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        del self._tasks[task_id]
        self._save()
        self.tasks_changed.emit()
        logger.info(f"[SchedMgr] task deleted: {task_id}")
        return True

    def set_enabled(self, task_id: str, enabled: bool) -> bool:
        return self.update_task(task_id, enabled=enabled)

    def get_all_tasks(self) -> list[ScheduledTaskConfig]:
        return list(self._tasks.values())

    def get_task(self, task_id: str) -> ScheduledTaskConfig | None:
        return self._tasks.get(task_id)

    # ── Tick & due checks ──

    def _tick(self):
        now = datetime.now()
        for task in list(self._tasks.values()):
            if not task.enabled:
                continue
            if self._is_due(task, now):
                self._fire(task)

    def _is_due(self, task: ScheduledTaskConfig, now: datetime) -> bool:
        try:
            if task.task_type == "once":
                return self._is_once_due(task, now)
            elif task.task_type == "daily":
                return self._is_daily_due(task, now)
            elif task.task_type == "weekly":
                return self._is_weekly_due(task, now)
            elif task.task_type == "cron":
                return self._is_cron_due(task, now)
        except Exception:
            logger.warning(f"[SchedMgr] is_due error for task {task.task_id}", exc_info=True)
        return False

    def _is_once_due(self, task, now):
        if task.last_fired_at is not None:
            return False
        try:
            target = datetime.fromisoformat(task.schedule)
            return now >= target
        except ValueError:
            return False

    def _is_daily_due(self, task, now):
        try:
            h, m = map(int, task.schedule.split(":"))
        except (ValueError, AttributeError):
            return False
        if now.hour != h or now.minute != m:
            return False
        if task.last_fired_at:
            last_date = datetime.fromisoformat(task.last_fired_at).date()
            if last_date == now.date():
                return False
        return True

    def _is_weekly_due(self, task, now):
        try:
            parts = task.schedule.split()
            weekday = int(parts[0])   # 0=Mon..6=Sun
            h, m = map(int, parts[1].split(":"))
        except (ValueError, IndexError, AttributeError):
            return False
        if now.weekday() != weekday:
            return False
        if now.hour != h or now.minute != m:
            return False
        if task.last_fired_at:
            last_date = datetime.fromisoformat(task.last_fired_at).date()
            if last_date == now.date():
                return False
        return True

    def _is_cron_due(self, task, now):
        try:
            from croniter import croniter
            target_minute = now.replace(second=0, microsecond=0)
            cron = croniter(task.schedule, target_minute)
            prev = cron.get_prev(datetime)
            return prev == target_minute
        except ImportError:
            logger.warning("[SchedMgr] croniter not installed, cron tasks disabled")
            return False
        except Exception:
            return False

    # ── Fire ──

    def _fire(self, task: ScheduledTaskConfig):
        from agent.task_manager import TaskType
        tid = self._task_mgr.create_task(
            name=task.content[:30],
            task_type=TaskType.TASK,
            message=task.content,
        )
        task.last_fired_at = datetime.now().isoformat()

        if task.task_type == "once":
            task.enabled = False

        logger.info(
            f"[SchedMgr] fired: {task.task_id} type={task.task_type} "
            f"-> worker={tid} content={task.content[:40]}"
        )
        self.task_fired.emit(task.task_id, task.content)
        self._save()
        self.tasks_changed.emit()

    # ── Persistence ──

    def _load(self):
        if not os.path.exists(SCHEDULED_TASKS_PATH):
            return
        try:
            with open(SCHEDULED_TASKS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                cfg = ScheduledTaskConfig(**item)
                self._tasks[cfg.task_id] = cfg
            logger.info(f"[SchedMgr] loaded {len(self._tasks)} tasks from disk")
        except Exception as e:
            logger.error(f"[SchedMgr] load failed: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(SCHEDULED_TASKS_PATH), exist_ok=True)
        try:
            data = [asdict(t) for t in self._tasks.values()]
            with open(SCHEDULED_TASKS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[SchedMgr] save failed: {e}")
