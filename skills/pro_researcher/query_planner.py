"""Search query generation with type-aware research budgets."""
from datetime import datetime

DEPTH_BUDGETS = {
    1: {"query_count": 5, "results_per_query": 4, "max_sources": 12, "max_pages_to_read": 7, "timeout_seconds": 60, "batch_size": 5},
    2: {"query_count": 8, "results_per_query": 5, "max_sources": 20, "max_pages_to_read": 12, "timeout_seconds": 120, "batch_size": 5},
    3: {"query_count": 12, "results_per_query": 5, "max_sources": 30, "max_pages_to_read": 18, "timeout_seconds": 240, "batch_size": 6},
    4: {"query_count": 16, "results_per_query": 6, "max_sources": 42, "max_pages_to_read": 28, "timeout_seconds": 360, "batch_size": 6},
    5: {"query_count": 22, "results_per_query": 6, "max_sources": 56, "max_pages_to_read": 40, "timeout_seconds": 540, "batch_size": 7},
}

TYPE_COLUMNS = {
    "news": ["核心新闻", "官方发布", "权威媒体", "行业动态", "风险争议", "趋势总结"],
    "technical": ["技术原理", "官方文档", "论文", "GitHub", "架构对比", "局限问题", "应用案例"],
    "product": ["产品定位", "功能对比", "价格方案", "用户评价", "替代产品", "适用场景", "局限问题"],
    "company": ["公司战略", "产品发布", "融资资本", "财务数据", "管理层", "竞争格局", "风险争议"],
    "policy": ["政策原文", "监管解读", "企业影响", "合规要求", "各方观点", "执行时间线"],
    "controversy": ["事实时间线", "官方回应", "权威媒体", "各方立场", "证据核验", "影响风险"],
    "general": ["背景", "核心事实", "权威来源", "行业分析", "风险局限", "未来趋势"],
}

OFFICIAL_SOURCE_HINTS = {
    "news": ["site:reuters.com", "site:apnews.com", "site:bloomberg.com", "site:ft.com", "site:theverge.com"],
    "technical": ["site:github.com", "site:arxiv.org", "site:docs.", "site:developer.", "site:paperswithcode.com"],
    "product": ["official docs", "pricing", "changelog", "review", "alternatives", "comparison"],
    "company": ["site:sec.gov", "site:reuters.com", "site:crunchbase.com", "site:companiesmarketcap.com"],
    "policy": ["site:gov", "site:europa.eu", "site:oecd.org", "site:whitehouse.gov", "site:gov.cn"],
    "controversy": ["official statement", "site:reuters.com", "site:apnews.com", "lawsuit", "court filing"],
    "general": ["official", "report", "analysis", "documentation"],
}

TYPE_KEYWORDS = {
    "controversy": [
        "争议", "传闻", "属实", "真假", "解散", "诉讼", "丑闻",
        "controversy", "lawsuit", "rumor", "true or false",
    ],
    "policy": [
        "政策", "监管", "法案", "合规", "条例", "监管影响",
        "act", "regulation", "policy", "compliance",
    ],
    "company": [
        "公司", "企业", "上市公司", "财报", "年报", "季报", "公告", "营收",
        "净利润", "管理层", "供应链", "生产基地", "市场份额", "竞争格局",
        "战略", "融资", "估值", "投资者关系", "anthropic", "openai", "xai",
        "meta", "google", "tesla", "nvidia",
    ],
    "technical": [
        "协议", "技术", "原理", "架构", "论文", "生态", "源码", "实现",
        "benchmark", "mcp", "paper", "github", "api", "sdk", "architecture",
    ],
    "product": [
        "区别", "对比", "竞品", "产品", "价格", "功能", "替代", "选型",
        "cursor", "claude code", "alternatives", "pricing", "features", "compare",
    ],
    "news": [
        "新闻", "日报", "动态", "近期", "最新", "本月", "今天", "today",
        "news", "daily", "brief", "latest",
    ],
}

TYPE_PRIORITY = ["controversy", "policy", "company", "technical", "product", "news", "general"]


def score_research_types(topic: str, focus: list | None = None) -> dict[str, int]:
    """Score research types instead of returning the first keyword hit."""
    text = f"{topic} {' '.join(focus or [])}".lower()
    scores = {key: 0 for key in TYPE_KEYWORDS}
    for research_type, keywords in TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text:
                scores[research_type] += 1

    # Strong signals should beat generic product words like "产品线".
    if any(k in text for k in ["上市公司", "财报", "年报", "季报", "公告", "营收", "净利润", "管理层", "供应链", "生产基地"]):
        scores["company"] += 4
    if any(k in text for k in ["是否属实", "真假", "传闻", "rumor"]):
        scores["controversy"] += 3
    if any(k in text for k in ["act", "法案", "条例", "合规要求"]):
        scores["policy"] += 3
    if any(k in text for k in ["vs", "对比", "区别", "替代", "pricing"]):
        scores["product"] += 3
    if "产品线" in text and scores["company"] > 0:
        scores["product"] = max(0, scores["product"] - 1)
    return scores


def detect_research_type(topic: str, focus: list | None = None) -> str:
    """Detect the best report type for a broad research topic."""
    scores = score_research_types(topic, focus)
    best = max(TYPE_PRIORITY[:-1], key=lambda key: (scores.get(key, 0), -TYPE_PRIORITY.index(key)))
    if scores.get(best, 0) > 0:
        return best
    t = f"{topic} {' '.join(focus or [])}".lower()
    if any(k in t for k in ["争议", "传闻", "属实", "真假", "解散", "诉讼", "丑闻", "controversy", "lawsuit", "rumor"]):
        return "controversy"
    if any(k in t for k in ["政策", "监管", "法案", "合规", "影响", "act", "regulation", "policy"]):
        return "policy"
    if any(k in t for k in ["区别", "对比", "竞品", "产品", "价格", "功能", "cursor", "claude code", "alternatives", "pricing"]):
        return "product"
    if any(k in t for k in ["协议", "技术", "原理", "架构", "论文", "生态", "源码", "mcp", "paper", "github", "api", "sdk"]):
        return "technical"
    if any(k in t for k in ["公司", "战略", "融资", "财报", "估值", "anthropic", "openai", "xai", "meta", "google"]):
        return "company"
    if any(k in t for k in ["新闻", "日报", "动态", "近期", "最新", "本月", "today", "news", "daily", "brief"]):
        return "news"
    return "general"


def is_ai_daily_topic(topic: str) -> bool:
    """Compatibility helper for existing callers."""
    t = topic.lower()
    has_ai = any(k in t for k in ["ai", "人工智能", "大模型", "智能体", "agent"])
    has_news = any(k in t for k in ["新闻", "日报", "动态", "近期", "最新", "调研", "news", "daily", "brief"])
    return has_ai and has_news


def _is_ai_topic(topic: str) -> bool:
    t = topic.lower()
    return any(k in t for k in ["ai", "artificial intelligence", "agent"])


def _is_agent_topic(topic: str) -> bool:
    t = topic.lower()
    return any(k in t for k in ["agent", "agentic", "ai agent", "智能体"])


def generate_search_queries(topic: str, depth: int = 3, focus: list = None, incremental_since: str = None) -> list[str]:
    """Generate type-aware search queries. Year is always current."""
    depth = max(1, min(depth, 5))
    now = datetime.now()
    year = now.year
    date_cn = f"{now.year}年{now.month}月{now.day}日"
    month_cn = f"{now.year}年{now.month}月"
    date_en = now.strftime("%B %#d %Y")
    month_en = now.strftime("%B %Y")
    focus = focus or []
    research_type = detect_research_type(topic, focus)
    columns = TYPE_COLUMNS[research_type]

    queries = [
        f"{topic} {year}",
        f"{topic} 官方 权威 {year}",
        f"{topic} report analysis {year}",
    ]
    if research_type == "news":
        queries = [
            f"{date_cn} {topic}",
            f"{month_cn} {topic} 最新 新闻",
            f"{date_en} {topic} latest news",
            f"{month_en} {topic} this week news",
        ] + queries
    if research_type == "news" and any(k in topic.lower() for k in ["ai", "人工智能", "大模型", "智能体"]):
        queries.extend([
            f"site:openai.com AI model release {year}",
            f"site:anthropic.com Claude AI news {year}",
            f"site:blog.google AI {year}",
            f"site:deepmind.google AI research {year}",
            f"{topic} AI Agent 智能体 {year}",
        ])
        if any(k in topic.lower() for k in ["美国", "us ", "u.s.", "america", "american"]):
            queries.extend([
                f"site:reuters.com AI United States May {year}",
                f"site:apnews.com artificial intelligence US {year}",
                f"site:theverge.com AI May {year}",
                f"site:techcrunch.com AI May {year}",
                f"site:whitehouse.gov artificial intelligence {year}",
                f"site:nist.gov AI {year}",
                f"site:ftc.gov AI {year}",
                f"site:sec.gov AI {year}",
            ])
    for col in columns:
        queries.append(f"{topic} {col} {year}")

    hints = OFFICIAL_SOURCE_HINTS.get(research_type, [])
    for hint in hints:
        queries.append(f"{hint} {topic} {year}")

    if research_type == "news" and any(k in topic.lower() for k in ["ai", "人工智能", "大模型", "智能体"]):
        queries.extend([
            f"site:microsoft.com AI Copilot {year}",
            f"site:nvidia.com AI GPU data center {year}",
            f"site:arxiv.org artificial intelligence {year}",
        ])

    if research_type == "company":
        queries.extend([
            f"{topic} 年报 财报 营收 净利润 {year}",
            f"{topic} 交易所 公告 投资者关系 {year}",
            f"{topic} 市场份额 竞争格局 行业报告 {year}",
            f"site:cninfo.com.cn {topic} 年报",
            f"site:szse.cn {topic} 公告",
            f"site:sse.com.cn {topic} 公告",
        ])

    if incremental_since:
        queries.append(f"{topic} after:{incremental_since[:10]}")
    for item in focus:
        queries.append(f"{topic} {item} {year}")

    if research_type == "news" and _is_ai_topic(topic):
        if _is_agent_topic(topic):
            priority_queries = [
                f"{date_en} AI agent latest news",
                f"{date_cn} AI Agent 智能体 最新新闻",
                f"AI agent news this week {month_en}",
                f"AI agent latest news {year} official announcement",
                f"agentic AI enterprise deployment {year} Reuters",
                f"AI agents tools workflow automation {year} The Verge TechCrunch",
                f"site:openai.com agent workflow automation {year}",
                f"site:anthropic.com Claude agent computer use {year}",
                f"site:blog.google AI agents Gemini agent {year}",
                f"site:microsoft.com AI agents Copilot {year}",
                f"site:salesforce.com Agentforce {year}",
                f"site:databricks.com AI agents report {year}",
            ]
        else:
            priority_queries = [
                f"{date_en} AI news artificial intelligence",
                f"{date_cn} 人工智能 最新新闻 大模型 芯片 监管",
                f"AI news this week {month_en} Reuters OpenAI Anthropic Google",
                f"AI news {year} Reuters artificial intelligence",
                f"AI latest developments {year} model release regulation chips",
                f"AI Agent intelligent agent news {year}",
                f"site:openai.com AI release {year}",
                f"site:anthropic.com Claude AI news {year}",
                f"site:blog.google AI {year}",
                f"site:deepmind.google AI research {year}",
                f"site:microsoft.com AI Copilot {year}",
                f"site:nvidia.com AI GPU data center {year}",
            ]
        queries = priority_queries + queries

    if research_type == "product":
        product_text = topic.lower()
        priority_queries = []
        if "cursor" in product_text:
            priority_queries.extend([
                f"site:cursor.com Cursor pricing features {year}",
                f"site:docs.cursor.com Cursor agent docs {year}",
                f"site:cursor.com Cursor changelog agent composer {year}",
            ])
        if "claude code" in product_text or "claude" in product_text:
            priority_queries.extend([
                f"site:anthropic.com Claude Code {year}",
                f"site:docs.anthropic.com Claude Code docs {year}",
                f"site:support.anthropic.com Claude Code pricing {year}",
            ])
        if priority_queries:
            priority_queries.extend([
                f"{topic} official docs pricing features {year}",
                f"{topic} developer workflow comparison {year}",
            ])
            queries = priority_queries + queries

    seen = set()
    result = []
    for q in queries:
        normalized = q.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if research_type == "company":
        priority = [
            f"{topic} 年报 财报 营收 净利润 {year}",
            f"{topic} 交易所 公告 投资者关系 {year}",
            f"{topic} 市场份额 竞争格局 行业报告 {year}",
            f"site:cninfo.com.cn {topic} 年报",
            f"site:szse.cn {topic} 公告",
            f"site:sse.com.cn {topic} 公告",
        ]
        merged = []
        for q in priority + result:
            if q not in merged:
                merged.append(q)
        result = merged
    return result[:DEPTH_BUDGETS[depth]["query_count"]]


def get_budget(depth: int) -> dict:
    """Get the budget dict for a given depth, clamped to valid range."""
    return DEPTH_BUDGETS.get(max(1, min(depth, 5)), DEPTH_BUDGETS[3])
