"""MemoryExtractor — LLM-driven memory extraction from conversations."""
import json
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("agent.memory.extractor")


class MemoryExtractor:
    """Extracts memories (preferences, facts, events) from conversations using LLM."""

    def __init__(self, memory_store, file_store):
        self.memory_store = memory_store
        self.file_store = file_store

    def extract_and_store(self, user_msg: str, cat_reply: str, llm_client):
        """Extract memories from a conversation turn and store them."""
        items = self._extract_from_conversation(user_msg, cat_reply, llm_client)
        if items:
            self._store_extracted(items)
        # Also write daily log summary
        summary = self._extract_summary(user_msg, cat_reply, llm_client)
        if summary:
            today = datetime.now().strftime("%Y-%m-%d")
            self.file_store.write_daily_log(today, summary)

    def _extract_from_conversation(self, user_msg: str, cat_reply: str, llm_client) -> list[dict]:
        """Call LLM to extract structured memories from a conversation turn."""
        prompt = (
            "从以下对话中提取值得长期记住的信息，返回JSON数组。\n"
            "只提取用户偏好、重要事实、关键事件。日常闲聊不提取。\n"
            "tags用逗号分隔的关键词。\n"
            '格式：[{"type": "preference|event|fact", "content": "内容", '
            '"importance": 0.0-1.0, "tags": "标签"}]\n'
            "没有值得记住的返回空数组 []。\n\n"
            f"用户：{user_msg}\ndeskagent：{cat_reply}"
        )
        try:
            result = llm_client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
            )
            text = result.get("content", "[]") if isinstance(result, dict) else "[]"
            if isinstance(text, str) and text.strip().startswith("["):
                return json.loads(text)
        except json.JSONDecodeError:
            logger.debug("[Extractor] JSON parse failed for memory extraction")
        except Exception:
            logger.debug("[Extractor] memory extraction failed (non-critical)", exc_info=True)
        return []

    def _extract_summary(self, user_msg: str, cat_reply: str, llm_client) -> str:
        """Generate a one-line summary of the conversation for daily log."""
        prompt = (
            "用一句话（15字以内）总结以下对话的内容。直接输出总结，不要加任何前缀或解释。\n\n"
            f"用户：{user_msg[:200]}\ndeskagent：{cat_reply[:200]}"
        )
        try:
            result = llm_client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
            )
            text = result.get("content", "") if isinstance(result, dict) else ""
            return text.strip()[:80]
        except Exception:
            return ""

    def _store_extracted(self, items: list[dict]):
        """Store extracted items in SQLite and MEMORY.md."""
        for item in items:
            memory_type = item.get("type", "fact")
            content = item.get("content", "")
            importance = item.get("importance", 0.5)
            tags = item.get("tags", "")

            try:
                self.memory_store.store(memory_type, content, importance, tags)
                logger.debug(f"[Extractor] stored: type={memory_type} imp={importance} tags={tags}")
            except Exception:
                logger.debug("[Extractor] store failed", exc_info=True)
                continue

            # High-importance → also write to MEMORY.md
            if importance > 0.6:
                line = f"- [{memory_type}] {content} (重要性:{importance:.1f})"
                ok = self.file_store.append_to_memory_md(line)
                if not ok:
                    logger.info("[Extractor] MEMORY.md full, skipping append")
