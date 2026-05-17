"""LLMRouter — 单一模型配置路由，基于 QSettings"""
from PySide6.QtCore import QSettings
from agent.llm.openai_client import UnifiedClient
from utils.logger import get_logger

logger = get_logger()
SETTINGS = QSettings("AgCat", "PoisonCat")


def get_llm_config() -> dict:
    return {
        "api_key": SETTINGS.value("llm/api_key", ""),
        "base_url": SETTINGS.value("llm/base_url",
                                     "https://ark.cn-beijing.volces.com/api/v3"),
        "model": SETTINGS.value("llm/model", "doubao-seed-2.0-thinking-pro"),
    }


def save_llm_config(api_key: str, base_url: str, model: str):
    SETTINGS.setValue("llm/api_key", api_key)
    SETTINGS.setValue("llm/base_url", base_url)
    SETTINGS.setValue("llm/model", model)
    SETTINGS.sync()


class LLMRouter:
    """单一路由 — 语言和视觉使用同一个模型"""

    def __init__(self):
        self._client = None
        self._init()

    def _init(self):
        c = get_llm_config()
        self._client = UnifiedClient(
            api_key=c["api_key"], base_url=c["base_url"], model=c["model"])

    def get_client(self):
        return self._client

    def reload(self):
        self._client = None
        self._init()
        logger.info("LLMRouter reloaded")
