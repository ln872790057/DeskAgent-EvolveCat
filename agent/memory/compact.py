"""AutoCompact — compress conversation history when approaching context limit."""
from utils.token_estimator import estimate_messages_tokens, CONTEXT_WINDOW, COMPACT_THRESHOLD, COMPACT_KEEP_ROUNDS, MAX_COMPACT_FAILURES
from utils.logger import get_logger

logger = get_logger("agent.memory.compact")


class CompactManager:
    """Compresses conversation history when token count exceeds threshold.

    Keeps the last N rounds intact, replaces earlier messages with an LLM-generated
    summary inserted as a system message. Circuit breaker prevents infinite retries.
    """

    def __init__(self):
        self._failures = 0
        self._breached = False  # circuit breaker open

    def should_compact(self, messages: list) -> bool:
        if self._breached:
            return False
        return estimate_messages_tokens(messages) >= CONTEXT_WINDOW * COMPACT_THRESHOLD

    def compact(self, messages: list, llm_client) -> list:
        """Compact messages in-place. Returns the compacted list."""
        if not self.should_compact(messages):
            return messages

        keep_count = COMPACT_KEEP_ROUNDS * 2  # 10 messages (5 rounds)
        if len(messages) <= keep_count:
            return messages

        early = messages[:-keep_count]
        recent = messages[-keep_count:]

        summary = self._llm_compact(early, llm_client)
        if summary is None:
            # LLM failed — use truncation fallback
            logger.warning("[Compact] LLM compact failed, truncating earliest messages")
            self._failures += 1
            if self._failures >= MAX_COMPACT_FAILURES:
                self._breached = True
                logger.error("[Compact] Circuit breaker open — compact disabled")
            return recent

        self._failures = 0  # reset on success

        # Insert summary as system message before recent messages
        compacted = [
            {"role": "system", "content": f"[对话摘要]\n{summary}"}
        ] + recent

        old_tokens = estimate_messages_tokens(messages)
        new_tokens = estimate_messages_tokens(compacted)
        logger.info(
            f"[Compact] compressed: {old_tokens} -> {new_tokens} tokens "
            f"({len(messages)} -> {len(compacted)} messages)"
        )
        return compacted

    def _llm_compact(self, early_messages: list, llm_client) -> str | None:
        """Generate a summary of early messages using LLM. Returns None on failure."""
        text = ""
        for m in early_messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if isinstance(content, str) and content:
                text += f"[{role}]: {content[:300]}\n"

        if not text.strip():
            return None

        prompt = (
            "请用2-3句话总结以下对话的关键信息，保留重要的上下文和用户意图：\n\n" + text[-4000:]
        )
        try:
            result = llm_client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
            )
            return result.get("content", "").strip() or None
        except Exception:
            logger.exception("[Compact] LLM call failed")
            return None
