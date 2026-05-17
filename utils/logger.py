"""日志系统 — 控制台 + 按日滚动文件，支持模块级 logger"""
import logging
import logging.handlers
import os
import sys
import io
from pathlib import Path


class _SafeStdout(io.TextIOBase):
    """stdout wrapper that replaces unencodable characters (emoji on GBK terminal)."""

    def __init__(self):
        self._stream = sys.stdout

    def write(self, s: str) -> int:
        try:
            return self._stream.write(s)
        except UnicodeEncodeError:
            # Replace emoji and other non-GBK chars with '?'
            safe = s.encode(self._stream.encoding or "utf-8", errors="replace").decode(
                self._stream.encoding or "utf-8", errors="replace"
            )
            return self._stream.write(safe)

    def flush(self):
        self._stream.flush()

    def close(self):
        pass  # Don't close real stdout

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

_loggers: dict[str, logging.Logger] = {}
_initialized = False
LOG_DIR: str = ""


def _ensure_log_dir() -> str:
    """确定日志目录：优先项目根下的 logs/，其次 data/"""
    global LOG_DIR
    if LOG_DIR:
        return LOG_DIR

    # 尝试 agcat/logs/
    candidates = []
    try:
        # 从 utils/logger.py 向上找到项目根
        root = Path(__file__).resolve().parent.parent
        candidates.append(str(root / "logs"))
        candidates.append(str(root / "data"))
    except Exception:
        pass
    # 当前工作目录
    candidates.append(os.path.join(os.getcwd(), "logs"))
    candidates.append(os.path.join(os.getcwd(), "data"))

    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            LOG_DIR = d
            return d
        except OSError:
            continue
    # 最后兜底
    LOG_DIR = os.path.join(os.getcwd(), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    return LOG_DIR


def _init_root_logger():
    """初始化根 logger：TimedRotatingFileHandler(DEBUG) + StreamHandler(INFO)"""
    global _initialized
    if _initialized:
        return

    log_dir = _ensure_log_dir()
    root = logging.getLogger("agcat")
    root.setLevel(logging.DEBUG)

    # 格式: [时间][级别][模块名] 消息
    fmt = logging.Formatter(
        "[%(asctime)s][%(levelname)-5s][%(name)s] %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    # 按日滚动文件 — DEBUG 级别
    daily_path = os.path.join(log_dir, "agcat.log")
    try:
        file_handler = logging.handlers.TimedRotatingFileHandler(
            daily_path,
            when="midnight",
            interval=1,
            backupCount=14,  # 保留 14 天
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        # 避免 extra 字段导致旧日志格式不兼容
        file_handler.addFilter(_drop_extra_filter)
        root.addHandler(file_handler)
    except Exception:
        # 回退到普通文件
        try:
            fallback = logging.FileHandler(
                os.path.join(log_dir, "agcat_fallback.log"),
                encoding="utf-8",
            )
            fallback.setLevel(logging.DEBUG)
            fallback.setFormatter(fmt)
            root.addHandler(fallback)
        except Exception:
            pass

    # 控制台 — INFO 级别，容错 Unicode（Windows GBK 终端无法输出 emoji）
    console = logging.StreamHandler(_SafeStdout())
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 抑制第三方库的 DEBUG 日志
    for lib in ("openai", "httpx", "httpcore", "urllib3", "PIL"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    _initialized = True


def _drop_extra_filter(record: logging.LogRecord) -> bool:
    """移除 extra 字段避免格式化报错"""
    for key in list(record.__dict__.keys()):
        if key not in {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module", "msecs",
            "message", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
        }:
            try:
                delattr(record, key)
            except Exception:
                pass
    return True


def get_logger(name: str = "agcat") -> logging.Logger:
    """获取模块级 logger。推荐用法：logger = get_logger(__name__)"""
    _init_root_logger()

    if name in _loggers:
        return _loggers[name]

    # 使用层级命名：agcat.agent.pet_agent
    full_name = f"agcat.{name}" if not name.startswith("agcat.") else name
    logger = logging.getLogger(full_name)
    _loggers[name] = logger
    return logger


# ── 启动时立即初始化 ──
_init_root_logger()
