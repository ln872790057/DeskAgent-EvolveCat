"""File-system memory store — MEMORY.md (8KB cap) + daily logs."""
import os
import sys
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("agent.memory.file_store")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "memory")
MEMORY_MD_PATH = os.path.join(DATA_DIR, "MEMORY.md")
MAX_MEMORY_SIZE = 8 * 1024  # 8KB hard cap


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def read_memory_md() -> str:
    _ensure_dir()
    if not os.path.exists(MEMORY_MD_PATH):
        return ""
    try:
        with open(MEMORY_MD_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def append_to_memory_md(entry: str) -> bool:
    """Append a line to MEMORY.md. If over 8KB, compress first."""
    _ensure_dir()
    existing = read_memory_md()
    new_content = existing + "\n" + entry if existing else entry
    if len(new_content.encode("utf-8")) > MAX_MEMORY_SIZE:
        logger.info("[FileStore] MEMORY.md over 8KB, needs compression before append")
        return False  # caller should compress first
    try:
        with open(MEMORY_MD_PATH, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        logger.error(f"[FileStore] write MEMORY.md failed: {e}")
        return False


def write_memory_md(content: str) -> bool:
    """Overwrite MEMORY.md. If over 8KB, return False (caller should compress)."""
    _ensure_dir()
    if len(content.encode("utf-8")) > MAX_MEMORY_SIZE:
        return False
    try:
        with open(MEMORY_MD_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"[FileStore] write MEMORY.md failed: {e}")
        return False


def compress_memory_md(llm_client, target_size: int = 4096) -> bool:
    """Use LLM to compress MEMORY.md to ~target_size bytes. Returns True on success."""
    existing = read_memory_md()
    if not existing or len(existing.encode("utf-8")) <= target_size:
        return True  # already small enough

    prompt = (
        f"以下是用户的长期记忆摘要（{len(existing.encode('utf-8'))}字节）。"
        f"请压缩到约{target_size}字节，保留最重要的偏好、事实和事件。"
        f"不要丢失关键信息。直接输出压缩后的文本，不要加解释。\n\n{existing}"
    )
    try:
        result = llm_client.chat(
            [{"role": "user", "content": prompt}],
            tools=None, stream=False,
        )
        compressed = result.get("content", "")
        if not compressed:
            return False
        if write_memory_md(compressed):
            logger.info(f"[FileStore] MEMORY.md compressed: {len(existing)} -> {len(compressed)} bytes")
            return True
    except Exception:
        logger.exception("[FileStore] compress_memory_md failed")
    return False


# ── Daily logs ──

def _log_path(date_str: str) -> str:
    return os.path.join(DATA_DIR, f"{date_str}.md")


def write_daily_log(date_str: str, content: str):
    _ensure_dir()
    path = _log_path(date_str)
    timestamp = datetime.now().strftime("%H:%M")
    line = f"[{timestamp}] {content}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.error(f"[FileStore] write daily log failed: {e}")


def read_daily_log(date_str: str) -> str:
    path = _log_path(date_str)
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def list_daily_logs() -> list[str]:
    _ensure_dir()
    logs = []
    for f in os.listdir(DATA_DIR):
        if f.endswith(".md") and f != "MEMORY.md":
            logs.append(f.replace(".md", ""))
    logs.sort()
    return logs


def get_unprocessed_logs(days: int = 3) -> list[str]:
    """Return log dates older than `days` days."""
    all_logs = list_daily_logs()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [d for d in all_logs if d < cutoff]


def distill_old_logs(llm_client, days: int = 30) -> int:
    """Distill logs >days old: extract key info to MEMORY.md, delete originals."""
    old = get_unprocessed_logs(days)
    if not old:
        return 0

    all_text = ""
    for date_str in old:
        text = read_daily_log(date_str)
        if text:
            all_text += f"\n## {date_str}\n{text}"

    if not all_text:
        return 0

    prompt = (
        "以下是用户的日常对话日志。请提取值得长期记住的关键信息"
        "（偏好、重要事件、事实），输出为一行一条的简洁文本。"
        "不要编造内容，没有值得记住的就输出'无'。\n\n" + all_text[:8000]
    )
    try:
        result = llm_client.chat(
            [{"role": "user", "content": prompt}],
            tools=None, stream=False,
        )
        extracted = result.get("content", "").strip()
        if extracted and extracted != "无":
            existing = read_memory_md()
            new_content = existing + "\n\n## 从旧日志提取\n" + extracted if existing else extracted
            if not write_memory_md(new_content):
                compress_memory_md(llm_client, 4096)
                write_memory_md(new_content)

        # Delete old log files
        deleted = 0
        for date_str in old:
            path = _log_path(date_str)
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                pass
        logger.info(f"[FileStore] distilled {deleted} old logs into MEMORY.md")
        return deleted
    except Exception:
        logger.exception("[FileStore] distill_old_logs failed")
        return 0
