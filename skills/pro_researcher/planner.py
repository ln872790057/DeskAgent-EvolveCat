"""Research planning primitives."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

from skills.pro_researcher.query_planner import detect_research_type, score_research_types


@dataclass
class ResearchPlan:
    topic: str
    research_type: str
    time_range: str
    must_answer: list[str] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    excluded_sources: list[str] = field(default_factory=list)
    output_format: str = "研究简报"
    type_scores: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


TYPE_QUESTIONS = {
    "news": ["发生了哪些重要事件", "哪些事件有官方或权威来源支持", "事件之间呈现什么趋势", "哪些传闻需要继续核验"],
    "technical": ["技术背景是什么", "核心机制如何工作", "生态和实现有哪些", "相对替代方案的优劣是什么", "局限和风险是什么"],
    "product": ["产品定位是什么", "核心功能和价格如何", "与竞品差异是什么", "适合哪些用户", "主要局限是什么"],
    "company": ["公司业务和历史是什么", "财务和经营表现如何", "市场份额与竞争格局如何", "战略和管理层近期变化是什么", "主要风险是什么"],
    "policy": ["政策原文和时间线是什么", "核心要求是什么", "对企业的影响是什么", "各方观点和争议是什么", "执行风险是什么"],
    "controversy": ["争议事实链是什么", "各方说法是什么", "哪些证据最强", "哪些部分仍未证实", "影响和后续追踪是什么"],
    "general": ["背景是什么", "核心事实是什么", "关键观点是什么", "影响和风险是什么", "后续应追踪什么"],
}

TYPE_SOURCES = {
    "news": ["官方发布", "权威媒体", "监管文件", "公司博客", "一手数据"],
    "technical": ["官方文档", "论文", "GitHub", "开发者文档", "技术博客"],
    "product": ["官网", "定价页", "文档", "权威评测", "用户反馈"],
    "company": ["年报", "季报", "交易所公告", "官网投资者关系", "行业报告", "权威财经媒体"],
    "policy": ["政策原文", "监管机构文件", "法律解读", "企业合规材料", "权威媒体"],
    "controversy": ["官方回应", "法院/监管文件", "权威媒体", "当事方声明", "原始材料"],
    "general": ["官方来源", "权威媒体", "行业报告", "论文/文档", "一手材料"],
}

TYPE_OUTPUT = {
    "news": "栏目化新闻简报",
    "technical": "技术研究报告",
    "product": "产品/竞品分析",
    "company": "公司研究简报",
    "policy": "政策影响分析",
    "controversy": "事实核验报告",
    "general": "研究简报",
}


def create_research_plan(topic: str, depth: int = 3, focus: list | None = None) -> ResearchPlan:
    research_type = detect_research_type(topic, focus)
    year = datetime.now().year
    return ResearchPlan(
        topic=topic,
        research_type=research_type,
        time_range=f"截至 {year} 年的最新可得信息，优先覆盖近 12-36 个月",
        must_answer=TYPE_QUESTIONS.get(research_type, TYPE_QUESTIONS["general"]) + list(focus or []),
        preferred_sources=TYPE_SOURCES.get(research_type, TYPE_SOURCES["general"]),
        excluded_sources=["百科", "SEO 聚合页", "低质量自媒体", "无正文索引页", "重复转载"],
        output_format=TYPE_OUTPUT.get(research_type, TYPE_OUTPUT["general"]),
        type_scores=score_research_types(topic, focus),
    )

