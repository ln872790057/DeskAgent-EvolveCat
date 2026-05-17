"""Rule-based research report critic."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from urllib.parse import urlparse

from skills.pro_researcher.models import ResearchReport


@dataclass
class CriticIssue:
    severity: str
    stage: str
    message: str


@dataclass
class CriticResult:
    passed: bool
    score: int
    issues: list[CriticIssue] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        return data


def review_report(report: ResearchReport) -> CriticResult:
    issues: list[CriticIssue] = []
    actions: list[str] = []

    core_events = report.top_events or report.events
    if len(report.events) < 3:
        issues.append(CriticIssue("high", "synthesis", "事件/观点条目不足，报告容易变成来源列表。"))
        actions.append("补充搜索并重新抽取至少 5 个具体条目。")
    if not report.one_line_conclusion:
        issues.append(CriticIssue("medium", "composer", "缺少一句话结论。"))
    if not report.editorial_summary or len(report.editorial_summary) < 80:
        issues.append(CriticIssue("medium", "composer", "编辑摘要过短，缺少综合判断。"))

    sourced = [event for event in core_events if event.source_urls]
    if core_events and len(sourced) < len(core_events):
        issues.append(CriticIssue("high", "evidence", "部分核心条目缺少来源编号。"))
        actions.append("删除无来源核心条目，或补充能支撑结论的来源。")

    impact_count = sum(1 for event in core_events if event.why_it_matters)
    if core_events and impact_count < min(3, len(core_events)):
        issues.append(CriticIssue("medium", "analysis", "影响判断不足，分析层没有充分工作。"))

    english_titles = [event for event in core_events if not _has_cjk(event.title)]
    if english_titles:
        issues.append(CriticIssue("high", "composer", "核心事件标题不是中文。"))
        actions.append("将标题、摘要、影响判断和证据点统一改写为中文。")

    short_events = [
        event for event in core_events
        if len(event.summary or "") < 80 or len(event.why_it_matters or "") < 50
    ]
    if short_events:
        issues.append(CriticIssue("medium", "composer", "核心事件内容过短，缺少背景、细节或影响分析。"))
        actions.append("扩写核心内容和编辑判断，每条至少包含背景、事实、影响和后续变量。")

    core_urls = {url for event in core_events for url in event.source_urls}
    core_sources = [source for source in report.sources if source.url in core_urls]
    weak_core = [
        source for source in core_sources
        if source.source_type in ("self_media", "aggregator", "pr") or not getattr(source, "usable_for_core", True)
    ]
    if weak_core:
        issues.append(CriticIssue("high", "source_selection", "低质量来源进入了核心结论。"))
        actions.append("将自媒体、聚合页、PR 或索引页降为背景来源。")

    unread_core = [source for source in core_sources if source.read_status not in ("full", "partial")]
    if unread_core:
        issues.append(CriticIssue("high", "source_selection", "核心结论使用了未读到正文的来源。"))
        actions.append("删除未读正文来源支撑的事件，或先成功读取原文后再生成报告。")

    if report.research_type == "news" and len(report.events) < 5:
        issues.append(CriticIssue("high", "synthesis", "新闻类报告少于 5 个具体事件。"))
        actions.append("补充权威来源并重新抽取至少 5 个具体新闻事件。")

    if report.research_type == "news" and "ai" in (report.topic or "").lower():
        off_topic = [
            event for event in core_events
            if any(term in f"{event.title} {event.summary}".lower() for term in ["future of news", "journalism", "media industry"])
        ]
        if off_topic:
            issues.append(CriticIssue("high", "relevance", "部分核心事件是新闻业/媒体行业主题，不是 AI 行业新闻。"))
            actions.append("过滤新闻业应用类条目，除非用户明确要求调研 AI 对新闻行业的影响。")

    if _topic_requires_agent(report.topic):
        drifted = [
            event for event in core_events
            if not _contains_agent_signal(f"{event.title} {event.summary} {event.category}")
        ]
        if drifted:
            issues.append(CriticIssue("high", "relevance", "部分核心事件与 AI Agent 主题相关性不足。"))
            actions.append("过滤泛 AI 新闻，只保留 Agent、agentic、工作流自动化、A2A/MCP 等相关事件。")

    single_source_data = [
        event for event in core_events
        if len({urlparse(url).netloc for url in event.source_urls}) < 2
        and _looks_like_data_claim(f"{event.title} {event.summary} {' '.join(event.evidence)}")
        and not any(source.source_type in ("official", "paper") for source in core_sources if source.url in event.source_urls)
    ]
    if single_source_data:
        issues.append(CriticIssue("medium", "evidence", "部分数字或调查结论缺少官方/原始来源或第二来源交叉验证。"))
        actions.append("追溯原始报告；追不到则在正文中标为待核验背景。")

    if report.research_type == "company":
        has_financial_source = any(
            any(token in f"{source.title} {source.url} {source.snippet}" for token in ["年报", "季报", "公告", "cninfo", "szse", "sse", "财报"])
            for source in report.sources
        )
        if not has_financial_source:
            issues.append(CriticIssue("high", "source_selection", "公司研究缺少年报、公告或财报类来源。"))
            actions.append("补搜交易所公告、巨潮资讯、官网投资者关系和年报。")

    score = 100
    for issue in issues:
        score -= {"high": 25, "medium": 12, "low": 5}.get(issue.severity, 8)
    score = max(0, score)
    passed = not any(issue.severity == "high" for issue in issues) and score >= 70
    return CriticResult(passed=passed, score=score, issues=issues, required_actions=actions)


def _topic_requires_agent(topic: str) -> bool:
    text = (topic or "").lower()
    return any(token in text for token in ["agent", "agentic", "ai agent", "智能体"])


def _contains_agent_signal(text: str) -> bool:
    text_l = (text or "").lower()
    return any(token in text_l for token in [
        "agent", "agentic", "ai agent", "multi-agent", "workflow automation",
        "computer use", "agentforce", "mcp", "a2a", "copilot", "智能体",
    ])


def _looks_like_data_claim(text: str) -> bool:
    text_l = (text or "").lower()
    if any(ch.isdigit() for ch in text_l) and any(token in text_l for token in ["%", "percent", "增长", "采用", "调查", "survey", "adoption", "increase"]):
        return True
    return any(token in text_l for token in ["pwc", "salesforce", "mckinsey", "gartner", "idc"])


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")
