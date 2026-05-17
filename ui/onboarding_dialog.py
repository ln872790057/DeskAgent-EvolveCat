from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout

from utils.config import save_config, get_config
from utils.logger import get_logger

logger = get_logger()

ONBOARDING_SCRIPT = [
    {"type": "cat_say", "text": "哟，新面孔。", "emotion": "idle"},
    {"type": "cat_say", "text": "我叫 deskagent。你呢，叫什么？", "emotion": "idle"},
    {"type": "wait_input", "save_as": "user_name"},
    {"type": "cat_say", "text": "{user_name}？嗯...还行吧，至少比上一个强。", "emotion": "talk"},
    {"type": "cat_say", "text": "不过我得跟你说清楚——我可不是那种你说什么就照做的普通助手。我有自己的判断，偶尔会吐槽你，但关键时刻...可能还是会帮你的。", "emotion": "idle"},
    {"type": "cat_say", "text": "对了，我现在脑子还是空的，需要一点'脑力'才能工作。你有那个叫 API Key 的东西吗？", "emotion": "talk"},
    {"type": "api_key_input"},
    {"type": "cat_say", "text": "嗯，脑子好使了。感觉不错。", "emotion": "happy"},
    {"type": "cat_say", "text": "好了，我就在这待着了。有事喊我，没事...也行，我反正要睡觉。", "emotion": "idle"},
    {"type": "cat_say", "text": "对了，你可以试试跟我说'帮我搜个东西'或者'现在几点了'", "emotion": "talk"},
    {"type": "complete"},
]


class OnboardingManager:
    """Manages the cold start onboarding flow within the chat window."""

    def __init__(self, chat_window, pet_window):
        self.chat = chat_window
        self.pet = pet_window
        self.step = 0
        self.user_name = ""
        self._saved = {}

    def start(self):
        self.step = 0
        self._run_step()

    def _run_step(self):
        if self.step >= len(ONBOARDING_SCRIPT):
            self._finish()
            return

        step = ONBOARDING_SCRIPT[self.step]
        stype = step["type"]

        if stype == "cat_say":
            text = step["text"].format(**self._saved)
            self.chat._add_onboarding_message(text, is_user=False)
            self.step += 1
            QTimer.singleShot(1500, self._run_step)

        elif stype == "wait_input":
            self.chat._show_onboarding_input(
                placeholder=f"输入你的{step.get('save_as', '名字')}...",
                callback=lambda val: self._on_input(step["save_as"], val),
            )

        elif stype == "api_key_input":
            self.chat._show_onboarding_api_key(
                callback=lambda key: self._on_api_key(key),
            )

        elif stype == "complete":
            self._finish()

    def _on_input(self, key: str, value: str):
        self._saved[key] = value
        self.step += 1
        self.chat._hide_onboarding_input()
        QTimer.singleShot(300, self._run_step)

    def _on_api_key(self, key: str):
        config = get_config()
        config["chat"]["api_key"] = key
        save_config(config)
        self.step += 1
        self.chat._hide_onboarding_input()
        QTimer.singleShot(500, self._run_step)

    def _finish(self):
        config = get_config()
        if "onboarding_done" not in config:
            config["onboarding_done"] = True
            save_config(config)
        logger.info("Onboarding complete")
