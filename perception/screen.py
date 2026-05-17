import time
import base64
import io

from PySide6.QtCore import QThread, Signal

from utils.logger import get_logger

logger = get_logger()


class ScreenPerceiver(QThread):
    screen_understood = Signal(str)

    def __init__(self, vision_client, interval: int = 300):
        super().__init__()
        self.vision_client = vision_client
        self.interval = interval
        self._running = False
        self._last_title = ""

    def run(self):
        self._running = True
        while self._running:
            try:
                # Optimization: only capture if window title changed
                current_title = self._get_active_title()
                if current_title == self._last_title and self._last_title:
                    self.msleep(self.interval * 1000)
                    continue
                self._last_title = current_title

                import pyautogui
                screenshot = pyautogui.screenshot()
                buf = io.BytesIO()
                screenshot.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

                prompt = "描述这张截图：1)用户正在使用什么应用 2)应用名称/窗口标题 3)用户在做什么具体操作。用中文回答，30字以内。"
                result = self.vision_client.chat_with_image(prompt, img_b64)
                if result:
                    self.screen_understood.emit(result[:80])
            except Exception:
                pass  # Silent fail

            for _ in range(self.interval):
                if not self._running:
                    break
                self.msleep(1000)

    def _get_active_title(self) -> str:
        try:
            from utils.platform_compat import get_active_window_title
            return get_active_window_title()
        except Exception:
            return ""

    def get_current_summary(self) -> str:
        return getattr(self, "_last_summary", "")

    def stop(self):
        self._running = False
