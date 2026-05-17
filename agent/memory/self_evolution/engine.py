"""EvolutionEngine — trigger detection + LLM rule extraction + process orchestration."""
import json

from utils.logger import get_logger

logger = get_logger("agent.self_evolution.engine")

CORRECTION_KEYWORDS = ["不对", "应该", "不要", "别", "改一下", "改成", "不是这样", "错了"]


class EvolutionEngine:
    """Detects triggers for rule learning, extracts rules via LLM, and generates confirm messages."""

    def __init__(self, rule_manager, message_manager):
        self.rule_manager = rule_manager
        self.message_manager = message_manager

    def check_triggers(self, user_msg: str, reply: str, history: list) -> tuple | None:
        """Check if any learning trigger is active.
        Returns (trigger_type, context) or None.
        """
        # Trigger 1: User correction keywords
        msg = user_msg.strip()
        if any(kw in msg for kw in CORRECTION_KEYWORDS):
            return ("correction", {"user_msg": user_msg, "reply": reply})

        # Trigger 2 & 3 require history analysis (>=3 same-type tasks or >=2 same-type corrections)
        if len(history) < 6:
            return None

        recent = history[-10:]
        user_msgs = [m.get("content", "") for m in recent if m.get("role") == "user"]

        # Trigger 2: 3+ same-type tasks in recent history
        tags_list = [set(self.rule_manager.tag_message(m)) for m in user_msgs if m]
        if len(tags_list) >= 3:
            for i in range(len(tags_list) - 2):
                common = tags_list[i] & tags_list[i + 1] & tags_list[i + 2]
                if common:
                    return ("pattern", {"task_tags": list(common), "count": 3})

        # Trigger 3: 2+ corrections of same type
        correction_msgs = [m for m in user_msgs if any(kw in (m or "") for kw in CORRECTION_KEYWORDS)]
        if len(correction_msgs) >= 2:
            corr_tags = [self.rule_manager.tag_message(m) for m in correction_msgs]
            for i in range(len(corr_tags) - 1):
                if corr_tags[i] & corr_tags[i + 1]:
                    return ("repeat_correction", {"task_tags": list(corr_tags[i]), "count": len(correction_msgs)})

        return None

    def extract_rule(self, context: dict, llm_client) -> dict | None:
        """Call LLM to extract a rule from a correction context. Returns rule dict or None."""
        user_msg = context.get("user_msg", "")[:300]
        reply = context.get("reply", "")[:300]

        prompt = (
            "你是 deskagent 的自我进化模块。用户刚才纠正了 Agent 的行为，提炼一条简洁的规则。\n"
            '输出JSON：{"content": "规则内容", "type": "output_style|process|behavior|other", '
            '"scope_tags": ["📰 新闻查询", "💬 闲聊"]}\n'
            "规则简短（15字内）。标签从这12个选：📰新闻查询 🔍搜索 💻写代码 📝写文档 "
            "📊分析 🔧调试 💬闲聊 🤔提问 ✏️创建/修改 ⚡忙碌 😊轻松 🎯专注\n\n"
            f"用户纠正：{user_msg}\n猫的回复：{reply}"
        )
        try:
            result = llm_client.chat(
                [{"role": "user", "content": prompt}],
                tools=None, stream=False,
            )
            text = result.get("content", "{}") if isinstance(result, dict) else "{}"
            # Extract JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            logger.debug("[Engine] LLM rule extraction JSON parse failed")
        except Exception:
            logger.debug("[Engine] rule extraction LLM call failed", exc_info=True)
        return None

    def process(self, user_msg: str, reply: str, llm_client, history: list) -> str | None:
        """Main entry: check triggers, extract rule, generate confirm message.
        Returns special message string or None.
        """
        trigger = self.check_triggers(user_msg, reply, history)
        if not trigger:
            return None

        trigger_type, context = trigger
        logger.info(f"[Engine] trigger: {trigger_type}")

        # Only extract rules for corrections (simpler path for MVP)
        if trigger_type == "correction":
            rule_dict = self.extract_rule(context, llm_client)
            if not rule_dict:
                return None

            content = rule_dict.get("content", "")
            tags = rule_dict.get("scope_tags", []) or self.rule_manager.tag_message(user_msg)

            # Check for existing similar rule
            existing = self.rule_manager.find_similar(content, tags)
            if existing:
                # Increment failure on old rule, user is overriding
                self.rule_manager.increment_failure(existing["rule_id"])
                logger.info(f"[Engine] similar rule exists: {existing['rule_id']}, incrementing failure")

            # Check rate limit
            priority = self.message_manager.PRIORITY_CORRECTION
            if not self.message_manager.can_send(priority):
                self.message_manager.add_pending(rule_dict)
                logger.info("[Engine] rate limited, deferred to weekly report")
                return None

            # Generate confirm message
            msg = self.message_manager.build_confirm_msg(content, tags)
            self.message_manager.record_sent()
            return msg

        return None

    def process_pattern(self, task_tags: list[str]) -> str | None:
        """Process a detected pattern (repeated task type). Returns message or None."""
        priority = self.message_manager.PRIORITY_PATTERN
        if not self.message_manager.can_send(priority):
            self.message_manager.add_pending({"task_tags": task_tags, "type": "pattern"})
            return None
        tag_str = " ".join(task_tags)
        msg = f"注意到你经常做{tag_str}类的操作，有什么我可以提前准备的？"
        self.message_manager.record_sent()
        return msg
