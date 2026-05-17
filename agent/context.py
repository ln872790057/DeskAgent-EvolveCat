from utils.logger import get_logger

logger = get_logger()

MAX_RECENT_ROUNDS = 20


class ContextManager:
    def __init__(self):
        self._history: list[dict] = []
        self._summary: str = ""
        self._perception_context: dict = {
            "screen_summary": "",
            "active_window": "",
            "clipboard_summary": "",
            "usage_duration": "",
        }

    def add_user_message(self, content: str):
        self._history.append({"role": "user", "content": content})
        self._maybe_summarize()

    def add_assistant_message(self, content: str):
        self._history.append({"role": "assistant", "content": content})
        self._maybe_summarize()

    def _maybe_summarize(self):
        if len(self._history) > MAX_RECENT_ROUNDS * 2:
            old = self._history[:-MAX_RECENT_ROUNDS * 2]
            self._history = self._history[-MAX_RECENT_ROUNDS * 2:]
            old_text = "\n".join(
                f"{m['role']}: {m['content'][:200]}" for m in old
            )
            logger.info(f"Triggering summary for {len(old)} old messages")
            self._pending_summary_text = old_text

    def set_summary(self, summary: str):
        self._summary = summary

    def get_summary(self) -> str:
        return self._summary

    def has_pending_summary(self) -> bool:
        return hasattr(self, "_pending_summary_text") and bool(self._pending_summary_text)

    def get_pending_summary_text(self) -> str:
        return getattr(self, "_pending_summary_text", "")

    def clear_pending_summary(self):
        self._pending_summary_text = ""

    def update_perception(self, key: str, value: str):
        if key in self._perception_context:
            self._perception_context[key] = value

    def get_perception_context(self) -> dict:
        return dict(self._perception_context)

    def get_messages_for_llm(self, system_prompt: str) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]

        if self._summary:
            messages.append({
                "role": "system",
                "content": f"[历史对话摘要]\n{self._summary}",
            })

        messages.extend(self._history)
        return messages

    def clear(self):
        self._history.clear()
        self._summary = ""
