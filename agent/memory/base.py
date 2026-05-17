from abc import ABC, abstractmethod
from typing import Optional


class MemoryItem:
    def __init__(self, id: int, memory_type: str, content: str, importance: float,
                 created_at: str, last_accessed: str, access_count: int,
                 tags: Optional[str] = None):
        self.id = id
        self.type = memory_type
        self.content = content
        self.importance = importance
        self.created_at = created_at
        self.last_accessed = last_accessed
        self.access_count = access_count
        self.tags = tags or ""


class BaseMemoryStore(ABC):
    @abstractmethod
    def store(self, memory_type: str, content: str, importance: float,
              tags: str = "") -> int:
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        pass

    @abstractmethod
    def delete(self, memory_id: int) -> bool:
        pass

    @abstractmethod
    def cleanup(self, max_items: int = 200) -> int:
        pass

    @abstractmethod
    def get_recent(self, limit: int = 10) -> list[MemoryItem]:
        pass

    @abstractmethod
    def update_access(self, memory_id: int):
        pass
