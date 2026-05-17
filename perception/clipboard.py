import hashlib

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

from utils.logger import get_logger

logger = get_logger()

SENSITIVE_KEYWORDS = ["password", "密码", "token", "secret", "key", "secret_key"]


class ClipboardMonitor(QThread):
    clipboard_changed = Signal(str)

    def __init__(self, interval: int = 2):
        super().__init__()
        self.interval = interval
        self._running = False
        self._last_hash = ""

    def run(self):
        self._running = True
        while self._running:
            try:
                app = QApplication.instance()
                if app is None:
                    self.msleep(self.interval * 1000)
                    continue

                clipboard = app.clipboard()
                if clipboard is None:
                    self.msleep(self.interval * 1000)
                    continue

                text = clipboard.text()
                if not text:
                    self.msleep(self.interval * 1000)
                    continue

                # Content hash comparison
                text_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
                if text_hash == self._last_hash:
                    self.msleep(self.interval * 1000)
                    continue
                self._last_hash = text_hash

                # Filter sensitive content
                text_lower = text.lower()
                if any(kw in text_lower for kw in SENSITIVE_KEYWORDS):
                    self.msleep(self.interval * 1000)
                    continue

                # Truncate > 100 chars
                if len(text) > 100:
                    text = text[:100] + "..."

                self.clipboard_changed.emit(text)
            except Exception:
                pass  # Silent fail

            self.msleep(self.interval * 1000)

    def get_current_text(self) -> str:
        return getattr(self, "_last_text", "")

    def stop(self):
        self._running = False
