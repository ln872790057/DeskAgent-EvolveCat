"""TaskWorker - QThread ReAct executor with bounded tool and LLM calls."""
import json
import queue
import threading
import time as _time_module

from PySide6.QtCore import QThread, Signal

from agent.task_manager import Task, TaskStatus, TaskType
from agent.router.intent_router import classify_message as _route_message_kind
from agent.tools import ToolRegistry
from utils.logger import get_logger

logger = get_logger("agent.task_worker")

MAX_LOOPS = 10
TOOL_TIMEOUT = 10
TOOL_TIMEOUTS = {"research_topic": 1800, "screenshot": 30}  # per-tool overrides
LLM_TIMEOUT = 30
HITL_TIMEOUT = 60

# Shell command risk grading
DANGEROUS_PATTERNS = [
    # Deletion
    "rm ", "rmdir", "del ", "deltree", "format ",
    # Network requests
    "curl ", "wget ", "ping ", "traceroute", "nslookup", "nc ",
    # Privilege/permission changes
    "sudo ", "chmod ", "chown ", "su ", "runas",
    # System modification
    "shutdown", "reboot", "mkfs", "dd ", "sc ", "reg ",
    # Redirection that overwrites
    "> /", "> C:", "> ~/",
]
SAFE_PATTERNS = [
    "touch ", "mkdir", "ls", "dir", "pwd", "echo", "cat ",
    "type ", "cd ", "cp ", "mv ", "git ", "python ", "pip ",
    "find ", "grep ", "wc ", "head ", "tail ",
]


def is_dangerous_command(command: str) -> bool:
    """Check if a shell command is high-risk and needs HITL confirmation."""
    cmd_lower = command.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return True
    # Writing to system directories is dangerous
    for sys_dir in ["/etc", "/usr", "/bin", "/sbin", "/boot", "c:\\windows", "c:\\program files"]:
        if sys_dir in cmd_lower:
            return True
    # Overwrite redirect to any path is dangerous
    if "> " in command and ">>" not in command:
        return True
    return False

TASK_SIGNALS = [
    "帮我", "搜索", "搜", "查", "找", "总结", "写", "翻译", "分析", "调研", "提醒",
    "读", "看", "检查", "监控", "整理", "对比", "生成", "列出", "制作", "安排",
    "计划", "提取", "转换", "计算", "截图", "截屏", "通知", "执行", "运行", "安装", "下载",
]
CHAT_SIGNALS = [
    "你好", "谢谢", "你真", "哈哈", "为什么", "是不是", "好看吗", "喜欢", "讨厌",
    "哼", "嗯", "哦", "嘿嘿", "哇", "算了", "无聊", "辛苦了", "晚安", "早安",
]

TOOL_ICONS = {
    "web_search": "🔍", "read_file": "📄", "write_file": "✏️",
    "clipboard_read": "📋", "clipboard_write": "📋",
    "screenshot": "📸", "notify": "🔔", "shell_exec": "⚡",
    "schedule_task": "⏰", "research_topic": "📊",
}
TOOL_LABELS = {
    "web_search": "正在搜索...", "read_file": "正在读取文件...",
    "write_file": "正在写入文件...", "clipboard_read": "正在读取剪贴板...",
    "clipboard_write": "正在写入剪贴板...", "screenshot": "正在看你的屏幕...",
    "notify": "正在发送通知...", "shell_exec": "正在执行命令...",
    "schedule_task": "正在设置定时任务...", "research_topic": "正在深度调研...",
}
TOOL_DONE = {
    "web_search": "搜索完成", "read_file": "文件读取完成",
    "write_file": "文件写入完成", "clipboard_read": "剪贴板读取完成",
    "clipboard_write": "剪贴板写入完成", "screenshot": "截屏分析完成",
    "notify": "通知已发送", "shell_exec": "命令执行完成",
    "schedule_task": "定时任务已设置", "research_topic": "调研报告已生成",
}

def classify_message(text: str) -> str:
    """Return TASK or CHAT."""
    return _route_message_kind(text)
    text = text.strip()
    if text.startswith("！"):
        return "CHAT"
    has_task = any(kw in text for kw in TASK_SIGNALS)
    has_chat = any(kw in text for kw in CHAT_SIGNALS)
    if has_task and has_chat:
        return "TASK"
    if has_task:
        return "TASK"
    if has_chat:
        return "CHAT"
    return "TASK" if len(text) > 20 else "CHAT"


def _future_result(func, timeout: int, *args, **kwargs):
    result_queue = queue.Queue(maxsize=1)

    def _target():
        try:
            result_queue.put((func(*args, **kwargs), None))
        except Exception:
            logger.exception(f"[future_result] exception in threaded call: {func.__name__ if hasattr(func, '__name__') else 'unknown'}")
            result_queue.put((None, "内部错误，请查看日志"))

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        logger.warning(f"[future_result] timeout after {timeout}s")
        return None, f"执行超时（{timeout}秒）"


def _tool_summary(tool_name: str, result: str, error: str = "") -> str:
    icon = TOOL_ICONS.get(tool_name, "🔧")
    if error:
        return f"{icon} {error[:160]}"
    text = (result or "完成").strip().replace("\r", " ").replace("\n", " ")
    label = TOOL_DONE.get(tool_name, f"{tool_name} 完成")
    return f"{icon} {label}: {text[:180]}"


def _assistant_message_from_response(resp: dict, tool_calls: list) -> dict:
    raw = resp.get("assistant_message")
    if isinstance(raw, dict):
        raw = dict(raw)
        raw["role"] = "assistant"
        return raw
    return {
        "role": "assistant",
        "content": resp.get("content") or "",
        "tool_calls": [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls
        ],
    }


def _build_tools_for_message(message: str) -> list[dict]:
    """Build tool list: all registered tools.
    Doubao native search is handled at the LLM client level via extra_body.
    """
    return list(ToolRegistry.get_all_schemas())


class TaskWorker(QThread):
    task_done = Signal(str, str, str)
    tool_status = Signal(str, str, str)
    tool_result = Signal(str, str, str)
    stream_chunk = Signal(str, str)
    stream_done = Signal(str, str)
    hitl_needed = Signal(str, str, dict)

    def __init__(self, task: Task, agent, parent=None):
        super().__init__(parent)
        self._task = task
        self._agent = agent
        self._loop_count = 0
        self._hitl_lock = threading.Lock()
        self._hitl_waits: dict[str, tuple[threading.Event, dict]] = {}

    def request_cancel(self):
        self._task.cancel_requested = True

    def resolve_hitl(self, tool_name: str, approved: bool):
        with self._hitl_lock:
            payload = self._hitl_waits.get(tool_name)
            if not payload:
                return
            event, state = payload
            state["approved"] = bool(approved)
            event.set()

    def run(self):
        tid = self._task.task_id
        t_start = _time_module.time()
        task_type = self._task.task_type.value
        user_text = self._task.messages[-1].get("content", "") if self._task.messages else ""

        logger.info(
            f"[Worker] start: tid={tid} type={task_type} "
            f"text={user_text[:200]}"
        )
        try:
            system = self._agent.get_system_prompt()
            history = self._agent.context.get_messages_for_llm(system)
            messages = history + self._task.messages
            client = self._agent.router.get_client()
            tools = _build_tools_for_message(user_text)
            logger.info(
                f"[Worker] init: tid={tid} history_msgs={len(history)} "
                f"total_msgs={len(messages)} "
                f"tools=[{','.join(t.get('function',{}).get('name','?') for t in tools)}]"
            )

            while self._loop_count < MAX_LOOPS:
                if self._task.cancel_requested:
                    logger.info(f"[Worker] cancelled: tid={tid} round={self._loop_count}")
                    self._task.status = TaskStatus.CANCELLED
                    self.task_done.emit(tid, "", "cancelled")
                    return

                logger.debug(
                    f"[Worker] llm_request: tid={tid} round={self._loop_count} "
                    f"msg_count={len(messages)} tool_count={len(tools)}"
                )
                resp, err = _future_result(client.chat, LLM_TIMEOUT, messages, tools=tools, stream=False)
                if err:
                    logger.error(f"[Worker] llm_call_failed: tid={tid} round={self._loop_count} error={err[:200]}")
                    # Try to compose fallback from tool results before failing
                    fallback = self._build_tool_fallback()
                    if fallback:
                        self.stream_done.emit(tid, fallback)
                        self.task_done.emit(tid, fallback, "")
                    else:
                        self.task_done.emit(tid, "", err)
                    return

                resp_type = resp.get("type")
                logger.info(
                    f"[Worker] llm_response: tid={tid} round={self._loop_count} "
                    f"type={resp_type} content_len={len(resp.get('content') or '')} "
                    f"tool_calls_count={len(resp.get('tool_calls') or [])}"
                )

                if resp.get("type") == "tool_calls":
                    tool_calls = resp.get("tool_calls", [])
                    logger.info(
                        f"[Worker] tool_calls: tid={tid} round={self._loop_count} "
                        f"count={len(tool_calls)} -> {[tc['function']['name'] for tc in tool_calls]}"
                    )
                    messages.append(_assistant_message_from_response(resp, tool_calls))

                    for tc in tool_calls:
                        fname = tc["function"]["name"]
                        try:
                            fargs = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            fargs = {}
                            logger.warning(f"[Worker] bad_tool_args: tid={tid} tool={fname}")

                        logger.info(
                            f"[Worker] tool_exec: tid={tid} tool={fname} "
                            f"args={json.dumps(fargs, ensure_ascii=False)[:200]}"
                        )
                        t_tool = _time_module.time()

                        if not ToolRegistry.is_safe(fname):
                            # For shell_exec, only require HITL for dangerous commands
                            if fname == "shell_exec":
                                cmd = fargs.get("command", "")
                                if not is_dangerous_command(cmd):
                                    logger.info(f"[Worker] shell_exec auto-approved (safe): tid={tid} cmd={cmd[:100]}")
                                    # Skip HITL, execute directly
                                    self.tool_status.emit(tid, fname, f"自动执行: {cmd[:40]}...")
                                    t_timeout = TOOL_TIMEOUTS.get(fname, TOOL_TIMEOUT)
                                    ToolRegistry.set_progress_emitter(
                                        lambda tool, text, tid=tid: self.tool_status.emit(tid, tool, text)
                                    )
                                    try:
                                        result = ToolRegistry.execute_with_timeout(fname, fargs, timeout=t_timeout)
                                    finally:
                                        ToolRegistry.clear_progress_emitter()
                                    tool_elapsed = (_time_module.time() - t_tool) * 1000
                                    summary = _tool_summary(fname, str(result))
                                    logger.info(
                                        f"[Worker] tool_result: tid={tid} tool={fname} "
                                        f"elapsed={tool_elapsed:.0f}ms result={str(result)[:240]}"
                                    )
                                    self.tool_result.emit(tid, fname, summary)
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc.get("id", ""),
                                        "content": str(result),
                                    })
                                    logger.debug(f"[Worker] tool_msg_appended: tid={tid} tool={fname} total_msgs={len(messages)}")
                                    self._task.tool_calls_log.append({
                                        "tool": fname, "args": fargs, "result": str(result)[:200],
                                    })
                                    continue

                            logger.info(f"[Worker] hitl_required: tid={tid} tool={fname}")
                            self.tool_status.emit(tid, fname, f"等待确认: {fname}")
                            self.hitl_needed.emit(tid, fname, fargs)
                            approved = self._wait_for_hitl(fname)
                            if not approved:
                                result = "用户未确认或确认超时，已跳过执行"
                                self.tool_result.emit(tid, fname, _tool_summary(fname, result))
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id", ""),
                                    "content": result,
                                })
                                logger.info(f"[Worker] tool_skipped: tid={tid} tool={fname} (hitl denied/timeout)")
                                continue

                        self.tool_status.emit(tid, fname, TOOL_LABELS.get(fname, f"正在执行 {fname}..."))
                        t_timeout = TOOL_TIMEOUTS.get(fname, TOOL_TIMEOUT)
                        ToolRegistry.set_progress_emitter(
                            lambda tool, text, tid=tid: self.tool_status.emit(tid, tool, text)
                        )
                        try:
                            result = ToolRegistry.execute_with_timeout(fname, fargs, timeout=t_timeout)
                        finally:
                            ToolRegistry.clear_progress_emitter()
                        tool_elapsed = (_time_module.time() - t_tool) * 1000
                        summary = _tool_summary(fname, str(result))
                        result_preview = str(result)[:240]
                        logger.info(
                            f"[Worker] tool_result: tid={tid} tool={fname} "
                            f"elapsed={tool_elapsed:.0f}ms result={result_preview}"
                        )
                        self.tool_result.emit(tid, fname, summary)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": str(result),
                        })
                        logger.debug(f"[Worker] tool_msg_appended: tid={tid} tool={fname} total_msgs={len(messages)}")
                        self._task.tool_calls_log.append({
                            "tool": fname,
                            "args": fargs,
                            "result": str(result)[:200],
                        })

                    self._loop_count += 1
                    logger.info(f"[Worker] continue_after_tools: tid={tid} next_round={self._loop_count} total_msgs={len(messages)}")
                    continue

                # ── Text reply ──
                full_reply = resp.get("content", "喵？")
                total_elapsed = (_time_module.time() - t_start) * 1000
                logger.info(
                    f"[Worker] final_reply: tid={tid} reply_len={len(full_reply)} "
                    f"type={task_type} rounds={self._loop_count} elapsed={total_elapsed:.0f}ms"
                )
                if self._task.task_type == TaskType.CHAT:
                    for ch in full_reply:
                        if self._task.cancel_requested:
                            self.task_done.emit(tid, "", "cancelled")
                            return
                        self.stream_chunk.emit(tid, ch)
                        self.msleep(12)
                self.stream_done.emit(tid, full_reply)
                self._agent.context.add_assistant_message(full_reply)
                self.task_done.emit(tid, full_reply, "")
                logger.info(f"[Worker] done: tid={tid} elapsed={total_elapsed:.0f}ms")
                return

            # ── Max rounds exceeded ──
            total_elapsed = (_time_module.time() - t_start) * 1000
            logger.warning(
                f"[Worker] max_rounds: tid={tid} rounds={self._loop_count} "
                f"elapsed={total_elapsed:.0f}ms"
            )
            fallback = self._build_tool_fallback()
            msg = fallback or "我想太久了，先告诉你目前的结果..."
            logger.info(f"[Worker] max_rounds_fallback: tid={tid} msg={msg[:120]}")
            self.stream_done.emit(tid, msg)
            self.task_done.emit(tid, msg, "")
        except Exception as e:
            total_elapsed = (_time_module.time() - t_start) * 1000
            logger.exception(
                f"[Worker] crashed: tid={tid} type={task_type} "
                f"round={self._loop_count} elapsed={total_elapsed:.0f}ms"
            )
            fallback = self._build_tool_fallback()
            if fallback:
                self.stream_done.emit(tid, fallback)
                self.task_done.emit(tid, fallback, "")
            else:
                self.task_done.emit(tid, "", str(e))

    def _build_tool_fallback(self) -> str:
        """Compose a fallback reply from tool execution results when LLM fails."""
        log = self._task.tool_calls_log
        if not log:
            return ""
        parts = []
        for entry in log[-3:]:  # last 3 tools
            tool = entry["tool"]
            result = entry.get("result", "")[:200]
            if tool == "web_search":
                parts.append(f"搜到了些结果：{result[:150]}")
            elif tool == "read_file":
                parts.append(f"文件内容：{result[:150]}")
            else:
                parts.append(f"{tool}: {result[:150]}")
        if parts:
            return "工具执行完了，这是结果：\n" + "\n".join(parts)
        return ""

    def _wait_for_hitl(self, tool_name: str) -> bool:
        event = threading.Event()
        state = {"approved": False}
        with self._hitl_lock:
            self._hitl_waits[tool_name] = (event, state)
        try:
            if not event.wait(HITL_TIMEOUT):
                return False
            return bool(state.get("approved"))
        finally:
            with self._hitl_lock:
                self._hitl_waits.pop(tool_name, None)
