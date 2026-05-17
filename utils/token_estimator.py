"""Token estimation utility — lightweight, no external deps."""
import re

# doubao-seed-2.0: 128K context window
CONTEXT_WINDOW = 128000
COMPACT_THRESHOLD = 0.9  # trigger compact at 90% = 115200 tokens
COMPACT_KEEP_ROUNDS = 5  # keep last 5 rounds (10 msgs) during compact
MAX_COMPACT_FAILURES = 3  # circuit breaker


def estimate_tokens(text: str) -> int:
    """Estimate token count for mixed Chinese/English text.
    Chinese: ~2 tokens per character. English: ~1.3 tokens per word.
    """
    if not text:
        return 0
    # Count CJK characters
    cjk = len(re.findall(r'[一-鿿㐀-䶿豈-﫿]', text))
    # Count English words (remaining text after removing CJK)
    remaining = re.sub(r'[一-鿿㐀-䶿豈-﫿]', ' ', text)
    eng_words = len(remaining.split())
    return int(cjk * 2 + eng_words * 1.3)


def estimate_messages_tokens(messages: list) -> int:
    """Estimate total tokens for a list of chat messages."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # Add overhead for role/tool_call formatting
        if msg.get("role") == "system":
            total += 4
        elif msg.get("role") == "tool":
            total += 8
        else:
            total += 4
        # tool_calls add significant overhead
        tool_calls = msg.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    total += estimate_tokens(tc.get("function", {}).get("arguments", ""))
                    total += estimate_tokens(tc.get("function", {}).get("name", ""))
                    total += 12  # overhead
    return total
