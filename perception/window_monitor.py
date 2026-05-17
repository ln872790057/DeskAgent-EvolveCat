from PySide6.QtCore import QThread, Signal

from utils.platform_compat import get_active_window_title, IS_MACOS
from utils.logger import get_logger

logger = get_logger()

KEYWORD_TAGS = {
    "b站": "摸鱼", "bilibili": "摸鱼",
    "抖音": "摸鱼", "douyin": "摸鱼",
    "github": "写代码", "vscode": "写代码",
    "pycharm": "写代码", "cursor": "写代码",
    "飞书": "工作", "钉钉": "工作", "企业微信": "工作",
    "boss": "找工作", "猎聘": "找工作", "拉勾": "找工作", "招聘": "找工作",
    "zoom": "会议", "腾讯会议": "会议", "飞书会议": "会议", "teams": "会议",
    "steam": "打游戏", "游戏": "打游戏",
}


class WindowMonitor(QThread):
    window_changed = Signal(str, str)  # (window_title, tag)
    permission_denied = Signal()
    user_idle = Signal(bool)  # True = idle > 15 min, False = active again

    def __init__(self, interval: int = 30):
        super().__init__()
        self.interval = interval
        self._running = False
        self._last_title = ""
        self._permission_warned = False
        self._same_title_count = 0
        self._was_idle = False

    def run(self):
        self._running = True
        while self._running:
            try:
                title = get_active_window_title()
            except Exception as e:
                error_str = str(e).lower()
                if IS_MACOS and not self._permission_warned:
                    if "not permitted" in error_str or "trusted" in error_str:
                        self.permission_denied.emit()
                        self._permission_warned = True
                title = ""

            if title and title != self._last_title:
                self._last_title = title
                self._same_title_count = 0
                tag = self._detect_tag(title)
                self.window_changed.emit(title, tag)
                if self._was_idle:
                    self._was_idle = False
                    self.user_idle.emit(False)
            elif title:
                self._same_title_count += 1
                # 15 min idle = 30 iterations at 30s interval
                if self._same_title_count >= 30 and not self._was_idle:
                    self._was_idle = True
                    self.user_idle.emit(True)

            for _ in range(self.interval):
                if not self._running:
                    break
                self.msleep(1000)

    def _detect_tag(self, title: str) -> str:
        title_lower = title.lower()
        for keyword, tag in KEYWORD_TAGS.items():
            if keyword in title_lower:
                return tag
        return ""

    def get_current_title(self) -> str:
        return self._last_title

    def stop(self):
        self._running = False
