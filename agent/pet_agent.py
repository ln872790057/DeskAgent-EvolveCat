import json
import time
from typing import Callable, Generator

from agent.base import BaseAgent, AgentResponse
from agent.llm.router import LLMRouter
from agent.llm.openai_client import AuthError, RateLimitError, NetworkError
from agent.prompt import PromptEngine
from agent.context import ContextManager
from agent.tools import ToolRegistry
from agent.memory.sqlite_store import SQLiteMemoryStore
from agent.memory import file_store as memory_files
from agent.memory.compact import CompactManager
from agent.memory.extractor import MemoryExtractor
from agent.memory.self_evolution.rule_manager import RuleManager
from agent.memory.self_evolution.engine import EvolutionEngine, CORRECTION_KEYWORDS
from agent.memory.self_evolution.message_manager import MessageManager
from agent.quick_actions import check_quick_action
from utils.logger import get_logger

logger = get_logger("agent.pet_agent")

MAX_TOOL_ROUNDS = 3

# ── Reduced error messages for streaming (fewer emoji to avoid encoding issues) ──
DEGRADE_AUTH = ("我脑子坏了...帮我修修设置呗？", "sick_dizzy")
DEGRADE_RATE = ("挤爆了，等会儿再聊", "sick_frustrated")
DEGRADE_NETWORK = ("网都没了，我先睡会儿", "sick_sleepy")
DEGRADE_FALLBACK = ("我刚才走神了，再说一遍？", "talk")


def _safe_close_gen(gen):
    if hasattr(gen, "close"):
        try:
            gen.close()
        except Exception:
            pass


def _call_llm_sync(client, messages, tools):
    """Call LLM synchronously with retry. Returns (result_dict, emotion_override)."""
    last_error = None
    for attempt in range(3):
        try:
            result = client.chat(messages, tools=tools, stream=False)
            return result, None
        except RateLimitError as e:
            last_error = e
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
            else:
                logger.error("Rate limit retries exhausted")
                return {"type": "degraded", "reply": DEGRADE_RATE[0],
                        "emotion": DEGRADE_RATE[1]}, DEGRADE_RATE[1]
        except AuthError as e:
            logger.error(f"Auth error: {e}")
            return {"type": "degraded", "reply": DEGRADE_AUTH[0],
                    "emotion": DEGRADE_AUTH[1]}, DEGRADE_AUTH[1]
        except NetworkError as e:
            logger.error(f"LLM error: {e}")
            return {"type": "degraded", "reply": DEGRADE_NETWORK[0],
                    "emotion": DEGRADE_NETWORK[1]}, DEGRADE_NETWORK[1]
        except Exception as e:
            logger.error(f"Unexpected LLM error: {e}")
            return {"type": "degraded", "reply": DEGRADE_FALLBACK[0],
                    "emotion": DEGRADE_FALLBACK[1]}, None

    return {"type": "degraded", "reply": DEGRADE_FALLBACK[0],
            "emotion": DEGRADE_FALLBACK[1]}, None


class PetAgent(BaseAgent):
    def __init__(self, config: dict, dream_worker=None):
        self.config = config
        self.router = LLMRouter()
        self.prompt_engine = PromptEngine(config)
        self.context = ContextManager()
        self.memory = SQLiteMemoryStore()
        self.compact_mgr = CompactManager()
        self.extractor = MemoryExtractor(self.memory, memory_files)
        self._dream_worker = dream_worker

        # Self-evolution engine
        self._rule_manager = RuleManager()
        self._message_manager = MessageManager()
        self._evolution_engine = EvolutionEngine(self._rule_manager, self._message_manager)
        self._pending_special_msg: str | None = None
        self._current_tags: list[str] = []
        self._scene_tagged = False  # tag only once per conversation window

    def set_dream_worker(self, dw):
        self._dream_worker = dw

    def get_pending_special_msg(self) -> str | None:
        """Return and clear the pending special message (evolution confirm/conflict)."""
        msg = self._pending_special_msg
        self._pending_special_msg = None
        return msg

    def reset_scene_tags(self):
        """Reset scene tagging for a new conversation window."""
        self._scene_tagged = False
        self._current_tags = []

    @property
    def rule_manager(self):
        return self._rule_manager

    # ── Sync chat ──

    def chat(self, message: str, context: dict = None) -> AgentResponse:
        t_start = time.time()
        if context is None:
            context = {}

        # Phase 8: Quick actions (highest priority)
        clipboard_text = self.context._perception_context.get("clipboard_summary", "")
        replaced = check_quick_action(message, clipboard_text)
        if replaced:
            logger.info(f"[Agent] quick_action triggered, replacing message")
            message = replaced

        logger.info(f"[Agent] user_input: {message[:200]}")
        self.context.add_user_message(message)

        # Self-evolution: tag scene + match rules
        if not self._scene_tagged:
            self._current_tags = self._rule_manager.tag_message(message)
            self._scene_tagged = True
        matched_rules = self._rule_manager.match_rules(self._current_tags, limit=3)

        # Phase 11: Memory recall
        core_memory = memory_files.read_memory_md()
        related = self.memory.search(message, limit=5)
        for m in related:
            self.memory.update_access(m.id)
        related_text = "\n".join(
            f"- [{m.type}] {m.content}" for m in related
        ) if related else ""
        context_summary = self.context.get_perception_context()
        context_text = "\n".join(
            f"- {k}: {v}" for k, v in context_summary.items() if v
        )

        perception = self.context.get_perception_context()
        merged_context = {
            **perception, **context,
            "memories": related,
            "context_summary": context_text,
            "core_memory": core_memory,
            "related_memories": related_text,
        }
        system_prompt = self.prompt_engine.format_prompt(merged_context, matched_rules=matched_rules)
        messages = self.context.get_messages_for_llm(system_prompt)

        # Phase 3: AutoCompact
        client = self.router.get_client()
        messages = self.compact_mgr.compact(messages, client)

        logger.debug(f"[Agent] messages_to_llm: {len(messages)} msgs, "
                      f"system_prompt_len={len(system_prompt)}, history_rounds={len(self.context._history)//2}")

        tools = self.get_tools()

        result, emotion_override = _call_llm_sync(client, messages, tools)
        thinking_info = None

        if result.get("type") == "degraded":
            reply = result["reply"]
            emotion = result["emotion"]
            logger.warning(f"[Agent] degraded response: {reply[:80]}")
        elif result.get("type") == "tool_calls":
            logger.info(f"[Agent] tool_calls detected, entering tool loop")
            reply, emotion, thinking_info = self._handle_tool_loop(
                client, messages, result, tools
            )
        else:
            reply = result.get("content", "喵？")
            emotion = self._detect_emotion(message, reply)
            logger.info(f"[Agent] direct text reply: len={len(reply)}, emotion={emotion}")

        if emotion_override:
            emotion = emotion_override

        self.context.add_assistant_message(reply)

        # Self-evolution: detect corrections, process triggers
        if any(kw in message for kw in CORRECTION_KEYWORDS):
            result_msg = self._evolution_engine.process(
                message, reply, client,
                self.context._history[-20:]  # last 10 rounds
            )
            if result_msg:
                self._pending_special_msg = result_msg
        self._message_manager.record_normal_msg()

        # Phase 5: Notify dream worker of new conversation round
        if self._dream_worker:
            self._dream_worker.on_chat_end()

        # Phase 4: Async memory extraction
        self._extract_memory_async(message, reply)
        # Summary if context overflows
        self._maybe_summarize()

        elapsed = (time.time() - t_start) * 1000
        logger.info(f"[Agent] chat complete: reply_len={len(reply)}, emotion={emotion}, "
                      f"tool_rounds={len(thinking_info)}, elapsed={elapsed:.0f}ms")
        return AgentResponse(
            reply=reply,
            emotion=emotion,
            tool_calls=thinking_info,
        )

    # ── Streaming chat: uses sync chat() internally to handle tool calls,
    # then simulates streaming by yielding reply character by character.

    def chat_stream(
        self, message: str, context: dict = None, on_complete: Callable = None,
    ) -> Generator[str, None, None]:
        if context is None:
            context = {}

        # Use sync chat() which handles tool calls properly
        response = self.chat(message, context)
        reply = response.reply
        emotion = response.emotion

        # Simulate streaming: yield chars one by one
        for char in reply:
            yield char
            import time
            time.sleep(0.015)  # ~15ms per char for natural typing feel

        if on_complete:
            on_complete(emotion)

    # ── Memory helpers ──

    def _extract_memory_async(self, user_msg: str, cat_reply: str):
        """Extract memories asynchronously via QTimer (next event loop tick)."""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_extract_memory(user_msg, cat_reply))

    def _do_extract_memory(self, user_msg: str, cat_reply: str):
        try:
            client = self.router.get_client()
            self.extractor.extract_and_store(user_msg, cat_reply, client)
        except Exception:
            logger.debug("memory extraction failed (non-critical)", exc_info=True)

    def _maybe_summarize(self):
        if not self.context.has_pending_summary():
            return
        try:
            old_text = self.context.get_pending_summary_text()
            summary_prompt = self.prompt_engine.get_summary_prompt(old_text)
            client = self.router.get_client()
            result, _ = _call_llm_sync(client, [
                {"role": "user", "content": summary_prompt}
            ], tools=None)
            summary = result.get("content", "") if isinstance(result, dict) else ""
            if summary:
                self.context.set_summary(summary)
            self.context.clear_pending_summary()
        except Exception:
            logger.debug("summary failed (non-critical)", exc_info=True)

    # ── Other methods ──

    def get_system_prompt(self, context: dict = None) -> str:
        return self.prompt_engine.format_prompt(context)

    def get_tools(self) -> list:
        return ToolRegistry.get_all_schemas()

    def handle_perception(self, event_type: str, data: str) -> str | None:
        """Handle perception events. Returns talk text if should trigger a chat, else None."""
        if event_type == "screen":
            self.context.update_perception("screen_summary", data)
        elif event_type == "clipboard":
            self.context.update_perception("clipboard_summary", data)
            # Detect code in clipboard
            if self._is_code(data):
                return "哟，抄代码呢？我什么都没看见🐱"
        elif event_type == "window":
            self.context.update_perception("active_window", data)
        return None

    def _is_code(self, text: str) -> bool:
        code_indicators = ["if ", "import ", "def ", "class ", "from ", "return ",
                           "function ", "const ", "let ", "var ", "print(", "async "]
        count = sum(1 for kw in code_indicators if kw in text)
        return count >= 2

    def _handle_tool_loop(self, client, messages, initial_result, tools) -> tuple[str, str, list]:
        thinking = []
        current_result = initial_result
        full_reply = ""
        loop_start = time.time()

        for round_num in range(MAX_TOOL_ROUNDS):
            tool_calls = current_result.get("tool_calls", [])
            if not tool_calls:
                full_reply = current_result.get("content", "")
                logger.info(f"[Agent] tool_loop exit: round={round_num}, got text reply")
                break

            logger.info(f"[Agent] tool_loop round={round_num}: {len(tool_calls)} tool_calls "
                         f"-> {[tc['function']['name'] for tc in tool_calls]}")

            tool_results = []
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    func_args = {}
                    logger.warning(f"[Agent] tool_loop: failed to parse args for {func_name}")

                t_tool = time.time()
                logger.info(f"[Agent] tool_exec start: {func_name} args={json.dumps(func_args, ensure_ascii=False)[:200]}")
                try:
                    result = ToolRegistry.execute_with_timeout(func_name, func_args, timeout=10)
                    elapsed = (time.time() - t_tool) * 1000
                    result_preview = str(result)[:500]
                    logger.info(f"[Agent] tool_exec done: {func_name} elapsed={elapsed:.0f}ms "
                                 f"result_preview={result_preview}")
                    thinking.append({"tool": func_name, "args": func_args, "result": str(result)[:100]})
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": str(result),
                    })
                except Exception as e:
                    logger.exception(f"[Agent] tool_exec failed: {func_name}")
                    thinking.append({"tool": func_name, "error": str(e)})
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": f"执行失败: {e}",
                    })

            assistant_message = current_result.get("assistant_message")
            if not isinstance(assistant_message, dict):
                assistant_message = {
                    "role": "assistant",
                    "content": current_result.get("content") or "",
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
            else:
                assistant_message = dict(assistant_message)
                assistant_message["role"] = "assistant"
            messages.append(assistant_message)
            messages.extend(tool_results)
            logger.debug(f"[Agent] tool_loop: messages now {len(messages)} (appended {1+len(tool_results)} msgs)")

            try:
                next_result, _ = _call_llm_sync(client, messages, tools)
                logger.info(f"[Agent] tool_loop llm_after_tools: type={next_result.get('type')} "
                             f"has_tool_calls={bool(next_result.get('tool_calls'))}")
            except Exception as e:
                logger.exception(f"[Agent] tool_loop LLM call crashed: round={round_num}")
                if thinking:
                    parts = [f"{t['tool']}搞定了" if "error" not in t else f"{t['tool']}失败" for t in thinking]
                    full_reply = "、".join(parts) + "（脑子卡了，但活干完了🐱）"
                else:
                    full_reply = "我刚才走神了，再说一遍？"
                break

            if next_result.get("type") == "degraded":
                logger.warning(f"[Agent] tool_loop degraded: round={round_num} reply={next_result.get('reply','')[:80]}")
                if thinking:
                    parts = [f"{t['tool']}搞定了" if "error" not in t else f"{t['tool']}失败" for t in thinking]
                    full_reply = "、".join(parts) + "（脑子卡了，但活干完了🐱）"
                else:
                    full_reply = next_result["reply"]
                break
            current_result = next_result

        if not full_reply:
            logger.warning(f"[Agent] tool_loop: no reply after {len(thinking)} tools, "
                           f"loop_elapsed={(time.time()-loop_start)*1000:.0f}ms")
            full_reply = "喵？"
        emotion = self._detect_emotion("", full_reply)
        return full_reply, emotion, thinking

    def _detect_emotion(self, user_msg: str, reply: str) -> str:
        combined = user_msg + reply
        if any(w in combined for w in ["谢谢", "赞", "好棒", "厉害", "不错"]):
            return "happy"
        if any(w in combined for w in ["烦", "气", "讨厌", "滚", "别烦"]):
            return "angry"
        if any(w in combined for w in ["代码", "工作", "bug", "报错", "写", "开发"]):
            return "working"
        return "talk"
