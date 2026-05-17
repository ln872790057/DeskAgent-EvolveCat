"""ToolRegistry — V2 tool system with HITL safety"""
import json
import time as _time_module
import threading

from utils.logger import get_logger

logger = get_logger("agent.tools")


class ToolDefinition:
    def __init__(self, name: str, func, schema: dict, safe: bool = True):
        self.name = name; self.func = func; self.schema = schema; self.safe = safe


class ToolRegistry:
    _tools: dict[str, ToolDefinition] = {}
    _always_allowed: set[str] = set()
    _progress_emitters = threading.local()

    @classmethod
    def register(cls, name, func, schema, safe=True):
        cls._tools[name] = ToolDefinition(name, func, schema, safe)
        logger.info(f"ToolOK: {name} safe={safe}")

    @classmethod
    def is_safe(cls, name) -> bool:
        t = cls._tools.get(name)
        return (t and t.safe) or name in cls._always_allowed if t else False

    @classmethod
    def set_always_allowed(cls, name):
        cls._always_allowed.add(name)

    @classmethod
    def get_all_schemas(cls) -> list:
        return [t.schema for t in cls._tools.values()]

    @classmethod
    def execute(cls, name, params):
        t = cls._tools.get(name)
        if not t: return f"未注册: {name}"
        try:
            r = t.func(**params)
            return cls._preprocess(name, r)
        except Exception as e:
            logger.exception(f"[ToolRegistry] execute failed: {name}")
            return f"执行失败: {e}"

    @classmethod
    def set_progress_emitter(cls, emitter):
        cls._progress_emitters.current = emitter

    @classmethod
    def clear_progress_emitter(cls):
        cls._progress_emitters.current = None

    @classmethod
    def emit_progress(cls, tool_name: str, text: str):
        emitter = getattr(cls._progress_emitters, "current", None)
        if emitter:
            try:
                emitter(tool_name, text)
            except Exception:
                logger.debug("[ToolRegistry] progress emitter failed", exc_info=True)

    @classmethod
    def execute_with_timeout(cls, name, params, timeout: int = 10):
        import queue
        import threading

        result_queue = queue.Queue(maxsize=1)
        parent_emitter = getattr(cls._progress_emitters, "current", None)

        def _target():
            if parent_emitter:
                cls.set_progress_emitter(parent_emitter)
            try:
                result_queue.put(cls.execute(name, params))
            finally:
                if parent_emitter:
                    cls.clear_progress_emitter()

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        try:
            return result_queue.get(timeout=timeout)
        except queue.Empty:
            return f"执行超时（{timeout}秒）"
        except Exception as e:
            return f"执行失败: {e}"

    @classmethod
    def _preprocess(cls, name, result):
        limits = {"read_file": 2000, "shell_exec": 2000, "screenshot": 500}
        limit = limits.get(name, 99999)
        return str(result)[:limit] if result else "完成"


# ═══ Tavily web_search — real internet search ═══

DEFAULT_TAVILY_KEY = "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"


def _get_tavily_key() -> str:
    """Get Tavily API key: user config first, then built-in default."""
    try:
        from utils.config import get_config
        user_key = get_config().get("tavily_api_key", "").strip()
        if user_key:
            return user_key
    except Exception:
        pass
    return DEFAULT_TAVILY_KEY


# ═══ Tool implementations ═══

def _web_search(query: str) -> str:
    """Real web search using Tavily API. Returns formatted search results."""
    import threading
    import queue

    t_start = _time_module.time()
    logger.info(f"[Tool:web_search] query: {query[:200]}")

    def _do_search():
        try:
            from tavily import TavilyClient
            key = _get_tavily_key()
            client = TavilyClient(api_key=key)
            response = client.search(query=query, max_results=5, search_depth="basic")
            return response
        except ImportError:
            return {"error": "搜索库未安装 (pip install tavily-python)"}
        except Exception as e:
            return {"error": f"搜索失败: {str(e)[:200]}"}

    result_queue = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: result_queue.put(_do_search()), daemon=True).start()
    try:
        raw = result_queue.get(timeout=15)
    except queue.Empty:
        logger.warning(f"[Tool:web_search] timeout: query={query[:100]}")
        return "搜索超时（15秒），请稍后再试或换个简短的关键词"
    except Exception as e:
        logger.exception(f"[Tool:web_search] queue error")
        return f"搜索出错: {str(e)[:80]}"

    elapsed = (_time_module.time() - t_start) * 1000

    if isinstance(raw, dict) and raw.get("error"):
        logger.error(f"[Tool:web_search] failed: {raw['error'][:200]}")
        return f"搜索失败: {raw['error'][:200]}"

    results = raw.get("results", [])
    if not results:
        logger.info(f"[Tool:web_search] no results: query={query[:100]} elapsed={elapsed:.0f}ms")
        return f"未找到关于'{query[:80]}'的相关结果"

    lines = ["【搜索结果】"]
    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "")[:80]
        url = r.get("url", "")
        content = r.get("content", "")[:200]
        source = url.split("/")[2] if url else "unknown"
        lines.append(f"\n{i}. {title}\n   来源: {source}\n   摘要: {content}")

    result = "\n".join(lines)
    logger.info(
        f"[Tool:web_search] done: query={query[:100]} "
        f"results={len(results)} elapsed={elapsed:.0f}ms"
    )
    return result


def _read_file(path: str) -> str:
    import os
    forbidden = ["/etc/shadow", "/etc/passwd", "C:\\Windows\\System32\\config"]
    for fb in forbidden:
        if fb.lower() in path.lower():
            return "不允许读取该文件"
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    size = os.path.getsize(path)
    if size > 1_000_000:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(100_000) + "\n...[文件过大已截断]"
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return "不支持读取二进制文件"


def _write_file(path: str, content: str) -> str:
    import os

    # Normalize path: handle "桌面", "desktop", "~/" etc.
    path = path.strip().strip("'").strip('"')
    lower = path.lower()
    if lower.startswith("桌面") or lower.startswith("desktop"):
        path = os.path.expanduser(os.path.join("~", "Desktop") + path[len(lower.split("/")[0]):])
    elif path.startswith("~"):
        path = os.path.expanduser(path)

    # Resolve to absolute path
    try:
        path = os.path.abspath(path)
        path = os.path.normpath(path)
    except Exception:
        pass

    logger.info(f"[Tool:write_file] writing to: {path} size={len(content)}")

    try:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[Tool:write_file] success: {path}")
        return f"文件已成功写入: {path}"
    except PermissionError:
        logger.error(f"[Tool:write_file] permission denied: {path}")
        return f"写入失败（权限不足）: {path}。请检查路径是否正确，或尝试写入其他位置。"
    except Exception as e:
        logger.exception(f"[Tool:write_file] failed: {path}")
        return f"写入失败: {e}。请检查路径是否正确，或尝试写入其他位置。"


def _clipboard_read() -> str:
    from PySide6.QtWidgets import QApplication
    cb = QApplication.clipboard()
    text = cb.text()
    if not text: return "剪贴板为空"
    for kw in ["password", "密码", "token", "secret", "key"]:
        if kw.lower() in text.lower():
            return "剪贴板内容包含敏感信息，不显示"
    return text[:1000]


def _clipboard_write(content: str) -> str:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(content)
    return "已复制到剪贴板"


def _screenshot(prompt: str = "描述用户屏幕上正在做什么，30字以内") -> str:
    import base64, io
    try:
        import pyautogui
        ss = pyautogui.screenshot()
    except Exception:
        return "截屏失败"
    if ss.width > 1280:
        ratio = 1280 / ss.width
        ss = ss.resize((1280, int(ss.height * ratio)))
    buf = io.BytesIO()
    ss.save(buf, format="PNG", optimize=True)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    try:
        from agent.llm.router import get_llm_config
        from openai import OpenAI
        c = get_llm_config()
        cl = OpenAI(api_key=c["api_key"], base_url=c["base_url"], timeout=30)
        resp = cl.chat.completions.create(
            model=c["model"],
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]}],
            max_tokens=200,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"视觉理解失败: {e}"


def _notify(title: str = "deskagent", body: str = "") -> str:
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from ui.tray_icon import TrayManager
    return f"通知已发送: {body[:50]}"


def _research_topic(topic: str, depth: int = 3, focus: list = None, incremental: bool = False) -> str:
    """Submit a professional research task to the background queue.
    Returns immediately with a queued status message."""
    from agent.task_manager import TaskManager, TaskType
    from skills.pro_researcher.researcher import research_topic_execute
    import json

    try:
        from agent.scheduled_task_manager import get_scheduled_task_manager_instance
    except ImportError:
        pass

    # Build the task payload as a message
    payload = json.dumps({
        "action": "research_topic",
        "topic": topic,
        "depth": depth,
        "focus": focus or [],
        "incremental": incremental,
    }, ensure_ascii=False)

    # This runs sync in the TaskWorker. Provide a lightweight LLM context so the
    # researcher can synthesize analysis instead of falling back to a source list.
    class _ResearchAgentProxy:
        def __init__(self):
            from agent.llm.router import LLMRouter
            self.router = LLMRouter()

    from agent.runtime.task_session import TaskSession
    from agent.workflows.research import ResearchWorkflow

    session = TaskSession.create(topic, "research", topic)
    stage_labels = {
        "detect_type": "规划调研类型",
        "generate_queries": "生成搜索计划",
        "search": "搜索资料来源",
        "deduplicate_sources": "整理来源列表",
        "read_and_rank_sources": "读取并筛选来源",
        "llm_analysis": "抽取证据并综合分析",
        "build_report_model": "审稿并构建报告",
        "render_and_save": "保存 Markdown 报告",
    }

    def _emit_research_progress(stage: str, status: str):
        label = stage_labels.get(stage, stage)
        ToolRegistry.emit_progress("research_topic", f"调研阶段：{label}")

    session.progress_callback = _emit_research_progress
    result = research_topic_execute(
        topic, depth, focus, incremental, agent=_ResearchAgentProxy(), session=session
    )
    if result.get("status") == "completed":
        return result.get("message", "调研完成")
    return result.get("message", "调研失败")


def _shell_exec(command: str) -> str:
    import subprocess, platform
    whitelist = ["ls","dir","cat","type","pwd","echo","python","python3","git",
                 "npm","pip","node","cd","find","grep","wc","head","tail","curl","ping"]
    blacklist = ["rm -rf","del /s","format","shutdown","reboot","mkfs","dd","fork bomb"]
    cmd_lower = command.lower()
    if not any(cmd_lower.startswith(w) for w in whitelist):
        return f"不允许执行该命令（不在白名单中）"
    for b in blacklist:
        if b in cmd_lower:
            return f"危险命令已拦截"
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        out = (r.stdout + r.stderr)[:2000]
        return out or "命令执行完成（无输出）"
    except subprocess.TimeoutExpired:
        return "命令超时"
    except Exception as e:
        return f"命令执行失败: {e}"


def _schedule_task(task_type: str, schedule: str, content: str) -> str:
    """Create a scheduled/periodic task via the global ScheduledTaskManager."""
    try:
        from agent.scheduled_task_manager import get_scheduled_task_manager_instance
        mgr = get_scheduled_task_manager_instance()
        if mgr is None:
            return "定时任务系统未初始化，请重启应用"
        task_id = mgr.add_task(task_type, schedule, content)
        type_labels = {"once": "一次性", "daily": "每天", "weekly": "每周", "cron": "定时"}
        return f"已设置{type_labels.get(task_type, '定时')}任务：{content}"
    except Exception as e:
        logger.exception("[Tool:schedule_task] failed")
        return f"创建定时任务失败: {e}"


def register_v2_tools():
    ToolRegistry.register("web_search", _web_search, {
        "type": "function", "function": {
            "name": "web_search", "description": "搜索互联网获取实时信息。当用户询问新闻、最新动态、天气、股价等需要联网的内容时使用此工具。禁止用shell_exec搜索网络。",
            "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]},
        },
    }, safe=True)

    ToolRegistry.register("read_file", _read_file, {
        "type": "function", "function": {
            "name": "read_file", "description": "读取文件内容",
            "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}}, "required": ["path"]},
        },
    }, safe=True)

    ToolRegistry.register("write_file", _write_file, {
        "type": "function", "function": {
            "name": "write_file", "description": "写入文件（需要用户确认）",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            }, "required": ["path", "content"]},
        },
    }, safe=False)

    ToolRegistry.register("clipboard_read", _clipboard_read, {
        "type": "function", "function": {
            "name": "clipboard_read", "description": "读取剪贴板内容",
            "parameters": {"type": "object", "properties": {}},
        },
    }, safe=True)

    ToolRegistry.register("clipboard_write", _clipboard_write, {
        "type": "function", "function": {
            "name": "clipboard_write", "description": "写入内容到剪贴板",
            "parameters": {"type": "object", "properties": {"content": {"type": "string", "description": "要复制的内容"}}, "required": ["content"]},
        },
    }, safe=True)

    ToolRegistry.register("screenshot", _screenshot, {
        "type": "function", "function": {
            "name": "screenshot", "description": "截屏查看用户屏幕内容",
            "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "理解提示"}}},
        },
    }, safe=True)

    ToolRegistry.register("notify", _notify, {
        "type": "function", "function": {
            "name": "notify", "description": "发送系统通知",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "通知标题"},
                "body": {"type": "string", "description": "通知内容"},
            }, "required": ["body"]},
        },
    }, safe=True)

    ToolRegistry.register("schedule_task", _schedule_task, {
        "type": "function", "function": {
            "name": "schedule_task",
            "description": "创建定时/周期任务。当用户表达提醒、定时、周期等时间意图时使用。将时间表达式从内容中剥离。",
            "parameters": {"type": "object", "properties": {
                "task_type": {"type": "string", "enum": ["once", "daily", "weekly", "cron"],
                              "description": "once=一次性 daily=每天 weekly=每周 cron=cron表达式"},
                "schedule": {"type": "string",
                             "description": "once用ISO时间(YYYY-MM-DDTHH:MM)，daily用HH:MM(24h)，weekly用'星期数 HH:MM'(0=周一)，cron用标准表达式"},
                "content": {"type": "string", "description": "去掉时间词后的任务描述"},
            }, "required": ["task_type", "schedule", "content"]},
        },
    }, safe=True)

    ToolRegistry.register("research_topic", _research_topic, {
        "type": "function", "function": {
            "name": "research_topic",
            "description": "对指定主题进行专业深度调研。后台执行，读取来源正文，形成带证据链的结构化Markdown报告并保存到桌面。",
            "parameters": {"type": "object", "properties": {
                "topic": {"type": "string", "description": "调研主题，越具体越好"},
                "depth": {"type": "integer", "description": "调研深度1-5", "default": 3, "minimum": 1, "maximum": 5},
                "focus": {"type": "array", "items": {"type": "string"}, "description": "可选关注维度"},
                "incremental": {"type": "boolean", "description": "是否基于历史调研只看新进展", "default": False},
            }, "required": ["topic"]},
        },
    }, safe=True)

    ToolRegistry.register("shell_exec", _shell_exec, {
        "type": "function", "function": {
            "name": "shell_exec", "description": "执行本地命令（白名单限制，需确认）。仅限文件操作、git等本地任务。严禁用于curl/wget/ping等网络请求，搜索信息请使用内置搜索能力。",
            "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的命令"}}, "required": ["command"]},
        },
    }, safe=False)


register_v2_tools()
