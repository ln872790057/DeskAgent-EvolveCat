"""Quick actions — clipboard summarise, translate, search shortcuts."""
from utils.logger import get_logger

logger = get_logger("agent.quick_actions")

# Pattern -> (replacement_template, requires_clipboard)
QUICK_PATTERNS = [
    ("总结剪贴板", "请总结以下剪贴板内容，用简洁的语言概括要点：\n\n{clipboard_text}"),
    ("总结一下", "请总结以下剪贴板内容，用简洁的语言概括要点：\n\n{clipboard_text}"),
    ("翻译剪贴板", "请将以下内容翻译成中文：\n\n{clipboard_text}"),
    ("翻译一下", "请将以下内容翻译成中文：\n\n{clipboard_text}"),
    ("翻译", "请将以下内容翻译成中文：\n\n{clipboard_text}"),
    ("搜索剪贴板", "请搜索以下内容的相关信息并总结：\n\n{clipboard_text}"),
    ("搜一下", "请搜索以下内容的相关信息并总结：\n\n{clipboard_text}"),
]


def check_quick_action(message: str, clipboard_text: str = "") -> str | None:
    """Check if message matches a quick action pattern.

    Returns the expanded message if matched, None otherwise.
    """
    msg = message.strip()
    for pattern, template in QUICK_PATTERNS:
        if msg == pattern or msg.startswith(pattern):
            if "{clipboard_text}" in template and not clipboard_text:
                return None  # need clipboard but it's empty
            expanded = template.format(clipboard_text=clipboard_text)
            logger.info(f"[QuickAction] matched: '{pattern}' -> expanded message")
            return expanded
    return None
