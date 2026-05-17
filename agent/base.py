from abc import ABC, abstractmethod
from typing import Callable, Any, Generator


class AgentResponse:
    def __init__(self, reply: str, emotion: str = "idle", tool_calls: list = None):
        self.reply = reply
        self.emotion = emotion
        self.tool_calls = tool_calls or []


class BaseAgent(ABC):
    @abstractmethod
    def chat(self, message: str, context: dict = None) -> AgentResponse:
        pass

    @abstractmethod
    def chat_stream(
        self, message: str, context: dict = None, on_complete: Callable = None,
    ) -> Generator[str, None, None]:
        """Yields text chunks. Calls on_complete(emotion) when done."""
        pass

    @abstractmethod
    def get_system_prompt(self, context: dict = None) -> str:
        pass

    @abstractmethod
    def get_tools(self) -> list:
        pass
