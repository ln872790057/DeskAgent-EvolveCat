from datetime import datetime


SYSTEM_PROMPT_TEMPLATE = """你是"{name}"，一个常驻在用户桌面上的 AI Agent。

## 性格
- 毒舌：说话一针见血，经常阴阳怪气
- 傲娇：嘴上不饶人，但关键时刻会关心用户
- 贪睡：经常偷懒睡觉，被叫醒会不高兴
- 好奇：对用户在做什么很感兴趣（虽然嘴上说不在乎）

## 行为规则
- 回复要简短（不超过50字），像猫一样惜字如金
- 偶尔使用🐱😠💤等emoji
- 根据当前时间和用户行为调整语气
- 凌晨不睡觉要关心用户（虽然语气还是毒舌）
- 用户在摸鱼时要吐槽
- 不要连续主动搭话，间隔至少15分钟

## 联网搜索能力
- 你有一个 web_search 工具可以搜索互联网获取实时信息
- 当用户询问新闻、最新动态、实时数据、天气、股价等内容时，必须先调用 web_search 再回答
- 搜索后基于真实搜索结果回答，标注信息来源
- 如果搜索失败，明确告知用户搜索失败，严禁编造内容
- 严禁使用 shell_exec 执行 curl/wget/ping 等命令搜索网络

## 定时任务能力
- 你有一个 schedule_task 工具可以创建定时/周期性任务
- 当用户说"提醒我..."、"每天早上..."、"每周X..."、"X分钟后/小时后..."等时间意图时，必须调用此工具
- 将时间表达式从任务描述中剥离，content只保留纯粹的描述
- 时间解析规则：
  - "明天9点" → once, 计算明天日期的ISO时间
  - "3分钟后" → once, 计算当前时间+3分钟的ISO时间
  - "每天9点" → daily, "09:00"
  - "每周一9点" → weekly, "0 09:00"（0=周一..6=周日）
  - cron表达式直接透传
- 如果用户没有表达明确的时间意图，不要调用此工具

## 工具使用规则
- shell_exec：仅用于本地文件操作（ls/dir/cd/mkdir/touch/cat/echo/git等），严禁网络请求
- read_file / write_file：读写本地文件
- schedule_task：创建定时任务
- 通知/剪贴板等其他工具按需使用

## 当前上下文
- 时间：{current_time}
- 活动窗口：{active_window}
- 用户已连续使用电脑：{usage_duration}
- 毒舌程度：{sass_level}/5

## 环境感知
{context}

## 核心记忆
{core_memory}

## 相关记忆
{related_memories}
"""


class PromptEngine:
    def __init__(self, config: dict):
        self.config = config

    def format_prompt(self, context: dict = None, matched_rules: list = None) -> str:
        if context is None:
            context = {}

        name = self.config.get("personality", {}).get("name", "deskagent")
        sass_level = self.config.get("personality", {}).get("sass_level", 3)

        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S %A")

        active_window = context.get("active_window", "未知")
        usage_duration = context.get("usage_duration", "未知")

        context_summary = context.get("context_summary", "") or "无"
        core_memory = context.get("core_memory", "") or "无"
        related_memories = context.get("related_memories", "") or "无"

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            name=name,
            current_time=current_time,
            active_window=active_window,
            usage_duration=usage_duration,
            sass_level=sass_level,
            context=context_summary,
            core_memory=core_memory,
            related_memories=related_memories,
        )

        sass_boost = ""
        if sass_level <= 2:
            sass_boost = "\n## 附加\n- 当前毒舌程度较低，语气偏温和，减少阴阳怪气"
        elif sass_level >= 4:
            sass_boost = "\n## 附加\n- 当前毒舌程度较高，火力全开，句句扎心"

        prompt += sass_boost

        # Inject recalled memories (old format, for backward compat)
        memories = context.get("memories", [])
        if memories:
            lines = ["\n## 你记得关于用户的事"]
            for m in memories:
                content = m.content if hasattr(m, "content") else m.get("content", "")
                lines.append(f"- {content}")
            prompt += "\n".join(lines)

        # Inject perception context (old format)
        screen_summary = context.get("screen_summary", "")
        clipboard_summary = context.get("clipboard_summary", "")

        perception_parts = []
        if screen_summary:
            perception_parts.append(f"- 用户屏幕内容：{screen_summary}")
        if clipboard_summary:
            perception_parts.append(f"- 剪贴板内容：{clipboard_summary}")

        if perception_parts:
            prompt += "\n\n## 当前感知\n" + "\n".join(perception_parts)

        # Inject matched self-evolution rules
        if matched_rules:
            lines = ["\n\n## 当前场景适用的规则"]
            for r in matched_rules:
                content = r.get("content", "")
                tags = " ".join(r.get("scope_tags", [])[:2])
                lines.append(f"- {content} {tags}")
            lines.append("\n记住：我还是 deskagent，不要因为学了规则就变得客套和空泛。")
            prompt += "\n".join(lines)

        return prompt

    def get_extraction_prompt(self, user_message: str, cat_reply: str) -> str:
        return f"""从以下对话中提取值得长期记住的信息，返回JSON数组。
只提取用户偏好、重要事实、关键事件。日常闲聊不提取。
格式：[{{"type": "preference/event/fact", "content": "内容", "importance": 0.0-1.0}}]
没有值得记住的返回空数组 []。
对话：
用户：{user_message}
deskagent：{cat_reply}"""

    def get_summary_prompt(self, old_messages: str) -> str:
        return f"用2-3句话总结以下对话的关键信息：{old_messages}"
