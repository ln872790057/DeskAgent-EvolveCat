from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list, tools: list = None, stream: bool = False) -> Any:
        pass

    @abstractmethod
    def chat_with_image(self, text: str, image_base64: str) -> str:
        pass
