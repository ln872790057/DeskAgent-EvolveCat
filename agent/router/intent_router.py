"""Rule-first intent router with structured output.

The router is intentionally cheap: simple messages should not pay for an
extra model call before the real work even starts.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class IntentResult:
    intent: str
    workflow: str
    complexity: str = "low"
    needs_plan: bool = False
    needs_user_confirmation: bool = False
    estimated_runtime: str = "seconds"
    risk_level: str = "low"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def task_kind(self) -> str:
        return "CHAT" if self.workflow == "chat" else "TASK"


CHAT_KEYWORDS = [
    "你好", "谢谢", "哈哈", "在吗", "早安", "晚安", "午安", "吃了吗",
    "为什么", "是不是", "好看吗", "喜欢", "讨厌", "无聊", "辛苦了",
]

RESEARCH_KEYWORDS = [
    "调研", "研究", "深度分析", "行业分析", "竞品分析", "市场分析",
    "资料收集", "查一下", "调查", "核验", "是否属实", "研究报告",
]

CODING_KEYWORDS = [
    "代码", "bug", "报错", "实现", "重构", "开发", "测试", "运行测试",
    "修复", "函数", "类", "接口", "repository", "repo", "commit",
]

DATA_KEYWORDS = [
    "数据", "csv", "excel", "表格", "统计", "可视化", "图表", "分析数据",
    "pandas", "dataset",
]

SCHEDULE_KEYWORDS = [
    "提醒", "定时", "每天", "每周", "每月", "分钟后", "小时后", "明天",
    "schedule", "remind",
]

FILE_KEYWORDS = [
    "读取文件", "写文件", "保存到", "整理文件", "重命名", "复制", "剪贴板",
    "read file", "write file",
]

TASK_KEYWORDS = [
    "搜索", "总结", "翻译", "分析", "生成", "列出", "制作", "安排",
    "计划", "提取", "转换", "计算", "截图", "通知", "执行", "运行",
    "安装", "下载",
]


def route_intent(message: str, context: dict | None = None) -> IntentResult:
    text = (message or "").strip()
    lower = text.lower()

    if not text:
        return IntentResult("chat", "chat")

    if any(k in lower or k in text for k in SCHEDULE_KEYWORDS):
        return IntentResult("schedule", "schedule", complexity="low", needs_plan=False)

    if any(k in lower or k in text for k in RESEARCH_KEYWORDS):
        return IntentResult(
            "research",
            "research",
            complexity="high",
            needs_plan=True,
            estimated_runtime="minutes",
        )

    if any(k in lower or k in text for k in CODING_KEYWORDS):
        return IntentResult(
            "coding",
            "coding",
            complexity="medium",
            needs_plan=True,
            estimated_runtime="minutes",
            risk_level="medium",
        )

    if any(k in lower or k in text for k in DATA_KEYWORDS):
        return IntentResult(
            "data_analysis",
            "data_analysis",
            complexity="medium",
            needs_plan=True,
            estimated_runtime="minutes",
        )

    if any(k in lower or k in text for k in FILE_KEYWORDS):
        return IntentResult("file_ops", "file_ops", complexity="medium", risk_level="medium")

    has_task = any(k in lower or k in text for k in TASK_KEYWORDS)
    has_chat = any(k in lower or k in text for k in CHAT_KEYWORDS)
    if has_task:
        return IntentResult("task", "react_task", complexity="medium", needs_plan=len(text) > 40)
    if has_chat:
        return IntentResult("chat", "chat")
    if len(text) > 20:
        return IntentResult("task", "react_task", complexity="medium")
    return IntentResult("chat", "chat")


def classify_message(message: str) -> str:
    """Compatibility wrapper for legacy callers."""
    return route_intent(message).task_kind

