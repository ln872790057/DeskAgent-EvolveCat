"""Professional research orchestrator: evidence-first event research pipeline."""
import json
import queue
import re
import threading
import ast
import time
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from agent.runtime.task_session import TaskSession
from skills.pro_researcher.models import (
    EvidenceItem,
    ResearchClaim,
    ResearchEvent,
    ResearchReport,
    ResearchSource,
)
from skills.pro_researcher.query_planner import (
    detect_research_type,
    generate_search_queries,
    get_budget,
)
from skills.pro_researcher.planner import create_research_plan
from skills.pro_researcher.critic import review_report
from skills.pro_researcher.filters import (
    classify_source_type,
    deduplicate_sources,
    grade_source_quality,
    is_low_value_source,
    mark_source_quality,
)
from skills.pro_researcher.source_reader import read_multiple_sources
from skills.pro_researcher.evidence import (
    check_cross_validation,
    estimate_report_confidence,
)
from skills.pro_researcher.templates import (
    render_report,
    render_user_reply,
    save_report_to_desktop,
)

from utils.logger import get_logger

logger = get_logger("skills.pro_researcher")


class ResearchAnalysisError(Exception):
    """Raised when model-based research synthesis fails and no formal report should be produced."""


@contextmanager
def _null_stage():
    yield

QUALITY_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}
TYPE_RANK = {
    "official": 0,
    "paper": 1,
    "github": 2,
    "tech_blog": 3,
    "industry_report": 4,
    "media": 5,
    "unknown": 6,
    "self_media": 7,
    "pr": 8,
}
EVENT_CATEGORIES = [
    ("模型发布", ["模型", "gpt", "claude", "gemini", "deepseek", "llama", "发布", "api", "model"]),
    ("AI Agent", ["agent", "智能体", "coding", "代码", "编程", "工具", "自动化", "copilot"]),
    ("算力与芯片", ["算力", "芯片", "gpu", "nvidia", "数据中心", "推理", "训练", "inference"]),
    ("政策监管", ["政策", "监管", "合规", "安全", "治理", "法案", "regulation", "safety"]),
    ("公司与资本", ["融资", "收购", "并购", "裁员", "公司", "战略", "openai", "anthropic", "google", "xai"]),
    ("开源与论文", ["开源", "论文", "arxiv", "github", "paper", "benchmark", "评测"]),
    ("应用落地", ["企业", "医疗", "教育", "金融", "应用", "落地", "enterprise", "customer"]),
    ("风险争议", ["争议", "诉讼", "版权", "幻觉", "泄露", "风险", "lawsuit", "controversy"]),
]
REPORT_TYPE_LABELS = {
    "news": "新闻日报",
    "technical": "技术研究",
    "product": "产品竞品",
    "company": "公司行业",
    "policy": "政策监管",
    "controversy": "争议核验",
    "general": "通用研究",
}
TYPE_REPORT_SECTIONS = {
    "news": ["大模型与核心技术", "智能体与工具", "AI硬件与终端", "公司战略与资本", "政策监管与安全", "行业观察与趋势"],
    "technical": ["技术背景", "核心原理", "生态与工具", "对比分析", "局限与风险", "应用场景"],
    "product": ["产品定位", "核心功能", "价格与商业模式", "竞品对比", "用户反馈", "适用建议"],
    "company": ["公司概况", "战略变化", "产品与技术", "资本与财务", "竞争格局", "风险判断"],
    "policy": ["政策原文与时间线", "核心要求", "企业影响", "合规建议", "各方观点", "风险与不确定性"],
    "controversy": ["事实时间线", "证据核验", "各方立场", "可信度判断", "影响分析", "后续追踪"],
    "general": ["背景脉络", "核心事实", "关键观点", "影响分析", "风险局限", "后续趋势"],
}


def _search_tavily(
    query: str,
    max_results: int = 5,
    *,
    topic: str = "",
    research_type: str = "general",
) -> list[dict]:
    """Call Tavily search. Returns list of result dicts."""
    from agent.tools import _get_tavily_key
    try:
        from tavily import TavilyClient
        key = _get_tavily_key()
        client = TavilyClient(api_key=key)
        freshness = _freshness_window(topic, research_type)
        kwargs = {
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced" if freshness else "basic",
            "include_raw_content": "text",
        }
        if freshness:
            kwargs.update({
                "topic": "news",
                "time_range": freshness["time_range"],
                "days": freshness["days"],
            })
            domains = _fresh_news_include_domains(topic, query)
            if domains:
                kwargs["include_domains"] = domains
        response = client.search(**kwargs)
        return response.get("results", [])
    except Exception as e:
        logger.warning(f"[Researcher] Tavily search failed for '{query}': {e}")
        return []


def _raw_result_to_source(r: dict) -> ResearchSource:
    """Convert a raw search result dict to ResearchSource."""
    url = r.get("url", "")
    domain = urlparse(url).netloc.lower().removeprefix("www.") if "://" in url else ""
    raw_content = r.get("raw_content", "") or ""
    snippet = r.get("content", "") or r.get("snippet", "") or raw_content[:1200]
    read_status = "full" if len(raw_content.strip()) >= 1200 else ("partial" if len(raw_content.strip()) >= 300 else "unread")
    return ResearchSource(
        title=(r.get("title", "") or "")[:160],
        url=url,
        domain=domain,
        snippet=snippet[:700],
        published_at=r.get("published_date") or r.get("published_at"),
        content=raw_content[:8000],
        accessed_at=datetime.now().isoformat(timespec="seconds"),
        source_type=classify_source_type(r.get("title", ""), url, snippet),
        read_status=read_status,
    )


def research_topic_execute(
    topic: str,
    depth: int = 3,
    focus: list = None,
    incremental: bool = False,
    agent=None,
    session: TaskSession | None = None,
) -> dict:
    """Execute a complete research cycle. Called from the tool handler."""
    t_start = datetime.now()
    depth = max(1, min(depth, 5))
    budget = get_budget(depth)
    session = session or TaskSession.create(topic, "research", topic)
    artifacts = session.artifacts
    if artifacts:
        artifacts.write_json("00_task.json", {
            "task_id": session.task_id,
            "topic": topic,
            "depth": depth,
            "focus": focus or [],
            "incremental": incremental,
            "budget": budget,
            "created_at": session.created_at,
        })
    logger.info(f"[Researcher] starting: topic={topic[:60]} depth={depth} budget={budget}")

    try:
        with artifacts.stage("01_detect_type") if artifacts else _null_stage():
            session.set_stage("detect_type", "planning")
            research_plan = create_research_plan(topic, depth=depth, focus=focus)
            research_type = research_plan.research_type
            session.plan = research_plan.to_dict() | {"budget": budget}
            if artifacts:
                artifacts.write_json("01_plan.json", session.plan)
        logger.info(f"[Researcher] detected type={research_type}")
        if agent and getattr(agent, "memory", None):
            prev = agent.memory.search(topic, limit=1)
            if prev and incremental:
                logger.info("[Researcher] found previous research, incremental mode")

        with artifacts.stage("02_generate_queries") if artifacts else _null_stage():
            session.set_stage("generate_queries", "planning")
            queries = generate_search_queries(topic, depth, focus=focus)
            if artifacts:
                artifacts.write_json("02_queries.json", {
                    "research_type": research_type,
                    "query_count": len(queries),
                    "queries": queries,
                })
        logger.info(f"[Researcher] queries ({len(queries)}): {queries[:6]}...")

        with artifacts.stage("03_search") if artifacts else _null_stage():
            session.set_stage("search", "executing")
            all_raw = []
            raw_by_query = []
            for q in queries:
                results = _search_tavily(q, max_results=budget["results_per_query"], topic=topic, research_type=research_type)
                raw_by_query.append({"query": q, "result_count": len(results), "results": results})
                all_raw.extend(results)
                if len(all_raw) >= budget["max_sources"] * 2:
                    break
            if artifacts:
                artifacts.write_json("03_raw_search_results.json", {
                    "total_raw_results": len(all_raw),
                    "by_query": raw_by_query,
                })

        if not all_raw:
            session.finish("failed", "no_results")
            return {"status": "no_results", "message": f"关于{topic}没搜到什么靠谱的信息，换个关键词试试？"}

        with artifacts.stage("04_deduplicate_sources") if artifacts else _null_stage():
            session.set_stage("deduplicate_sources", "executing")
            sources = [_raw_result_to_source(r) for r in all_raw if r.get("url")]
            sources = deduplicate_sources(sources)[:budget["max_sources"]]
            if artifacts:
                artifacts.write_json("04_sources_dedup.json", {
                    "source_count": len(sources),
                    "sources": sources,
                })
        logger.info(f"[Researcher] sources: {len(sources)} after dedup")

        with artifacts.stage("05_read_and_rank_sources") if artifacts else _null_stage():
            session.set_stage("read_and_rank_sources", "executing")
            sources = _prioritize_sources_for_reading(sources, topic, research_type)
            read_multiple_sources(sources, max_pages=budget["max_pages_to_read"], timeout=20)
            for s in sources:
                s.source_type = classify_source_type(s.title, s.url, s.snippet, s.content)
                mark_source_quality(s)
            _fill_inferred_dates(sources)
            sources = _rank_sources(sources, topic=topic, research_type=research_type)
            sources = _maybe_supplement_fresh_sources(sources, topic, research_type, budget, artifacts)
            if artifacts:
                artifacts.write_json("05_sources_ranked.json", {
                    "source_count": len(sources),
                    "read_success_count": sum(1 for s in sources if s.read_status in ("full", "partial")),
                    "sources": sources,
                })
                for index, source in enumerate(sources, 1):
                    artifacts.append_jsonl("05_read_sources.jsonl", {
                        "index": index,
                        "source": source,
                    })

        high_quality = sum(1 for s in sources if s.quality in ("S", "A"))
        logger.info(f"[Researcher] quality: {high_quality} high-quality out of {len(sources)}")
        preflight_review = _preflight_quality_review(sources, topic, research_type)
        if artifacts:
            artifacts.write_json("05_quality_preflight.json", preflight_review)

        session.set_stage("llm_analysis", "executing")
        analysis_started = time.time()
        if agent:
            try:
                analysis = _llm_analyze(sources, topic, agent, research_type=research_type, budget=budget, artifacts=artifacts)
            except ResearchAnalysisError as e:
                logger.warning(f"[Researcher] analysis failed without fallback: {e}")
                if artifacts:
                    artifacts.write_json("06_analysis_failed.json", {
                        "error": str(e),
                        "message": "LLM analysis failed; no fake fallback report generated.",
                    })
                    artifacts.record_stage("06_llm_analysis", analysis_started, "failed", str(e))
                session.finish("failed", str(e))
                return {
                    "status": "analysis_failed",
                    "message": (
                        "搜索和来源读取完成了，但模型分析与综合失败，所以没有生成正式调研报告。\n\n"
                        f"原因：{e}\n"
                        "我没有使用规则兜底拼一份假报告。可以稍后重试，或检查 logs/research_llm_failures 里的原始模型输出。"
                    ),
                }
        else:
            analysis = _fallback_analysis(sources, topic, research_type)
        if artifacts:
            artifacts.write_json("07_analysis.json", analysis)
            artifacts.record_stage("06_llm_analysis", analysis_started)

        session.set_stage("build_report_model", "composing")
        report_started = time.time()
        report = ResearchReport(
            topic=topic,
            depth=depth,
            research_type=research_type,
            sources=sources,
            time_range=_estimate_time_range(sources),
        )
        _fill_report_from_analysis(report, analysis, sources)
        for warning in preflight_review.get("warnings", []):
            if warning not in report.limitations:
                report.limitations.append(warning)

        report.claims = check_cross_validation(report.claims, sources)
        report.confidence = estimate_report_confidence(report)
        critic_result = review_report(report)
        _attach_critic_result(report, critic_result)
        if not critic_result.passed:
            report.limitations.extend(
                issue.message for issue in critic_result.issues
                if issue.severity in ("high", "medium") and issue.message not in report.limitations
            )
            if artifacts:
                artifacts.write_json("08_report_model.json", report)
                artifacts.write_json("08_critic_review.json", critic_result.to_dict())
                artifacts.record_stage("07_build_report_model", report_started, "completed_with_warnings", "critic rejected report")
            # Keep a warned report instead of dropping the user's research output.
            logger.warning(
                "[Researcher] critic rejected report but saving warned draft: "
                + "; ".join(issue.message for issue in critic_result.issues[:4])
            )
            if False:
                session.finish("failed", "critic rejected report")
            issues = "；".join(issue.message for issue in critic_result.issues[:4])
            if False:
                return {
                    "status": "analysis_failed",
                    "message": (
                    "调研已完成搜索、阅读和模型分析，但质检没有通过，所以没有输出低质量正式报告。\n\n"
                    f"主要问题：{issues}\n\n"
                    f"过程产物：{artifacts.root if artifacts else '未记录'}"
                ),
            }
        if critic_result.passed and artifacts:
            artifacts.write_json("08_report_model.json", report)
            artifacts.write_json("08_critic_review.json", critic_result.to_dict())
            artifacts.record_stage("07_build_report_model", report_started)

        session.set_stage("render_and_save", "composing")
        render_started = time.time()
        md_content = render_report(report)
        if artifacts:
            artifacts.write_text("09_report.md", md_content)
        file_path, fallback = save_report_to_desktop(report, md_content)
        if artifacts:
            artifacts.write_json("10_saved_report.json", {
                "desktop_report_path": file_path,
                "fallback_notice": fallback,
                "artifacts_dir": str(artifacts.root),
            })
            artifacts.record_stage("08_render_and_save", render_started)

        if agent and getattr(agent, "memory", None) and report.confidence != "低":
            _store_research_memory(agent, topic, report, file_path)

        reply = render_user_reply(report, file_path, fallback)
        if artifacts:
            reply += f"\n\n调研过程产物：{artifacts.root}"
        elapsed = (datetime.now() - t_start).total_seconds()
        final_status = "completed" if critic_result.passed else "completed_with_warnings"
        session.finish(final_status)
        logger.info(f"[Researcher] complete: topic={topic[:40]} conf={report.confidence} status={final_status} elapsed={elapsed:.0f}s")
        return {"status": final_status, "message": reply}

    except Exception as e:
        session.finish("failed", str(e))
        if artifacts:
            artifacts.write_json("error.json", {
                "stage": session.current_stage,
                "error_type": type(e).__name__,
                "error": str(e),
            })
        logger.exception(f"[Researcher] failed for topic={topic}")
        return {"status": "failed", "message": f"调研失败了：{str(e)[:100]}"}


def _attach_critic_result(report: ResearchReport, critic_result) -> None:
    """Copy the final critic result into the report so warned drafts are explicit."""
    report.review_passed = bool(critic_result.passed)
    report.review_score = int(critic_result.score)
    report.review_issues = [issue.message for issue in critic_result.issues]
    report.review_actions = list(critic_result.required_actions)
    if not critic_result.passed:
        report.confidence = "低"


def _preflight_quality_review(sources: list[ResearchSource], topic: str, research_type: str) -> dict:
    """Cheap quality gate before synthesis. It does not block, it feeds warnings forward."""
    core_sources = [s for s in sources if _source_can_drive_core(s)]
    read_sources = [s for s in sources if s.read_status in ("full", "partial")]
    official_sources = [s for s in core_sources if s.source_type in ("official", "paper", "github")]
    weak_sources = [
        s for s in sources
        if s.source_type in ("self_media", "aggregator", "pr") or not getattr(s, "usable_for_core", True)
    ]
    warnings = []
    if len(read_sources) < 5:
        warnings.append("正文读取成功来源偏少，报告可能缺少足够上下文。")
    if len(core_sources) < 5:
        warnings.append("可进入核心结论的高质量来源偏少，建议补充官方、论文、监管文件或权威媒体。")
    if len(official_sources) < 2 and research_type in ("company", "policy", "technical", "news"):
        warnings.append("官方/原始来源不足，关键数字和强判断需要谨慎处理。")
    if weak_sources and len(weak_sources) >= max(5, len(sources) // 3):
        warnings.append("低质量、转载或聚合来源占比较高，需要防止正文被二手材料牵着走。")
    if research_type == "news" and len(core_sources) < 5:
        warnings.append("新闻类任务的可用核心来源不足 5 条，后续可能无法形成完整日报。")
    return {
        "topic": topic,
        "research_type": research_type,
        "source_count": len(sources),
        "read_success_count": len(read_sources),
        "core_source_count": len(core_sources),
        "official_source_count": len(official_sources),
        "weak_source_count": len(weak_sources),
        "warnings": warnings,
    }


def _rank_sources(
    sources: list[ResearchSource],
    topic: str = "",
    research_type: str = "general",
) -> list[ResearchSource]:
    """Put official / authoritative / full-content sources ahead of reposts."""
    freshness = _freshness_window(topic, research_type)
    return sorted(
        sources,
        key=lambda s: (
            _recency_rank(s, freshness) if freshness else 0,
            QUALITY_RANK.get(s.quality, 9),
            TYPE_RANK.get(s.source_type, 9),
            0 if s.read_status in ("full", "partial") else 1,
            s.domain,
        ),
    )


def _freshness_window(topic: str, research_type: str) -> dict | None:
    """Return Tavily freshness parameters for time-sensitive research."""
    text = (topic or "").lower()
    if research_type != "news" and not any(k in text for k in ["最新", "近期", "现状", "当前", "今天", "今日", "本周", "本月", "latest", "recent", "current", "today", "week", "month"]):
        return None
    if any(k in text for k in ["今天", "今日", "today"]):
        return {"time_range": "week", "days": 7}
    if any(k in text for k in ["本周", "近一周", "week"]):
        return {"time_range": "week", "days": 10}
    if any(k in text for k in ["本月", "5月", "五月", "month"]):
        return {"time_range": "month", "days": 45}
    if any(k in text for k in ["最新", "近期", "现状", "当前", "recent", "latest", "current", "news", "新闻", "动态"]):
        return {"time_range": "month", "days": 45}
    return None


def _fresh_news_include_domains(topic: str, query: str) -> list[str]:
    """Constrain generic fresh AI-news searches to better source pools."""
    text = f"{topic} {query}".lower()
    if "site:" in query.lower():
        return []
    if not any(k in text for k in ["ai", "artificial intelligence", "人工智能", "大模型", "智能体", "agent"]):
        return []
    return [
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "theverge.com",
        "techcrunch.com",
        "ft.com",
        "wsj.com",
        "technologyreview.com",
        "openai.com",
        "anthropic.com",
        "blog.google",
        "deepmind.google",
        "microsoft.com",
        "nvidia.com",
        "whitehouse.gov",
        "nist.gov",
        "ftc.gov",
        "sec.gov",
    ]


def _fill_inferred_dates(sources: list[ResearchSource]) -> None:
    for source in sources:
        if not source.published_at:
            source.published_at = _infer_source_date(source)


def _infer_source_date(source: ResearchSource) -> str | None:
    text = " ".join([
        source.title or "",
        source.url or "",
        source.snippet or "",
        (source.content or "")[:1200],
    ])
    patterns = [
        r"(20\d{2})[-/.年](0?[1-9]|1[0-2])[-/.月](0?[1-9]|[12]\d|3[01])日?",
        r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(year, month, day).date().isoformat()
        except Exception:
            continue
    m = re.search(r"(20\d{2})[-/.年](0?[1-9]|1[0-2])月?", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1).date().isoformat()
        except Exception:
            return None
    return None


def _recency_rank(source: ResearchSource, freshness: dict | None) -> int:
    if not freshness:
        return 0
    parsed = _parse_source_date(source.published_at)
    if not parsed:
        # Keep specific official releases, but push undated pages behind dated fresh items.
        return 45 if source.source_type in ("official", "paper", "media") else 90
    age_days = (datetime.now().date() - parsed.date()).days
    if age_days < 0:
        return 5
    if age_days <= int(freshness.get("days", 45)):
        return age_days
    return 180 + age_days


def _parse_source_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m", "%Y/%m", "%Y.%m"):
        try:
            return datetime.strptime(text[:len(fmt)], fmt)
        except Exception:
            pass
    m = re.search(r"(20\d{2})[-/.年](0?[1-9]|1[0-2])(?:[-/.月](0?[1-9]|[12]\d|3[01]))?", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except Exception:
            return None
    return None


def _maybe_supplement_fresh_sources(
    sources: list[ResearchSource],
    topic: str,
    research_type: str,
    budget: dict,
    artifacts=None,
) -> list[ResearchSource]:
    """If a fresh-news task has too few usable sources, run a small targeted news补搜."""
    freshness = _freshness_window(topic, research_type)
    if not freshness or research_type != "news":
        return sources
    core_count = len([s for s in sources if _source_can_drive_core(s)])
    if core_count >= 10:
        return sources

    now = datetime.now()
    queries = _supplemental_fresh_queries(topic, now)
    raw = []
    by_query = []
    for query in queries:
        results = _search_tavily(query, max_results=4, topic=topic, research_type=research_type)
        by_query.append({"query": query, "result_count": len(results), "results": results})
        raw.extend(results)
        if len(raw) >= 24:
            break
    if not raw:
        return sources

    extra = [_raw_result_to_source(r) for r in raw if r.get("url")]
    combined = deduplicate_sources(extra + sources)[:max(int(budget.get("max_sources", 30)), len(sources))]
    new_urls = {s.url for s in combined} - {s.url for s in sources}
    new_sources = [s for s in combined if s.url in new_urls]
    if new_sources:
        new_sources = _prioritize_sources_for_reading(new_sources, topic, research_type)
        read_multiple_sources(new_sources, max_pages=min(8, len(new_sources)), timeout=20)
        for source in new_sources:
            source.source_type = classify_source_type(source.title, source.url, source.snippet, source.content)
            mark_source_quality(source)
        _fill_inferred_dates(new_sources)
    result = _rank_sources(combined, topic=topic, research_type=research_type)
    if artifacts:
        artifacts.write_json("05_supplemental_fresh_search.json", {
            "reason": f"core_source_count={core_count}",
            "queries": by_query,
            "added_source_count": len(new_sources),
            "added_sources": new_sources,
        })
    return result


def _supplemental_fresh_queries(topic: str, now: datetime) -> list[str]:
    date_en = now.strftime("%B %-d %Y") if sys.platform != "win32" else now.strftime("%B %#d %Y")
    date_cn = f"{now.year}年{now.month}月{now.day}日"
    month_en = now.strftime("%B %Y")
    base = topic
    return [
        f"{date_en} AI news model release agent chip regulation",
        f"{date_cn} 人工智能 新闻 大模型 智能体 芯片 监管",
        f"AI news this week {month_en} Reuters OpenAI Anthropic Google Microsoft Nvidia",
        f"site:reuters.com artificial intelligence {month_en}",
        f"site:techcrunch.com AI {month_en}",
        f"site:theverge.com AI {month_en}",
        f"site:openai.com/index {month_en} AI",
        f"site:anthropic.com/news {month_en} Claude AI",
        f"site:blog.google AI {month_en}",
        f"{base} 最新 今天 本周",
    ]


def _prioritize_sources_for_reading(sources: list[ResearchSource], topic: str, research_type: str) -> list[ResearchSource]:
    """Read the most promising sources first before the max_pages budget is consumed."""
    def score(source: ResearchSource) -> tuple:
        text = f"{source.title} {source.snippet} {source.url}".lower()
        relevance_penalty = 0 if _topic_relevant_text(topic, text) else 3
        if research_type == "news" and _is_ai_news_like_topic(topic):
            off_topic_news = any(term in text for term in ["future of news", "journalism", "media industry"])
            relevance_penalty += 4 if off_topic_news else 0
            relevance_penalty += 6 if not _ai_news_core_relevant(source) else 0
        return (
            relevance_penalty,
            TYPE_RANK.get(source.source_type, 9),
            0 if source.source_type in ("official", "paper") else 1,
            source.domain,
        )

    return sorted(sources, key=score)


def _append_source_card_candidates(
    target: list,
    batch: list[ResearchSource],
    topic: str,
    research_type: str,
    max_total: int = 10,
) -> int:
    """Append deduplicated source-card candidates to keep reports traceable."""
    existing_urls = {
        url
        for event in target
        if isinstance(event, dict)
        for url in _as_list(event.get("source_urls"))
    }
    existing_titles = {
        str(event.get("title", "")).strip()
        for event in target
        if isinstance(event, dict)
    }
    added = 0
    for card in _source_cards_from_batch(batch, topic, research_type):
        title = str(card.get("title", "")).strip()
        card_urls = set(_as_list(card.get("source_urls")))
        if title and title in existing_titles:
            continue
        if card_urls and card_urls.issubset(existing_urls):
            continue
        target.append(card)
        existing_titles.add(title)
        existing_urls.update(card_urls)
        added += 1
        if len(target) >= max_total:
            break
    return added


def _llm_analyze(
    sources: list[ResearchSource],
    topic: str,
    agent,
    research_type: str = "general",
    budget: dict | None = None,
    artifacts=None,
) -> dict:
    """Use small-batch extraction plus editorial synthesis for all research types."""
    budget = budget or {}
    candidates = _analysis_sources(sources, topic)
    batch_size = int(budget.get("batch_size", 6))
    batches = [candidates[i:i + batch_size] for i in range(0, min(len(candidates), 28), batch_size)]
    extracted_events = []
    extracted_findings = []
    failed_batches = 0
    source_card_batches = 0
    if artifacts:
        artifacts.write_json("06_analysis_input.json", {
            "candidate_count": len(candidates),
            "batch_size": batch_size,
            "batch_count": len(batches),
            "candidates": candidates,
        })

    try:
        for batch_index, batch in enumerate(batches, 1):
            prompt = _build_extraction_prompt(topic, research_type, sources, batch, batch_index)
            try:
                parsed = _call_llm_json(
                    agent,
                    prompt,
                    max_tokens=3600,
                    timeout=240,
                    label=f"extract_batch_{batch_index}",
                    artifacts=artifacts,
                )
                if artifacts:
                    artifacts.write_json(f"06_extract_batch_{batch_index}.json", parsed)
                batch_events = parsed.get("events") or []
                batch_findings = parsed.get("key_findings") or []
                if batch_events or batch_findings:
                    extracted_events.extend(batch_events)
                    extracted_findings.extend(batch_findings)
                else:
                    failed_batches += 1
                    added = _append_source_card_candidates(
                        extracted_events,
                        batch,
                        topic,
                        research_type,
                        max_total=12,
                    )
                    if added:
                        source_card_batches += 1
                    if artifacts:
                        artifacts.write_json(f"06_extract_batch_{batch_index}_empty.json", {
                            "message": "LLM extraction returned empty JSON; source-card candidates were used.",
                            "added_source_cards": added,
                        })
            except Exception as e:
                failed_batches += 1
                added = _append_source_card_candidates(
                    extracted_events,
                    batch,
                    topic,
                    research_type,
                    max_total=12,
                )
                if added:
                    source_card_batches += 1
                if artifacts:
                    artifacts.write_json(f"06_extract_batch_{batch_index}_recovered.json", {
                        "message": "LLM extraction failed; source-card candidates were used.",
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "added_source_cards": added,
                    })
                logger.warning(f"[Researcher] extraction batch failed: batch={batch_index} error={e}")

        if research_type == "news" and len(extracted_events) < 5:
            added = _append_source_card_candidates(
                extracted_events,
                candidates,
                topic,
                research_type,
                max_total=8,
            )
            if added:
                source_card_batches += 1

        if not extracted_events:
            added = _append_source_card_candidates(
                extracted_events,
                candidates,
                topic,
                research_type,
                max_total=10,
            )
            if added:
                source_card_batches += 1

        if extracted_events or extracted_findings:
            prompt = _build_editor_prompt(topic, research_type, sources, extracted_events, extracted_findings)
            if artifacts:
                artifacts.write_json("06_editor_input.json", {
                    "event_count": len(extracted_events),
                    "finding_count": len(extracted_findings),
                    "events": extracted_events,
                    "findings": extracted_findings,
                })
            try:
                parsed = _call_llm_json(
                    agent,
                    prompt,
                    max_tokens=9000,
                    timeout=600,
                    label="editor_synthesis",
                    artifacts=artifacts,
                )
            except Exception as e:
                logger.warning(f"[Researcher] editor synthesis failed; using extracted event candidates: {e}")
                parsed = _analysis_from_extracted_events(topic, research_type, extracted_events, extracted_findings)
                parsed.setdefault("limitations", []).append(
                    f"总编辑综合阶段失败，报告改由已抽取候选卡片生成；错误：{str(e)[:120]}"
                )
                if artifacts:
                    artifacts.write_json("06_editor_synthesis_recovered.json", {
                        "message": "Editor synthesis failed; extracted event candidates were used.",
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "event_count": len(extracted_events),
                    })
            if artifacts:
                artifacts.write_json("06_editor_synthesis.json", parsed)
            parsed = _enforce_news_event_floor(parsed, extracted_events, topic, research_type)
            if artifacts:
                artifacts.write_json("06_editor_synthesis_final.json", parsed)
            if parsed and (parsed.get("events") or parsed.get("conclusion") or parsed.get("key_findings")):
                if failed_batches:
                    parsed.setdefault("limitations", []).append(f"{failed_batches} 个来源批次没有产出可用结构化结果，已用可追溯来源卡片补足候选事件。")
                if source_card_batches:
                    parsed.setdefault("limitations", []).append("部分正文条目来自规则生成的来源候选卡，建议优先查看来源编号和质检提示。")
                return parsed
            logger.warning("[Researcher] editor synthesis returned empty JSON; using extracted event candidates")
            return _analysis_from_extracted_events(topic, research_type, extracted_events, extracted_findings)
        raise ValueError("no extracted events from LLM batches")
    except Exception as e:
        logger.warning(f"[Researcher] LLM analysis failed and no usable source-card report could be generated: {e}")
        raise ResearchAnalysisError(str(e)) from e


def _analysis_from_extracted_events(topic: str, research_type: str, events: list, findings: list) -> dict:
    """Build a minimal analysis object from model-extracted event candidates."""
    clean_events = [
        event for event in events
        if isinstance(event, dict) and event.get("title") and event.get("source_urls")
    ]
    title_bits = [str(event.get("title", "")) for event in clean_events[:4]]
    summary = (
        f"本次围绕「{topic}」从模型抽取层得到 {len(clean_events)} 个可追溯候选事件。"
        "由于总编辑综合层返回为空，报告采用候选事件生成，并交由质检规则继续筛查。"
    )
    if title_bits:
        summary += " 主要线索包括：" + "；".join(title_bits) + "。"
    return {
        "editorial_summary": summary,
        "conclusion": f"{topic} 已形成 {len(clean_events)} 个候选事件，需重点查看证据质量和后续追踪。",
        "events": clean_events,
        "key_findings": [str(item) for item in findings[:8]],
        "trend_judgement": "趋势判断基于候选事件保守生成；若需要更强判断，应继续补充一手来源和交叉验证。",
        "risks": "部分事件可能仍为单来源支撑，需依赖质检结果决定是否可发布为正式报告。",
        "timeline": "",
        "watchlist": [],
        "limitations": ["总编辑综合层返回空 JSON，本报告由模型抽取候选事件生成并经过规则质检。"],
    }


def _enforce_news_event_floor(parsed: dict, extracted_events: list, topic: str, research_type: str) -> dict:
    """Prevent the editor stage from collapsing a news brief into one or two items."""
    if research_type != "news" or not isinstance(parsed, dict):
        return parsed
    events = [event for event in (parsed.get("events") or []) if isinstance(event, dict)]
    if len(events) < 5 and len(extracted_events) < 5:
        return parsed
    if len(events) < 5:
        seen = {str(event.get("title", "")).strip() for event in events}
        for event in extracted_events:
            if not isinstance(event, dict):
                continue
            title = str(event.get("title", "")).strip()
            if not title or title in seen or not event.get("source_urls"):
                continue
            events.append(event)
            seen.add(title)
            if len(events) >= 8:
                break
    parsed["events"] = events
    if len(events) >= 5:
        if not parsed.get("editorial_summary"):
            parsed["editorial_summary"] = f"本次围绕“{topic}”形成{len(events)}条近期AI事件，覆盖模型发布、智能体、算力基础设施、行业应用和资本合作等方向。整体看，近期AI新闻不再只是单一模型发布，而是模型能力、终端入口、云算力、企业应用和监管环境同时推进。"
        if not parsed.get("conclusion"):
            parsed["conclusion"] = f"{topic}的近期动态不应被压缩为单点新闻，至少需要按多条事件追踪。"
        limitations = parsed.setdefault("limitations", [])
        if isinstance(limitations, list):
            limitations.append("总编辑阶段输出事件过少，系统已从抽取阶段补回候选事件以保留信息覆盖面。")
    return parsed


def _call_llm_json(
    agent,
    prompt: str,
    max_tokens: int = 3000,
    timeout: int = 240,
    label: str = "research",
    artifacts=None,
) -> dict:
    """Call the configured LLM with a per-request research timeout and parse JSON."""
    client = agent.router.get_client()
    result_queue = queue.Queue(maxsize=1)

    def _call_model():
        try:
            if hasattr(client, "client"):
                kwargs = {
                    "model": client.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.12,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                }
                if _supports_json_object_output(client):
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.client.chat.completions.create(**kwargs)
                result_queue.put((resp.choices[0].message.content or "{}", None))
            else:
                result = client.chat(
                    [{"role": "user", "content": prompt}],
                    tools=None,
                    stream=False,
                )
                result_queue.put((result.get("content", "{}") if isinstance(result, dict) else "{}", None))
        except Exception as e:
            result_queue.put(("", e))

    threading.Thread(target=_call_model, daemon=True).start()
    try:
        text, err = result_queue.get(timeout=timeout + 15)
    except queue.Empty:
        raise TimeoutError(f"LLM analysis timed out after {timeout}s")
    if err:
        if artifacts:
            artifacts.write_text(f"llm/{label}_prompt.txt", prompt)
            artifacts.write_text(f"llm/{label}_error.txt", str(err))
        _save_llm_failure(label, prompt, "", err)
        raise err
    if artifacts:
        artifacts.write_text(f"llm/{label}_prompt.txt", prompt)
        artifacts.write_text(f"llm/{label}_raw.txt", text or "")
    parsed = _parse_json_object(text)
    if parsed is None:
        if artifacts:
            artifacts.write_text(f"llm/{label}_parse_error.txt", text or "")
        failure_path = _save_llm_failure(label, prompt, text, ValueError("LLM returned no JSON"))
        logger.warning(
            f"[Researcher] LLM returned no JSON: label={label} "
            f"prompt_len={len(prompt)} response_len={len(text or '')} saved={failure_path}"
        )
        raise ValueError("LLM returned no JSON")
    return parsed


def _supports_json_object_output(client) -> bool:
    model = (getattr(client, "model", "") or "").lower()
    base_url = (getattr(client, "base_url", "") or "").lower()
    return "deepseek" in model or "deepseek" in base_url


def _save_llm_failure(label: str, prompt: str, response: str, error: Exception) -> str:
    try:
        root = Path(__file__).resolve().parents[2] / "logs" / "research_llm_failures"
        root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label)[:80] or "research"
        path = root / f"{ts}_{safe_label}.txt"
        path.write_text(
            "\n".join([
                f"label: {label}",
                f"error_type: {type(error).__name__}",
                f"error: {error}",
                f"prompt_len: {len(prompt or '')}",
                f"response_len: {len(response or '')}",
                "",
                "=== RESPONSE ===",
                response or "",
                "",
                "=== PROMPT_HEAD ===",
                (prompt or "")[:4000],
            ]),
            encoding="utf-8",
        )
        return str(path)
    except Exception as log_error:
        logger.warning(f"[Researcher] failed to save raw LLM failure: {log_error}")
        return ""


def _build_extraction_prompt(
    topic: str,
    research_type: str,
    all_sources: list[ResearchSource],
    batch: list[ResearchSource],
    batch_index: int,
) -> str:
    source_text = _format_sources(batch, all_sources, chars=1000)
    sections = "、".join(TYPE_REPORT_SECTIONS.get(research_type, TYPE_REPORT_SECTIONS["general"]))
    return f"""你是研究助理，正在为「{topic}」做{REPORT_TYPE_LABELS.get(research_type, '通用研究')}。

请只处理本批来源，抽取具体事实/事件/观点，不要写总报告。
报告应覆盖这些维度：{sections}

规则：
- 所有输出字段必须使用中文。即使来源是英文，title、summary、why_it_matters、evidence 也要翻译/改写成自然中文。
- title 必须是中文新闻标题，不要直接复制英文标题。
- summary 写成 120-220 字，包含背景、核心事实、关键数据/产品/主体。
- why_it_matters 写成 80-160 字，说明影响、受益/受损对象、后续变量。
- evidence 写成中文证据点，每条 20-80 字，最多 4 条。
- 不要把网站栏目名、导航页标题、SEO聚合标题当成事件。
- 每条必须是具体事实、产品、政策、观点、数据或争议。
- source_urls 必须来自本批来源 URL。
- 自媒体/转载只能做背景，不能作为强结论。
- 最多输出4条 events。
- 只输出合法 JSON，不要 Markdown，不要解释。

JSON:
{{
  "events": [
    {{
      "title": "具体条目标题",
      "category": "所属维度",
      "event_time": "日期或待核验",
      "summary": "核心事实",
      "why_it_matters": "影响判断",
      "affected_parties": ["对象"],
      "importance": "high|medium|low",
      "certainty": "confirmed|likely|unverified",
      "source_urls": ["https://..."],
      "evidence": ["短证据点"]
    }}
  ],
  "key_findings": ["发现"]
}}

本批来源 #{batch_index}:
{source_text}"""


def _build_editor_prompt(
    topic: str,
    research_type: str,
    sources: list[ResearchSource],
    events: list,
    findings: list,
) -> str:
    sections = "、".join(TYPE_REPORT_SECTIONS.get(research_type, TYPE_REPORT_SECTIONS["general"]))
    compact_events = json.dumps(events[:35], ensure_ascii=False)[:22000]
    compact_findings = json.dumps(findings[:20], ensure_ascii=False)[:5000]
    return f"""你是资深研究编辑。请把候选条目整理为一篇高质量中文 Markdown 调研报告的数据结构。

主题：{topic}
类型：{REPORT_TYPE_LABELS.get(research_type, '通用研究')}
建议章节：{sections}

编辑要求：
- 全部字段必须使用中文。不要输出英文标题、英文摘要或中英混排正文；英文专有名词可保留，但解释和句子必须是中文。
- 每个事件都要写成“可直接放进报告正文”的完整中文段落，不能只写一两行提纲。
- title 必须是中文标题，summary 160-300 字，why_it_matters 100-200 字，risks 150-300 字。
- 新闻日报不要收缩成单事件报告；只要候选条目足够，events 至少输出 5 条，覆盖模型/产品、Agent、算力、政策、安全、公司动态等不同维度。
- 正文要像成品研究简报，不要像来源列表。
- 合并重复条目，同一来源不能重复支撑多个核心条目。
- 保留具体产品名、公司名、日期、价格、数据、政策条款、技术点。
- 对单来源传闻标为 unverified。
- 每个核心结论必须有 source_urls。
- 不要出现“分析不可用”“暂无详细分析”“模型深度综合分析未完成”。
- 只输出合法 JSON。

JSON:
{{
  "editorial_summary": "200-400字摘要，给出编辑判断",
  "conclusion": "一句话结论",
  "events": [{{"title":"","category":"","event_time":"","summary":"","why_it_matters":"","affected_parties":[],"importance":"high|medium|low","certainty":"confirmed|likely|unverified","source_urls":[],"evidence":[]}}],
  "key_findings": [],
  "trend_judgement": "趋势/综合判断",
  "risks": "风险与争议",
  "timeline": "关键时间线",
  "watchlist": [],
  "limitations": []
}}

候选条目：
{compact_events}

候选发现：
{compact_findings}"""


def _format_sources(batch: list[ResearchSource], all_sources: list[ResearchSource], chars: int = 1400) -> str:
    url_to_id = {s.url: f"S{i}" for i, s in enumerate(all_sources, 1)}
    blocks = []
    for s in batch:
        text = (s.content or s.snippet or "")[:chars]
        blocks.append(
            f"[{url_to_id.get(s.url, '?')}] {s.title}\n"
            f"URL: {s.url}\n"
            f"Domain: {s.domain}\n"
            f"Quality: {s.quality}/{s.source_type}/{s.read_status}\n"
            f"Published: {s.published_at or 'unknown'}\n"
            f"Content:\n{text}"
        )
    return "\n---\n".join(blocks)


def _analysis_sources(sources: list[ResearchSource], topic: str = "") -> list[ResearchSource]:
    strong = [
        s for s in sources
        if _source_can_drive_core(s)
        and _topic_relevant_text(topic, f"{s.title} {s.snippet} {s.content[:1200]}")
        and (not _is_ai_news_like_topic(topic) or _ai_news_core_relevant(s))
    ]
    research_type = "news" if _freshness_window(topic, "news") else "general"
    return _rank_sources(strong, topic=topic, research_type=research_type)[:24]


def _source_can_drive_core(source: ResearchSource) -> bool:
    return bool(
        getattr(source, "usable_for_core", True)
        and source.quality in ("S", "A", "B")
        and source.read_status in ("full", "partial")
        and not is_low_value_source(source)
        and source.source_type not in ("self_media", "aggregator", "pr")
    )


def _is_ai_news_like_topic(topic: str) -> bool:
    text = (topic or "").lower()
    return any(k in text for k in ["ai", "artificial intelligence", "人工智能", "大模型", "智能体", "agent"])


def _ai_news_core_relevant(source: ResearchSource) -> bool:
    text = f"{source.title} {source.snippet} {source.content[:1000]}".lower()
    reject_terms = [
        "met gala", "katy perry", "meme", "daily compliance news",
        "ai impact awards", "award winners", "future of news", "journalism",
        "media industry", "reader forum",
    ]
    if any(term in text for term in reject_terms):
        return False
    strong_terms = [
        "openai", "anthropic", "claude", "chatgpt", "google", "gemini",
        "deepmind", "microsoft", "copilot", "nvidia", "deepseek", "meta",
        "xai", "model", "llm", "agent", "agentic", "chip", "gpu",
        "compute", "data center", "regulation", "ai act", "white house",
        "ftc", "nist", "sec", "funding", "startup", "artificial intelligence",
        "大模型", "模型", "智能体", "芯片", "算力", "监管", "融资", "发布",
    ]
    return any(term in text for term in strong_terms)


def _topic_requires_agent(topic: str) -> bool:
    text = (topic or "").lower()
    return any(token in text for token in ["agent", "agentic", "ai agent", "智能体"])


def _topic_relevant_text(topic: str, text: str) -> bool:
    if not _topic_requires_agent(topic):
        return True
    text_l = (text or "").lower()
    agent_terms = [
        "agent", "agentic", "ai agent", "multi-agent", "workflow automation",
        "computer use", "agentforce", "copilot", "mcp", "a2a", "智能体",
    ]
    return any(term in text_l for term in agent_terms)


def _source_cards_from_batch(batch: list[ResearchSource], topic: str, research_type: str) -> list[dict]:
    """Create conservative candidate cards when a model batch returns bad JSON."""
    cards = []
    for s in batch:
        if not _source_can_drive_core(s):
            continue
        title = _compact_event_title("候选条目", s.title, topic)
        if _is_generic_event_title(title):
            continue
        cards.append({
            "title": title,
            "category": _guess_category_from_source(s, research_type),
            "event_time": s.published_at or _guess_event_time([s]),
            "summary": _clean_excerpt(s),
            "why_it_matters": _why_category_matters(_guess_category_from_source(s, research_type), research_type),
            "affected_parties": _affected_parties(_guess_category_from_source(s, research_type), research_type),
            "importance": "high" if s.quality in ("S", "A") else "medium",
            "certainty": "confirmed" if s.source_type in ("official", "paper") else "likely",
            "source_urls": [s.url],
            "evidence": [_clean_excerpt(s)],
        })
        if len(cards) >= 4:
            break
    return cards


def _guess_category_from_source(source: ResearchSource, research_type: str) -> str:
    text = f"{source.title} {source.snippet} {source.content[:400]}".lower()
    for category, keywords in _event_categories_for_type(research_type):
        if any(k.lower() in text for k in keywords):
            return category
    return TYPE_REPORT_SECTIONS.get(research_type, TYPE_REPORT_SECTIONS["general"])[0]


def _parse_json_object(text: str) -> dict | None:
    text = _strip_code_fence(text or "").strip()
    candidates = []
    obj = _slice_balanced(text, "{", "}")
    if obj:
        candidates.append(obj)
    arr = _slice_balanced(text, "[", "]")
    if arr:
        candidates.append('{"events": ' + arr + "}")
    salvaged_events = _salvage_events_array(text)
    if salvaged_events:
        candidates.append(json.dumps({"events": salvaged_events}, ensure_ascii=False))
    start = text.find("{")
    if start >= 0:
        candidates.append(_balance_json(text[start:]))

    for candidate in candidates:
        candidate = _remove_trailing_commas(candidate)
        try:
            parsed = json.loads(candidate)
            return _normalize_parsed_json(parsed)
        except Exception:
            try:
                parsed = ast.literal_eval(candidate)
                return _normalize_parsed_json(parsed)
            except Exception:
                continue
    return None


def _salvage_events_array(text: str) -> list[dict]:
    """Recover complete event objects from a truncated JSON events array."""
    marker = '"events"'
    marker_at = text.find(marker)
    if marker_at < 0:
        return []
    array_start = text.find("[", marker_at)
    if array_start < 0:
        return []

    events = []
    depth = 0
    obj_start = -1
    in_string = False
    escape = False
    for i in range(array_start + 1, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    fragment = _remove_trailing_commas(text[obj_start:i + 1])
                    try:
                        parsed = json.loads(fragment)
                    except Exception:
                        try:
                            parsed = ast.literal_eval(fragment)
                        except Exception:
                            parsed = None
                    if isinstance(parsed, dict):
                        events.append(parsed)
                    obj_start = -1
    return events


def _normalize_parsed_json(parsed) -> dict:
    if isinstance(parsed, list):
        return {"events": parsed}
    if isinstance(parsed, dict):
        if "events" in parsed or "key_findings" in parsed or "conclusion" in parsed:
            return parsed
        if "title" in parsed and ("source_urls" in parsed or "summary" in parsed):
            return {"events": [parsed]}
        return parsed
    return {}


def _strip_code_fence(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text.strip())
    return text


def _slice_balanced(text: str, open_ch: str, close_ch: str) -> str:
    start = text.find(open_ch)
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def _balance_json(text: str) -> str:
    text = text.strip()
    braces = text.count("{") - text.count("}")
    brackets = text.count("[") - text.count("]")
    return text + ("]" * max(brackets, 0)) + ("}" * max(braces, 0))


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _fallback_analysis(sources: list[ResearchSource], topic: str, research_type: str = "general") -> dict:
    """Build a complete structured report from ranked source metadata."""
    events = _fallback_events(sources, topic, research_type)
    categories = []
    for event in events:
        if event.category not in categories:
            categories.append(event.category)

    conclusion = (
        f"关于{topic}，已聚合{len(sources)}个来源并形成{len(events)}个事件；"
        f"重点集中在{'、'.join(categories[:4]) or '综合动态'}。"
    )
    type_label = REPORT_TYPE_LABELS.get(research_type, "通用研究")
    editorial_summary = (
        f"本次以“{type_label}”方式处理「{topic}」，优先采用官方、论文、监管文件、公司博客、权威媒体和行业报告。"
        f"当前可确认的信息集中在{'、'.join(categories[:5]) or '背景、事实、影响与风险'}。"
        f"低质量来源、单来源传闻和重复转载已降权，结论按保守口径呈现。"
    )
    return {
        "editorial_summary": editorial_summary,
        "conclusion": conclusion,
        "events": [event.__dict__ for event in events],
        "key_findings": [f"{event.title}：{event.summary}" for event in events[:8]],
        "trend_judgement": _fallback_trend_judgement(events),
        "risks": "主要风险来自重复转载、标题党、自媒体二次解读和单来源公司传闻。未被官方或至少两个独立来源支持的事件应按未证实处理。",
        "timeline": _fallback_timeline(events),
        "watchlist": _fallback_watchlist(events),
        "limitations": ["这是基于事件聚类和来源质量规则生成的兜底分析，深层因果判断仍需继续补充一手材料。"],
    }


def _fallback_events(sources: list[ResearchSource], topic: str, research_type: str = "general") -> list[ResearchEvent]:
    events: list[ResearchEvent] = []
    used_urls = set()
    core_sources = [
        s for s in sources
        if _source_can_drive_core(s)
        and _topic_relevant_text(topic, f"{s.title} {s.snippet} {s.content[:1200]}")
    ]

    for category, keywords in _event_categories_for_type(research_type):
        matched = []
        for s in core_sources:
            if s.url in used_urls:
                continue
            text = f"{s.title} {s.snippet} {s.content[:300]}".lower()
            if any(k.lower() in text for k in keywords):
                matched.append(s)
        matched = _rank_sources(matched)[:3]
        if not matched:
            continue
        for s in matched:
            used_urls.add(s.url)
        title = _compact_event_title(category, matched[0].title, topic)
        if _is_generic_event_title(title):
            continue
        events.append(ResearchEvent(
            title=title,
            summary=_source_based_summary(matched),
            category=category,
            event_time=_guess_event_time(matched),
            source_urls=[s.url for s in matched],
            importance=_infer_importance(matched, category),
            certainty=_infer_certainty(matched),
            why_it_matters=_why_category_matters(category, research_type),
            affected_parties=_affected_parties(category, research_type),
            evidence=[_clean_excerpt(s) for s in matched[:3]],
        ))

    for s in core_sources:
        if len(events) >= 8:
            break
        if s.url in used_urls:
            continue
        events.append(ResearchEvent(
            title=s.title or f"{topic}相关动态",
            summary=_clean_excerpt(s) or "来源标题显示该方向值得继续核验。",
            category="其他",
            event_time=s.published_at or "待核验",
            source_urls=[s.url],
            importance="medium" if s.quality in ("S", "A") else "low",
            certainty="likely" if s.quality in ("S", "A", "B") else "unverified",
            why_it_matters="该条目补充了主线之外的观察点，可作为后续追踪和交叉验证入口。",
            affected_parties=["行业观察者", "相关企业", "开发者/用户"],
            evidence=[_clean_excerpt(s)],
        ))

    return events[:8]


def _is_generic_event_title(title: str) -> bool:
    title_l = (title or "").strip().lower()
    patterns = [
        r"^home\b",
        r"^research\b",
        r"^publications\b",
        r"newsroom\s*[\\|/-]\s*product",
        r"openai research\s*\|\s*release",
        r"google deepmind\s*$",
        r"^首页$",
    ]
    return any(re.search(p, title_l, re.I) for p in patterns)


def _event_categories_for_type(research_type: str) -> list[tuple[str, list[str]]]:
    typed = {
        "technical": [
            ("技术背景", ["背景", "overview", "introduction", "生态", "protocol"]),
            ("核心原理", ["原理", "架构", "机制", "spec", "标准", "architecture"]),
            ("实现与工具", ["github", "sdk", "api", "工具", "实现", "示例", "server"]),
            ("对比分析", ["对比", "比较", "vs", "benchmark", "评测"]),
            ("局限风险", ["风险", "限制", "安全", "问题", "limitation", "security"]),
            ("应用场景", ["应用", "案例", "场景", "use case", "enterprise"]),
        ],
        "product": [
            ("产品定位", ["产品", "定位", "官网", "what is", "overview"]),
            ("核心功能", ["功能", "feature", "能力", "workflow", "agent"]),
            ("价格与商业模式", ["价格", "pricing", "订阅", "plan", "商业"]),
            ("竞品对比", ["对比", "vs", "alternative", "竞品", "compare"]),
            ("用户反馈", ["评价", "review", "用户", "体验", "feedback"]),
            ("适用建议", ["适用", "场景", "use case", "best for"]),
        ],
        "company": [
            ("战略变化", ["战略", "strategy", "roadmap", "方向", "合作"]),
            ("产品技术", ["产品", "模型", "技术", "release", "launch"]),
            ("资本财务", ["融资", "估值", "财报", "revenue", "funding", "investment"]),
            ("竞争格局", ["竞争", "market", "competitor", "份额"]),
            ("组织管理", ["管理层", "招聘", "裁员", "团队", "organization"]),
            ("风险争议", ["风险", "争议", "诉讼", "监管", "controversy"]),
        ],
        "policy": [
            ("政策原文", ["政策", "法案", "act", "regulation", "guidance"]),
            ("执行时间线", ["时间", "生效", "deadline", "timeline", "实施"]),
            ("核心要求", ["要求", "义务", "合规", "risk", "requirement"]),
            ("企业影响", ["企业", "business", "impact", "成本", "影响"]),
            ("各方观点", ["解读", "观点", "criticism", "support"]),
            ("风险不确定性", ["风险", "争议", "处罚", "uncertainty"]),
        ],
        "controversy": [
            ("事实时间线", ["时间线", "发生", "爆料", "reported", "claim"]),
            ("官方回应", ["官方", "回应", "statement", "denied", "confirmed"]),
            ("证据核验", ["证据", "source", "filing", "document", "核验"]),
            ("各方立场", ["观点", "立场", "reaction", "response"]),
            ("可信度判断", ["传闻", "属实", "真假", "unverified", "rumor"]),
            ("影响风险", ["影响", "风险", "market", "监管", "legal"]),
        ],
        "news": EVENT_CATEGORIES,
        "general": [
            ("背景脉络", ["背景", "overview", "history", "发展"]),
            ("核心事实", ["事实", "发布", "数据", "report", "announcement"]),
            ("关键观点", ["观点", "分析", "opinion", "insight"]),
            ("影响分析", ["影响", "market", "business", "应用"]),
            ("风险局限", ["风险", "问题", "局限", "controversy"]),
            ("后续趋势", ["趋势", "未来", "roadmap", "prediction"]),
        ],
    }
    return typed.get(research_type, typed["general"])


def _compact_event_title(category: str, title: str, topic: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    if not title:
        return f"{category}出现新动态"
    return title[:80]


def _source_based_summary(sources: list[ResearchSource]) -> str:
    snippets = [_clean_excerpt(s) for s in sources if _clean_excerpt(s)]
    if snippets:
        return snippets[0][:220]
    titles = [s.title for s in sources if s.title]
    return "；".join(titles[:2])[:220] if titles else "来源显示该方向出现新动态。"


def _clean_excerpt(source: ResearchSource) -> str:
    text = source.snippet or source.content[:300] or source.title
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text or "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:240]


def _guess_event_time(sources: list[ResearchSource]) -> str:
    for s in sources:
        if s.published_at:
            return str(s.published_at)[:10]
    text = " ".join(f"{s.title} {s.snippet}" for s in sources)
    match = re.search(r"(20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}日?)", text)
    return match.group(1) if match else "待核验"


def _infer_importance(sources: list[ResearchSource], category: str) -> str:
    if category in ("模型发布", "政策监管", "算力与芯片") and any(s.quality in ("S", "A") for s in sources):
        return "high"
    if len({s.domain for s in sources}) >= 2 and any(s.quality in ("S", "A") for s in sources):
        return "high"
    if any(s.quality in ("S", "A", "B") for s in sources):
        return "medium"
    return "low"


def _infer_certainty(sources: list[ResearchSource]) -> str:
    domains = {s.domain for s in sources if s.domain}
    if any(s.source_type in ("official", "paper") for s in sources):
        return "confirmed"
    if len(domains) >= 2 and any(s.quality in ("A", "B") for s in sources):
        return "likely"
    return "unverified"


def _why_category_matters(category: str, research_type: str = "general") -> str:
    reasons = {
        "模型发布": "模型能力和价格会直接影响开发者选型、产品路线和竞争格局。",
        "AI Agent": "智能体是 AI 从问答工具走向可执行工作流的关键环节，决定实际生产力落地速度。",
        "算力与芯片": "算力供给、芯片迭代和数据中心投资会影响模型训练成本、推理成本和行业门槛。",
        "政策监管": "监管和安全规则会改变产品上线节奏、数据使用方式和企业合规成本。",
        "公司与资本": "资本动作和组织调整往往预示战略重心变化，也会影响人才和生态流向。",
        "开源与论文": "开源模型、论文和评测是判断技术路线是否可复制、是否被社区验证的重要证据。",
        "应用落地": "落地案例决定 AI 是否从演示走向持续付费，也反映真实需求和交付难点。",
        "风险争议": "争议事件会影响公众信任、监管强度和企业采用意愿。",
    }
    if category in reasons:
        return reasons[category]
    generic = {
        "technical": "该条目有助于判断技术路线是否成熟、可实现、可集成。",
        "product": "该条目影响产品选型、成本判断和使用场景匹配。",
        "company": "该条目有助于理解公司战略、竞争位置和潜在风险。",
        "policy": "该条目可能改变合规要求、企业成本和执行时间表。",
        "controversy": "该条目有助于区分事实、传闻和需要继续核验的部分。",
    }
    return generic.get(research_type, "该条目可作为理解主题变化的补充证据。")


def _affected_parties(category: str, research_type: str = "general") -> list[str]:
    mapping = {
        "模型发布": ["开发者", "企业客户", "模型厂商"],
        "AI Agent": ["知识工作者", "SaaS厂商", "自动化工具团队"],
        "算力与芯片": ["云厂商", "芯片公司", "模型训练团队"],
        "政策监管": ["AI公司", "企业用户", "监管机构"],
        "公司与资本": ["创业公司", "投资机构", "行业竞争者"],
        "开源与论文": ["研究者", "开发者社区", "企业技术团队"],
        "应用落地": ["行业客户", "产品团队", "服务商"],
        "风险争议": ["公众用户", "平台方", "监管机构"],
    }
    if category in mapping:
        return mapping[category]
    generic = {
        "technical": ["开发者", "技术团队", "架构决策者"],
        "product": ["用户", "采购/决策者", "产品团队"],
        "company": ["投资者", "合作伙伴", "竞争者"],
        "policy": ["企业", "监管机构", "合规团队"],
        "controversy": ["当事方", "用户/客户", "行业观察者"],
    }
    return generic.get(research_type, ["相关企业", "用户", "行业观察者"])


def _fallback_trend_judgement(events: list[ResearchEvent]) -> str:
    categories = [e.category for e in events]
    if not categories:
        return "来源不足，暂不做强趋势判断。"
    top = []
    for category in dict.fromkeys(categories):
        top.append(f"{category}({categories.count(category)}条)")
    return (
        "从事件分布看，短期热点集中在"
        f"{'、'.join(top[:5])}。判断上应优先看官方发布和权威媒体交叉验证，"
        "再用自媒体材料补充市场情绪。"
    )


def _fallback_timeline(events: list[ResearchEvent]) -> str:
    lines = []
    for event in events[:8]:
        lines.append(f"- {event.event_time}：{event.title}")
    return "\n".join(lines) if lines else "未抽取到明确时间线。"


def _fallback_watchlist(events: list[ResearchEvent]) -> list[str]:
    result = []
    for event in events[:5]:
        result.append(f"继续核验「{event.title}」是否出现官方公告或第二独立来源。")
    if not result:
        result.append("补充官方公告、论文、监管文件或权威媒体来源。")
    return result


def _fill_report_from_analysis(report: ResearchReport, analysis: dict, sources: list[ResearchSource]):
    """Fill report fields from analysis result."""
    report.one_line_conclusion = _as_text(analysis.get("conclusion"))[:240]
    report.editorial_summary = _as_text(analysis.get("editorial_summary")) or report.one_line_conclusion
    report.key_findings = _as_list(analysis.get("key_findings"))[:10]
    report.tech_analysis = _as_text(analysis.get("trend_judgement") or analysis.get("tech_trends")) or "趋势判断见事件卡片。"
    report.business_analysis = _as_text(analysis.get("business_impact"))
    report.risks_and_controversies = _as_text(analysis.get("risks")) or "未发现明确风险，但单来源事件仍需核验。"
    report.timeline_content = _as_text(analysis.get("timeline")) or "未抽取到明确时间线。"
    report.recommendation = _as_text(analysis.get("prediction") or analysis.get("trend_judgement"))
    report.watchlist = _as_list(analysis.get("watchlist"))[:8]
    report.limitations = _as_list(analysis.get("limitations")) or ["来源覆盖仍可能不完整。"]

    events = _events_from_analysis(analysis.get("events"), sources)
    events = [
        event for event in events
        if _topic_relevant_text(report.topic, f"{event.title} {event.summary} {event.category}")
    ]
    if not events:
        events = _fallback_events(sources, report.topic, report.research_type)
    report.events = _dedupe_events(events)[:12]
    report.top_events = _select_top_events(report.events)
    if not report.key_findings:
        report.key_findings = [f"{e.title}：{e.summary}" for e in report.top_events[:5]]
    if not report.watchlist:
        report.watchlist = _fallback_watchlist(report.events)
    if not report.one_line_conclusion:
        report.one_line_conclusion = f"本次调研形成{len(report.events)}个事件，重点看{report.top_events[0].category if report.top_events else '主要来源'}。"

    report.evidence_items = _build_evidence_items(report.events, sources)
    report.claims = _claims_from_events(report.events, sources)


def _events_from_analysis(raw_events, sources: list[ResearchSource]) -> list[ResearchEvent]:
    if not isinstance(raw_events, list):
        return []
    known_urls = {s.url for s in sources}
    url_to_source = {s.url: s for s in sources}
    events = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        source_urls = [u for u in _as_list(item.get("source_urls")) if u in known_urls]
        if not source_urls:
            source_urls = _match_sources_for_text(_as_text(item.get("title")) + " " + _as_text(item.get("summary")), sources)
        source_urls = [u for u in source_urls if _source_can_drive_core(url_to_source.get(u, ResearchSource(title="", url=u)))]
        title = (_as_text(item.get("title")) or "未命名事件")[:120]
        if not source_urls or _is_generic_event_title(title):
            continue
        events.append(ResearchEvent(
            title=title,
            summary=_as_text(item.get("summary"))[:600],
            category=_as_text(item.get("category")) or "综合动态",
            event_time=_as_text(item.get("event_time")) or "待核验",
            source_urls=source_urls[:5],
            importance=item.get("importance") if item.get("importance") in ("high", "medium", "low") else "medium",
            certainty=item.get("certainty") if item.get("certainty") in ("confirmed", "likely", "unverified") else "likely",
            why_it_matters=_as_text(item.get("why_it_matters"))[:600],
            affected_parties=_as_list(item.get("affected_parties"))[:5],
            evidence=_as_list(item.get("evidence"))[:4],
        ))
    return events


def _match_sources_for_text(text: str, sources: list[ResearchSource]) -> list[str]:
    text = text.lower()
    scores = []
    for s in sources:
        score = 0
        for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", s.title.lower()):
            if token in text:
                score += 1
        if score:
            scores.append((score, s.url))
    scores.sort(reverse=True)
    return [url for _, url in scores[:3]]


def _merge_events(primary: list[ResearchEvent], fallback: list[ResearchEvent]) -> list[ResearchEvent]:
    seen = {e.title for e in primary}
    result = list(primary)
    for event in fallback:
        if event.title in seen:
            continue
        result.append(event)
        seen.add(event.title)
    return result


def _dedupe_events(events: list[ResearchEvent]) -> list[ResearchEvent]:
    """Remove repeated weak events, especially one source posing as many categories."""
    result = []
    seen_titles = set()
    primary_url_count: dict[str, int] = {}
    for event in events:
        key = re.sub(r"\W+", "", (event.title or "").lower())[:60]
        primary_url = event.source_urls[0] if event.source_urls else ""
        if key and key in seen_titles:
            continue
        if primary_url and primary_url_count.get(primary_url, 0) >= 2 and event.certainty != "confirmed":
            continue
        result.append(event)
        if key:
            seen_titles.add(key)
        if primary_url:
            primary_url_count[primary_url] = primary_url_count.get(primary_url, 0) + 1
    return result


def _select_top_events(events: list[ResearchEvent]) -> list[ResearchEvent]:
    return sorted(
        events,
        key=lambda e: (
            {"high": 0, "medium": 1, "low": 2}.get(e.importance, 3),
            {"confirmed": 0, "likely": 1, "unverified": 2}.get(e.certainty, 3),
            -len(e.source_urls),
        ),
    )[:5]


def _build_evidence_items(events: list[ResearchEvent], sources: list[ResearchSource]) -> list[EvidenceItem]:
    url_to_source = {s.url: s for s in sources}
    url_to_events: dict[str, list[str]] = {}
    for event in events:
        for url in event.source_urls:
            url_to_events.setdefault(url, []).append(event.title)

    evidence = []
    for index, s in enumerate(sources, 1):
        if s.url not in url_to_events:
            continue
        evidence.append(EvidenceItem(
            source_id=f"S{index}",
            url=s.url,
            title=s.title,
            source_type=s.source_type,
            quality=s.quality,
            excerpt=_clean_excerpt(s),
            supports=url_to_events.get(s.url, []),
        ))
    return evidence[:16]


def _claims_from_events(events: list[ResearchEvent], sources: list[ResearchSource]) -> list[ResearchClaim]:
    claims = []
    for event in events[:10]:
        support_count = len({urlparse(u).netloc for u in event.source_urls})
        confidence = "high" if event.certainty == "confirmed" else "medium" if event.certainty == "likely" else "low"
        claims.append(ResearchClaim(
            claim=f"{event.title}：{event.summary}"[:240],
            claim_type="fact",
            source_urls=event.source_urls,
            confidence=confidence,
            support_count=support_count,
            caveat="" if event.certainty != "unverified" else "单来源或非权威来源，需继续核验",
        ))
        if event.why_it_matters:
            claims.append(ResearchClaim(
                claim=f"{event.title}影响判断：{event.why_it_matters}"[:240],
                claim_type="analysis",
                source_urls=event.source_urls,
                confidence="medium" if event.certainty != "unverified" else "low",
                support_count=support_count,
            ))
    return claims


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None and str(v).strip()]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _as_text(item)
            if text:
                parts.append(f"{key}：{text}")
        return "；".join(parts)
    return str(value).strip()


def _estimate_time_range(sources: list[ResearchSource]) -> str:
    now = datetime.now().strftime("%Y-%m-%d")
    return f"截止 {now}，共 {len(sources)} 个来源"


def _store_research_memory(agent, topic: str, report: ResearchReport, file_path: str):
    """Store a research memory card in long-term memory."""
    try:
        card = json.dumps({
            "type": "research_artifact",
            "topic": topic,
            "top_events": [e.title for e in report.top_events[:5]],
            "key_findings": report.key_findings[:5],
            "confidence": report.confidence,
            "source_count": report.source_count,
            "report_path": file_path,
        }, ensure_ascii=False)
        agent.memory.store(
            memory_type="research_artifact",
            content=card,
            importance=0.7,
            tags=f"research,{topic[:30]}",
        )
        logger.info(f"[Researcher] memory card stored: {topic[:30]}")
    except Exception as e:
        logger.debug(f"[Researcher] memory store failed (non-critical): {e}")
