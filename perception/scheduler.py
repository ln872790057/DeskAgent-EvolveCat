import time
import random
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from utils.platform_compat import get_active_window_title, is_fullscreen
from utils.logger import get_logger

logger = get_logger()

# ── Proactive talk templates ──

TIME_TEMPLATES = {
    (7, 9): "早啊...虽然我不想承认，你起得还挺早。",
    (9, 12): None,  # no specific message, relies on behavior triggers
    (12, 14): "该吃饭了吧？别告诉我你又要加班。",
    (14, 18): None,
    (18, 20): "下班了吗？...你的表情告诉我没有。",
    (20, 22): "还不休息？电脑比你重要还是我比你重要？",
    (22, 1): "该准备睡觉了吧？",
    (1, 7): "还不睡？你不睡我还要睡呢！",
}

MEETING_KEYWORDS = [
    "Zoom", "腾讯会议", "飞书会议", "钉钉会议", "Teams", "Google Meet",
    "Webex", "Skype", "Discord",
]


def _hour_in_range(hour, start, end):
    if start < end:
        return start <= hour < end
    else:
        return hour >= start or hour < end


class ProactiveScheduler(QObject):
    """Manages proactive chat triggers and focus mode."""

    talk_triggered = Signal(str)   # emit talk text
    focus_entered = Signal()
    focus_exited = Signal()

    def __init__(self, pet_window, config: dict):
        super().__init__()
        self.pet = pet_window
        self.config = config
        self._enabled = True
        self._in_focus = False
        self._focus_start_time = None

        # Cooldown tracking
        self._last_talks: list[tuple[float, str]] = []  # (timestamp, type)
        self._last_type_times: dict[str, float] = {}

        # Usage tracking
        self._last_active_title = ""
        self._usage_start = time.time()

        # Main check timer (every 60s)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60000)

        # Focus check timer (every 30s)
        self._focus_timer = QTimer(self)
        self._focus_timer.timeout.connect(self._check_focus)
        self._focus_timer.start(30000)

        # Delayed exit from focus (3 minutes)
        self._focus_exit_timer = QTimer(self)
        self._focus_exit_timer.setSingleShot(True)
        self._focus_exit_timer.timeout.connect(self._exit_focus)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    @property
    def in_focus(self) -> bool:
        return self._in_focus

    def _tick(self):
        if not self._enabled or self._in_focus:
            return

        now = datetime.now()
        hour = now.hour

        # ── Time-based triggers ──
        for (start, end), template in TIME_TEMPLATES.items():
            if template and _hour_in_range(hour, start, end):
                if self._can_talk("time"):
                    self._do_talk(template, "time")
                break

        # ── Behavior triggers ──
        idle_sec = self.pet.get_idle_duration()

        # Continuous use > 2h
        usage_sec = time.time() - self._usage_start
        if usage_sec > 7200 and self._can_talk("usage"):
            self._do_talk("你是不打算下班了吗？我替你心疼你的发际线🐱", "usage")

        # Long idle then resume (>10 min idle, then interaction)
        # Handled by mark_interaction in pet_window

    def _can_talk(self, talk_type: str) -> bool:
        now = time.time()
        min_interval = self.config.get("perception", {}).get(
            "proactive_chat_min_interval", 900
        )

        # Same type cooldown: 2 hours
        last_type_time = self._last_type_times.get(talk_type, 0)
        if now - last_type_time < 7200:
            return False

        # Overall cooldown: half of min_interval (at least 30 min)
        overall_min = max(30, min_interval / 2)
        if self._last_talks:
            last_time, _ = self._last_talks[-1]
            if now - last_time < overall_min:
                return False

        return True

    def _do_talk(self, text: str, talk_type: str):
        now = time.time()
        self._last_talks.append((now, talk_type))
        self._last_type_times[talk_type] = now
        # Keep only last 5
        if len(self._last_talks) > 5:
            self._last_talks = self._last_talks[-5:]
        self.talk_triggered.emit(text)
        logger.info(f"Proactive talk ({talk_type}): {text[:30]}...")

    def mark_user_active(self):
        self._usage_start = time.time()
        self._last_active_title = get_active_window_title()

    # ── Focus mode ──

    def _check_focus(self):
        should_focus = self._detect_focus_condition()

        if should_focus and not self._in_focus:
            self._enter_focus()
        elif not should_focus and self._in_focus:
            # Start delayed exit
            if not self._focus_exit_timer.isActive():
                self._focus_exit_timer.start(180000)  # 3 minutes
        elif should_focus and self._in_focus:
            # Still in focus, cancel any pending exit
            if self._focus_exit_timer.isActive():
                self._focus_exit_timer.stop()

    def _detect_focus_condition(self) -> bool:
        # Fullscreen check
        if is_fullscreen():
            return True

        # Meeting software check
        title = get_active_window_title()
        for kw in MEETING_KEYWORDS:
            if kw.lower() in title.lower():
                return True

        return False

    def _enter_focus(self):
        if self._in_focus:
            return
        self._in_focus = True
        self._focus_start_time = time.time()
        logger.info("Entering focus mode")
        self.focus_entered.emit()

    def _exit_focus(self):
        if not self._in_focus:
            return
        self._in_focus = False
        self._focus_start_time = None
        logger.info("Exiting focus mode")
        self.focus_exited.emit()
        # Optional welcome-back bubble
        QTimer.singleShot(2000, lambda: self.talk_triggered.emit("你终于回来了🐱"))
